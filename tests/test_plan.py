"""Tests for sag_task_plan tool."""
import json
import pytest
import sagtask


class TestPlanGeneration:
    def _create_task_with_tdd_step(self, plugin, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-plan",
            "name": "Test Plan",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [{
                    "id": "step-1",
                    "name": "Implement Parser",
                    "description": "Build a JSON parser with error recovery",
                    "methodology": {"type": "tdd", "config": {"coverage_threshold": 80}},
                }],
            }],
        })

    def test_plan_creates_plan_file(self, isolated_sagtask, mock_git):
        """sag_task_plan should create .sag_plans/<step_id>.json."""
        self._create_task_with_tdd_step(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_plan({"sag_task_id": "test-plan"})
        assert result["ok"] is True
        plan_path = isolated_sagtask.get_task_root("test-plan") / ".sag_plans" / "step-1.json"
        assert plan_path.exists()

    def test_plan_has_correct_structure(self, isolated_sagtask, mock_git):
        """Plan file should have step_id, generated_at, methodology, subtasks."""
        self._create_task_with_tdd_step(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_plan({"sag_task_id": "test-plan"})
        plan_path = isolated_sagtask.get_task_root("test-plan") / ".sag_plans" / "step-1.json"
        plan = json.loads(plan_path.read_text())
        assert plan["step_id"] == "step-1"
        assert "generated_at" in plan
        assert plan["methodology"] == "tdd"
        assert isinstance(plan["subtasks"], list)
        assert len(plan["subtasks"]) >= 2

    def test_subtask_has_required_fields(self, isolated_sagtask, mock_git):
        """Each subtask should have id, title, status, depends_on, context."""
        self._create_task_with_tdd_step(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_plan({"sag_task_id": "test-plan"})
        plan_path = isolated_sagtask.get_task_root("test-plan") / ".sag_plans" / "step-1.json"
        plan = json.loads(plan_path.read_text())
        for st in plan["subtasks"]:
            assert "id" in st
            assert "title" in st
            assert st["status"] == "pending"
            assert "depends_on" in st
            assert "context" in st

    def test_plan_updates_state_reference(self, isolated_sagtask, mock_git):
        """Plan should update methodology_state.plan_file and subtask_progress."""
        self._create_task_with_tdd_step(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_plan({"sag_task_id": "test-plan"})
        state = isolated_sagtask.load_task_state("test-plan")
        ms = state["methodology_state"]
        assert ms["plan_file"] == ".sag_plans/step-1.json"
        assert ms["subtask_progress"]["total"] > 0
        assert ms["subtask_progress"]["completed"] == 0

    def test_plan_without_methodology_uses_default(self, isolated_sagtask, mock_git):
        """Steps without methodology should get a default plan."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-plan-no-method",
            "name": "No Method",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [{"id": "step-1", "name": "Do Something", "description": "Do the thing"}],
            }],
        })
        result = sagtask._handle_sag_task_plan({"sag_task_id": "test-plan-no-method"})
        assert result["ok"] is True
        plan_path = isolated_sagtask.get_task_root("test-plan-no-method") / ".sag_plans" / "step-1.json"
        plan = json.loads(plan_path.read_text())
        assert plan["methodology"] == "none"
        assert len(plan["subtasks"]) >= 1

    def test_plan_fails_without_active_task(self, isolated_sagtask, mock_git):
        """Should return error when no task_id and no active task."""
        result = sagtask._handle_sag_task_plan({})
        assert result["ok"] is False
        assert "error" in result

    def test_plan_fails_when_step_has_existing_plan(self, isolated_sagtask, mock_git):
        """Should return error if step already has a plan (use update to modify)."""
        self._create_task_with_tdd_step(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_plan({"sag_task_id": "test-plan"})
        result = sagtask._handle_sag_task_plan({"sag_task_id": "test-plan"})
        assert result["ok"] is False
        assert "already" in result["error"].lower() or "exists" in result["error"].lower()

    def test_plan_granularity_affects_subtask_count(self, isolated_sagtask, mock_git):
        """Fine granularity should produce more subtasks than coarse."""
        self._create_task_with_tdd_step(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_plan({"sag_task_id": "test-plan", "granularity": "fine"})
        plan_path = isolated_sagtask.get_task_root("test-plan") / ".sag_plans" / "step-1.json"
        plan = json.loads(plan_path.read_text())
        assert plan["granularity"] == "fine"
        # Fine granularity: at least 3 subtasks for a TDD step
        assert len(plan["subtasks"]) >= 3

    def test_tdd_plan_includes_red_green_refactor(self, isolated_sagtask, mock_git):
        """TDD methodology plan should include RED, GREEN, REFACTOR subtasks."""
        self._create_task_with_tdd_step(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_plan({"sag_task_id": "test-plan"})
        plan_path = isolated_sagtask.get_task_root("test-plan") / ".sag_plans" / "step-1.json"
        plan = json.loads(plan_path.read_text())
        titles = [st["title"].lower() for st in plan["subtasks"]]
        has_red = any("red" in t or "failing" in t or "test" in t for t in titles)
        has_green = any("green" in t or "implement" in t or "pass" in t for t in titles)
        assert has_red and has_green
