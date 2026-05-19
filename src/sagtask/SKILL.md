---
name: sagtask
description: 长期任务管理系统，支持分阶段推进、审批门、Git 产物追踪、子任务派发。
version: 2.0.3
category: productivity
tags: [task-management, multi-phase, git, dispatch, tdd, brainstorming]
author: ethanchen669
date_created: 2026-04-20
---
# SagTask — 长期任务管理

## 是什么

SagTask 是 Hermes Agent 的**长期任务管理插件**，用于管理需要分阶段完成、跨越多天/多会话的大型工作。

每个 SagTask 对应 `~/.hermes/sag_tasks/<task_id>/` 下的一个独立 Git 仓库，包含：
- `.sag_task_state.json` — 任务状态（阶段、步骤、gate、产物）
- `.sag_artifacts/` — 产物快照目录
- 项目本身的源代码和文档

**核心能力**：

| 能力 | 说明 |
|------|------|
| 分阶段推进 | Phase → Step → Step，每次 advance 自动 commit |
| 审批门 | 步骤可设置 gate，暂停等待人工审批（approve/reject） |
| 上下文注入 | `pre_llm_call` hook 每次 LLM 调用前自动注入任务状态和上下文 |
| 产物追踪 | advance 时自动生成 git diff/stat artifact summary |
| 子任务派发 | dispatch 将子任务发给 subagent 独立执行 |
| 任意方法论 | 支持 TDD、brainstorm、debug、review 等执行模式 |
| 状态持久化 | 所有状态存文件，Gateway 重启不丢失 |

**工具数**：19 个

---

## 快速上手

### 创建任务

```
sag_task_create
  sag_task_id: "my-project-v1"
  name: "My Project"
  description: "..."
  phases:
    - id: "phase-1"
      name: "设计"
      steps:
        - id: "step-1"
          name: "需求分析"
        - id: "step-2"
          name: "技术方案"
          gate:
            id: "gate-1"
            question: "方案是否通过？"
            choices: ["Approve", "Reject", "Request Changes"]
```

### 日常推进

```bash
# 查看当前状态
sag_task_status

# 推进到下一步（自动 commit + 生成 artifact summary）
sag_task_advance

# 如有审批门，等待审批
sag_task_approve gate_id: "gate-1" decision: "Approve"

# 暂停任务（保存上下文快照）
sag_task_pause reason: "等待外部依赖"

# 恢复任务
sag_task_resume
```

### 查看历史

```bash
# Git 提交历史
sag_task_git_log

# 手动 commit
sag_task_commit message: "[Step 2] 完成技术方案文档"
```

---

## 工具清单（共 19 个）

| 工具 | 说明 |
|------|------|
| `sag_task_create` | 创建任务，初始化 Git repo + state |
| `sag_task_status` | 查看当前阶段/步骤/gate/产物摘要 |
| `sag_task_pause` | 暂停，保存上下文快照 |
| `sag_task_resume` | 从暂停点恢复 |
| `sag_task_advance` | 推进到下一步，自动 commit + 生成 artifact summary |
| `sag_task_approve` | 响应审批门（Approve / Reject / Request Changes）|
| `sag_task_list` | 列出所有任务（按状态过滤）|
| `sag_task_commit` | 手动 commit |
| `sag_task_branch` | 创建新分支 |
| `sag_task_git_log` | 查看任务 Git 提交历史 |
| `sag_task_plan` | 将当前步骤分解为子任务 |
| `sag_task_plan_update` | 更新子任务状态 |
| `sag_task_relate` | 建立跨任务关联（cross-pollination）|
| `sag_task_verify` | 运行步骤验证命令 |
| `sag_task_brainstorm` | 生成设计选项供选择 |
| `sag_task_debug` | 记录调试假设和修复 |
| `sag_task_dispatch` | 派发子任务给 subagent 独立执行 |
| `sag_task_review` | 执行两步评审（spec 合规 + 代码质量）|
| `sag_task_metrics` | 查询验证统计、覆盖率趋势、吞吐量 |

---

## 工作流示例

### 完整生命周期

```
1. sag_task_create  →  初始化任务
2. sag_task_plan    →  分解步骤为子任务
3. [执行子任务]      →  sag_task_plan_update 标记 done
4. sag_task_verify  →  运行验证命令
5. sag_task_advance →  推进，生成 artifact summary
   ↓
   如有 gate → sag_task_approve 审批
   ↓
   进入下一 phase
```

### TDD 模式

创建时指定 `methodology: { type: "tdd", config: { coverage_threshold: 80, test_first: true } }`

```
sag_task_plan
  → 生成 test 文件的 subtask
  → 执行测试（应 fail）
  → 写实现代码
  → sag_task_verify 跑覆盖率
  → sag_task_advance
```

### dispatch 派发模式

```
sag_task_dispatch subtask_id: "st-3"
  → subagent 在独立 context 中执行
  → 返回结果写入 artifact
  → 主任务 sag_task_plan_update st-3 → done
```

### debug 循环

```
sag_task_debug hypothesis: "根因是 N+1 查询"
  → sag_task_debug fix_description: "加数据库索引"
  → sag_task_verify
  → sag_task_advance
```

---

## 执行方法论

创建任务时可为步骤指定 methodology：

| 类型 | 说明 |
|------|------|
| `tdd` | 测试驱动，覆盖率门槛约束 |
| `brainstorm` | 生成多个设计选项，用户选择后继续 |
| `debug` | 假设→诊断→修复→验证循环 |
| `plan-execute` | 规划→执行分离 |
| `parallel-agents` | 并行派发多个 subagent |
| `review` | spec 评审 + 代码评审 |
| `none` | 无特殊方法论 |

---

## 产物追踪（Artifact Summaries）

`sag_task_advance` 时自动生成 artifact summary，包含：

1. `git diff --stat HEAD~1..HEAD` — 上一步的文件变更
2. `git status --porcelain` — 未提交变更
3. `git ls-files` — 所有追踪文件列表
4. 已有 `.sag_artifacts/` 条目合并

产物存在 `.sag_tasks/<task_id>/.sag_artifacts/` 目录，每次 advance 追加。

---

## pre_llm_call 上下文注入

| 场景 | 是否注入 |
|------|---------|
| 正常 turn | ✅ |
| Context Compression 后 | ✅ |
| Session start | ✅ |
| Subagent / batch | ✅ |
| `_handle_max_iterations()` 退出 | ❌ |

注入内容：当前任务状态 + 当前步骤描述 + artifact summary + 相关任务关联内容。

**实现要点**：`_on_pre_llm_call` 读文件而非内存缓存，理由：
- Context compression 丢弃旧消息但文件独立存在
- Gateway 重启后 `on_session_start` 恢复 active task，文件无 stale 问题

---

## 插件结构

```
~/.hermes/plugins/sagtask/       ← 插件根目录
├── __init__.py                  # 注册入口
├── plugin.yaml                  # 元数据（version: 2.0.0, kind: standalone）
├── plugin.py                    # SagTaskPlugin 核心类
├── hooks.py                     # _on_pre_llm_call, _on_session_start
├── schemas.py                   # 19 个工具的 JSON schema
├── _utils.py                    # _get_provider(), _validate_task_id()
└── handlers/
    ├── _lifecycle.py            # create, status, pause, resume, advance, approve
    ├── _git.py                  # list, commit, branch, git_log
    ├── _plan.py                 # plan, plan_update, relate, verify, brainstorm, debug
    ├── _orchestration.py        # dispatch, review
    └── _metrics.py              # metrics
```

**状态文件**：`~/.hermes/sag_tasks/<task_id>/.sag_task_state.json`

**不占用**：`memory.provider` 配置槽位（standalone plugin）

---

## 安装与更新

```bash
# 克隆
git clone https://github.com/ethanchen669/sagtask.git ~/.hermes/plugins/sagtask

# 更新
cd ~/.hermes/plugins/sagtask && git pull

# 发布
git add -A && git commit -m "fix: <description>" && git push
git tag v2.x.0 && git push origin v2.x.0   # GitHub Actions 自动构建 release asset
```

---

## Gateway 与代码更新

**⚠️ Gateway 停止/重启必须经用户明确同意。**

Python 代码变更不一定需要重启：

| 变更类型 | 是否需要 restart |
|---------|-----------------|
| 普通 `.py` 文件（逻辑修改）| 清 pycache 即可 |
| handler 函数签名变更（含 `**kwargs`）| **必须 restart** |
| `plugin.yaml` 修改 | **必须 restart** |
| 新增文件需 startup 发现 | **必须 restart** |
| 二进制模块（`.so`/Cython）| **必须 restart** |

```bash
# 清 pycache（不需要 restart）
rm -rf ~/.hermes/plugins/sagtask/__pycache__
rm -rf ~/.hermes/plugins/sagtask/handlers/__pycache__
```

**需要 restart 时**（需用户授权）：

```bash
ps aux | grep hermes_cli.main | grep -v grep
# kill <PID>
# ~/.hermes/hermes-agent/venv/bin/hermes gateway run --replace &
```

---

## 常见 Bug

1. **sag_task_relate missing `list` action** — 只处理 `add`/`remove`，漏了 `list`。把 `state = load_task_state` 移到 `related_task_id` 检查之前。

2. **task_status missing new fields** — 新增 state 字段时，必须同时加到 `handle_sag_task_create` 初始状态和 `handle_sag_task_status` 返回值。

3. **_generate_artifact_summaries empty-write** — `if summaries:` guard 导致空列表不写入，每次 advance 都会重复扫描。去掉 guard，always write。

4. **_generate_artifact_summaries re-scan** — 从 `_handle_sag_task_advance` 调用时必须 `force=True`，否则跳过已存在的 state。

5. **handler_map rename trap** — rename handler 函数时，git blob 里的 keys 更新了，但 working directory 文件没更新。**总是先更新源码文件，确认 on disk，再 commit**。验证：`grep "_handle_task_" ~/.hermes/plugins/sagtask/handlers/*.py` 应返回空。

6. **install.sh release URL** — 安装脚本必须用 GitHub release asset URL（`/releases/download/<tag>/`），不能用 `raw.githubusercontent.com` 的 main 分支路径。

7. **rename 后目录名字符串遗漏** — 症状：`_projects_root` 指向空目录，所有任务操作返回 "task not found"。验证：`plugin._projects_root == pathlib.Path.home() / ".hermes" / "sag_tasks"`。

8. **FakeCtx 验证过时** — sagtask 从 11 工具扩到 19 工具时，FakeCtx 验证代码的 `len(ctx.tools) == 11` 没更新。

9. **handler 缺少 `**kwargs`** — 最常见炸鸡。`tools/registry.py` 的 `dispatch()` 调用 `entry.handler(args, **kwargs)`，sagtask 所有 19 个 handler 签名必须含 `**kwargs`。验证：`python3 -c "from sagtask.handlers._git import _handle_sag_task_list; _handle_sag_task_list({}, task_id='x')"` 应不抛 TypeError。

---

## 验证 SagTaskPlugin 加载状态

```python
import sys
sys.path.insert(0, "/Users/ethan/.hermes/plugins")

from sagtask._utils import _get_provider
from sagtask.handlers import _tool_handlers

p = _get_provider()
assert type(p).__name__ == "SagTaskPlugin"
assert len(_tool_handlers) == 19, f"Expected 19, got {len(_tool_handlers)}"

from sagtask.hooks import _on_pre_llm_call, _on_session_start
assert callable(_on_pre_llm_call)
assert callable(_on_session_start)

assert p._projects_root == p._hermes_home / "sag_tasks"
p._active_task_id  # 当前活跃任务 ID
```

---

## 手动创建 Task（Plugin 未注册时）

若 Gateway 未运行或插件未加载，直接调用 handler 会报 `RuntimeError: SagTaskPlugin not registered`。

**Workaround：手动写 state 文件**

```bash
mkdir -p ~/.hermes/sag_tasks/<task_id>/.sag_artifacts
# 写入 .sag_task_state.json
# git init + initial commit
```

最小 state 文件结构：
```json
{
  "sag_task_id": "<task_id>",
  "name": "<name>",
  "description": "<desc>",
  "status": "active",
  "current_phase": "phase-1",
  "phases": [...],
  "artifacts": [],
  "artifact_summaries": [],
  "related_task_ids": []
}
```

---


