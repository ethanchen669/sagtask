"""Lifecycle handlers — create, status, pause, resume, advance, approve."""
from __future__ import annotations

import json
import logging
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from .._utils import (
    SCHEMA_VERSION,
    _SUBPROCESS_TIMEOUT,
    _get_provider,
    _utcnow_iso,
    _validate_task_id,
)

logger = logging.getLogger(__name__)


def _handle_sag_task_create(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args["sag_task_id"]
    validation_err = _validate_task_id(task_id)
    if validation_err:
        return {"ok": False, "error": validation_err}
    name = args["name"]
    description = args.get("description", "")
    phases = args.get("phases", [])

    task_root = p.get_task_root(task_id)
    task_root.mkdir(parents=True, exist_ok=True)

    # Determine initial methodology from first step's methodology config
    first_step = (phases[0]["steps"][0] if phases and phases[0].get("steps") else None) or {}
    first_methodology = first_step.get("methodology", {})
    initial_methodology = first_methodology.get("type", "none") if first_methodology else "none"

    state = {
        "sag_task_id": task_id,
        "name": name,
        "description": description,
        "status": "active",
        "created_at": _utcnow_iso(),
        "updated_at": _utcnow_iso(),
        "current_phase_id": phases[0]["id"] if phases else "",
        "current_step_id": phases[0]["steps"][0]["id"] if phases and phases[0].get("steps") else "",
        "phases": phases,
        "pending_gates": [],
        "artifacts_summary": "",
        "decisions": [],
        "executions": [],
        "relationships": [],
        "artifact_summaries": [],
        "schema_version": SCHEMA_VERSION,
        "methodology_state": {
            "current_methodology": initial_methodology,
            "tdd_phase": None,
            "plan_file": None,
            "subtask_progress": {"total": 0, "completed": 0, "in_progress": 0},
            "last_verification": None,
            "review_state": None,
        },
    }

    p.save_task_state(task_id, state)

    gitignore = p.get_gitignore_path(task_id)
    gitignore.write_text(".sag_task_state.json\n.sag_artifacts/\n.sag_executions/\n.sag_worktrees/\n__pycache__/\n*.pyc\n")

    p.ensure_git_repo(task_id)
    p.create_github_repo(task_id)
    p.git_push(task_id, branch="main")
    p._set_active_task(task_id)

    return {
        "ok": True,
        "sag_task_id": task_id,
        "name": name,
        "status": "active",
        "current_phase": state["current_phase_id"],
        "current_step": state["current_step_id"],
        "message": f"Task '{name}' created with {len(phases)} phase(s). Git repo initialized.",
    }


def _handle_sag_task_status(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    verbose = args.get("verbose", False)

    if not task_id:
        return {"ok": False, "error": "No active sag long term task. Use sag_task_list to find a sag long term task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    current_phase = p._get_current_phase(state)
    current_step = p._get_current_step(state)

    result = {
        "ok": True,
        "sag_task_id": task_id,
        "name": state.get("name"),
        "description": state.get("description"),
        "status": state.get("status"),
        "current_phase": current_phase,
        "current_step": current_step,
        "pending_gates": state.get("pending_gates", []),
        "artifacts_summary": state.get("artifacts_summary", ""),
        "relationships": state.get("relationships", []),
        "artifact_summaries": state.get("artifact_summaries", []),
    }

    if verbose:
        result["phases"] = state.get("phases", [])
        result["decisions"] = state.get("decisions", [])
        result["git_log"] = p.git_log(task_id)

        task_root = p.get_task_root(task_id)
        executions_dir = task_root / ".sag_executions"
        paused = []
        if executions_dir.exists():
            for f in executions_dir.glob("*.json"):
                data = json.loads(f.read_text())
                if data.get("status") == "paused":
                    paused.append(data.get("execution_id"))
        result["paused_executions"] = paused

    return result


def _handle_sag_task_pause(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    reason = args.get("reason", "")

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    execution_id = f"exec-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    paused_ctx = {
        "execution_id": execution_id,
        "sag_task_id": task_id,
        "status": "paused",
        "paused_at": _utcnow_iso(),
        "reason": reason,
        "gate_id": state.get("current_gate_id", ""),
        "step_id": state.get("current_step_id", ""),
        "phase_id": state.get("current_phase_id", ""),
        "pending_tool_calls": [],
        "pending_tool_results": [],
        "artifacts_summary": state.get("artifacts_summary", ""),
        "session_context_summary": reason or "Paused by user request",
    }

    task_root = p.get_task_root(task_id)
    executions_dir = task_root / ".sag_executions"
    executions_dir.mkdir(parents=True, exist_ok=True)
    (executions_dir / f"{execution_id}.json").write_text(json.dumps(paused_ctx, indent=2, ensure_ascii=False))

    state = {
        **state,
        "status": "paused",
        "updated_at": _utcnow_iso(),
        "executions": [*state.get("executions", []), execution_id],
    }
    p.save_task_state(task_id, state)

    return {
        "ok": True,
        "sag_task_id": task_id,
        "execution_id": execution_id,
        "status": "paused",
        "message": f"Task paused. Use task_resume('{task_id}') to continue.",
    }


def _handle_sag_task_resume(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id

    if not task_id:
        return {"ok": False, "error": "No active task."}

    task_root = p.get_task_root(task_id)
    executions_dir = task_root / ".sag_executions"

    if not executions_dir.exists():
        return {"ok": False, "error": f"No paused executions found for task '{task_id}'."}

    paused_files = sorted(executions_dir.glob("*.json"), reverse=True)
    paused_ctx = None
    resume_execution_id = None
    for f in paused_files:
        data = json.loads(f.read_text())
        if data.get("status") == "paused":
            paused_ctx = data
            resume_execution_id = f.stem
            break

    if not paused_ctx:
        return {"ok": False, "error": "No paused execution found."}

    state = p.load_task_state(task_id)
    state = {
        **state,
        "status": "active",
        "current_phase_id": paused_ctx.get("phase_id", state.get("current_phase_id")),
        "current_step_id": paused_ctx.get("step_id", state.get("current_step_id")),
        "updated_at": _utcnow_iso(),
    }

    paused_ctx["status"] = "resumed"
    paused_ctx["resumed_at"] = _utcnow_iso()
    (executions_dir / f"{resume_execution_id}.json").write_text(json.dumps(paused_ctx, indent=2, ensure_ascii=False))

    p.save_task_state(task_id, state)
    p._set_active_task(task_id)

    return {
        "ok": True,
        "sag_task_id": task_id,
        "execution_id": resume_execution_id,
        "status": "active",
        "current_phase": paused_ctx.get("phase_id"),
        "current_step": paused_ctx.get("step_id"),
        "recovery_instruction": paused_ctx.get("session_context_summary", ""),
        "message": f"Task resumed from execution {resume_execution_id}.",
    }


def _handle_sag_task_advance(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    commit_message = args.get("commit_message", "")
    artifacts_summary = args.get("artifacts_summary", "")

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    # Check verification requirements before advancing
    step_obj = p._get_current_step_object(state)
    if step_obj:
        verification = step_obj.get("verification", {})
        if verification.get("must_pass", False):
            ms = state.get("methodology_state", {})
            last_v = ms.get("last_verification")
            if not last_v or not last_v.get("passed", False):
                return {
                    "ok": False,
                    "error": "Verification not passed. Run sag_task_verify before advancing.",
                    "last_verification": last_v,
                }

    # Reset tdd_phase on advance (step completed)
    ms = state.get("methodology_state", {})
    if ms.get("tdd_phase"):
        state = {
            **state,
            "methodology_state": {**ms, "tdd_phase": None},
        }

    phases = state.get("phases", [])
    current_phase_id = state.get("current_phase_id", "")
    current_step_id = state.get("current_step_id", "")

    phase_idx = next((i for i, ph in enumerate(phases) if ph.get("id") == current_phase_id), -1)
    if phase_idx == -1:
        return {"ok": False, "error": f"Phase '{current_phase_id}' not found."}

    steps = phases[phase_idx].get("steps", [])
    step_idx = next((i for i, s in enumerate(steps) if s.get("id") == current_step_id), -1)

    next_phase_id = current_phase_id
    next_step_id = current_step_id

    if step_idx < len(steps) - 1:
        next_step_id = steps[step_idx + 1]["id"]
    elif phase_idx < len(phases) - 1:
        next_phase_id = phases[phase_idx + 1]["id"]
        next_step_id = phases[phase_idx + 1]["steps"][0]["id"] if phases[phase_idx + 1].get("steps") else ""
    else:
        state = {
            **state,
            "status": "completed",
            "updated_at": _utcnow_iso(),
        }
        p.save_task_state(task_id, state)
        return {
            "ok": True,
            "sag_task_id": task_id,
            "status": "completed",
            "message": "All phases completed. Task finished!",
        }

    task_root = p.get_task_root(task_id)

    if (task_root / ".git").exists():
        short_name = current_step_id or "current"
        msg = commit_message or f"WIP: [{short_name}] {steps[step_idx].get('name', '')}"
        try:
            subprocess.run(["git", "add", "-A"], cwd=str(task_root), capture_output=True, timeout=_SUBPROCESS_TIMEOUT)
            subprocess.run(["git", "commit", "-m", msg], cwd=str(task_root), capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)
        except Exception as e:
            logger.warning("Git commit failed for task %s: %s", task_id, e)

    # Auto-generate artifact_summaries from git diff (if not manually provided)
    # Runs AFTER git commit so git diff HEAD~1..HEAD captures this step's changes
    if not artifacts_summary:
        auto_summaries = p._generate_artifact_summaries(task_id, force=True)
        if auto_summaries:
            artifacts_summary = "; ".join(
                f"{s['path']}: {s['summary']}" for s in auto_summaries[:3]
            )

    state = {
        **state,
        "current_phase_id": next_phase_id,
        "current_step_id": next_step_id,
        "updated_at": _utcnow_iso(),
        **({"artifacts_summary": artifacts_summary} if artifacts_summary else {}),
    }
    p.save_task_state(task_id, state)

    branch_name = f"step/{next_phase_id}/{next_step_id}"
    p.git_branch(task_id, branch_name)

    return {
        "ok": True,
        "sag_task_id": task_id,
        "previous_phase": current_phase_id,
        "previous_step": current_step_id,
        "current_phase": next_phase_id,
        "current_step": next_step_id,
        "message": f"Advanced to {next_phase_id}/{next_step_id}. New branch '{branch_name}' created.",
    }


def _handle_sag_task_approve(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    gate_id = args.get("gate_id")
    decision = args.get("decision")
    comment = args.get("comment", "")

    if not task_id:
        return {"ok": False, "error": "No active task."}
    if not gate_id:
        return {"ok": False, "error": "gate_id is required."}
    if not decision:
        return {"ok": False, "error": "decision is required."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    approval_record = {
        "gate_id": gate_id,
        "decision": decision,
        "comment": comment,
        "approved_at": _utcnow_iso(),
    }

    pending = [g for g in state.get("pending_gates", []) if g != gate_id]
    state["pending_gates"] = pending
    state["updated_at"] = _utcnow_iso()
    state["decisions"] = state.get("decisions", []) + [approval_record]
    p.save_task_state(task_id, state)

    if decision == "Approve":
        return _handle_sag_task_advance({"sag_task_id": task_id, "commit_message": f"[Gate {gate_id}] Approved: {comment}"})

    return {
        "ok": True,
        "sag_task_id": task_id,
        "gate_id": gate_id,
        "decision": decision,
        "message": f"Gate '{gate_id}' recorded as '{decision}'.",
    }
