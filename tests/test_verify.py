"""Tests for sag_task_verify tool."""
import subprocess
from unittest.mock import MagicMock
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
        mock_git.return_value = MagicMock(returncode=0, stdout="2 passed", stderr="")
        result = sagtask._handle_sag_task_verify({"sag_task_id": "test-verify"})
        assert result["ok"] is True
        assert result["passed"] is True
        # Verify subprocess was called correctly
        call_kwargs = mock_git.call_args
        assert call_kwargs[1].get("shell") is True or call_kwargs.kwargs.get("shell") is True
        state = isolated_sagtask.load_task_state("test-verify")
        verification = state["methodology_state"]["last_verification"]
        assert verification["passed"] is True
        assert len(verification["results"]) == 1
        assert verification["results"][0]["exit_code"] == 0

    def test_verify_failing_command(self, isolated_sagtask, mock_git):
        """Verify with a failing command should record failure."""
        self._create_task_with_verification(isolated_sagtask, mock_git)
        mock_git.return_value = MagicMock(returncode=1, stdout="", stderr="1 failed")
        result = sagtask._handle_sag_task_verify({"sag_task_id": "test-verify"})
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
        result = sagtask._handle_sag_task_verify({"sag_task_id": "test-no-verify"})
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
        mock_git.side_effect = [
            MagicMock(returncode=0, stdout="passed", stderr=""),
            MagicMock(returncode=1, stdout="", stderr="type error"),
        ]
        result = sagtask._handle_sag_task_verify({"sag_task_id": "test-multi-verify"})
        assert result["ok"] is True
        assert result["passed"] is False
        state = isolated_sagtask.load_task_state("test-multi-verify")
        assert len(state["methodology_state"]["last_verification"]["results"]) == 2

    def test_verify_timeout(self, isolated_sagtask, mock_git):
        """Verify handles timeout gracefully."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-timeout-verify",
            "name": "Timeout Verify",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [{
                    "id": "step-1",
                    "name": "Step 1",
                    "verification": {"commands": ["sleep 999"], "must_pass": True},
                }],
            }],
        })
        mock_git.side_effect = sagtask.subprocess.TimeoutExpired(cmd="sleep 999", timeout=30)
        result = sagtask._handle_sag_task_verify({"sag_task_id": "test-timeout-verify"})
        assert result["ok"] is True
        assert result["passed"] is False
        state = isolated_sagtask.load_task_state("test-timeout-verify")
        assert state["methodology_state"]["last_verification"]["results"][0]["exit_code"] == -1

    def test_verify_no_active_task(self, isolated_sagtask, mock_git):
        """Verify returns error when no active task and no task_id given."""
        isolated_sagtask._active_task_id = None
        result = sagtask._handle_sag_task_verify({})
        assert result["ok"] is False
        assert "No active task" in result["error"]

    def test_verify_task_not_found(self, isolated_sagtask, mock_git):
        """Verify returns error when task doesn't exist."""
        result = sagtask._handle_sag_task_verify({"sag_task_id": "nonexistent"})
        assert result["ok"] is False
        assert "not found" in result["error"]
