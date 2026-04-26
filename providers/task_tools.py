"""Tool implementations for MemTaskProvider."""

from __future__ import annotations

import json
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .. import MemTaskProvider


# ── Task Lifecycle ────────────────────────────────────────────────────────────


def handle_task_create(provider: MemTaskProvider, args: Dict[str, Any]) -> Dict[str, Any]:
    task_id = args["task_id"]
    name = args["name"]
    description = args.get("description", "")
    phases = args.get("phases", [])

    task_root = provider.get_task_root(task_id)
    task_root.mkdir(parents=True, exist_ok=True)

    # Build initial task state
    state = {
        "task_id": task_id,
        "name": name,
        "description": description,
        "status": "active",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "current_phase_id": phases[0]["id"] if phases else "",
        "current_step_id": phases[0]["steps"][0]["id"] if phases and phases[0].get("steps") else "",
        "phases": phases,
        "pending_gates": [],
        "artifacts_summary": "",
        "decisions": [],
        "executions": [],
        "relationships": [],
        "artifact_summaries": [],
    }

    provider.save_task_state(task_id, state)

    # Write .gitignore
    gitignore = provider.get_gitignore_path(task_id)
    gitignore.write_text(
        "task_state.json\nartifacts/\nexecutions/\n__pycache__/\n*.pyc\n"
    )

    # Write task.md (optional, per Q1 decision: default not generated)
    # Generated only if explicitly requested or for important milestones

    # Initialize git repo
    provider.ensure_git_repo(task_id)

    # Create GitHub repo and push initial commit
    provider.create_github_repo(task_id)
    provider.git_push(task_id, branch="main")

    # Set as active task
    provider._set_active_task(task_id)

    return {
        "ok": True,
        "task_id": task_id,
        "name": name,
        "status": "active",
        "current_phase": state["current_phase_id"],
        "current_step": state["current_step_id"],
        "message": f"Task '{name}' created with {len(phases)} phase(s). Git repo initialized.",
    }


def handle_task_status(provider: MemTaskProvider, args: Dict[str, Any]) -> Dict[str, Any]:
    task_id = args.get("task_id") or provider._active_task_id
    verbose = args.get("verbose", False)

    if not task_id:
        return {"ok": False, "error": "No active task. Use task_list to find a task."}

    state = provider.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    current_phase = provider._get_current_phase(state)
    current_step = provider._get_current_step(state)

    result = {
        "ok": True,
        "task_id": task_id,
        "name": state.get("name"),
        "description": state.get("description"),
        "status": state.get("status"),
        "current_phase": current_phase,
        "current_step": current_step,
        "pending_gates": state.get("pending_gates", []),
        "artifacts_summary": state.get("artifacts_summary", ""),
    }

    if verbose:
        result["phases"] = state.get("phases", [])
        result["decisions"] = state.get("decisions", [])

        # Git log
        git_log = provider.git_log(task_id)
        result["git_log"] = git_log

        # Check for paused execution
        task_root = provider.get_task_root(task_id)
        executions_dir = task_root / "executions"
        paused = []
        if executions_dir.exists():
            for f in executions_dir.glob("*.json"):
                data = json.loads(f.read_text())
                if data.get("status") == "paused":
                    paused.append(data.get("execution_id"))
        result["paused_executions"] = paused

    return result


def handle_task_pause(provider: MemTaskProvider, args: Dict[str, Any]) -> Dict[str, Any]:
    task_id = args.get("task_id") or provider._active_task_id
    reason = args.get("reason", "")

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = provider.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    execution_id = f"exec-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    # Build PausedExecutionContext snapshot
    paused_ctx = {
        "execution_id": execution_id,
        "task_id": task_id,
        "status": "paused",
        "paused_at": datetime.utcnow().isoformat() + "Z",
        "reason": reason,
        "gate_id": state.get("current_gate_id", ""),
        "step_id": state.get("current_step_id", ""),
        "phase_id": state.get("current_phase_id", ""),
        "pending_tool_calls": [],  # Filled by the caller before calling task_pause
        "pending_tool_results": [],
        "artifacts_summary": state.get("artifacts_summary", ""),
        "session_context_summary": reason or "Paused by user request",
    }

    # Write snapshot to executions/
    task_root = provider.get_task_root(task_id)
    executions_dir = task_root / "executions"
    executions_dir.mkdir(parents=True, exist_ok=True)
    (executions_dir / f"{execution_id}.json").write_text(
        json.dumps(paused_ctx, indent=2, ensure_ascii=False)
    )

    # Update task state
    state["status"] = "paused"
    state["updated_at"] = datetime.utcnow().isoformat() + "Z"
    state["executions"] = state.get("executions", []) + [execution_id]
    provider.save_task_state(task_id, state)

    return {
        "ok": True,
        "task_id": task_id,
        "execution_id": execution_id,
        "status": "paused",
        "message": f"Task paused. Use task_resume('{task_id}') to continue.",
    }


def handle_task_resume(provider: MemTaskProvider, args: Dict[str, Any]) -> Dict[str, Any]:
    task_id = args.get("task_id") or provider._active_task_id

    if not task_id:
        return {"ok": False, "error": "No active task."}

    task_root = provider.get_task_root(task_id)
    executions_dir = task_root / "executions"

    # Find most recent paused execution
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

    # Restore state
    state = provider.load_task_state(task_id)
    state["status"] = "active"
    state["current_phase_id"] = paused_ctx.get("phase_id", state.get("current_phase_id"))
    state["current_step_id"] = paused_ctx.get("step_id", state.get("current_step_id"))
    state["updated_at"] = datetime.utcnow().isoformat() + "Z"

    # Mark execution as resumed
    paused_ctx["status"] = "resumed"
    paused_ctx["resumed_at"] = datetime.utcnow().isoformat() + "Z"
    (executions_dir / f"{resume_execution_id}.json").write_text(
        json.dumps(paused_ctx, indent=2, ensure_ascii=False)
    )

    provider.save_task_state(task_id, state)
    provider._set_active_task(task_id)

    return {
        "ok": True,
        "task_id": task_id,
        "execution_id": resume_execution_id,
        "status": "active",
        "current_phase": paused_ctx.get("phase_id"),
        "current_step": paused_ctx.get("step_id"),
        "recovery_instruction": paused_ctx.get("session_context_summary", ""),
        "message": f"Task resumed from execution {resume_execution_id}.",
    }


def handle_task_advance(provider: MemTaskProvider, args: Dict[str, Any]) -> Dict[str, Any]:
    task_id = args.get("task_id") or provider._active_task_id
    commit_message = args.get("commit_message", "")
    artifacts_summary = args.get("artifacts_summary", "")

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = provider.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    phases = state.get("phases", [])
    current_phase_id = state.get("current_phase_id", "")
    current_step_id = state.get("current_step_id", "")

    # Find current phase and step index
    phase_idx = next(
        (i for i, p in enumerate(phases) if p.get("id") == current_phase_id), -1
    )
    if phase_idx == -1:
        return {"ok": False, "error": f"Phase '{current_phase_id}' not found."}

    steps = phases[phase_idx].get("steps", [])
    step_idx = next(
        (i for i, s in enumerate(steps) if s.get("id") == current_step_id), -1
    )

    # Determine next step or next phase
    next_phase_id = current_phase_id
    next_step_id = current_step_id

    if step_idx < len(steps) - 1:
        # Next step in same phase
        next_step_id = steps[step_idx + 1]["id"]
    elif phase_idx < len(phases) - 1:
        # First step of next phase
        next_phase_id = phases[phase_idx + 1]["id"]
        next_step_id = phases[phase_idx + 1]["steps"][0]["id"] if phases[phase_idx + 1].get("steps") else ""
    else:
        # Task completed
        state["status"] = "completed"
        state["updated_at"] = datetime.utcnow().isoformat() + "Z"
        provider.save_task_state(task_id, state)
        return {
            "ok": True,
            "task_id": task_id,
            "status": "completed",
            "message": "All phases completed. Task finished!",
        }

    # Commit current work before advancing
    task_root = provider.get_task_root(task_id)
    if (task_root / ".git").exists():
        short_name = current_step_id or "current"
        msg = commit_message or f"WIP: [{short_name}] {steps[step_idx].get('name', '')}"
        try:
            subprocess.run(["git", "add", "-A"], cwd=str(task_root), capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", msg],
                cwd=str(task_root),
                capture_output=True,
                text=True,
            )
        except Exception as e:
            pass  # Non-fatal if git commit fails

    # Update state
    state["current_phase_id"] = next_phase_id
    state["current_step_id"] = next_step_id
    state["updated_at"] = datetime.utcnow().isoformat() + "Z"
    if artifacts_summary:
        state["artifacts_summary"] = artifacts_summary
    provider.save_task_state(task_id, state)

    # Create new branch for the next step
    branch_name = f"step/{next_phase_id}/{next_step_id}"
    provider.git_branch(task_id, branch_name)

    return {
        "ok": True,
        "task_id": task_id,
        "previous_phase": current_phase_id,
        "previous_step": current_step_id,
        "current_phase": next_phase_id,
        "current_step": next_step_id,
        "message": f"Advanced to {next_phase_id}/{next_step_id}. New branch '{branch_name}' created.",
    }


def handle_task_approve(provider: MemTaskProvider, args: Dict[str, Any]) -> Dict[str, Any]:
    task_id = args.get("task_id") or provider._active_task_id
    gate_id = args.get("gate_id")
    decision = args.get("decision")
    comment = args.get("comment", "")

    if not task_id:
        return {"ok": False, "error": "No active task."}
    if not gate_id:
        return {"ok": False, "error": "gate_id is required."}
    if not decision:
        return {"ok": False, "error": "decision is required."}

    state = provider.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    # Record approval decision
    approval_record = {
        "gate_id": gate_id,
        "decision": decision,
        "comment": comment,
        "approved_at": datetime.utcnow().isoformat() + "Z",
    }

    # Remove from pending gates
    pending = [g for g in state.get("pending_gates", []) if g != gate_id]
    state["pending_gates"] = pending
    state["updated_at"] = datetime.utcnow().isoformat() + "Z"
    state["decisions"] = state.get("decisions", []) + [approval_record]
    provider.save_task_state(task_id, state)

    # If approved, advance to next step
    if decision == "Approve":
        return handle_task_advance(provider, {"task_id": task_id, "commit_message": f"[Gate {gate_id}] Approved: {comment}"})

    return {
        "ok": True,
        "task_id": task_id,
        "gate_id": gate_id,
        "decision": decision,
        "message": f"Gate '{gate_id}' recorded as '{decision}'.",
    }


# ── Task Discovery ────────────────────────────────────────────────────────────


def handle_task_list(provider: MemTaskProvider, args: Dict[str, Any]) -> Dict[str, Any]:
    status_filter = args.get("status_filter", "all")
    projects_root = provider._projects_root

    tasks = []
    if not projects_root.exists():
        return {"ok": True, "tasks": []}

    for task_dir in sorted(projects_root.iterdir()):
        if task_dir.is_dir() and not task_dir.name.startswith("."):
            task_id = task_dir.name
            state = provider.load_task_state(task_id)
            if not state:
                continue

            status = state.get("status", "unknown")
            if status_filter != "all" and status != status_filter:
                continue

            tasks.append({
                "task_id": task_id,
                "name": state.get("name"),
                "status": status,
                "current_phase": provider._get_current_phase(state),
                "current_step": provider._get_current_step(state),
                "updated_at": state.get("updated_at", ""),
            })

    return {"ok": True, "tasks": tasks}


# ── Git Operations ────────────────────────────────────────────────────────────


def handle_task_commit(provider: MemTaskProvider, args: Dict[str, Any]) -> Dict[str, Any]:
    task_id = args.get("task_id") or provider._active_task_id
    message = args.get("message", "")

    if not task_id:
        return {"ok": False, "error": "No active task."}

    task_root = provider.get_task_root(task_id)
    git_dir = task_root / ".git"
    if not git_dir.exists():
        return {"ok": False, "error": f"Task '{task_id}' is not a Git repo. Run task_advance to initialize."}

    result = subprocess.run(
        ["git", "add", "-A"],
        cwd=str(task_root),
        capture_output=True,
        text=True,
    )

    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(task_root),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return {"ok": False, "error": f"Git commit failed: {result.stderr}"}

    return {
        "ok": True,
        "task_id": task_id,
        "message": message,
        "commit_hash": result.stdout.strip(),
    }


def handle_task_branch(provider: MemTaskProvider, args: Dict[str, Any]) -> Dict[str, Any]:
    task_id = args.get("task_id") or provider._active_task_id
    branch_name = args.get("branch_name", "")

    if not task_id:
        return {"ok": False, "error": "No active task."}

    if not branch_name:
        # Auto-generate from current step context
        state = provider.load_task_state(task_id)
        if state:
            branch_name = f"step/{state.get('current_phase_id', '?')}/{state.get('current_step_id', '?')}"

    if not branch_name:
        return {"ok": False, "error": "branch_name is required when no active task context."}

    success = provider.git_branch(task_id, branch_name)
    if not success:
        return {"ok": False, "error": f"Failed to create branch '{branch_name}'."}

    return {
        "ok": True,
        "task_id": task_id,
        "branch": branch_name,
        "message": f"Switched to new branch '{branch_name}'.",
    }


def handle_task_git_log(provider: MemTaskProvider, args: Dict[str, Any]) -> Dict[str, Any]:
    task_id = args.get("task_id") or provider._active_task_id
    max_count = args.get("max_count", 20)

    if not task_id:
        return {"ok": False, "error": "No active task."}

    git_log = provider.git_log(task_id, max_count)
    return {
        "ok": True,
        "task_id": task_id,
        "commits": git_log,
    }


# ── Cross-Task Relationships ──────────────────────────────────────────────────

MAX_CROSS_POLLINATION = 2


def handle_task_relate(provider: MemTaskProvider, args: Dict[str, Any]) -> Dict[str, Any]:
    task_id = args.get("task_id") or provider._active_task_id
    related_task_id = args.get("related_task_id")
    relationship = args.get("relationship")
    action = args.get("action")

    if not task_id:
        return {"ok": False, "error": "No active task. Provide task_id explicitly."}
    if not related_task_id:
        return {"ok": False, "error": "related_task_id is required."}
    if not relationship:
        return {"ok": False, "error": "relationship is required."}
    if action not in ("add", "remove"):
        return {"ok": False, "error": "action must be 'add' or 'remove'."}

    state = provider.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    # Verify related task exists
    related_state = provider.load_task_state(related_task_id)
    if not related_state:
        return {"ok": False, "error": f"Related task '{related_task_id}' not found."}

    relationships = state.get("relationships", [])

    if action == "add":
        # Check N≤2 for cross-pollination
        cross_poll_count = sum(
            1 for r in relationships if r.get("relationship") == "cross-pollination"
        )
        if cross_poll_count >= MAX_CROSS_POLLINATION:
            return {
                "ok": False,
                "error": f"Max {MAX_CROSS_POLLINATION} cross-pollination relationships allowed. "
                f"Use task_relate with action='remove' to remove one first.",
            }

        # Avoid duplicate
        existing = [r for r in relationships if r.get("task_id") == related_task_id]
        if existing:
            return {
                "ok": False,
                "error": f"Task '{related_task_id}' is already in the relationships list.",
            }

        relationships.append({
            "task_id": related_task_id,
            "relationship": relationship,
        })

    elif action == "remove":
        before = len(relationships)
        relationships = [
            r for r in relationships if r.get("task_id") != related_task_id
        ]
        if len(relationships) == before:
            return {
                "ok": False,
                "error": f"Task '{related_task_id}' was not in the relationships list.",
            }

    state["relationships"] = relationships
    state["updated_at"] = datetime.utcnow().isoformat() + "Z"
    provider.save_task_state(task_id, state)

    return {
        "ok": True,
        "task_id": task_id,
        "relationship": relationship,
        "related_task_id": related_task_id,
        "action": action,
        "total_relationships": len(relationships),
    }
