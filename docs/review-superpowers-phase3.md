# Code Review: feature/superpowers-phase3 (PR #5)

**审查日期:** 2026-05-11  
**分支:** `feature/superpowers-phase3`  
**基于:** `origin/main` (ed2629f)  
**变更统计:** 20 文件，+3,443 / -1,671 行  
**提交数:** 21（含 Phase 2 的 8 个 + Phase 2 fix 的 2 个 + Phase 3 的 11 个）

---

## 一、变更概述

Phase 3 完成了两大工作：**模块拆分重构** + **编排层功能**。

### A. 模块拆分（6 commits）

将 1,734 行的单文件拆分为清晰的模块结构：

```
src/sagtask/
├── __init__.py              (121 行 — 薄导出层)
├── _utils.py                (45 行 — 常量 + 工具函数)
├── plugin.py                (665 行 — SagTaskPlugin 类)
├── schemas.py               (438 行 — 16 个 tool schema)
├── hooks.py                 (73 行 — pre_llm_call + on_session_start)
└── handlers/
    ├── __init__.py           (66 行 — _tool_handlers dict)
    ├── _lifecycle.py         (392 行 — create/status/pause/resume/advance/approve)
    ├── _git.py               (110 行 — list/commit/branch/git_log)
    ├── _plan.py              (322 行 — relate/verify/plan/plan_update)
    └── _orchestration.py     (341 行 — dispatch/review)
```

**总计:** ~2,553 行分布在 10 个文件中（最大文件 665 行 < 800 行上限）

### B. 编排层功能（5 commits）

| 工具 | 功能 |
|------|------|
| `sag_task_dispatch` | 构建自包含的子代理上下文 prompt，标记 subtask 为 in-progress |
| `sag_task_review` | 构建两阶段审查 prompt（spec compliance + code quality） |
| Context injection 增强 | 注入 "Active dispatches: N subtask(s) in-progress" |

---

## 二、肯定之处

### 2.1 模块拆分质量高

- **无行为变更**：拆分是纯结构重构，`__init__.py` 通过 re-export 保证所有现有 import 路径不变
- **测试兼容**：`conftest.py` 更新了 `sagtask._utils._sagtask_instance` 同步，保证 singleton 在测试中正确隔离
- **清晰的职责划分**：lifecycle/git/plan/orchestration 四个 handler 模块，每个 < 400 行
- **backward-compat alias**：`__init__.py` 保留 `_sagtask_instance` 属性供测试使用

### 2.2 Dispatch 设计精巧

- **自包含 context**：`_build_dispatch_context` 生成的 prompt 包含 subtask 详情、methodology 指令、verification 命令、依赖状态、兄弟 subtask 列表 — 足够一个无状态子代理独立执行
- **幂等安全**：已完成的 subtask 拒绝重新 dispatch；已 in-progress 的 subtask re-dispatch 返回 warning
- **methodology 指令模板**：`_METHODOLOGY_INSTRUCTIONS` 字典为 tdd/brainstorm/debug/plan-execute 提供预定义指南
- **路径遍历防护**：plan_path 的 `relative_to` 检查一贯保持

### 2.3 Review 工具设计合理

- **两阶段审查**：Stage 1 (spec compliance) + Stage 2 (code quality)，遵循 Superpowers 的 subagent-driven-development 模式
- **methodology-aware**：TDD step 审查 "tests were written before implementation"，brainstorm step 审查 "design rationale documented"
- **severity levels**：内嵌 CRITICAL/HIGH/MEDIUM/LOW 表格，审查代理可直接使用

### 2.4 Context injection 增强恰到好处

```
- Active dispatches: 2 subtask(s) in-progress
```

一行信息让 LLM 知道有活跃的并行执行，避免重复 dispatch 或错误 advance。

### 2.5 测试覆盖完整

- `test_dispatch.py`（9 tests）：context 内容、in-progress 标记、重复 dispatch、依赖显示
- `test_review.py`（8 tests）：scope 参数、spec/quality criteria、verification 包含
- `test_register.py` 更新：适配双 singleton 模式

---

## 三、需要修复的问题

### HIGH

#### 3.1 Singleton 双份存储增加了维护负担

**位置:** `__init__.py` L102 + `_utils.py` L19

```python
# __init__.py
_sagtask_instance: Optional["SagTaskPlugin"] = None

# _utils.py
_sagtask_instance: Optional["SagTaskPlugin"] = None
```

`register()` 中必须同步两份：
```python
_sagtask_instance = SagTaskPlugin()
_utils._sagtask_instance = _sagtask_instance
```

`conftest.py` 中也需要双份清理：
```python
sagtask._sagtask_instance = None
sagtask._utils._sagtask_instance = None
```

如果忘记同步任何一份，行为不一致。

**建议：** 删除 `__init__.py` 中的 `_sagtask_instance`，统一使用 `_utils._sagtask_instance` 作为唯一数据源。`__init__.py` 中的属性改为 property 或 `@property` wrapper：

```python
# __init__.py — 替代方案
@property  # 不行，module-level 不支持 property
# 改用 __getattr__:
def __getattr__(name):
    if name == "_sagtask_instance":
        return _utils._sagtask_instance
    raise AttributeError(name)
```

或更简单：在 `conftest.py` 中只操作 `sagtask._utils._sagtask_instance`，删除 `__init__.py` 中的副本。

#### 3.2 `_handle_sag_task_dispatch` 不检查 depends_on 是否完成

用户可以 dispatch 一个依赖于未完成 subtask 的任务（如 dispatch "st-2" 而 "st-1" 仍 pending）。context 中会显示依赖状态，但不阻断执行。

**当前行为：** 允许 dispatch，context 中标注 `[pending] st-1: ...`  
**风险：** 子代理可能在前置工作未完成的情况下执行，产生错误结果

**建议：** 添加 warning 字段（不阻断）：

```python
unfinished_deps = [d for d in subtask.get("depends_on", []) 
                   if any(s["id"] == d and s["status"] != "done" for s in plan["subtasks"])]
if unfinished_deps:
    result["warning"] = f"Dependencies not done: {unfinished_deps}"
```

#### 3.3 `_handle_sag_task_review` scope="phase" 和 scope="full" 没有差异化实现

无论 scope 是 "step"、"phase" 还是 "full"，实际都只构建当前 step 的 review context。phase/full 仅影响输出中 `result["scope"]` 字段的值。

**建议：**
- `scope="phase"`：应包含当前 phase 所有 step 的 names + 进度
- `scope="full"`：应包含全部 phases 概览 + 决策历史

或在 schema description 中明确说明当前只支持 step-level review，phase/full 为预留。

#### 3.4 CHANGELOG 中 Phase 3 的 refactoring 未记录

拆分 6 个 commits 的模块重构是重大架构变更，但 CHANGELOG 只记录了新功能。

**建议：** 添加 `### Changed` 段落：
```
### Changed
- Refactored monolithic __init__.py (1,734 lines) into 10 modules (max 665 lines each)
```

---

### MEDIUM

#### 3.5 `_build_dispatch_context` 返回的 context 没有 token 预算控制

对于复杂 step（长 description + 多依赖 + 多 sibling），生成的 context 可能很长。目前没有截断机制。

**建议：** 添加 `max_context_len` 参数（默认 4000 chars），超出时截断 sibling 列表。

#### 3.6 `subprocess` 的 `import` 在 `__init__.py` 中是为了测试 mock

```python
import subprocess  # noqa: F401 — re-exported for test mock targets
```

这个设计意味着测试 mock `sagtask.subprocess.run`，但实际 subprocess 调用在 `plugin.py` 中。如果 `plugin.py` 中用的是自己 import 的 subprocess，mock 可能不生效。

**当前能工作的原因：** `plugin.py` 中 `import subprocess` 创建了自己的引用，但 conftest mock 的是 `sagtask.subprocess.run`。需要确认 mock 目标是否正确。

**建议：** 验证测试实际运行通过（如果通过则说明 Python 模块引用机制使 mock 生效）。如果迁移到更严格的 mock（如 `sagtask.plugin.subprocess.run`），需要更新 conftest。

#### 3.7 `_orchestration.py` 中的 `_load_plan` 与 `_plan.py` 中的 plan 加载逻辑重复

`_plan.py` 的 `_handle_sag_task_plan_update` 中也有 `json.loads(plan_path.read_text())` 逻辑。

**建议：** 将 `_load_plan` 移到 `_utils.py` 或 `plugin.py` 作为共享方法。

#### 3.8 `_METHODOLOGY_INSTRUCTIONS` 模板硬编码

指令模板写死在代码中。如果用户想自定义 methodology 指令（如特定项目的 TDD 约定），无法扩展。

**建议（长期）：** 支持 task 级别的 `methodology_instructions` 覆盖字段。短期无需改动。

#### 3.9 `dispatch` 不记录 dispatch 历史

dispatch 只设置 subtask status 为 in-progress，但不记录「谁在什么时间 dispatch 了这个 subtask」。如果子代理失败需要重试，无法追溯。

**建议：** 在 plan.json 的 subtask 中添加 `dispatched_at` 字段：
```python
{**s, "status": "in_progress", "dispatched_at": _utcnow_iso()}
```

---

### LOW

#### 3.10 `handlers/_plan.py` 包含 `relate` 和 `verify` — 命名不完全准确

`_plan.py` 包含 relate + verify + plan + plan_update 四个 handler。前两个（relate、verify）与 "plan" 无关。

**建议：** 重命名为 `_extended.py` 或将 relate/verify 移到 `_lifecycle.py`。低优先级。

#### 3.11 `test_dispatch.py` 的 `test_dispatch_includes_depends_on_status` 有条件跳过

```python
dep_task = next((s for s in plan["subtasks"] if s.get("depends_on")), None)
if dep_task:
    ...
```

如果 plan 模板变更导致没有 depends_on 的 subtask，测试会静默跳过而非失败。

**建议：** 改为 `assert dep_task is not None` 确保测试前置条件成立。

---

## 四、Phase 3 目标达成度

| 计划目标（from superpowers-integration-proposal.md） | 状态 | 评价 |
|------|------|------|
| `sag_task_dispatch` 工具 | ✅ 完成 | 自包含 context 构建，非 subprocess 执行（Phase 3 原计划是 subprocess，改为 context-only 更合理） |
| 子代理结果收集 | ⚠️ 部分 | plan_update 可手动记录，但无自动回收机制 |
| 并行执行支持 | ✅ 设计支持 | in-progress 计数 + 多 subtask 可同时 dispatch |
| 两阶段审查 | ✅ 完成 | spec review + quality review 结构化 prompt |
| `sag_task_review` 工具 | ✅ 完成 | 支持 step/phase/full scope（实际仅 step 有差异化） |
| 模块拆分 | ✅ 完成 | 10 个文件，最大 665 行 |

**设计决策变更说明：**

原计划 `sag_task_dispatch` 通过 subprocess 调用 `hermes` CLI 实现子代理派遣。实际实现改为「构建并返回 context prompt」，让调用方自行决定如何 dispatch。这是正确的决策——保持插件层的简单性，将编排复杂度留给上层。

---

## 五、安全检查

| 检查项 | 状态 |
|--------|------|
| 路径遍历防护（dispatch 的 plan_path） | ✅ `relative_to` 检查 |
| 输入验证（scope、subtask_id） | ✅ 有效 |
| 无 shell 执行 | ✅ dispatch/review 不执行命令 |
| 文件写入安全（dispatch 更新 plan） | ✅ 原子 os.replace |
| singleton 一致性 | ⚠️ 双份存储有风险（见 3.1） |

---

## 六、模块拆分质量评估

| 维度 | 评分 | 说明 |
|------|------|------|
| 内聚性 | 9/10 | 每个模块有清晰的单一职责 |
| 耦合性 | 8/10 | 通过 `_get_provider()` 统一访问 singleton，handlers 间无直接依赖 |
| 向后兼容 | 9/10 | re-export 保证旧 import 路径可用 |
| 文件大小 | 10/10 | 最大 665 行，远低于 800 行上限 |
| 可发现性 | 8/10 | 新开发者需要知道从 handlers/ 入口找功能 |

**唯一扣分点：** singleton 双份存储（`__init__.py` + `_utils.py`）增加了认知负担。

---

## 七、与历史 Review 遗留问题对照

| 遗留问题 | Phase 3 是否解决 |
|----------|-----------------|
| 模块拆分（Phase 1 review #3.12） | ✅ **已解决** |
| CI Python 版本矩阵 | ❌ 未处理 |
| release workflow 缺 build 步骤 | ❌ 未处理 |
| plan_update context 覆盖问题（Phase 2 #3.2） | ❌ 未处理 |
| plan_version 字段（Phase 2 #3.7） | ❌ 未处理 |

---

## 八、合并建议

**判定：可以合并**

没有 CRITICAL 问题。HIGH 问题主要是功能语义层面（scope 未差异化、depends_on 不校验），不影响现有功能正确性。

**合并前（建议）：**
1. CHANGELOG 添加 `### Changed` 记录模块拆分（3.4，一行改动）

**合并后跟进：**
1. 统一 singleton 存储（3.1）— 消除双份同步负担
2. review scope 差异化实现（3.3）— 或在 schema 中标注为预留
3. dispatch 添加 `dispatched_at` 记录（3.9）
4. 共享 `_load_plan` 函数（3.7）

---

## 九、测试验证

新增测试：
```
tests/test_dispatch.py    — 9 tests
tests/test_review.py      — 8 tests
tests/test_register.py    — 更新适配双 singleton
tests/test_context_injection.py — 新增 dispatch 进度注入测试
```

需要确认：`PYTHONPATH=src python -m pytest tests/ -q` 全部通过（mock 目标在模块拆分后仍然正确）。
