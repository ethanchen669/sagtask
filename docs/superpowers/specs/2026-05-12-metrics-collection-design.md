# Metrics Collection Design

**Date:** 2026-05-12
**Status:** Approved (revised after design review)
**Scope:** P3 item from Phase 4 — verification stats, coverage trends, subtask throughput

---

## Overview

Add an append-only event log (`.sag_metrics.jsonl`) that records verification runs, subtask lifecycle events, and step transitions. A new `sag_task_metrics` tool queries the log and returns computed summaries. Context injection surfaces a one-line metrics summary to the agent.

**Consumers:**
- Agent (context injection) — makes decisions based on pass rates, coverage trends
- Human (tool output / raw JSONL) — inspects task health and velocity

**Priority focus:** Verification stats (pass/fail counts, retry frequency, coverage trends).

---

## 1. Event Log

**File:** `<task_root>/.sag_metrics.jsonl` (git-ignored, append-only, local runtime state)

**Common fields on every event:**

| Field | Type | Description |
|-------|------|-------------|
| `ts` | string (ISO-8601 UTC) | Timestamp of the event |
| `event` | string | Event type identifier |
| `step_id` | string | Current step when event occurred |
| `phase_id` | string | Current phase when event occurred |

**Event types:**

| Event | Emitted by | Additional fields |
|-------|-----------|-------------------|
| `verify_run` | `sag_task_verify` | `command`, `exit_code`, `passed`, `coverage_pct` (optional) |
| `subtask_dispatch` | `sag_task_dispatch` | `subtask_id`, `use_worktree` |
| `subtask_complete` | `sag_task_plan_update` | `subtask_id`, `old_status`, `new_status` |
| `step_advance` | `sag_task_advance` | `from_step`, `to_step` |
| `task_pause` | `sag_task_pause` | `reason` |
| `task_resume` | `sag_task_resume` | — |

**Example log:**
```jsonl
{"ts":"2026-05-12T10:00:00Z","event":"verify_run","step_id":"s1","phase_id":"p1","command":"pytest tests/","exit_code":1,"passed":false}
{"ts":"2026-05-12T10:01:30Z","event":"verify_run","step_id":"s1","phase_id":"p1","command":"pytest tests/ --cov=src","exit_code":0,"passed":true,"coverage_pct":85}
{"ts":"2026-05-12T10:01:45Z","event":"subtask_complete","step_id":"s1","phase_id":"p1","subtask_id":"st-1","old_status":"in_progress","new_status":"done"}
{"ts":"2026-05-12T10:02:00Z","event":"step_advance","step_id":"s1","phase_id":"p1","from_step":"s1","to_step":"s2"}
```

---

## 2. `sag_task_metrics` Tool

**Tool #19.** Queries the event log and returns computed summaries.

**Schema:**
```json
{
  "name": "sag_task_metrics",
  "description": "Query metrics for the current task. Returns verification stats, coverage trends, and throughput.",
  "parameters": {
    "type": "object",
    "properties": {
      "sag_task_id": {
        "type": "string",
        "description": "Task ID. Defaults to active task."
      },
      "scope": {
        "type": "string",
        "enum": ["step", "phase", "task"],
        "description": "Scope of metrics query. Defaults to current step."
      },
      "metric": {
        "type": "string",
        "enum": ["verification", "coverage", "throughput", "all"],
        "description": "Which metric category to return. Defaults to all."
      }
    }
  }
}
```

**Return structure (example: `metric: "all"`, `scope: "step"`):**
```json
{
  "ok": true,
  "scope": "step",
  "step_id": "s2",
  "verification": {
    "total_runs": 7,
    "passed": 4,
    "failed": 3,
    "pass_rate": 0.57,
    "last_result": "passed",
    "streak": 2
  },
  "coverage": {
    "current": 85,
    "history": [72, 78, 80, 85],
    "trend": "improving"
  },
  "throughput": {
    "subtasks_total": 5,
    "subtasks_done": 3,
    "subtasks_failed": 0
  }
}
```

**Field semantics:**
- `streak`: consecutive passes (positive int) or failures (negative int)
- `trend`: `"improving"` / `"stable"` / `"declining"` — computed from last 3+ coverage data points
- When `scope: "task"`, aggregates across all steps
- When no events exist for the requested scope, returns `{"ok": true, "message": "No metrics recorded yet."}`

---

## 3. Context Injection

**Location:** `_build_task_context` in `plugin.py`, appended after existing methodology lines.

**Format:**
```
- Verify: 4/7 passed (57%), streak +2 | Coverage: 85% (↑) | Subtasks: 3/5 done
```

**Rules:**
- Only inject if `.sag_metrics.jsonl` exists and has events for the current step
- One line max — dense but scannable
- Arrow indicators: `↑` improving, `→` stable, `↓` declining
- Skip sections with no data (e.g., no coverage events → omit that segment)
- Computed per-call by reading tail of the log

---

## 4. Implementation Details

### 4.1 `emit_metric` Method

**Location:** `SagTaskPlugin` method in `plugin.py`

```python
def emit_metric(self, task_id: str, event: str, step_id: str, phase_id: str, **fields) -> None:
    """Append one metric event to .sag_metrics.jsonl."""
```

- Opens `<task_root>/.sag_metrics.jsonl` in append mode, writes one JSON line, closes
- Automatically adds `ts` (from `_utcnow_iso()`)
- `step_id` and `phase_id` are passed explicitly by the caller (from the state dict they already have loaded)
- Caller passes `event` type and any additional fields as kwargs
- Logs write failures at debug level (metrics are non-critical, but silence hides bugs)

### 4.2 Coverage Parsing (Best-Effort)

- Regex on combined stdout+stderr: `r"TOTAL\s+.*?(\d+)%"`
- Only attempted when the command string contains `"cov"` (heuristic to avoid false matches)
- Returns `None` if not found — field omitted from event
- This is best-effort extraction; wrapper scripts or XML/JSON reports are not parsed

### 4.3 Metrics Computation (`_handle_sag_task_metrics`)

**Location:** New file `handlers/_metrics.py`

Reads `.sag_metrics.jsonl`, filters by scope (step/phase/task), computes:
- **Verification:** count pass/fail, compute rate, determine streak
- **Coverage:** extract `coverage_pct` values, compute trend
- **Throughput:** aggregate by latest `new_status` per `subtask_id` (idempotent — handles repeated/reversed transitions)

**Trend algorithm:** Compare mean of last 3 values to mean of preceding 3. If delta > +2: improving. If delta < -2: declining. Otherwise: stable.

### 4.4 Emit Points (existing handlers modified)

| Handler | Event emitted |
|---------|--------------|
| `_handle_sag_task_verify` (`_plan.py`) | `verify_run` (per command) |
| `_handle_sag_task_dispatch` (`_orchestration.py`) | `subtask_dispatch` |
| `_handle_sag_task_plan_update` (`_plan.py`) | `subtask_complete` (when status → done/failed) |
| `_handle_sag_task_advance` (`_lifecycle.py`) | `step_advance` |
| `_handle_sag_task_pause` (`_lifecycle.py`) | `task_pause` |
| `_handle_sag_task_resume` (`_lifecycle.py`) | `task_resume` |

### 4.5 File Inventory

| File | Change type |
|------|-------------|
| `src/sagtask/plugin.py` | Add `emit_metric()` method + metrics line in context injection + `.sag_metrics.jsonl` to gitignore template |
| `src/sagtask/handlers/_plan.py` | Emit `verify_run`, `subtask_complete` |
| `src/sagtask/handlers/_orchestration.py` | Emit `subtask_dispatch` |
| `src/sagtask/handlers/_lifecycle.py` | Emit `step_advance`, `task_pause`, `task_resume` + `.sag_metrics.jsonl` to gitignore template |
| `src/sagtask/schemas.py` | Add `TASK_METRICS_SCHEMA` to schemas + `ALL_TOOL_SCHEMAS` |
| `src/sagtask/handlers/_metrics.py` | New — `_handle_sag_task_metrics` |
| `src/sagtask/handlers/__init__.py` | Import handler, add to `_tool_handlers` map and `__all__` |
| `src/sagtask/__init__.py` | Re-export handler + schema |
| `tests/test_metrics.py` | New — tests for emit, query, context injection, idempotent throughput, malformed JSONL |

---

## 5. Non-Goals

- No execution-time tracking (wall-clock durations, pause-adjusted time) — deferred until there's a concrete use case
- No external metrics backend (Prometheus, StatsD, etc.)
- No real-time dashboard
- No alerting or notifications
- No historical comparison across different tasks
- No metrics for LLM token usage or cost

## 6. Design Review Resolutions

| Finding | Resolution |
|---------|-----------|
| Tool registration incomplete | Added `handlers/__init__.py` to file inventory |
| Execution-time claimed but not designed | Removed from scope — verification stats are the priority |
| Throughput not idempotent | `subtask_complete` now carries `old_status`/`new_status`; aggregation uses latest state per subtask_id |
| Git-tracking creates noise | Changed to git-ignored (local runtime state) |
| `_emit_metric` ownership | Moved to `SagTaskPlugin.emit_metric()` method |
| Coverage parsing fragility | Documented as best-effort; parses stdout+stderr combined |
