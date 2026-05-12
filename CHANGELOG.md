# Changelog

All notable changes to SagTask will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `sag_task_dispatch` tool — build subagent context and dispatch subtasks for execution
- `sag_task_review` tool — two-stage code review (spec compliance + quality)
- `sag_task_brainstorm` tool — structured design exploration with option selection
- `sag_task_debug` tool — systematic debugging workflow (reproduce → diagnose → fix)
- Brainstorm and debug phase tracking in context injection
- `_recommend_methodology()` helper for auto-suggesting methodology from step descriptions
- Git worktree integration for isolated subtask dispatch (`use_worktree` param)
- `create_worktree`/`remove_worktree` methods on SagTaskPlugin
- Active dispatch status in context injection
- Orchestration handlers module (`handlers/_orchestration.py`)
- `sag_task_plan` tool — generate structured subtask plans per step
- `sag_task_plan_update` tool — track subtask completion with progress sync
- TDD state machine — auto red/green phase transitions on verify
- Plan progress injection in LLM context ("3/7 subtasks completed")
- `.sag_plans/<step_id>.json` storage for Git-tracked plans
- `sag_task_metrics` tool — query verification stats, coverage trends, and subtask throughput
- Append-only metrics event log (`.sag_metrics.jsonl`) emitted by verify, dispatch, plan_update, advance, pause, resume
- Metrics summary in context injection (pass rate, coverage trend, subtask progress)

### Fixed
- `.sag_worktrees/` now included in `.gitignore` template (prevents accidental tracking)
- Worktree creation in `dispatch` moved before state save (failure no longer leaves stale in-progress status)
- `remove_worktree` no longer uses `--force` by default (protects uncommitted work)
- Simplified redundant condition in brainstorm explore phase initialization
- `DEBUG_PHASE_*` constants moved to `_utils.py` (eliminates `_plan → _orchestration` dependency)
- `selected_option` schema now documents `0` as custom design indicator

### Changed
- Refactored monolithic `__init__.py` (1,734 lines) into 10 modules (max 665 lines each)

## [1.3.0] - 2026-05-08

### Added
- `sag_task_verify` tool for step-level verification commands
- Step schema `methodology` and `verification` fields
- `schema_version: 2` with automatic migration from v1
- Methodology context injection via `pre_llm_call` hook (TDD phase, plan progress, verification status)
- Advance verification gate — blocks advancement when `must_pass` is set and verification fails

### Fixed
- `handle_tool_call` missing `sag_task_verify` — now uses shared `_tool_handlers` dict
- Command injection risk in verify — added cwd validation and execution logging
- Duplicate context builder between `on_turn_start` and `_on_pre_llm_call`
- `pause`/`resume` handlers now use immutable state updates

## [1.2.0] - 2026-05-06

### Added
- Input validation for task_id (alphanumeric + hyphens, max 64 chars)
- Subprocess timeout protection (30s) on all Git operations
- Configurable GitHub owner via `SAGTASK_GITHUB_OWNER` environment variable
- Exception logging (replaced silent `except Exception: pass` blocks)
- Test suite: 26 tests covering validation, lifecycle, and edge cases
- CI pipeline via GitHub Actions (`.github/workflows/test.yml`)

### Fixed
- `_get_current_step` UnboundLocalError when phases is empty
- Hardcoded `charlenchen` GitHub username — now configurable

## [1.1.0] - 2026-04-15

### Added
- Cross-pollination context injection via `pre_llm_call` hook
- Artifact scanning for generated files (markdown, code, JSON)
- Task relation system (`sag_task_relate` tool)

## [1.0.0] - 2026-03-20

### Added
- Initial release
- Per-task Git repositories with lazy initialization
- Multi-phase task lifecycle (create, advance, pause, resume, complete)
- Human-in-the-loop approval gates
- 11 tool handlers for task management
- Cross-session recovery via task state persistence
