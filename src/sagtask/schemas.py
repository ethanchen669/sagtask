"""Tool schema definitions for SagTask."""
from __future__ import annotations

from typing import Any, Dict, List

# ─────────────────────────────────────────────────────────────────────────────
# Tool schemas — extracted from __init__.py into a dedicated module
# ─────────────────────────────────────────────────────────────────────────────

TASK_CREATE_SCHEMA = {
    "name": "sag_task_create",
    "description": "Create a new sag long term task with phased steps and approval gates. "
    "Initializes a dedicated Git repo under ~/.hermes/sag_tasks/<task_id>/. "
    "Returns the task_id and current state.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {
                "type": "string",
                "description": "Unique sag long term task identifier (alphanumeric + hyphens, e.g. 'sc-mrp-v1'). "
                "Used as the Git repo name.",
            },
            "name": {"type": "string", "description": "Human-readable task name."},
            "description": {"type": "string", "description": "Detailed task description."},
            "phases": {
                "type": "array",
                "description": "List of phases. Each phase has steps with optional approval gates.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Unique phase ID (e.g. 'phase-1')."},
                        "name": {"type": "string", "description": "Phase name (e.g. '数据建模')."},
                        "steps": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                    "gate": {
                                        "type": "object",
                                        "description": "Optional approval gate for this step.",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "question": {
                                                "type": "string",
                                                "description": "Approval question presented to the user.",
                                            },
                                            "choices": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                                "description": "Approval options (e.g. ['Approve', 'Reject', 'Request Changes']).",
                                            },
                                        },
                                        "required": ["id", "question"],
                                    },
                                    "methodology": {
                                        "type": "object",
                                        "description": "Optional execution methodology for this step.",
                                        "properties": {
                                            "type": {
                                                "type": "string",
                                                "enum": [
                                                    "tdd",
                                                    "brainstorm",
                                                    "debug",
                                                    "plan-execute",
                                                    "parallel-agents",
                                                    "review",
                                                    "none",
                                                ],
                                                "description": "Methodology type.",
                                            },
                                            "config": {
                                                "type": "object",
                                                "description": "Methodology-specific configuration.",
                                                "properties": {
                                                    "coverage_threshold": {
                                                        "type": "integer",
                                                        "description": "Min test coverage % for TDD.",
                                                    },
                                                    "test_first": {
                                                        "type": "boolean",
                                                        "description": "Enforce test-first for TDD.",
                                                    },
                                                },
                                            },
                                        },
                                        "required": ["type"],
                                    },
                                    "verification": {
                                        "type": "object",
                                        "description": "Optional verification requirements. Advance is blocked until verification passes.",
                                        "properties": {
                                            "commands": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                                "description": "Shell commands to run for verification.",
                                            },
                                            "must_pass": {
                                                "type": "boolean",
                                                "default": True,
                                                "description": "If True, advance is blocked until verification passes.",
                                            },
                                            "cwd": {
                                                "type": "string",
                                                "description": "Working directory for verification commands (default: task root).",
                                            },
                                        },
                                        "required": ["commands"],
                                    },
                                },
                                "required": ["id", "name"],
                            },
                        },
                    },
                    "required": ["id", "name", "steps"],
                },
            },
        },
        "required": ["sag_task_id", "name", "phases"],
    },
}

TASK_STATUS_SCHEMA = {
    "name": "sag_task_status",
    "description": "Show the current status of a sag long term task — phase, step, pending gates, and recent artifacts.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {
                "type": "string",
                "description": "Sag long term task identifier. Omit to use the currently active task.",
            },
            "verbose": {
                "type": "boolean",
                "default": False,
                "description": "If True, include full phase/step tree and git log.",
            },
        },
        "required": [],
    },
}

TASK_PAUSE_SCHEMA = {
    "name": "sag_task_pause",
    "description": "Pause the active sag long term task and save a PausedExecutionContext snapshot. "
    "The task can be resumed later with sag_task_resume. "
    "This snapshots pending tool calls, artifacts, and session context so the agent "
    "can recover mid-step without losing work.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {"type": "string", "description": "Sag long term task to pause. Omit to pause the active task."},
            "reason": {"type": "string", "description": "Reason for pausing (shown on resume)."},
        },
        "required": [],
    },
}

TASK_RESUME_SCHEMA = {
    "name": "sag_task_resume",
    "description": "Resume a paused sag long term task from its PausedExecutionContext snapshot. "
    "Restores pending tool calls, artifacts, and context. "
    "After resuming, use sag_task_advance to proceed after an approval gate.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {"type": "string", "description": "Sag long term task to resume. Omit to resume the active task."},
        },
        "required": [],
    },
}

TASK_ADVANCE_SCHEMA = {
    "name": "sag_task_advance",
    "description": "Advance the sag long term task to the next Step or Phase after completing the current one. "
    "Writes the updated task_state.json (per-step, not per-turn). "
    "Creates a new git branch for the next step and commits the current work.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {"type": "string", "description": "Sag long term task to advance. Omit for the active task."},
            "commit_message": {
                "type": "string",
                "description": "Git commit message for the current step's work. "
                "Defaults to 'WIP: <step_name> completed'.",
            },
            "artifacts_summary": {
                "type": "string",
                "description": "Brief summary of artifacts produced in this step (for sag long term task_state).",
            },
        },
        "required": [],
    },
}

TASK_APPROVE_SCHEMA = {
    "name": "sag_task_approve",
    "description": "Submit an approval decision for a pending gate. "
    "Used when a user approves/rejects a step or requests changes. "
    "After approval, the sag long term task status is updated and the approver's decision is recorded.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {"type": "string", "description": "Sag long term task with pending gate. Omit for the active task."},
            "gate_id": {"type": "string", "description": "The gate ID to approve (from task_status pending_gates)."},
            "decision": {
                "type": "string",
                "description": "One of the gate's allowed choices (e.g. 'Approve', 'Reject').",
                "enum": ["Approve", "Reject", "Request Changes"],
            },
            "comment": {"type": "string", "description": "Optional comment from the approver."},
        },
        "required": ["gate_id", "decision"],
    },
}

TASK_LIST_SCHEMA = {
    "name": "sag_task_list",
    "description": "List all sag long term tasks under ~/.hermes/sag_tasks/, showing task_id, status, current phase/step, and last active time.",
    "parameters": {
        "type": "object",
        "properties": {
            "status_filter": {
                "type": "string",
                "description": "Filter by status: 'active', 'paused', 'completed', 'all'. " "Defaults to 'all'.",
            },
        },
        "required": [],
    },
}

TASK_COMMIT_SCHEMA = {
    "name": "sag_task_commit",
    "description": "Commit current working state to the sag long term task's Git repo. "
    "Auto-stages all tracked files. Use before sag_task_advance or sag_task_pause to persist work.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {"type": "string", "description": "Sag long term task whose repo to commit. Omit for the active task."},
            "message": {
                "type": "string",
                "description": "Commit message. Should follow: '[Step N] <description>'.",
            },
        },
        "required": ["message"],
    },
}

TASK_BRANCH_SCHEMA = {
    "name": "sag_task_branch",
    "description": "Create a new Git branch for the next step of the sag long term task. "
    "The branch name follows: step/<phase_id>/<step_id>-<short-description>. "
    "Automatically switches to the new branch.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {"type": "string", "description": "Sag long term task whose repo to branch. Omit for the active task."},
            "branch_name": {
                "type": "string",
                "description": "Full branch name (e.g. 'step/phase-2/step-3-bom-engine'). "
                "Omit to auto-generate from current step context.",
            },
        },
        "required": [],
    },
}

TASK_GIT_LOG_SCHEMA = {
    "name": "sag_task_git_log",
    "description": "Show the Git commit history for a sag long term task, most recent first.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {"type": "string", "description": "Sag long term task whose git log to show. Omit for the active task."},
            "max_count": {
                "type": "integer",
                "default": 20,
                "description": "Maximum number of commits to return.",
            },
        },
        "required": [],
    },
}

TASK_RELATE_SCHEMA = {
    "name": "sag_task_relate",
    "description": "Declare a cross-pollination relationship between this sag long term task and another. "
    "Use this when two tasks share the same research theme but follow different research paths "
    "and their artifacts may inspire each other. "
    "Relationships are stored in task_state.json. Max 2 cross-pollination relationships per task.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {"type": "string", "description": "Sag long term task to add a relationship to. Omit for the active task."},
            "related_task_id": {"type": "string", "description": "The task_id of the related sag long term task to link."},
            "relationship": {
                "type": "string",
                "description": "Relationship type. Use 'cross-pollination' for medium-strength "
                "same-theme-different-path relationships.",
                "enum": ["cross-pollination"],
            },
            "action": {"type": "string", "description": "'add' to add a relationship, 'remove' to remove it.", "enum": ["add", "remove"]},
        },
        "required": ["related_task_id", "relationship", "action"],
    },
}

TASK_VERIFY_SCHEMA = {
    "name": "sag_task_verify",
    "description": "Run verification commands for the current step. "
    "Commands must be defined in the step's verification config at creation time. "
    "Results are recorded in methodology_state. "
    "Must pass before sag_task_advance if verification.must_pass is True.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {
                "type": "string",
                "description": "Sag long term task identifier. Omit to verify the active task.",
            },
        },
        "required": [],
    },
}

TASK_PLAN_UPDATE_SCHEMA = {
    "name": "sag_task_plan_update",
    "description": "Update the status of a subtask in the current step's plan. "
    "Syncs progress counts to methodology_state.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {
                "type": "string",
                "description": "Task ID. Defaults to active task.",
            },
            "subtask_id": {
                "type": "string",
                "description": "Subtask ID to update (e.g. 'st-1').",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "done", "failed"],
                "description": "New status for the subtask.",
            },
            "context": {
                "type": "string",
                "description": "Optional context or result to record on the subtask.",
            },
        },
        "required": ["subtask_id", "status"],
    },
}

TASK_DISPATCH_SCHEMA = {
    "name": "sag_task_dispatch",
    "description": "Dispatch a subtask for execution. Builds a self-contained context "
    "prompt with subtask details, methodology instructions, and dependency status. "
    "Marks the subtask as in-progress. Use the returned context to dispatch a subagent.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {
                "type": "string",
                "description": "Task ID. Defaults to active task.",
            },
            "subtask_id": {
                "type": "string",
                "description": "Subtask ID from the plan to dispatch.",
            },
            "max_context_len": {
                "type": "integer",
                "description": "Max characters for the returned context prompt. "
                "0 (default) means no limit.",
            },
        },
        "required": ["subtask_id"],
    },
}

TASK_PLAN_SCHEMA = {
    "name": "sag_task_plan",
    "description": "Generate a structured subtask plan for the current step. "
    "Creates .sag_plans/<step_id>.json with bite-sized subtasks. "
    "Each subtask is 2-30 minutes of work depending on granularity.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {
                "type": "string",
                "description": "Task ID. Defaults to active task.",
            },
            "granularity": {
                "type": "string",
                "enum": ["fine", "medium", "coarse"],
                "description": "Subtask granularity. fine=2-5min, medium=10-15min, coarse=30+min. Default: medium. Note: only affects TDD methodology plans.",
            },
        },
    },
}

TASK_REVIEW_SCHEMA = {
    "name": "sag_task_review",
    "description": "Build a structured review prompt for the current step. "
    "Supports two-stage review: spec compliance first, then code quality. "
    "Returns review criteria based on step verification and methodology.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {
                "type": "string",
                "description": "Task ID. Defaults to active task.",
            },
            "scope": {
                "type": "string",
                "enum": ["step", "phase", "full"],
                "description": "Review scope. Default: step.",
            },
        },
    },
}

ALL_TOOL_SCHEMAS = [
    TASK_CREATE_SCHEMA,
    TASK_STATUS_SCHEMA,
    TASK_PAUSE_SCHEMA,
    TASK_RESUME_SCHEMA,
    TASK_ADVANCE_SCHEMA,
    TASK_APPROVE_SCHEMA,
    TASK_LIST_SCHEMA,
    TASK_COMMIT_SCHEMA,
    TASK_BRANCH_SCHEMA,
    TASK_GIT_LOG_SCHEMA,
    TASK_RELATE_SCHEMA,
    TASK_VERIFY_SCHEMA,
    TASK_PLAN_SCHEMA,
    TASK_PLAN_UPDATE_SCHEMA,
    TASK_DISPATCH_SCHEMA,
    TASK_REVIEW_SCHEMA,
]
