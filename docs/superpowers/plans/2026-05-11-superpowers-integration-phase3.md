# Superpowers Integration — Phase 3: Orchestration Layer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add sub-agent dispatch and review tools to SagTask — enabling structured subtask execution with context isolation and two-stage code review.

**Architecture:** Add `sag_task_dispatch` tool that builds subagent context for a subtask, marks it in-progress, and returns a structured dispatch prompt. Add `sag_task_review` tool that builds review criteria and returns a structured review prompt. Dispatch status is tracked in the plan file. Context injection shows active dispatches.

**Tech Stack:** Python 3.10+, pytest

**Spec:** `docs/superpowers-integration-proposal.md` — Phase 3 only

---

## File Structure

```
src/sagtask/
├── schemas.py              ← MODIFY: add TASK_DISPATCH_SCHEMA, TASK_REVIEW_SCHEMA
├── handlers/
│   ├── __init__.py         ← MODIFY: add dispatch/review to _tool_handlers
│   └── _orchestration.py   ← NEW: dispatch + review handlers
tests/
├── test_dispatch.py        ← NEW: tests for dispatch tool
├── test_review.py          ← NEW: tests for review tool
```

---

### Task 1: Add `sag_task_dispatch` schema and handler

**Files:**
- Modify: `src/sagtask/schemas.py` (add TASK_DISPATCH_SCHEMA)
- Create: `src/sagtask/handlers/_orchestration.py`
- Modify: `src/sagtask/handlers/__init__.py` (add to _tool_handlers)
- Modify: `src/sagtask/__init__.py` (add re-export)
- Create: `tests/test_dispatch.py`

**Context:** `sag_task_dispatch` prepares a subtask for execution by building a self-contained context prompt and marking the subtask as in-progress. It does NOT spawn sub-processes — it returns structured data that the LLM uses to dispatch a subagent. The dispatch includes: subtask details, parent step context, methodology instructions, dependency status, and task root path.

- [ ] **Step 1: Write failing tests for dispatch**

Create `tests/test_dispatch.py`:

```python
"""Tests for sag_task_dispatch tool."""
import json
import pytest
import sagtask


class TestDispatch:
    def _create_task_with_plan(self, plugin, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-dispatch",
            "name": "Test Dispatch",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [{
                    "id": "step-1",
                    "name": "Build Parser",
                    "description": "Build a JSON parser with error recovery",
                    "methodology": {"type": "tdd", "config": {"coverage_threshold": 80}},
                    "verification": {"commands": ["pytest"], "must_pass": True},
                }],
            }],
        })
        sagtask._handle_sag_task_plan({"sag_task_id": "test-dispatch"})

    def _get_plan(self, plugin, task_id="test-dispatch"):
        plan_path = plugin.get_task_root(task_id) / ".sag_plans" / "step-1.json"
        return json.loads(plan_path.read_text())

    def test_dispatch_returns_context(self, isolated_sagtask, mock_git):
        """Dispatch should return a structured context prompt."""
        self._create_task_with_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        subtask_id = plan["subtasks"][0]["id"]
        result = sagtask._handle_sag_task_dispatch({
            "sag_task_id": "test-dispatch",
            "subtask_id": subtask_id,
        })
        assert result["ok"] is True
        assert "context" in result
        assert "subtask_id" in result
        assert result["subtask_id"] == subtask_id

    def test_dispatch_marks_in_progress(self, isolated_sagtask, mock_git):
        """Dispatch should mark the subtask as in_progress."""
        self._create_task_with_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        subtask_id = plan["subtasks"][0]["id"]
        sagtask._handle_sag_task_dispatch({
            "sag_task_id": "test-dispatch",
            "subtask_id": subtask_id,
        })
        updated_plan = self._get_plan(isolated_sagtask)
        st = next(s for s in updated_plan["subtasks"] if s["id"] == subtask_id)
        assert st["status"] == "in_progress"

    def test_dispatch_includes_methodology_instructions(self, isolated_sagtask, mock_git):
        """Context should include TDD instructions for tdd methodology."""
        self._create_task_with_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        subtask_id = plan["subtasks"][0]["id"]
        result = sagtask._handle_sag_task_dispatch({
            "sag_task_id": "test-dispatch",
            "subtask_id": subtask_id,
        })
        assert "tdd" in result["context"].lower() or "test" in result["context"].lower()

    def test_dispatch_includes_task_root(self, isolated_sagtask, mock_git):
        """Context should include the task root path for the subagent."""
        self._create_task_with_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        subtask_id = plan["subtasks"][0]["id"]
        result = sagtask._handle_sag_task_dispatch({
            "sag_task_id": "test-dispatch",
            "subtask_id": subtask_id,
        })
        assert "task_root" in result
        assert "test-dispatch" in result["task_root"]

    def test_dispatch_invalid_subtask(self, isolated_sagtask, mock_git):
        """Should return error for non-existent subtask."""
        self._create_task_with_plan(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_dispatch({
            "sag_task_id": "test-dispatch",
            "subtask_id": "st-999",
        })
        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    def test_dispatch_already_in_progress(self, isolated_sagtask, mock_git):
        """Should warn but allow re-dispatch of in-progress subtask."""
        self._create_task_with_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        subtask_id = plan["subtasks"][0]["id"]
        sagtask._handle_sag_task_dispatch({
            "sag_task_id": "test-dispatch",
            "subtask_id": subtask_id,
        })
        result = sagtask._handle_sag_task_dispatch({
            "sag_task_id": "test-dispatch",
            "subtask_id": subtask_id,
        })
        assert result["ok"] is True
        assert "warning" in result or "re-dispatch" in result.get("message", "").lower()

    def test_dispatch_includes_depends_on_status(self, isolated_sagtask, mock_git):
        """Context should show dependency status for subtasks with depends_on."""
        self._create_task_with_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        # Find a subtask with dependencies
        dep_task = next((s for s in plan["subtasks"] if s.get("depends_on")), None)
        if dep_task:
            result = sagtask._handle_sag_task_dispatch({
                "sag_task_id": "test-dispatch",
                "subtask_id": dep_task["id"],
            })
            assert result["ok"] is True
            assert "depends" in result["context"].lower() or "dependency" in result["context"].lower()

    def test_dispatch_no_task(self, isolated_sagtask, mock_git):
        """Should return error when no task_id and no active task."""
        result = sagtask._handle_sag_task_dispatch({"subtask_id": "st-1"})
        assert result["ok"] is False
        assert "error" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python -m pytest tests/test_dispatch.py -v`
Expected: FAIL with `_handle_sag_task_dispatch` not defined

- [ ] **Step 3: Add TASK_DISPATCH_SCHEMA to schemas.py**

Add after `TASK_PLAN_UPDATE_SCHEMA`:

```python
TASK_DISPATCH_SCHEMA: Dict[str, Any] = {
    "name": "sag_task_dispatch",
    "description": "Dispatch a subtask for execution. Builds a self-contained context "
    "prompt with subtask details, methodology instructions, and dependency status. "
    "Marks the subtask as in-progress. Use the returned context to dispatch a subagent.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {
                "type": "string",
                "description": "Task ID. Defaults to active task.",
            },
            "subtask_id": {
                "type": "string",
                "description": "Subtask ID from the plan to dispatch.",
            },
        },
        "required": ["subtask_id"],
    },
}
```

Add to `ALL_TOOL_SCHEMAS` list:
```python
    TASK_DISPATCH_SCHEMA,
```

- [ ] **Step 4: Create handlers/_orchestration.py**

```python
"""Orchestration handlers — dispatch and review for subtask execution."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .._utils import _get_provider, _utcnow_iso

logger = logging.getLogger(__name__)

# ── Methodology instruction templates ────────────────────────────────────────

_METHODOLOGY_INSTRUCTIONS: Dict[str, str] = {
    "tdd": (
        "## TDD Methodology\n"
        "Follow test-driven development:\n"
        "1. RED: Write a failing test that captures the expected behavior\n"
        "2. GREEN: Write the minimal code to make the test pass\n"
        "3. REFACTOR: Clean up while keeping tests green\n"
        "Run tests frequently. Commit after each green phase."
    ),
    "brainstorm": (
        "## Brainstorm Methodology\n"
        "1. Explore multiple design options (at least 3)\n"
        "2. Evaluate trade-offs for each option\n"
        "3. Select the best approach and document the rationale\n"
        "4. Implement the selected design"
    ),
    "debug": (
        "## Debug Methodology\n"
        "1. Reproduce the issue with a minimal test case\n"
        "2. Identify the root cause (not just symptoms)\n"
        "3. Fix the root cause, not the symptom\n"
        "4. Verify the fix and check for regressions"
    ),
    "plan-execute": (
        "## Plan-Execute Methodology\n"
        "1. Plan: Break the work into small steps\n"
        "2. Review: Verify the plan covers all requirements\n"
        "3. Execute: Implement each step, testing as you go\n"
        "4. Verify: Confirm all requirements are met"
    ),
}


def _load_plan(plan_path: Path) -> Optional[Dict[str, Any]]:
    """Load and return plan JSON, or None on error."""
    if not plan_path.exists():
        return None
    try:
        return json.loads(plan_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _build_dispatch_context(
    subtask: Dict[str, Any],
    step_obj: Dict[str, Any],
    methodology: str,
    task_root: str,
    plan: Dict[str, Any],
) -> str:
    """Build a self-contained context prompt for a subagent dispatch."""
    lines = [
        f"## Subtask Dispatch: {subtask['title']}",
        "",
        f"**Subtask ID:** {subtask['id']}",
        f"**Task root:** `{task_root}`",
        "",
        "### Subtask Details",
        f"- Title: {subtask['title']}",
    ]

    # Original context from plan generation
    if subtask.get("context"):
        lines.append(f"- Context: {subtask['context']}")

    # Previous result if re-dispatching
    if subtask.get("result"):
        lines.append(f"- Previous result: {subtask['result']}")

    # Parent step info
    step_name = step_obj.get("name", "Unknown Step")
    step_desc = step_obj.get("description", "")
    lines.extend([
        "",
        "### Parent Step",
        f"- Step: {step_name}",
    ])
    if step_desc:
        lines.append(f"- Description: {step_desc}")

    # Methodology instructions
    instructions = _METHODOLOGY_INSTRUCTIONS.get(methodology)
    if instructions:
        lines.extend(["", instructions])

    # Verification commands
    verification = step_obj.get("verification", {})
    commands = verification.get("commands", [])
    if commands:
        lines.extend([
            "",
            "### Verification",
            "Run these commands to verify your work:",
            *[f"```bash\n{cmd}\n```" for cmd in commands],
        ])

    # Dependency status
    depends_on = subtask.get("depends_on", [])
    if depends_on:
        lines.extend(["", "### Dependencies"])
        for dep_id in depends_on:
            dep_st = next((s for s in plan["subtasks"] if s["id"] == dep_id), None)
            if dep_st:
                dep_status = dep_st.get("status", "unknown")
                dep_title = dep_st.get("title", dep_id)
                status_icon = "done" if dep_status == "done" else "pending"
                lines.append(f"- [{status_icon}] {dep_id}: {dep_title}")
            else:
                lines.append(f"- [?] {dep_id}: not found in plan")

    # Sibling context (other subtasks for awareness)
    siblings = [s for s in plan["subtasks"] if s["id"] != subtask["id"]]
    if siblings:
        lines.extend(["", "### Other Subtasks (for context)"])
        for s in siblings:
            icon = "done" if s["status"] == "done" else "in_progress" if s["status"] == "in_progress" else "pending"
            lines.append(f"- [{icon}] {s['id']}: {s['title']}")

    return "\n".join(lines)


def _handle_sag_task_dispatch(args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch a subtask for execution by building subagent context."""
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    subtask_id = args.get("subtask_id", "")

    if not task_id:
        return {"ok": False, "error": "No active task."}
    if not subtask_id:
        return {"ok": False, "error": "subtask_id is required."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    ms = state.get("methodology_state", {})
    plan_file = ms.get("plan_file")
    if not plan_file:
        return {"ok": False, "error": "No plan found. Run sag_task_plan first."}

    task_root = p.get_task_root(task_id)
    plan_path = (task_root / plan_file).resolve()
    try:
        plan_path.relative_to(task_root.resolve())
    except ValueError:
        return {"ok": False, "error": f"Plan path '{plan_file}' is outside task root."}

    plan = _load_plan(plan_path)
    if not plan:
        return {"ok": False, "error": f"Plan file '{plan_file}' not found or corrupted."}

    subtask = next((s for s in plan["subtasks"] if s["id"] == subtask_id), None)
    if not subtask:
        return {"ok": False, "error": f"Subtask '{subtask_id}' not found in plan."}

    # Check if already done
    if subtask["status"] == "done":
        return {"ok": False, "error": f"Subtask '{subtask_id}' is already done. Use plan_update to reopen."}

    # Mark as in-progress (allow re-dispatch of in-progress)
    was_in_progress = subtask["status"] == "in_progress"
    updated_subtasks = [
        {**s, "status": "in_progress"} if s["id"] == subtask_id else s
        for s in plan["subtasks"]
    ]
    plan = {**plan, "subtasks": updated_subtasks}

    # Atomic write
    tmp_path = plan_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False))
    import os
    os.replace(str(tmp_path), str(plan_path))

    # Sync progress
    total = len(plan["subtasks"])
    completed = sum(1 for s in plan["subtasks"] if s["status"] == "done")
    in_progress = sum(1 for s in plan["subtasks"] if s["status"] == "in_progress")
    state = {
        **state,
        "methodology_state": {
            **ms,
            "subtask_progress": {"total": total, "completed": completed, "in_progress": in_progress},
        },
    }
    p.save_task_state(task_id, state)

    # Build dispatch context
    step_obj = p._get_current_step_object(state)
    methodology = ms.get("current_methodology", plan.get("methodology", "none"))
    context = _build_dispatch_context(
        subtask=next(s for s in plan["subtasks"] if s["id"] == subtask_id),
        step_obj=step_obj or {},
        methodology=methodology,
        task_root=str(task_root),
        plan=plan,
    )

    result: Dict[str, Any] = {
        "ok": True,
        "sag_task_id": task_id,
        "subtask_id": subtask_id,
        "task_root": str(task_root),
        "context": context,
        "message": f"Dispatched subtask '{subtask_id}'. Use the context to execute with a subagent.",
    }
    if was_in_progress:
        result["warning"] = f"Subtask '{subtask_id}' was already in-progress. Re-dispatched."
        result["message"] = f"Re-dispatched subtask '{subtask_id}'."

    return result
```

- [ ] **Step 5: Update handlers/__init__.py**

Add import:
```python
from ._orchestration import (
    _handle_sag_task_dispatch,
)
```

Add to `_tool_handlers` dict:
```python
    "sag_task_dispatch": _handle_sag_task_dispatch,
```

Add to `__all__`:
```python
    "_handle_sag_task_dispatch",
```

- [ ] **Step 6: Update __init__.py**

Add re-export:
```python
from sagtask.handlers._orchestration import (  # noqa: F401
    _handle_sag_task_dispatch,
)
```

Add schema import:
```python
    TASK_DISPATCH_SCHEMA,
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/test_dispatch.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/sagtask/schemas.py src/sagtask/handlers/_orchestration.py src/sagtask/handlers/__init__.py src/sagtask/__init__.py tests/test_dispatch.py
git commit -m "feat: add sag_task_dispatch tool for subtask execution"
```

---

### Task 2: Add `sag_task_review` tool

**Files:**
- Modify: `src/sagtask/schemas.py` (add TASK_REVIEW_SCHEMA)
- Modify: `src/sagtask/handlers/_orchestration.py` (add review handler)
- Modify: `src/sagtask/handlers/__init__.py` (add to _tool_handlers)
- Modify: `src/sagtask/__init__.py` (add re-export)
- Create: `tests/test_review.py`

**Context:** `sag_task_review` builds a structured review prompt for the current step's changes. It supports three scopes: `step` (current step only), `phase` (all steps in current phase), `full` (entire task). The review follows two-stage pattern: spec compliance first, then code quality. It returns review criteria based on the step's verification config and methodology.

- [ ] **Step 1: Write failing tests for review**

Create `tests/test_review.py`:

```python
"""Tests for sag_task_review tool."""
import json
import pytest
import sagtask


class TestReview:
    def _create_task_with_step(self, plugin, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-review",
            "name": "Test Review",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [{
                    "id": "step-1",
                    "name": "Build Parser",
                    "description": "Build a JSON parser",
                    "methodology": {"type": "tdd", "config": {"coverage_threshold": 80}},
                    "verification": {"commands": ["pytest"], "must_pass": True},
                }],
            }],
        })

    def test_review_returns_context(self, isolated_sagtask, mock_git):
        """Review should return structured review context."""
        self._create_task_with_step(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_review({
            "sag_task_id": "test-review",
            "scope": "step",
        })
        assert result["ok"] is True
        assert "context" in result
        assert "scope" in result

    def test_review_includes_spec_criteria(self, isolated_sagtask, mock_git):
        """Context should include spec compliance criteria."""
        self._create_task_with_step(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_review({
            "sag_task_id": "test-review",
            "scope": "step",
        })
        context = result["context"].lower()
        assert "spec" in context or "requirement" in context or "verification" in context

    def test_review_includes_quality_criteria(self, isolated_sagtask, mock_git):
        """Context should include code quality criteria."""
        self._create_task_with_step(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_review({
            "sag_task_id": "test-review",
            "scope": "step",
        })
        context = result["context"].lower()
        assert "quality" in context or "readable" in context or "test" in context

    def test_review_scope_step(self, isolated_sagtask, mock_git):
        """Step scope should focus on current step only."""
        self._create_task_with_step(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_review({
            "sag_task_id": "test-review",
            "scope": "step",
        })
        assert result["scope"] == "step"
        assert "Build Parser" in result["context"]

    def test_review_scope_phase(self, isolated_sagtask, mock_git):
        """Phase scope should include all steps in current phase."""
        self._create_task_with_step(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_review({
            "sag_task_id": "test-review",
            "scope": "phase",
        })
        assert result["scope"] == "phase"
        assert "Phase 1" in result["context"]

    def test_review_default_scope(self, isolated_sagtask, mock_git):
        """Default scope should be 'step'."""
        self._create_task_with_step(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_review({
            "sag_task_id": "test-review",
        })
        assert result["ok"] is True
        assert result["scope"] == "step"

    def test_review_no_task(self, isolated_sagtask, mock_git):
        """Should return error when no task_id and no active task."""
        result = sagtask._handle_sag_task_review({"scope": "step"})
        assert result["ok"] is False
        assert "error" in result

    def test_review_includes_verification_commands(self, isolated_sagtask, mock_git):
        """Context should include verification commands from step config."""
        self._create_task_with_step(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_review({
            "sag_task_id": "test-review",
            "scope": "step",
        })
        assert "pytest" in result["context"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python -m pytest tests/test_review.py -v`
Expected: FAIL with `_handle_sag_task_review` not defined

- [ ] **Step 3: Add TASK_REVIEW_SCHEMA to schemas.py**

```python
TASK_REVIEW_SCHEMA: Dict[str, Any] = {
    "name": "sag_task_review",
    "description": "Build a structured review prompt for the current step. "
    "Supports two-stage review: spec compliance first, then code quality. "
    "Returns review criteria based on step verification and methodology.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {
                "type": "string",
                "description": "Task ID. Defaults to active task.",
            },
            "scope": {
                "type": "string",
                "enum": ["step", "phase", "full"],
                "description": "Review scope. Default: step.",
            },
        },
    },
}
```

Add to `ALL_TOOL_SCHEMAS`:
```python
    TASK_REVIEW_SCHEMA,
```

- [ ] **Step 4: Add review handler to _orchestration.py**

Add to `handlers/_orchestration.py`:

```python
def _build_review_context(
    step_obj: Dict[str, Any],
    scope: str,
    state: Dict[str, Any],
) -> str:
    """Build a structured review prompt."""
    step_name = step_obj.get("name", "Unknown Step")
    step_desc = step_obj.get("description", "")

    lines = [
        f"## Code Review: {step_name}",
        f"**Scope:** {scope}",
        "",
        "### Stage 1: Spec Compliance",
        "Verify the implementation matches the requirements:",
    ]

    if step_desc:
        lines.append(f"- Requirement: {step_desc}")

    # Verification commands
    verification = step_obj.get("verification", {})
    commands = verification.get("commands", [])
    if commands:
        lines.append("- Verification commands:")
        for cmd in commands:
            lines.append(f"  ```bash\n  {cmd}\n  ```")

    must_pass = verification.get("must_pass", False)
    if must_pass:
        lines.append("- **MUST PASS** before advancing")

    # Methodology-specific criteria
    methodology = step_obj.get("methodology", {}).get("type", "none")
    lines.extend(["", "### Stage 2: Code Quality"])

    if methodology == "tdd":
        lines.extend([
            "Check TDD compliance:",
            "- Tests exist for new functionality",
            "- Tests were written before implementation",
            "- Coverage meets threshold",
            "- Code is readable and well-named",
        ])
    elif methodology == "brainstorm":
        lines.extend([
            "Check design quality:",
            "- Design rationale is documented",
            "- Trade-offs are explicitly stated",
            "- Implementation matches selected design",
        ])
    else:
        lines.extend([
            "General quality checks:",
            "- Code is readable and well-named",
            "- Functions are focused (<50 lines)",
            "- Error handling is explicit",
            "- Tests exist for new functionality",
        ])

    # Review severity guide
    lines.extend([
        "",
        "### Review Severity Levels",
        "| Level | Meaning | Action |",
        "|-------|---------|--------|",
        "| CRITICAL | Security vulnerability or data loss | BLOCK |",
        "| HIGH | Bug or significant quality issue | WARN |",
        "| MEDIUM | Maintainability concern | INFO |",
        "| LOW | Style or minor suggestion | NOTE |",
    ])

    return "\n".join(lines)


def _handle_sag_task_review(args: Dict[str, Any]) -> Dict[str, Any]:
    """Build a structured review prompt for the current step."""
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    scope = args.get("scope", "step")

    if scope not in ("step", "phase", "full"):
        return {"ok": False, "error": f"Invalid scope '{scope}'. Must be step, phase, or full."}

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    step_obj = p._get_current_step_object(state)
    if not step_obj:
        return {"ok": False, "error": "Cannot find current step in task phases."}

    context = _build_review_context(
        step_obj=step_obj,
        scope=scope,
        state=state,
    )

    return {
        "ok": True,
        "sag_task_id": task_id,
        "scope": scope,
        "step_id": step_obj.get("id", "unknown"),
        "context": context,
        "message": f"Review context built for scope '{scope}'. Use this to dispatch a review subagent.",
    }
```

- [ ] **Step 5: Update handlers/__init__.py**

Add to imports from `_orchestration`:
```python
from ._orchestration import (
    _handle_sag_task_dispatch,
    _handle_sag_task_review,
)
```

Add to `_tool_handlers`:
```python
    "sag_task_review": _handle_sag_task_review,
```

Add to `__all__`:
```python
    "_handle_sag_task_review",
```

- [ ] **Step 6: Update __init__.py**

Add re-export and schema import.

- [ ] **Step 7: Run tests**

Run: `PYTHONPATH=src python -m pytest tests/test_review.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/sagtask/schemas.py src/sagtask/handlers/_orchestration.py src/sagtask/handlers/__init__.py src/sagtask/__init__.py tests/test_review.py
git commit -m "feat: add sag_task_review tool for two-stage code review"
```

---

### Task 3: Enhance context injection with dispatch status

**Files:**
- Modify: `src/sagtask/plugin.py` (`_build_task_context` method)
- Modify: `tests/test_context_injection.py`

**Context:** When subtasks are in-progress (dispatched), the context injection should show which subtasks are actively being worked on. This gives the LLM awareness of parallel work.

- [ ] **Step 1: Write failing test**

Add to `tests/test_context_injection.py`:

```python
    def test_context_shows_active_dispatches(self, isolated_sagtask, mock_git):
        """Context should show in-progress subtasks as active dispatches."""
        self._create_task_with_methodology(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_plan({"sag_task_id": "test-ctx"})
        plan_path = isolated_sagtask.get_task_root("test-ctx") / ".sag_plans" / "step-1.json"
        plan = json.loads(plan_path.read_text())
        first_id = plan["subtasks"][0]["id"]
        sagtask._handle_sag_task_plan_update({
            "sag_task_id": "test-ctx",
            "subtask_id": first_id,
            "status": "in_progress",
        })
        result = sagtask._on_pre_llm_call(
            session_id="test", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert "in_progress" in result["context"].lower() or "dispatched" in result["context"].lower() or "active" in result["context"].lower()
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `PYTHONPATH=src python -m pytest tests/test_context_injection.py::TestContextInjection::test_context_shows_active_dispatches -v`
Expected: May already pass if context shows subtask_progress with in_progress > 0

- [ ] **Step 3: If needed, enhance _build_task_context in plugin.py**

In `_build_task_context`, after the plan progress line, add dispatch awareness:

```python
                in_progress_count = progress.get("in_progress", 0)
                if in_progress_count > 0:
                    lines.append(f"- Active dispatches: {in_progress_count} subtask(s) in-progress")
```

- [ ] **Step 4: Run full test suite**

Run: `PYTHONPATH=src python -m pytest tests/ -q`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/sagtask/plugin.py tests/test_context_injection.py
git commit -m "feat: show active dispatches in context injection"
```

---

### Task 4: Update CHANGELOG and final verification

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update CHANGELOG**

Add under `[Unreleased]`:

```markdown
### Added
- `sag_task_dispatch` tool — build subagent context and dispatch subtasks for execution
- `sag_task_review` tool — two-stage code review (spec compliance + quality)
- Active dispatch status in context injection
- Orchestration handlers module (`handlers/_orchestration.py`)
```

- [ ] **Step 2: Run full test suite with coverage**

Run: `PYTHONPATH=src python -m pytest tests/ --cov=sagtask --cov-report=term-missing --tb=short`
Expected: All PASS, coverage ≥ 80%

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: add Phase 3 features to CHANGELOG"
```

---

## Self-Review Notes

**Dispatch design decision:** `sag_task_dispatch` does NOT spawn sub-processes. It builds context and marks subtasks as in-progress. The LLM uses the returned context to dispatch subagents via Hermes' native Agent tool. This follows the "Hermes native subagent" approach from the proposal's Decision 2.

**Review design decision:** `sag_task_review` returns structured review criteria, not a review result. The LLM uses this to dispatch a review subagent. This keeps the tool lightweight and the review quality depends on the LLM's capability.

**Result collection:** Already handled by existing `sag_task_plan_update` with `context` → `result` field. No new tool needed.

**Parallel execution:** The dispatch tool works for individual subtasks. Parallel execution is achieved by calling `sag_task_dispatch` multiple times for independent subtasks (no depends_on). The context injection shows in_progress count.
