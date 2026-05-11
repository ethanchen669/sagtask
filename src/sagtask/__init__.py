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

import json
import logging
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Re-exported from _utils for backward compatibility ────────────────────────
from ._utils import (  # noqa: E402
    SAGTASK_PROVIDER,
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
# Tool handlers — all inlined here (no providers/ subpackage needed)
# Each accesses the singleton via _get_provider()
# ─────────────────────────────────────────────────────────────────────────────

MAX_CROSS_POLLINATION = 2


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
    gitignore.write_text(".sag_task_state.json\n.sag_artifacts/\n.sag_executions/\n__pycache__/\n*.pyc\n")

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


def _handle_sag_task_relate(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    related_task_id = args.get("related_task_id")
    relationship = args.get("relationship")
    action = args.get("action")

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    if action == "list":
        rels = state.get("relationships", [])
        return {"ok": True, "sag_task_id": task_id, "relationships": rels}

    if not related_task_id:
        return {"ok": False, "error": "related_task_id is required."}
    if not relationship:
        return {"ok": False, "error": "relationship is required."}
    if action not in ("add", "remove"):
        return {"ok": False, "error": "action must be 'add' or 'remove'."}

    related_state = p.load_task_state(related_task_id)
    if not related_state:
        return {"ok": False, "error": f"Related task '{related_task_id}' not found."}

    relationships = state.get("relationships", [])

    if action == "add":
        cross_poll_count = sum(1 for r in relationships if r.get("relationship") == "cross-pollination")
        if cross_poll_count >= MAX_CROSS_POLLINATION:
            return {
                "ok": False,
                "error": f"Max {MAX_CROSS_POLLINATION} cross-pollination relationships allowed. "
                f"Use task_relate with action='remove' to remove one first.",
            }
        existing = [r for r in relationships if r.get("sag_task_id") == related_task_id]
        if existing:
            return {"ok": False, "error": f"Task '{related_task_id}' is already in the relationships list."}
        relationships.append({"sag_task_id": related_task_id, "relationship": relationship})

    elif action == "remove":
        before = len(relationships)
        relationships = [r for r in relationships if r.get("sag_task_id") != related_task_id]
        if len(relationships) == before:
            return {"ok": False, "error": f"Task '{related_task_id}' was not in the relationships list."}

    state["relationships"] = relationships
    state["updated_at"] = _utcnow_iso()
    p.save_task_state(task_id, state)

    return {
        "ok": True,
        "sag_task_id": task_id,
        "relationship": relationship,
        "related_task_id": related_task_id,
        "action": action,
        "total_relationships": len(relationships),
    }


def _handle_sag_task_verify(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    step = p._get_current_step_object(state)
    if not step:
        return {"ok": False, "error": "Cannot find current step in task phases."}

    verification = step.get("verification", {})
    commands = verification.get("commands", [])

    if not commands:
        return {
            "ok": True,
            "passed": True,
            "message": "No verification configured for this step.",
        }

    task_root = p.get_task_root(task_id)
    cwd_raw = verification.get("cwd") or str(task_root)
    cwd_path = Path(cwd_raw).resolve()
    try:
        cwd_path.relative_to(task_root.resolve())
    except ValueError:
        return {"ok": False, "error": f"cwd '{cwd_raw}' is outside task root."}
    cwd = str(cwd_path)

    results = []
    all_passed = True

    for cmd in commands:
        logger.warning("sag_task_verify executing: cmd=%r cwd=%s", cmd, cwd)
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=cwd,
                capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
            )
            results.append({
                "command": cmd,
                "exit_code": proc.returncode,
                "stdout": proc.stdout[:_VERIFY_OUTPUT_MAX_LEN],
                "stderr": proc.stderr[:_VERIFY_OUTPUT_MAX_LEN],
            })
            if proc.returncode != 0:
                all_passed = False
        except subprocess.TimeoutExpired:
            results.append({
                "command": cmd,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {_SUBPROCESS_TIMEOUT}s",
            })
            all_passed = False
        except Exception as e:
            results.append({
                "command": cmd,
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
            })
            all_passed = False

    # TDD state machine: auto-transition phase based on verification result
    tdd_phase_update: Dict[str, Any] = {}
    step_obj_for_tdd = p._get_current_step_object(state)
    if step_obj_for_tdd:
        m_type = step_obj_for_tdd.get("methodology", {}).get("type", "none")
        if m_type == "tdd":
            tdd_phase_update["tdd_phase"] = "green" if all_passed else "red"

    state = {
        **state,
        "methodology_state": {
            **state.get("methodology_state", {}),
            "last_verification": {
                "passed": all_passed,
                "timestamp": _utcnow_iso(),
                "results": results,
            },
            **tdd_phase_update,
        },
    }
    p.save_task_state(task_id, state)

    return {
        "ok": True,
        "passed": all_passed,
        "results": results,
        "message": f"Verification {'passed' if all_passed else 'failed'} ({len(results)} commands).",
    }


def _handle_sag_task_plan(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    granularity = args.get("granularity", "medium")

    valid_granularities = {"fine", "medium", "coarse"}
    if granularity not in valid_granularities:
        return {"ok": False, "error": f"Invalid granularity '{granularity}'. Must be one of: {', '.join(sorted(valid_granularities))}"}

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    step_obj = p._get_current_step_object(state)
    if not step_obj:
        return {"ok": False, "error": "Cannot find current step in task phases."}

    step_id = step_obj.get("id", "unknown")
    task_root = p.get_task_root(task_id)
    plans_dir = task_root / ".sag_plans"
    plan_path = plans_dir / f"{step_id}.json"

    if plan_path.exists():
        return {"ok": False, "error": f"Plan already exists for step '{step_id}'. Delete it first or use plan_update."}

    plan = p._generate_plan(step_obj, granularity)
    plans_dir.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False))

    total = len(plan["subtasks"])
    state = {
        **state,
        "methodology_state": {
            **state.get("methodology_state", {}),
            "plan_file": f".sag_plans/{step_id}.json",
            "subtask_progress": {"total": total, "completed": 0, "in_progress": 0},
        },
    }
    p.save_task_state(task_id, state)

    return {
        "ok": True,
        "sag_task_id": task_id,
        "step_id": step_id,
        "plan_file": f".sag_plans/{step_id}.json",
        "total_subtasks": total,
        "subtasks": [{"id": st["id"], "title": st["title"]} for st in plan["subtasks"]],
        "message": f"Plan generated with {total} subtasks for step '{step_id}'.",
    }


def _handle_sag_task_plan_update(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    subtask_id = args.get("subtask_id", "")
    new_status = args.get("status", "")
    context = args.get("context")

    if not task_id:
        return {"ok": False, "error": "No active task."}

    valid_statuses = {"pending", "in_progress", "done", "failed"}
    if new_status not in valid_statuses:
        return {
            "ok": False,
            "error": f"Invalid status '{new_status}'. Must be one of: {', '.join(sorted(valid_statuses))}",
        }

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    ms = state.get("methodology_state", {})
    plan_file = ms.get("plan_file")
    if not plan_file:
        return {"ok": False, "error": "No plan found for current step. Run sag_task_plan first."}

    task_root = p.get_task_root(task_id)
    plan_path = (task_root / plan_file).resolve()
    try:
        plan_path.relative_to(task_root.resolve())
    except ValueError:
        return {"ok": False, "error": f"Plan path '{plan_file}' is outside task root."}
    if not plan_path.exists():
        return {"ok": False, "error": f"Plan file '{plan_file}' not found on disk."}

    try:
        plan = json.loads(plan_path.read_text())
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"Plan file '{plan_file}' is corrupted: {e}"}

    subtask = next((s for s in plan["subtasks"] if s["id"] == subtask_id), None)
    if not subtask:
        return {"ok": False, "error": f"Subtask '{subtask_id}' not found in plan."}

    updated_subtasks = [
        {**s, "status": new_status, **(({"result": context}) if context else {})}
        if s["id"] == subtask_id else s
        for s in plan["subtasks"]
    ]
    plan = {**plan, "subtasks": updated_subtasks}

    # Atomic write: temp file then os.replace
    tmp_path = plan_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False))
    os.replace(str(tmp_path), str(plan_path))

    # Sync progress counts
    subtasks = plan["subtasks"]
    total = len(subtasks)
    completed = sum(1 for s in subtasks if s["status"] == "done")
    in_progress = sum(1 for s in subtasks if s["status"] == "in_progress")

    state = {
        **state,
        "methodology_state": {
            **ms,
            "subtask_progress": {
                "total": total,
                "completed": completed,
                "in_progress": in_progress,
            },
        },
    }
    p.save_task_state(task_id, state)

    return {
        "ok": True,
        "sag_task_id": task_id,
        "subtask_id": subtask_id,
        "status": new_status,
        "progress": {"total": total, "completed": completed, "in_progress": in_progress},
        "message": f"Subtask '{subtask_id}' -> {new_status}. Progress: {completed}/{total}.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Handler dispatch map — used by register() to call ctx.register_tool()
# ─────────────────────────────────────────────────────────────────────────────

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
