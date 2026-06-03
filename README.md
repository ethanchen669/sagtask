<div align="center">

# SagTask

### Long-running task management for AI agents — phases, approvals, Git-tracked.

[![Version](https://img.shields.io/badge/version-2.2.1-blue.svg)]()
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)]()
[![Tests](https://img.shields.io/badge/tests-264%20passing-brightgreen.svg)]()
[![Hermes](https://img.shields.io/badge/Hermes-Plugin-purple.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)]()

**The missing project manager for your AI agent.** SagTask turns a 4-week build into a sequence of phases and steps, with human-in-the-loop approval gates, automatic Git commits, and per-session context recovery — so your agent never loses its place.

[Quick Install](#-quick-install-30-seconds) · [Why SagTask?](#-why-sagtask) · [Demo](#-30-second-demo) · [Architecture](#-architecture) · [Compare](#-vs-langgraph--autogen--crewai)

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

## ⚡ Quick Install (30 seconds)

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

## 🎬 30-Second Demo

> **Scenario:** Build a CLI tool with TDD, in 3 phases.

```
$ /sagtask create \
    --name "my-cli-tool" \
    --phases phase-1:design,phase-2:implement,phase-3:ship \
    --methodology tdd

✓ Task created: ~/.hermes/sag_tasks/my-cli-tool/
✓ Phase 1 of 3: Design (step: write-spec)
  [SagTask] task=my-cli-tool phase=phase-1 step=write-spec status=active

# Agent writes the spec...

$ /sagtask advance
✓ Step write-spec complete. Commit: a3f8c1d "Add design spec"
✓ Pending gate: gate-1-spec-review (Approve / Reject / Request Changes)

$ /sagtask approve gate-1-spec-review --decision Approve
✓ Gate approved. Entering phase 2.

# ... weeks of work, many sessions, many context compressions ...
# The agent always picks up exactly where it left off.

$ /sagtask status
┌────────────────────────────────────────────┐
│ Task:      my-cli-tool                     │
│ Status:    active                          │
│ Phase:     3 of 3 (Ship)                   │
│ Step:      5 of 6 (publish-to-pypi)        │
│ Pending:   gate-3-release (needs human)    │
│ Commits:   47                              │
│ Tests:     142/142 passing (94% coverage)  │
└────────────────────────────────────────────┘
```

> **The point:** your agent treats a 4-week project the way a senior engineer would — with structure, commits, and checkpoints.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         HERMES AGENT                                │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    Your AI conversation                       │  │
│  │              "SagTask, advance to next step"                  │  │
│  └─────────────────────────────┬─────────────────────────────────┘  │
│                                │ tool call                          │
│                                ▼                                    │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │              SagTask Plugin  (20 tools)                      │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │    │
│  │  │  Lifecycle   │  │  Planning    │  │   Methodology    │   │    │
│  │  │  create      │  │  plan        │  │   tdd            │   │    │
│  │  │  status      │  │  dispatch    │  │   brainstorm     │   │    │
│  │  │  advance     │  │  verify      │  │   debug          │   │    │
│  │  │  pause/resume│  │  review      │  │   metrics        │   │    │
│  │  │  approve     │  │              │  │                  │   │    │
│  │  └──────────────┘  └──────────────┘  └──────────────────┘   │    │
│  │                                                             │    │
│  │  ┌──────────────────────────────────────────────────────┐   │    │
│  │  │         pre_llm_call Hook (Context Injection)        │   │    │
│  │  │   L0: task + phase  L1: gates  L2: methodology       │   │    │
│  │  │   L2.5: rules     L3: metrics  L4: related tasks    │   │    │
│  │  └──────────────────────────────────────────────────────┘   │    │
│  └─────────────────────────────┬───────────────────────────────┘    │
└────────────────────────────────┼────────────────────────────────────┘
                                 │
                                 ▼
        ┌─────────────────────────────────────────────────────┐
        │   ~/.hermes/sag_tasks/<task_id>/   (Git repo)      │
        │  ┌──────────────────────────────────────────────┐   │
        │  │  .sag_task_state.json  (phases/steps/gates)  │   │
        │  │  .sag_metrics.jsonl    (verification log)    │   │
        │  │  .sag_plans/            (subtask JSON)        │   │
        │  │  src/, tests/, docs/   (your code)           │   │
        │  │  + .sag_artifacts/     (auto-captured)       │   │
        │  └──────────────────────────────────────────────┘   │
        └─────────────────────────────────────────────────────┘
```

**Key insight:** SagTask is **NOT a memory provider**. It coexists with any memory system and injects task context via the `pre_llm_call` hook — so the LLM always knows what phase it's in, what's blocked, and what just changed.

---

## ⚖️ vs LangGraph / AutoGen / CrewAI

> SagTask isn't trying to be a general agent framework. It's a **task management layer** that drops into any agent.

| Feature | **SagTask** | LangGraph | AutoGen | CrewAI |
|---------|:-----------:|:---------:|:-------:|:------:|
| Phases + steps + approval gates | ✅ | ⚠️ DIY | ❌ | ❌ |
| Cross-session state recovery | ✅ Git-backed | ⚠️ External DB | ❌ | ❌ |
| Human-in-the-loop approval | ✅ Built-in | ⚠️ DIY interrupt | ⚠️ UserProxy | ⚠️ DIY |
| Per-step methodology (TDD, debug…) | ✅ | ❌ | ❌ | ❌ |
| Auto-commit per advance | ✅ | ❌ | ❌ | ❌ |
| Works with ANY agent (not just one framework) | ✅ | ❌ LangChain only | ❌ AutoGen only | ❌ CrewAI only |
| Subagent dispatch + worktree isolation | ✅ | ⚠️ DIY | ⚠️ Limited | ⚠️ Limited |
| Coverage / pass-rate metrics built-in | ✅ | ❌ | ❌ | ❌ |
| Pause + resume with full context snapshot | ✅ | ❌ | ❌ | ❌ |
| **Install time** | **30 sec** | Hours | Hours | Hours |
| **Learning curve** | **5 min** | Days | Days | Days |

**TL;DR:** Use LangGraph/AutoGen/CrewAI to *build* agents. Use **SagTask to *manage* the long-running projects your agents work on**.

---

## 🌟 Real-World Usage

SagTask is used internally to build itself — `sagtask-devop` is a 5-phase, 23-step task managed by SagTask, with 264 tests and 47+ Git commits.

Other public tasks in the wild:

- **[EchoThane](https://github.com/ethanchen669)** — AI terminal adventure game (active, Week 5)
- **[personal-llm-wiki](https://github.com/ethanchen669)** — Personal knowledge graph (completed)
- **[personal-local-cdn](https://github.com/ethanchen669)** — Personal CDN with auto-renewing certs (completed)
- **[etshield-multi-agent](https://github.com/ethanchen669)** — Multi-Hermes-agent team setup (completed)

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

12 built-in rules auto-loaded on task creation. Smart context injection selects relevant rules based on methodology and phase. See [Development Rules System](#development-rules-system) for details.

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

## Methodology System

Each step can declare a `methodology` that guides execution:

| Type | Workflow |
|------|----------|
| `tdd` | RED → GREEN → REFACTOR cycle, auto-transitions on verify |
| `brainstorm` | Generate 3+ options → user selects → implement |
| `debug` | Reproduce → diagnose (hypothesis) → fix |
| `plan-execute` | Plan subtasks → execute sequentially → verify each |
| `none` | No methodology constraint (default) |

---

## Development Rules System

12 built-in rules guide agent behavior across all tasks. Rules use a **global defaults + per-task overrides** pattern.

### Storage

- **Global rules:** `~/.hermes/sag_tasks/.rules.json` — shared across all tasks
- **Per-task overrides:** `.sag_task_state.json` → `rules` field — task-specific additions/toggles

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

### Smart Context Injection

Rules are injected into `pre_llm_call` context at **L2.5**, filtered by current state:

| Trigger | Rules Injected |
|---------|---------------|
| methodology = `tdd` | rule-9 (tests encode intent) |
| methodology = `brainstorm` | rule-1 (think first), rule-7 (surface conflicts) |
| methodology = `debug` | rule-12 (fail loudly), rule-4 (goal-driven) |
| Pending gates | rule-3 (surgical changes), rule-10 (checkpoint) |
| First turn | All 12 rules |
| No special state | rule-1, rule-2, rule-12 (core three) |

### Managing Rules

```bash
# List current task's rules
sag_task_rules action: list

# Add a custom rule (task-level)
sag_task_rules action: add content: "Use type hints on all functions" task_id: "my-project" category: "quality"

# Add a global rule
sag_task_rules action: add content: "All PRs need 2 approvals" category: "process"

# Toggle a rule on/off
sag_task_rules action: toggle rule_id: "rule-6" task_id: "my-project"

# Remove a custom rule
sag_task_rules action: remove rule_id: "rule-custom-abc123" task_id: "my-project"
```

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
