"""Tests for sag_task_debug tool."""
import pytest
import sagtask


class TestDebug:
    def _create_debug_task(self, plugin, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-debug",
            "name": "Test Debug",
            "phases": [{
                "id": "phase-1",
                "name": "Fix",
                "steps": [{
                    "id": "step-1",
                    "name": "Fix Parser Crash",
                    "description": "Parser crashes on nested arrays deeper than 10 levels",
                    "methodology": {"type": "debug"},
                }],
            }],
        })

    def test_debug_returns_context(self, isolated_sagtask, mock_git):
        self._create_debug_task(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_debug({
            "sag_task_id": "test-debug",
        })
        assert result["ok"] is True
        assert "context" in result
        assert "debug" in result["context"].lower() or "reproduce" in result["context"].lower()

    def test_debug_sets_reproduce_phase(self, isolated_sagtask, mock_git):
        self._create_debug_task(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_debug({"sag_task_id": "test-debug"})
        state = isolated_sagtask.load_task_state("test-debug")
        ms = state.get("methodology_state", {})
        assert ms.get("debug_phase") == "reproduce"

    def test_debug_records_hypothesis(self, isolated_sagtask, mock_git):
        self._create_debug_task(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_debug({"sag_task_id": "test-debug"})
        result = sagtask._handle_sag_task_debug({
            "sag_task_id": "test-debug",
            "hypothesis": "Stack overflow from unbounded recursion",
        })
        assert result["ok"] is True
        state = isolated_sagtask.load_task_state("test-debug")
        ms = state.get("methodology_state", {})
        assert ms.get("debug_phase") == "diagnose"
        assert ms.get("debug_hypothesis") == "Stack overflow from unbounded recursion"

    def test_debug_records_fix(self, isolated_sagtask, mock_git):
        self._create_debug_task(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_debug({"sag_task_id": "test-debug"})
        sagtask._handle_sag_task_debug({
            "sag_task_id": "test-debug",
            "hypothesis": "Stack overflow from unbounded recursion",
        })
        result = sagtask._handle_sag_task_debug({
            "sag_task_id": "test-debug",
            "fix_description": "Added max_depth=100 parameter with ValueError on exceed",
        })
        assert result["ok"] is True
        state = isolated_sagtask.load_task_state("test-debug")
        ms = state.get("methodology_state", {})
        assert ms.get("debug_phase") == "fix"
        assert "max_depth" in ms.get("debug_fix", "")

    def test_debug_includes_step_info(self, isolated_sagtask, mock_git):
        self._create_debug_task(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_debug({"sag_task_id": "test-debug"})
        assert "Fix Parser Crash" in result["context"]
        assert "nested arrays" in result["context"]

    def test_debug_no_task(self, isolated_sagtask, mock_git):
        result = sagtask._handle_sag_task_debug({})
        assert result["ok"] is False
        assert "error" in result

    def test_debug_phase_progression(self, isolated_sagtask, mock_git):
        self._create_debug_task(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_debug({"sag_task_id": "test-debug"})
        sagtask._handle_sag_task_debug({
            "sag_task_id": "test-debug",
            "hypothesis": "Null pointer on empty input",
        })
        sagtask._handle_sag_task_debug({
            "sag_task_id": "test-debug",
            "fix_description": "Added null check",
        })
        state = isolated_sagtask.load_task_state("test-debug")
        ms = state.get("methodology_state", {})
        assert ms.get("debug_phase") == "fix"
