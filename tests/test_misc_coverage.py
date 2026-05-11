"""Tests for misc uncovered code paths — approve, get_provider, system_prompt_block."""
import pytest
from unittest.mock import MagicMock

import sagtask


class TestGetProvider:
    def test_raises_when_not_registered(self):
        sagtask._utils._sagtask_instance = None
        with pytest.raises(RuntimeError, match="not registered"):
            sagtask._get_provider()


class TestApproveHandler:
    def test_no_active_task(self, isolated_sagtask):
        isolated_sagtask._active_task_id = None
        result = sagtask._handle_sag_task_approve({})
        assert result["ok"] is False
        assert "No active task" in result["error"]

    def test_no_gate_id(self, isolated_sagtask, mock_git):
        isolated_sagtask._active_task_id = "test"
        result = sagtask._handle_sag_task_approve({"decision": "approve"})
        assert result["ok"] is False
        assert "gate_id" in result["error"]

    def test_no_decision(self, isolated_sagtask, mock_git):
        isolated_sagtask._active_task_id = "test"
        result = sagtask._handle_sag_task_approve({"gate_id": "g1"})
        assert result["ok"] is False
        assert "decision" in result["error"]

    def test_task_not_found(self, isolated_sagtask, mock_git):
        result = sagtask._handle_sag_task_approve({
            "sag_task_id": "nonexistent",
            "gate_id": "g1",
            "decision": "approve",
        })
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_approve_success(self, isolated_sagtask, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-approve",
            "name": "Approve Test",
            "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        result = sagtask._handle_sag_task_approve({
            "sag_task_id": "test-approve",
            "gate_id": "g1",
            "decision": "approve",
            "comment": "Looks good",
        })
        assert result["ok"] is True
        state = isolated_sagtask.load_task_state("test-approve")
        assert len(state["decisions"]) == 1
        assert state["decisions"][0]["gate_id"] == "g1"


class TestSystemPromptBlock:
    def test_no_active_task(self, isolated_sagtask):
        isolated_sagtask._active_task_id = None
        result = isolated_sagtask.system_prompt_block()
        assert result == ""

    def test_active_task(self, isolated_sagtask, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-prompt",
            "name": "Prompt Test",
            "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        isolated_sagtask._active_task_id = "test-prompt"
        result = isolated_sagtask.system_prompt_block()
        assert "test-prompt" in result
        assert "SagTask" in result

    def test_active_task_not_found(self, isolated_sagtask):
        isolated_sagtask._active_task_id = "nonexistent"
        result = isolated_sagtask.system_prompt_block()
        assert result == ""


class TestPreLlmCallEdgeCases:
    def test_no_active_task(self, isolated_sagtask):
        isolated_sagtask._active_task_id = None
        result = sagtask._on_pre_llm_call(
            session_id="s1", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert result == {}

    def test_active_task_not_found(self, isolated_sagtask):
        isolated_sagtask._active_task_id = "nonexistent"
        result = sagtask._on_pre_llm_call(
            session_id="s1", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert result == {}

    def test_task_with_pending_gates(self, isolated_sagtask, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-gates",
            "name": "Gates Test",
            "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        state = isolated_sagtask.load_task_state("test-gates")
        state["pending_gates"] = ["gate-1", "gate-2"]
        isolated_sagtask.save_task_state("test-gates", state)
        isolated_sagtask._active_task_id = "test-gates"
        result = sagtask._on_pre_llm_call(
            session_id="s1", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert "gate-1" in result["context"]
        assert "gate-2" in result["context"]

    def test_task_with_artifacts(self, isolated_sagtask, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-art",
            "name": "Art Test",
            "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        state = isolated_sagtask.load_task_state("test-art")
        state["artifacts_summary"] = "output.md: generated"
        isolated_sagtask.save_task_state("test-art", state)
        isolated_sagtask._active_task_id = "test-art"
        result = sagtask._on_pre_llm_call(
            session_id="s1", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert "output.md" in result["context"]

    def test_task_with_plan_progress(self, isolated_sagtask, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-progress",
            "name": "Progress Test",
            "phases": [{
                "id": "p1", "name": "P1",
                "steps": [{"id": "s1", "name": "S1", "methodology": {"type": "tdd"}}],
            }],
        })
        state = isolated_sagtask.load_task_state("test-progress")
        state["methodology_state"]["subtask_progress"] = {"total": 5, "completed": 3, "in_progress": 1}
        isolated_sagtask.save_task_state("test-progress", state)
        isolated_sagtask._active_task_id = "test-progress"
        result = sagtask._on_pre_llm_call(
            session_id="s1", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert "3/5" in result["context"]


class TestPauseResumeEdgeCases:
    def test_pause_no_active_task(self, isolated_sagtask):
        isolated_sagtask._active_task_id = None
        result = sagtask._handle_sag_task_pause({})
        assert result["ok"] is False

    def test_pause_task_not_found(self, isolated_sagtask):
        result = sagtask._handle_sag_task_pause({"sag_task_id": "nonexistent"})
        assert result["ok"] is False

    def test_resume_no_active_task(self, isolated_sagtask):
        isolated_sagtask._active_task_id = None
        result = sagtask._handle_sag_task_resume({})
        assert result["ok"] is False

    def test_resume_task_not_found(self, isolated_sagtask):
        result = sagtask._handle_sag_task_resume({"sag_task_id": "nonexistent"})
        assert result["ok"] is False

    def test_pause_and_resume(self, isolated_sagtask, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-pause-resume",
            "name": "Pause Resume",
            "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        pause_result = sagtask._handle_sag_task_pause({
            "sag_task_id": "test-pause-resume",
            "reason": "testing",
        })
        assert pause_result["ok"] is True
        execution_id = pause_result["execution_id"]

        resume_result = sagtask._handle_sag_task_resume({
            "sag_task_id": "test-pause-resume",
            "execution_id": execution_id,
        })
        assert resume_result["ok"] is True
