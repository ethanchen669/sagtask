# SagTask 高效测试方案

## 背景与挑战

SagTask 作为 Hermes Agent 的 standalone 插件运行，测试面临以下挑战：

1. **插件依赖宿主环境** — `register(ctx)` 需要 Hermes 提供的 `PluginContext` 对象
2. **涉及外部系统** — Git 操作、GitHub API（`gh` CLI）
3. **文件系统状态** — 每个 task 有独立目录树 + JSON 状态文件
4. **跨会话恢复** — pause/resume 依赖持久化的 `.active_task` 标记
5. **当前开发流程低效** — 修改代码 → 运行 `dev-install.sh` → 重启 gateway → 手动验证

---

## 测试分层架构

```
┌─────────────────────────────────────────────────────┐
│ Layer 4: E2E Integration (with real Hermes)         │  ← 偶尔运行
├─────────────────────────────────────────────────────┤
│ Layer 3: Plugin Registration Test                   │  ← CI 中运行
├─────────────────────────────────────────────────────┤
│ Layer 2: Tool Handler Integration Tests             │  ← 每次修改后运行
├─────────────────────────────────────────────────────┤
│ Layer 1: Unit Tests (pure logic, no I/O)            │  ← 每次保存后运行
└─────────────────────────────────────────────────────┘
```

---

## Layer 1: 单元测试（纯逻辑，无 I/O）

### 目标

测试所有不依赖文件系统或 subprocess 的纯逻辑函数。

### 覆盖范围

- `_get_current_phase()` / `_get_current_step()` — 状态解析
- Schema 验证逻辑（如果添加输入验证）
- 分支名生成逻辑
- Artifact summary 截断逻辑
- Cross-pollination context 构建

### 示例

```python
# tests/test_state_helpers.py
import pytest
from sagtask import SagTaskPlugin


class TestGetCurrentPhase:
    def test_returns_phase_name_when_found(self):
        state = {
            "current_phase_id": "phase-2",
            "phases": [
                {"id": "phase-1", "name": "设计"},
                {"id": "phase-2", "name": "实现"},
            ],
        }
        assert SagTaskPlugin._get_current_phase(state) == "实现"

    def test_returns_dash_when_phases_empty(self):
        state = {"current_phase_id": "phase-1", "phases": []}
        assert SagTaskPlugin._get_current_phase(state) == "phase-1"

    def test_returns_id_when_name_missing(self):
        state = {
            "current_phase_id": "phase-1",
            "phases": [{"id": "phase-1", "steps": []}],
        }
        assert SagTaskPlugin._get_current_phase(state) == "phase-1"


class TestGetCurrentStep:
    def test_returns_step_name(self):
        state = {
            "current_phase_id": "phase-1",
            "current_step_id": "step-2",
            "phases": [
                {
                    "id": "phase-1",
                    "steps": [
                        {"id": "step-1", "name": "设计"},
                        {"id": "step-2", "name": "编码"},
                    ],
                }
            ],
        }
        assert SagTaskPlugin._get_current_step(state) == "编码"

    def test_returns_dash_when_no_match(self):
        state = {
            "current_phase_id": "nonexistent",
            "current_step_id": "step-1",
            "phases": [],
        }
        result = SagTaskPlugin._get_current_step(state)
        assert result in ("step-1", "—")
```

### 运行方式

```bash
pytest tests/test_state_helpers.py -v --no-header -q
```

---

## Layer 2: Tool Handler 集成测试（核心层）

### 目标

测试完整的 tool handler 逻辑，使用真实文件系统（`tmp_path`），但 mock 掉 Git/GitHub 操作。

### 关键设计：Mock PluginContext + 隔离文件系统

```python
# tests/conftest.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sagtask


@pytest.fixture
def isolated_sagtask(tmp_path, monkeypatch):
    """Create an isolated SagTaskPlugin with tmp_path as projects_root.
    
    This fixture:
    1. Creates a fresh SagTaskPlugin instance
    2. Points projects_root to tmp_path (no ~/.hermes pollution)
    3. Mocks subprocess calls (git, gh) by default
    4. Resets the global singleton after each test
    """
    # Reset global singleton
    sagtask._sagtask_instance = None

    plugin = sagtask.SagTaskPlugin()
    plugin._hermes_home = tmp_path / "hermes"
    plugin._projects_root = tmp_path / "hermes" / "sag_tasks"
    plugin._projects_root.mkdir(parents=True)

    # Set as global singleton (tool handlers use _get_provider())
    sagtask._sagtask_instance = plugin

    yield plugin

    # Cleanup
    sagtask._sagtask_instance = None


@pytest.fixture
def mock_git(monkeypatch):
    """Mock all subprocess.run calls to simulate git operations."""
    results = {}

    def fake_run(cmd, **kwargs):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd

        # Simulate specific git commands
        if "git init" in cmd_str:
            mock_result.stdout = "Initialized empty Git repository"
        elif "git log" in cmd_str:
            mock_result.stdout = "abc1234 Initial commit\ndef5678 WIP: step-1"
        elif "git rev-list --count" in cmd_str:
            mock_result.stdout = "2"
        elif "git diff --stat" in cmd_str:
            mock_result.stdout = " src/main.py | 10 ++++\n 1 file changed"
        elif "git status --porcelain" in cmd_str:
            mock_result.stdout = ""
        elif "gh repo view" in cmd_str:
            mock_result.returncode = 1  # Repo doesn't exist
        elif "gh repo create" in cmd_str:
            mock_result.stdout = "Created repository"

        # Allow tests to override specific commands
        for pattern, result in results.items():
            if pattern in cmd_str:
                return result

        return mock_result

    monkeypatch.setattr("subprocess.run", fake_run)
    return results  # Tests can modify this dict to customize responses


@pytest.fixture
def sample_phases():
    """Standard test phases with gates."""
    return [
        {
            "id": "phase-1",
            "name": "数据建模",
            "steps": [
                {
                    "id": "step-1",
                    "name": "数据模型设计",
                    "gate": {
                        "id": "gate-1",
                        "question": "数据模型是否满足需求？",
                        "choices": ["Approve", "Reject", "Request Changes"],
                    },
                },
                {"id": "step-2", "name": "数据迁移脚本"},
            ],
        },
        {
            "id": "phase-2",
            "name": "引擎实现",
            "steps": [
                {"id": "step-3", "name": "BOM展开引擎"},
            ],
        },
    ]
```

### 测试用例：完整生命周期

```python
# tests/test_lifecycle.py
import json
import pytest
from sagtask import (
    _handle_sag_task_create,
    _handle_sag_task_status,
    _handle_sag_task_advance,
    _handle_sag_task_pause,
    _handle_sag_task_resume,
    _handle_sag_task_approve,
    _get_provider,
)


class TestTaskCreate:
    def test_create_basic(self, isolated_sagtask, mock_git, sample_phases):
        result = _handle_sag_task_create({
            "sag_task_id": "test-task-1",
            "name": "Test Task",
            "description": "A test task",
            "phases": sample_phases,
        })

        assert result["ok"] is True
        assert result["sag_task_id"] == "test-task-1"
        assert result["status"] == "active"

        # Verify state file was written
        p = _get_provider()
        state_path = p.get_task_state_path("test-task-1")
        assert state_path.exists()

        state = json.loads(state_path.read_text())
        assert state["current_phase_id"] == "phase-1"
        assert state["current_step_id"] == "step-1"

    def test_create_sets_active_task(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "my-task",
            "name": "My Task",
            "phases": sample_phases,
        })

        p = _get_provider()
        assert p._active_task_id == "my-task"

        # Verify marker file
        marker = p._projects_root / ".active_task"
        assert marker.read_text().strip() == "my-task"


class TestTaskAdvance:
    def test_advance_to_next_step(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "adv-task",
            "name": "Advance Test",
            "phases": sample_phases,
        })

        result = _handle_sag_task_advance({"sag_task_id": "adv-task"})

        assert result["ok"] is True
        assert result["current_phase"] == "phase-1"
        assert result["current_step"] == "step-2"

    def test_advance_to_next_phase(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "adv-task",
            "name": "Advance Test",
            "phases": sample_phases,
        })

        # Advance step-1 → step-2
        _handle_sag_task_advance({"sag_task_id": "adv-task"})
        # Advance step-2 → phase-2/step-3
        result = _handle_sag_task_advance({"sag_task_id": "adv-task"})

        assert result["ok"] is True
        assert result["current_phase"] == "phase-2"
        assert result["current_step"] == "step-3"

    def test_advance_at_end_completes_task(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "adv-task",
            "name": "Advance Test",
            "phases": sample_phases,
        })

        _handle_sag_task_advance({"sag_task_id": "adv-task"})  # step-1 → step-2
        _handle_sag_task_advance({"sag_task_id": "adv-task"})  # step-2 → step-3
        result = _handle_sag_task_advance({"sag_task_id": "adv-task"})  # step-3 → done

        assert result["ok"] is True
        assert result["status"] == "completed"


class TestTaskPauseResume:
    def test_pause_and_resume(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "pr-task",
            "name": "Pause Resume Test",
            "phases": sample_phases,
        })

        # Pause
        pause_result = _handle_sag_task_pause({
            "sag_task_id": "pr-task",
            "reason": "等待审批",
        })
        assert pause_result["ok"] is True
        assert pause_result["status"] == "paused"

        # Verify state is paused
        p = _get_provider()
        state = p.load_task_state("pr-task")
        assert state["status"] == "paused"

        # Resume
        resume_result = _handle_sag_task_resume({"sag_task_id": "pr-task"})
        assert resume_result["ok"] is True
        assert resume_result["status"] == "active"


class TestTaskApprove:
    def test_approve_gate_advances(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "gate-task",
            "name": "Gate Test",
            "phases": sample_phases,
        })

        # Set a pending gate
        p = _get_provider()
        state = p.load_task_state("gate-task")
        state["pending_gates"] = ["gate-1"]
        p.save_task_state("gate-task", state)

        result = _handle_sag_task_approve({
            "sag_task_id": "gate-task",
            "gate_id": "gate-1",
            "decision": "Approve",
            "comment": "Looks good",
        })

        assert result["ok"] is True
        # Approve should trigger advance
        assert result["current_step"] == "step-2"
```

### 运行方式

```bash
# 快速运行（日常开发）
pytest tests/test_lifecycle.py -v -x --tb=short

# 带覆盖率
pytest tests/ --cov=src/sagtask --cov-report=term-missing --cov-fail-under=80
```

---

## Layer 3: 插件注册测试

### 目标

验证 SagTask 能在 Hermes 的 PluginManager 中正确加载和注册。

### 方式：复用 Hermes 测试模式

```python
# tests/test_registration.py
import sys
import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock


class TestPluginRegistration:
    """Test that SagTask registers correctly with a mock PluginContext."""

    def test_register_creates_singleton(self, tmp_path, monkeypatch):
        """register(ctx) creates the global SagTaskPlugin instance."""
        import sagtask
        sagtask._sagtask_instance = None  # Reset

        ctx = MagicMock()
        ctx.register_tool = MagicMock()
        ctx.register_hook = MagicMock()

        sagtask.register(ctx)

        assert sagtask._sagtask_instance is not None
        sagtask._sagtask_instance = None  # Cleanup

    def test_register_all_tools(self, tmp_path, monkeypatch):
        """register(ctx) registers all 11 tools."""
        import sagtask
        sagtask._sagtask_instance = None

        ctx = MagicMock()
        registered_tools = []
        ctx.register_tool = lambda **kwargs: registered_tools.append(kwargs["name"])
        ctx.register_hook = MagicMock()

        sagtask.register(ctx)

        expected_tools = [
            "sag_task_create", "sag_task_status", "sag_task_pause",
            "sag_task_resume", "sag_task_advance", "sag_task_approve",
            "sag_task_list", "sag_task_commit", "sag_task_branch",
            "sag_task_git_log", "sag_task_relate",
        ]
        assert sorted(registered_tools) == sorted(expected_tools)
        sagtask._sagtask_instance = None

    def test_register_hooks(self, tmp_path, monkeypatch):
        """register(ctx) registers pre_llm_call and on_session_start hooks."""
        import sagtask
        sagtask._sagtask_instance = None

        ctx = MagicMock()
        registered_hooks = []
        ctx.register_tool = MagicMock()
        ctx.register_hook = lambda name, cb: registered_hooks.append(name)

        sagtask.register(ctx)

        assert "pre_llm_call" in registered_hooks
        assert "on_session_start" in registered_hooks
        sagtask._sagtask_instance = None

    def test_register_idempotent(self):
        """Calling register() twice does not create duplicate instances."""
        import sagtask
        sagtask._sagtask_instance = None

        ctx = MagicMock()
        ctx.register_tool = MagicMock()
        ctx.register_hook = MagicMock()

        sagtask.register(ctx)
        first_instance = sagtask._sagtask_instance

        sagtask.register(ctx)  # Second call
        assert sagtask._sagtask_instance is first_instance

        sagtask._sagtask_instance = None


class TestHermesFull:
    """Test loading SagTask through Hermes PluginManager.
    
    Requires hermes-agent to be importable. Skip if not available.
    """

    @pytest.fixture
    def hermes_env(self, tmp_path, monkeypatch):
        """Set up a minimal Hermes environment pointing at SagTask source."""
        hermes_home = tmp_path / "hermes"
        plugins_dir = hermes_home / "plugins" / "sagtask"
        plugins_dir.mkdir(parents=True)

        # Symlink SagTask source into plugin directory
        src_dir = Path(__file__).parent.parent / "src" / "sagtask"
        for f in src_dir.iterdir():
            (plugins_dir / f.name).write_bytes(f.read_bytes())

        # Enable plugin in config
        config = {"plugins": {"enabled": ["sagtask"]}}
        (hermes_home / "config.yaml").write_text(yaml.safe_dump(config))

        monkeypatch.setenv("HERMES_HOME", str(hermes_home))
        return hermes_home

    @pytest.mark.skipif(
        "hermes_cli" not in sys.modules and not any(
            "hermes" in str(p) for p in sys.path
        ),
        reason="hermes-agent not importable",
    )
    def test_loads_via_plugin_manager(self, hermes_env, monkeypatch):
        """SagTask loads successfully through Hermes PluginManager."""
        from hermes_cli.plugins import PluginManager

        mgr = PluginManager()
        mgr.discover_and_load()

        assert "sagtask" in mgr._plugins
        assert mgr._plugins["sagtask"].enabled
```

---

## Layer 4: E2E 集成测试

### 目标

在真实 Hermes 环境中验证 SagTask 端到端工作。

### 方式：CLI 驱动

```python
# tests/e2e/test_e2e_sagtask.py
import json
import subprocess
import pytest
from pathlib import Path


@pytest.fixture
def hermes_cli():
    """Check if hermes CLI is available."""
    result = subprocess.run(["hermes", "--version"], capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip("hermes CLI not available")
    return "hermes"


@pytest.mark.e2e
class TestE2ESagTask:
    """End-to-end tests using real Hermes CLI.
    
    These tests are slow and require:
    - hermes CLI installed and configured
    - sagtask plugin enabled
    - Network access (for GitHub operations)
    
    Run with: pytest tests/e2e/ -m e2e -v
    """

    def test_task_list(self, hermes_cli):
        """sag_task_list works through Hermes CLI."""
        result = subprocess.run(
            [hermes_cli, "run", "--tool", "sag_task_list", "--args", '{}'],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
```

---

## 快速开发循环方案

### 方案 A：直接 pytest（推荐日常使用）

无需启动 Hermes gateway，直接在 SagTask 项目目录运行测试：

```bash
cd /home/mi/Work/sagtask

# 安装开发依赖
pip install -e . pytest pytest-cov

# 运行全部测试
pytest tests/ -v

# 监听文件变化自动运行（需安装 pytest-watch）
pip install pytest-watch
ptw tests/ -- -v --tb=short
```

**优势：**
- 秒级反馈（<2s 完成全部 Layer 1-2 测试）
- 无需重启任何服务
- 与 IDE 集成（PyCharm/VSCode test runner）

### 方案 B：热重载开发脚本

替代当前的 `dev-install.sh` 手动流程：

```bash
#!/usr/bin/env bash
# dev-watch.sh — Watch for changes and auto-reload plugin
set -euo pipefail

PLUGIN_SRC="$(pwd)/src/sagtask"
PLUGIN_DST="${HOME}/.hermes/plugins/sagtask"

echo "→ Watching ${PLUGIN_SRC} for changes..."
echo "   Press Ctrl+C to stop"

# Initial copy
cp -rf "$PLUGIN_SRC"/* "$PLUGIN_DST"/

# Watch and copy on change (requires inotifywait)
inotifywait -m -r -e modify,create,delete "$PLUGIN_SRC" |
while read -r dir event file; do
    echo "[$(date +%H:%M:%S)] Change detected: ${file} (${event})"
    cp -rf "$PLUGIN_SRC"/* "$PLUGIN_DST"/
    echo "   → Plugin updated. Gateway will pick up changes on next tool call."
done
```

### 方案 C：pytest + Hermes 联合测试

在 CI 中使用，验证与真实 Hermes 的集成：

```yaml
# .github/workflows/test.yml
name: Test
on: [push, pull_request]

jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install pytest pytest-cov
      - run: pytest tests/ --cov=src/sagtask --cov-report=xml -v
        env:
          PYTHONPATH: src

  integration:
    runs-on: ubuntu-latest
    needs: unit
    steps:
      - uses: actions/checkout@v4
      - uses: actions/checkout@v4
        with:
          repository: ethanchen669/hermes-agent
          path: hermes-agent
      - run: |
          cd hermes-agent && pip install -e .
          cd .. && pip install pytest
      - run: pytest tests/test_registration.py -v
        env:
          PYTHONPATH: src
```

---

## 项目结构调整

```
sagtask/
├── src/sagtask/
│   ├── __init__.py
│   └── plugin.yaml
├── tests/
│   ├── __init__.py
│   ├── conftest.py              ← 共享 fixtures
│   ├── test_state_helpers.py    ← Layer 1: 纯逻辑
│   ├── test_lifecycle.py        ← Layer 2: handler 集成
│   ├── test_git_ops.py          ← Layer 2: git 操作
│   ├── test_cross_pollination.py ← Layer 2: 关系管理
│   ├── test_registration.py     ← Layer 3: 插件注册
│   ├── test_hooks.py            ← Layer 3: hook 调用
│   └── e2e/
│       └── test_e2e_sagtask.py  ← Layer 4: 端到端
├── pyproject.toml               ← 项目元数据 + pytest 配置
├── dev-install.sh
├── dev-watch.sh                 ← 热重载脚本
└── .github/workflows/test.yml
```

### pyproject.toml

```toml
[project]
name = "sagtask"
version = "1.2.0"
requires-python = ">=3.10"

[project.optional-dependencies]
dev = ["pytest>=7.0", "pytest-cov>=4.0", "pytest-watch"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "e2e: end-to-end tests requiring hermes CLI",
]
addopts = "--tb=short -q"

[tool.coverage.run]
source = ["src/sagtask"]
omit = ["tests/*"]

[tool.coverage.report]
fail_under = 80
show_missing = true
```

---

## Mock 策略总结

| 被测对象 | Mock 什么 | 真实执行什么 |
|----------|-----------|------------|
| State helpers | 无 | 纯函数计算 |
| Tool handlers | `subprocess.run`（Git/GitHub） | 文件系统操作（用 `tmp_path`） |
| Context injection | 无（只读 state） | `_on_pre_llm_call` 完整逻辑 |
| Plugin registration | `ctx`（MagicMock） | `register()` 调用链 |
| Git operations | `subprocess.run` 的返回值 | 路径构建和参数组装 |
| E2E | 无（全真实） | hermes CLI + 插件 + Git |

---

## 日常开发工作流

```
修改代码
    │
    ▼
pytest tests/ -x -v  ← 秒级反馈（Layer 1-2）
    │
    ├── PASS → 继续开发 / 提交
    │
    └── FAIL → 修复 → 重新运行
         │
         ▼ (准备发布时)
    pytest tests/ --cov  ← 覆盖率检查
         │
         ▼
    dev-install.sh → 手动验证 ← 仅关键变更
         │
         ▼
    git commit + push → CI 运行全部测试
```

**关键原则：** 日常开发 90% 的测试在 Layer 1-2 完成，无需启动 Hermes gateway。只有涉及 hook 调用时序或 CLI 交互的变更才需要 Layer 3-4。

---

## 快速启动步骤

1. 创建 `tests/` 目录和 `conftest.py`
2. 创建 `pyproject.toml`
3. 安装开发依赖：`pip install -e ".[dev]"`
4. 编写第一个测试：从 `test_lifecycle.py::TestTaskCreate` 开始
5. 运行验证：`pytest tests/ -v`
6. 添加到 CI：`.github/workflows/test.yml`
