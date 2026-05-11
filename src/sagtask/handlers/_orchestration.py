"""Orchestration handlers -- dispatch and review for subtask execution."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from .._utils import _get_provider, _utcnow_iso

logger = logging.getLogger(__name__)

# -- Methodology instruction templates -------------------------------------------

_METHODOLOGY_INSTRUCTIONS: Dict[str, str] = {
    "tdd": (
        "## TDD Methodology\n"
        "Follow test-driven development:\n"
        "1. RED: Write a failing test that captures the expected behavior\n"
        "2. GREEN: Write the minimal code to make the test pass\n"
        "3. REFACTOR: Clean up while keeping tests green\n"
        "Run tests frequently. Commit after each green phase."
    ),
    "brainstorm": (
        "## Brainstorm Methodology\n"
        "1. Explore multiple design options (at least 3)\n"
        "2. Evaluate trade-offs for each option\n"
        "3. Select the best approach and document the rationale\n"
        "4. Implement the selected design"
    ),
    "debug": (
        "## Debug Methodology\n"
        "1. Reproduce the issue with a minimal test case\n"
        "2. Identify the root cause (not just symptoms)\n"
        "3. Fix the root cause, not the symptom\n"
        "4. Verify the fix and check for regressions"
    ),
    "plan-execute": (
        "## Plan-Execute Methodology\n"
        "1. Plan: Break the work into small steps\n"
        "2. Review: Verify the plan covers all requirements\n"
        "3. Execute: Implement each step, testing as you go\n"
        "4. Verify: Confirm all requirements are met"
    ),
}


def _load_plan(plan_path: Path) -> Optional[Dict[str, Any]]:
    """Load and return plan JSON, or None on error."""
    if not plan_path.exists():
        return None
    try:
        return json.loads(plan_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _build_dispatch_context(
    subtask: Dict[str, Any],
    step_obj: Dict[str, Any],
    methodology: str,
    task_root: str,
    plan: Dict[str, Any],
) -> str:
    """Build a self-contained context prompt for a subagent dispatch."""
    lines = [
        f"## Subtask Dispatch: {subtask['title']}",
        "",
        f"**Subtask ID:** {subtask['id']}",
        f"**Task root:** `{task_root}`",
        "",
        "### Subtask Details",
        f"- Title: {subtask['title']}",
    ]

    if subtask.get("context"):
        lines.append(f"- Context: {subtask['context']}")

    if subtask.get("result"):
        lines.append(f"- Previous result: {subtask['result']}")

    step_name = step_obj.get("name", "Unknown Step")
    step_desc = step_obj.get("description", "")
    lines.extend([
        "",
        "### Parent Step",
        f"- Step: {step_name}",
    ])
    if step_desc:
        lines.append(f"- Description: {step_desc}")

    instructions = _METHODOLOGY_INSTRUCTIONS.get(methodology)
    if instructions:
        lines.extend(["", instructions])

    verification = step_obj.get("verification", {})
    commands = verification.get("commands", [])
    if commands:
        lines.extend([
            "",
            "### Verification",
            "Run these commands to verify your work:",
            *[f"```bash\n{cmd}\n```" for cmd in commands],
        ])

    depends_on = subtask.get("depends_on", [])
    if depends_on:
        lines.extend(["", "### Dependencies"])
        for dep_id in depends_on:
            dep_st = next((s for s in plan["subtasks"] if s["id"] == dep_id), None)
            if dep_st:
                dep_status = dep_st.get("status", "unknown")
                dep_title = dep_st.get("title", dep_id)
                status_icon = "done" if dep_status == "done" else "pending"
                lines.append(f"- [{status_icon}] {dep_id}: {dep_title}")
            else:
                lines.append(f"- [?] {dep_id}: not found in plan")

    siblings = [s for s in plan["subtasks"] if s["id"] != subtask["id"]]
    if siblings:
        lines.extend(["", "### Other Subtasks (for context)"])
        for s in siblings:
            icon = (
                "done" if s["status"] == "done"
                else "in_progress" if s["status"] == "in_progress"
                else "pending"
            )
            lines.append(f"- [{icon}] {s['id']}: {s['title']}")

    return "\n".join(lines)


def _handle_sag_task_dispatch(args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch a subtask for execution by building subagent context."""
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    subtask_id = args.get("subtask_id", "")

    if not task_id:
        return {"ok": False, "error": "No active task."}
    if not subtask_id:
        return {"ok": False, "error": "subtask_id is required."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    ms = state.get("methodology_state", {})
    plan_file = ms.get("plan_file")
    if not plan_file:
        return {"ok": False, "error": "No plan found. Run sag_task_plan first."}

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

    if subtask["status"] == "done":
        return {"ok": False, "error": f"Subtask '{subtask_id}' is already done. Use plan_update to reopen."}

    was_in_progress = subtask["status"] == "in_progress"
    updated_subtasks = [
        {**s, "status": "in_progress"} if s["id"] == subtask_id else s
        for s in plan["subtasks"]
    ]
    plan = {**plan, "subtasks": updated_subtasks}

    tmp_path = plan_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False))
    os.replace(str(tmp_path), str(plan_path))

    total = len(plan["subtasks"])
    completed = sum(1 for s in plan["subtasks"] if s["status"] == "done")
    in_progress = sum(1 for s in plan["subtasks"] if s["status"] == "in_progress")
    state = {
        **state,
        "methodology_state": {
            **ms,
            "subtask_progress": {"total": total, "completed": completed, "in_progress": in_progress},
        },
    }
    p.save_task_state(task_id, state)

    step_obj = p._get_current_step_object(state)
    methodology = ms.get("current_methodology", plan.get("methodology", "none"))
    context = _build_dispatch_context(
        subtask=next(s for s in plan["subtasks"] if s["id"] == subtask_id),
        step_obj=step_obj or {},
        methodology=methodology,
        task_root=str(task_root),
        plan=plan,
    )

    result: Dict[str, Any] = {
        "ok": True,
        "sag_task_id": task_id,
        "subtask_id": subtask_id,
        "task_root": str(task_root),
        "context": context,
        "message": f"Dispatched subtask '{subtask_id}'. Use the context to execute with a subagent.",
    }
    if was_in_progress:
        result["warning"] = f"Subtask '{subtask_id}' was already in-progress. Re-dispatched."
        result["message"] = f"Re-dispatched subtask '{subtask_id}'."

    return result
