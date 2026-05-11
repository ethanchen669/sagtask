# Superpowers Integration — Phase 4: Advanced Methodology & Worktree

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add brainstorm and debug methodology handlers, git worktree isolation for dispatch, and methodology auto-recommendation to SagTask.

**Architecture:** Add `sag_task_brainstorm` tool that builds a structured brainstorm prompt and tracks design selection state. Add `sag_task_debug` tool that builds a structured debug prompt and tracks hypothesis/fix state. Extend dispatch with optional worktree creation. Add `_recommend_methodology()` helper for auto-suggesting methodology from step descriptions. Enhance context injection to show brainstorm/debug phases.

**Tech Stack:** Python 3.10+, pytest

**Spec:** `docs/superpowers-integration-proposal.md` — Phase 4 only

---

## File Structure

```
src/sagtask/
├── _utils.py                    ← MODIFY: add _recommend_methodology helper
├── schemas.py                   ← MODIFY: add TASK_BRAINSTORM_SCHEMA, TASK_DEBUG_SCHEMA
├── handlers/
│   ├── __init__.py              ← MODIFY: add brainstorm/debug to _tool_handlers
│   ├── _orchestration.py        ← MODIFY: add _build_brainstorm_context, _build_debug_context
│   └── _plan.py                 ← MODIFY: add _handle_sag_task_brainstorm, _handle_sag_task_debug
├── plugin.py                    ← MODIFY: enhance _build_task_context for brainstorm/debug phases
tests/
├── test_brainstorm.py           ← NEW: tests for brainstorm tool
├── test_debug.py                ← NEW: tests for debug tool
├── test_methodology_recommend.py ← NEW: tests for auto-recommendation
├── test_context_injection.py    ← MODIFY: add tests for brainstorm/debug context
```

---

### Task 1: Add `sag_task_brainstorm` tool — context builder and design selection

**Files:**
- Modify: `src/sagtask/schemas.py` (add TASK_BRAINSTORM_SCHEMA)
- Modify: `src/sagtask/handlers/_orchestration.py` (add `_build_brainstorm_context`)
- Modify: `src/sagtask/handlers/_plan.py` (add `_handle_sag_task_brainstorm`)
- Modify: `src/sagtask/handlers/__init__.py` (add to _tool_handlers)
- Modify: `src/sagtask/__init__.py` (add re-exports)
- Create: `tests/test_brainstorm.py`

**Context:** `sag_task_brainstorm` builds a structured brainstorm prompt for the current step. When called without `selected_option`, it returns a context prompt guiding the LLM to generate 3+ design options with trade-offs. When called with `selected_option`, it records the user's choice in state and transitions brainstorm_phase from "explore" to "select". The brainstorm state is stored in `methodology_state.brainstorm_*` fields.

The workflow:
1. LLM calls `sag_task_brainstorm` → gets brainstorm context prompt
2. LLM generates 3+ design options, presents to user
3. User picks one → LLM calls `sag_task_brainstorm(selected_option=1)` → records selection
4. LLM implements the selected design
5. LLM calls `sag_task_verify` → verification runs

- [ ] **Step 1: Write failing tests for brainstorm**

Create `tests/test_brainstorm.py`:

```python
"""Tests for sag_task_brainstorm tool."""
import json
import pytest
import sagtask


class TestBrainstorm:
    def _create_brainstorm_task(self, plugin, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-brain",
            "name": "Test Brainstorm",
            "phases": [{
                "id": "phase-1",
                "name": "Design",
                "steps": [{
                    "id": "step-1",
                    "name": "Design Parser",
                    "description": "Design a JSON parser with error recovery",
                    "methodology": {"type": "brainstorm"},
                }],
            }],
        })

    def test_brainstorm_returns_context(self, isolated_sagtask, mock_git):
        """Brainstorm should return a structured brainstorm context prompt."""
        self._create_brainstorm_task(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_brainstorm({
            "sag_task_id": "test-brain",
        })
        assert result["ok"] is True
        assert "context" in result
        assert "brainstorm" in result["context"].lower() or "design" in result["context"].lower()

    def test_brainstorm_sets_explore_phase(self, isolated_sagtask, mock_git):
        """Brainstorm should set brainstorm_phase to explore."""
        self._create_brainstorm_task(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_brainstorm({"sag_task_id": "test-brain"})
        state = isolated_sagtask.load_task_state("test-brain")
        ms = state.get("methodology_state", {})
        assert ms.get("brainstorm_phase") == "explore"

    def test_brainstorm_records_selection(self, isolated_sagtask, mock_git):
        """Brainstorm with selected_option should record selection and set phase to select."""
        self._create_brainstorm_task(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_brainstorm({"sag_task_id": "test-brain"})
        result = sagtask._handle_sag_task_brainstorm({
            "sag_task_id": "test-brain",
            "selected_option": 1,
        })
        assert result["ok"] is True
        state = isolated_sagtask.load_task_state("test-brain")
        ms = state.get("methodology_state", {})
        assert ms.get("brainstorm_phase") == "select"
        assert ms.get("brainstorm_selected") == 1

    def test_brainstorm_records_custom_design(self, isolated_sagtask, mock_git):
        """Brainstorm with custom design details should record them."""
        self._create_brainstorm_task(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_brainstorm({
            "sag_task_id": "test-brain",
            "selected_option": 0,
            "design_title": "Recursive Descent Parser",
            "design_description": "Use recursive descent with error recovery tokens",
        })
        assert result["ok"] is True
        state = isolated_sagtask.load_task_state("test-brain")
        ms = state.get("methodology_state", {})
        assert ms.get("brainstorm_selected_design", {}).get("title") == "Recursive Descent Parser"

    def test_brainstorm_includes_step_info(self, isolated_sagtask, mock_git):
        """Context should include step name and description."""
        self._create_brainstorm_task(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_brainstorm({"sag_task_id": "test-brain"})
        assert "Design Parser" in result["context"]
        assert "JSON parser" in result["context"]

    def test_brainstorm_no_task(self, isolated_sagtask, mock_git):
        """Should return error when no task_id and no active task."""
        result = sagtask._handle_sag_task_brainstorm({})
        assert result["ok"] is False
        assert "error" in result

    def test_brainstorm_already_selected(self, isolated_sagtask, mock_git):
        """Should warn when design already selected."""
        self._create_brainstorm_task(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_brainstorm({"sag_task_id": "test-brain"})
        sagtask._handle_sag_task_brainstorm({
            "sag_task_id": "test-brain",
            "selected_option": 1,
        })
        result = sagtask._handle_sag_task_brainstorm({
            "sag_task_id": "test-brain",
            "selected_option": 2,
        })
        assert result["ok"] is True
        assert "warning" in result or "already" in result.get("message", "").lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python -m pytest tests/test_brainstorm.py -v`
Expected: FAIL with `_handle_sag_task_brainstorm` not defined

- [ ] **Step 3: Add `_build_brainstorm_context` to `_orchestration.py`**

Add after `_build_review_context`:

```python
def _build_brainstorm_context(
    step_obj: Dict[str, Any],
    state: Dict[str, Any],
) -> str:
    """Build a structured brainstorm prompt for design exploration."""
    step_name = step_obj.get("name", "Unknown Step")
    step_desc = step_obj.get("description", "")

    lines = [
        f"## Design Brainstorm: {step_name}",
        "",
        "### Step Requirements",
    ]
    if step_desc:
        lines.append(f"- {step_desc}")
    else:
        lines.append(f"- {step_name}")

    methodology_config = step_obj.get("methodology", {}).get("config", {})
    min_options = methodology_config.get("min_options", 3)

    lines.extend([
        "",
        "### Instructions",
        f"Generate at least {min_options} distinct design options for this step.",
        "",
        "For each option, provide:",
        "- **Title**: A concise name for the design approach",
        "- **Description**: 2-3 sentences explaining the approach",
        "- **Trade-offs**: Pros and cons of this approach",
        "",
        "Present options as a numbered list. After presenting, ask the user to select one.",
        "",
        "### Design Evaluation Criteria",
        "- Simplicity: Is the approach easy to understand and maintain?",
        "- Correctness: Does it handle all requirements and edge cases?",
        "- Performance: Are there any performance concerns?",
        "- Extensibility: Can the design accommodate future changes?",
    ])

    # Show verification requirements if any
    verification = step_obj.get("verification", {})
    commands = verification.get("commands", [])
    if commands:
        lines.extend([
            "",
            "### Verification",
            "After implementation, these commands must pass:",
            *[f"```bash\n{cmd}\n```" for cmd in commands],
        ])

    return "\n".join(lines)
```

- [ ] **Step 4: Add `_handle_sag_task_brainstorm` to `_plan.py`**

Add after `_handle_sag_task_plan_update`:

```python
def _handle_sag_task_brainstorm(args: Dict[str, Any]) -> Dict[str, Any]:
    """Build brainstorm context or record design selection."""
    from ._orchestration import _build_brainstorm_context

    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    selected_option = args.get("selected_option")
    design_title = args.get("design_title", "")
    design_description = args.get("design_description", "")

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    step_obj = p._get_current_step_object(state)
    if not step_obj:
        return {"ok": False, "error": "Cannot find current step in task phases."}

    ms = state.get("methodology_state", {})
    current_phase = ms.get("brainstorm_phase", "explore")

    # If recording a selection
    if selected_option is not None:
        if current_phase == "select":
            return {
                "ok": True,
                "sag_task_id": task_id,
                "brainstorm_phase": "select",
                "warning": "Design already selected. Use plan_update to track implementation progress.",
                "message": f"Design option {ms.get('brainstorm_selected')} was already selected.",
            }

        selected_design = {}
        if design_title:
            selected_design = {"title": design_title, "description": design_description}

        state = {
            **state,
            "methodology_state": {
                **ms,
                "brainstorm_phase": "select",
                "brainstorm_selected": selected_option,
                "brainstorm_selected_design": selected_design,
            },
        }
        p.save_task_state(task_id, state)

        return {
            "ok": True,
            "sag_task_id": task_id,
            "brainstorm_phase": "select",
            "selected_option": selected_option,
            "selected_design": selected_design,
            "message": f"Selected design option {selected_option}. Proceed with implementation.",
        }

    # Building brainstorm context (explore phase)
    if current_phase == "explore" and not ms.get("brainstorm_phase"):
        state = {
            **state,
            "methodology_state": {
                **ms,
                "brainstorm_phase": "explore",
            },
        }
        p.save_task_state(task_id, state)

    context = _build_brainstorm_context(step_obj=step_obj, state=state)

    return {
        "ok": True,
        "sag_task_id": task_id,
        "brainstorm_phase": ms.get("brainstorm_phase", "explore"),
        "step_id": step_obj.get("id", "unknown"),
        "context": context,
        "message": "Use this context to generate design options. Call again with selected_option to record choice.",
    }
```

- [ ] **Step 5: Add TASK_BRAINSTORM_SCHEMA to schemas.py**

Add after `TASK_REVIEW_SCHEMA`:

```python
TASK_BRAINSTORM_SCHEMA = {
    "name": "sag_task_brainstorm",
    "description": "Build a structured brainstorm prompt for design exploration. "
    "Returns context for generating design options. Call with selected_option to record user's choice.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {
                "type": "string",
                "description": "Task ID. Defaults to active task.",
            },
            "selected_option": {
                "type": "integer",
                "description": "Which design option the user selected (1-indexed). "
                "Omit to generate options; include to record selection.",
            },
            "design_title": {
                "type": "string",
                "description": "Title of the selected design (optional, for recording).",
            },
            "design_description": {
                "type": "string",
                "description": "Description of the selected design (optional, for recording).",
            },
        },
        "required": [],
    },
}
```

Add `TASK_BRAINSTORM_SCHEMA` to `ALL_TOOL_SCHEMAS`.

- [ ] **Step 6: Update handlers/__init__.py and __init__.py**

Add import and handler entry:

```python
# handlers/__init__.py
from ._plan import (
    _handle_sag_task_plan,
    _handle_sag_task_plan_update,
    _handle_sag_task_relate,
    _handle_sag_task_verify,
    _handle_sag_task_brainstorm,
)
```

Add to `_tool_handlers`:
```python
    "sag_task_brainstorm": _handle_sag_task_brainstorm,
```

Add to `__all__`:
```python
    "_handle_sag_task_brainstorm",
```

In `src/sagtask/__init__.py`, add re-export:
```python
from sagtask.handlers._plan import (  # noqa: F401
    _handle_sag_task_plan,
    _handle_sag_task_plan_update,
    _handle_sag_task_relate,
    _handle_sag_task_verify,
    _handle_sag_task_brainstorm,
)
```

Add schema import:
```python
    TASK_BRAINSTORM_SCHEMA,
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/test_brainstorm.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/sagtask/schemas.py src/sagtask/handlers/_orchestration.py src/sagtask/handlers/_plan.py src/sagtask/handlers/__init__.py src/sagtask/__init__.py tests/test_brainstorm.py
git commit -m "feat: add sag_task_brainstorm tool for design exploration"
```

---

### Task 2: Add `sag_task_debug` tool — structured debugging workflow

**Files:**
- Modify: `src/sagtask/schemas.py` (add TASK_DEBUG_SCHEMA)
- Modify: `src/sagtask/handlers/_orchestration.py` (add `_build_debug_context`)
- Modify: `src/sagtask/handlers/_plan.py` (add `_handle_sag_task_debug`)
- Modify: `src/sagtask/handlers/__init__.py` (add to _tool_handlers)
- Modify: `src/sagtask/__init__.py` (add re-exports)
- Create: `tests/test_debug.py`

**Context:** `sag_task_debug` builds a structured debugging prompt for the current step. It tracks the debug workflow through phases: reproduce → diagnose → fix → verify. The LLM calls this tool to get structured debugging guidance. Calling with `hypothesis` records the current hypothesis. Calling with `fix_description` records the fix and transitions to verify phase.

The workflow:
1. LLM calls `sag_task_debug` → gets debug context (reproduce phase)
2. LLM reproduces the issue, calls `sag_task_debug(hypothesis="...")` → records hypothesis (diagnose phase)
3. LLM implements fix, calls `sag_task_debug(fix_description="...")` → records fix (fix phase)
4. LLM calls `sag_task_verify` → verification runs → transitions to verify phase

- [ ] **Step 1: Write failing tests for debug**

Create `tests/test_debug.py`:

```python
"""Tests for sag_task_debug tool."""
import pytest
import sagtask


class TestDebug:
    def _create_debug_task(self, plugin, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-debug",
            "name": "Test Debug",
            "phases": [{
                "id": "phase-1",
                "name": "Fix",
                "steps": [{
                    "id": "step-1",
                    "name": "Fix Parser Crash",
                    "description": "Parser crashes on nested arrays deeper than 10 levels",
                    "methodology": {"type": "debug"},
                }],
            }],
        })

    def test_debug_returns_context(self, isolated_sagtask, mock_git):
        """Debug should return a structured debug context prompt."""
        self._create_debug_task(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_debug({
            "sag_task_id": "test-debug",
        })
        assert result["ok"] is True
        assert "context" in result
        assert "debug" in result["context"].lower() or "reproduce" in result["context"].lower()

    def test_debug_sets_reproduce_phase(self, isolated_sagtask, mock_git):
        """Debug should set debug_phase to reproduce initially."""
        self._create_debug_task(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_debug({"sag_task_id": "test-debug"})
        state = isolated_sagtask.load_task_state("test-debug")
        ms = state.get("methodology_state", {})
        assert ms.get("debug_phase") == "reproduce"

    def test_debug_records_hypothesis(self, isolated_sagtask, mock_git):
        """Debug with hypothesis should record it and set phase to diagnose."""
        self._create_debug_task(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_debug({"sag_task_id": "test-debug"})
        result = sagtask._handle_sag_task_debug({
            "sag_task_id": "test-debug",
            "hypothesis": "Stack overflow from unbounded recursion",
        })
        assert result["ok"] is True
        state = isolated_sagtask.load_task_state("test-debug")
        ms = state.get("methodology_state", {})
        assert ms.get("debug_phase") == "diagnose"
        assert ms.get("debug_hypothesis") == "Stack overflow from unbounded recursion"

    def test_debug_records_fix(self, isolated_sagtask, mock_git):
        """Debug with fix_description should record fix and set phase to fix."""
        self._create_debug_task(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_debug({"sag_task_id": "test-debug"})
        sagtask._handle_sag_task_debug({
            "sag_task_id": "test-debug",
            "hypothesis": "Stack overflow from unbounded recursion",
        })
        result = sagtask._handle_sag_task_debug({
            "sag_task_id": "test-debug",
            "fix_description": "Added max_depth=100 parameter with ValueError on exceed",
        })
        assert result["ok"] is True
        state = isolated_sagtask.load_task_state("test-debug")
        ms = state.get("methodology_state", {})
        assert ms.get("debug_phase") == "fix"
        assert "max_depth" in ms.get("debug_fix", "")

    def test_debug_includes_step_info(self, isolated_sagtask, mock_git):
        """Context should include step name and description."""
        self._create_debug_task(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_debug({"sag_task_id": "test-debug"})
        assert "Fix Parser Crash" in result["context"]
        assert "nested arrays" in result["context"]

    def test_debug_no_task(self, isolated_sagtask, mock_git):
        """Should return error when no task_id and no active task."""
        result = sagtask._handle_sag_task_debug({})
        assert result["ok"] is False
        assert "error" in result

    def test_debug_phase_progression(self, isolated_sagtask, mock_git):
        """Debug phases should progress: reproduce → diagnose → fix."""
        self._create_debug_task(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_debug({"sag_task_id": "test-debug"})
        sagtask._handle_sag_task_debug({
            "sag_task_id": "test-debug",
            "hypothesis": "Null pointer on empty input",
        })
        sagtask._handle_sag_task_debug({
            "sag_task_id": "test-debug",
            "fix_description": "Added null check",
        })
        state = isolated_sagtask.load_task_state("test-debug")
        ms = state.get("methodology_state", {})
        assert ms.get("debug_phase") == "fix"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python -m pytest tests/test_debug.py -v`
Expected: FAIL with `_handle_sag_task_debug` not defined

- [ ] **Step 3: Add `_build_debug_context` to `_orchestration.py`**

Add after `_build_brainstorm_context`:

```python
def _build_debug_context(
    step_obj: Dict[str, Any],
    state: Dict[str, Any],
) -> str:
    """Build a structured debug prompt for systematic debugging."""
    step_name = step_obj.get("name", "Unknown Step")
    step_desc = step_obj.get("description", "")

    ms = state.get("methodology_state", {})
    debug_phase = ms.get("debug_phase", "reproduce")
    hypothesis = ms.get("debug_hypothesis", "")
    fix = ms.get("debug_fix", "")

    lines = [
        f"## Debugging: {step_name}",
        f"**Current phase:** {debug_phase}",
        "",
        "### Issue Description",
    ]
    if step_desc:
        lines.append(f"- {step_desc}")
    else:
        lines.append(f"- {step_name}")

    lines.extend([
        "",
        "### Debug Methodology",
    ])

    if debug_phase == "reproduce":
        lines.extend([
            "1. **Reproduce** the issue with a minimal test case",
            "   - Write the smallest possible code that triggers the bug",
            "   - Confirm the bug is reproducible",
            "   - Document the exact error/behavior",
            "",
            "After reproducing, call `sag_task_debug` with `hypothesis` to record your diagnosis.",
        ])
    elif debug_phase == "diagnose":
        lines.extend([
            "1. ~~Reproduce~~ ✓",
            f"2. **Diagnose** — Current hypothesis: *{hypothesis}*",
            "   - Verify the hypothesis with targeted tests",
            "   - If wrong, call `sag_task_debug` with a new hypothesis",
            "   - If confirmed, proceed to fix",
            "",
            "After confirming the root cause, call `sag_task_debug` with `fix_description`.",
        ])
    elif debug_phase == "fix":
        lines.extend([
            "1. ~~Reproduce~~ ✓",
            f"2. ~~Diagnose~~ ✓ — {hypothesis}",
            f"3. **Fix** — Proposed fix: *{fix}*",
            "   - Implement the minimal fix for the root cause",
            "   - Do NOT fix symptoms; fix the underlying issue",
            "   - Run verification to confirm the fix works",
            "",
            "After implementing, call `sag_task_verify` to validate.",
        ])

    # Show previous verification results if any
    last_v = ms.get("last_verification")
    if last_v:
        v_status = "passed" if last_v.get("passed") else "failed"
        lines.extend([
            "",
            f"### Last Verification: {v_status}",
        ])

    verification = step_obj.get("verification", {})
    commands = verification.get("commands", [])
    if commands:
        lines.extend([
            "",
            "### Verification Commands",
            *[f"```bash\n{cmd}\n```" for cmd in commands],
        ])

    return "\n".join(lines)
```

- [ ] **Step 4: Add `_handle_sag_task_debug` to `_plan.py`**

Add after `_handle_sag_task_brainstorm`:

```python
def _handle_sag_task_debug(args: Dict[str, Any]) -> Dict[str, Any]:
    """Build debug context or record hypothesis/fix."""
    from ._orchestration import _build_debug_context

    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    hypothesis = args.get("hypothesis", "")
    fix_description = args.get("fix_description", "")

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    step_obj = p._get_current_step_object(state)
    if not step_obj:
        return {"ok": False, "error": "Cannot find current step in task phases."}

    ms = state.get("methodology_state", {})
    debug_phase = ms.get("debug_phase", "reproduce")

    # Record fix
    if fix_description:
        state = {
            **state,
            "methodology_state": {
                **ms,
                "debug_phase": "fix",
                "debug_fix": fix_description,
            },
        }
        p.save_task_state(task_id, state)
        return {
            "ok": True,
            "sag_task_id": task_id,
            "debug_phase": "fix",
            "fix_description": fix_description,
            "message": "Fix recorded. Run sag_task_verify to validate.",
        }

    # Record hypothesis
    if hypothesis:
        new_phase = "diagnose"
        state = {
            **state,
            "methodology_state": {
                **ms,
                "debug_phase": new_phase,
                "debug_hypothesis": hypothesis,
            },
        }
        p.save_task_state(task_id, state)
        return {
            "ok": True,
            "sag_task_id": task_id,
            "debug_phase": new_phase,
            "hypothesis": hypothesis,
            "message": "Hypothesis recorded. Verify it, then call with fix_description.",
        }

    # Build debug context
    if not ms.get("debug_phase"):
        state = {
            **state,
            "methodology_state": {
                **ms,
                "debug_phase": "reproduce",
            },
        }
        p.save_task_state(task_id, state)

    context = _build_debug_context(step_obj=step_obj, state=state)

    return {
        "ok": True,
        "sag_task_id": task_id,
        "debug_phase": ms.get("debug_phase", "reproduce"),
        "step_id": step_obj.get("id", "unknown"),
        "context": context,
        "message": "Follow the debug methodology. Record hypothesis or fix as you progress.",
    }
```

- [ ] **Step 5: Add TASK_DEBUG_SCHEMA to schemas.py**

Add after `TASK_BRAINSTORM_SCHEMA`:

```python
TASK_DEBUG_SCHEMA = {
    "name": "sag_task_debug",
    "description": "Build a structured debug prompt for systematic debugging. "
    "Tracks workflow: reproduce → diagnose → fix. Record hypothesis or fix to progress.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {
                "type": "string",
                "description": "Task ID. Defaults to active task.",
            },
            "hypothesis": {
                "type": "string",
                "description": "Current root cause hypothesis. Records diagnosis.",
            },
            "fix_description": {
                "type": "string",
                "description": "Description of the fix. Records fix and transitions to verify.",
            },
        },
        "required": [],
    },
}
```

Add `TASK_DEBUG_SCHEMA` to `ALL_TOOL_SCHEMAS`.

- [ ] **Step 6: Update handlers/__init__.py and __init__.py**

Add import and handler entry for `_handle_sag_task_debug`.

In `src/sagtask/__init__.py`, add re-export and schema import.

- [ ] **Step 7: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/test_debug.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/sagtask/schemas.py src/sagtask/handlers/_orchestration.py src/sagtask/handlers/_plan.py src/sagtask/handlers/__init__.py src/sagtask/__init__.py tests/test_debug.py
git commit -m "feat: add sag_task_debug tool for structured debugging workflow"
```

---

### Task 3: Enhance context injection with brainstorm/debug phases

**Files:**
- Modify: `src/sagtask/plugin.py` (`_build_task_context` method)
- Modify: `tests/test_context_injection.py`

**Context:** When brainstorm or debug methodology is active, the context injection should show the current phase and relevant state (selected design for brainstorm, hypothesis for debug).

- [ ] **Step 1: Write failing tests**

Add to `tests/test_context_injection.py`:

```python
    def test_context_shows_brainstorm_phase(self, isolated_sagtask, mock_git):
        """Context should show brainstorm phase when brainstorm methodology is active."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-ctx-brain",
            "name": "Brainstorm Context",
            "phases": [{
                "id": "p1", "name": "P1",
                "steps": [{
                    "id": "s1", "name": "Design Module",
                    "methodology": {"type": "brainstorm"},
                }],
            }],
        })
        sagtask._handle_sag_task_brainstorm({"sag_task_id": "test-ctx-brain"})
        isolated_sagtask._active_task_id = "test-ctx-brain"
        result = sagtask._on_pre_llm_call(
            session_id="s1", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert "brainstorm" in result["context"].lower() or "explore" in result["context"].lower()

    def test_context_shows_debug_phase(self, isolated_sagtask, mock_git):
        """Context should show debug phase when debug methodology is active."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-ctx-debug",
            "name": "Debug Context",
            "phases": [{
                "id": "p1", "name": "P1",
                "steps": [{
                    "id": "s1", "name": "Fix Bug",
                    "methodology": {"type": "debug"},
                }],
            }],
        })
        sagtask._handle_sag_task_debug({"sag_task_id": "test-ctx-debug"})
        isolated_sagtask._active_task_id = "test-ctx-debug"
        result = sagtask._on_pre_llm_call(
            session_id="s1", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert "debug" in result["context"].lower() or "reproduce" in result["context"].lower()
```

- [ ] **Step 2: Run tests to verify they fail or pass**

Run: `PYTHONPATH=src python -m pytest tests/test_context_injection.py::TestContextInjection::test_context_shows_brainstorm_phase tests/test_context_injection.py::TestContextInjection::test_context_shows_debug_phase -v`
Expected: FAIL — brainstorm/debug phases not yet injected

- [ ] **Step 3: Enhance `_build_task_context` in plugin.py**

In `_build_task_context`, after the TDD phase line (around line 280), add brainstorm/debug phase injection:

```python
                tdd_phase = ms.get("tdd_phase")
                if tdd_phase and methodology == "tdd":
                    lines.append(f"- TDD phase: {tdd_phase.upper()}")
                brainstorm_phase = ms.get("brainstorm_phase")
                if brainstorm_phase and methodology == "brainstorm":
                    selected = ms.get("brainstorm_selected")
                    phase_text = brainstorm_phase
                    if selected:
                        phase_text = f"selected option {selected}"
                    lines.append(f"- Brainstorm phase: {phase_text}")
                debug_phase = ms.get("debug_phase")
                if debug_phase and methodology == "debug":
                    hypothesis = ms.get("debug_hypothesis", "")
                    phase_text = debug_phase
                    if hypothesis and debug_phase == "diagnose":
                        phase_text = f"diagnosing: {hypothesis}"
                    elif debug_phase == "fix":
                        phase_text = "fixing"
                    lines.append(f"- Debug phase: {phase_text}")
```

- [ ] **Step 4: Run full test suite**

Run: `PYTHONPATH=src python -m pytest tests/ -q`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/sagtask/plugin.py tests/test_context_injection.py
git commit -m "feat: show brainstorm/debug phases in context injection"
```

---

### Task 4: Methodology auto-recommendation

**Files:**
- Modify: `src/sagtask/_utils.py` (add `_recommend_methodology`)
- Create: `tests/test_methodology_recommend.py`

**Context:** `_recommend_methodology(step_name, step_description)` analyzes the step's name and description to suggest the most appropriate methodology. It uses keyword matching: "test"/"coverage" → tdd, "design"/"explore"/"architect" → brainstorm, "bug"/"fix"/"crash"/"error" → debug, "plan"/"break down" → plan-execute. Returns a list of (methodology, confidence, reason) tuples sorted by confidence.

- [ ] **Step 1: Write failing tests**

Create `tests/test_methodology_recommend.py`:

```python
"""Tests for _recommend_methodology helper."""
import pytest
from sagtask._utils import _recommend_methodology


class TestRecommendMethodology:
    def test_suggests_tdd_for_test_keywords(self):
        results = _recommend_methodology("Write unit tests", "Add test coverage for parser")
        assert len(results) > 0
        assert results[0][0] == "tdd"

    def test_suggests_brainstorm_for_design_keywords(self):
        results = _recommend_methodology("Design API", "Explore architecture options for the service")
        assert len(results) > 0
        assert results[0][0] == "brainstorm"

    def test_suggests_debug_for_bug_keywords(self):
        results = _recommend_methodology("Fix crash", "Parser crashes on empty input")
        assert len(results) > 0
        assert results[0][0] == "debug"

    def test_suggests_plan_execute_for_planning_keywords(self):
        results = _recommend_methodology("Plan migration", "Break down database migration into steps")
        assert len(results) > 0
        assert results[0][0] == "plan-execute"

    def test_returns_empty_for_no_keywords(self):
        results = _recommend_methodology("Do stuff", "Things and things")
        assert isinstance(results, list)

    def test_returns_tuples_with_confidence(self):
        results = _recommend_methodology("Test parser", "Write tests for JSON parser")
        assert len(results) > 0
        for methodology, confidence, reason in results:
            assert isinstance(methodology, str)
            assert isinstance(confidence, (int, float))
            assert isinstance(reason, str)

    def test_multiple_keywords_higher_confidence(self):
        single = _recommend_methodology("Test", "")
        multi = _recommend_methodology("Test coverage", "Write unit tests with pytest")
        if single and multi:
            assert multi[0][1] >= single[0][1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python -m pytest tests/test_methodology_recommend.py -v`
Expected: FAIL with `_recommend_methodology` not defined

- [ ] **Step 3: Implement `_recommend_methodology` in `_utils.py`**

Add after `_load_plan`:

```python
# Methodology recommendation keywords
_METHODOLOGY_KEYWORDS: Dict[str, Dict[str, Any]] = {
    "tdd": {
        "keywords": ["test", "coverage", "unit test", "pytest", "spec", "assert", "tdd"],
        "reason": "Step involves testing or test-driven development",
    },
    "brainstorm": {
        "keywords": ["design", "explore", "architect", "option", "trade-off", "evaluate", "compare"],
        "reason": "Step involves design exploration or evaluation",
    },
    "debug": {
        "keywords": ["bug", "fix", "crash", "error", "broken", "fail", "regression", "debug"],
        "reason": "Step involves fixing a bug or debugging",
    },
    "plan-execute": {
        "keywords": ["plan", "break down", "decompose", "migration", "refactor", "phase"],
        "reason": "Step involves planning or breaking work into phases",
    },
}


def _recommend_methodology(
    step_name: str, step_description: str
) -> list[tuple[str, float, str]]:
    """Recommend methodology based on step name and description.

    Returns list of (methodology, confidence, reason) sorted by confidence descending.
    """
    text = f"{step_name} {step_description}".lower()
    results: list[tuple[str, float, str]] = []

    for methodology, config in _METHODOLOGY_KEYWORDS.items():
        keywords = config["keywords"]
        matches = sum(1 for kw in keywords if kw in text)
        if matches > 0:
            confidence = min(matches / len(keywords), 1.0)
            results.append((methodology, confidence, config["reason"]))

    results.sort(key=lambda x: x[1], reverse=True)
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/test_methodology_recommend.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/sagtask/_utils.py tests/test_methodology_recommend.py
git commit -m "feat: add _recommend_methodology for auto-suggesting methodology"
```

---

### Task 5: Git worktree integration for dispatch

**Files:**
- Modify: `src/sagtask/handlers/_orchestration.py` (extend `_handle_sag_task_dispatch` with worktree support)
- Modify: `src/sagtask/plugin.py` (add `create_worktree`, `remove_worktree` methods)
- Modify: `src/sagtask/schemas.py` (add `use_worktree` param to dispatch schema)
- Modify: `tests/test_dispatch.py` (add worktree tests)

**Context:** When `use_worktree=True` is passed to `sag_task_dispatch`, create a git worktree at `<task_root>/.sag_worktrees/<subtask_id>/` and include the worktree path in the returned context. This allows subagents to work in isolation without affecting the main task branch. The worktree is created via `git worktree add`. A `sag_task_worktree_cleanup` tool removes completed worktrees.

- [ ] **Step 1: Write failing tests for worktree dispatch**

Add to `tests/test_dispatch.py`:

```python
    def test_dispatch_with_worktree(self, isolated_sagtask, mock_git):
        """Dispatch with use_worktree should include worktree path in result."""
        self._create_task_with_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        subtask_id = plan["subtasks"][0]["id"]
        mock_git.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = sagtask._handle_sag_task_dispatch({
            "sag_task_id": "test-dispatch",
            "subtask_id": subtask_id,
            "use_worktree": True,
        })
        assert result["ok"] is True
        assert "worktree_path" in result
        assert subtask_id in result["worktree_path"]

    def test_dispatch_worktree_creates_directory(self, isolated_sagtask, mock_git):
        """Dispatch with worktree should call git worktree add."""
        self._create_task_with_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        subtask_id = plan["subtasks"][0]["id"]
        mock_git.return_value = MagicMock(returncode=0, stdout="", stderr="")
        sagtask._handle_sag_task_dispatch({
            "sag_task_id": "test-dispatch",
            "subtask_id": subtask_id,
            "use_worktree": True,
        })
        # Check git worktree add was called
        calls = mock_git.call_args_list
        worktree_calls = [c for c in calls if "worktree" in str(c)]
        assert len(worktree_calls) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python -m pytest tests/test_dispatch.py::TestDispatch::test_dispatch_with_worktree -v`
Expected: FAIL

- [ ] **Step 3: Add `create_worktree` and `remove_worktree` to plugin.py**

Add to `SagTaskPlugin` class:

```python
    def create_worktree(self, task_id: str, subtask_id: str) -> Optional[Path]:
        """Create a git worktree for isolated subtask execution.

        Returns the worktree path, or None on failure.
        """
        task_root = self.get_task_root(task_id)
        worktree_dir = task_root / ".sag_worktrees" / subtask_id
        if worktree_dir.exists():
            return worktree_dir

        branch_name = f"worktree/{subtask_id}"
        try:
            result = subprocess.run(
                ["git", "worktree", "add", "-b", branch_name, str(worktree_dir)],
                cwd=str(task_root),
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
            if result.returncode != 0:
                logger.warning("git worktree add failed: %s", result.stderr)
                return None
            return worktree_dir
        except Exception as e:
            logger.warning("Failed to create worktree: %s", e)
            return None

    def remove_worktree(self, task_id: str, subtask_id: str) -> bool:
        """Remove a git worktree after subtask completion."""
        task_root = self.get_task_root(task_id)
        worktree_dir = task_root / ".sag_worktrees" / subtask_id
        if not worktree_dir.exists():
            return True

        try:
            result = subprocess.run(
                ["git", "worktree", "remove", str(worktree_dir), "--force"],
                cwd=str(task_root),
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
            return result.returncode == 0
        except Exception as e:
            logger.warning("Failed to remove worktree: %s", e)
            return False
```

- [ ] **Step 4: Extend `_handle_sag_task_dispatch` for worktree support**

In `_handle_sag_task_dispatch`, after the plan is loaded and before building context, add worktree creation:

```python
    # Create worktree if requested
    worktree_path = None
    use_worktree = args.get("use_worktree", False)
    if use_worktree:
        worktree_path = p.create_worktree(task_id, subtask_id)
        if not worktree_path:
            return {"ok": False, "error": f"Failed to create worktree for subtask '{subtask_id}'."}
```

And add `worktree_path` to the result dict:

```python
    result: Dict[str, Any] = {
        "ok": True,
        "sag_task_id": task_id,
        "subtask_id": subtask_id,
        "task_root": str(task_root),
        "context": context,
        "message": f"Dispatched subtask '{subtask_id}'. Use the context to execute with a subagent.",
    }
    if worktree_path:
        result["worktree_path"] = str(worktree_path)
        result["message"] = f"Dispatched subtask '{subtask_id}' in worktree. Use the worktree path for isolated execution."
```

- [ ] **Step 5: Add `use_worktree` to dispatch schema**

In `TASK_DISPATCH_SCHEMA`, add:

```python
            "use_worktree": {
                "type": "boolean",
                "description": "Create a git worktree for isolated subtask execution. Default: false.",
            },
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/test_dispatch.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/sagtask/plugin.py src/sagtask/handlers/_orchestration.py src/sagtask/schemas.py tests/test_dispatch.py
git commit -m "feat: add git worktree integration for isolated dispatch"
```

---

### Task 6: Update CHANGELOG and final verification

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update CHANGELOG**

Add under `[Unreleased]`:

```markdown
### Added
- `sag_task_brainstorm` tool — structured design exploration with option selection
- `sag_task_debug` tool — systematic debugging workflow (reproduce → diagnose → fix)
- Brainstorm and debug phase tracking in context injection
- `_recommend_methodology()` helper for auto-suggesting methodology from step descriptions
- Git worktree integration for isolated subtask dispatch (`use_worktree` param)
- `create_worktree`/`remove_worktree` methods on SagTaskPlugin
```

- [ ] **Step 2: Run full test suite with coverage**

Run: `PYTHONPATH=src python -m pytest tests/ --cov=sagtask --cov-report=term-missing --tb=short`
Expected: All PASS, coverage ≥ 80%

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: add Phase 4 features to CHANGELOG"
```

---

## Self-Review Notes

**Brainstorm design decision:** `sag_task_brainstorm` follows the same pattern as `sag_task_review` — it builds a context prompt and returns it. The LLM drives the actual brainstorming. When the user selects an option, the LLM calls the same tool with `selected_option` to record the choice. This keeps the tool lightweight and the design quality depends on the LLM's capability.

**Debug design decision:** `sag_task_debug` uses a simple 3-phase state machine (reproduce → diagnose → fix). The "verify" phase is handled by the existing `sag_task_verify` tool. This avoids duplicating verification logic.

**Worktree design decision:** Worktrees are created at dispatch time via `git worktree add`. The worktree path is returned in the dispatch result so the LLM can direct subagents to work there. Cleanup is manual via `remove_worktree()`. We don't auto-cleanup because the user may want to inspect the worktree after completion.

**Auto-recommendation scope:** `_recommend_methodology` is a pure helper function, not a tool. It can be called by `sag_task_create` or exposed to the LLM via context injection. It uses simple keyword matching — not ML — which is sufficient for this use case.

**Metrics collection (P3):** Deferred to a future phase. The infrastructure (timestamps in state, verify results) is already in place. A dedicated `sag_task_metrics` tool can be added later without schema changes.
