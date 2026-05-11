# P0+P1: Security Fixes & Testing Infrastructure Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix security vulnerabilities (path injection, hardcoded credentials) and establish testing infrastructure with 80%+ coverage for all P0+P1 changes.

**Architecture:** Single-file plugin (`src/sagtask/__init__.py`) with 11 tool handlers. Changes: add input validation at handler entry points, extract GitHub owner to env var, add timeout to all subprocess calls, fix silent exception swallowing, fix undefined variable bug. Testing: pytest with `tmp_path` isolation and subprocess mocking.

**Tech Stack:** Python 3.10+, pytest, pytest-cov, subprocess (git/gh CLI)

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `src/sagtask/__init__.py` | Modify | All P0+P1 code fixes |
| `tests/__init__.py` | Create | Package marker |
| `tests/conftest.py` | Create | Shared fixtures (isolated plugin, mock git, sample phases) |
| `tests/test_validation.py` | Create | Tests for input validation (P0) |
| `tests/test_github_owner.py` | Create | Tests for configurable GitHub owner (P0) |
| `tests/test_subprocess_timeout.py` | Create | Tests for timeout behavior (P1) |
| `tests/test_exception_handling.py` | Create | Tests for improved exception logging (P1) |
| `tests/test_get_current_step.py` | Create | Tests for _get_current_step fix (P1) |
| `tests/test_lifecycle.py` | Create | Integration tests: create → advance → complete, pause → resume, approve gate |
| `pyproject.toml` | Create | Project metadata + pytest config + coverage threshold |
| `.github/workflows/test.yml` | Create | CI pipeline |

---

## Task 1: Fix `_get_current_step` undefined variable

**Files:**
- Modify: `src/sagtask/__init__.py:631-643`

The bug: if `phases` is empty or `current_phase_id` matches no phase, the `for` loop never assigns `current_step_id`, so `return current_step_id or "—"` raises `UnboundLocalError`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_get_current_step.py`:

```python
"""Tests for SagTaskPlugin._get_current_step static method."""
import pytest
from sagtask import SagTaskPlugin


class TestGetCurrentStep:
    def test_returns_step_name_when_found(self):
        state = {
            "current_phase_id": "phase-1",
            "current_step_id": "step-2",
            "phases": [
                {
                    "id": "phase-1",
                    "steps": [
                        {"id": "step-1", "name": "Design"},
                        {"id": "step-2", "name": "Implement"},
                    ],
                }
            ],
        }
        assert SagTaskPlugin._get_current_step(state) == "Implement"

    def test_returns_first_step_name_when_current_step_not_in_list(self):
        state = {
            "current_phase_id": "phase-1",
            "current_step_id": "step-nonexistent",
            "phases": [
                {
                    "id": "phase-1",
                    "steps": [{"id": "step-1", "name": "First"}],
                }
            ],
        }
        assert SagTaskPlugin._get_current_step(state) == "First"

    def test_returns_dash_when_phases_empty(self):
        state = {"current_phase_id": "phase-1", "current_step_id": "step-1", "phases": []}
        assert SagTaskPlugin._get_current_step(state) == "—"

    def test_returns_dash_when_current_phase_not_found(self):
        state = {
            "current_phase_id": "nonexistent",
            "current_step_id": "step-1",
            "phases": [],
        }
        assert SagTaskPlugin._get_current_step(state) == "—"

    def test_returns_step_id_when_name_missing(self):
        state = {
            "current_phase_id": "phase-1",
            "current_step_id": "step-1",
            "phases": [
                {"id": "phase-1", "steps": [{"id": "step-1"}]},
            ],
        }
        assert SagTaskPlugin._get_current_step(state) == "step-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/ethan/.hermes/sag_tasks/sagtask-devop && python -m pytest tests/test_get_current_step.py -v`
Expected: `test_returns_dash_when_phases_empty` FAIL with `UnboundLocalError: local variable 'current_step_id' referenced before assignment`

- [ ] **Step 3: Fix the bug in `__init__.py`**

In `src/sagtask/__init__.py`, replace lines 631-643:

```python
    @staticmethod
    def _get_current_step(state: Dict[str, Any]) -> str:
        current_step_id = state.get("current_step_id", "")
        phases = state.get("phases", [])
        current_phase_id = state.get("current_phase_id", "")
        for p in phases:
            if p.get("id") == current_phase_id:
                steps = p.get("steps", [])
                for s in steps:
                    if s.get("id") == current_step_id:
                        return s.get("name", current_step_id)
                if steps:
                    return steps[0].get("name", "—")
        return current_step_id or "—"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/ethan/.hermes/sag_tasks/sagtask-devop && python -m pytest tests/test_get_current_step.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/sagtask/__init__.py tests/test_get_current_step.py
git commit -m "fix: initialize current_step_id before loop to prevent UnboundLocalError"
```

---

## Task 2: Add input validation for `sag_task_id`

**Files:**
- Modify: `src/sagtask/__init__.py` (add `_validate_task_id` function, call from all handlers)
- Create: `tests/test_validation.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_validation.py`:

```python
"""Tests for sag_task_id input validation."""
import pytest
from sagtask import _validate_task_id


class TestValidateTaskId:
    def test_valid_ids(self):
        assert _validate_task_id("my-task") is True
        assert _validate_task_id("task_v2") is True
        assert _validate_task_id("sc-mrp-v1") is True
        assert _validate_task_id("a") is True
        assert _validate_task_id("A1b2C3") is True

    def test_rejects_empty(self):
        assert _validate_task_id("") == "task_id cannot be empty"

    def test_rejects_path_traversal(self):
        assert _validate_task_id("../../etc") == "Invalid task_id format"
        assert _validate_task_id("..%2F..%2Fetc") == "Invalid task_id format"

    def test_rejects_special_chars(self):
        assert _validate_task_id("task name") == "Invalid task_id format"
        assert _validate_task_id("task@name") == "Invalid task_id format"
        assert _validate_task_id("task/name") == "Invalid task_id format"

    def test_rejects_too_long(self):
        long_id = "a" * 64
        assert _validate_task_id(long_id) is True
        too_long = "a" * 65
        assert _validate_task_id(too_long) == "task_id must be 64 characters or less"

    def test_rejects_starting_with_hyphen(self):
        assert _validate_task_id("-task") == "Invalid task_id format"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/ethan/.hermes/sag_tasks/sagtask-devop && python -m pytest tests/test_validation.py -v`
Expected: All tests FAIL with `ImportError: cannot import name '_validate_task_id'`

- [ ] **Step 3: Add validation function**

In `src/sagtask/__init__.py`, add after the `SAGTASK_PROVIDER` line (around line 39), before the tool schemas:

```python
import os

_TASK_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def _validate_task_id(task_id: str) -> str | None:
    """Validate task_id format. Returns error message or None if valid."""
    if not task_id:
        return "task_id cannot be empty"
    if not _TASK_ID_RE.match(task_id):
        return "Invalid task_id format"
    if len(task_id) > 64:
        return "task_id must be 64 characters or less"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/ethan/.hermes/sag_tasks/sagtask-devop && python -m pytest tests/test_validation.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Add validation to `_handle_sag_task_create`**

In `_handle_sag_task_create` (line ~824), add after `task_id = args["sag_task_id"]`:

```python
    validation_err = _validate_task_id(task_id)
    if validation_err:
        return {"ok": False, "error": validation_err}
```

- [ ] **Step 6: Run test again to confirm no regression**

Run: `cd /Users/ethan/.hermes/sag_tasks/sagtask-devop && python -m pytest tests/test_validation.py tests/test_get_current_step.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/sagtask/__init__.py tests/test_validation.py
git commit -m "feat: add task_id input validation with path traversal protection"
```

---

## Task 3: Extract hardcoded GitHub username to environment variable

**Files:**
- Modify: `src/sagtask/__init__.py:384,392,394,402,404`
- Create: `tests/test_github_owner.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_github_owner.py`:

```python
"""Tests for configurable GitHub owner."""
import pytest
from sagtask import _get_github_owner


class TestGetGitHubOwner:
    def test_returns_env_var_when_set(self, monkeypatch):
        monkeypatch.setenv("SAGTASK_GITHUB_OWNER", "myorg")
        assert _get_github_owner() == "myorg"

    def test_returns_default_when_env_not_set(self, monkeypatch):
        monkeypatch.delenv("SAGTASK_GITHUB_OWNER", raising=False)
        assert _get_github_owner() == "ethanchen669"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/ethan/.hermes/sag_tasks/sagtask-devop && python -m pytest tests/test_github_owner.py -v`
Expected: All tests FAIL with `ImportError: cannot import name '_get_github_owner'`

- [ ] **Step 3: Add the function**

In `src/sagtask/__init__.py`, add after `_validate_task_id`:

```python
_DEFAULT_GITHUB_OWNER = "ethanchen669"


def _get_github_owner() -> str:
    """Return GitHub owner from SAGTASK_GITHUB_OWNER env var or default."""
    return os.environ.get("SAGTASK_GITHUB_OWNER", _DEFAULT_GITHUB_OWNER)
```

- [ ] **Step 4: Replace all hardcoded `charlenchen` references**

In `ensure_git_repo` (line 384), replace:
```python
        remote_url = f"git@github.com:charlenchen/{task_id}.git"
```
with:
```python
        remote_url = f"git@github.com:{_get_github_owner()}/{task_id}.git"
```

In `create_github_repo` (line 392), replace:
```python
        result = subprocess.run(["gh", "repo", "view", f"charlenchen/{task_id}"], capture_output=True, text=True)
```
with:
```python
        result = subprocess.run(["gh", "repo", "view", f"{_get_github_owner()}/{task_id}"], capture_output=True, text=True)
```

Replace all remaining `charlenchen` string literals (lines 394, 402, 404) with `_get_github_owner()` calls.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/ethan/.hermes/sag_tasks/sagtask-devop && python -m pytest tests/test_github_owner.py -v`
Expected: All 2 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/sagtask/__init__.py tests/test_github_owner.py
git commit -m "feat: extract GitHub owner to SAGTASK_GITHUB_OWNER env var"
```

---

## Task 4: Add subprocess timeout protection

**Files:**
- Modify: `src/sagtask/__init__.py` (all `subprocess.run` calls without timeout)
- Create: `tests/test_subprocess_timeout.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_subprocess_timeout.py`:

```python
"""Tests that subprocess calls use timeout."""
import pytest
from unittest.mock import patch, MagicMock
import sagtask


class TestSubprocessTimeout:
    def test_ensure_git_repo_uses_timeout(self, isolated_sagtask, monkeypatch):
        """ensure_git_repo subprocess calls should have timeout."""
        call_args = []

        def fake_run(cmd, **kwargs):
            call_args.append(kwargs)
            mock = MagicMock()
            mock.returncode = 0
            mock.stdout = ""
            mock.stderr = ""
            return mock

        monkeypatch.setattr("subprocess.run", fake_run)
        isolated_sagtask.ensure_git_repo("test-timeout")

        for kwargs in call_args:
            assert "timeout" in kwargs, f"Missing timeout in: {kwargs}"

    def test_git_push_uses_timeout(self, isolated_sagtask, monkeypatch):
        call_args = []

        def fake_run(cmd, **kwargs):
            call_args.append(kwargs)
            mock = MagicMock()
            mock.returncode = 0
            mock.stdout = ""
            mock.stderr = ""
            return mock

        monkeypatch.setattr("subprocess.run", fake_run)
        isolated_sagtask.git_push("test-timeout")

        for kwargs in call_args:
            assert "timeout" in kwargs, f"Missing timeout in: {kwargs}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/ethan/.hermes/sag_tasks/sagtask-devop && python -m pytest tests/test_subprocess_timeout.py -v`
Expected: Tests FAIL because subprocess calls lack `timeout` kwarg

- [ ] **Step 3: Add timeout to all subprocess.run calls**

Add a module constant after the existing constants:

```python
_SUBPROCESS_TIMEOUT = 30  # seconds
```

Then add `timeout=_SUBPROCESS_TIMEOUT` to every `subprocess.run()` call in the file. The calls are at lines: 380, 385, 386, 387, 392, 396, 409, 413, 424, 431, 437, 659, 668, 694, 719, 1068, 1069, 1189, 1190.

For example, line 380 changes from:
```python
        result = subprocess.run(["git", "init"], cwd=str(task_root), capture_output=True, text=True)
```
to:
```python
        result = subprocess.run(["git", "init"], cwd=str(task_root), capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/ethan/.hermes/sag_tasks/sagtask-devop && python -m pytest tests/test_subprocess_timeout.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/sagtask/__init__.py tests/test_subprocess_timeout.py
git commit -m "feat: add 30s timeout to all subprocess.run calls"
```

---

## Task 5: Improve exception handling — log instead of silent pass

**Files:**
- Modify: `src/sagtask/__init__.py:689,714,739,1070`
- Create: `tests/test_exception_handling.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_exception_handling.py`:

```python
"""Tests that exceptions are logged, not silently swallowed."""
import pytest
from unittest.mock import patch, MagicMock
import logging
import sagtask


class TestExceptionLogging:
    def test_advance_logs_git_commit_error(self, isolated_sagtask, mock_git, sample_phases, caplog):
        """Git commit failure in advance should be logged, not swallowed."""
        _handle_sag_task_create({
            "sag_task_id": "exc-test",
            "name": "Exception Test",
            "phases": sample_phases,
        })

        # Make git commit raise an exception
        original_run = __import__("subprocess").run

        def failing_run(cmd, **kwargs):
            if "git" in cmd and "commit" in cmd:
                raise OSError("git not found")
            return original_run(cmd, **kwargs)

        with patch("subprocess.run", side_effect=failing_run):
            with caplog.at_level(logging.WARNING):
                sagtask._handle_sag_task_advance({"sag_task_id": "exc-test"})

        # Should have logged a warning, not silently passed
        assert any("git" in record.message.lower() or "commit" in record.message.lower()
                    for record in caplog.records), \
            f"No git error logged. Log records: {[r.message for r in caplog.records]}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/ethan/.hermes/sag_tasks/sagtask-devop && python -m pytest tests/test_exception_handling.py -v`
Expected: FAIL — the `except Exception: pass` at line 1070 swallows the error without logging

- [ ] **Step 3: Fix the exception handlers**

Replace all 4 `except Exception: pass` blocks with logging. Line 1070 (`_handle_sag_task_advance`):

```python
        except Exception as e:
            logger.warning("Git commit failed for task %s: %s", task_id, e)
```

Lines 689, 714, 739 (`_scan_git_artifacts`):

```python
        except Exception as e:
            logger.debug("Git artifact scan step failed for %s: %s", task_id, e)
```

Use `logger.debug` for artifact scanning (these are non-critical discovery operations), `logger.warning` for the advance commit (user-visible action).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/ethan/.hermes/sag_tasks/sagtask-devop && python -m pytest tests/test_exception_handling.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sagtask/__init__.py tests/test_exception_handling.py
git commit -m "fix: replace silent except Exception pass with logger.warning/debug"
```

---

## Task 6: Set up test infrastructure

**Files:**
- Create: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "sagtask"
version = "1.2.0"
requires-python = ">=3.10"

[project.optional-dependencies]
dev = ["pytest>=7.0", "pytest-cov>=4.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "e2e: end-to-end tests requiring hermes CLI",
]
addopts = "--tb=short -q"

[tool.coverage.run]
source = ["src/sagtask"]
omit = ["tests/*"]

[tool.coverage.report]
fail_under = 80
show_missing = true
```

- [ ] **Step 2: Create `tests/__init__.py`**

Empty file — just a package marker.

- [ ] **Step 3: Create `tests/conftest.py`**

```python
"""Shared fixtures for SagTask tests."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock

import sagtask


@pytest.fixture
def isolated_sagtask(tmp_path):
    """Create an isolated SagTaskPlugin with tmp_path as projects_root."""
    sagtask._sagtask_instance = None

    plugin = sagtask.SagTaskPlugin()
    plugin._hermes_home = tmp_path / "hermes"
    plugin._projects_root = tmp_path / "hermes" / "sag_tasks"
    plugin._projects_root.mkdir(parents=True)

    sagtask._sagtask_instance = plugin
    yield plugin
    sagtask._sagtask_instance = None


@pytest.fixture
def mock_git(monkeypatch):
    """Mock all subprocess.run calls to simulate git operations."""
    results = {}

    def fake_run(cmd, **kwargs):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd

        if "git init" in cmd_str:
            mock_result.stdout = "Initialized empty Git repository"
        elif "git log" in cmd_str:
            mock_result.stdout = "abc1234 Initial commit\ndef5678 WIP: step-1"
        elif "git rev-list --count" in cmd_str:
            mock_result.stdout = "2"
        elif "git diff --stat" in cmd_str:
            mock_result.stdout = " src/main.py | 10 ++++\n 1 file changed"
        elif "git status --porcelain" in cmd_str:
            mock_result.stdout = ""
        elif "gh repo view" in cmd_str:
            mock_result.returncode = 1
        elif "gh repo create" in cmd_str:
            mock_result.stdout = "Created repository"

        for pattern, result in results.items():
            if pattern in cmd_str:
                return result

        return mock_result

    monkeypatch.setattr("subprocess.run", fake_run)
    return results


@pytest.fixture
def sample_phases():
    """Standard test phases with gates."""
    return [
        {
            "id": "phase-1",
            "name": "Design",
            "steps": [
                {
                    "id": "step-1",
                    "name": "Data Model",
                    "gate": {
                        "id": "gate-1",
                        "question": "Is the data model correct?",
                        "choices": ["Approve", "Reject", "Request Changes"],
                    },
                },
                {"id": "step-2", "name": "Migration Script"},
            ],
        },
        {
            "id": "phase-2",
            "name": "Implementation",
            "steps": [
                {"id": "step-3", "name": "BOM Engine"},
            ],
        },
    ]
```

- [ ] **Step 4: Install dev dependencies and run all existing tests**

Run: `cd /Users/ethan/.hermes/sag_tasks/sagtask-devop && pip install -e ".[dev]" && python -m pytest tests/ -v`
Expected: All tests from Tasks 1-5 PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/__init__.py tests/conftest.py
git commit -m "chore: add test infrastructure with pyproject.toml and shared fixtures"
```

---

## Task 7: Write lifecycle integration tests

**Files:**
- Create: `tests/test_lifecycle.py`

- [ ] **Step 1: Write the lifecycle tests**

Create `tests/test_lifecycle.py`:

```python
"""Integration tests for full task lifecycle."""
import json
import pytest
from sagtask import (
    _handle_sag_task_create,
    _handle_sag_task_status,
    _handle_sag_task_advance,
    _handle_sag_task_pause,
    _handle_sag_task_resume,
    _handle_sag_task_approve,
    _handle_sag_task_list,
    _get_provider,
)


class TestTaskCreate:
    def test_create_sets_active_task(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "create-test",
            "name": "Create Test",
            "phases": sample_phases,
        })
        p = _get_provider()
        assert p._active_task_id == "create-test"
        marker = p._projects_root / ".active_task"
        assert marker.read_text().strip() == "create-test"

    def test_create_writes_state_file(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "state-test",
            "name": "State Test",
            "phases": sample_phases,
        })
        p = _get_provider()
        state = json.loads(p.get_task_state_path("state-test").read_text())
        assert state["current_phase_id"] == "phase-1"
        assert state["current_step_id"] == "step-1"
        assert state["status"] == "active"

    def test_create_rejects_invalid_id(self, isolated_sagtask, mock_git, sample_phases):
        result = _handle_sag_task_create({
            "sag_task_id": "../../etc",
            "name": "Bad ID",
            "phases": sample_phases,
        })
        assert result["ok"] is False
        assert "Invalid" in result["error"]


class TestTaskAdvance:
    def test_advance_to_next_step(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "adv-test",
            "name": "Advance Test",
            "phases": sample_phases,
        })
        result = _handle_sag_task_advance({"sag_task_id": "adv-test"})
        assert result["ok"] is True
        assert result["current_phase"] == "phase-1"
        assert result["current_step"] == "step-2"

    def test_advance_to_next_phase(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "adv-phase",
            "name": "Phase Test",
            "phases": sample_phases,
        })
        _handle_sag_task_advance({"sag_task_id": "adv-phase"})  # step-1 → step-2
        result = _handle_sag_task_advance({"sag_task_id": "adv-phase"})  # step-2 → phase-2/step-3
        assert result["current_phase"] == "phase-2"
        assert result["current_step"] == "step-3"

    def test_advance_completes_task(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "adv-done",
            "name": "Complete Test",
            "phases": sample_phases,
        })
        _handle_sag_task_advance({"sag_task_id": "adv-done"})  # step-1 → step-2
        _handle_sag_task_advance({"sag_task_id": "adv-done"})  # step-2 → step-3
        result = _handle_sag_task_advance({"sag_task_id": "adv-done"})  # step-3 → done
        assert result["status"] == "completed"


class TestTaskPauseResume:
    def test_pause_and_resume(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "pr-test",
            "name": "Pause Resume",
            "phases": sample_phases,
        })
        pause = _handle_sag_task_pause({"sag_task_id": "pr-test", "reason": "waiting"})
        assert pause["ok"] is True
        assert pause["status"] == "paused"

        p = _get_provider()
        assert p.load_task_state("pr-test")["status"] == "paused"

        resume = _handle_sag_task_resume({"sag_task_id": "pr-test"})
        assert resume["ok"] is True
        assert resume["status"] == "active"


class TestTaskApprove:
    def test_approve_gate_advances(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "gate-test",
            "name": "Gate Test",
            "phases": sample_phases,
        })
        p = _get_provider()
        state = p.load_task_state("gate-test")
        state["pending_gates"] = ["gate-1"]
        p.save_task_state("gate-test", state)

        result = _handle_sag_task_approve({
            "sag_task_id": "gate-test",
            "gate_id": "gate-1",
            "decision": "Approve",
            "comment": "Looks good",
        })
        assert result["ok"] is True
        assert result["current_step"] == "step-2"


class TestTaskList:
    def test_list_tasks(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "list-a",
            "name": "List A",
            "phases": sample_phases,
        })
        _handle_sag_task_create({
            "sag_task_id": "list-b",
            "name": "List B",
            "phases": sample_phases,
        })
        result = _handle_sag_task_list({"status_filter": "all"})
        assert result["ok"] is True
        assert len(result["tasks"]) == 2
```

- [ ] **Step 2: Run the tests**

Run: `cd /Users/ethan/.hermes/sag_tasks/sagtask-devop && python -m pytest tests/test_lifecycle.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_lifecycle.py
git commit -m "test: add lifecycle integration tests (create/advance/pause/resume/approve)"
```

---

## Task 8: Add CI workflow

**Files:**
- Create: `.github/workflows/test.yml`

- [ ] **Step 1: Create the CI file**

```yaml
name: Test
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: python -m pytest tests/ --cov=src/sagtask --cov-report=term-missing -v
        env:
          PYTHONPATH: src
```

- [ ] **Step 2: Verify tests pass locally one final time**

Run: `cd /Users/ethan/.hermes/sag_tasks/sagtask-devop && python -m pytest tests/ --cov=src/sagtask --cov-report=term-missing -v`
Expected: All tests PASS, coverage ≥ 80% for the changed code paths

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/test.yml
git commit -m "ci: add GitHub Actions test workflow"
```

---

## Task 9: Final verification and cleanup

- [ ] **Step 1: Run full test suite with coverage**

Run: `cd /Users/ethan/.hermes/sag_tasks/sagtask-devop && python -m pytest tests/ --cov=src/sagtask --cov-report=term-missing -v`
Expected: All tests PASS

- [ ] **Step 2: Verify no remaining hardcoded `charlenchen`**

Run: `grep -rn "charlenchen" src/sagtask/__init__.py`
Expected: No output

- [ ] **Step 3: Verify no remaining `except Exception: pass`**

Run: `grep -n "except Exception: pass" src/sagtask/__init__.py`
Expected: No output

- [ ] **Step 4: Verify all subprocess calls have timeout**

Run: `grep -n "subprocess.run" src/sagtask/__init__.py | grep -v "timeout"`
Expected: No output (all calls should have timeout)

- [ ] **Step 5: Final commit if any cleanup was needed**

```bash
git add -A
git commit -m "chore: P0+P1 cleanup — validation, env config, timeouts, logging, tests"
```
