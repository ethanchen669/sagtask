# Code Review: feature/superpowers-phase1

**审查日期:** 2026-05-09  
**分支:** `feature/superpowers-phase1`  
**变更统计:** 31 文件，+4,091 / -96 行  
**测试结果:** 全部通过 (125 tests)

---

## 一、变更概述

本分支在 main（8ae2d9f）基础上完成了两大类工作：

### A. 基础工程改进（review.md 中 P0/P1 问题修复）

| 提交 | 修复内容 |
|------|----------|
| 9888f2d | task_id 输入验证 + 路径遍历防护 |
| 96f7c20 | GitHub owner 环境变量可配置 |
| 0d78b52 | subprocess 30s 超时保护 |
| 843300e | `_get_current_step` UnboundLocalError 修复 |
| a540eff | 静默 exception 替换为 logger 记录 |
| 8404f8f | 添加 pytest 测试套件 + pyproject.toml |
| 6d9e9a4 | GitHub Actions CI |

### B. Superpowers Phase 1 功能（methodology + verification）

| 提交 | 功能 |
|------|------|
| 1c4701e | 状态 schema_version=2 + methodology_state |
| 26352a4 | 不可变 schema 迁移逻辑 |
| c370031 | Step schema 扩展（methodology + verification 字段） |
| 2ced125 | `sag_task_verify` 工具 |
| c2d861d | advance 验证前置阻断 |
| 7cf9a5b | pre_llm_call 方法论上下文注入 |
| ff4b6d7 | code review 反馈修复（安全、不可变性、废弃 API） |
| 0ec547c | 测试覆盖率达标 (82%) |

### C. 发布基础设施

| 提交 | 内容 |
|------|------|
| a841dbb | pyproject.toml + hatchling + pip entry-point |
| d9c72de / fbf966e | build-release.sh + bump-version.sh |
| 31f56b4 | install.sh 改进（asset 下载 + checksum 验证） |
| 18fc4d4 | release workflow (GitHub Actions) |
| a5ff987 | CHANGELOG.md |

---

## 二、肯定之处

### 2.1 安全性改进到位

- `_validate_task_id` 正则校验 + 长度限制，彻底封堵路径遍历
- `_SUBPROCESS_TIMEOUT = 30` 全局统一，无遗漏
- `_get_github_owner()` 环境变量解耦，不再硬编码

### 2.2 Schema 迁移设计合理

`_ensure_schema_version` 采用不可变更新（`{**state, ...}`），在 `save_task_state` 中自动升级，对旧数据透明兼容。

### 2.3 Verification 工具设计清晰

- 命令在 step 定义时声明（不接受运行时注入）→ 安全
- `must_pass` 控制是否阻断 advance → 灵活
- 结果记录在 `methodology_state.last_verification` → 可追溯
- 支持 timeout + 通用异常处理

### 2.4 测试覆盖充分

125 个测试，覆盖了核心路径：lifecycle、advance-with-verification、context-injection、relate、schema-versioning、edge cases。fixture 设计简洁。

### 2.5 Context injection 增强有价值

pre_llm_call 中注入 methodology 类型、TDD phase、plan 进度、verification 状态 — 给 LLM 足够的方法论提示而不过度占用 token。

---

## 三、需要修复的问题

### CRITICAL

#### 3.1 `sag_task_verify` 存在命令注入风险

**位置:** `__init__.py:1509`

```python
proc = subprocess.run(
    cmd, shell=True, cwd=cwd,
    capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
)
```

`shell=True` + 用户提供的 `commands` 数组意味着任何 task 创建者可以注入任意 shell 命令。虽然 commands 在 task 创建时定义（不是运行时参数），但如果 task state JSON 被篡改或来自不可信源，这是一个提权向量。

**建议：**
- 方案 A（推荐）：添加命令白名单模式，只允许预定义的命令前缀（`pytest`, `mypy`, `ruff`, `cargo test` 等）
- 方案 B：文档明确标注此风险，在 verify 输出中显示将要执行的命令供用户确认
- 方案 C（最小改动）：在 verify 执行前 log 一条 WARNING 包含完整命令

#### 3.2 `handle_tool_call` 未注册 `sag_task_verify`

**位置:** `__init__.py:640-652`

`handle_tool_call` 内的 `handler_map` 只有 11 个 handler，缺少 `sag_task_verify`。如果有代码路径通过 `handle_tool_call` 方法（而非直接 `_tool_handlers` dispatch）调用 verify，会返回 "Unknown tool" 错误。

```python
handler_map = {
    "sag_task_create": _handle_sag_task_create,
    ...
    "sag_task_relate": _handle_sag_task_relate,
    # MISSING: "sag_task_verify": _handle_sag_task_verify,
}
```

**建议：** 删除 `handle_tool_call` 中的重复 map，改为引用 `_tool_handlers`：

```python
def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
    handler = _tool_handlers.get(tool_name)
    ...
```

---

### HIGH

#### 3.3 `register()` 注释/日志仍说 "tools=11"

**位置:** `__init__.py:1700-1733`

docstring 说 "Registers 11 task_* tools" 但实际注册了 12 个（含 `sag_task_verify`）。日志也输出 `tools=11`。

**建议：** 改为 `tools={len(ALL_TOOL_SCHEMAS)}`。

#### 3.4 `_on_pre_llm_call` 和 `on_turn_start` 逻辑仍然重复

`on_turn_start`（L664-687）构建的上下文缺少 methodology 信息，但 `_on_pre_llm_call`（L1583-1668）包含完整的 methodology 注入。两者的基础部分（status、phase、step、pending_gates、artifacts）完全一致。

**建议：** 提取共享方法 `_build_task_context(state, include_methodology=True)` 避免双份维护。

#### 3.5 CHANGELOG 未更新 Phase 1 新功能

CHANGELOG 只记录了 1.2.0 的基础修复，缺少：
- `sag_task_verify` 工具
- step schema `methodology` + `verification` 字段
- `schema_version: 2`
- 方法论上下文注入
- advance 验证阻断

**建议：** 添加 `[1.3.0]` 或 `[Unreleased]` 段落记录这些变更。

#### 3.6 `_handle_sag_task_pause` 直接 mutate state

**位置:** `__init__.py:1107-1110`

```python
state["status"] = "paused"
state["updated_at"] = ...
state["executions"] = state.get("executions", []) + [execution_id]
```

其他 handler（advance、approve 的部分路径）已改为 `{**state, ...}` 不可变模式，但 pause 和 resume 仍然直接 mutate。

**建议：** 统一为不可变更新模式，保持一致性。

---

### MEDIUM

#### 3.7 `datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")` 重复出现 20+ 次

**建议：** 提取为工具函数：

```python
def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
```

#### 3.8 `cwd` 参数在 verify 中缺少验证

**位置:** `__init__.py:1503`

```python
cwd = verification.get("cwd") or str(task_root)
```

如果用户在 step 定义中设置 `cwd: "/etc"` 或 `cwd: "../../../"`，命令会在非预期目录执行。

**建议：** 验证 cwd 必须是 task_root 的子路径，或为 None（默认 task_root）。

#### 3.9 verify 的 stdout/stderr 截断在 2000 字符

这个值是硬编码的魔数（L1517-1518）。

**建议：** 提取为类常量 `VERIFY_OUTPUT_MAX_LEN = 2000`。

#### 3.10 test CI workflow 缺少 Python 版本矩阵

当前只测 Python 3.12。pyproject.toml 声明 `requires-python = ">=3.10"`，但未验证 3.10/3.11 兼容性。

**建议：** 添加 matrix strategy 测试 3.10 和 3.12。

#### 3.11 release workflow 缺少 `pip install -e .` 步骤

PyPI 发布步骤直接使用 `pypa/gh-action-pypi-publish`，但没有先 build wheel/sdist。

**建议：** 在 PyPI 发布前添加 `pip install build && python -m build` 步骤。

#### 3.12 文件仍然是单个 1734 行的 `__init__.py`

Phase 1 功能增加了 ~300 行，文件从 1450 → 1734 行。距离不可维护的临界点越来越近。

**建议：** 在 Phase 2 开始前拆分模块（参见 `docs/review.md` 中的结构建议）。

---

### LOW / 建议

#### 3.13 测试文件命名碎片化

16 个测试文件，部分粒度过细：
- `test_github_owner.py` (13 行，1 个测试)
- `test_subprocess_timeout.py` (40 行，2 个测试)
- `test_validation.py` (33 行，2 个测试)

**建议：** 合并为更有意义的分组（如 `test_security.py` 包含 validation + timeout + github_owner）。

#### 3.14 `sample_phases` fixture 缺少 methodology/verification

conftest.py 中的 `sample_phases` 只有基础 step 定义。需要 Phase 1 功能的测试各自重新定义带 methodology 的 phases。

**建议：** 添加 `sample_phases_with_verification` fixture 到 conftest。

#### 3.15 `_DEFAULT_GITHUB_OWNER = "ethanchen669"` 应与 install.sh 中的 OWNER 一致

install.sh 中 `OWNER="ethanchen669"`，plugin.yaml 的 INSTALLATION 说明中是 `ethanchen669`，但 `ensure_git_repo` 过去用的是 `charlenchen`。现在虽然已统一为环境变量，但默认值应确认。

---

## 四、架构评估

### Phase 1 目标达成度

| 计划目标 | 状态 | 评价 |
|----------|------|------|
| Step schema 扩展（methodology + verification） | ✅ 完成 | Schema 设计合理，向后兼容 |
| `sag_task_verify` 工具 | ✅ 完成 | 功能完整，有安全隐患需处理 |
| Advance 验证前置 | ✅ 完成 | 逻辑正确，测试覆盖 |
| Context injection 增强 | ✅ 完成 | methodology + verification 状态均注入 |
| 状态 schema 版本化 | ✅ 完成 | v2 + 迁移逻辑，不可变更新 |

**总结：** Phase 1 计划目标全部达成。

### 为 Phase 2 留下的技术债

1. 单文件架构即将到达极限（1734 行），Phase 2 添加 plan/dispatch 工具后必须拆分
2. `handle_tool_call` 重复 map 问题需在添加更多工具前解决
3. on_turn_start vs _on_pre_llm_call 重复逻辑，新增功能时容易遗忘同步

---

## 五、合并建议

**判定：可以合并，但需先修复 2 个 CRITICAL 问题**

1. **CRITICAL 3.1** — verify 命令注入：至少添加执行前 log WARNING（方案 C），最好添加 cwd 验证（3.8）
2. **CRITICAL 3.2** — `handle_tool_call` 缺少 verify handler：改为引用 `_tool_handlers` dict

HIGH 问题建议在合并后的下一个 commit 修复，不阻塞合并。

---

## 六、测试验证

```
$ PYTHONPATH=src python -m pytest tests/ -q
125 passed
```

所有测试在无网络、无 Git 环境下通过。fixture 隔离良好，无副作用。
