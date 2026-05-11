"""SagTask — Task management plugin for Hermes Agent.

Per-task Git repos with human-in-the-loop approval gates and cross-session
recovery. SagTask overlays task-management context on top of any existing
memory provider — it does NOT replace it.

INSTALLATION (user plugin):
  git clone https://github.com/ethanchen669/sagtask.git ~/.hermes/plugins/sagtask
  Restart the Hermes gateway.

STORAGE LAYOUT:
  ~/.hermes/sag_tasks/<task_id>/
  ├── .git/                           ← Task Git repo (lazy init)
  ├── .gitignore                      ← Ignores: .sag_task_state.json, .sag_artifacts/, .sag_executions/
  ├── .sag_task_state.json            ← Machine-readable state (NOT in Git)
  ├── src/                            ← ✅ In Git
  ├── tests/                          ← ✅ In Git
  ├── docs/                           ← ✅ In Git
  ├── .sag_plans/                     ← ✅ In Git (subtask plans are valuable artifacts)
  ├── .sag_artifacts/                 ← ⚠️ Git-ignored (manual cleanup)
  └── .sag_executions/                ← ⚠️ Git-ignored (snapshot on pause)
SagTask — user plugin (standalone, NOT a memory provider).
Context is injected via pre_llm_call hook.
"""

from __future__ import annotations

import logging
import subprocess  # noqa: F401 — re-exported for test mock targets (conftest patches sagtask.subprocess.run)
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Re-exported from _utils for backward compatibility ────────────────────────
from ._utils import (  # noqa: E402
    SCHEMA_VERSION,
    _SUBPROCESS_TIMEOUT,
    _TASK_ID_RE,
    _VERIFY_OUTPUT_MAX_LEN,
    _get_github_owner,
    _get_provider,
    _utcnow_iso,
    _validate_task_id,
)
from . import _utils  # noqa: E402


from sagtask.schemas import (  # noqa: F401
    ALL_TOOL_SCHEMAS,
    TASK_ADVANCE_SCHEMA,
    TASK_APPROVE_SCHEMA,
    TASK_BRANCH_SCHEMA,
    TASK_COMMIT_SCHEMA,
    TASK_CREATE_SCHEMA,
    TASK_GIT_LOG_SCHEMA,
    TASK_LIST_SCHEMA,
    TASK_PAUSE_SCHEMA,
    TASK_PLAN_SCHEMA,
    TASK_PLAN_UPDATE_SCHEMA,
    TASK_RELATE_SCHEMA,
    TASK_RESUME_SCHEMA,
    TASK_STATUS_SCHEMA,
    TASK_VERIFY_SCHEMA,
)

# ─────────────────────────────────────────────────────────────────────────────
# Singleton instance — set by register(), used by tool handlers
# ─────────────────────────────────────────────────────────────────────────────

# Backward-compat alias — the canonical storage lives in _utils._sagtask_instance.
# Tests do ``sagtask._sagtask_instance = None`` so we keep this variable here.
_sagtask_instance: Optional["SagTaskPlugin"] = None


from sagtask.plugin import SagTaskPlugin  # noqa: F401

# ─────────────────────────────────────────────────────────────────────────────
# Tool handlers — extracted to sagtask.handlers subpackage
# ─────────────────────────────────────────────────────────────────────────────

from sagtask.handlers._lifecycle import (  # noqa: F401
    _handle_sag_task_advance,
    _handle_sag_task_approve,
    _handle_sag_task_create,
    _handle_sag_task_pause,
    _handle_sag_task_resume,
    _handle_sag_task_status,
)

# ─────────────────────────────────────────────────────────────────────────────
# Git handlers — extracted to handlers/_git.py
# ─────────────────────────────────────────────────────────────────────────────

from sagtask.handlers._git import (  # noqa: F401
    _handle_sag_task_branch,
    _handle_sag_task_commit,
    _handle_sag_task_git_log,
    _handle_sag_task_list,
)

# ─────────────────────────────────────────────────────────────────────────────
# Plan handlers — extracted to handlers/_plan.py
# ─────────────────────────────────────────────────────────────────────────────

from sagtask.handlers._plan import (  # noqa: F401
    _handle_sag_task_plan,
    _handle_sag_task_plan_update,
    _handle_sag_task_relate,
    _handle_sag_task_verify,
)

# ─────────────────────────────────────────────────────────────────────────────
# Handler dispatch map — used by register() to call ctx.register_tool()
# ─────────────────────────────────────────────────────────────────────────────

from sagtask.handlers import _tool_handlers  # noqa: F401


# ─────────────────────────────────────────────────────────────────────────────
# Hook callbacks — registered via ctx.register_hook()
# ─────────────────────────────────────────────────────────────────────────────

def _on_pre_llm_call(
    session_id: str,
    user_message: str,
    conversation_history: List[Any],
    is_first_turn: bool,
    model: str,
    platform: str,
    sender_id: str,
    **kwargs,
) -> Dict[str, Any]:
    """pre_llm_call hook — inject task context before each LLM call.

    Returns {"context": "..."} to be appended to the user message,
    or {} to skip injection.
    """
    p = _get_provider()

    # Ensure projects root is initialized
    if p._projects_root is None:
        hermes_home = kwargs.get("hermes_home")
        if hermes_home:
            p._hermes_home = Path(hermes_home)
        else:
            p._hermes_home = Path.home() / ".hermes"
        p._projects_root = p._hermes_home / "sag_tasks"
        p._projects_root.mkdir(parents=True, exist_ok=True)
        p._restore_active_task()

    if not p._active_task_id:
        return {}

    state = p.load_task_state(p._active_task_id)
    if not state:
        return {}

    context_text = p._build_task_context(state, include_methodology=True)
    return {"context": context_text}


def _on_session_start(
    session_id: str,
    model: str,
    platform: str,
    **kwargs,
) -> None:
    """on_session_start hook — restore active task marker on session start."""
    p = _get_provider()
    if p._projects_root is None:
        hermes_home = kwargs.get("hermes_home")
        if hermes_home:
            p._hermes_home = Path(hermes_home)
        else:
            p._hermes_home = Path.home() / ".hermes"
        p._projects_root = p._hermes_home / "sag_tasks"
        p._projects_root.mkdir(parents=True, exist_ok=True)
    p._restore_active_task()
    logger.debug(
        "SagTask on_session_start: session_id=%s, active_task=%s",
        session_id,
        p._active_task_id,
    )


# ----------------------------------------------------------------------------
# Plugin registration — singleton guard + hook + tool registration
# -----------------------------------------------------------------------------


def register(ctx) -> None:
    """Register SagTask as a user plugin.

    - Registers task_* tools via ctx.register_tool()
    - Registers pre_llm_call hook for per-turn context injection
    - Registers on_session_start hook for sagtask root initialization
    """
    global _sagtask_instance
    if _sagtask_instance is not None:
        logger.debug("SagTaskPlugin already registered, skipping")
        return

    _sagtask_instance = SagTaskPlugin()
    _utils._sagtask_instance = _sagtask_instance

    # ── Tools ────────────────────────────────────────────────────────────────
    for schema in ALL_TOOL_SCHEMAS:
        tool_name = schema["name"]
        handler = _tool_handlers.get(tool_name)
        if not handler:
            logger.warning("No handler registered for tool: %s", tool_name)
            continue
        ctx.register_tool(
            name=tool_name,
            toolset="memory",
            schema=schema,
            handler=handler,
            description=schema.get("description", ""),
        )
        logger.debug("Registered tool: %s", tool_name)

    # ── Hooks ───────────────────────────────────────────────────────────────
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    ctx.register_hook("on_session_start", _on_session_start)
    logger.info("SagTask plugin registered (tools=%d, hooks=pre_llm_call+on_session_start)", len(_tool_handlers))
