# SagTask × Superpowers 集成方案

## 背景

Superpowers 是一套为 AI 编码代理设计的系统化开发方法论，包含 14 个核心技能（skills），覆盖 TDD、计划制定、子代理派遣、代码审查、系统化调试等完整开发生命周期。

SagTask 当前管理任务的 **结构**（phases/steps/gates），但不管理任务的 **执行方法论**。将 Superpowers 的方法论能力引入 SagTask，可以让每个 step 不仅有"做什么"的定义，还有"怎么做"的系统化指导。

---

## 一、集成目标

| 目标 | 说明 |
|------|------|
| 方法论绑定 | 每个 step 可绑定执行方法论（TDD、brainstorming、debugging 等） |
| 子代理编排 | 支持将 step 拆分为子任务，派遣并行子代理执行 |
| 质量门控增强 | 在现有 approval gate 基础上增加自动化质量验证 |
| 计划-执行分离 | 支持 plan → review → execute 的分阶段工作模式 |
| 验证闭环 | 每个 step 完成前强制验证（测试通过、构建成功等） |

---

## 二、设计方案

### 方案概述

将 Superpowers 的能力以三个层次集成到 SagTask：

```
Layer 3: Orchestration（编排层）
  ├── 子代理派遣与并行执行
  ├── 计划文件生成与执行跟踪
  └── 多代理工作流协调

Layer 2: Methodology（方法论层）
  ├── Step 方法论绑定（TDD/brainstorming/debugging）
  ├── 质量验证规则
  └── 代码审查触发条件

Layer 1: Context（上下文层）
  ├── 活跃方法论注入到 pre_llm_call
  ├── 计划状态追踪
  └── 验证结果记录
```

### 2.1 Step Schema 扩展

在现有 step 定义中增加 `methodology` 字段：

```json
{
  "id": "step-2-bom-engine",
  "name": "BOM 展开引擎实现",
  "description": "实现 BOM 递归展开算法",
  "methodology": {
    "type": "tdd",
    "config": {
      "coverage_threshold": 80,
      "test_first": true
    }
  },
  "verification": {
    "commands": ["pytest tests/ --cov=src --cov-fail-under=80"],
    "must_pass": true
  },
  "subtasks": {
    "strategy": "subagent",
    "parallel": true,
    "tasks": []
  }
}
```

支持的 methodology types：

| Type | 对应 Superpowers 技能 | 用途 |
|------|----------------------|------|
| `tdd` | test-driven-development | 先测试后实现 |
| `brainstorm` | brainstorming | 设计探索，需用户审批后实现 |
| `debug` | systematic-debugging | 根因分析驱动的修复 |
| `plan-execute` | writing-plans + executing-plans | 计划-执行分离 |
| `parallel-agents` | subagent-driven-development | 子代理并行执行 |
| `review` | requesting-code-review | 审查驱动的改进 |
| `none` | (默认) | 无特定方法论约束 |

### 2.2 新增工具

#### `sag_task_plan` — 为当前 step 生成执行计划

```json
{
  "name": "sag_task_plan",
  "description": "Generate a bite-sized execution plan for the current step. Each subtask is 2-5 minutes of work with complete context.",
  "parameters": {
    "type": "object",
    "properties": {
      "sag_task_id": {"type": "string"},
      "granularity": {
        "type": "string",
        "enum": ["fine", "medium", "coarse"],
        "description": "Task decomposition granularity. 'fine' = 2-5 min tasks, 'medium' = 10-15 min, 'coarse' = 30+ min."
      }
    }
  }
}
```

输出存储为 `plan.json` 在 step 目录下：

```json
{
  "step_id": "step-2-bom-engine",
  "generated_at": "2026-05-06T10:00:00Z",
  "subtasks": [
    {
      "id": "st-1",
      "title": "Write failing test for recursive BOM expansion",
      "status": "pending",
      "depends_on": [],
      "context": "Test should verify 3-level depth limit...",
      "verification": "pytest tests/test_bom.py::test_recursive_expand -v"
    },
    {
      "id": "st-2",
      "title": "Implement minimal BOM expand function",
      "status": "pending",
      "depends_on": ["st-1"],
      "context": "Make test_recursive_expand pass with minimal code...",
      "verification": "pytest tests/test_bom.py -v"
    }
  ]
}
```

#### `sag_task_dispatch` — 派遣子代理执行子任务

```json
{
  "name": "sag_task_dispatch",
  "description": "Dispatch a subtask to a fresh subagent for execution. The subagent gets only the subtask context, not full session history.",
  "parameters": {
    "type": "object",
    "properties": {
      "sag_task_id": {"type": "string"},
      "subtask_id": {"type": "string", "description": "Subtask ID from the plan."},
      "agent_type": {
        "type": "string",
        "enum": ["implementer", "reviewer", "debugger"],
        "description": "Type of subagent to dispatch."
      },
      "parallel": {
        "type": "boolean",
        "default": false,
        "description": "If true, dispatch without waiting for completion."
      }
    },
    "required": ["subtask_id", "agent_type"]
  }
}
```

#### `sag_task_verify` — 运行 step 验证命令

```json
{
  "name": "sag_task_verify",
  "description": "Run verification commands for the current step. Must pass before sag_task_advance.",
  "parameters": {
    "type": "object",
    "properties": {
      "sag_task_id": {"type": "string"},
      "commands": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Override verification commands. Defaults to step's verification config."
      }
    }
  }
}
```

#### `sag_task_review` — 触发代码审查

```json
{
  "name": "sag_task_review",
  "description": "Request code review for the current step's changes. Uses two-stage review: spec compliance first, then code quality.",
  "parameters": {
    "type": "object",
    "properties": {
      "sag_task_id": {"type": "string"},
      "scope": {
        "type": "string",
        "enum": ["step", "phase", "full"],
        "description": "Review scope: current step changes, current phase, or full task."
      }
    }
  }
}
```

### 2.3 Context Injection 增强

在 `pre_llm_call` 注入中追加方法论上下文：

```
## Active Task: sc-mrp-v1
- Status: **active**
- Phase: BOM引擎  |  Step: BOM展开引擎实现
- Methodology: **TDD** (coverage ≥ 80%, test-first enforced)
- Plan progress: 3/7 subtasks completed
- Verification: pytest pending (last run: 2 passed, 1 failed)
- ⚠️ RED phase: write failing test before implementation
```

### 2.4 Advance 增强：验证前置

修改 `sag_task_advance` 逻辑：

```python
def _handle_sag_task_advance(args):
    # ... existing logic ...

    # NEW: Check verification requirements
    step_config = current_step.get("verification", {})
    if step_config.get("must_pass", False):
        verification_result = state.get("last_verification", {})
        if not verification_result.get("passed", False):
            return {
                "ok": False,
                "error": "Verification not passed. Run sag_task_verify before advancing.",
                "last_verification": verification_result,
            }

    # ... proceed with advance ...
```

### 2.5 Task State 扩展

```json
{
  "sag_task_id": "sc-mrp-v1",
  "methodology_state": {
    "current_methodology": "tdd",
    "tdd_phase": "red",
    "plan_file": ".sag_plans/step-2-bom-engine.json",
    "subtask_progress": {"total": 7, "completed": 3, "in_progress": 1},
    "last_verification": {
      "passed": false,
      "timestamp": "2026-05-06T10:30:00Z",
      "results": [
        {"command": "pytest tests/", "exit_code": 1, "summary": "2 passed, 1 failed"}
      ]
    },
    "review_state": {
      "requested": true,
      "spec_review": "passed",
      "quality_review": "pending"
    }
  }
}
```

---

## 三、执行路线

### Phase 1: 基础层（2 周）

**目标：** 验证可行性，建立最小可用框架

| 任务 | 产出 | 优先级 |
|------|------|--------|
| Step schema 扩展 | `methodology` + `verification` 字段 | P0 |
| `sag_task_verify` 工具 | 运行验证命令并记录结果 | P0 |
| Advance 验证前置 | 阻止未验证的 step advance | P0 |
| Context injection 增强 | 方法论状态注入 | P1 |
| 状态 schema 版本化 | `schema_version: 2` + 迁移逻辑 | P1 |

**验收标准：**
- 创建带 verification 的 task，advance 时自动检查
- pre_llm_call 注入包含方法论上下文

### Phase 2: 计划层（2 周）

**目标：** 实现 plan → execute 的分离能力

| 任务 | 产出 | 优先级 |
|------|------|--------|
| `sag_task_plan` 工具 | 生成结构化子任务计划 | P0 |
| Plan 存储 | `.sag_plans/<step_id>.json` | P0 |
| Subtask 状态追踪 | 计划中子任务的 pending/done 状态 | P1 |
| TDD 方法论执行器 | RED-GREEN-REFACTOR 状态机 | P1 |
| Plan 进度注入 | "3/7 subtasks completed" 注入 context | P2 |

**验收标准：**
- 为一个 step 生成计划，按计划逐步执行，追踪进度
- TDD 模式下，系统提示当前处于 RED/GREEN/REFACTOR 阶段

### Phase 3: 编排层（3 周）

**目标：** 实现子代理派遣和并行执行

| 任务 | 产出 | 优先级 |
|------|------|--------|
| `sag_task_dispatch` 工具 | 子代理上下文构建与派遣 | P0 |
| 子代理结果收集 | 执行结果写回 plan.json | P0 |
| 并行执行支持 | 独立子任务并发执行 | P1 |
| 两阶段审查 | spec review → quality review | P1 |
| `sag_task_review` 工具 | 触发代码审查 | P2 |

**验收标准：**
- 派遣子代理执行子任务，结果自动收集
- 独立子任务可以并行执行
- 审查结果记录在 task state 中

### Phase 4: 高级集成（2 周）

**目标：** 完善方法论闭环和工作流

| 任务 | 产出 | 优先级 |
|------|------|--------|
| Brainstorming 方法论 | 设计探索 → 用户审批 → 实现 | P1 |
| Debugging 方法论 | 根因分析 → 假设验证 → 修复 | P1 |
| Git worktree 集成 | 子代理在隔离 worktree 中工作 | P2 |
| 方法论自动推荐 | 根据 step 描述自动建议方法论 | P2 |
| Metrics 收集 | 执行时间、测试覆盖率趋势 | P3 |

**验收标准：**
- Brainstorming 模式产出设计文档并等待审批
- 子代理在独立 worktree 中执行，不干扰主分支

---

## 四、架构决策

### 决策 1：方法论执行 — 建议式 vs 强制式

| 方案 | 优点 | 缺点 |
|------|------|------|
| **建议式**（推荐） | 灵活，不阻断工作流 | 可能被忽略 |
| 强制式 | 保证方法论执行 | 增加复杂度，可能阻断 |

**推荐：** 默认建议式，gate-level 可配置为强制式。context injection 中提示当前方法论，但不阻止操作。verification + must_pass 提供硬约束点。

### 决策 2：子代理接口 — Hermes 原生 vs 外部编排

| 方案 | 优点 | 缺点 |
|------|------|------|
| **Hermes 原生子代理** | 架构统一，状态共享 | 依赖 Hermes 子代理 API |
| 外部编排（subprocess） | 解耦，可复用 | 上下文传递复杂 |
| **混合**（推荐） | 先 subprocess 原型，后迁移原生 | 迁移成本 |

**推荐：** Phase 3 先用 subprocess 调用 `hermes` CLI 实现子代理派遣，验证模型后再迁移到 Hermes 原生子代理 API。

### 决策 3：Plan 存储位置

| 方案 | 优点 | 缺点 |
|------|------|------|
| task_state.json 内嵌 | 简单 | state 文件膨胀 |
| **独立 plan 文件**（推荐） | 清晰分离，可独立版本化 | 多文件管理 |
| Git 版本化 plan | 历史可追溯 | 增加 commit 噪声 |

**推荐：** `.sag_plans/<step_id>.json` 独立文件，Git-tracked（计划是有价值的产出物）。task_state.json 只存引用路径。

### 决策 4：验证执行环境

| 方案 | 优点 | 缺点 |
|------|------|------|
| Task 目录内执行 | 简单 | 可能缺少依赖 |
| **用户指定 working_dir** | 灵活 | 配置复杂 |
| Docker 容器 | 隔离 | 重量级 |

**推荐：** 验证命令在 task 根目录执行，支持 `verification.cwd` 字段覆盖。

---

## 五、与现有设计的兼容性

### 不破坏现有功能

- 所有新字段（`methodology`、`verification`、`subtasks`）为 **可选**
- 现有 task state 无这些字段时行为不变
- `schema_version` 迁移保证旧数据兼容
- 新工具是新增的，不修改现有 11 个工具的行为

### 渐进采用路径

```
Level 0: 现状 — 纯手动方法论
Level 1: 添加 verification — advance 前自动验证
Level 2: 添加 methodology — context 注入方法论提示
Level 3: 添加 plan — 结构化子任务分解
Level 4: 添加 dispatch — 子代理编排执行
```

用户可以在任何 level 停下，不需要一步到位。

---

## 六、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 方法论注入增加 context 开销 | token 消耗增加 | 设置注入上限（200 tokens），可配置关闭 |
| 子代理执行失败丢失上下文 | 子任务需要重做 | 子代理结果持久化到文件，支持重试 |
| 验证命令执行不安全 | 安全风险 | 白名单机制 + sandbox 选项 |
| 方法论强制过于侵入 | 用户体验差 | 默认建议式，gate 级别可配置强制 |
| Plan 粒度不合适 | 子任务太大或太小 | 支持 fine/medium/coarse 粒度选择 |
| Hermes 子代理 API 变更 | 集成中断 | 先用 subprocess 原型，解耦接口层 |

---

## 七、成功指标

| 指标 | 目标 |
|------|------|
| Step 完成前验证通过率 | ≥ 90% |
| 使用方法论绑定的 step 占比 | ≥ 50%（6个月后） |
| 子代理首次执行成功率 | ≥ 70% |
| 计划覆盖率（有 plan 的 step） | ≥ 60% |
| 用户对方法论提示的采纳率 | ≥ 40% |

---

## 八、参考

- Superpowers 技能目录：`~/.claude/plugins/cache/claude-plugins-official/superpowers/5.1.0/skills/`
- SagTask 设计文档：`docs/design.md`
- SagTask 现有问题清单：`docs/review.md`
- Superpowers 核心原则：test-first, verify-before-claim, plan-then-execute, fresh-context-per-agent
