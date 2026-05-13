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
