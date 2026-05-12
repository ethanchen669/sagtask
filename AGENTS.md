# Repository Guidelines

## Project Structure & Module Organization

SagTask is a Python 3.10+ Hermes Agent plugin. Runtime code lives in `src/sagtask/`: `plugin.py` contains the core `SagTaskPlugin`, `hooks.py` handles Hermes hooks, `schemas.py` defines tool schemas, `_utils.py` holds shared helpers, and `handlers/` groups tool handlers by concern. Tests live in `tests/` and mirror plugin behavior with focused `test_*.py` modules. Long-form design notes and release plans live in `docs/`; release utilities are in `scripts/`; CI workflows are in `.github/workflows/`.

## Build, Test, and Development Commands

- `pip install -e ".[dev]"`: install the package plus pytest and coverage tooling.
- `python -m pytest`: run the default test suite using `pyproject.toml` settings.
- `python -m pytest tests/ --cov=src/sagtask --cov-report=term-missing -v`: run the same coverage-oriented command used by CI.
- `./dev-install.sh`: copy the plugin into the local Hermes plugin directory for manual testing.
- `hermes gateway restart`: reload Hermes after reinstalling the plugin.
- `bash scripts/build-release.sh 1.2.0`: build a versioned release tarball and checksum in `dist/`.

## Coding Style & Naming Conventions

Use 4-space indentation, `from __future__ import annotations`, and type hints on public or nontrivial functions. Keep names in Python `snake_case`; classes use `PascalCase`; constants use `UPPER_SNAKE_CASE`. Tool names and handlers should keep the `sag_task_*` prefix, for example `_handle_sag_task_status`. Preserve the existing modular layout and route state mutations through `save_task_state()` so schema upgrades and JSON persistence remain centralized.

## Testing Guidelines

Tests use `pytest`; shared fixtures are in `tests/conftest.py`. Keep tests isolated with `tmp_path` and mock `git` or `gh` subprocess calls instead of touching real repositories or GitHub. Name files `test_<feature>.py` and test functions `test_<expected_behavior>`. Coverage is configured with `fail_under = 80`; add or update tests for every behavior change. Mark real Hermes CLI end-to-end checks with `@pytest.mark.e2e`.

## Commit & Pull Request Guidelines

Recent history uses short imperative messages, often with conventional prefixes such as `docs:` and `fix:`. Prefer `type: concise summary` when possible, for example `fix: handle missing active task state`. Pull requests should include the problem, the solution, tests run, linked issues or plans, and screenshots or CLI output only when user-facing behavior changes.

## Security & Configuration Tips

Do not commit local Hermes state from `~/.hermes/`, generated `dist/` artifacts, credentials, or task repositories. Keep tests offline-safe by mocking external commands. When changing release or install scripts, verify paths against the current `src/sagtask/` package layout.
