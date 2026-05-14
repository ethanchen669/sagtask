"""Tests for methodology context injection in pre_llm_call."""
import json
import sagtask


class TestContextInjection:
    def _create_task_with_methodology(self, plugin, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-ctx",
            "name": "Test Context",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [{
                    "id": "step-1",
                    "name": "Step 1",
                    "methodology": {"type": "tdd", "config": {"coverage_threshold": 80}},
                    "verification": {"commands": ["pytest"], "must_pass": True},
                }],
            }],
        })
        active_file = plugin._projects_root / ".active_task"
        active_file.write_text("test-ctx")

    def test_context_includes_methodology_type(self, isolated_sagtask, mock_git):
        """Context should include methodology type when set."""
        self._create_task_with_methodology(isolated_sagtask, mock_git)
        result = sagtask._on_pre_llm_call(
            session_id="test", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert "context" in result
        assert "tdd" in result["context"].lower()

    def test_context_includes_verification_status(self, isolated_sagtask, mock_git):
        """Context should include verification status when verification is configured."""
        self._create_task_with_methodology(isolated_sagtask, mock_git)
        result = sagtask._on_pre_llm_call(
            session_id="test", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert "verify:" in result["context"].lower()

    def test_context_includes_tdd_phase(self, isolated_sagtask, mock_git):
        """Context should include TDD phase when methodology is tdd."""
        self._create_task_with_methodology(isolated_sagtask, mock_git)
        state = isolated_sagtask.load_task_state("test-ctx")
        state["methodology_state"]["tdd_phase"] = "red"
        isolated_sagtask.save_task_state("test-ctx", state)
        result = sagtask._on_pre_llm_call(
            session_id="test", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert "RED" in result["context"]

    def test_context_no_methodology_for_none(self, isolated_sagtask, mock_git):
        """Context should not show methodology line when methodology is 'none'."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-ctx-none",
            "name": "No Method",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [{"id": "step-1", "name": "Step 1"}],
            }],
        })
        active_file = isolated_sagtask._projects_root / ".active_task"
        active_file.write_text("test-ctx-none")
        result = sagtask._on_pre_llm_call(
            session_id="test", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert "Methodology" not in result.get("context", "")

    def test_context_includes_plan_progress(self, isolated_sagtask, mock_git):
        """Context should include plan progress when plan exists."""
        self._create_task_with_methodology(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_plan({"sag_task_id": "test-ctx"})
        result = sagtask._on_pre_llm_call(
            session_id="test", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert "plan" in result["context"].lower()
        assert "0/" in result["context"]

    def test_context_shows_updated_progress(self, isolated_sagtask, mock_git):
        """Context should reflect completed subtasks."""
        self._create_task_with_methodology(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_plan({"sag_task_id": "test-ctx"})
        plan_path = isolated_sagtask.get_task_root("test-ctx") / ".sag_plans" / "step-1.json"
        plan = json.loads(plan_path.read_text())
        first_id = plan["subtasks"][0]["id"]
        sagtask._handle_sag_task_plan_update({
            "sag_task_id": "test-ctx",
            "subtask_id": first_id,
            "status": "done",
        })
        result = sagtask._on_pre_llm_call(
            session_id="test", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert "1/" in result["context"]

    def test_context_shows_active_dispatches(self, isolated_sagtask, mock_git):
        """Context should show in-progress subtasks as active dispatches."""
        self._create_task_with_methodology(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_plan({"sag_task_id": "test-ctx"})
        plan_path = isolated_sagtask.get_task_root("test-ctx") / ".sag_plans" / "step-1.json"
        plan = json.loads(plan_path.read_text())
        first_id = plan["subtasks"][0]["id"]
        sagtask._handle_sag_task_plan_update({
            "sag_task_id": "test-ctx",
            "subtask_id": first_id,
            "status": "in_progress",
        })
        result = sagtask._on_pre_llm_call(
            session_id="test", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert "active" in result["context"].lower()

    def test_context_shows_brainstorm_phase(self, isolated_sagtask, mock_git):
        """Context should show brainstorm phase when brainstorm methodology is active."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-ctx-brain",
            "name": "Brainstorm Context",
            "phases": [{
                "id": "p1", "name": "P1",
                "steps": [{
                    "id": "s1", "name": "Design Module",
                    "methodology": {"type": "brainstorm"},
                }],
            }],
        })
        sagtask._handle_sag_task_brainstorm({"sag_task_id": "test-ctx-brain"})
        isolated_sagtask._active_task_id = "test-ctx-brain"
        result = sagtask._on_pre_llm_call(
            session_id="s1", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert "brainstorm" in result["context"].lower() or "explore" in result["context"].lower()

    def test_context_shows_brainstorm_selected(self, isolated_sagtask, mock_git):
        """Context should show selected option after brainstorm selection."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-ctx-brain-sel",
            "name": "Brainstorm Selected",
            "phases": [{
                "id": "p1", "name": "P1",
                "steps": [{
                    "id": "s1", "name": "Design Module",
                    "methodology": {"type": "brainstorm"},
                }],
            }],
        })
        sagtask._handle_sag_task_brainstorm({"sag_task_id": "test-ctx-brain-sel"})
        sagtask._handle_sag_task_brainstorm({
            "sag_task_id": "test-ctx-brain-sel",
            "selected_option": 2,
        })
        isolated_sagtask._active_task_id = "test-ctx-brain-sel"
        result = sagtask._on_pre_llm_call(
            session_id="s1", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert "brainstorm" in result["context"].lower()
        assert "select" in result["context"].lower()

    def test_context_shows_debug_phase(self, isolated_sagtask, mock_git):
        """Context should show debug phase when debug methodology is active."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-ctx-debug",
            "name": "Debug Context",
            "phases": [{
                "id": "p1", "name": "P1",
                "steps": [{
                    "id": "s1", "name": "Fix Bug",
                    "methodology": {"type": "debug"},
                }],
            }],
        })
        sagtask._handle_sag_task_debug({"sag_task_id": "test-ctx-debug"})
        isolated_sagtask._active_task_id = "test-ctx-debug"
        result = sagtask._on_pre_llm_call(
            session_id="s1", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert "debug" in result["context"].lower() or "reproduce" in result["context"].lower()

    def test_context_shows_debug_diagnose_with_hypothesis(self, isolated_sagtask, mock_git):
        """Context should show debug diagnose phase."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-ctx-debug-hyp",
            "name": "Debug Hypothesis",
            "phases": [{
                "id": "p1", "name": "P1",
                "steps": [{
                    "id": "s1", "name": "Fix Bug",
                    "methodology": {"type": "debug"},
                }],
            }],
        })
        sagtask._handle_sag_task_debug({"sag_task_id": "test-ctx-debug-hyp"})
        sagtask._handle_sag_task_debug({
            "sag_task_id": "test-ctx-debug-hyp",
            "hypothesis": "Null pointer on empty input",
        })
        isolated_sagtask._active_task_id = "test-ctx-debug-hyp"
        result = sagtask._on_pre_llm_call(
            session_id="s1", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert "debug" in result["context"].lower()
        assert "diagnosing" in result["context"].lower()

    def test_context_shows_debug_fix_phase(self, isolated_sagtask, mock_git):
        """Context should show debug fix phase."""
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-ctx-debug-fix",
            "name": "Debug Fix",
            "phases": [{
                "id": "p1", "name": "P1",
                "steps": [{
                    "id": "s1", "name": "Fix Bug",
                    "methodology": {"type": "debug"},
                }],
            }],
        })
        sagtask._handle_sag_task_debug({"sag_task_id": "test-ctx-debug-fix"})
        sagtask._handle_sag_task_debug({
            "sag_task_id": "test-ctx-debug-fix",
            "hypothesis": "Root cause",
        })
        sagtask._handle_sag_task_debug({
            "sag_task_id": "test-ctx-debug-fix",
            "fix_description": "Added null check",
        })
        isolated_sagtask._active_task_id = "test-ctx-debug-fix"
        result = sagtask._on_pre_llm_call(
            session_id="s1", user_message="hello", conversation_history=[],
            is_first_turn=True, model="test", platform="test", sender_id="test",
        )
        assert "debug" in result["context"].lower()
        assert "fix" in result["context"].lower()
