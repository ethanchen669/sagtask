# Layered Context Injection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace flat always-full context injection with a layered, state-aware system that injects only contextually relevant information each turn.

**Architecture:** The `_on_pre_llm_call` hook in `hooks.py` calls a new `_build_layered_context()` method on `SagTaskPlugin`. This method uses an `_InjectionCache` dataclass (keyed by session+task) to detect what changed since last injection, then assembles only the relevant layers (L0-L4b). Dead memory-provider code (`prefetch`, `on_turn_start`, `sync_turn`) is removed. Tool registration changes from `toolset="memory"` to `toolset="sagtask"`.

**Tech Stack:** Python 3.10+, pytest, no new dependencies.

---

### Task 1: Fix toolset registration and remove dead memory-provider code

**Files:**
- Modify: `src/sagtask/__init__.py:117-119`
- Modify: `src/sagtask/plugin.py:32-38, 226-233, 564-571`
- Modify: `tests/test_register.py`

- [ ] **Step 1: Write a test asserting toolset is "sagtask"**

In `tests/test_register.py`, add to `TestRegister`:

```python
def test_register_uses_sagtask_toolset(self):
    sagtask._utils._sagtask_instance = None
    ctx = MagicMock()
    sagtask.register(ctx)
    for call in ctx.register_tool.call_args_list:
        assert call.kwargs.get("toolset") == "sagtask" or call[1].get("toolset") == "sagtask", \
            f"Tool registered with wrong toolset: {call}"
    sagtask._utils._sagtask_instance = None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_register.py::TestRegister::test_register_uses_sagtask_toolset -v`
Expected: FAIL — toolset is "memory"

- [ ] **Step 3: Change toolset to "sagtask"**

In `src/sagtask/__init__.py`, change line 119:

```python
        ctx.register_tool(
            name=tool_name,
            toolset="sagtask",
            schema=schema,
            handler=handler,
            description=schema.get("description", ""),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_register.py::TestRegister::test_register_uses_sagtask_toolset -v`
Expected: PASS

- [ ] **Step 5: Remove dead code from plugin.py**

Remove from `SagTaskPlugin.__init__`:
```python
        self._prefetch_result: str = ""
        self._prefetch_lock = threading.Lock()
```

Remove the `import threading` (check if used elsewhere first — if `threading` is not used by anything else, remove it).

Remove these methods entirely:
- `prefetch(self, query, *, session_id="")`
- `on_turn_start(self, turn_number, message, **kwargs)`
- `sync_turn(self, user_content, assistant_content, *, session_id="")`

- [ ] **Step 6: Run full test suite**

Run: `pytest -x -q`
Expected: All pass. If any test uses `prefetch()` or `on_turn_start()`, update or remove that test.

- [ ] **Step 7: Commit**

```bash
git add src/sagtask/__init__.py src/sagtask/plugin.py tests/test_register.py
git commit -m "fix: change toolset to 'sagtask', remove dead memory-provider methods"
```

---

### Task 2: Add `failed` count to subtask_progress

**Files:**
- Modify: `src/sagtask/handlers/_plan.py:526-539`
- Modify: `tests/test_plan_update.py`

- [ ] **Step 1: Write a test for failed count in subtask_progress**

In `tests/test_plan_update.py`, add:

```python
def test_plan_update_tracks_failed_count(isolated_sagtask, mock_git):
    """subtask_progress includes 'failed' count after status change to failed."""
    task_id = "test-failed"
    sagtask._handle_sag_task_create({
        "sag_task_id": task_id,
        "name": "Test Failed",
        "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
    })
    task_root = isolated_sagtask.get_task_root(task_id)
    plans_dir = task_root / ".sag_plans"
    plans_dir.mkdir()
    plan = {
        "plan_version": 1,
        "step_id": "s1",
        "subtasks": [
            {"id": "st-1", "title": "A", "status": "in_progress", "depends_on": []},
            {"id": "st-2", "title": "B", "status": "in_progress", "depends_on": []},
            {"id": "st-3", "title": "C", "status": "pending", "depends_on": []},
        ],
    }
    (plans_dir / "s1.json").write_text(json.dumps(plan))
    state = isolated_sagtask.load_task_state(task_id)
    state["methodology_state"]["plan_file"] = ".sag_plans/s1.json"
    state["methodology_state"]["subtask_progress"] = {"total": 3, "completed": 0, "in_progress": 2}
    isolated_sagtask.save_task_state(task_id, state)

    result = sagtask._handle_sag_task_plan_update({
        "sag_task_id": task_id, "subtask_id": "st-1", "status": "failed",
    })
    assert result["ok"] is True

    state = isolated_sagtask.load_task_state(task_id)
    progress = state["methodology_state"]["subtask_progress"]
    assert progress["failed"] == 1
    assert progress["in_progress"] == 1
    assert progress["total"] == 3
```

Add `import json` at the top of the file if not already present.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_plan_update.py::test_plan_update_tracks_failed_count -v`
Expected: FAIL — KeyError: 'failed'

- [ ] **Step 3: Add failed count to subtask_progress sync**

In `src/sagtask/handlers/_plan.py`, find the progress sync block (around line 526-539) and add `failed`:

```python
    # Sync progress counts
    subtasks = plan["subtasks"]
    total = len(subtasks)
    completed = sum(1 for s in subtasks if s["status"] == "done")
    in_progress = sum(1 for s in subtasks if s["status"] == "in_progress")
    failed = sum(1 for s in subtasks if s["status"] == "failed")

    state = {
        **state,
        "methodology_state": {
            **ms,
            "subtask_progress": {
                "total": total,
                "completed": completed,
                "in_progress": in_progress,
                "failed": failed,
            },
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_plan_update.py::test_plan_update_tracks_failed_count -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest -x -q`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/sagtask/handlers/_plan.py tests/test_plan_update.py
git commit -m "feat: track failed subtask count in subtask_progress"
```

---

### Task 3: Implement `_InjectionCache` and `_compute_context_hash`

**Files:**
- Modify: `src/sagtask/plugin.py`
- Create: `tests/test_layered_injection.py`

- [ ] **Step 1: Write tests for context hash and cache**

Create `tests/test_layered_injection.py`:

```python
"""Tests for layered context injection."""
from __future__ import annotations

import json
import sagtask
from sagtask.plugin import SagTaskPlugin


class TestContextHash:
    def test_same_state_produces_same_hash(self, isolated_sagtask):
        state = {
            "status": "active",
            "current_phase_id": "p1",
            "current_step_id": "s1",
            "pending_gates": [],
            "artifacts_summary": "",
            "relationships": [],
            "methodology_state": {
                "current_methodology": "tdd",
                "tdd_phase": "red",
                "debug_phase": None,
                "brainstorm_phase": None,
                "subtask_progress": {"total": 5, "completed": 2, "in_progress": 2, "failed": 1},
                "last_verification": None,
            },
        }
        h1 = isolated_sagtask._compute_context_hash(state)
        h2 = isolated_sagtask._compute_context_hash(state)
        assert h1 == h2

    def test_different_state_produces_different_hash(self, isolated_sagtask):
        state1 = {
            "status": "active", "current_phase_id": "p1", "current_step_id": "s1",
            "pending_gates": [], "artifacts_summary": "", "relationships": [],
            "methodology_state": {"current_methodology": "tdd", "tdd_phase": "red",
                                  "debug_phase": None, "brainstorm_phase": None,
                                  "subtask_progress": {}, "last_verification": None},
        }
        state2 = {**state1, "current_step_id": "s2"}
        h1 = isolated_sagtask._compute_context_hash(state1)
        h2 = isolated_sagtask._compute_context_hash(state2)
        assert h1 != h2

    def test_relationship_count_affects_hash(self, isolated_sagtask):
        state1 = {
            "status": "active", "current_phase_id": "p1", "current_step_id": "s1",
            "pending_gates": [], "artifacts_summary": "", "relationships": [],
            "methodology_state": {"current_methodology": "none", "tdd_phase": None,
                                  "debug_phase": None, "brainstorm_phase": None,
                                  "subtask_progress": {}, "last_verification": None},
        }
        state2 = {**state1, "relationships": [{"sag_task_id": "other", "relationship": "cross-pollination"}]}
        h1 = isolated_sagtask._compute_context_hash(state1)
        h2 = isolated_sagtask._compute_context_hash(state2)
        assert h1 != h2


class TestInjectionCache:
    def test_cache_keyed_by_session_and_task(self, isolated_sagtask):
        cache = isolated_sagtask._get_injection_cache("sess1", "task-a")
        cache.context_hash = "abc"
        other = isolated_sagtask._get_injection_cache("sess1", "task-b")
        assert other.context_hash == ""

    def test_cache_persists_within_same_key(self, isolated_sagtask):
        cache = isolated_sagtask._get_injection_cache("sess1", "task-a")
        cache.context_hash = "abc"
        same = isolated_sagtask._get_injection_cache("sess1", "task-a")
        assert same.context_hash == "abc"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_layered_injection.py -v`
Expected: FAIL — AttributeError: '_compute_context_hash' / '_get_injection_cache'

- [ ] **Step 3: Implement _InjectionCache and _compute_context_hash**

In `src/sagtask/plugin.py`, add after imports (before class):

```python
from dataclasses import dataclass, field


@dataclass
class _InjectionCache:
    context_hash: str = ""
    artifacts_summary: str = ""
    step_id: str = ""
    metrics_summary_hash: str = ""
    methodology: str = ""
```

In `SagTaskPlugin.__init__`, add:

```python
        self._injection_cache: Dict[tuple, _InjectionCache] = {}
```

Add methods to `SagTaskPlugin`:

```python
    def _get_injection_cache(self, session_id: str, task_id: str) -> _InjectionCache:
        key = (session_id, task_id)
        if key not in self._injection_cache:
            self._injection_cache[key] = _InjectionCache()
        return self._injection_cache[key]

    def _compute_context_hash(self, state: Dict[str, Any]) -> str:
        import hashlib
        ms = state.get("methodology_state", {})
        payload = {
            "status": state.get("status", ""),
            "phase_id": state.get("current_phase_id", ""),
            "step_id": state.get("current_step_id", ""),
            "pending_gates": state.get("pending_gates", []),
            "artifacts_summary": state.get("artifacts_summary", ""),
            "methodology": ms.get("current_methodology", ""),
            "tdd_phase": ms.get("tdd_phase") or "",
            "debug_phase": ms.get("debug_phase") or "",
            "brainstorm_phase": ms.get("brainstorm_phase") or "",
            "subtask_progress": ms.get("subtask_progress", {}),
            "last_verification": ms.get("last_verification") or {},
            "relationship_count": len(state.get("relationships", [])),
        }
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(canonical.encode()).hexdigest()[:8]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_layered_injection.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sagtask/plugin.py tests/test_layered_injection.py
git commit -m "feat: add _InjectionCache and _compute_context_hash"
```

---

### Task 4: Implement `_build_layered_context` with L0-L3 layers

**Files:**
- Modify: `src/sagtask/plugin.py`
- Modify: `tests/test_layered_injection.py`

- [ ] **Step 1: Write tests for L0 anchor (always present)**

Append to `tests/test_layered_injection.py`:

```python
class TestLayeredContext:
    def _make_state(self, **overrides):
        base = {
            "sag_task_id": "test-task",
            "status": "active",
            "current_phase_id": "p1",
            "current_step_id": "s1",
            "pending_gates": [],
            "artifacts_summary": "",
            "relationships": [],
            "phases": [{"id": "p1", "name": "Phase 1", "steps": [{"id": "s1", "name": "Step 1"}]}],
            "methodology_state": {
                "current_methodology": "none",
                "tdd_phase": None,
                "debug_phase": None,
                "brainstorm_phase": None,
                "subtask_progress": {"total": 0, "completed": 0, "in_progress": 0, "failed": 0},
                "last_verification": None,
            },
        }
        base.update(overrides)
        return base

    def test_l0_anchor_always_present(self, isolated_sagtask):
        isolated_sagtask._active_task_id = "test-task"
        state = self._make_state()
        result = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        assert result.startswith("[SagTask]")
        assert "task=test-task" in result
        assert "status=active" in result
        assert "step=s1" in result

    def test_no_active_task_returns_empty(self, isolated_sagtask):
        isolated_sagtask._active_task_id = None
        result = isolated_sagtask._build_layered_context({}, user_message="", session_id="s1")
        assert result == ""

    def test_l1_pending_gate_every_turn(self, isolated_sagtask):
        isolated_sagtask._active_task_id = "test-task"
        state = self._make_state(pending_gates=["gate-review"])
        # First call
        r1 = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        assert "Gate: awaiting approval gate-review" in r1
        # Second call — same state, gate still shows
        r2 = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        assert "Gate: awaiting approval gate-review" in r2

    def test_l2_compact_with_methodology(self, isolated_sagtask):
        isolated_sagtask._active_task_id = "test-task"
        state = self._make_state()
        state["methodology_state"]["current_methodology"] = "tdd"
        state["methodology_state"]["tdd_phase"] = "red"
        state["methodology_state"]["subtask_progress"] = {"total": 8, "completed": 2, "in_progress": 1, "failed": 0}
        result = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        assert "TDD: RED" in result
        assert "2/8" in result

    def test_l2_expanded_with_failures(self, isolated_sagtask):
        isolated_sagtask._active_task_id = "test-task"
        state = self._make_state()
        state["methodology_state"]["current_methodology"] = "tdd"
        state["methodology_state"]["tdd_phase"] = "green"
        state["methodology_state"]["subtask_progress"] = {"total": 5, "completed": 2, "in_progress": 1, "failed": 1}
        result = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        assert "1 failed" in result

    def test_l3_blocking_verification(self, isolated_sagtask):
        isolated_sagtask._active_task_id = "test-task"
        state = self._make_state()
        state["phases"][0]["steps"][0]["verification"] = {"commands": ["pytest"], "must_pass": True}
        result = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        assert "must pass" in result.lower()

    def test_l3_failed_verification_every_turn(self, isolated_sagtask):
        isolated_sagtask._active_task_id = "test-task"
        state = self._make_state()
        state["phases"][0]["steps"][0]["verification"] = {"commands": ["pytest"], "must_pass": True}
        state["methodology_state"]["last_verification"] = {"passed": False, "output": "FAIL"}
        r1 = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        r2 = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        assert "Verify:" in r1 and "failed" in r1.lower()
        assert "Verify:" in r2 and "failed" in r2.lower()

    def test_minimal_output_no_methodology_no_verification(self, isolated_sagtask):
        isolated_sagtask._active_task_id = "test-task"
        state = self._make_state()
        # Call twice so context_hash_changed is False on second call
        isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        result = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        # Should be just L0 anchor
        lines = [l for l in result.strip().split("\n") if l.strip()]
        assert len(lines) == 1
        assert lines[0].startswith("[SagTask]")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_layered_injection.py::TestLayeredContext -v`
Expected: FAIL — AttributeError: '_build_layered_context'

- [ ] **Step 3: Implement `_build_layered_context` with L0-L3**

Add to `SagTaskPlugin` in `src/sagtask/plugin.py`:

```python
    _RELATED_INTENT_KEYWORDS = {"related", "reuse", "reference", "参考", "借鉴", "相关"}

    def _user_wants_related(self, query: str) -> bool:
        q_lower = query.lower()
        return any(kw in q_lower for kw in self._RELATED_INTENT_KEYWORDS)

    def _build_layered_context(
        self, state: Dict[str, Any], *, user_message: str = "", session_id: str = ""
    ) -> str:
        if not self._active_task_id:
            return ""

        task_id = self._active_task_id
        cache = self._get_injection_cache(session_id, task_id)
        current_hash = self._compute_context_hash(state)
        ms = state.get("methodology_state", {})
        step_id = state.get("current_step_id", "")
        methodology = ms.get("current_methodology", "none")

        # Change detection
        first_turn = cache.context_hash == ""
        context_hash_changed = current_hash != cache.context_hash
        step_just_switched = step_id != cache.step_id
        artifacts_summary_changed = state.get("artifacts_summary", "") != cache.artifacts_summary
        methodology_just_entered = methodology != cache.methodology and methodology in ("brainstorm", "debug")

        # Metrics change detection
        metrics_summary = self._build_metrics_summary(state)
        import hashlib
        metrics_hash = hashlib.md5(metrics_summary.encode()).hexdigest()[:8] if metrics_summary else ""
        metrics_changed = metrics_hash != cache.metrics_summary_hash

        # Update cache
        cache.context_hash = current_hash
        cache.step_id = step_id
        cache.artifacts_summary = state.get("artifacts_summary", "")
        cache.metrics_summary_hash = metrics_hash
        cache.methodology = methodology

        # Build layers
        lines = []

        # L0: Anchor (always)
        lines.append(
            f"[SagTask] task={task_id} status={state.get('status', 'unknown')} "
            f"phase={state.get('current_phase_id', '')} step={step_id}"
        )

        # L1: Navigation (on change or blocking)
        pending_gates = state.get("pending_gates", [])
        if context_hash_changed or first_turn:
            phase_name = self._get_current_phase(state)
            step_name = self._get_current_step(state)
            lines.append(f"- Phase: {phase_name} | Step: {step_name}")
        if pending_gates:
            for gate in pending_gates:
                lines.append(f"- Gate: awaiting approval {gate}")

        # L1.5: Artifacts (on change)
        if artifacts_summary_changed and state.get("artifacts_summary"):
            lines.append(f"- Artifacts: {state['artifacts_summary']}")

        # L2: Execution
        progress = ms.get("subtask_progress", {})
        plan_total = progress.get("total", 0)
        if methodology != "none" or plan_total > 0:
            completed = progress.get("completed", 0)
            in_prog = progress.get("in_progress", 0)
            failed = progress.get("failed", 0)

            if in_prog > 0 or failed > 0:
                # L2 Expanded
                meth_label = methodology
                phase_label = ""
                if methodology == "tdd" and ms.get("tdd_phase"):
                    phase_label = f" | TDD phase: {ms['tdd_phase'].upper()}"
                elif methodology == "debug" and ms.get("debug_phase"):
                    phase_label = f" | Debug phase: {ms['debug_phase']}"
                elif methodology == "brainstorm" and ms.get("brainstorm_phase"):
                    phase_label = f" | Brainstorm: {ms['brainstorm_phase']}"
                lines.append(f"- Methodology: {meth_label}{phase_label}")
                parts = [f"{completed}/{plan_total} done"]
                if in_prog > 0:
                    parts.append(f"{in_prog} active")
                if failed > 0:
                    parts.append(f"{failed} failed")
                lines.append(f"- Plan: {', '.join(parts)}")
            else:
                # L2 Compact
                phase_str = ""
                if methodology == "tdd" and ms.get("tdd_phase"):
                    phase_str = f"TDD: {ms['tdd_phase'].upper()}"
                elif methodology == "debug" and ms.get("debug_phase"):
                    phase_str = f"Debug: {ms['debug_phase']}"
                elif methodology == "brainstorm" and ms.get("brainstorm_phase"):
                    phase_str = f"Brainstorm: {ms['brainstorm_phase']}"
                elif methodology != "none":
                    phase_str = f"Methodology: {methodology}"
                plan_str = f"Plan: {completed}/{plan_total} done" if plan_total > 0 else ""
                compact_parts = [p for p in [phase_str, plan_str] if p]
                if compact_parts:
                    lines.append(f"- {' | '.join(compact_parts)}")

        # L3: Quality
        step_obj = self._get_current_step_object(state)
        if step_obj and step_obj.get("verification"):
            verification = step_obj["verification"]
            must_pass = verification.get("must_pass", False)
            last_v = ms.get("last_verification")

            if must_pass and (not last_v or not last_v.get("passed", False)):
                if not last_v:
                    lines.append("- Verify: pending, must pass before advance")
                else:
                    # Failed — include metrics if available
                    if metrics_summary:
                        lines.append(metrics_summary)
                    else:
                        lines.append("- Verify: failed, must pass before advance")
            elif metrics_changed and metrics_summary:
                lines.append(metrics_summary)

        # L4a: Related Hint
        relationships = state.get("relationships", [])
        cross_tasks = [r for r in relationships if r.get("relationship") == "cross-pollination"]
        if cross_tasks:
            lines.append(f"- Related: {len(cross_tasks)} task(s) available")

        # L4b: Related Details
        if cross_tasks and (step_just_switched or self._user_wants_related(user_message) or methodology_just_entered):
            lines.append("[Related]")
            for rel in cross_tasks[:2]:
                related_id = rel.get("sag_task_id")
                summaries = self._generate_artifact_summaries(related_id)
                if summaries:
                    for s in summaries[:2]:
                        lines.append(f"- {related_id}: {s.get('path', '')} - {s.get('summary', '')}")

        return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_layered_injection.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest -x -q`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/sagtask/plugin.py tests/test_layered_injection.py
git commit -m "feat: implement _build_layered_context with L0-L4 layers"
```

---

### Task 5: Wire `_build_layered_context` into `_on_pre_llm_call`

**Files:**
- Modify: `src/sagtask/hooks.py:44-49`
- Modify: `tests/test_layered_injection.py`

- [ ] **Step 1: Write a test exercising the full hook path**

Append to `tests/test_layered_injection.py`:

```python
class TestPreLlmCallHook:
    def test_hook_returns_layered_context(self, isolated_sagtask, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "hook-test",
            "name": "Hook Test",
            "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        isolated_sagtask._active_task_id = "hook-test"

        result = sagtask._on_pre_llm_call(
            session_id="sess1", user_message="do something",
            conversation_history=[], is_first_turn=True,
            model="test", platform="test", sender_id="test",
        )
        assert "context" in result
        assert "[SagTask]" in result["context"]
        assert "task=hook-test" in result["context"]

    def test_hook_no_active_task_returns_empty(self, isolated_sagtask):
        isolated_sagtask._active_task_id = None
        result = sagtask._on_pre_llm_call(
            session_id="sess1", user_message="hello",
            conversation_history=[], is_first_turn=False,
            model="test", platform="test", sender_id="test",
        )
        assert result == {}

    def test_hook_passes_user_message_for_intent(self, isolated_sagtask, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "intent-test",
            "name": "Intent Test",
            "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        isolated_sagtask._active_task_id = "intent-test"
        state = isolated_sagtask.load_task_state("intent-test")
        state["relationships"] = [{"sag_task_id": "other-task", "relationship": "cross-pollination"}]
        isolated_sagtask.save_task_state("intent-test", state)

        result = sagtask._on_pre_llm_call(
            session_id="sess1", user_message="参考一下相关任务",
            conversation_history=[], is_first_turn=False,
            model="test", platform="test", sender_id="test",
        )
        assert "[Related]" in result["context"]
```

- [ ] **Step 2: Run tests to verify they fail (or show old format)**

Run: `pytest tests/test_layered_injection.py::TestPreLlmCallHook -v`
Expected: FAIL — old `_build_task_context` doesn't return `[SagTask]` format

- [ ] **Step 3: Update hooks.py to call `_build_layered_context`**

In `src/sagtask/hooks.py`, replace the context building line:

```python
    context_text = p._build_layered_context(state, user_message=user_message, session_id=session_id)
    return {"context": context_text} if context_text else {}
```

The full `_on_pre_llm_call` function becomes:

```python
def _on_pre_llm_call(
    session_id: str,
    user_message: str,
    conversation_history: List[Any],
    is_first_turn: bool,
    model: str,
    platform: str,
    sender_id: str,
    **kwargs,
) -> Dict[str, Any]:
    """pre_llm_call hook — inject layered task context before each LLM call."""
    p = _get_provider()

    # Ensure projects root is initialized
    if p._projects_root is None:
        hermes_home = kwargs.get("hermes_home")
        if hermes_home:
            p._hermes_home = Path(hermes_home)
        else:
            p._hermes_home = Path.home() / ".hermes"
        p._projects_root = p._hermes_home / "sag_tasks"
        p._projects_root.mkdir(parents=True, exist_ok=True)
        p._restore_active_task()

    if not p._active_task_id:
        return {}

    state = p.load_task_state(p._active_task_id)
    if not state:
        return {}

    context_text = p._build_layered_context(state, user_message=user_message, session_id=session_id)
    return {"context": context_text} if context_text else {}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_layered_injection.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite and fix any broken tests**

Run: `pytest -x -q`

Some existing tests in `tests/test_context_injection.py` check for old format strings (e.g. `"## Active Task"`, `"Methodology: **tdd**"`). Update these tests to check for the new format:
- `"tdd"` in context → `"TDD:"` in context
- `"Verification"` in context → `"Verify:"` in context

- [ ] **Step 6: Commit**

```bash
git add src/sagtask/hooks.py tests/test_layered_injection.py tests/test_context_injection.py
git commit -m "feat: wire _build_layered_context into _on_pre_llm_call hook"
```

---

### Task 6: Update existing context injection tests

**Files:**
- Modify: `tests/test_context_injection.py`
- Modify: `tests/test_metrics.py`

- [ ] **Step 1: Update test_context_injection.py for new format**

The existing `TestContextInjection` tests call `_on_pre_llm_call` and assert on old format. Update assertions:

- `test_context_includes_methodology_type`: assert `"tdd"` appears in context (case-insensitive, will match `"TDD:"`)
- `test_context_includes_verification_status`: assert `"Verify:"` or `"verify"` in context
- `test_context_includes_tdd_phase`: assert `"RED"` in context (now uppercase)
- Any test checking `"## Active Task"` → check `"[SagTask]"` instead
- Any test checking `"Methodology: **tdd**"` → check `"TDD:"` or `"Methodology: tdd"` instead

- [ ] **Step 2: Update test_metrics.py context injection test**

In `tests/test_metrics.py::test_context_injection_includes_metrics`, the test calls `p._build_task_context(state)`. This method still exists for now but is no longer used by the hook. Update the test to call `p._build_layered_context(state, user_message="", session_id="")` instead, and adjust assertions:

- `"Verify:" in context` (was `"Verify:"`)
- `"2/3" in context` → may now appear as part of L3 metrics line
- `"88%" in context` → check coverage appears

- [ ] **Step 3: Run full test suite**

Run: `pytest -x -q`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_context_injection.py tests/test_metrics.py
git commit -m "test: update context injection tests for layered format"
```

---

### Task 7: Add layer-specific edge case tests

**Files:**
- Modify: `tests/test_layered_injection.py`

- [ ] **Step 1: Add tests for task switch, stable brainstorm, metrics change, L1.5 artifacts**

Append to `tests/test_layered_injection.py`:

```python
class TestLayerEdgeCases:
    def _make_state(self, task_id="test-task", **overrides):
        base = {
            "sag_task_id": task_id,
            "status": "active",
            "current_phase_id": "p1",
            "current_step_id": "s1",
            "pending_gates": [],
            "artifacts_summary": "",
            "relationships": [],
            "phases": [{"id": "p1", "name": "Phase 1", "steps": [{"id": "s1", "name": "Step 1"}]}],
            "methodology_state": {
                "current_methodology": "none",
                "tdd_phase": None,
                "debug_phase": None,
                "brainstorm_phase": None,
                "subtask_progress": {"total": 0, "completed": 0, "in_progress": 0, "failed": 0},
                "last_verification": None,
            },
        }
        base.update(overrides)
        return base

    def test_task_switch_triggers_full_expansion(self, isolated_sagtask):
        """Switching tasks resets cache, triggers L1 even with same step_id."""
        isolated_sagtask._active_task_id = "task-a"
        state_a = self._make_state(task_id="task-a")
        isolated_sagtask._build_layered_context(state_a, user_message="", session_id="s1")
        # Now switch
        isolated_sagtask._active_task_id = "task-b"
        state_b = self._make_state(task_id="task-b")
        result = isolated_sagtask._build_layered_context(state_b, user_message="", session_id="s1")
        assert "Phase:" in result  # L1 triggered

    def test_stable_brainstorm_no_l4b_repeat(self, isolated_sagtask):
        """After entering brainstorm, L4b should not repeat on subsequent turns."""
        isolated_sagtask._active_task_id = "test-task"
        state = self._make_state()
        state["methodology_state"]["current_methodology"] = "brainstorm"
        state["methodology_state"]["brainstorm_phase"] = "explore"
        state["relationships"] = [{"sag_task_id": "rel1", "relationship": "cross-pollination"}]

        # First call: methodology just entered → L4b
        r1 = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        # Second call: same methodology, no intent → no L4b
        r2 = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        assert "[Related]" in r1
        assert "[Related]" not in r2

    def test_l15_artifacts_on_change(self, isolated_sagtask):
        """Artifacts summary appears when it changes."""
        isolated_sagtask._active_task_id = "test-task"
        state = self._make_state(artifacts_summary="")
        isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        # Now change artifacts
        state["artifacts_summary"] = "added auth module"
        result = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        assert "Artifacts: added auth module" in result

    def test_cache_isolated_per_task(self, isolated_sagtask):
        """Cache for task-a doesn't affect task-b."""
        isolated_sagtask._active_task_id = "task-a"
        state_a = self._make_state(task_id="task-a", artifacts_summary="something")
        isolated_sagtask._build_layered_context(state_a, user_message="", session_id="s1")

        isolated_sagtask._active_task_id = "task-b"
        state_b = self._make_state(task_id="task-b", artifacts_summary="something")
        result = isolated_sagtask._build_layered_context(state_b, user_message="", session_id="s1")
        # For task-b it's the first time seeing this artifacts → should show it
        assert "Artifacts:" in result
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_layered_injection.py::TestLayerEdgeCases -v`
Expected: All PASS (implementation from Task 4 handles these cases)

- [ ] **Step 3: Commit**

```bash
git add tests/test_layered_injection.py
git commit -m "test: add edge case tests for layer selection logic"
```

---

### Task 8: Remove old `_build_task_context` (if no longer referenced)

**Files:**
- Modify: `src/sagtask/plugin.py`

- [ ] **Step 1: Check if `_build_task_context` is still referenced**

Run: `grep -rn "_build_task_context" src/ tests/`

If the only references are:
- Definition in `plugin.py`
- The `on_pre_compress` method (which builds a different, shorter string)

Then remove `_build_task_context` entirely. If `on_pre_compress` or other code still calls it, keep it but note it's only for the compress path.

- [ ] **Step 2: Remove or keep based on findings**

If removing: delete the method and its docstring. If it's used by `on_pre_compress`, leave it (it serves a different purpose there).

Check: the `on_pre_compress` method at line 600 builds its own inline context — it does NOT call `_build_task_context`. So `_build_task_context` can be removed.

- [ ] **Step 3: Run full test suite**

Run: `pytest -x -q`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add src/sagtask/plugin.py
git commit -m "refactor: remove unused _build_task_context method"
```

---

### Task 9: Final validation

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite with coverage**

Run: `pytest --cov=src/sagtask --cov-report=term-missing -q`
Expected: All pass, coverage ≥ 80%.

- [ ] **Step 2: Verify no dead imports**

Run: `grep -n "import threading" src/sagtask/plugin.py`

If `threading` is no longer used (after removing `_prefetch_lock`), remove the import.

- [ ] **Step 3: Commit any cleanup**

```bash
git add -A
git commit -m "chore: remove unused threading import"
```
