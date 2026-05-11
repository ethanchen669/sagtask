"""Plan, verify, and relate handlers — including TDD state machine."""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict

from .._utils import (
    _SUBPROCESS_TIMEOUT,
    _VERIFY_OUTPUT_MAX_LEN,
    _get_provider,
    _load_plan,
    _utcnow_iso,
)

logger = logging.getLogger(__name__)

MAX_CROSS_POLLINATION = 2


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


def _handle_sag_task_brainstorm(args: Dict[str, Any]) -> Dict[str, Any]:
    """Build brainstorm context or record design selection."""
    from ._orchestration import _build_brainstorm_context

    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    selected_option = args.get("selected_option")
    design_title = args.get("design_title", "")
    design_description = args.get("design_description", "")

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    step_obj = p._get_current_step_object(state)
    if not step_obj:
        return {"ok": False, "error": "Cannot find current step in task phases."}

    ms = state.get("methodology_state", {})
    current_phase = ms.get("brainstorm_phase", "explore")

    # If recording a selection
    if selected_option is not None:
        if current_phase == "select":
            return {
                "ok": True,
                "sag_task_id": task_id,
                "brainstorm_phase": "select",
                "warning": "Design already selected. Use plan_update to track implementation progress.",
                "message": f"Design option {ms.get('brainstorm_selected')} was already selected.",
            }

        selected_design = {}
        if design_title:
            selected_design = {"title": design_title, "description": design_description}

        state = {
            **state,
            "methodology_state": {
                **ms,
                "brainstorm_phase": "select",
                "brainstorm_selected": selected_option,
                "brainstorm_selected_design": selected_design,
            },
        }
        p.save_task_state(task_id, state)

        return {
            "ok": True,
            "sag_task_id": task_id,
            "brainstorm_phase": "select",
            "selected_option": selected_option,
            "selected_design": selected_design,
            "message": f"Selected design option {selected_option}. Proceed with implementation.",
        }

    # Building brainstorm context (explore phase)
    if current_phase == "explore" and not ms.get("brainstorm_phase"):
        state = {
            **state,
            "methodology_state": {
                **ms,
                "brainstorm_phase": "explore",
            },
        }
        p.save_task_state(task_id, state)

    context = _build_brainstorm_context(step_obj=step_obj, state=state)

    return {
        "ok": True,
        "sag_task_id": task_id,
        "brainstorm_phase": ms.get("brainstorm_phase", "explore"),
        "step_id": step_obj.get("id", "unknown"),
        "context": context,
        "message": "Use this context to generate design options. Call again with selected_option to record choice.",
    }


def _handle_sag_task_debug(args: Dict[str, Any]) -> Dict[str, Any]:
    """Build debug context or record hypothesis/fix."""
    from ._orchestration import _build_debug_context

    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    hypothesis = args.get("hypothesis", "")
    fix_description = args.get("fix_description", "")

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    step_obj = p._get_current_step_object(state)
    if not step_obj:
        return {"ok": False, "error": "Cannot find current step in task phases."}

    ms = state.get("methodology_state", {})

    # Record fix
    if fix_description:
        state = {
            **state,
            "methodology_state": {
                **ms,
                "debug_phase": "fix",
                "debug_fix": fix_description,
            },
        }
        p.save_task_state(task_id, state)
        return {
            "ok": True,
            "sag_task_id": task_id,
            "debug_phase": "fix",
            "fix_description": fix_description,
            "message": "Fix recorded. Run sag_task_verify to validate.",
        }

    # Record hypothesis
    if hypothesis:
        state = {
            **state,
            "methodology_state": {
                **ms,
                "debug_phase": "diagnose",
                "debug_hypothesis": hypothesis,
            },
        }
        p.save_task_state(task_id, state)
        return {
            "ok": True,
            "sag_task_id": task_id,
            "debug_phase": "diagnose",
            "hypothesis": hypothesis,
            "message": "Hypothesis recorded. Verify it, then call with fix_description.",
        }

    # Build debug context
    if not ms.get("debug_phase"):
        state = {
            **state,
            "methodology_state": {
                **ms,
                "debug_phase": "reproduce",
            },
        }
        p.save_task_state(task_id, state)

    context = _build_debug_context(step_obj=step_obj, state=state)

    return {
        "ok": True,
        "sag_task_id": task_id,
        "debug_phase": ms.get("debug_phase", "reproduce"),
        "step_id": step_obj.get("id", "unknown"),
        "context": context,
        "message": "Follow the debug methodology. Record hypothesis or fix as you progress.",
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

    plan = _load_plan(plan_path)
    if not plan:
        return {"ok": False, "error": f"Plan file '{plan_file}' not found or corrupted."}

    subtask = next((s for s in plan["subtasks"] if s["id"] == subtask_id), None)
    if not subtask:
        return {"ok": False, "error": f"Subtask '{subtask_id}' not found in plan."}

    def _update_subtask(s: Dict[str, Any]) -> Dict[str, Any]:
        if s["id"] != subtask_id:
            return s
        updated = {**s, "status": new_status}
        if context:
            existing = s.get("result", "")
            updated["result"] = f"{existing}\n{context}".strip() if existing else context
        return updated

    updated_subtasks = [_update_subtask(s) for s in plan["subtasks"]]
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
