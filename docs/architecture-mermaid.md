---
title: "SagTask 架构图 (Mermaid)"
created: 2026-06-03
---

# SagTask 架构图 (Mermaid)

> GitHub / Obsidian / 任何 Markdown 渲染器自动渲染。
> 如果渲染失败，回退到 [`architecture.txt`](./architecture.txt) 的 ASCII 版本。

---

## 1. 系统全景 (System Overview)

```mermaid
flowchart TB
    User([用户提示])
    GW1[Hermes Gateway<br/>default profile]
    GW2[Hermes Gateway<br/>profile: hbuilder]
    GW3[Hermes Gateway<br/>profile: hexpert]

    subgraph PLUGIN["SagTask Plugin (20 tools × N profiles)"]
        Tools[20 工具<br/>lifecycle/planning/methodology/rules/git]
        Hooks[pre_llm_call hook<br/>on_session_start hook]
    end

    subgraph STORAGE["~/.hermes/sag_tasks/"]
        Active[".active_tasks.json<br/>per-profile active task"]
        Rules[".rules.json<br/>global dev rules"]
        T1[my-project/]
        T2[sagtask-devop/]
        T3[another-task/]
    end

    User --> GW1
    User --> GW2
    User --> GW3
    GW1 & GW2 & GW3 --> PLUGIN
    PLUGIN <--> STORAGE
```

---

## 2. 插件内部结构 (Plugin Internals)

```mermaid
flowchart LR
    subgraph REGISTER["register(ctx)"]
        RT[ctx.register_tool × 20]
        RH[ctx.register_hook]
    end

    subgraph LIFECYCLE["Lifecycle (7)"]
        L1[create]
        L2[status]
        L3[advance]
        L4[pause]
        L5[resume]
        L6[approve]
        L7[list]
    end

    subgraph PLANNING["Planning (5)"]
        P1[plan]
        P2[plan_update]
        P3[dispatch]
        P4[verify]
        P5[review]
    end

    subgraph METHODOLOGY["Methodology (3)"]
        M1[brainstorm]
        M2[debug]
        M3[metrics]
    end

    subgraph RULES["Rules (1)"]
        R1[rules]
    end

    subgraph GIT["Git Ops (4)"]
        G1[commit]
        G2[branch]
        G3[git_log]
        G4[relate]
    end

    REGISTER --> LIFECYCLE
    REGISTER --> PLANNING
    REGISTER --> METHODOLOGY
    REGISTER --> RULES
    REGISTER --> GIT
```

---

## 3. 上下文注入层 (Context Injection Layers)

```mermaid
flowchart TD
    Hook["pre_llm_call hook"] --> L0
    Hook --> L1
    Hook --> L1_5
    Hook --> L2
    Hook --> L2_5
    Hook --> L3
    Hook --> L4a
    Hook --> L4b

    L0["L0 — task/phase/step<br/>每轮 ~50 tokens"]
    L1["L1 — phase/step 名 + 待审批门<br/>变化时注入"]
    L1_5["L1.5 — artifact summaries<br/>变化时注入"]
    L2["L2 — methodology state + plan 进度<br/>变化时注入"]
    L2_5["L2.5 — 智能过滤的 dev rules<br/>变化时 + 首轮"]
    L3["L3 — verification metrics<br/>变化时 + 阻塞时"]
    L4a["L4a — N 个相关任务提示<br/>有关联时"]
    L4b["L4b — 相关任务详情<br/>首轮 / 切换时"]
```

---

## 4. 推进生命周期 (Advance Lifecycle)

```mermaid
stateDiagram-v2
    [*] --> PLAN
    PLAN --> EXECUTE: sag_task_plan
    EXECUTE --> VERIFY: subagent + plan_update
    VERIFY --> ADVANCE: sag_task_verify
    ADVANCE --> GATE: 有 gate
    ADVANCE --> NEXT: 无 gate
    GATE --> PLAN: Approve
    GATE --> [*]: Reject / 等待人工
    NEXT --> PLAN: 进入下一步
    NEXT --> PHASE: 推进到下一 phase
    NEXT --> DONE: task 完成
    PHASE --> PLAN
    DONE --> [*]
```

---

## 5. 任务存储布局 (Storage Layout)

```mermaid
flowchart TB
    ROOT["~/.hermes/sag_tasks/"]
    ROOT --> A1[".active_tasks.json"]
    ROOT --> A2[".rules.json"]
    ROOT --> TASK1["my-project/"]
    ROOT --> TASK2["sagtask-devop/"]

    subgraph TASK["每个 task = 独立 Git 仓库"]
        G[".git/"]
        GI[".gitignore"]
        STATE[".sag_task_state.json<br/>(git-ignored)"]
        METRICS[".sag_metrics.jsonl<br/>(git-ignored)"]
        PLANS[".sag_plans/"]
        ART[".sag_artifacts/"]
        EXEC[".sag_executions/"]
        WT[".sag_worktrees/"]
        SRC["src/"]
        TESTS["tests/"]
        DOCS["docs/"]
    end

    TASK1 -.包含.-> TASK
    TASK2 -.包含.-> TASK
```

---

## 6. 跨会话恢复 (Cross-Session Recovery)

```mermaid
sequenceDiagram
    participant S1 as Session 1
    participant FS as File System<br/>(.sag_task_state.json + Git)
    participant S2 as Session 2 (新会话/重启)
    participant Agent as Hermes Agent

    Note over S1,FS: 工作中
    S1->>FS: 写入 state.json
    S1->>FS: git commit
    Note over S1,FS: ----- 中断 / 重启 -----
    S2->>FS: 读取 .active_tasks.json
    FS-->>S2: _active_task_id
    S2->>S2: on_session_start 恢复
    S2->>Agent: 注入 L0-L4b 上下文
    Agent->>Agent: 继续 step X.Y
```

---

## 7. 与 Agent 框架对比定位 (SagTask vs Others)

```mermaid
flowchart LR
    subgraph FRAMEWORKS["Agent 框架<br/>(造 agent 用)"]
        LG[LangGraph]
        AG[AutoGen]
        CA[CrewAI]
    end

    subgraph SAGTASK["SagTask<br/>(管理 agent 干的项目)"]
        ST1[Phases & Steps]
        ST2[Approval Gates]
        ST3[Cross-session state]
        ST4[Methodology engine]
        ST5[Metrics & verification]
    end

    subgraph USERS["最终用户项目"]
        P1[4 周项目]
        P2[多 Agent 协作]
        P3[需要审批的部署]
    end

    FRAMEWORKS -.生成.-> Agents[AI Agent]
    Agents --> SAGTASK
    SAGTASK --> USERS
```

**TL;DR:** 用 LangGraph/AutoGen/CrewAI *造* agent，用 SagTask *管* agent 干的项目。

---

*对应源文件：*
- *完整 ASCII 参考：[`architecture.txt`](./architecture.txt)*
- *README 内的简版 ASCII（嵌入用）：[`../README.md`](../README.md#-architecture)*
- *Cast 演示：[`demo.cast`](./demo.cast) （用 `asciinema play docs/demo.cast` 播放）*
