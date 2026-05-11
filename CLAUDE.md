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

## Development Principles

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.
