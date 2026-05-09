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
