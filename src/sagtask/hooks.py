"""Hook callbacks for SagTask — registered via ctx.register_hook()."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from ._utils import _get_provider

logger = logging.getLogger(__name__)


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
