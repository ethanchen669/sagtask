# Changelog

All notable changes to SagTask will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `sag_task_plan` tool — generate structured subtask plans per step
- `sag_task_plan_update` tool — track subtask completion with progress sync
- TDD state machine — auto red/green phase transitions on verify
- Plan progress injection in LLM context ("3/7 subtasks completed")
- `.sag_plans/<step_id>.json` storage for Git-tracked plans

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
