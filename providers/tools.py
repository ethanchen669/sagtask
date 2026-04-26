"""Tool schemas for MemTaskProvider — per-task Git repos with approval gates."""

from __future__ import annotations

# ── Task Lifecycle ────────────────────────────────────────────────────────────

TASK_CREATE_SCHEMA = {
    "name": "task_create",
    "description": "Create a new long-running task with phased steps and approval gates. "
    "Initializes a dedicated Git repo under ~/.hermes/projects/<task_id>/. "
    "Returns the task_id and current state.",
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Unique task identifier (alphanumeric + hyphens, e.g. 'sc-mrp-v1'). "
                "Used as the Git repo name.",
            },
            "name": {
                "type": "string",
                "description": "Human-readable task name.",
            },
            "description": {
                "type": "string",
                "description": "Detailed task description.",
            },
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
                                            "question": {"type": "string", "description": "Approval question presented to the user."},
                                            "choices": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                                "description": "Approval options (e.g. ['Approve', 'Reject', 'Request Changes']).",
                                            },
                                        },
                                        "required": ["id", "question"],
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
        "required": ["task_id", "name", "phases"],
    },
}

TASK_STATUS_SCHEMA = {
    "name": "task_status",
    "description": "Show the current status of a task — phase, step, pending gates, and recent artifacts.",
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task identifier. Omit to use the currently active task.",
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
    "name": "task_pause",
    "description": "Pause the active task and save a PausedExecutionContext snapshot. "
    "The task can be resumed later with task_resume. "
    "This snapshots pending tool calls, artifacts, and session context so the agent "
    "can recover mid-step without losing work.",
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task to pause. Omit to pause the active task.",
            },
            "reason": {
                "type": "string",
                "description": "Reason for pausing (shown on resume).",
            },
        },
        "required": [],
    },
}

TASK_RESUME_SCHEMA = {
    "name": "task_resume",
    "description": "Resume a paused task from its PausedExecutionContext snapshot. "
    "Restores pending tool calls, artifacts, and context. "
    "After resuming, use task_advance to proceed after an approval gate.",
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task to resume. Omit to resume the active task.",
            },
        },
        "required": [],
    },
}

TASK_ADVANCE_SCHEMA = {
    "name": "task_advance",
    "description": "Advance the task to the next Step or Phase after completing the current one. "
    "Writes the updated task_state.json (per-step, not per-turn). "
    "Creates a new git branch for the next step and commits the current work.",
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task to advance. Omit for the active task.",
            },
            "commit_message": {
                "type": "string",
                "description": "Git commit message for the current step's work. "
                "Defaults to 'WIP: <step_name> completed'.",
            },
            "artifacts_summary": {
                "type": "string",
                "description": "Brief summary of artifacts produced in this step (for task_state).",
            },
        },
        "required": [],
    },
}

TASK_APPROVE_SCHEMA = {
    "name": "task_approve",
    "description": "Submit an approval decision for a pending gate. "
    "Used when a user approves/rejects a step or requests changes. "
    "After approval, the task status is updated and the approver's decision is recorded.",
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task with pending gate. Omit for the active task.",
            },
            "gate_id": {
                "type": "string",
                "description": "The gate ID to approve (from task_status pending_gates).",
            },
            "decision": {
                "type": "string",
                "description": "One of the gate's allowed choices (e.g. 'Approve', 'Reject').",
                "enum": ["Approve", "Reject", "Request Changes"],
            },
            "comment": {
                "type": "string",
                "description": "Optional comment from the approver.",
            },
        },
        "required": ["gate_id", "decision"],
    },
}

# ── Task Discovery ───────────────────────────────────────────────────────────

TASK_LIST_SCHEMA = {
    "name": "task_list",
    "description": "List all tasks under ~/.hermes/projects/, showing task_id, status, "
    "current phase/step, and last active time.",
    "parameters": {
        "type": "object",
        "properties": {
            "status_filter": {
                "type": "string",
                "description": "Filter by status: 'active', 'paused', 'completed', 'all'. "
                "Defaults to 'all'.",
            },
        },
        "required": [],
    },
}

# ── Git Operations ────────────────────────────────────────────────────────────

TASK_COMMIT_SCHEMA = {
    "name": "task_commit",
    "description": "Commit current working state to the task's Git repo. "
    "Auto-stages all tracked files. Use before task_advance or task_pause to persist work.",
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task whose repo to commit. Omit for the active task.",
            },
            "message": {
                "type": "string",
                "description": "Commit message. Should follow: '[Step N] <description>'.",
            },
        },
        "required": ["message"],
    },
}

TASK_BRANCH_SCHEMA = {
    "name": "task_branch",
    "description": "Create a new Git branch for the next step. "
    "The branch name follows: step/<phase_id>/<step_id>-<short-description>. "
    "Automatically switches to the new branch.",
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task whose repo to branch. Omit for the active task.",
            },
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
    "name": "task_git_log",
    "description": "Show the Git commit history for a task, most recent first.",
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task whose git log to show. Omit for the active task.",
            },
            "max_count": {
                "type": "integer",
                "default": 20,
                "description": "Maximum number of commits to return.",
            },
        },
        "required": [],
    },
}

# ── Cross-Task Relationships ────────────────────────────────────────────────

TASK_RELATE_SCHEMA = {
    "name": "task_relate",
    "description": "Declare a cross-pollination relationship with another task. "
    "Use this when two tasks share the same research theme but follow different research paths "
    "and their artifacts may inspire each other. "
    "Relationships are stored in task_state.json. Max 2 cross-pollination relationships per task.",
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task to add a relationship to. Omit for the active task.",
            },
            "related_task_id": {
                "type": "string",
                "description": "The task_id of the related task to link.",
            },
            "relationship": {
                "type": "string",
                "description": "Relationship type. Use 'cross-pollination' for medium-strength "
                "same-theme-different-path relationships.",
                "enum": ["cross-pollination"],
            },
            "action": {
                "type": "string",
                "description": "'add' to add a relationship, 'remove' to remove it.",
                "enum": ["add", "remove"],
            },
        },
        "required": ["related_task_id", "relationship", "action"],
    },
}
