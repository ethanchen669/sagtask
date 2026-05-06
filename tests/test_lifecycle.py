"""Integration tests for full task lifecycle."""
import json
import pytest
from sagtask import (
    _handle_sag_task_create,
    _handle_sag_task_status,
    _handle_sag_task_advance,
    _handle_sag_task_pause,
    _handle_sag_task_resume,
    _handle_sag_task_approve,
    _handle_sag_task_list,
    _get_provider,
)


class TestTaskCreate:
    def test_create_sets_active_task(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "create-test",
            "name": "Create Test",
            "phases": sample_phases,
        })
        p = _get_provider()
        assert p._active_task_id == "create-test"
        marker = p._projects_root / ".active_task"
        assert marker.read_text().strip() == "create-test"

    def test_create_writes_state_file(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "state-test",
            "name": "State Test",
            "phases": sample_phases,
        })
        p = _get_provider()
        state = json.loads(p.get_task_state_path("state-test").read_text())
        assert state["current_phase_id"] == "phase-1"
        assert state["current_step_id"] == "step-1"
        assert state["status"] == "active"

    def test_create_rejects_invalid_id(self, isolated_sagtask, mock_git, sample_phases):
        result = _handle_sag_task_create({
            "sag_task_id": "../../etc",
            "name": "Bad ID",
            "phases": sample_phases,
        })
        assert result["ok"] is False
        assert "Invalid" in result["error"]


class TestTaskAdvance:
    def test_advance_to_next_step(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "adv-test",
            "name": "Advance Test",
            "phases": sample_phases,
        })
        result = _handle_sag_task_advance({"sag_task_id": "adv-test"})
        assert result["ok"] is True
        assert result["current_phase"] == "phase-1"
        assert result["current_step"] == "step-2"

    def test_advance_to_next_phase(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "adv-phase",
            "name": "Phase Test",
            "phases": sample_phases,
        })
        _handle_sag_task_advance({"sag_task_id": "adv-phase"})
        result = _handle_sag_task_advance({"sag_task_id": "adv-phase"})
        assert result["current_phase"] == "phase-2"
        assert result["current_step"] == "step-3"

    def test_advance_completes_task(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "adv-done",
            "name": "Complete Test",
            "phases": sample_phases,
        })
        _handle_sag_task_advance({"sag_task_id": "adv-done"})
        _handle_sag_task_advance({"sag_task_id": "adv-done"})
        result = _handle_sag_task_advance({"sag_task_id": "adv-done"})
        assert result["status"] == "completed"


class TestTaskPauseResume:
    def test_pause_and_resume(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "pr-test",
            "name": "Pause Resume",
            "phases": sample_phases,
        })
        pause = _handle_sag_task_pause({"sag_task_id": "pr-test", "reason": "waiting"})
        assert pause["ok"] is True
        assert pause["status"] == "paused"

        p = _get_provider()
        assert p.load_task_state("pr-test")["status"] == "paused"

        resume = _handle_sag_task_resume({"sag_task_id": "pr-test"})
        assert resume["ok"] is True
        assert resume["status"] == "active"


class TestTaskApprove:
    def test_approve_gate_advances(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "gate-test",
            "name": "Gate Test",
            "phases": sample_phases,
        })
        p = _get_provider()
        state = p.load_task_state("gate-test")
        state["pending_gates"] = ["gate-1"]
        p.save_task_state("gate-test", state)

        result = _handle_sag_task_approve({
            "sag_task_id": "gate-test",
            "gate_id": "gate-1",
            "decision": "Approve",
            "comment": "Looks good",
        })
        assert result["ok"] is True
        assert result["current_step"] == "step-2"


class TestTaskList:
    def test_list_tasks(self, isolated_sagtask, mock_git, sample_phases):
        _handle_sag_task_create({
            "sag_task_id": "list-a",
            "name": "List A",
            "phases": sample_phases,
        })
        _handle_sag_task_create({
            "sag_task_id": "list-b",
            "name": "List B",
            "phases": sample_phases,
        })
        result = _handle_sag_task_list({"status_filter": "all"})
        assert result["ok"] is True
        assert len(result["tasks"]) == 2
