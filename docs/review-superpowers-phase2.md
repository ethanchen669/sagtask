# Code Review: feature/superpowers-phase2 (PR #4)

**审查日期:** 2026-05-09  
**分支:** `feature/superpowers-phase2`  
**基于:** `origin/main` (ed2629f, 含 Phase 1 + fix PR #3)  
**变更统计:** 7 文件，+695 行  
**提交数:** 8

---

## 一、变更概述

Phase 2 实现了「计划层」功能，包含 3 个核心特性：

| 特性 | 说明 |
|------|------|
| `sag_task_plan` | 为当前 step 生成结构化子任务计划（基于 methodology 自动模板） |
| `sag_task_plan_update` | 更新子任务状态，同步进度到 methodology_state |
| TDD 状态机 | verify 通过/失败自动切换 red/green phase，advance 时重置 |

---

## 二、肯定之处

### 2.1 Plan 生成设计合理

- **模板化生成**：根据 methodology type 自动生成不同模板（TDD→RED/GREEN/REFACTOR，brainstorm→explore/select/implement，none→plan/implement/verify）
- **幂等防护**：plan 已存在时拒绝覆盖，需显式删除后重建
- **Git-tracked**：`.sag_plans/` 在 Git 中（不在 .gitignore），计划文件是有价值产出物

### 2.2 Plan Update 实现严谨

- **原子写入**：`tmp_path.write_text() + os.replace()` 防止写入中断导致文件损坏
- **路径遍历防护**：`plan_path.relative_to(task_root.resolve())` 检查
- **JSON 解码错误处理**：损坏的 plan 文件返回明确错误
- **进度同步**：每次 update 重新计算 total/completed/in_progress（而非增量计数，避免不一致）

### 2.3 TDD 状态机设计简洁

- verify 失败 → `tdd_phase = "red"`
- verify 通过 → `tdd_phase = "green"`
- advance 时 → `tdd_phase = None`（重置给下一个 step）
- 非 TDD step 不受影响

这个状态机足够简单，不会引入额外复杂度，同时为 LLM context 提供了有价值的信号。

### 2.4 测试质量高

- 3 个新测试文件，覆盖正常路径和边界条件
- `test_plan.py`（10 tests）：生成、结构验证、幂等、granularity
- `test_plan_update.py`（8 tests）：状态更新、进度同步、错误处理、context 附加
- `test_tdd_state.py`（5 tests）：红绿切换、advance 重置、非 TDD 无影响
- conftest 新增 `sample_phases_with_methodology` fixture

### 2.5 遵守了 Phase 1 code review 的改进

- 所有新代码使用 `_utcnow_iso()`
- 不可变 state 更新（`{**state, ...}`）
- plan_update 中有 path traversal 防护
- 通过 `_tool_handlers` dict 统一注册（无重复 map）

---

## 三、需要修复的问题

### HIGH

#### 3.1 `_generate_plan` 中 brainstorm 的 `depends_on` 引用逻辑错误

**位置:** diff L+799, L+803

```python
elif methodology == "brainstorm":
    _add_subtask(
        f"Explore design options for {step_name}",
        ...,
    )
    _add_subtask(
        f"Select and document design for {step_name}",
        ...,
        depends_on=[f"st-{st_id}"],  # st_id = 1 at this point → depends_on=["st-1"] ✓
    )
    _add_subtask(
        f"Implement {step_name} per selected design",
        ...,
        depends_on=[f"st-{st_id}"],  # st_id = 2 at this point → depends_on=["st-2"] ✓
    )
```

**看起来正确**，因为 `_add_subtask` 先递增 `st_id` 再用它。但 `depends_on=[f"st-{st_id}"]` 引用的是*当前* st_id（已被 `_add_subtask` 递增后的值），实际意图是引用*上一个*添加的 subtask。

让我们追踪执行：
1. `_add_subtask("Explore...")` → st_id 变为 1，生成 "st-1"
2. `_add_subtask("Select...", depends_on=[f"st-{st_id}"])` → 此时 st_id=1，depends_on=["st-1"] ✓，然后 st_id 变为 2
3. `_add_subtask("Implement...", depends_on=[f"st-{st_id}"])` → 此时 st_id=2，depends_on=["st-2"] ✓

实际上是正确的。**撤回此条。**

#### 3.2 `_handle_sag_task_plan_update` 的 context 覆盖了原有 context

**位置:** diff L+1871

```python
updated_subtasks = [
    {**s, "status": new_status, **(({"context": context}) if context else {})}
    if s["id"] == subtask_id else s
    for s in plan["subtasks"]
]
```

当 `context` 有值时，会**完全替换**该 subtask 原有的 `context` 字段。但 subtask 的原始 `context` 包含有价值的生成描述（如 "Write test(s) that capture the expected behavior..."）。用户更新状态时附带的 context 可能是补充信息而非替换。

**建议：** 将更新记录追加到 `result` 字段，保留原始 `context` 不变：

```python
update_fields = {"status": new_status}
if context:
    update_fields["result"] = context  # 区分于原始 context
```

或在文档中明确说明 context 参数是*替换*行为。

#### 3.3 Plan 生成不验证 granularity 对非 TDD 的影响

`_generate_plan` 对 `brainstorm` 和 `none` methodology，`granularity` 参数没有任何效果。只有 `tdd` + `fine` 会多生成一个 "verify coverage" subtask。

**现状：**
- `tdd` + `fine` → 4 subtasks
- `tdd` + `medium`/`coarse` → 3 subtasks
- `brainstorm` + 任何 granularity → 3 subtasks（无区别）
- `none` + 任何 granularity → 3 subtasks（无区别）

**建议：** 
- 方案 A：在非 tdd methodology 下忽略 granularity，schema 描述中说明
- 方案 B：为每种 methodology 实现 granularity 差异（如 brainstorm + fine 添加 "Write ADR" subtask）

当前行为不是 bug，但可能让用户困惑为什么换 granularity 没效果。至少在 plan 返回结果中注明。

#### 3.4 advance 后的 tdd_phase 重置位置可能导致双重 save

**位置:** diff L+1368-1375

```python
# Reset tdd_phase on advance (step completed)
ms = state.get("methodology_state", {})
if ms.get("tdd_phase"):
    state = {
        **state,
        "methodology_state": {**ms, "tdd_phase": None},
    }
```

这段代码在 verification 检查之后、phase/step 推进逻辑之前。如果 verification 检查失败提前返回，不会执行到这里（正确）。但如果 advance 成功，后续逻辑也会调用 `p.save_task_state(task_id, state)` — 此时 state 已包含 tdd_phase=None。

**实际没有问题**（只有一次 save），但代码可读性上，reset 放在 advance 成功路径中（在 save 之前）会更清晰。

---

### MEDIUM

#### 3.5 `_generate_plan` 是纯模板，缺少 step.description 的深度利用

当前 plan 生成是硬编码模板 + step name/description 字符串拼接。对于复杂 step，3 个 subtask 可能粒度不够。

**建议（Phase 3 方向）：** 考虑接受用户传入的 `subtasks` 参数覆盖自动模板，或支持 plan 追加 subtask。当前模板生成是好的起点。

#### 3.6 plan_update 不检查 depends_on 约束

用户可以将 st-3（depends_on=["st-2"]）标为 done，而 st-2 仍是 pending。系统不强制依赖顺序。

**建议：** 添加 warning（不阻断）当更新的 subtask 有未完成的依赖：

```python
if new_status == "done":
    deps = subtask.get("depends_on", [])
    unfinished = [d for d in deps if any(s["id"] == d and s["status"] != "done" for s in subtasks)]
    if unfinished:
        logger.warning("Subtask %s marked done but depends_on %s not completed", subtask_id, unfinished)
```

#### 3.7 plan 文件没有 schema_version

`.sag_plans/<step_id>.json` 没有版本号。如果后续添加字段（如 `estimated_minutes`、`agent_type`），旧 plan 文件无法兼容迁移。

**建议：** 添加 `"plan_version": 1` 字段。

#### 3.8 `_generate_plan` 未处理空 step（无 name/description）

如果 step 只有 `id` 和 `name`（description 为空），生成的 subtask context 中会出现 "described in: " 结尾悬空。

**建议：** 对空 description fallback 到 step name。当前代码 `step_desc = step.get("description", step_name)` 已经有 fallback，但如果 description 是空字符串 `""` 不会触发 fallback。改为：

```python
step_desc = step.get("description") or step_name
```

---

### LOW

#### 3.9 `_add_subtask` 使用 `nonlocal st_id` — 闭包副作用

`_generate_plan` 内嵌的 `_add_subtask` 闭包 mutate 外层 `st_id`。虽然能工作，但不如直接用 `enumerate` 或让调用者管理 ID 更清晰。

**建议：** 低优先级，当前实现足够简单不需要改。

#### 3.10 granularity 的 validation 可以提前到 schema 层

`_handle_sag_task_plan` 手动验证 granularity 值。但 schema 中已有 `"enum": ["fine", "medium", "coarse"]`。如果 Hermes 框架做了 schema 校验，这个运行时检查是冗余的。

**建议：** 保留运行时检查作为防御性编程（Hermes 不一定做 schema validation），但可以不在 review 中计入。

---

## 四、Phase 2 目标达成度

| 计划目标（from superpowers-integration-proposal.md） | 状态 | 评价 |
|------|------|------|
| `sag_task_plan` 工具 | ✅ 完成 | 模板生成 + 文件存储 |
| Plan 存储（`.sag_plans/<step_id>.json`） | ✅ 完成 | Git-tracked，原子写入 |
| Subtask 状态追踪 | ✅ 完成 | `sag_task_plan_update` + 进度同步 |
| TDD 方法论执行器 | ✅ 完成 | red/green 自动切换状态机 |
| Plan 进度注入 | ✅ 完成 | "3/7 subtasks completed" 注入 context |

**额外完成（未在原计划中）：**
- advance 时 TDD phase 自动重置
- brainstorm methodology 模板
- plan 幂等防护（不允许覆盖已有 plan）
- `sample_phases_with_methodology` shared fixture

**未完成（计划中但延后至 Phase 3）：**
- 无（Phase 2 所有计划项均已实现）

---

## 五、安全检查

| 检查项 | 状态 |
|--------|------|
| 路径遍历防护（plan_update 的 plan_path） | ✅ 有 `relative_to` 检查 |
| 输入验证（granularity、status） | ✅ 有白名单验证 |
| 文件写入安全（原子 os.replace） | ✅ 防中断损坏 |
| JSON 解析错误处理 | ✅ 有 try/except |
| shell 注入 | N/A（plan 工具不执行命令） |

---

## 六、与 Phase 1 review 遗留问题的关联

| Phase 1 遗留 | Phase 2 是否处理 |
|-------------|-----------------|
| CI Python 版本矩阵 | ❌ 未处理 |
| release workflow 缺 build 步骤 | ❌ 未处理 |
| 模块拆分 | ❌ 未处理（文件增至 ~2000 行） |

**注意：** `__init__.py` 在 Phase 2 后将达到约 2034 行。Phase 3 添加 dispatch 工具后可能突破 2200 行。**强烈建议在 Phase 3 开始前完成模块拆分。**

---

## 七、合并建议

**判定：可以合并**

没有 CRITICAL 问题。HIGH 问题（3.2 context 覆盖、3.3 granularity 无效果）属于功能语义问题而非 bug — 当前行为可工作，只是可能让用户困惑。建议：

1. **合并前（可选）：** 在 `TASK_PLAN_UPDATE_SCHEMA` 的 `context` 参数描述中明确说明是**替换**而非追加
2. **合并后跟进：** 
   - 添加 `plan_version: 1` 字段（3.7）
   - 修复空 description fallback（3.8，一行改动）
   - 在 Phase 3 前完成模块拆分

---

## 八、测试验证

```
tests/test_plan.py         — 10 tests
tests/test_plan_update.py  — 8 tests  
tests/test_tdd_state.py    — 5 tests
tests/test_context_injection.py — 新增 2 tests (plan progress)
```

所有新增测试与现有测试集无冲突。
