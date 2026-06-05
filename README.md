<div align="center">

# SagTask

### Long-running task management for AI agents — Steps/Phases, Approvals, Git-tracked.

[![Version](https://img.shields.io/badge/version-2.2.1-blue.svg)]()
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)]()
[![Tests](https://img.shields.io/badge/tests-264%20passing-brightgreen.svg)]()
[![Hermes](https://img.shields.io/badge/Hermes-Plugin-purple.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)]()

**The missing project manager for your AI agent.** SagTask turns a 4-week build into a sequence of phases and steps, with human-in-the-loop approval gates, automatic Git commits, and per-session context recovery — so your agent never loses its place.

[Quick Install](#-quick-install) · [Why SagTask?](#-why-sagtask) · [Demo](#-demo) · [Architecture](#-architecture) · [Compare](#-where-sagtask-fits)

</div>

---

## 🤔 Why SagTask?

You start an AI agent on a 4-week project. By **day 3**, it's forgotten the original goals. By **day 7**, it's contradicted last week's design. By **day 14**, you've lost track of what's done and what's broken.

**SagTask fixes this** by treating AI agent work like a real engineering project:

| Without SagTask | With SagTask |
|----------------|-------------|
| Agent loses context between sessions | **Cross-session recovery** — task state lives in Git, not RAM |
| No way to know "where are we?" | **Always-visible status** — phase, step, pending gates |
| Free-form prose TODO lists | **Structured workflow** — phases → steps → gates → metrics |
| One big prompt = chaos | **Methodology engine** — TDD, brainstorm, debug, plan-execute |
| Can't pause/resume safely | **Snapshot + resume** — full execution context saved |
| No audit trail | **Git-backed** — every advance = a commit, full history |
| Approval = manual Slack message | **Built-in gates** — `Approve` / `Reject` / `Request Changes` |

---

## ⚡ Quick Install

```bash
curl -fsSL https://raw.githubusercontent.com/ethanchen669/sagtask/main/install.sh | bash
```

Then restart your Hermes gateway. That's it — **20 new tools** are loaded:

```
✓ sag_task_create        ✓ sag_task_advance      ✓ sag_task_verify
✓ sag_task_status        ✓ sag_task_approve      ✓ sag_task_review
✓ sag_task_list          ✓ sag_task_pause        ✓ sag_task_brainstorm
✓ sag_task_plan          ✓ sag_task_resume       ✓ sag_task_debug
✓ sag_task_dispatch      ✓ sag_task_commit       ✓ sag_task_metrics
✓ sag_task_plan_update   ✓ sag_task_branch       ✓ sag_task_git_log
                          ✓ sag_task_relate       ✓ sag_task_rules
```

<details>
<summary><b>Manual install (if you prefer)</b></summary>

```bash
git clone https://github.com/ethanchen669/sagtask.git ~/.hermes/plugins/sagtask
# Restart your Hermes gateway to load the plugin
```

</details>

<details>
<summary><b>Self-update via /sagtask slash command</b></summary>

```
/sagtask update    → Check GitHub releases, download + install to all profiles
/sagtask version   → Show current installed version
/sagtask help      → Show usage
```

</details>

---

## 🎬 Demo

> **The agent drives SagTask itself.** No slash commands, no human babysitting — the agent *calls tools*, reads structured JSON back, and reacts. Below: an agent building a token-bucket rate limiter with TDD, end-to-end. Every result shape is exactly what the real handlers return; the `[SagTask]` line is injected before each turn to keep the agent oriented.

```
USER: Add a token-bucket rate limiter to our API client, TDD.

[SagTask] task= status=none phase= step=
agent: New long-running feature. I'll model it as a phased SagTask so state
       survives across sessions, then drive it with tool calls.

agent → sag_task_create({
  sag_task_id: "rate-limiter-v1", name: "Token-bucket rate limiter",
  phases: [{ id:"phase-1", name:"Implement", steps:[
    { id:"step-1", name:"Core limiter",
      methodology:{ type:"tdd", config:{ coverage_threshold:90, test_first:true } },
      verification:{ commands:["pytest tests/test_limiter.py -q"], must_pass:true } },
    { id:"step-2", name:"Wire into client",
      gate:{ id:"gate-ship", question:"Ship limiter to prod client?",
             choices:["Approve","Reject","Request Changes"] } }]}]})
← { "ok": true, "current_phase": "phase-1", "current_step": "step-1",
    "message": "Task 'Token-bucket rate limiter' created with 1 phase(s). Git repo initialized." }

[SagTask] task=rate-limiter-v1 status=active phase=phase-1 step=step-1
- Phase: Implement | Step: Core limiter
agent: On step-1 (TDD). Break it into subtasks so I can track progress.

agent → sag_task_plan({ granularity: "fine" })
← { "ok": true, "step_id": "step-1", "plan_file": ".sag_plans/step-1.json", "total_subtasks": 3,
    "subtasks": [ {"id":"st-1","title":"Write failing tests for token bucket"},
                  {"id":"st-2","title":"Implement minimal TokenBucket"},
                  {"id":"st-3","title":"Refactor + edge cases"} ] }

agent: RED first. (writes tests/test_limiter.py) They should fail. Verifying RED.

agent → sag_task_verify({})
← { "ok": true, "passed": false,
    "results": [{ "command":"pytest tests/test_limiter.py -q", "exit_code":1,
                  "stdout":"E  ImportError: cannot import name 'TokenBucket'" }],
    "message": "Verification failed (1 commands)." }

agent: Good — RED confirmed (tdd_phase=red recorded). (implements TokenBucket) Now GREEN.

agent → sag_task_verify({})
← { "ok": true, "passed": true,
    "results": [{ "command":"pytest tests/test_limiter.py -q", "exit_code":0,
                  "stdout":"6 passed in 0.11s" }],
    "message": "Verification passed (1 commands)." }

[SagTask] task=rate-limiter-v1 status=active phase=phase-1 step=step-1
agent: GREEN. must_pass is satisfied — advancing.

agent → sag_task_advance({ commit_message:"[step-1] token-bucket core, tests green" })
← { "ok": true, "previous_step":"step-1", "current_step":"step-2",
    "message": "Advanced to phase-1/step-2. New branch 'step/phase-1/step-2' created." }

[SagTask] task=rate-limiter-v1 status=active phase=phase-1 step=step-2
- Phase: Implement | Step: Wire into client
agent: step-2 carries gate-ship. I surface the question to the user — I don't
       self-approve. User says "Approve." Recording the decision.

agent → sag_task_approve({ gate_id:"gate-ship", decision:"Approve", comment:"LGTM, ship it" })
← { "ok": true, "status":"completed", "message": "All phases completed. Task finished!" }

[SagTask] task=rate-limiter-v1 status=completed phase=phase-1 step=step-2
agent: Done. Limiter merged, gate approved, state Git-committed and recoverable.
```

> **The point:** the agent treats a feature the way a senior engineer would — phased, test-first, checkpointed to Git, and blocked at human gates. Try `sag_task_advance` before tests pass and it **refuses** (`must_pass`). Restart the gateway mid-task and the agent picks up exactly where it left off.

---

## 🏗️ Architecture

📊 **Full diagrams:** [Mermaid (renders on GitHub)](docs/architecture-mermaid.md) · [ASCII reference](docs/architecture.txt) · [asciinema cast](docs/demo.cast) (`asciinema play docs/demo.cast`)

```
   default profile      profile: hbuilder      profile: hexpert      ← Multi-Agent
  ┌──────────────┐     ┌──────────────┐       ┌──────────────┐         (N Hermes
  │ Hermes Agent │     │ Hermes Agent │       │ Hermes Agent │          profiles,
  └──────┬───────┘     └──────┬───────┘       └──────┬───────┘          same plugin)
         │ tool call          │                      │
         └────────────────────┼──────────────────────┘
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│                   SagTask Plugin  (20 tools)                        │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐         │
│  │ Lifecycle  │ │ Planning   │ │ Methodology│ │ Git Ops    │         │
│  │ create     │ │ plan       │ │ brainstorm │ │ commit     │         │
│  │ status     │ │ plan_update│ │ debug      │ │ branch     │         │
│  │ advance    │ │ dispatch   │ │ metrics    │ │ git_log    │         │
│  │ pause/resume││ verify     │ │ (tdd via   │ │ relate     │         │
│  │ approve    │ │ review     │ │  verify)   │ │            │         │
│  │ list       │ │            │ │            │ │            │         │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘         │
│  ┌──────────────────────────┐  ┌──────────────────────────────────┐  │
│  │  Rules engine (sag_task_ │  │  pre_llm_call Hook               │  │
│  │  rules)                  │  │  — Layered Context Injection —   │  │
│  │  12 built-in rules,      │─▶│  L0  task/phase/step (every turn)│  │
│  │  global + per-task,      │  │  L1  gates   L1.5 artifacts      │  │
│  │  smart-filtered by       │  │  L2  methodology  L2.5 rules     │  │
│  │  phase + methodology     │  │  L3  metrics   L4a/b related     │  │
│  └──────────────────────────┘  └────────────────┬─────────────────┘  │
└───────────────────────────────────────────────┼─────────────────────┘
                                                 │ persists to
                                                 ▼
   ~/.hermes/sag_tasks/         ← shared task pool across ALL profiles
   ├── .active_tasks.json         per-profile active task pointer
   ├── .rules.json                global development rules (shared)
   └── <task_id>/   (Git repo)
       ├── .sag_task_state.json   phases / steps / gates / rules
       ├── .sag_metrics.jsonl     append-only verification log
       ├── .sag_plans/            subtask JSON (git-tracked)
       ├── .sag_artifacts/        auto-captured git diffs
       └── src/, tests/, docs/    your code
```

**Two things make this work:**

- **NOT a memory provider.** SagTask coexists with any memory system. It injects task context via the `pre_llm_call` hook — so the LLM always knows what phase it's in, what's blocked, and what just changed, **plus** the relevant subset of the 12 development rules for the current phase/methodology.
- **Multi-Agent by design.** Every Hermes profile loads the same plugin but tracks its **own** active task via `.active_tasks.json`, while all profiles share one task pool. One agent can `relate` its task to another's for cross-pollination.

---

## ⚖️ Where SagTask fits

SagTask is a **Hermes plugin**, not an agent framework. The fairest comparison isn't to agent *runtimes* — it's to other tools that give a coding agent **engineering discipline**. The closest peer is **Claude + Superpowers**.

### vs Claude + Superpowers (the closest peer)

[Superpowers](https://github.com/obra/superpowers) gives a coding agent a library of **skills** — markdown playbooks for TDD, planning, debugging, code review, subagent dispatch. SagTask borrows several of these methodologies (its own docs credit the lineage). The difference is **guidance vs. enforcement, and stateless vs. stateful**:

| | **Superpowers** | **SagTask** |
|--|-----------------|-------------|
| **What it is** | Skills = instructions injected into the prompt | Stateful infrastructure = tools + persisted state |
| **How it works** | Agent *reads* a skill and is asked to follow it | Tool calls *mutate* durable state; some transitions are *blocked* in code |
| **State** | Stateless — relies on the host's ephemeral TODO list per session | **Git repo per task** + `.sag_task_state.json`; survives gateway restarts |
| **Approval gates** | A skill can *recommend* pausing for a human | `must_pass` verification and gates **mechanically block** `advance` |
| **Progress tracking** | In-session TodoWrite (lost when the session ends) | Phases/steps/subtasks + metrics event log, queryable across sessions |
| **Methodology** | TDD / debugging / brainstorming as prose skills | Same methodologies, but as **state machines** (e.g. TDD auto-flips red→green on verify) |
| **Best at** | Teaching *how* to do good engineering, portably across hosts | Remembering *where you are* and *enforcing* the process over weeks |

**They're complementary, not exclusive.** Superpowers shapes *how* the agent works in a session; SagTask remembers *what's done* and *what's blocked* across many sessions. You can run both.

### vs agent frameworks (LangGraph / AutoGen / CrewAI)

These are a **different layer** — frameworks for *building* agents (graphs, conversations, crews), each with its own strong persistence story (LangGraph checkpointers, AutoGen `save_state`, CrewAI memory) and, for AutoGen/CrewAI, multi-agent orchestration as a core strength. SagTask doesn't compete with them and doesn't replace a runtime. What it adds — and what these frameworks leave you to wire yourself — is a ready-made **phases → gates → verify → commit** project workflow with methodology scaffolding and a Git trail. Use a framework to *build* the agent; use SagTask (on Hermes) to *manage the multi-week project* it works on.

**Honest caveat:** SagTask runs **inside Hermes**, not standalone or inside other frameworks. The *ideas* (phased Git-backed tasks, gates, methodology scaffolding) port anywhere — the plugin doesn't.


---

## 🧠 Multi-Agent Collaboration

Hermes supports multiple **profiles** (agents) that share the same `~/.hermes/sag_tasks/` directory — all agents collaborate on the same pool of tasks. But each agent tracks its **own** active task independently:

```
~/.hermes/
├── plugins/sagtask/              ← Default profile plugin
├── profiles/
│   ├── hbuilder/plugins/sagtask/ ← Profile "hbuilder" plugin
│   └── hexpert/plugins/sagtask/  ← Profile "hexpert" plugin
└── sag_tasks/                    ← Shared task pool (all agents)
    ├── .active_tasks.json        ← Per-profile active task tracking
    ├── my-project/               ← Task Git repo (shared)
    └── another-task/             ← Task Git repo (shared)
```

**`.active_tasks.json`** tracks which task each agent is working on:

```json
{
  "default": "my-project",
  "hbuilder": "sagtask-devop",
  "hexpert": null
}
```

**How it works:**
- Each profile's `SagTaskPlugin` derives its profile ID from the `_hermes_home` path (`~/.hermes/profiles/<name>`)
- `_active_task_id` is a `@property` that transparently reads/writes the correct entry in the dict
- **Zero changes needed in handlers or hooks** — the property abstraction handles everything
- Legacy `.active_task` files are auto-migrated on first read

**Installation:** `install.sh` and `/sagtask update` automatically install the plugin to **all** profiles:

```bash
curl -fsSL https://raw.githubusercontent.com/ethanchen669/sagtask/main/install.sh | bash
# Installs to ~/.hermes/plugins/sagtask/ + every ~/.hermes/profiles/*/plugins/sagtask/
```

Or manually:

```bash
git clone https://github.com/ethanchen669/sagtask.git ~/.hermes/plugins/sagtask
# Restart your Hermes gateway to load the plugin
```

### Self-Update

SagTask has a built-in `/sagtask` slash command:

```
/sagtask update    → Check GitHub releases, download + install to all profiles
/sagtask version   → Show current installed version
/sagtask help      → Show usage
```

---

## 🎯 12 Rules + Smart Context Injection

**The headline feature.** Long-running agents drift — they forget conventions, skip verification, over-engineer. SagTask ships **12 built-in development rules** and, crucially, injects only the *relevant* ones into each LLM call based on the current methodology and phase. The agent gets the right guardrails at the right moment, without burning tokens on rules that don't apply right now.

```
            ┌──────────────────────────────────────────────┐
            │  12 Development Rules                        │
            │  (global defaults + per-task overrides)      │
            └───────────────────────┬──────────────────────┘
                                    │  smart filter by state
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
  methodology=tdd            pending gate              methodology=debug
  → rule-9                   → rule-3, rule-10         → rule-12, rule-4
  (tests encode intent)      (surgical, checkpoint)    (fail loudly, goal-driven)
        └───────────────────────────┼───────────────────────────┘
                                    ▼
                   injected at L2.5 of pre_llm_call
                   (only what's relevant, ~1 line each)
```

### The 12 Rules

| # | Rule | Category |
|---|------|----------|
| 1 | **Think Before Editing.** State assumptions explicitly; ask when uncertain; present options when ambiguous. | thinking |
| 2 | **Simplicity first.** Minimum code that solves the problem. No speculative design, no unrequested features. | thinking |
| 3 | **Surgical changes.** Touch only necessary code; don't refactor unrequested parts; match existing style. | process |
| 4 | **Goal-driven.** Define verification criteria and loop until met, don't follow rigid step sequences. | process |
| 5 | **LLM for judgment only.** Use LLM for classification, drafting, summarization, extraction. Use code for routing, retries, deterministic transforms. | quality |
| 6 | **Manage Context Deliberately.** Treat context as a limited resource. For long tasks, maintain compact checkpoints: objective, files changed, commands run, artifacts produced, unresolved assumptions, next step. Load targeted files first; avoid broad dumps. Never skip required reading or verification to save context. | quality |
| 7 | **Surface conflicts, don't average them.** When patterns contradict, pick one and explain; flag the other for cleanup. | thinking |
| 8 | **Read Before Writing.** Check exports, callers, shared utilities before adding code. Ask when unclear. | process |
| 9 | **Tests encode intent.** Tests should encode why behavior matters, not just pass when business logic changes. | quality |
| 10 | **Checkpoint every step.** Summarize progress, verify state, list remaining work. Stop and restate position when lost. | process |
| 11 | **Match codebase conventions.** Consistency over personal preference. Raise disagreements explicitly, don't silently change style. | style |
| 12 | **Fail loudly.** Skipping tests and saying 'tests pass' is misleading. Surface uncertainty by default. | quality |

### Smart Injection — only the relevant rules, only when needed

Rules are injected into `pre_llm_call` context at **L2.5**, filtered by current state so the agent never sees all 12 at once (except the first turn):

| Trigger | Rules Injected |
|---------|---------------|
| methodology = `tdd` | rule-9 (tests encode intent) |
| methodology = `brainstorm` | rule-1 (think first), rule-7 (surface conflicts) |
| methodology = `debug` | rule-12 (fail loudly), rule-4 (goal-driven) |
| Pending gates | rule-3 (surgical changes), rule-10 (checkpoint) |
| First turn | All 12 rules |
| No special state | rule-1, rule-2, rule-12 (core three) |

### Storage & Management

- **Global rules:** `~/.hermes/sag_tasks/.rules.json` — shared across all tasks
- **Per-task overrides:** `.sag_task_state.json` → `rules` field — task-specific additions/toggles

```bash
sag_task_rules action: list                                        # list current task's rules
sag_task_rules action: add content: "Use type hints" category: "quality" task_id: "my-project"
sag_task_rules action: add content: "All PRs need 2 approvals" category: "process"   # global
sag_task_rules action: toggle rule_id: "rule-6" task_id: "my-project"
sag_task_rules action: remove rule_id: "rule-custom-abc123" task_id: "my-project"
```

---

## 🧭 Methodology System

**Each step can declare *how* it should be done.** SagTask doesn't just track *what* step you're on — it scaffolds the *method*, implemented as state machines (not just prompts). TDD auto-flips red→green on verify; debug walks reproduce→diagnose→fix; brainstorm forces option generation before commitment.

| Type | Workflow | State machine? |
|------|----------|:--------------:|
| `tdd` | RED → GREEN → REFACTOR cycle, auto-transitions on `sag_task_verify` | ✅ |
| `brainstorm` | Generate 3+ options → user selects → implement | ✅ |
| `debug` | Reproduce → diagnose (record hypothesis) → fix | ✅ |
| `plan-execute` | Plan subtasks → execute sequentially → verify each | ✅ |
| `none` | No methodology constraint (default) | — |

The active methodology drives **L2 context injection** (phase/progress) and feeds the [Smart Context Injection](#-12-rules--smart-context-injection) rule filter above — e.g. a `tdd` step automatically surfaces rule-9 *(tests encode intent)*.

---

## Tools (20)

### Task Lifecycle

| Tool | Description |
|------|-------------|
| `sag_task_create` | Create task with phased steps/gates, init Git + GitHub repo |
| `sag_task_status` | Show current phase/step/pending gates |
| `sag_task_advance` | Move to next step/phase (blocks if verification fails) |
| `sag_task_pause` | Snapshot execution context for later resume |
| `sag_task_resume` | Restore from most recent paused execution |
| `sag_task_approve` | Submit approval decision for a pending gate |
| `sag_task_list` | List all tasks with status |

### Planning & Execution

| Tool | Description |
|------|-------------|
| `sag_task_plan` | Generate structured subtask plan for the current step |
| `sag_task_plan_update` | Update subtask status (done/failed), sync progress |
| `sag_task_dispatch` | Build subagent context for a subtask, optional worktree isolation |
| `sag_task_verify` | Run verification commands, record pass/fail |
| `sag_task_review` | Build structured review prompt (step/phase/full scope) |

### Methodology

| Tool | Description |
|------|-------------|
| `sag_task_brainstorm` | Design exploration → option selection workflow |
| `sag_task_debug` | Systematic debugging: reproduce → diagnose → fix |
| `sag_task_metrics` | Query verification stats, coverage trends, throughput |

### Rules

| Tool | Description |
|------|-------------|
| `sag_task_rules` | Manage development rules: list/add/update/remove/toggle |

12 built-in rules auto-loaded on task creation. Smart context injection selects relevant rules based on methodology and phase. See [12 Rules + Smart Context Injection](#-12-rules--smart-context-injection) for details.

### Git Operations

| Tool | Description |
|------|-------------|
| `sag_task_commit` | Stage all + commit with message |
| `sag_task_branch` | Create + push new branch |
| `sag_task_git_log` | Show recent commit history |
| `sag_task_relate` | Link two tasks as cross-pollination partners |

---

## 🗂️ Source Layout

```
src/sagtask/
├── __init__.py          ← register(), re-exports
├── plugin.py            ← SagTaskPlugin class, layered context injection
├── hooks.py             ← pre_llm_call, on_session_start
├── schemas.py           ← 20 tool JSON schemas
├── _utils.py            ← constants, shared helpers
├── rules.py             ← 12 default rules, CRUD, smart context selection
└── handlers/
    ├── __init__.py      ← _tool_handlers dispatch dict
    ├── _lifecycle.py    ← create, status, advance, pause, resume, approve, list
    ├── _plan.py         ← plan, plan_update, verify, brainstorm, debug
    ├── _orchestration.py← dispatch, review, context builders
    ├── _metrics.py      ← metrics query handler
    └── _git.py          ← commit, branch, git_log, relate
```

### Plugin Registration

```python
register(ctx)
    ├── ctx.register_tool("sag_task_*", ...) × 20
    ├── ctx.register_hook("pre_llm_call", ...)    # layered context injection
    └── ctx.register_hook("on_session_start", ...) # restore active task
```

---

## Context Injection — Layered System

SagTask injects a compact, adaptive context block before each LLM call. The system minimizes token usage by only including information that has changed or is urgently needed.

| Layer | Content | Frequency |
|-------|---------|-----------|
| **L0** | `[SagTask] task=X status=active phase=P step=S` | Every turn |
| **L1** | Phase/step names, pending gates | On change + blocking gates |
| **L1.5** | Artifacts summary | On change |
| **L2** | Methodology phase, plan progress, failures | On change |
| **L2.5** | Selected development rules (smart filtering) | On change + first turn |
| **L3** | Verification status, metrics (pass rate, coverage) | On change + blocking |
| **L4a** | Related tasks hint ("2 tasks available") | When relationships exist |
| **L4b** | Related task details | First turn, step switch, user intent |

**Cache:** Per-session per-task cache with context hashing. Stable state → single L0 line (~50 tokens). Changed state → relevant layers expand.

---

## Orchestration

```
sag_task_plan          → Generate subtasks from step description
sag_task_dispatch      → Build subagent context, optional git worktree
  └─ subagent executes → sag_task_plan_update(status="done")
sag_task_review        → Spec compliance + quality review context
sag_task_verify        → Run commands, record results to metrics
sag_task_advance       → Move to next step (blocks if must_pass fails)
```

### Metrics

Append-only event log (`.sag_metrics.jsonl`) tracks:
- Verification runs (pass/fail, exit codes, coverage)
- Subtask completions
- Step advances, dispatches, pauses/resumes

Query with `sag_task_metrics` for pass rates, coverage trends, and subtask throughput.

---

## Storage Layout

```
~/.hermes/sag_tasks/
├── .active_tasks.json           ← Per-profile active task tracking
├── .rules.json                  ← Global development rules (shared)
└── <task_id>/
    ├── .git/                        ← Task Git repo
    ├── .gitignore
    ├── .sag_task_state.json         ← Machine-readable state (git-ignored)
    ├── .sag_plans/                  ← Subtask plans (git-tracked)
    │   └── <step_id>.json
    ├── .sag_metrics.jsonl           ← Metrics event log (git-ignored)
    ├── .sag_artifacts/              ← Generated artifacts (git-ignored)
    ├── .sag_executions/             ← Pause snapshots (git-ignored)
    ├── .sag_worktrees/              ← Isolated subtask worktrees (git-ignored)
    └── src/, tests/, docs/          ← User code (git-tracked)
```

---

## Development

```bash
# Run tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=src/sagtask --cov-report=term-missing

# Install for local Hermes dev
./dev-install.sh

# Build release tarball
bash scripts/build-release.sh 2.0.0

# Bump version across all files
bash scripts/bump-version.sh 2.1.0
```

---

## Release Process

```bash
bash scripts/bump-version.sh X.Y.Z
# Update CHANGELOG.md
git add -A && git commit -m "chore: release vX.Y.Z"
git tag vX.Y.Z && git push origin main --tags
# GitHub Actions builds artifact + creates release automatically
```

---

## License

MIT
