# Changelog

All notable changes to SagTask will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
