"""Tests for sag_task_dispatch tool."""
import json
import pytest
import sagtask


class TestDispatch:
    def _create_task_with_plan(self, plugin, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-dispatch",
            "name": "Test Dispatch",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [{
                    "id": "step-1",
                    "name": "Build Parser",
                    "description": "Build a JSON parser with error recovery",
                    "methodology": {"type": "tdd", "config": {"coverage_threshold": 80}},
                    "verification": {"commands": ["pytest"], "must_pass": True},
                }],
            }],
        })
        sagtask._handle_sag_task_plan({"sag_task_id": "test-dispatch"})

    def _get_plan(self, plugin, task_id="test-dispatch"):
        plan_path = plugin.get_task_root(task_id) / ".sag_plans" / "step-1.json"
        return json.loads(plan_path.read_text())

    def test_dispatch_returns_context(self, isolated_sagtask, mock_git):
        self._create_task_with_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        subtask_id = plan["subtasks"][0]["id"]
        result = sagtask._handle_sag_task_dispatch({
            "sag_task_id": "test-dispatch",
            "subtask_id": subtask_id,
        })
        assert result["ok"] is True
        assert "context" in result
        assert "subtask_id" in result
        assert result["subtask_id"] == subtask_id

    def test_dispatch_marks_in_progress(self, isolated_sagtask, mock_git):
        self._create_task_with_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        subtask_id = plan["subtasks"][0]["id"]
        sagtask._handle_sag_task_dispatch({
            "sag_task_id": "test-dispatch",
            "subtask_id": subtask_id,
        })
        updated_plan = self._get_plan(isolated_sagtask)
        st = next(s for s in updated_plan["subtasks"] if s["id"] == subtask_id)
        assert st["status"] == "in_progress"

    def test_dispatch_includes_methodology_instructions(self, isolated_sagtask, mock_git):
        self._create_task_with_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        subtask_id = plan["subtasks"][0]["id"]
        result = sagtask._handle_sag_task_dispatch({
            "sag_task_id": "test-dispatch",
            "subtask_id": subtask_id,
        })
        assert "tdd" in result["context"].lower() or "test" in result["context"].lower()

    def test_dispatch_includes_task_root(self, isolated_sagtask, mock_git):
        self._create_task_with_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        subtask_id = plan["subtasks"][0]["id"]
        result = sagtask._handle_sag_task_dispatch({
            "sag_task_id": "test-dispatch",
            "subtask_id": subtask_id,
        })
        assert "task_root" in result
        assert "test-dispatch" in result["task_root"]

    def test_dispatch_invalid_subtask(self, isolated_sagtask, mock_git):
        self._create_task_with_plan(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_dispatch({
            "sag_task_id": "test-dispatch",
            "subtask_id": "st-999",
        })
        assert result["ok"] is False
        assert "not found" in result["error"].lower()

    def test_dispatch_already_in_progress(self, isolated_sagtask, mock_git):
        self._create_task_with_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        subtask_id = plan["subtasks"][0]["id"]
        sagtask._handle_sag_task_dispatch({
            "sag_task_id": "test-dispatch",
            "subtask_id": subtask_id,
        })
        result = sagtask._handle_sag_task_dispatch({
            "sag_task_id": "test-dispatch",
            "subtask_id": subtask_id,
        })
        assert result["ok"] is True
        assert "warning" in result or "re-dispatch" in result.get("message", "").lower()

    def test_dispatch_includes_depends_on_status(self, isolated_sagtask, mock_git):
        self._create_task_with_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        dep_task = next((s for s in plan["subtasks"] if s.get("depends_on")), None)
        assert dep_task is not None, "Plan should have at least one subtask with depends_on"
        result = sagtask._handle_sag_task_dispatch({
            "sag_task_id": "test-dispatch",
            "subtask_id": dep_task["id"],
        })
        assert result["ok"] is True
        assert "depends" in result["context"].lower() or "dependency" in result["context"].lower()

    def test_dispatch_warns_on_unfinished_deps(self, isolated_sagtask, mock_git):
        self._create_task_with_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        dep_task = next((s for s in plan["subtasks"] if s.get("depends_on")), None)
        assert dep_task is not None
        result = sagtask._handle_sag_task_dispatch({
            "sag_task_id": "test-dispatch",
            "subtask_id": dep_task["id"],
        })
        assert "warning" in result
        assert "not done" in result["warning"].lower() or "depend" in result["warning"].lower()

    def test_dispatch_records_timestamp(self, isolated_sagtask, mock_git):
        self._create_task_with_plan(isolated_sagtask, mock_git)
        plan = self._get_plan(isolated_sagtask)
        subtask_id = plan["subtasks"][0]["id"]
        sagtask._handle_sag_task_dispatch({
            "sag_task_id": "test-dispatch",
            "subtask_id": subtask_id,
        })
        updated_plan = self._get_plan(isolated_sagtask)
        st = next(s for s in updated_plan["subtasks"] if s["id"] == subtask_id)
        assert "dispatched_at" in st

    def test_dispatch_no_task(self, isolated_sagtask, mock_git):
        result = sagtask._handle_sag_task_dispatch({"subtask_id": "st-1"})
        assert result["ok"] is False
        assert "error" in result
