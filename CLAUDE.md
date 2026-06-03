# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SagTask is a Hermes Agent standalone user plugin for long-running, multi-phase tasks with human-in-the-loop approval gates and cross-session recovery. It does **not** implement the `MemoryProvider` ABC — it injects task context via the `pre_llm_call` hook.

## Development Commands

```bash
# Install plugin to Hermes (copies src/sagtask/ → ~/.hermes/plugins/sagtask/)
./dev-install.sh

# After editing code, re-run dev-install.sh then restart gateway
hermes gateway restart

# Verify plugin loaded
task_list
```

## Architecture

**Single-file plugin** (`src/sagtask/__init__.py`, ~1450 lines) containing:
- `SagTaskPlugin` class — singleton, registered via `register(ctx)`
- 11 tool handler functions (`_handle_sag_task_*`) dispatched via `handle_tool_call()`
- 2 hook callbacks (`_on_pre_llm_call`, `_on_session_start`) for context injection
- Tool schemas inlined as module-level dicts (self-contained, no subpackage)

**Key patterns:**
- Singleton instance `_sagtask_instance` set by `register()`, accessed by handlers via `_get_provider()`
- All tool handlers are top-level functions, not methods — they call `_get_provider()` to access the singleton
- Git operations use `subprocess.run()` with `cwd` set to task root directory

**Storage:** `~/.hermes/sag_tasks/<task_id>/` — each task is a Git repo with `.sag_task_state.json` (git-ignored, machine-readable state) and `.sag_executions/` (pause snapshots).

**Active task marker:** `~/.hermes/sag_tasks/.active_task` — plain text file containing the current task_id.

## Code Conventions

- Python 3.10+ with `from __future__ import annotations`
- Type hints on all function signatures
- All state mutations go through `save_task_state()` which writes JSON atomically
- Git operations are lazy-initialized on first push
- Tool names use `sag_task_*` prefix (not `task_*`)
- Constants: `SAGTASK_PROVIDER = "sagtask"`, plugin class `SagTaskPlugin`

## Development Rules

These 12 rules guide agent behavior across all tasks. They are enforced via SagTask's smart context injection system.

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
