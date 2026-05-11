"""Git operation handlers — list, commit, branch, git_log."""
from __future__ import annotations

import json
import logging
import subprocess
from typing import Any, Dict

from .._utils import (
    _SUBPROCESS_TIMEOUT,
    _get_provider,
    _utcnow_iso,
)

logger = logging.getLogger(__name__)


def _handle_sag_task_list(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    status_filter = args.get("status_filter", "all")
    projects_root = p._projects_root

    tasks = []
    if not projects_root.exists():
        return {"ok": True, "tasks": []}

    for task_dir in sorted(projects_root.iterdir()):
        if task_dir.is_dir() and not task_dir.name.startswith("."):
            task_id = task_dir.name
            state = p.load_task_state(task_id)
            if not state:
                continue
            status = state.get("status", "unknown")
            if status_filter != "all" and status != status_filter:
                continue
            tasks.append({
                "sag_task_id": task_id,
                "name": state.get("name"),
                "status": status,
                "current_phase": p._get_current_phase(state),
                "current_step": p._get_current_step(state),
                "updated_at": state.get("updated_at", ""),
            })

    return {"ok": True, "tasks": tasks}


def _handle_sag_task_commit(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    message = args.get("message", "")

    if not task_id:
        return {"ok": False, "error": "No active task."}

    task_root = p.get_task_root(task_id)
    git_dir = task_root / ".git"
    if not git_dir.exists():
        return {"ok": False, "error": f"Task '{task_id}' is not a Git repo. Run task_advance to initialize."}

    subprocess.run(["git", "add", "-A"], cwd=str(task_root), capture_output=True, timeout=_SUBPROCESS_TIMEOUT)
    result = subprocess.run(["git", "commit", "-m", message], cwd=str(task_root), capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)

    if result.returncode != 0:
        return {"ok": False, "error": f"Git commit failed: {result.stderr}"}

    return {
        "ok": True,
        "sag_task_id": task_id,
        "message": message,
        "commit_hash": result.stdout.strip(),
    }


def _handle_sag_task_branch(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    branch_name = args.get("branch_name")

    if not task_id:
        return {"ok": False, "error": "No active task."}

    if not branch_name:
        state = p.load_task_state(task_id)
        if not state:
            return {"ok": False, "error": f"Task '{task_id}' not found."}
        branch_name = f"step/{state.get('current_phase_id')}/{state.get('current_step_id')}"

    success = p.git_branch(task_id, branch_name)
    if not success:
        return {"ok": False, "error": f"Failed to create branch '{branch_name}'."}

    return {
        "ok": True,
        "sag_task_id": task_id,
        "branch_name": branch_name,
        "message": f"Branch '{branch_name}' created and checked out.",
    }


def _handle_sag_task_git_log(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    max_count = args.get("max_count", 20)

    if not task_id:
        return {"ok": False, "error": "No active task."}

    log = p.git_log(task_id, max_count=max_count)
    return {"ok": True, "sag_task_id": task_id, "commits": log}
