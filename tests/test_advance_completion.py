"""Tests for _handle_sag_task_advance — edge cases and completion path."""
from unittest.mock import MagicMock
import sagtask


class TestAdvanceEdgeCases:
    def test_advance_no_active_task(self, isolated_sagtask):
        isolated_sagtask._active_task_id = None
        result = sagtask._handle_sag_task_advance({})
        assert result["ok"] is False
        assert "No active task" in result["error"]

    def test_advance_task_not_found(self, isolated_sagtask):
        isolated_sagtask._active_task_id = "nonexistent"
        result = sagtask._handle_sag_task_advance({"sag_task_id": "nonexistent"})
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_advance_phase_not_found(self, isolated_sagtask, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-bad-phase",
            "name": "Bad Phase",
            "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        state = isolated_sagtask.load_task_state("test-bad-phase")
        state["current_phase_id"] = "nonexistent-phase"
        isolated_sagtask.save_task_state("test-bad-phase", state)
        result = sagtask._handle_sag_task_advance({"sag_task_id": "test-bad-phase"})
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_advance_to_completion(self, isolated_sagtask, mock_git):
        """Advance through all phases to hit the completion path."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-complete",
            "name": "Complete Test",
            "phases": [
                {"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]},
                {"id": "p2", "name": "P2", "steps": [{"id": "s2", "name": "S2"}]},
            ],
        })
        # Advance past p1/s1 → p2/s2
        result = sagtask._handle_sag_task_advance({"sag_task_id": "test-complete"})
        assert result["ok"] is True
        assert result["current_phase"] == "p2"
        assert result["current_step"] == "s2"

        # Advance past p2/s2 → completed
        result = sagtask._handle_sag_task_advance({"sag_task_id": "test-complete"})
        assert result["ok"] is True
        assert result["status"] == "completed"

    def test_advance_with_artifacts_summary(self, isolated_sagtask, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-artifacts",
            "name": "Artifacts Test",
            "phases": [
                {"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]},
                {"id": "p2", "name": "P2", "steps": [{"id": "s2", "name": "S2"}]},
            ],
        })
        result = sagtask._handle_sag_task_advance({
            "sag_task_id": "test-artifacts",
            "artifacts_summary": "output.md: generated",
        })
        assert result["ok"] is True
        state = isolated_sagtask.load_task_state("test-artifacts")
        assert state["artifacts_summary"] == "output.md: generated"

    def test_advance_with_commit_message(self, isolated_sagtask, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-commit-msg",
            "name": "Commit Msg",
            "phases": [
                {"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]},
                {"id": "p2", "name": "P2", "steps": [{"id": "s2", "name": "S2"}]},
            ],
        })
        result = sagtask._handle_sag_task_advance({
            "sag_task_id": "test-commit-msg",
            "commit_message": "Custom commit message",
        })
        assert result["ok"] is True

    def test_advance_multi_step_phase(self, isolated_sagtask, mock_git):
        """Advance within a phase that has multiple steps."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-multi-step",
            "name": "Multi Step",
            "phases": [
                {"id": "p1", "name": "P1", "steps": [
                    {"id": "s1", "name": "S1"},
                    {"id": "s2", "name": "S2"},
                ]},
            ],
        })
        result = sagtask._handle_sag_task_advance({"sag_task_id": "test-multi-step"})
        assert result["ok"] is True
        assert result["current_step"] == "s2"
        assert result["current_phase"] == "p1"


class TestStatusVerbose:
    def test_verbose_status(self, isolated_sagtask, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-verbose",
            "name": "Verbose Test",
            "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        mock_git.return_value = MagicMock(returncode=0, stdout="abc1234 commit\n", stderr="")
        result = sagtask._handle_sag_task_status({
            "sag_task_id": "test-verbose",
            "verbose": True,
        })
        assert result["ok"] is True
        assert "phases" in result
        assert "decisions" in result
        assert "git_log" in result
        assert "paused_executions" in result

    def test_status_no_task(self, isolated_sagtask):
        isolated_sagtask._active_task_id = None
        result = sagtask._handle_sag_task_status({})
        assert result["ok"] is False
        assert "No active" in result["error"]

    def test_status_task_not_found(self, isolated_sagtask):
        result = sagtask._handle_sag_task_status({"sag_task_id": "nonexistent"})
        assert result["ok"] is False
