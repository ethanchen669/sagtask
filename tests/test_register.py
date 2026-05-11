"""Tests for register() and _on_session_start hook."""
from pathlib import Path
from unittest.mock import MagicMock

import sagtask


class TestRegister:
    def test_register_creates_singleton(self):
        sagtask._sagtask_instance = None
        sagtask._utils._sagtask_instance = None
        ctx = MagicMock()
        sagtask.register(ctx)
        assert sagtask._sagtask_instance is not None
        sagtask._sagtask_instance = None
        sagtask._utils._sagtask_instance = None

    def test_register_skips_if_already_registered(self):
        sagtask._sagtask_instance = sagtask.SagTaskPlugin()
        sagtask._utils._sagtask_instance = sagtask._sagtask_instance
        ctx = MagicMock()
        sagtask.register(ctx)
        ctx.register_tool.assert_not_called()
        ctx.register_hook.assert_not_called()
        sagtask._sagtask_instance = None
        sagtask._utils._sagtask_instance = None

    def test_register_calls_tools_and_hooks(self):
        sagtask._sagtask_instance = None
        sagtask._utils._sagtask_instance = None
        ctx = MagicMock()
        sagtask.register(ctx)
        assert ctx.register_tool.call_count == len(sagtask.ALL_TOOL_SCHEMAS)
        assert ctx.register_hook.call_count == 2
        sagtask._sagtask_instance = None
        sagtask._utils._sagtask_instance = None


class TestOnSessionStart:
    def test_session_start_initializes_projects_root(self):
        plugin = sagtask.SagTaskPlugin()
        plugin._projects_root = None
        sagtask._sagtask_instance = plugin
        sagtask._utils._sagtask_instance = plugin
        sagtask._on_session_start("s1", "test-model", "test-platform")
        assert plugin._projects_root is not None
        sagtask._sagtask_instance = None
        sagtask._utils._sagtask_instance = None

    def test_session_start_restores_active_task(self, tmp_path):
        plugin = sagtask.SagTaskPlugin()
        plugin._projects_root = tmp_path / "sag_tasks"
        plugin._projects_root.mkdir()
        marker = plugin._projects_root / ".active_task"
        marker.write_text("restored-task")
        sagtask._sagtask_instance = plugin
        sagtask._utils._sagtask_instance = plugin
        # Create a minimal state file so _restore_active_task finds it
        task_root = plugin._projects_root / "restored-task"
        task_root.mkdir()
        state_path = task_root / ".sag_task_state.json"
        state_path.write_text('{"name": "test"}')
        plugin._active_task_id = None
        sagtask._on_session_start("s1", "test-model", "test-platform")
        assert plugin._active_task_id == "restored-task"
        sagtask._sagtask_instance = None
        sagtask._utils._sagtask_instance = None
