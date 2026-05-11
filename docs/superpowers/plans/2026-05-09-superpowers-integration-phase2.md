# Superpowers Integration — Phase 2: Plan Layer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured subtask planning and TDD state machine to SagTask — enabling plan → execute separation and methodology-aware execution tracking.

**Architecture:** Add `sag_task_plan` tool that generates subtask plans stored as `.sag_plans/<step_id>.json` in the task repo. Add `sag_task_plan_update` tool for marking subtask completion and syncing progress to `methodology_state`. Enhance verify handler with automatic TDD phase transitions. All new state fields are optional and backward-compatible.

**Tech Stack:** Python 3.10+, pytest, subprocess (for verification commands)

**Spec:** `docs/superpowers-integration-proposal.md` — Phase 2 only

---

## File Structure

```
src/sagtask/
├── __init__.py          ← MODIFY: add plan/plan_update handlers, TDD state machine, plan context injection
tests/
├── test_plan.py         ← NEW: tests for plan generation and storage
├── test_plan_update.py  ← NEW: tests for subtask status updates and progress sync
├── test_tdd_state.py    ← NEW: tests for TDD phase transitions
├── conftest.py          ← MODIFY: add sample_phases_with_methodology fixture
```

---

### Task 1: Add `sag_task_plan` tool schema and handler skeleton

**Files:**
- Modify: `src/sagtask/__init__.py` (tool schemas section + handler + dispatch map)
- Create: `tests/test_plan.py`

**Context:** `sag_task_plan` generates a subtask plan for the current step. It reads the step's methodology type and description, creates a structured plan with subtasks, and saves it to `.sag_plans/<step_id>.json`. The plan file is Git-tracked (plans are valuable artifacts). The task state's `methodology_state.plan_file` is updated to reference it.

- [ ] **Step 1: Write failing test for plan generation**

Create `tests/test_plan.py`:

```python
"""Tests for sag_task_plan tool."""
import json
import pytest
import sagtask


class TestPlanGeneration:
    def _create_task_with_tdd_step(self, plugin, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-plan",
            "name": "Test Plan",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [{
                    "id": "step-1",
                    "name": "Implement Parser",
                    "description": "Build a JSON parser with error recovery",
                    "methodology": {"type": "tdd", "config": {"coverage_threshold": 80}},
                }],
            }],
        })

    def test_plan_creates_plan_file(self, isolated_sagtask, mock_git):
        """sag_task_plan should create .sag_plans/<step_id>.json."""
        self._create_task_with_tdd_step(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_plan({"sag_task_id": "test-plan"})
        assert result["ok"] is True
        plan_path = isolated_sagtask.get_task_root("test-plan") / ".sag_plans" / "step-1.json"
        assert plan_path.exists()

    def test_plan_has_correct_structure(self, isolated_sagtask, mock_git):
        """Plan file should have step_id, generated_at, methodology, subtasks."""
        self._create_task_with_tdd_step(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_plan({"sag_task_id": "test-plan"})
        plan_path = isolated_sagtask.get_task_root("test-plan") / ".sag_plans" / "step-1.json"
        plan = json.loads(plan_path.read_text())
        assert plan["step_id"] == "step-1"
        assert "generated_at" in plan
        assert plan["methodology"] == "tdd"
        assert isinstance(plan["subtasks"], list)
        assert len(plan["subtasks"]) >= 2

    def test_subtask_has_required_fields(self, isolated_sagtask, mock_git):
        """Each subtask should have id, title, status, depends_on, context."""
        self._create_task_with_tdd_step(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_plan({"sag_task_id": "test-plan"})
        plan_path = isolated_sagtask.get_task_root("test-plan") / ".sag_plans" / "step-1.json"
        plan = json.loads(plan_path.read_text())
        for st in plan["subtasks"]:
            assert "id" in st
            assert "title" in st
            assert st["status"] == "pending"
            assert "depends_on" in st
            assert "context" in st

    def test_plan_updates_state_reference(self, isolated_sagtask, mock_git):
        """Plan should update methodology_state.plan_file and subtask_progress."""
        self._create_task_with_tdd_step(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_plan({"sag_task_id": "test-plan"})
        state = isolated_sagtask.load_task_state("test-plan")
        ms = state["methodology_state"]
        assert ms["plan_file"] == ".sag_plans/step-1.json"
        assert ms["subtask_progress"]["total"] > 0
        assert ms["subtask_progress"]["completed"] == 0

    def test_plan_without_methodology_uses_default(self, isolated_sagtask, mock_git):
        """Steps without methodology should get a default plan."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-plan-no-method",
            "name": "No Method",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [{"id": "step-1", "name": "Do Something", "description": "Do the thing"}],
            }],
        })
        result = sagtask._handle_sag_task_plan({"sag_task_id": "test-plan-no-method"})
        assert result["ok"] is True
        plan_path = isolated_sagtask.get_task_root("test-plan-no-method") / ".sag_plans" / "step-1.json"
        plan = json.loads(plan_path.read_text())
        assert plan["methodology"] == "none"
        assert len(plan["subtasks"]) >= 1

    def test_plan_fails_without_active_task(self, isolated_sagtask, mock_git):
        """Should return error when no task_id and no active task."""
        result = sagtask._handle_sag_task_plan({})
        assert result["ok"] is False
        assert "error" in result

    def test_plan_fails_when_step_has_existing_plan(self, isolated_sagtask, mock_git):
        """Should return error if step already has a plan (use update to modify)."""
        self._create_task_with_tdd_step(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_plan({"sag_task_id": "test-plan"})
        result = sagtask._handle_sag_task_plan({"sag_task_id": "test-plan"})
        assert result["ok"] is False
        assert "already" in result["error"].lower() or "exists" in result["error"].lower()

    def test_plan_granularity_affects_subtask_count(self, isolated_sagtask, mock_git):
        """Fine granularity should produce more subtasks than coarse."""
        self._create_task_with_tdd_step(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_plan({"sag_task_id": "test-plan", "granularity": "fine"})
        plan_path = isolated_sagtask.get_task_root("test-plan") / ".sag_plans" / "step-1.json"
        plan = json.loads(plan_path.read_text())
        assert plan["granularity"] == "fine"
        # Fine granularity: at least 3 subtasks for a TDD step
        assert len(plan["subtasks"]) >= 3

    def test_tdd_plan_includes_red_green_refactor(self, isolated_sagtask, mock_git):
        """TDD methodology plan should include RED, GREEN, REFACTOR subtasks."""
        self._create_task_with_tdd_step(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_plan({"sag_task_id": "test-plan"})
        plan_path = isolated_sagtask.get_task_root("test-plan") / ".sag_plans" / "step-1.json"
        plan = json.loads(plan_path.read_text())
        titles = [st["title"].lower() for st in plan["subtasks"]]
        has_red = any("red" in t or "failing" in t or "test" in t for t in titles)
        has_green = any("green" in t or "implement" in t or "pass" in t for t in titles)
        assert has_red and has_green
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python -m pytest tests/test_plan.py -v`
Expected: FAIL with `_handle_sag_task_plan` not defined

- [ ] **Step 3: Add `sag_task_plan` tool schema**

Add after `TASK_VERIFY_SCHEMA` in `__init__.py`:

```python
TASK_PLAN_SCHEMA = {
    "name": "sag_task_plan",
    "description": "Generate a structured subtask plan for the current step. "
    "Creates .sag_plans/<step_id>.json with bite-sized subtasks. "
    "Each subtask is 2-30 minutes of work depending on granularity.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {
                "type": "string",
                "description": "Task ID. Defaults to active task.",
            },
            "granularity": {
                "type": "string",
                "enum": ["fine", "medium", "coarse"],
                "description": "Subtask granularity. fine=2-5min, medium=10-15min, coarse=30+min. Default: medium.",
            },
        },
    },
}
```

- [ ] **Step 4: Implement `_generate_plan` helper method on SagTaskPlugin**

Add method to SagTaskPlugin class (after `_build_task_context`):

```python
    def _generate_plan(
        self, step: Dict[str, Any], granularity: str = "medium"
    ) -> Dict[str, Any]:
        """Generate a subtask plan for a step based on its methodology and description."""
        methodology = step.get("methodology", {}).get("type", "none")
        step_name = step.get("name", "Unnamed Step")
        step_desc = step.get("description", step_name)

        subtasks: List[Dict[str, Any]] = []
        st_id = 0

        def _add_subtask(title: str, context: str, depends_on: Optional[List[str]] = None) -> str:
            nonlocal st_id
            st_id += 1
            sid = f"st-{st_id}"
            subtasks.append({
                "id": sid,
                "title": title,
                "status": "pending",
                "depends_on": depends_on or [],
                "context": context,
            })
            return sid

        if methodology == "tdd":
            red_id = _add_subtask(
                f"RED: Write failing test for {step_name}",
                f"Write test(s) that capture the expected behavior described in: {step_desc}. "
                "Tests must fail initially — no implementation yet.",
            )
            green_id = _add_subtask(
                f"GREEN: Implement {step_name} to pass tests",
                f"Write the minimal implementation that makes all tests pass. "
                f"Context: {step_desc}",
                depends_on=[red_id],
            )
            _add_subtask(
                f"REFACTOR: Clean up {step_name}",
                "Refactor implementation and tests for clarity and maintainability. "
                "All tests must continue passing.",
                depends_on=[green_id],
            )
            if granularity == "fine":
                # Insert extra fine-grained subtasks
                _add_subtask(
                    f"Verify coverage meets threshold",
                    "Run pytest with --cov and verify coverage meets the configured threshold.",
                    depends_on=[green_id],
                )
        elif methodology == "brainstorm":
            _add_subtask(
                f"Explore design options for {step_name}",
                f"Brainstorm 2-3 approaches for: {step_desc}. "
                "Document trade-offs for each approach.",
            )
            _add_subtask(
                f"Select and document design for {step_name}",
                "Present options and select the best approach. Document the decision.",
                depends_on=[f"st-{st_id}"],
            )
            _add_subtask(
                f"Implement {step_name} per selected design",
                "Implement the selected approach from the previous subtask.",
                depends_on=[f"st-{st_id}"],
            )
        else:
            # Default plan-execute style
            _add_subtask(
                f"Plan: Analyze requirements for {step_name}",
                f"Analyze what needs to be done for: {step_desc}. "
                "Identify dependencies and edge cases.",
            )
            _add_subtask(
                f"Implement: {step_name}",
                f"Implement the solution for: {step_desc}.",
                depends_on=[f"st-{st_id}"],
            )
            _add_subtask(
                f"Verify: Test {step_name}",
                "Write tests and verify the implementation works correctly.",
                depends_on=[f"st-{st_id}"],
            )

        return {
            "step_id": step.get("id", ""),
            "generated_at": _utcnow_iso(),
            "methodology": methodology,
            "granularity": granularity,
            "subtasks": subtasks,
        }
```

- [ ] **Step 5: Implement `_handle_sag_task_plan` handler**

Add handler function before `_tool_handlers` dict:

```python
def _handle_sag_task_plan(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    granularity = args.get("granularity", "medium")

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    step_obj = p._get_current_step_object(state)
    if not step_obj:
        return {"ok": False, "error": "Cannot find current step in task phases."}

    step_id = step_obj.get("id", "unknown")
    task_root = p.get_task_root(task_id)
    plans_dir = task_root / ".sag_plans"
    plan_path = plans_dir / f"{step_id}.json"

    if plan_path.exists():
        return {"ok": False, "error": f"Plan already exists for step '{step_id}'. Delete it first or use plan_update."}

    plan = p._generate_plan(step_obj, granularity)
    plans_dir.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False))

    total = len(plan["subtasks"])
    state = {
        **state,
        "methodology_state": {
            **state.get("methodology_state", {}),
            "plan_file": f".sag_plans/{step_id}.json",
            "subtask_progress": {"total": total, "completed": 0, "in_progress": 0},
        },
    }
    p.save_task_state(task_id, state)

    return {
        "ok": True,
        "sag_task_id": task_id,
        "step_id": step_id,
        "plan_file": f".sag_plans/{step_id}.json",
        "total_subtasks": total,
        "subtasks": [{"id": st["id"], "title": st["title"]} for st in plan["subtasks"]],
        "message": f"Plan generated with {total} subtasks for step '{step_id}'.",
    }
```

- [ ] **Step 6: Add to `_tool_handlers` and `ALL_TOOL_SCHEMAS`**

In `_tool_handlers` dict, add:
```python
    "sag_task_plan": _handle_sag_task_plan,
```

In `ALL_TOOL_SCHEMAS` list, add:
```python
    TASK_PLAN_SCHEMA,
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/test_plan.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/sagtask/__init__.py tests/test_plan.py
git commit -m "feat: add sag_task_plan tool for subtask plan generation"
```

---

### Task 2: Add `sag_task_plan_update` tool for subtask status tracking

**Files:**
- Modify: `src/sagtask/__init__.py` (tool schema + handler + dispatch map)
- Create: `tests/test_plan_update.py`

**Context:** `sag_task_plan_update` marks subtasks as done/in_progress/failed and syncs progress counts to `methodology_state.subtask_progress`. The plan file is the source of truth for subtask status; `methodology_state.subtask_progress` is a denormalized counter for context injection.

- [ ] **Step 1: Write failing tests for plan update**

Create `tests/test_plan_update.py`:

```python
"""Tests for sag_task_plan_update tool."""
import json
import pytest
import sagtask


class TestPlanUpdate:
    def _create_task_and_generate_plan(self, plugin, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-planupd",
            "name": "Test Plan Update",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [{
                    "id": "step-1",
                    "name": "Build Parser",
                    "description": "Build a JSON parser",
                    "methodology": {"type": "tdd"},
                }],
            }],
        })
        sagtask._handle_sag_task_plan({"sag_task_id": "test-planupd"})

    def _get_plan(self, plugin, task_id="test-planupd"):
        plan_path = plugin.get_task_root(task_id) / ".sag_plans" / "step-1.json"
        return json.loads(plan_path.read_text())

    def test_mark_subtask_done(self, isolated_sagtask, mock_git):
        """Should update subtask status to done and sync progress."""
        self._create_task_and_generate_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        first_id = plan["subtasks"][0]["id"]
        result = sagtask._handle_sag_task_plan_update({
            "sag_task_id": "test-planupd",
            "subtask_id": first_id,
            "status": "done",
        })
        assert result["ok"] is True
        state = isolated_sagtask.load_task_state("test-planupd")
        assert state["methodology_state"]["subtask_progress"]["completed"] == 1

    def test_mark_subtask_in_progress(self, isolated_sagtask, mock_git):
        """Should update subtask status to in_progress."""
        self._create_task_and_generate_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        first_id = plan["subtasks"][0]["id"]
        result = sagtask._handle_sag_task_plan_update({
            "sag_task_id": "test-planupd",
            "subtask_id": first_id,
            "status": "in_progress",
        })
        assert result["ok"] is True
        state = isolated_sagtask.load_task_state("test-planupd")
        assert state["methodology_state"]["subtask_progress"]["in_progress"] == 1

    def test_progress_counts_sync_correctly(self, isolated_sagtask, mock_git):
        """Completing multiple subtasks should update progress counts correctly."""
        self._create_task_and_generate_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        for st in plan["subtasks"][:2]:
            sagtask._handle_sag_task_plan_update({
                "sag_task_id": "test-planupd",
                "subtask_id": st["id"],
                "status": "done",
            })
        state = isolated_sagtask.load_task_state("test-planupd")
        ms = state["methodology_state"]
        assert ms["subtask_progress"]["completed"] == 2
        assert ms["subtask_progress"]["total"] == len(plan["subtasks"])

    def test_mark_invalid_subtask_id(self, isolated_sagtask, mock_git):
        """Should return error for non-existent subtask_id."""
        self._create_task_and_generate_plan(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_plan_update({
            "sag_task_id": "test-planupd",
            "subtask_id": "st-999",
            "status": "done",
        })
        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    def test_mark_invalid_status(self, isolated_sagtask, mock_git):
        """Should return error for invalid status value."""
        self._create_task_and_generate_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        result = sagtask._handle_sag_task_plan_update({
            "sag_task_id": "test-planupd",
            "subtask_id": plan["subtasks"][0]["id"],
            "status": "invalid",
        })
        assert result["ok"] is False

    def test_update_without_plan_returns_error(self, isolated_sagtask, mock_git):
        """Should return error when no plan exists for current step."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-noplan",
            "name": "No Plan",
            "phases": [{"id": "phase-1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        result = sagtask._handle_sag_task_plan_update({
            "sag_task_id": "test-noplan",
            "subtask_id": "st-1",
            "status": "done",
        })
        assert result["ok"] is False
        assert "no plan" in result["error"].lower() or "not found" in result["error"].lower()

    def test_done_with_note_records_context(self, isolated_sagtask, mock_git):
        """Marking done with context should update the subtask's context field."""
        self._create_task_and_generate_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        first_id = plan["subtasks"][0]["id"]
        sagtask._handle_sag_task_plan_update({
            "sag_task_id": "test-planupd",
            "subtask_id": first_id,
            "status": "done",
            "context": "Completed with 3 test cases covering edge cases.",
        })
        updated_plan = self._get_plan(isolated_sagtask)
        updated_st = next(s for s in updated_plan["subtasks"] if s["id"] == first_id)
        assert "3 test cases" in updated_st["context"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python -m pytest tests/test_plan_update.py -v`
Expected: FAIL with `_handle_sag_task_plan_update` not defined

- [ ] **Step 3: Add `sag_task_plan_update` tool schema**

Add after `TASK_PLAN_SCHEMA`:

```python
TASK_PLAN_UPDATE_SCHEMA = {
    "name": "sag_task_plan_update",
    "description": "Update the status of a subtask in the current step's plan. "
    "Syncs progress counts to methodology_state.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {
                "type": "string",
                "description": "Task ID. Defaults to active task.",
            },
            "subtask_id": {
                "type": "string",
                "description": "Subtask ID to update (e.g. 'st-1').",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "done", "failed"],
                "description": "New status for the subtask.",
            },
            "context": {
                "type": "string",
                "description": "Optional context or result to record on the subtask.",
            },
        },
        "required": ["subtask_id", "status"],
    },
}
```

- [ ] **Step 4: Implement `_handle_sag_task_plan_update` handler**

```python
def _handle_sag_task_plan_update(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    subtask_id = args.get("subtask_id", "")
    new_status = args.get("status", "")
    context = args.get("context")

    valid_statuses = {"pending", "in_progress", "done", "failed"}
    if new_status not in valid_statuses:
        return {"ok": False, "error": f"Invalid status '{new_status}'. Must be one of: {', '.join(sorted(valid_statuses))}"}

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    ms = state.get("methodology_state", {})
    plan_file = ms.get("plan_file")
    if not plan_file:
        return {"ok": False, "error": "No plan found for current step. Run sag_task_plan first."}

    task_root = p.get_task_root(task_id)
    plan_path = task_root / plan_file
    if not plan_path.exists():
        return {"ok": False, "error": f"Plan file '{plan_file}' not found on disk."}

    plan = json.loads(plan_path.read_text())
    subtask = next((s for s in plan["subtasks"] if s["id"] == subtask_id), None)
    if not subtask:
        return {"ok": False, "error": f"Subtask '{subtask_id}' not found in plan."}

    subtask["status"] = new_status
    if context:
        subtask["context"] = context

    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False))

    # Sync progress counts
    subtasks = plan["subtasks"]
    total = len(subtasks)
    completed = sum(1 for s in subtasks if s["status"] == "done")
    in_progress = sum(1 for s in subtasks if s["status"] == "in_progress")

    state = {
        **state,
        "methodology_state": {
            **ms,
            "subtask_progress": {"total": total, "completed": completed, "in_progress": in_progress},
        },
    }
    p.save_task_state(task_id, state)

    return {
        "ok": True,
        "sag_task_id": task_id,
        "subtask_id": subtask_id,
        "status": new_status,
        "progress": {"total": total, "completed": completed, "in_progress": in_progress},
        "message": f"Subtask '{subtask_id}' → {new_status}. Progress: {completed}/{total}.",
    }
```

- [ ] **Step 5: Add to `_tool_handlers` and `ALL_TOOL_SCHEMAS`**

```python
    "sag_task_plan_update": _handle_sag_task_plan_update,
```
```python
    TASK_PLAN_UPDATE_SCHEMA,
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/test_plan_update.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/sagtask/__init__.py tests/test_plan_update.py
git commit -m "feat: add sag_task_plan_update tool for subtask status tracking"
```

---

### Task 3: TDD state machine — automatic phase transitions

**Files:**
- Modify: `src/sagtask/__init__.py` (verify handler enhancement)
- Create: `tests/test_tdd_state.py`

**Context:** When a step has `methodology.type == "tdd"`, the verify handler should automatically update `methodology_state.tdd_phase` based on test results:
- Verification fails → `tdd_phase = "red"` (tests are failing, write implementation)
- Verification passes → `tdd_phase = "green"` (tests pass, ready to refactor/advance)
- After advance → `tdd_phase = None` (step complete, phase resets)

Additionally, add a `tdd_phase` parameter to `sag_task_plan_update` to allow manual TDD phase override.

- [ ] **Step 1: Write failing tests for TDD state machine**

Create `tests/test_tdd_state.py`:

```python
"""Tests for TDD state machine phase transitions."""
import json
import pytest
import sagtask


class TestTDDStateMachine:
    def _create_tdd_task(self, plugin, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-tdd",
            "name": "Test TDD",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [{
                    "id": "step-1",
                    "name": "Build Parser",
                    "methodology": {"type": "tdd", "config": {"coverage_threshold": 80}},
                    "verification": {"commands": ["pytest"], "must_pass": True},
                }, {
                    "id": "step-2",
                    "name": "Next Step",
                }],
            }],
        })

    def test_verify_fail_sets_red_phase(self, isolated_sagtask, mock_git):
        """Failed verification should set tdd_phase to 'red'."""
        self._create_tdd_task(isolated_sagtask, mock_git)
        # Mock subprocess to return failure
        mock_git.return_value = type("Proc", (), {"returncode": 1, "stdout": "", "stderr": "FAIL"})()
        sagtask._handle_sag_task_verify({"sag_task_id": "test-tdd"})
        state = isolated_sagtask.load_task_state("test-tdd")
        assert state["methodology_state"]["tdd_phase"] == "red"

    def test_verify_pass_sets_green_phase(self, isolated_sagtask, mock_git):
        """Passed verification should set tdd_phase to 'green'."""
        self._create_tdd_task(isolated_sagtask, mock_git)
        mock_git.return_value = type("Proc", (), {"returncode": 0, "stdout": "OK", "stderr": ""})()
        sagtask._handle_sag_task_verify({"sag_task_id": "test-tdd"})
        state = isolated_sagtask.load_task_state("test-tdd")
        assert state["methodology_state"]["tdd_phase"] == "green"

    def test_advance_resets_tdd_phase(self, isolated_sagtask, mock_git):
        """Advancing should reset tdd_phase to None for the next step."""
        self._create_tdd_task(isolated_sagtask, mock_git)
        # Set green so advance is allowed
        state = isolated_sagtask.load_task_state("test-tdd")
        state["methodology_state"]["tdd_phase"] = "green"
        state["methodology_state"]["last_verification"] = {"passed": True}
        isolated_sagtask.save_task_state("test-tdd", state)
        sagtask._handle_sag_task_advance({"sag_task_id": "test-tdd"})
        state = isolated_sagtask.load_task_state("test-tdd")
        # After advancing, tdd_phase should be reset
        assert state["methodology_state"]["tdd_phase"] is None

    def test_non_tdd_step_verify_no_phase_change(self, isolated_sagtask, mock_git):
        """Verify on non-TDD step should not change tdd_phase."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-non-tdd",
            "name": "Non TDD",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [{
                    "id": "step-1",
                    "name": "Step 1",
                    "verification": {"commands": ["true"]},
                }],
            }],
        })
        mock_git.return_value = type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        sagtask._handle_sag_task_verify({"sag_task_id": "test-non-tdd"})
        state = isolated_sagtask.load_task_state("test-non-tdd")
        assert state["methodology_state"]["tdd_phase"] is None

    def test_context_injection_shows_green_phase(self, isolated_sagtask, mock_git):
        """Context injection should show GREEN phase in output."""
        self._create_tdd_task(isolated_sagtask, mock_git)
        state = isolated_sagtask.load_task_state("test-tdd")
        state["methodology_state"]["tdd_phase"] = "green"
        isolated_sagtask.save_task_state("test-tdd", state)
        active_file = isolated_sagtask._projects_root / ".active_task"
        active_file.write_text("test-tdd")
        result = sagtask._on_pre_llm_call(
            session_id="test", user_message="", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert "GREEN" in result["context"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python -m pytest tests/test_tdd_state.py -v`
Expected: FAIL (tdd_phase not being set by verify)

- [ ] **Step 3: Enhance verify handler with TDD state transitions**

In `_handle_sag_task_verify`, after `p.save_task_state(task_id, state)` and before the return statement, add:

```python
    # TDD state machine: auto-transition phase based on verification result
    step_obj_for_tdd = p._get_current_step_object(state)
    if step_obj_for_tdd:
        m_type = step_obj_for_tdd.get("methodology", {}).get("type", "none")
        if m_type == "tdd":
            state = p.load_task_state(task_id)  # reload after save
            ms = state.get("methodology_state", {})
            new_tdd_phase = "green" if all_passed else "red"
            state = {
                **state,
                "methodology_state": {**ms, "tdd_phase": new_tdd_phase},
            }
            p.save_task_state(task_id, state)
```

- [ ] **Step 4: Reset tdd_phase on advance**

In `_handle_sag_task_advance`, after the verification check block and before the phases loop, add:

```python
    # Reset tdd_phase on advance (step completed)
    ms = state.get("methodology_state", {})
    if ms.get("tdd_phase"):
        state = {
            **state,
            "methodology_state": {**ms, "tdd_phase": None},
        }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/test_tdd_state.py -v`
Expected: All PASS

- [ ] **Step 6: Run full test suite to check for regressions**

Run: `PYTHONPATH=src python -m pytest tests/ -q`
Expected: All PASS (no regressions)

- [ ] **Step 7: Commit**

```bash
git add src/sagtask/__init__.py tests/test_tdd_state.py
git commit -m "feat: TDD state machine — auto red/green phase transitions"
```

---

### Task 4: Plan progress injection in context

**Files:**
- Modify: `src/sagtask/__init__.py` (`_build_task_context` method)

**Context:** Phase 1 already injects `subtask_progress` into context when `total > 0`. This task verifies the integration works end-to-end: after generating a plan and marking subtasks done, the context should show "X/Y subtasks completed".

- [ ] **Step 1: Write failing test for plan progress in context**

Add to `tests/test_context_injection.py`:

```python
    def test_context_includes_plan_progress(self, isolated_sagtask, mock_git):
        """Context should include plan progress when plan exists."""
        self._create_task_with_methodology(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_plan({"sag_task_id": "test-ctx"})
        result = sagtask._on_pre_llm_call(
            session_id="test", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert "subtask" in result["context"].lower() or "progress" in result["context"].lower()
        assert "0/" in result["context"]

    def test_context_shows_updated_progress(self, isolated_sagtask, mock_git):
        """Context should reflect completed subtasks."""
        self._create_task_with_methodology(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_plan({"sag_task_id": "test-ctx"})
        plan_path = isolated_sagtask.get_task_root("test-ctx") / ".sag_plans" / "step-1.json"
        plan = json.loads(plan_path.read_text())
        first_id = plan["subtasks"][0]["id"]
        sagtask._handle_sag_task_plan_update({
            "sag_task_id": "test-ctx",
            "subtask_id": first_id,
            "status": "done",
        })
        result = sagtask._on_pre_llm_call(
            session_id="test", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert "1/" in result["context"]
```

- [ ] **Step 2: Run test to verify it passes (Phase 1 already handles this)**

Run: `PYTHONPATH=src python -m pytest tests/test_context_injection.py::TestContextInjection::test_context_includes_plan_progress -v`
Expected: PASS (the `_build_task_context` already checks `subtask_progress.total > 0`)

- [ ] **Step 3: Verify all context injection tests pass**

Run: `PYTHONPATH=src python -m pytest tests/test_context_injection.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_context_injection.py
git commit -m "test: verify plan progress appears in context injection"
```

---

### Task 5: Update conftest and run full suite

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Add `sample_phases_with_methodology` fixture**

Add to `tests/conftest.py`:

```python
@pytest.fixture
def sample_phases_with_methodology():
    """Test phases with methodology and verification configured."""
    return [
        {
            "id": "phase-1",
            "name": "Design",
            "steps": [
                {
                    "id": "step-1",
                    "name": "Data Model",
                    "methodology": {"type": "tdd", "config": {"coverage_threshold": 80}},
                    "verification": {"commands": ["pytest"], "must_pass": True},
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

- [ ] **Step 2: Run full test suite**

Run: `PYTHONPATH=src python -m pytest tests/ -q`
Expected: All PASS

- [ ] **Step 3: Check coverage**

Run: `PYTHONPATH=src python -m pytest --cov=sagtask --cov-report=term-missing`
Expected: Coverage ≥ 80%

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add sample_phases_with_methodology fixture"
```

---

### Task 6: Update CHANGELOG and verify

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update CHANGELOG**

Add under `[Unreleased]`:

```markdown
## [Unreleased]

### Added
- `sag_task_plan` tool — generate structured subtask plans per step
- `sag_task_plan_update` tool — track subtask completion with progress sync
- TDD state machine — auto red/green phase transitions on verify
- Plan progress injection in LLM context ("3/7 subtasks completed")
- `.sag_plans/<step_id>.json` storage for Git-tracked plans
```

- [ ] **Step 2: Run full test suite one final time**

Run: `PYTHONPATH=src python -m pytest tests/ -q`
Expected: All PASS

- [ ] **Step 3: Final commit**

```bash
git add CHANGELOG.md
git commit -m "docs: add Phase 2 features to CHANGELOG"
```
