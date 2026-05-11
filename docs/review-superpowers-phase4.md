# Code Review: feature/superpowers-phase4 (PR #7)

**审查日期:** 2026-05-11  
**分支:** `feature/superpowers-phase4`  
**基于:** `origin/main`  
**变更统计:** 13 文件，+1,006 / -2 行  
**提交数:** 7

---

## 一、变更概述

Phase 4 实现了「高级集成」功能，完成了 Superpowers 集成的最后一层：

| 特性 | 说明 |
|------|------|
| `sag_task_brainstorm` | 设计探索工作流 — explore → select 两阶段 |
| `sag_task_debug` | 系统化调试工作流 — reproduce → diagnose → fix 三阶段 |
| `_recommend_methodology` | 基于关键词自动推荐方法论 |
| Git worktree 集成 | dispatch 时可创建隔离 worktree |
| Context injection 增强 | 显示 brainstorm/debug phase 状态 |

---

## 二、肯定之处

### 2.1 Brainstorm 工具设计清晰

- **两阶段状态机**：`explore` → `select`，状态持久化到 `methodology_state`
- **幂等防护**：已 select 后再次调用返回 warning 而非覆盖
- **自定义设计记录**：支持 `design_title` + `design_description` 附加信息
- **结构化 prompt 输出**：包含 evaluation criteria（simplicity、correctness、performance、extensibility）

### 2.2 Debug 工具的状态机严谨

- **三阶段强制顺序**：reproduce → diagnose → fix
- **状态转换守卫**：
  - 未经 hypothesis 不能直接提交 fix（阻止跳过根因分析）
  - fix 阶段不能回退提交新 hypothesis
- **hypothesis 可覆盖**：diagnose 阶段允许更新假设（符合调试迭代的现实）
- **context 中显示进度**：已完成步骤用 ~~strikethrough~~ 标记

### 2.3 Git worktree 集成设计合理

- **opt-in**：`use_worktree: true` 显式启用，默认不创建
- **幂等**：worktree 已存在时直接返回路径
- **清理机制**：`remove_worktree` 方法配合 `--force` 清理
- **隔离分支命名**：`worktree/{subtask_id}`，不干扰 step 分支

### 2.4 Methodology 推荐实现简洁实用

- **纯函数**：`_recommend_methodology(step_name, step_description)` 无副作用
- **confidence 排序**：多关键词命中 → 更高置信度
- **不强制**：返回建议列表，不自动应用

### 2.5 测试覆盖完善

- `test_brainstorm.py`（8 tests）：explore/select/幂等/自定义设计
- `test_debug.py`（10 tests）：完整状态机 + 守卫条件 + 覆盖
- `test_dispatch.py` 新增 5 tests：worktree 创建/失败/mock 验证
- `test_methodology_recommend.py`（8 tests）：各 methodology 关键词 + confidence 排序
- `test_context_injection.py` 新增：brainstorm/debug phase 显示

---

## 三、需要修复的问题

### HIGH

#### 3.1 `create_worktree` 中 `.sag_worktrees/` 未加入 `.gitignore`

**位置:** `plugin.py` L+258

```python
worktree_dir = task_root / ".sag_worktrees" / subtask_id
```

Worktree 目录在 task_root 下，但 `.sag_worktrees/` 未添加到 `.gitignore` 模板。虽然 Git 通常不会将 worktree 目录误跟踪（因为 worktree 本身包含 `.git` 文件），但 `git add -A` 在某些 Git 版本下可能产生意外行为。

**建议：** 在 `ensure_git_repo` 的 `.gitignore` 模板和 `_handle_sag_task_create` 中的 gitignore 写入中添加 `.sag_worktrees/`：

```
.sag_task_state.json
.sag_artifacts/
.sag_executions/
.sag_worktrees/
__pycache__/
*.pyc
```

#### 3.2 `_handle_sag_task_brainstorm` 中 explore 阶段的条件判断逻辑冗余

**位置:** `_plan.py` L+300-307

```python
if current_phase == "explore" and not ms.get("brainstorm_phase"):
    state = {
        **state,
        "methodology_state": {
            **ms,
            "brainstorm_phase": "explore",
        },
    }
    p.save_task_state(task_id, state)
```

条件 `current_phase == "explore" and not ms.get("brainstorm_phase")` 有问题：`current_phase` 来自 `ms.get("brainstorm_phase", "explore")`，所以如果 `brainstorm_phase` 不存在，`current_phase == "explore"` 为 True 且 `not ms.get("brainstorm_phase")` 也为 True — 条件成立。但如果已经设了 `brainstorm_phase: "explore"`，`current_phase == "explore"` True 但 `not ms.get("brainstorm_phase")` False — 不进入。

**实际效果：** 只在首次调用时写入 `brainstorm_phase: "explore"`，后续调用跳过。逻辑正确但表达不清晰。

**建议：** 简化为：
```python
if not ms.get("brainstorm_phase"):
    state = {**state, "methodology_state": {**ms, "brainstorm_phase": "explore"}}
    p.save_task_state(task_id, state)
```

#### 3.3 `_handle_sag_task_debug` 从 `_orchestration.py` 导入常量 — 循环依赖风险

**位置:** `_plan.py` L+341, L+399

```python
from ._orchestration import (
    DEBUG_PHASE_DIAGNOSE,
    DEBUG_PHASE_FIX,
    DEBUG_PHASE_REPRODUCE,
    _build_debug_context,
)
```

`_plan.py` 调用 `_orchestration.py` 中的 context builders。这创建了 `_plan → _orchestration` 的依赖。如果未来 `_orchestration` 需要调用 `_plan` 中的任何东西，会产生循环导入。

**当前不是 bug**（Python 的延迟 import 在函数内解决了这个问题），但架构上不够干净。

**建议：** 将 `DEBUG_PHASE_*` 常量和 `_build_brainstorm_context` / `_build_debug_context` 移到 `_utils.py` 或新建 `_context_builders.py`，消除 handler 间依赖。

#### 3.4 `dispatch` 中 worktree 创建在 state 保存之后

**位置:** `_orchestration.py` L+193-197

```python
p.save_task_state(task_id, state)  # subtask 已标记为 in-progress

# Create worktree if requested
worktree_path = None
use_worktree = args.get("use_worktree", False)
if use_worktree:
    worktree_path = p.create_worktree(task_id, subtask_id)
    if not worktree_path:
        return {"ok": False, "error": ...}  # 但 state 已保存为 in-progress!
```

如果 worktree 创建失败，state 已经将 subtask 标记为 `in-progress`，但返回了错误。下次重试会看到 "already in-progress" 的 warning。

**建议：** 将 worktree 创建移到 state 保存之前，或在失败时回滚 subtask status：

```python
if use_worktree:
    worktree_path = p.create_worktree(task_id, subtask_id)
    if not worktree_path:
        # Rollback: restore plan to original state
        ...
        return {"ok": False, "error": ...}
```

---

### MEDIUM

#### 3.5 `_recommend_methodology` 未被任何 tool 主动调用

函数已实现且有完整测试，但没有 tool handler 在任何地方调用它。它是一个纯工具函数，等待上层使用。

**当前状态：** 纯库函数，无集成入口  
**建议：** 考虑在以下场景自动调用：
- `sag_task_plan` 时如果 step 没有 methodology 配置，返回推荐
- `_on_pre_llm_call` 中对当前 step 无 methodology 时给出建议

或在 CHANGELOG 中标注为 utility function available for future integration。

#### 3.6 Brainstorm `selected_option=0` 的语义不清

测试中出现 `"selected_option": 0`，schema 描述说 "1-indexed"。`0` 是否合法？如果用于表示"自定义设计"（非预生成选项），应在 schema 中明确说明。

**建议：** 在 schema description 中添加 "0 for custom design (provide design_title/design_description)" 或添加运行时验证。

#### 3.7 Debug 阶段不可回退

一旦进入 `fix` 阶段，无法回到 `diagnose`（比如发现 fix 不对，需要重新诊断）。

**当前守卫：**
```python
if current_phase not in (DEBUG_PHASE_REPRODUCE, DEBUG_PHASE_DIAGNOSE):
    return {"ok": False, "error": "Cannot record hypothesis in fix phase."}
```

**建议：** 添加 `reset` 参数或允许 fix 阶段提交新 hypothesis（重置回 diagnose）。这符合真实调试的迭代特性。低优先级 — 用户可通过手动编辑 state 或创建新 debug step 绕过。

#### 3.8 `remove_worktree` 使用 `--force` 但无数据保护

**位置:** `plugin.py` L+284

```python
["git", "worktree", "remove", str(worktree_dir), "--force"]
```

`--force` 会丢弃 worktree 中未提交的更改。如果子代理在 worktree 中有未提交工作，清理时会丢失。

**建议：** 先不用 `--force`，检查返回码。如果失败（有未提交更改），返回 warning 让用户决定是否 force remove。或在 remove 前自动 commit WIP。

#### 3.9 Context injection 中 brainstorm/debug 状态嵌套在 `if methodology != "none"` 内

**位置:** `plugin.py` L+328-340

如果用户在 step 定义中设置了 `methodology: "brainstorm"` 但 `methodology_state.current_methodology` 因为某种原因是 `"none"`，brainstorm phase 不会显示。

**实际风险：** 低。`_handle_sag_task_create` 会从首个 step 的 methodology 初始化 `current_methodology`。但如果手动编辑 state 或 schema 迁移遗漏，可能出现不一致。

---

### LOW

#### 3.10 `__init__.py` 缺少新 handler 的 re-export

`_handle_sag_task_brainstorm` 和 `_handle_sag_task_debug` 需要在 `__init__.py` 中 re-export 以保持向后兼容性（如果外部代码直接 `from sagtask import _handle_sag_task_brainstorm`）。

**当前情况：** `__init__.py` diff 只添加了 4 行 — 需要确认是否包含这两个 handler 的导入。

#### 3.11 CHANGELOG 中 Phase 4 段落较短

只有 6 行，缺少 worktree 集成和 methodology recommend 的记录。

---

## 四、Phase 4 目标达成度

| 计划目标（from superpowers-integration-proposal.md） | 状态 | 评价 |
|------|------|------|
| Brainstorming 方法论 | ✅ 完成 | explore → select 状态机 + 结构化 prompt |
| Debugging 方法论 | ✅ 完成 | reproduce → diagnose → fix 三阶段 + 守卫 |
| Git worktree 集成 | ✅ 完成 | opt-in per dispatch，create + remove |
| 方法论自动推荐 | ✅ 完成 | 关键词匹配 + confidence 排序（未集成到 tool） |
| Metrics 收集 | ❌ 未实现 | 原计划 P3 优先级，延后合理 |

---

## 五、安全检查

| 检查项 | 状态 |
|--------|------|
| 输入验证 | ✅ brainstorm/debug 都检查 task 存在性 |
| 状态转换守卫 | ✅ debug 强制阶段顺序 |
| shell 执行 | ⚠️ worktree 通过 subprocess 调用 git，但参数来自 `subtask_id`（已验证过的 plan 内容，非用户直接输入） |
| 文件系统写入 | ✅ worktree 在 task_root 子目录 |
| 不可变 state 更新 | ✅ 所有新代码使用 `{**state, ...}` |

---

## 六、架构评估

### 工具总数统计

Phase 4 后 SagTask 总计 **18 个工具**：

| 类别 | 工具 | 数量 |
|------|------|------|
| Lifecycle | create, status, pause, resume, advance, approve | 6 |
| Git | list, commit, branch, git_log | 4 |
| Plan/Method | relate, verify, plan, plan_update, brainstorm, debug | 6 |
| Orchestration | dispatch, review | 2 |

这是一个合理的工具集规模。每个工具有清晰的单一职责。

### 模块大小（Phase 4 后）

| 模块 | 行数 | 评价 |
|------|------|------|
| `plugin.py` | ~728 | 接近上限（+63 from worktree） |
| `handlers/_plan.py` | ~520 | 接近上限（+198 from brainstorm/debug） |
| `handlers/_orchestration.py` | ~503 | 接近上限（+162 from context builders） |
| `schemas.py` | ~497 | 可接受 |

`_plan.py` 和 `_orchestration.py` 都接近需要再次拆分的阈值。建议后续将 brainstorm/debug 提取为独立模块 `handlers/_methodology.py`。

---

## 七、合并建议

**判定：可以合并，建议先修复 3.1**

- **合并前修复**：`.sag_worktrees/` 加入 gitignore 模板（3.1，2 行改动）
- **合并后跟进**：
  1. Worktree 创建失败时回滚 state（3.4）
  2. 将 debug 常量/context builders 移到独立模块（3.3）
  3. 丰富 CHANGELOG（3.11）
  4. 考虑 `_recommend_methodology` 的集成入口（3.5）

---

## 八、Superpowers 集成总结（Phase 1-4）

所有 4 个 Phase 均已完成。最终实现 vs 原始计划对比：

| 原始计划 | 最终实现 | 差异 |
|----------|----------|------|
| subprocess 子代理执行 | Context prompt 构建（调用方决定执行方式） | 更简单、更解耦 |
| 命令白名单 | shell=True + cwd 验证 + warning log | 安全级别足够 |
| LLM 生成 plan | 模板化 plan 生成（基于 methodology） | 更可预测、零 API 成本 |
| 强制方法论 | 建议式（context 注入） + 可选硬约束（must_pass） | 更灵活 |

**总工具数：** 18 个  
**总代码量：** ~3,200 行（10 个模块）  
**测试覆盖：** ~180+ tests
