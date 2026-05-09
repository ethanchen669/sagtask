"""Tests for sag_task_plan_update tool."""
import json
import pytest
import sagtask


class TestPlanUpdate:
    def _create_task_and_generate_plan(self, plugin, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-planupd",
            "name": "Test Plan Update",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [{
                    "id": "step-1",
                    "name": "Build Parser",
                    "description": "Build a JSON parser",
                    "methodology": {"type": "tdd"},
                }],
            }],
        })
        sagtask._handle_sag_task_plan({"sag_task_id": "test-planupd"})

    def _get_plan(self, plugin, task_id="test-planupd"):
        plan_path = plugin.get_task_root(task_id) / ".sag_plans" / "step-1.json"
        return json.loads(plan_path.read_text())

    def test_mark_subtask_done(self, isolated_sagtask, mock_git):
        """Should update subtask status to done and sync progress."""
        self._create_task_and_generate_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        first_id = plan["subtasks"][0]["id"]
        result = sagtask._handle_sag_task_plan_update({
            "sag_task_id": "test-planupd",
            "subtask_id": first_id,
            "status": "done",
        })
        assert result["ok"] is True
        state = isolated_sagtask.load_task_state("test-planupd")
        assert state["methodology_state"]["subtask_progress"]["completed"] == 1

    def test_mark_subtask_in_progress(self, isolated_sagtask, mock_git):
        """Should update subtask status to in_progress."""
        self._create_task_and_generate_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        first_id = plan["subtasks"][0]["id"]
        result = sagtask._handle_sag_task_plan_update({
            "sag_task_id": "test-planupd",
            "subtask_id": first_id,
            "status": "in_progress",
        })
        assert result["ok"] is True
        state = isolated_sagtask.load_task_state("test-planupd")
        assert state["methodology_state"]["subtask_progress"]["in_progress"] == 1

    def test_progress_counts_sync_correctly(self, isolated_sagtask, mock_git):
        """Completing multiple subtasks should update progress counts correctly."""
        self._create_task_and_generate_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        for st in plan["subtasks"][:2]:
            sagtask._handle_sag_task_plan_update({
                "sag_task_id": "test-planupd",
                "subtask_id": st["id"],
                "status": "done",
            })
        state = isolated_sagtask.load_task_state("test-planupd")
        ms = state["methodology_state"]
        assert ms["subtask_progress"]["completed"] == 2
        assert ms["subtask_progress"]["total"] == len(plan["subtasks"])

    def test_mark_invalid_subtask_id(self, isolated_sagtask, mock_git):
        """Should return error for non-existent subtask_id."""
        self._create_task_and_generate_plan(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_plan_update({
            "sag_task_id": "test-planupd",
            "subtask_id": "st-999",
            "status": "done",
        })
        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    def test_mark_invalid_status(self, isolated_sagtask, mock_git):
        """Should return error for invalid status value."""
        self._create_task_and_generate_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        result = sagtask._handle_sag_task_plan_update({
            "sag_task_id": "test-planupd",
            "subtask_id": plan["subtasks"][0]["id"],
            "status": "invalid",
        })
        assert result["ok"] is False

    def test_update_without_plan_returns_error(self, isolated_sagtask, mock_git):
        """Should return error when no plan exists for current step."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-noplan",
            "name": "No Plan",
            "phases": [{"id": "phase-1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        result = sagtask._handle_sag_task_plan_update({
            "sag_task_id": "test-noplan",
            "subtask_id": "st-1",
            "status": "done",
        })
        assert result["ok"] is False
        assert "no plan" in result["error"].lower() or "not found" in result["error"].lower()

    def test_done_with_note_records_context(self, isolated_sagtask, mock_git):
        """Marking done with context should update the subtask's context field."""
        self._create_task_and_generate_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        first_id = plan["subtasks"][0]["id"]
        sagtask._handle_sag_task_plan_update({
            "sag_task_id": "test-planupd",
            "subtask_id": first_id,
            "status": "done",
            "context": "Completed with 3 test cases covering edge cases.",
        })
        updated_plan = self._get_plan(isolated_sagtask)
        updated_st = next(s for s in updated_plan["subtasks"] if s["id"] == first_id)
        assert "3 test cases" in updated_st["context"]
