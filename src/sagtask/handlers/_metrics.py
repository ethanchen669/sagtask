"""Metrics query handler for SagTask."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from .._utils import _get_provider

logger = logging.getLogger(__name__)


def _load_events(task_id: str) -> List[Dict[str, Any]]:
    """Load all events from .sag_metrics.jsonl, skipping malformed lines."""
    p = _get_provider()
    task_root = p.get_task_root(task_id)
    metrics_file = task_root / ".sag_metrics.jsonl"
    if not metrics_file.exists():
        return []
    events = []
    for line in metrics_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            logger.debug("Skipping malformed metrics line: %s", line[:80])
    return events


def _filter_by_scope(events: List[Dict[str, Any]], scope: str, state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Filter events by scope (step, phase, or task)."""
    if scope == "task":
        return events
    elif scope == "phase":
        phase_id = state.get("current_phase_id", "")
        return [e for e in events if e.get("phase_id") == phase_id]
    else:  # step (default)
        step_id = state.get("current_step_id", "")
        return [e for e in events if e.get("step_id") == step_id]


def _compute_verification(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute verification stats from verify_run events."""
    verify_events = [e for e in events if e.get("event") == "verify_run"]
    if not verify_events:
        return {}
    total = len(verify_events)
    passed = sum(1 for e in verify_events if e.get("passed"))
    failed = total - passed
    pass_rate = round(passed / total, 2) if total else 0.0
    last_result = "passed" if verify_events[-1].get("passed") else "failed"

    # Compute streak (consecutive same results from the end)
    streak = 0
    last_val = verify_events[-1].get("passed")
    for e in reversed(verify_events):
        if e.get("passed") == last_val:
            streak += 1
        else:
            break
    if not last_val:
        streak = -streak

    return {
        "total_runs": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": pass_rate,
        "last_result": last_result,
        "streak": streak,
    }


def compute_coverage_trend(coverage_values: List[int]) -> str:
    """Compute coverage trend direction from a list of coverage percentages.

    Shared by query handler and context injection to ensure consistency.
    """
    if len(coverage_values) < 3:
        return "stable"
    if len(coverage_values) >= 6:
        recent = sum(coverage_values[-3:]) / 3
        prior = sum(coverage_values[-6:-3]) / 3
    else:
        recent = sum(coverage_values[-3:]) / 3
        prior = sum(coverage_values[:3]) / 3
    if recent - prior > 2:
        return "improving"
    elif recent - prior < -2:
        return "declining"
    return "stable"


def _compute_coverage(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute coverage trend from verify_run events with coverage_pct."""
    coverage_values = [
        e["coverage_pct"] for e in events
        if e.get("event") == "verify_run" and "coverage_pct" in e
    ]
    if not coverage_values:
        return {}

    return {
        "current": coverage_values[-1],
        "history": coverage_values,
        "trend": compute_coverage_trend(coverage_values),
    }


def _compute_throughput(events: List[Dict[str, Any]], plan_total: int = 0) -> Dict[str, Any]:
    """Compute subtask throughput — idempotent by latest state per subtask_id."""
    complete_events = [e for e in events if e.get("event") == "subtask_complete"]
    if not complete_events:
        return {}

    # Track latest status per subtask_id
    latest: Dict[str, str] = {}
    for e in complete_events:
        sid = e.get("subtask_id", "")
        if sid:
            latest[sid] = e.get("new_status", "")

    done = sum(1 for s in latest.values() if s == "done")
    failed = sum(1 for s in latest.values() if s == "failed")
    total = plan_total if plan_total > 0 else len(latest)

    return {
        "subtasks_total": total,
        "subtasks_done": done,
        "subtasks_failed": failed,
    }


def _handle_sag_task_metrics(args: Dict[str, Any]) -> Dict[str, Any]:
    """Query metrics from the event log."""
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    events = _load_events(task_id)
    if not events:
        return {"ok": True, "message": "No metrics recorded yet."}

    scope = args.get("scope", "step")
    metric = args.get("metric", "all")

    filtered = _filter_by_scope(events, scope, state)
    if not filtered:
        return {"ok": True, "message": f"No metrics for scope '{scope}'."}

    result: Dict[str, Any] = {
        "ok": True,
        "scope": scope,
        "step_id": state.get("current_step_id", ""),
    }

    if metric in ("verification", "all"):
        v = _compute_verification(filtered)
        if v:
            result["verification"] = v

    if metric in ("coverage", "all"):
        c = _compute_coverage(filtered)
        if c:
            result["coverage"] = c

    if metric in ("throughput", "all"):
        plan_total = state.get("methodology_state", {}).get("subtask_progress", {}).get("total", 0)
        t = _compute_throughput(filtered, plan_total=plan_total)
        if t:
            result["throughput"] = t

    return result
