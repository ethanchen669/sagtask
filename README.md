# SagTask

A Hermes Agent **standalone user plugin** for long-running, multi-phase tasks with structured methodology execution, subagent orchestration, and cross-session recovery. Each task gets its own Git repository with full version control.

> **SagTask is NOT a memory provider.** It coexists with any memory system and injects task context via the `pre_llm_call` hook.

## Quick Install

```bash
curl -fsSL https://raw.githubusercontent.com/ethanchen669/sagtask/main/install.sh | bash
```

Or manually:

```bash
git clone https://github.com/ethanchen669/sagtask.git ~/.hermes/plugins/sagtask
# Restart your Hermes gateway to load the plugin
```

## Tools (19)

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

### Git Operations

| Tool | Description |
|------|-------------|
| `sag_task_commit` | Stage all + commit with message |
| `sag_task_branch` | Create + push new branch |
| `sag_task_git_log` | Show recent commit history |
| `sag_task_relate` | Link two tasks as cross-pollination partners |

---

## Architecture

```
src/sagtask/
├── __init__.py          ← register(), re-exports
├── plugin.py            ← SagTaskPlugin class, layered context injection
├── hooks.py             ← pre_llm_call, on_session_start
├── schemas.py           ← 19 tool JSON schemas
├── _utils.py            ← constants, shared helpers
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
    ├── ctx.register_tool("sag_task_*", ...) × 19
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
~/.hermes/sag_tasks/<task_id>/
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
