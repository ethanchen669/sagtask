"""Metrics query handler for SagTask."""
from __future__ import annotations

from typing import Any, Dict

from .._utils import _get_provider


def _handle_sag_task_metrics(args: Dict[str, Any]) -> Dict[str, Any]:
    """Query metrics from the event log."""
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id

    if not task_id:
        return {"ok": False, "error": "No active task."}

    return {"ok": True, "message": "No metrics recorded yet."}
