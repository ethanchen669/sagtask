# Superpowers Integration — Phase 1: Foundation Layer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add methodology binding, verification enforcement, and schema versioning to SagTask — the foundation for Superpowers integration.

**Architecture:** Extend step schema with optional `methodology` and `verification` fields. Add `sag_task_verify` tool that runs verification commands and records results. Block `sag_task_advance` when verification is required but not passed. Inject methodology state into LLM context via `pre_llm_call` hook. Version task state schema for forward compatibility.

**Tech Stack:** Python 3.10+, pytest, subprocess (for verification commands)

**Spec:** `docs/superpowers-integration-proposal.md` — Phase 1 only

---

## File Structure

```
src/sagtask/
├── __init__.py          ← MODIFY: schema versioning, verify handler, advance guard, context injection
├── plugin.yaml          (unchanged)
├── VERSION              (unchanged)
tests/
├── conftest.py          ← MODIFY: add methodology-aware fixtures
├── test_schema_versioning.py  ← NEW
├── test_verify.py       ← NEW
├── test_advance_verification.py  ← NEW
├── test_context_injection.py  ← NEW
```

---

### Task 1: Add schema versioning to task state

**Files:**
- Modify: `src/sagtask/__init__.py` (near `save_task_state` and `load_task_state`)
- Create: `tests/test_schema_versioning.py`

**Context:** Task state has no version field. We need `schema_version: 2` in all new states and a migration path for old states (which have no version → treat as v1).

- [ ] **Step 1: Write failing tests for schema versioning**

Create `tests/test_schema_versioning.py`:

```python
"""Tests for task state schema versioning."""
import json
import sagtask


class TestSchemaVersioning:
    def test_new_task_has_schema_version(self, isolated_sagtask, mock_git):
        """Newly created tasks should have schema_version in state."""
        result = sagtask._handle_sag_task_create({
            "sag_task_id": "test-versioning",
            "name": "Test Versioning",
            "phases": [{"id": "p1", "name": "Phase 1", "steps": [{"id": "s1", "name": "Step 1"}]}],
        })
        assert result["ok"] is True
        state = isolated_sagtask.load_task_state("test-versioning")
        assert state is not None
        assert state.get("schema_version") == 2

    def test_old_state_without_version_gets_migrated(self, isolated_sagtask):
        """A state file without schema_version should be treated as v1 and get schema_version added on save."""
        task_id = "test-migrate-old"
        task_root = isolated_sagtask.get_task_root(task_id)
        task_root.mkdir(parents=True)
        old_state = {
            "task_id": task_id,
            "name": "Old Task",
            "status": "active",
            "phases": [{"id": "p1", "name": "P", "steps": [{"id": "s1", "name": "S"}]}],
            "current_phase_id": "p1",
            "current_step_id": "s1",
        }
        # Write old state without schema_version
        (task_root / ".sag_task_state.json").write_text(json.dumps(old_state))

        # Load should detect no version, and on next save it should get version 2
        state = isolated_sagtask.load_task_state(task_id)
        assert state is not None
        assert "schema_version" not in state

        # After saving (e.g. via advance), schema_version should be added
        isolated_sagtask.save_task_state(task_id, state)
        reloaded = isolated_sagtask.load_task_state(task_id)
        assert reloaded.get("schema_version") == 2

    def test_methodology_state_initialized(self, isolated_sagtask, mock_git):
        """New tasks should have methodology_state initialized."""
        result = sagtask._handle_sag_task_create({
            "sag_task_id": "test-method-init",
            "name": "Test Method Init",
            "phases": [{"id": "p1", "name": "P", "steps": [{"id": "s1", "name": "S"}]}],
        })
        assert result["ok"] is True
        state = isolated_sagtask.load_task_state("test-method-init")
        assert "methodology_state" in state
        assert state["methodology_state"]["current_methodology"] == "none"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_schema_versioning.py -v`
Expected: FAIL (schema_version not set, methodology_state not initialized)

- [ ] **Step 3: Implement schema versioning**

In `src/sagtask/__init__.py`, add constant and migration logic:

```python
# Near the top, after _SUBPROCESS_TIMEOUT
SCHEMA_VERSION = 2
```

Add a helper method to `SagTaskPlugin`:

```python
@staticmethod
def _ensure_schema_version(state: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure state has current schema_version. Mutates and returns state."""
    if state.get("schema_version") != SCHEMA_VERSION:
        state["schema_version"] = SCHEMA_VERSION
    return state
```

Modify `save_task_state` to call `_ensure_schema_version` before writing:

```python
def save_task_state(self, task_id: str, state: Dict[str, Any]) -> None:
    self._ensure_schema_version(state)
    path = self.get_task_state_path(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False))
```

In `_handle_sag_task_create`, after building the initial state dict (around line 870-875), add:

```python
state["schema_version"] = SCHEMA_VERSION
state["methodology_state"] = {
    "current_methodology": "none",
    "tdd_phase": None,
    "plan_file": None,
    "subtask_progress": {"total": 0, "completed": 0, "in_progress": 0},
    "last_verification": None,
    "review_state": None,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_schema_versioning.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sagtask/__init__.py tests/test_schema_versioning.py
git commit -m "feat: add schema_version (v2) and methodology_state to task state"
```

---

### Task 2: Extend step schema with methodology and verification

**Files:**
- Modify: `src/sagtask/__init__.py` (TASK_CREATE_SCHEMA)
- Modify: `tests/conftest.py` (add methodology fixtures)

**Context:** Steps currently only have `id`, `name`, `description`, and optional `gate`. We need to add optional `methodology` and `verification` fields per the proposal spec.

- [ ] **Step 1: Update TASK_CREATE_SCHEMA**

In `TASK_CREATE_SCHEMA` (line ~96-121), add new fields to the step items schema, after the `gate` property:

```python
"methodology": {
    "type": "object",
    "description": "Optional execution methodology for this step.",
    "properties": {
        "type": {
            "type": "string",
            "enum": ["tdd", "brainstorm", "debug", "plan-execute", "parallel-agents", "review", "none"],
            "description": "Methodology type.",
        },
        "config": {
            "type": "object",
            "description": "Methodology-specific configuration.",
            "properties": {
                "coverage_threshold": {"type": "integer", "description": "Min test coverage % for TDD."},
                "test_first": {"type": "boolean", "description": "Enforce test-first for TDD."},
            },
        },
    },
    "required": ["type"],
},
"verification": {
    "type": "object",
    "description": "Optional verification requirements. Advance is blocked until verification passes.",
    "properties": {
        "commands": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Shell commands to run for verification.",
        },
        "must_pass": {
            "type": "boolean",
            "default": True,
            "description": "If True, advance is blocked until verification passes.",
        },
        "cwd": {
            "type": "string",
            "description": "Working directory for verification commands (default: task root).",
        },
    },
    "required": ["commands"],
},
```

- [ ] **Step 2: Update sample_phases fixture in conftest.py**

Add a phases fixture that includes methodology and verification:

```python
@pytest.fixture
def sample_phases_with_methodology():
    """Test phases with methodology and verification fields."""
    return [
        {
            "id": "phase-1",
            "name": "Design",
            "steps": [
                {
                    "id": "step-1",
                    "name": "Data Model",
                    "methodology": {"type": "tdd", "config": {"coverage_threshold": 80, "test_first": True}},
                    "verification": {"commands": ["pytest tests/ -v"], "must_pass": True},
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

- [ ] **Step 3: Commit**

```bash
git add src/sagtask/__init__.py tests/conftest.py
git commit -m "feat: extend step schema with methodology and verification fields"
```

---

### Task 3: Add sag_task_verify tool

**Files:**
- Modify: `src/sagtask/__init__.py` (add TASK_VERIFY_SCHEMA, handler, register)
- Create: `tests/test_verify.py`

**Context:** This tool runs verification commands for the current step and records results in `methodology_state.last_verification`. It's the enforcement mechanism for the quality gates described in the proposal.

- [ ] **Step 1: Write failing tests for sag_task_verify**

Create `tests/test_verify.py`:

```python
"""Tests for sag_task_verify tool."""
import json
from unittest.mock import MagicMock, patch
import sagtask


class TestSagTaskVerify:
    def _create_task_with_verification(self, plugin, mock_git):
        """Helper: create a task with verification on step-1."""
        result = sagtask._handle_sag_task_create({
            "sag_task_id": "test-verify",
            "name": "Test Verify",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [{
                    "id": "step-1",
                    "name": "Step 1",
                    "verification": {
                        "commands": ["pytest tests/ -v"],
                        "must_pass": True,
                    },
                }],
            }],
        })
        return result

    def test_verify_passing_command(self, isolated_sagtask, mock_git):
        """Verify with a passing command should record success."""
        self._create_task_with_verification(isolated_sagtask, mock_git)

        # Mock subprocess.run to simulate passing test
        mock_git.return_value = MagicMock(returncode=0, stdout="2 passed", stderr="")

        result = sagtask._handle_sag_task_verify({
            "sag_task_id": "test-verify",
        })
        assert result["ok"] is True
        assert result["passed"] is True

        state = isolated_sagtask.load_task_state("test-verify")
        verification = state["methodology_state"]["last_verification"]
        assert verification["passed"] is True
        assert len(verification["results"]) == 1
        assert verification["results"][0]["exit_code"] == 0

    def test_verify_failing_command(self, isolated_sagtask, mock_git):
        """Verify with a failing command should record failure."""
        self._create_task_with_verification(isolated_sagtask, mock_git)

        # Mock subprocess.run to simulate failing test
        mock_git.return_value = MagicMock(returncode=1, stdout="", stderr="1 failed")

        result = sagtask._handle_sag_task_verify({
            "sag_task_id": "test-verify",
        })
        assert result["ok"] is True
        assert result["passed"] is False

        state = isolated_sagtask.load_task_state("test-verify")
        verification = state["methodology_state"]["last_verification"]
        assert verification["passed"] is False

    def test_verify_no_verification_configured(self, isolated_sagtask, mock_git):
        """Verify on a step without verification should succeed."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-no-verify",
            "name": "No Verify",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [{"id": "step-1", "name": "Step 1"}],
            }],
        })

        result = sagtask._handle_sag_task_verify({
            "sag_task_id": "test-no-verify",
        })
        assert result["ok"] is True
        assert result["passed"] is True
        assert "No verification configured" in result["message"]

    def test_verify_multiple_commands(self, isolated_sagtask, mock_git):
        """Verify with multiple commands should run all."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-multi-verify",
            "name": "Multi Verify",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [{
                    "id": "step-1",
                    "name": "Step 1",
                    "verification": {
                        "commands": ["pytest tests/", "mypy src/"],
                        "must_pass": True,
                    },
                }],
            }],
        })

        # First call passes, second fails
        mock_git.side_effect = [
            MagicMock(returncode=0, stdout="passed", stderr=""),
            MagicMock(returncode=1, stdout="", stderr="type error"),
        ]

        result = sagtask._handle_sag_task_verify({
            "sag_task_id": "test-multi-verify",
        })
        assert result["ok"] is True
        assert result["passed"] is False  # One failed

        state = isolated_sagtask.load_task_state("test-multi-verify")
        assert len(state["methodology_state"]["last_verification"]["results"]) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_verify.py -v`
Expected: FAIL (handler not found / schema not registered)

- [ ] **Step 3: Implement TASK_VERIFY_SCHEMA and handler**

Add schema after TASK_RELATE_SCHEMA:

```python
TASK_VERIFY_SCHEMA = {
    "name": "sag_task_verify",
    "description": "Run verification commands for the current step. "
    "Results are recorded in methodology_state. "
    "Must pass before sag_task_advance if verification.must_pass is True.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {
                "type": "string",
                "description": "Sag long term task identifier. Omit to verify the active task.",
            },
            "commands": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Override verification commands. Defaults to step's verification config.",
            },
        },
        "required": [],
    },
}
```

Add to `ALL_TOOL_SCHEMAS` list:

```python
ALL_TOOL_SCHEMAS = [
    # ... existing 11 schemas ...
    TASK_VERIFY_SCHEMA,
]
```

Add helper to `SagTaskPlugin` to find current step object:

```python
@staticmethod
def _get_current_step_object(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the current step dict from phases, or None."""
    phases = state.get("phases", [])
    current_phase_id = state.get("current_phase_id", "")
    current_step_id = state.get("current_step_id", "")
    for p in phases:
        if p.get("id") == current_phase_id:
            for s in p.get("steps", []):
                if s.get("id") == current_step_id:
                    return s
    return None
```

Add handler function:

```python
def _handle_sag_task_verify(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    step = p._get_current_step_object(state)
    if not step:
        return {"ok": False, "error": "Cannot find current step in task phases."}

    verification = step.get("verification", {})
    commands = args.get("commands") or verification.get("commands", [])

    if not commands:
        return {
            "ok": True,
            "passed": True,
            "message": "No verification configured for this step.",
        }

    task_root = p.get_task_root(task_id)
    cwd = verification.get("cwd") or str(task_root)
    results = []
    all_passed = True

    for cmd in commands:
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=cwd,
                capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
            )
            results.append({
                "command": cmd,
                "exit_code": proc.returncode,
                "stdout": proc.stdout[:2000],  # truncate
                "stderr": proc.stderr[:2000],
            })
            if proc.returncode != 0:
                all_passed = False
        except subprocess.TimeoutExpired:
            results.append({
                "command": cmd,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {_SUBPROCESS_TIMEOUT}s",
            })
            all_passed = False
        except Exception as e:
            results.append({
                "command": cmd,
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
            })
            all_passed = False

    # Record in methodology_state
    ms = state.setdefault("methodology_state", {})
    ms["last_verification"] = {
        "passed": all_passed,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "results": results,
    }
    p.save_task_state(task_id, state)

    return {
        "ok": True,
        "passed": all_passed,
        "results": results,
        "message": f"Verification {'passed' if all_passed else 'failed'} ({len(results)} commands).",
    }
```

Register handler in `_tool_handlers` dict:

```python
"sag_task_verify": _handle_sag_task_verify,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_verify.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sagtask/__init__.py tests/test_verify.py
git commit -m "feat: add sag_task_verify tool for step verification"
```

---

### Task 4: Block advance when verification fails

**Files:**
- Modify: `src/sagtask/__init__.py` (`_handle_sag_task_advance`)
- Create: `tests/test_advance_verification.py`

**Context:** Per the proposal, `sag_task_advance` should check if the current step has `verification.must_pass = True` and if `last_verification.passed` is False, it should block the advance.

- [ ] **Step 1: Write failing tests**

Create `tests/test_advance_verification.py`:

```python
"""Tests that advance is blocked when verification fails."""
import sagtask


class TestAdvanceVerification:
    def _create_task_with_verification(self, plugin, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-adv-verify",
            "name": "Test Advance Verify",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [
                    {
                        "id": "step-1",
                        "name": "Step 1",
                        "verification": {"commands": ["true"], "must_pass": True},
                    },
                    {"id": "step-2", "name": "Step 2"},
                ],
            }],
        })

    def test_advance_blocked_when_verification_fails(self, isolated_sagtask, mock_git):
        """Advance should be blocked if verification must_pass and last_verification failed."""
        self._create_task_with_verification(isolated_sagtask, mock_git)

        # Manually set last_verification to failed
        state = isolated_sagtask.load_task_state("test-adv-verify")
        state["methodology_state"]["last_verification"] = {
            "passed": False,
            "timestamp": "2026-05-07T00:00:00Z",
            "results": [{"command": "pytest", "exit_code": 1, "stdout": "", "stderr": "1 failed"}],
        }
        isolated_sagtask.save_task_state("test-adv-verify", state)

        result = sagtask._handle_sag_task_advance({
            "sag_task_id": "test-adv-verify",
        })
        assert result["ok"] is False
        assert "verification" in result["error"].lower() or "verify" in result["error"].lower()

    def test_advance_allowed_when_verification_passes(self, isolated_sagtask, mock_git):
        """Advance should proceed if verification passed."""
        self._create_task_with_verification(isolated_sagtask, mock_git)

        # Set last_verification to passed
        state = isolated_sagtask.load_task_state("test-adv-verify")
        state["methodology_state"]["last_verification"] = {
            "passed": True,
            "timestamp": "2026-05-07T00:00:00Z",
            "results": [{"command": "true", "exit_code": 0, "stdout": "", "stderr": ""}],
        }
        isolated_sagtask.save_task_state("test-adv-verify", state)

        result = sagtask._handle_sag_task_advance({
            "sag_task_id": "test-adv-verify",
        })
        assert result["ok"] is True

    def test_advance_allowed_without_verification(self, isolated_sagtask, mock_git):
        """Advance should proceed if no verification is configured."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-adv-no-verify",
            "name": "No Verify",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [
                    {"id": "step-1", "name": "Step 1"},
                    {"id": "step-2", "name": "Step 2"},
                ],
            }],
        })

        result = sagtask._handle_sag_task_advance({
            "sag_task_id": "test-adv-no-verify",
        })
        assert result["ok"] is True

    def test_advance_allowed_when_must_pass_false(self, isolated_sagtask, mock_git):
        """Advance should proceed if verification.must_pass is False."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-adv-not-mandatory",
            "name": "Not Mandatory",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [
                    {
                        "id": "step-1",
                        "name": "Step 1",
                        "verification": {"commands": ["false"], "must_pass": False},
                    },
                    {"id": "step-2", "name": "Step 2"},
                ],
            }],
        })

        result = sagtask._handle_sag_task_advance({
            "sag_task_id": "test-adv-not-mandatory",
        })
        assert result["ok"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_advance_verification.py -v`
Expected: FAIL (advance doesn't check verification yet)

- [ ] **Step 3: Add verification check to _handle_sag_task_advance**

In `_handle_sag_task_advance`, after loading state and before the phase/step navigation (around line 1062, after `if not state: return ...`), add:

```python
    # Check verification requirements before advancing
    step_obj = p._get_current_step_object(state)
    if step_obj:
        verification = step_obj.get("verification", {})
        if verification.get("must_pass", False):
            ms = state.get("methodology_state", {})
            last_v = ms.get("last_verification")
            if not last_v or not last_v.get("passed", False):
                return {
                    "ok": False,
                    "error": "Verification not passed. Run sag_task_verify before advancing.",
                    "last_verification": last_v,
                }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_advance_verification.py -v`
Expected: PASS

- [ ] **Step 5: Run all existing tests to check for regressions**

Run: `python -m pytest tests/ -v`
Expected: All tests pass (the advance tests in test_lifecycle.py use steps without verification, so they should be unaffected)

- [ ] **Step 6: Commit**

```bash
git add src/sagtask/__init__.py tests/test_advance_verification.py
git commit -m "feat: block advance when verification must_pass and not passed"
```

---

### Task 5: Enhance context injection with methodology state

**Files:**
- Modify: `src/sagtask/__init__.py` (`_on_pre_llm_call`)
- Create: `tests/test_context_injection.py`

**Context:** The `pre_llm_call` hook currently injects task status, phase/step, gates, and artifacts. We need to add methodology state: current methodology type, verification status, TDD phase, and plan progress.

- [ ] **Step 1: Write failing tests**

Create `tests/test_context_injection.py`:

```python
"""Tests for methodology context injection in pre_llm_call."""
import json
import sagtask


class TestContextInjection:
    def _create_task_with_methodology(self, plugin, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-ctx",
            "name": "Test Context",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [{
                    "id": "step-1",
                    "name": "Step 1",
                    "methodology": {"type": "tdd", "config": {"coverage_threshold": 80}},
                    "verification": {"commands": ["pytest"], "must_pass": True},
                }],
            }],
        })
        # Set active task marker
        active_file = plugin._projects_root / ".active_task"
        active_file.write_text("test-ctx")

    def test_context_includes_methodology_type(self, isolated_sagtask, mock_git):
        """Context should include methodology type when set."""
        self._create_task_with_methodology(isolated_sagtask, mock_git)

        result = sagtask._on_pre_llm_call(
            session_id="test",
            user_message="hello",
            conversation_history=[],
            is_first_turn=True,
            model="test",
            platform="test",
            sender_id="test",
        )
        assert "context" in result
        assert "tdd" in result["context"].lower()

    def test_context_includes_verification_status(self, isolated_sagtask, mock_git):
        """Context should include verification status when verification is configured."""
        self._create_task_with_methodology(isolated_sagtask, mock_git)

        result = sagtask._on_pre_llm_call(
            session_id="test",
            user_message="hello",
            conversation_history=[],
            is_first_turn=True,
            model="test",
            platform="test",
            sender_id="test",
        )
        assert "Verification" in result["context"] or "verification" in result["context"].lower()

    def test_context_includes_tdd_phase(self, isolated_sagtask, mock_git):
        """Context should include TDD phase when methodology is tdd."""
        self._create_task_with_methodology(isolated_sagtask, mock_git)

        # Set TDD phase
        state = isolated_sagtask.load_task_state("test-ctx")
        state["methodology_state"]["tdd_phase"] = "red"
        isolated_sagtask.save_task_state("test-ctx", state)

        result = sagtask._on_pre_llm_call(
            session_id="test",
            user_message="hello",
            conversation_history=[],
            is_first_turn=True,
            model="test",
            platform="test",
            sender_id="test",
        )
        assert "RED" in result["context"]

    def test_context_no_methodology_for_none(self, isolated_sagtask, mock_git):
        """Context should not show methodology line when methodology is 'none'."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-ctx-none",
            "name": "No Method",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [{"id": "step-1", "name": "Step 1"}],
            }],
        })
        active_file = isolated_sagtask._projects_root / ".active_task"
        active_file.write_text("test-ctx-none")

        result = sagtask._on_pre_llm_call(
            session_id="test",
            user_message="hello",
            conversation_history=[],
            is_first_turn=True,
            model="test",
            platform="test",
            sender_id="test",
        )
        # Should not contain methodology line
        assert "Methodology" not in result.get("context", "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_context_injection.py -v`
Expected: FAIL (context doesn't include methodology)

- [ ] **Step 3: Enhance _on_pre_llm_call context injection**

In `_on_pre_llm_call` (around line 1400-1415), after the existing lines and before the `cross_context` block, add methodology context:

```python
    # Methodology context
    ms = state.get("methodology_state", {})
    methodology = ms.get("current_methodology", "none")
    if methodology and methodology != "none":
        lines.append(f"- Methodology: **{methodology}**")

        # TDD phase
        tdd_phase = ms.get("tdd_phase")
        if tdd_phase and methodology == "tdd":
            lines.append(f"- ⚠️ TDD phase: {tdd_phase.upper()}")

        # Verification status
        step_obj = p._get_current_step_object(state)
        if step_obj and step_obj.get("verification"):
            last_v = ms.get("last_verification")
            if last_v:
                v_status = "✓ passed" if last_v.get("passed") else "✗ failed"
                lines.append(f"- Verification: {v_status}")
            else:
                lines.append("- Verification: pending")

        # Plan progress
        progress = ms.get("subtask_progress", {})
        total = progress.get("total", 0)
        completed = progress.get("completed", 0)
        if total > 0:
            lines.append(f"- Plan progress: {completed}/{total} subtasks completed")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_context_injection.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sagtask/__init__.py tests/test_context_injection.py
git commit -m "feat: inject methodology state into LLM context"
```

---

### Task 6: Run full test suite and verify

- [ ] **Step 1: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests pass (old + new)

- [ ] **Step 2: Verify test count**

Expected: ~44 tests (26 existing + ~18 new from Phase 1)

- [ ] **Step 3: Final commit if any fixups needed**

```bash
git add -A
git commit -m "chore: phase 1 foundation — schema versioning, verify tool, advance guard, context injection"
```

---

## Summary

After completing this plan, SagTask will have:

| Feature | Description |
|---------|-------------|
| Schema versioning | `schema_version: 2` in all task states, migration for old states |
| Step methodology | Optional `methodology` field (tdd, brainstorm, debug, etc.) |
| Step verification | Optional `verification` with commands + must_pass flag |
| `sag_task_verify` | New tool (12th) that runs commands and records results |
| Advance guard | Blocks `sag_task_advance` when verification required but failed |
| Enhanced context | LLM receives methodology type, TDD phase, verification status |

All new fields are **optional** — existing tasks without them continue to work unchanged.
