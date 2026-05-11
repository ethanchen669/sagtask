"""Tests for sag_task_brainstorm tool."""
import json
import pytest
import sagtask


class TestBrainstorm:
    def _create_brainstorm_task(self, plugin, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-brain",
            "name": "Test Brainstorm",
            "phases": [{
                "id": "phase-1",
                "name": "Design",
                "steps": [{
                    "id": "step-1",
                    "name": "Design Parser",
                    "description": "Design a JSON parser with error recovery",
                    "methodology": {"type": "brainstorm"},
                }],
            }],
        })

    def test_brainstorm_returns_context(self, isolated_sagtask, mock_git):
        self._create_brainstorm_task(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_brainstorm({
            "sag_task_id": "test-brain",
        })
        assert result["ok"] is True
        assert "context" in result
        assert "brainstorm" in result["context"].lower() or "design" in result["context"].lower()

    def test_brainstorm_sets_explore_phase(self, isolated_sagtask, mock_git):
        self._create_brainstorm_task(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_brainstorm({"sag_task_id": "test-brain"})
        state = isolated_sagtask.load_task_state("test-brain")
        ms = state.get("methodology_state", {})
        assert ms.get("brainstorm_phase") == "explore"

    def test_brainstorm_records_selection(self, isolated_sagtask, mock_git):
        self._create_brainstorm_task(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_brainstorm({"sag_task_id": "test-brain"})
        result = sagtask._handle_sag_task_brainstorm({
            "sag_task_id": "test-brain",
            "selected_option": 1,
        })
        assert result["ok"] is True
        state = isolated_sagtask.load_task_state("test-brain")
        ms = state.get("methodology_state", {})
        assert ms.get("brainstorm_phase") == "select"
        assert ms.get("brainstorm_selected") == 1

    def test_brainstorm_records_custom_design(self, isolated_sagtask, mock_git):
        self._create_brainstorm_task(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_brainstorm({
            "sag_task_id": "test-brain",
            "selected_option": 0,
            "design_title": "Recursive Descent Parser",
            "design_description": "Use recursive descent with error recovery tokens",
        })
        assert result["ok"] is True
        state = isolated_sagtask.load_task_state("test-brain")
        ms = state.get("methodology_state", {})
        assert ms.get("brainstorm_selected_design", {}).get("title") == "Recursive Descent Parser"

    def test_brainstorm_includes_step_info(self, isolated_sagtask, mock_git):
        self._create_brainstorm_task(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_brainstorm({"sag_task_id": "test-brain"})
        assert "Design Parser" in result["context"]
        assert "JSON parser" in result["context"]

    def test_brainstorm_no_task(self, isolated_sagtask, mock_git):
        result = sagtask._handle_sag_task_brainstorm({})
        assert result["ok"] is False
        assert "error" in result

    def test_brainstorm_already_selected(self, isolated_sagtask, mock_git):
        self._create_brainstorm_task(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_brainstorm({"sag_task_id": "test-brain"})
        sagtask._handle_sag_task_brainstorm({
            "sag_task_id": "test-brain",
            "selected_option": 1,
        })
        result = sagtask._handle_sag_task_brainstorm({
            "sag_task_id": "test-brain",
            "selected_option": 2,
        })
        assert result["ok"] is True
        assert "warning" in result or "already" in result.get("message", "").lower()
