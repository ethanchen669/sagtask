"""Integration tests that verify sagtask works with actual hermes-agent loading and dispatch.

These tests catch issues that unit tests miss:
- Import failures when loaded as `hermes_plugins.sagtask` (relative vs absolute imports)
- Handler signature mismatches with `registry.dispatch()` kwargs (task_id, user_task)
- Registration failures with real PluginContext

Requires hermes-agent source at ~/ai-workspace/hermes-agent.
Skips gracefully if not available.

Run: pytest tests/test_hermes_integration.py -m integration -v
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path

import pytest

HERMES_AGENT_PATH = Path(
    os.environ.get("HERMES_AGENT_PATH", os.path.expanduser("~/ai-workspace/hermes-agent"))
)
SAGTASK_SRC_DIR = Path(__file__).parent.parent / "src" / "sagtask"

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def hermes_on_path():
    """Add hermes-agent source to sys.path for duration of each test."""
    if not HERMES_AGENT_PATH.exists():
        pytest.skip(f"hermes-agent source not found at {HERMES_AGENT_PATH}")

    path_str = str(HERMES_AGENT_PATH)
    sys.path.insert(0, path_str)
    yield
    sys.path.remove(path_str)

    # Clean hermes modules to prevent cross-test pollution
    to_remove = [
        k for k in sys.modules
        if k.startswith(("hermes_cli", "hermes_plugins", "tools.registry"))
        or k == "tools"
    ]
    for k in to_remove:
        del sys.modules[k]


@pytest.fixture
def clean_sagtask_modules():
    """Remove sagtask modules from sys.modules to allow fresh loading."""
    to_remove = [k for k in sys.modules if k.startswith("sagtask") or k.startswith("hermes_plugins")]
    for k in to_remove:
        del sys.modules[k]
    yield
    # Restore sagtask import for subsequent tests
    to_remove = [k for k in sys.modules if k.startswith("hermes_plugins")]
    for k in to_remove:
        del sys.modules[k]


def _load_as_hermes_plugin():
    """Replicate hermes _load_directory_module for sagtask.

    This is the exact mechanism from hermes_cli/plugins.py:1193-1229.
    """
    # Create hermes_plugins namespace package
    if "hermes_plugins" not in sys.modules:
        ns_pkg = types.ModuleType("hermes_plugins")
        ns_pkg.__path__ = []
        ns_pkg.__package__ = "hermes_plugins"
        sys.modules["hermes_plugins"] = ns_pkg

    module_name = "hermes_plugins.sagtask"
    init_file = SAGTASK_SRC_DIR / "__init__.py"

    spec = importlib.util.spec_from_file_location(
        module_name,
        init_file,
        submodule_search_locations=[str(SAGTASK_SRC_DIR)],
    )
    module = importlib.util.module_from_spec(spec)
    module.__package__ = module_name
    module.__path__ = [str(SAGTASK_SRC_DIR)]
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class TestPluginLoading:
    """Test that sagtask loads correctly under hermes_plugins namespace."""

    def test_loads_without_import_error(self, clean_sagtask_modules):
        """The plugin must load without ImportError when mounted as hermes_plugins.sagtask."""
        module = _load_as_hermes_plugin()
        assert module is not None

    def test_register_function_exists(self, clean_sagtask_modules):
        """The loaded module must expose a register() function."""
        module = _load_as_hermes_plugin()
        assert hasattr(module, "register")
        assert callable(module.register)

    def test_all_public_attributes_accessible(self, clean_sagtask_modules):
        """All key attributes must be accessible after namespace loading."""
        module = _load_as_hermes_plugin()
        assert hasattr(module, "SagTaskPlugin")
        assert hasattr(module, "ALL_TOOL_SCHEMAS")
        assert hasattr(module, "_on_pre_llm_call")
        assert hasattr(module, "_on_session_start")
        assert len(module.ALL_TOOL_SCHEMAS) == 19

    def test_submodule_imports_work(self, clean_sagtask_modules):
        """Submodules (handlers, schemas, plugin) must be importable."""
        module = _load_as_hermes_plugin()
        # handlers._tool_handlers should be accessible
        from hermes_plugins.sagtask.handlers import _tool_handlers
        assert len(_tool_handlers) == 19

    def test_handler_modules_accessible(self, clean_sagtask_modules):
        """Each handler submodule must be importable."""
        _load_as_hermes_plugin()
        from hermes_plugins.sagtask.handlers import _lifecycle
        from hermes_plugins.sagtask.handlers import _git
        from hermes_plugins.sagtask.handlers import _plan
        from hermes_plugins.sagtask.handlers import _orchestration
        from hermes_plugins.sagtask.handlers import _metrics
        assert _lifecycle is not None
        assert _git is not None
        assert _plan is not None
        assert _orchestration is not None
        assert _metrics is not None


class TestRegistration:
    """Test register(ctx) with real hermes PluginContext."""

    def test_register_completes(self, clean_sagtask_modules, tmp_path):
        """register(ctx) must complete without error using real PluginContext."""
        module = _load_as_hermes_plugin()

        from hermes_cli.plugins import PluginManager, PluginManifest, PluginContext

        mgr = PluginManager()
        manifest = PluginManifest(
            name="sagtask",
            source="user",
            path=str(SAGTASK_SRC_DIR),
        )
        ctx = PluginContext(manifest, mgr)

        # Reset singleton so register() runs its full path
        module._utils._sagtask_instance = None
        module.register(ctx)

        # Verify tools were registered
        assert len(mgr._plugin_tool_names) == 19

        # Verify hooks were registered
        assert "pre_llm_call" in mgr._hooks
        assert "on_session_start" in mgr._hooks
        assert len(mgr._hooks["pre_llm_call"]) == 1
        assert len(mgr._hooks["on_session_start"]) == 1

        # Cleanup
        module._utils._sagtask_instance = None

    def test_all_19_tools_registered_by_name(self, clean_sagtask_modules, tmp_path):
        """Every expected tool name must be registered."""
        module = _load_as_hermes_plugin()
        from hermes_cli.plugins import PluginManager, PluginManifest, PluginContext

        mgr = PluginManager()
        manifest = PluginManifest(name="sagtask", source="user", path=str(SAGTASK_SRC_DIR))
        ctx = PluginContext(manifest, mgr)

        module._utils._sagtask_instance = None
        module.register(ctx)

        expected_tools = {
            "sag_task_create", "sag_task_status", "sag_task_pause", "sag_task_resume",
            "sag_task_advance", "sag_task_approve", "sag_task_list", "sag_task_commit",
            "sag_task_branch", "sag_task_git_log", "sag_task_relate", "sag_task_verify",
            "sag_task_plan", "sag_task_plan_update", "sag_task_dispatch", "sag_task_review",
            "sag_task_brainstorm", "sag_task_debug", "sag_task_metrics",
        }
        assert mgr._plugin_tool_names == expected_tools
        module._utils._sagtask_instance = None


class TestDispatchKwargs:
    """Test that all handlers accept the kwargs registry.dispatch() passes."""

    def test_all_handlers_accept_task_id_and_user_task(self, clean_sagtask_modules, tmp_path):
        """Every handler must accept task_id and user_task kwargs without TypeError.

        This is the exact calling convention: registry.dispatch(name, args, task_id=..., user_task=...)
        """
        module = _load_as_hermes_plugin()
        from tools.registry import ToolRegistry

        # Set up a minimal provider so handlers don't crash on NoneType
        module._utils._sagtask_instance = None
        plugin = module.SagTaskPlugin.__new__(module.SagTaskPlugin)
        plugin._hermes_home = tmp_path / "hermes"
        plugin._projects_root = tmp_path / "hermes" / "sag_tasks"
        plugin._projects_root.mkdir(parents=True)
        plugin._active_task_id = None
        module._utils._sagtask_instance = plugin

        reg = ToolRegistry()
        from hermes_plugins.sagtask.handlers import _tool_handlers

        for name, handler in _tool_handlers.items():
            schema = next(s for s in module.ALL_TOOL_SCHEMAS if s["name"] == name)
            reg.register(name=name, toolset="sagtask", schema=schema, handler=handler)

        for name in _tool_handlers:
            # Dispatch with kwargs exactly as hermes does
            result = reg.dispatch(name, {}, task_id="integration-test-123", user_task="test task")
            # Result should be valid (error JSON is fine — we're testing no TypeError)
            assert "TypeError" not in str(result), f"Handler {name} does not accept dispatch kwargs"

        module._utils._sagtask_instance = None

    def test_handlers_return_serializable_result(self, clean_sagtask_modules, tmp_path):
        """Handlers must return something json.dumps can serialize (dict or str)."""
        module = _load_as_hermes_plugin()

        module._utils._sagtask_instance = None
        plugin = module.SagTaskPlugin.__new__(module.SagTaskPlugin)
        plugin._hermes_home = tmp_path / "hermes"
        plugin._projects_root = tmp_path / "hermes" / "sag_tasks"
        plugin._projects_root.mkdir(parents=True)
        plugin._active_task_id = None
        module._utils._sagtask_instance = plugin

        from hermes_plugins.sagtask.handlers import _tool_handlers

        # Skip sag_task_create which requires specific args (sag_task_id, name)
        skip = {"sag_task_create"}
        for name, handler in _tool_handlers.items():
            if name in skip:
                continue
            result = handler({}, task_id="test-123", user_task="test")
            # Must be serializable
            serialized = json.dumps(result, ensure_ascii=False)
            assert isinstance(serialized, str), f"Handler {name} returned non-serializable result"

        module._utils._sagtask_instance = None


class TestHookSignatures:
    """Test that hooks accept the calling convention hermes uses."""

    def test_pre_llm_call_hook_accepts_kwargs(self, clean_sagtask_modules, tmp_path):
        """pre_llm_call signature: (session_id, user_message, conversation_history, is_first_turn, model, platform, sender_id, **kwargs)."""
        module = _load_as_hermes_plugin()

        module._utils._sagtask_instance = None
        plugin = module.SagTaskPlugin.__new__(module.SagTaskPlugin)
        plugin._hermes_home = tmp_path / "hermes"
        plugin._projects_root = tmp_path / "hermes" / "sag_tasks"
        plugin._projects_root.mkdir(parents=True)
        plugin._active_task_id = None
        plugin._injection_cache = {}
        plugin._injection_lock = __import__("threading").Lock()
        module._utils._sagtask_instance = plugin

        # Call with the actual hermes calling convention
        result = module._on_pre_llm_call(
            session_id="session-abc",
            user_message="hello",
            conversation_history=[],
            is_first_turn=True,
            model="claude-sonnet-4-20250514",
            platform="cli",
            sender_id="user-1",
            hermes_home=str(tmp_path / "hermes"),
        )
        # Result is {} or {"context": "..."} when no active task
        assert isinstance(result, dict)

        module._utils._sagtask_instance = None

    def test_on_session_start_hook_accepts_kwargs(self, clean_sagtask_modules, tmp_path):
        """on_session_start signature: (session_id, model, platform, **kwargs)."""
        module = _load_as_hermes_plugin()

        module._utils._sagtask_instance = None
        plugin = module.SagTaskPlugin.__new__(module.SagTaskPlugin)
        plugin._hermes_home = tmp_path / "hermes"
        plugin._projects_root = tmp_path / "hermes" / "sag_tasks"
        plugin._projects_root.mkdir(parents=True)
        plugin._active_task_id = None
        module._utils._sagtask_instance = plugin

        # Call with the actual hermes calling convention
        result = module._on_session_start(
            session_id="session-abc",
            model="claude-sonnet-4-20250514",
            platform="cli",
            hermes_home=str(tmp_path / "hermes"),
        )
        # Returns None
        assert result is None

        module._utils._sagtask_instance = None
