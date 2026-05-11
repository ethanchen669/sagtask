"""SagTask tool handlers."""
from __future__ import annotations

from ._lifecycle import (
    _handle_sag_task_advance,
    _handle_sag_task_approve,
    _handle_sag_task_create,
    _handle_sag_task_pause,
    _handle_sag_task_resume,
    _handle_sag_task_status,
)
from ._git import (
    _handle_sag_task_branch,
    _handle_sag_task_commit,
    _handle_sag_task_git_log,
    _handle_sag_task_list,
)
from ._plan import (
    _handle_sag_task_plan,
    _handle_sag_task_plan_update,
    _handle_sag_task_relate,
    _handle_sag_task_verify,
)

_tool_handlers = {
    "sag_task_create": _handle_sag_task_create,
    "sag_task_status": _handle_sag_task_status,
    "sag_task_pause": _handle_sag_task_pause,
    "sag_task_resume": _handle_sag_task_resume,
    "sag_task_advance": _handle_sag_task_advance,
    "sag_task_approve": _handle_sag_task_approve,
    "sag_task_list": _handle_sag_task_list,
    "sag_task_commit": _handle_sag_task_commit,
    "sag_task_branch": _handle_sag_task_branch,
    "sag_task_git_log": _handle_sag_task_git_log,
    "sag_task_relate": _handle_sag_task_relate,
    "sag_task_verify": _handle_sag_task_verify,
    "sag_task_plan": _handle_sag_task_plan,
    "sag_task_plan_update": _handle_sag_task_plan_update,
}

__all__ = [
    "_tool_handlers",
    "_handle_sag_task_create",
    "_handle_sag_task_status",
    "_handle_sag_task_pause",
    "_handle_sag_task_resume",
    "_handle_sag_task_advance",
    "_handle_sag_task_approve",
    "_handle_sag_task_list",
    "_handle_sag_task_commit",
    "_handle_sag_task_branch",
    "_handle_sag_task_git_log",
    "_handle_sag_task_relate",
    "_handle_sag_task_verify",
    "_handle_sag_task_plan",
    "_handle_sag_task_plan_update",
]
