"""SagTask — Task management plugin for Hermes Agent.

Per-task Git repos with human-in-the-loop approval gates and cross-session
recovery. This is a thin re-export layer; logic lives in submodules:
  hooks.py, plugin.py, schemas.py, _utils.py, handlers/.
"""

from __future__ import annotations

import logging
import subprocess  # noqa: F401 — re-exported for test mock targets (conftest patches sagtask.subprocess.run)

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
    TASK_DISPATCH_SCHEMA,
    TASK_REVIEW_SCHEMA,
    TASK_GIT_LOG_SCHEMA,
    TASK_LIST_SCHEMA,
    TASK_PAUSE_SCHEMA,
    TASK_PLAN_SCHEMA,
    TASK_PLAN_UPDATE_SCHEMA,
    TASK_RELATE_SCHEMA,
    TASK_RESUME_SCHEMA,
    TASK_STATUS_SCHEMA,
    TASK_VERIFY_SCHEMA,
    TASK_BRAINSTORM_SCHEMA,
    TASK_DEBUG_SCHEMA,
)

from sagtask.plugin import SagTaskPlugin  # noqa: F401
from sagtask.handlers._lifecycle import (  # noqa: F401
    _handle_sag_task_advance,
    _handle_sag_task_approve,
    _handle_sag_task_create,
    _handle_sag_task_pause,
    _handle_sag_task_resume,
    _handle_sag_task_status,
)
from sagtask.handlers._git import (  # noqa: F401
    _handle_sag_task_branch,
    _handle_sag_task_commit,
    _handle_sag_task_git_log,
    _handle_sag_task_list,
)

from sagtask.handlers._plan import (  # noqa: F401
    _handle_sag_task_plan,
    _handle_sag_task_plan_update,
    _handle_sag_task_relate,
    _handle_sag_task_verify,
    _handle_sag_task_brainstorm,
    _handle_sag_task_debug,
)

from sagtask.handlers._orchestration import (  # noqa: F401
    _handle_sag_task_dispatch,
    _handle_sag_task_review,
)

from sagtask.handlers import _tool_handlers  # noqa: F401

# ── Hook callbacks — re-exported from hooks.py ───────────────────────────────
from sagtask.hooks import _on_pre_llm_call, _on_session_start  # noqa: F401


# Backward-compat: tests do ``sagtask._sagtask_instance = None``.
# Proxied to _utils._sagtask_instance (the single source of truth).
def __getattr__(name: str):
    if name == "_sagtask_instance":
        return _utils._sagtask_instance
    raise AttributeError(name)


def register(ctx) -> None:
    """Register SagTask as a user plugin.

    - Registers task_* tools via ctx.register_tool()
    - Registers pre_llm_call hook for per-turn context injection
    - Registers on_session_start hook for sagtask root initialization
    """
    if _utils._sagtask_instance is not None:
        logger.debug("SagTaskPlugin already registered, skipping")
        return

    _utils._sagtask_instance = SagTaskPlugin()

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
