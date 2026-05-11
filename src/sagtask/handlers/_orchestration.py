"""Orchestration handlers -- dispatch and review for subtask execution."""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from .._utils import _get_provider, _load_plan, _utcnow_iso

logger = logging.getLogger(__name__)

# Debug phase constants
DEBUG_PHASE_REPRODUCE = "reproduce"
DEBUG_PHASE_DIAGNOSE = "diagnose"
DEBUG_PHASE_FIX = "fix"

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


def _build_dispatch_context(
    subtask: Dict[str, Any],
    step_obj: Dict[str, Any],
    methodology: str,
    task_root: str,
    plan: Dict[str, Any],
    max_context_len: int = 0,
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

    context = "\n".join(lines)
    if max_context_len > 0 and len(context) > max_context_len:
        context = context[:max_context_len] + "\n\n... (truncated)"
    return context


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
        {**s, "status": "in_progress", "dispatched_at": _utcnow_iso()} if s["id"] == subtask_id else s
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

    # Create worktree if requested
    worktree_path = None
    use_worktree = args.get("use_worktree", False)
    if use_worktree:
        worktree_path = p.create_worktree(task_id, subtask_id)
        if not worktree_path:
            return {"ok": False, "error": f"Failed to create worktree for subtask '{subtask_id}'."}

    step_obj = p._get_current_step_object(state)
    methodology = ms.get("current_methodology", plan.get("methodology", "none"))
    max_context_len = args.get("max_context_len", 0)
    context = _build_dispatch_context(
        subtask=next(s for s in plan["subtasks"] if s["id"] == subtask_id),
        step_obj=step_obj or {},
        methodology=methodology,
        task_root=str(task_root),
        plan=plan,
        max_context_len=max_context_len,
    )

    result: Dict[str, Any] = {
        "ok": True,
        "sag_task_id": task_id,
        "subtask_id": subtask_id,
        "task_root": str(task_root),
        "context": context,
        "message": f"Dispatched subtask '{subtask_id}'. Use the context to execute with a subagent.",
    }
    if worktree_path:
        result["worktree_path"] = str(worktree_path)
        result["message"] = f"Dispatched subtask '{subtask_id}' in worktree. Use the worktree path for isolated execution."
    if was_in_progress:
        result["warning"] = f"Subtask '{subtask_id}' was already in-progress. Re-dispatched."
        result["message"] = f"Re-dispatched subtask '{subtask_id}'."

    # Warn if dependencies are not done
    unfinished_deps = [
        d for d in subtask.get("depends_on", [])
        if any(s["id"] == d and s["status"] != "done" for s in plan["subtasks"])
    ]
    if unfinished_deps:
        dep_warning = f"Dependencies not done: {unfinished_deps}"
        existing = result.get("warning", "")
        result["warning"] = f"{existing}; {dep_warning}" if existing else dep_warning

    return result


# -- Review context builder -----------------------------------------------------


def _build_review_context(
    step_obj: Dict[str, Any],
    scope: str,
    state: Dict[str, Any],
    phase_name: str = "",
    phase_obj: Optional[Dict[str, Any]] = None,
) -> str:
    """Build a structured review prompt."""
    step_name = step_obj.get("name", "Unknown Step")
    step_desc = step_obj.get("description", "")

    lines = [
        f"## Code Review: {phase_name + ': ' if phase_name else ''}{step_name}",
        f"**Scope:** {scope}",
        "",
        "### Stage 1: Spec Compliance",
        "Verify the implementation matches the requirements:",
    ]

    if step_desc:
        lines.append(f"- Requirement: {step_desc}")

    verification = step_obj.get("verification", {})
    commands = verification.get("commands", [])
    if commands:
        lines.append("- Verification commands:")
        for cmd in commands:
            lines.append(f"  ```bash\n  {cmd}\n  ```")

    must_pass = verification.get("must_pass", False)
    if must_pass:
        lines.append("- **MUST PASS** before advancing")

    # Phase/full scope: show all steps in the phase
    if scope in ("phase", "full") and phase_obj:
        phase_steps = phase_obj.get("steps", [])
        if phase_steps:
            lines.extend(["", f"### Phase Overview: {phase_obj.get('name', '')}"])
            for s in phase_steps:
                lines.append(f"- {s['id']}: {s.get('name', '')}")

    # Full scope: show all phases
    if scope == "full":
        phases = state.get("phases", [])
        if len(phases) > 1:
            lines.extend(["", "### All Phases"])
            for ph in phases:
                lines.append(f"- {ph['id']}: {ph.get('name', '')} ({len(ph.get('steps', []))} steps)")

    methodology = step_obj.get("methodology", {}).get("type", "none")
    lines.extend(["", "### Stage 2: Code Quality"])

    if methodology == "tdd":
        lines.extend([
            "Check TDD compliance:",
            "- Tests exist for new functionality",
            "- Tests were written before implementation",
            "- Coverage meets threshold",
            "- Code is readable and well-named",
        ])
    elif methodology == "brainstorm":
        lines.extend([
            "Check design quality:",
            "- Design rationale is documented",
            "- Trade-offs are explicitly stated",
            "- Implementation matches selected design",
        ])
    else:
        lines.extend([
            "General quality checks:",
            "- Code is readable and well-named",
            "- Functions are focused (<50 lines)",
            "- Error handling is explicit",
            "- Tests exist for new functionality",
        ])

    lines.extend([
        "",
        "### Review Severity Levels",
        "| Level | Meaning | Action |",
        "|-------|---------|--------|",
        "| CRITICAL | Security vulnerability or data loss | BLOCK |",
        "| HIGH | Bug or significant quality issue | WARN |",
        "| MEDIUM | Maintainability concern | INFO |",
        "| LOW | Style or minor suggestion | NOTE |",
    ])

    return "\n".join(lines)


# -- Brainstorm context builder -------------------------------------------------


def _build_brainstorm_context(
    step_obj: Dict[str, Any],
    state: Dict[str, Any],
) -> str:
    """Build a structured brainstorm prompt for design exploration."""
    step_name = step_obj.get("name", "Unknown Step")
    step_desc = step_obj.get("description", "")

    lines = [
        f"## Design Brainstorm: {step_name}",
        "",
        "### Step Requirements",
    ]
    if step_desc:
        lines.append(f"- {step_desc}")
    else:
        lines.append(f"- {step_name}")

    methodology_config = step_obj.get("methodology", {}).get("config", {})
    min_options = methodology_config.get("min_options", 3)

    lines.extend([
        "",
        "### Instructions",
        f"Generate at least {min_options} distinct design options for this step.",
        "",
        "For each option, provide:",
        "- **Title**: A concise name for the design approach",
        "- **Description**: 2-3 sentences explaining the approach",
        "- **Trade-offs**: Pros and cons of this approach",
        "",
        "Present options as a numbered list. After presenting, ask the user to select one.",
        "",
        "### Design Evaluation Criteria",
        "- Simplicity: Is the approach easy to understand and maintain?",
        "- Correctness: Does it handle all requirements and edge cases?",
        "- Performance: Are there any performance concerns?",
        "- Extensibility: Can the design accommodate future changes?",
    ])

    verification = step_obj.get("verification", {})
    commands = verification.get("commands", [])
    if commands:
        lines.extend([
            "",
            "### Verification",
            "After implementation, these commands must pass:",
            *[f"```bash\n{cmd}\n```" for cmd in commands],
        ])

    return "\n".join(lines)


# -- Debug context builder ------------------------------------------------------


def _debug_phase_reproduce_lines() -> list[str]:
    return [
        "1. **Reproduce** the issue with a minimal test case",
        "   - Write the smallest possible code that triggers the bug",
        "   - Confirm the bug is reproducible",
        "   - Document the exact error/behavior",
        "",
        "After reproducing, call `sag_task_debug` with `hypothesis` to record your diagnosis.",
    ]


def _debug_phase_diagnose_lines(hypothesis: str) -> list[str]:
    return [
        "1. ~~Reproduce~~ ✓",
        f"2. **Diagnose** — Current hypothesis: *{hypothesis}*",
        "   - Verify the hypothesis with targeted tests",
        "   - If wrong, call `sag_task_debug` with a new hypothesis",
        "   - If confirmed, proceed to fix",
        "",
        "After confirming the root cause, call `sag_task_debug` with `fix_description`.",
    ]


def _debug_phase_fix_lines(hypothesis: str, fix: str) -> list[str]:
    return [
        "1. ~~Reproduce~~ ✓",
        f"2. ~~Diagnose~~ ✓ — {hypothesis}",
        f"3. **Fix** — Proposed fix: *{fix}*",
        "   - Implement the minimal fix for the root cause",
        "   - Do NOT fix symptoms; fix the underlying issue",
        "   - Run verification to confirm the fix works",
        "",
        "After implementing, call `sag_task_verify` to validate.",
    ]


def _build_debug_context(
    step_obj: Dict[str, Any],
    state: Dict[str, Any],
) -> str:
    """Build a structured debug prompt for systematic debugging."""
    step_name = step_obj.get("name", "Unknown Step")
    step_desc = step_obj.get("description", "")

    ms = state.get("methodology_state", {})
    debug_phase = ms.get("debug_phase", DEBUG_PHASE_REPRODUCE)
    hypothesis = ms.get("debug_hypothesis", "")
    fix = ms.get("debug_fix", "")

    lines = [
        f"## Debugging: {step_name}",
        f"**Current phase:** {debug_phase}",
        "",
        "### Issue Description",
    ]
    if step_desc:
        lines.append(f"- {step_desc}")
    else:
        lines.append(f"- {step_name}")

    lines.extend(["", "### Debug Methodology"])

    if debug_phase == DEBUG_PHASE_REPRODUCE:
        lines.extend(_debug_phase_reproduce_lines())
    elif debug_phase == DEBUG_PHASE_DIAGNOSE:
        lines.extend(_debug_phase_diagnose_lines(hypothesis))
    elif debug_phase == DEBUG_PHASE_FIX:
        lines.extend(_debug_phase_fix_lines(hypothesis, fix))

    last_v = ms.get("last_verification")
    if last_v:
        v_status = "passed" if last_v.get("passed") else "failed"
        lines.extend(["", f"### Last Verification: {v_status}"])

    verification = step_obj.get("verification", {})
    commands = verification.get("commands", [])
    if commands:
        lines.extend([
            "",
            "### Verification Commands",
            *[f"```bash\n{cmd}\n```" for cmd in commands],
        ])

    return "\n".join(lines)


def _handle_sag_task_review(args: Dict[str, Any]) -> Dict[str, Any]:
    """Build a structured review prompt for the current step."""
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    scope = args.get("scope", "step")

    if scope not in ("step", "phase", "full"):
        return {"ok": False, "error": f"Invalid scope '{scope}'. Must be step, phase, or full."}

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    step_obj = p._get_current_step_object(state)
    if not step_obj:
        return {"ok": False, "error": "Cannot find current step in task phases."}

    # Find the current phase for the step
    phase_name = ""
    phase_obj = None
    step_id = step_obj.get("id")
    for phase in state.get("phases", []):
        for s in phase.get("steps", []):
            if s.get("id") == step_id:
                phase_name = phase.get("name", "")
                phase_obj = phase
                break
        if phase_name:
            break

    context = _build_review_context(
        step_obj=step_obj,
        scope=scope,
        state=state,
        phase_name=phase_name,
        phase_obj=phase_obj,
    )

    return {
        "ok": True,
        "sag_task_id": task_id,
        "scope": scope,
        "step_id": step_obj.get("id", "unknown"),
        "context": context,
        "message": f"Review context built for scope '{scope}'. Use this to dispatch a review subagent.",
    }
