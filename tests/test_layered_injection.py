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
        r1 = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        assert "Gate: awaiting approval gate-review" in r1
        r2 = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        assert "Gate: awaiting approval gate-review" in r2

    def test_l2_compact_with_methodology(self, isolated_sagtask):
        isolated_sagtask._active_task_id = "test-task"
        state = self._make_state()
        state["methodology_state"]["current_methodology"] = "tdd"
        state["methodology_state"]["tdd_phase"] = "red"
        state["methodology_state"]["subtask_progress"] = {"total": 8, "completed": 2, "in_progress": 0, "failed": 0}
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
        assert "Verify:" in r1 or "verify" in r1.lower()
        assert "Verify:" in r2 or "verify" in r2.lower()

    def test_minimal_output_no_methodology_no_verification(self, isolated_sagtask):
        isolated_sagtask._active_task_id = "test-task"
        state = self._make_state()
        # First call triggers L1, second call should be minimal
        isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        result = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        lines = [l for l in result.strip().split("\n") if l.strip()]
        assert len(lines) == 1
        assert lines[0].startswith("[SagTask]")


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
        # Second call for task-a — should be minimal
        r_stable = isolated_sagtask._build_layered_context(state_a, user_message="", session_id="s1")
        assert "Phase:" not in r_stable
        # Now switch to task-b
        isolated_sagtask._active_task_id = "task-b"
        state_b = self._make_state(task_id="task-b")
        result = isolated_sagtask._build_layered_context(state_b, user_message="", session_id="s1")
        assert "Phase:" in result  # L1 triggered for new task

    def test_stable_brainstorm_no_l4b_repeat(self, isolated_sagtask):
        """After entering brainstorm, L4b should not repeat on subsequent turns."""
        isolated_sagtask._active_task_id = "test-task"
        state = self._make_state()
        state["methodology_state"]["current_methodology"] = "brainstorm"
        state["methodology_state"]["brainstorm_phase"] = "explore"
        state["relationships"] = [{"sag_task_id": "rel1", "relationship": "cross-pollination"}]

        # First call: methodology just entered → but cache.methodology starts as "", so
        # methodology_just_entered fires only when cache.methodology != ""
        # We need to prime the cache first with methodology="none"
        state_before = self._make_state()
        state_before["relationships"] = [{"sag_task_id": "rel1", "relationship": "cross-pollination"}]
        isolated_sagtask._build_layered_context(state_before, user_message="", session_id="s1")

        # Now switch to brainstorm — methodology_just_entered should fire
        r1 = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        # Second call: same methodology, no intent → no L4b
        r2 = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        assert "[Related]" in r1
        assert "[Related]" not in r2

    def test_l15_artifacts_on_change(self, isolated_sagtask):
        """Artifacts summary appears when it changes from one value to another."""
        isolated_sagtask._active_task_id = "test-task"
        state = self._make_state(artifacts_summary="initial stuff")
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
        # For task-b it's the first time — artifacts should show
        assert "Artifacts:" in result

    def test_user_intent_triggers_l4b(self, isolated_sagtask):
        """User message with related keywords triggers L4b."""
        isolated_sagtask._active_task_id = "test-task"
        state = self._make_state()
        state["relationships"] = [{"sag_task_id": "other", "relationship": "cross-pollination"}]
        # First call primes cache
        isolated_sagtask._build_layered_context(state, user_message="hello", session_id="s1")
        # Second call with intent keyword
        result = isolated_sagtask._build_layered_context(state, user_message="参考相关任务", session_id="s1")
        assert "[Related]" in result

    def test_l4a_hint_present_when_relationships_exist(self, isolated_sagtask):
        """L4a hint shows count of related tasks."""
        isolated_sagtask._active_task_id = "test-task"
        state = self._make_state()
        state["relationships"] = [
            {"sag_task_id": "t1", "relationship": "cross-pollination"},
            {"sag_task_id": "t2", "relationship": "cross-pollination"},
        ]
        result = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        assert "2 task(s) available" in result


class TestReviewRegressions:
    """Regression tests for issues found during code review."""

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

    def test_dispatch_after_failure_preserves_failed_count(self, isolated_sagtask, mock_git):
        """Dispatching a subtask after another failed must not erase the failed count."""
        task_id = "test-dispatch-fail"
        sagtask._handle_sag_task_create({
            "sag_task_id": task_id,
            "name": "Dispatch Fail",
            "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1", "methodology": {"type": "tdd"}}]}],
        })
        sagtask._handle_sag_task_plan({"sag_task_id": task_id})

        plan_path = isolated_sagtask.get_task_root(task_id) / ".sag_plans" / "s1.json"
        plan = json.loads(plan_path.read_text())
        subtask_ids = [s["id"] for s in plan["subtasks"]]

        # Mark first subtask as failed
        sagtask._handle_sag_task_plan_update({"sag_task_id": task_id, "subtask_id": subtask_ids[0], "status": "failed"})
        state = isolated_sagtask.load_task_state(task_id)
        assert state["methodology_state"]["subtask_progress"]["failed"] == 1

        # Dispatch second subtask — failed count must survive
        sagtask._handle_sag_task_dispatch({"sag_task_id": task_id, "subtask_id": subtask_ids[1]})
        state = isolated_sagtask.load_task_state(task_id)
        assert state["methodology_state"]["subtask_progress"]["failed"] == 1

        # Context should still show "1 failed"
        isolated_sagtask._active_task_id = task_id
        result = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        assert "1 failed" in result

    def test_passed_verification_metrics_on_first_turn(self, isolated_sagtask):
        """First context build with passed verification + metrics must show Verify: line."""
        import json as _json
        task_id = "test-verify-pass"
        task_root = isolated_sagtask._projects_root / task_id
        task_root.mkdir()

        events = [
            {"ts": "2026-05-12T10:00:00Z", "event": "verify_run", "step_id": "s1", "phase_id": "p1", "command": "pytest", "exit_code": 0, "passed": True},
            {"ts": "2026-05-12T10:01:00Z", "event": "verify_run", "step_id": "s1", "phase_id": "p1", "command": "pytest", "exit_code": 0, "passed": True},
        ]
        (task_root / ".sag_metrics.jsonl").write_text("\n".join(_json.dumps(e) for e in events) + "\n")

        state = self._make_state(task_id=task_id)
        state["phases"][0]["steps"][0]["verification"] = {"commands": ["pytest"], "must_pass": True}
        state["methodology_state"]["last_verification"] = {"passed": True}

        isolated_sagtask._active_task_id = task_id
        result = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        assert "Verify:" in result

    def test_l4b_on_first_turn_with_relationships(self, isolated_sagtask):
        """First turn for a task with relationships should emit [Related] details."""
        isolated_sagtask._active_task_id = "test-task"
        state = self._make_state()
        state["relationships"] = [{"sag_task_id": "other-task", "relationship": "cross-pollination"}]
        result = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        assert "[Related]" in result

    def test_task_switch_with_relationships_shows_related(self, isolated_sagtask):
        """Switching tasks should show [Related] for the new task."""
        # Prime cache for task-a
        isolated_sagtask._active_task_id = "task-a"
        state_a = self._make_state(task_id="task-a")
        isolated_sagtask._build_layered_context(state_a, user_message="", session_id="s1")

        # Switch to task-b which has relationships
        isolated_sagtask._active_task_id = "task-b"
        state_b = self._make_state(task_id="task-b")
        state_b["relationships"] = [{"sag_task_id": "related-task", "relationship": "cross-pollination"}]
        result = isolated_sagtask._build_layered_context(state_b, user_message="", session_id="s1")
        assert "[Related]" in result

    def test_relationship_identity_change_affects_hash(self, isolated_sagtask):
        """Replacing one related task with another (same count) should change hash."""
        state1 = self._make_state()
        state1["relationships"] = [{"sag_task_id": "task-a", "relationship": "cross-pollination"}]
        state2 = self._make_state()
        state2["relationships"] = [{"sag_task_id": "task-b", "relationship": "cross-pollination"}]
        h1 = isolated_sagtask._compute_context_hash(state1)
        h2 = isolated_sagtask._compute_context_hash(state2)
        assert h1 != h2

    def test_metrics_appear_after_cache_primed_empty(self, isolated_sagtask):
        """Metrics should show when they appear after cache was primed with no metrics."""
        import json as _json
        task_id = "test-metrics-appear"
        task_root = isolated_sagtask._projects_root / task_id
        task_root.mkdir()

        state = self._make_state(task_id=task_id)
        state["phases"][0]["steps"][0]["verification"] = {"commands": ["pytest"], "must_pass": True}
        state["methodology_state"]["last_verification"] = {"passed": True}
        isolated_sagtask._active_task_id = task_id

        # First call: no metrics file yet → cache primed with empty metrics_summary_hash
        r1 = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        assert "Verify:" not in r1

        # Now metrics appear (as if verify just ran)
        events = [
            {"ts": "2026-05-12T10:00:00Z", "event": "verify_run", "step_id": "s1", "phase_id": "p1", "command": "pytest", "exit_code": 0, "passed": True},
        ]
        (task_root / ".sag_metrics.jsonl").write_text("\n".join(_json.dumps(e) for e in events) + "\n")

        # Second call: metrics now exist → must show Verify: line
        r2 = isolated_sagtask._build_layered_context(state, user_message="", session_id="s1")
        assert "Verify:" in r2
