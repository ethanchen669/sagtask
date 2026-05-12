# Metrics Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an append-only event log (`.sag_metrics.jsonl`) with verification stats, coverage trends, and subtask throughput — queryable via a new `sag_task_metrics` tool and surfaced in LLM context injection.

**Architecture:** Events are emitted by existing handlers into a per-task JSONL file. A new `_handle_sag_task_metrics` handler reads the log and computes summaries. Context injection appends a one-line metrics summary.

**Tech Stack:** Python 3.10+, JSON, regex for coverage parsing. No new dependencies.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/sagtask/plugin.py` | `emit_metric()` method + metrics context line + gitignore update |
| `src/sagtask/handlers/_metrics.py` | New — `_handle_sag_task_metrics` query handler |
| `src/sagtask/handlers/__init__.py` | Register new handler in `_tool_handlers` |
| `src/sagtask/handlers/_plan.py` | Emit `verify_run` and `subtask_complete` events |
| `src/sagtask/handlers/_orchestration.py` | Emit `subtask_dispatch` event |
| `src/sagtask/handlers/_lifecycle.py` | Emit `step_advance`, `task_pause`, `task_resume` events + gitignore |
| `src/sagtask/schemas.py` | `TASK_METRICS_SCHEMA` + add to `ALL_TOOL_SCHEMAS` |
| `src/sagtask/__init__.py` | Re-export handler + schema |
| `tests/test_metrics.py` | Full test coverage for metrics feature |

---

### Task 1: `emit_metric` Method + Gitignore

**Files:**
- Modify: `src/sagtask/plugin.py:277-305` (add method before `shutdown`)
- Modify: `src/sagtask/plugin.py:81` (gitignore template)
- Modify: `src/sagtask/handlers/_lifecycle.py:71` (gitignore template)
- Test: `tests/test_metrics.py`

- [ ] **Step 1: Write the failing test for emit_metric**

```python
# tests/test_metrics.py
"""Tests for metrics collection."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sagtask.plugin import SagTaskPlugin


@pytest.fixture
def plugin(tmp_path):
    """Create a plugin with a tmp task root."""
    p = SagTaskPlugin()
    p._tasks_root = tmp_path
    return p


@pytest.fixture
def task_root(tmp_path):
    """Create a task directory."""
    task_dir = tmp_path / "test-task"
    task_dir.mkdir()
    return task_dir


def test_emit_metric_creates_jsonl(plugin, task_root):
    """emit_metric creates .sag_metrics.jsonl and writes one event."""
    task_id = "test-task"
    with patch.object(plugin, "get_task_root", return_value=task_root):
        plugin.emit_metric(task_id, "verify_run", step_id="s1", phase_id="p1", passed=True)

    metrics_file = task_root / ".sag_metrics.jsonl"
    assert metrics_file.exists()
    event = json.loads(metrics_file.read_text().strip())
    assert event["event"] == "verify_run"
    assert event["step_id"] == "s1"
    assert event["phase_id"] == "p1"
    assert event["passed"] is True
    assert "ts" in event


def test_emit_metric_appends(plugin, task_root):
    """Multiple calls append lines, not overwrite."""
    task_id = "test-task"
    with patch.object(plugin, "get_task_root", return_value=task_root):
        plugin.emit_metric(task_id, "verify_run", step_id="s1", phase_id="p1", passed=True)
        plugin.emit_metric(task_id, "verify_run", step_id="s1", phase_id="p1", passed=False)

    metrics_file = task_root / ".sag_metrics.jsonl"
    lines = metrics_file.read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["passed"] is True
    assert json.loads(lines[1])["passed"] is False


def test_emit_metric_ignores_write_failure(plugin, task_root):
    """emit_metric does not raise on write failure."""
    task_id = "test-task"
    with patch.object(plugin, "get_task_root", return_value=Path("/nonexistent/path")):
        # Should not raise
        plugin.emit_metric(task_id, "verify_run", step_id="s1", phase_id="p1", passed=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_metrics.py -v`
Expected: FAIL — `SagTaskPlugin` has no `emit_metric` method

- [ ] **Step 3: Implement emit_metric**

Add to `src/sagtask/plugin.py` before the `shutdown` method (before line 305):

```python
    def emit_metric(self, task_id: str, event: str, step_id: str = "", phase_id: str = "", **fields) -> None:
        """Append one metric event to .sag_metrics.jsonl."""
        task_root = self.get_task_root(task_id)
        metrics_file = task_root / ".sag_metrics.jsonl"
        entry = {"ts": _utcnow_iso(), "event": event, "step_id": step_id, "phase_id": phase_id, **fields}
        try:
            with open(metrics_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug("Failed to write metric: %s", e)
```

- [ ] **Step 4: Update gitignore templates**

In `src/sagtask/plugin.py` line 81, change the gitignore string to include `.sag_metrics.jsonl`:
```python
gitignore.write_text(".sag_task_state.json\n.sag_artifacts/\n.sag_executions/\n.sag_worktrees/\n.sag_metrics.jsonl\n__pycache__/\n*.pyc\n")
```

Same in `src/sagtask/handlers/_lifecycle.py` line 71:
```python
gitignore.write_text(".sag_task_state.json\n.sag_artifacts/\n.sag_executions/\n.sag_worktrees/\n.sag_metrics.jsonl\n__pycache__/\n*.pyc\n")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_metrics.py -v`
Expected: 3 PASSED

- [ ] **Step 6: Commit**

```bash
git add src/sagtask/plugin.py src/sagtask/handlers/_lifecycle.py tests/test_metrics.py
git commit -m "feat(metrics): add emit_metric method and gitignore entry"
```

---

### Task 2: Schema + Handler Registration

**Files:**
- Modify: `src/sagtask/schemas.py:483-503` (add schema + append to list)
- Create: `src/sagtask/handlers/_metrics.py`
- Modify: `src/sagtask/handlers/__init__.py`
- Modify: `src/sagtask/__init__.py`
- Test: `tests/test_metrics.py`

- [ ] **Step 1: Write the failing test for handler registration**

Append to `tests/test_metrics.py`:

```python
def test_metrics_tool_registered():
    """sag_task_metrics is in ALL_TOOL_SCHEMAS and _tool_handlers."""
    from sagtask.schemas import ALL_TOOL_SCHEMAS
    from sagtask.handlers import _tool_handlers

    schema_names = [s["name"] for s in ALL_TOOL_SCHEMAS]
    assert "sag_task_metrics" in schema_names
    assert "sag_task_metrics" in _tool_handlers
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_metrics.py::test_metrics_tool_registered -v`
Expected: FAIL — schema and handler not yet defined

- [ ] **Step 3: Add TASK_METRICS_SCHEMA to schemas.py**

Add before `ALL_TOOL_SCHEMAS` (after line 503 in `src/sagtask/schemas.py`):

```python
TASK_METRICS_SCHEMA = {
    "name": "sag_task_metrics",
    "description": "Query metrics for the current task. Returns verification stats, coverage trends, and throughput.",
    "parameters": {
        "type": "object",
        "properties": {
            "sag_task_id": {
                "type": "string",
                "description": "Task ID. Defaults to active task.",
            },
            "scope": {
                "type": "string",
                "enum": ["step", "phase", "task"],
                "description": "Scope of metrics query. Defaults to current step.",
            },
            "metric": {
                "type": "string",
                "enum": ["verification", "coverage", "throughput", "all"],
                "description": "Which metric category to return. Defaults to all.",
            },
        },
        "required": [],
    },
}
```

Add `TASK_METRICS_SCHEMA` to the `ALL_TOOL_SCHEMAS` list.

- [ ] **Step 4: Create handlers/_metrics.py with stub handler**

Create `src/sagtask/handlers/_metrics.py`:

```python
"""Metrics query handler for SagTask."""
from __future__ import annotations

from typing import Any, Dict

from .._utils import _get_provider


def _handle_sag_task_metrics(args: Dict[str, Any]) -> Dict[str, Any]:
    """Query metrics from the event log."""
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id

    if not task_id:
        return {"ok": False, "error": "No active task."}

    return {"ok": True, "message": "No metrics recorded yet."}
```

- [ ] **Step 5: Register handler in handlers/__init__.py**

Add import:
```python
from ._metrics import _handle_sag_task_metrics
```

Add to `_tool_handlers` dict:
```python
"sag_task_metrics": _handle_sag_task_metrics,
```

Add to `__all__` list:
```python
"_handle_sag_task_metrics",
```

- [ ] **Step 6: Re-export in __init__.py**

Add to imports in `src/sagtask/__init__.py`:

In the schemas import block:
```python
TASK_METRICS_SCHEMA,
```

Add new import line:
```python
from sagtask.handlers._metrics import _handle_sag_task_metrics  # noqa: F401
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_metrics.py -v`
Expected: 4 PASSED

- [ ] **Step 8: Commit**

```bash
git add src/sagtask/schemas.py src/sagtask/handlers/_metrics.py src/sagtask/handlers/__init__.py src/sagtask/__init__.py tests/test_metrics.py
git commit -m "feat(metrics): add sag_task_metrics schema and handler registration"
```

---

### Task 3: Emit Events from Existing Handlers

**Files:**
- Modify: `src/sagtask/handlers/_plan.py:88-184` (verify handler)
- Modify: `src/sagtask/handlers/_plan.py:436-520` (plan_update handler)
- Modify: `src/sagtask/handlers/_orchestration.py:180-200` (dispatch handler)
- Modify: `src/sagtask/handlers/_lifecycle.py:140-176` (pause handler)
- Modify: `src/sagtask/handlers/_lifecycle.py:200-238` (resume handler)
- Modify: `src/sagtask/handlers/_lifecycle.py:241-310` (advance handler)
- Test: `tests/test_metrics.py`

- [ ] **Step 1: Write the failing test for verify_run event emission**

Append to `tests/test_metrics.py`:

```python
def test_verify_emits_metric(tmp_path, monkeypatch):
    """sag_task_verify emits verify_run events to metrics log."""
    import sagtask
    from sagtask.handlers._plan import _handle_sag_task_verify

    task_id = "test-task"
    task_root = tmp_path / task_id
    task_root.mkdir()

    state = {
        "sag_task_id": task_id,
        "status": "active",
        "current_phase_id": "p1",
        "current_step_id": "s1",
        "phases": [{"id": "p1", "steps": [{"id": "s1", "verification": {"commands": ["echo ok"]}}]}],
        "methodology_state": {},
    }

    p = SagTaskPlugin()
    p._tasks_root = tmp_path
    p._active_task_id = task_id
    monkeypatch.setattr(sagtask._utils, "_sagtask_instance", p)
    p.save_task_state(task_id, state)

    result = _handle_sag_task_verify({"sag_task_id": task_id})
    assert result["ok"] is True

    metrics_file = task_root / ".sag_metrics.jsonl"
    assert metrics_file.exists()
    event = json.loads(metrics_file.read_text().strip())
    assert event["event"] == "verify_run"
    assert event["command"] == "echo ok"
    assert event["passed"] is True
    assert event["exit_code"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_metrics.py::test_verify_emits_metric -v`
Expected: FAIL — metrics file not created (no emit call yet)

- [ ] **Step 3: Add emit call to _handle_sag_task_verify**

In `src/sagtask/handlers/_plan.py`, inside the `for cmd in commands:` loop, after each result is appended (after line 138 for success, after line 147 for timeout, after line 155 for exception), add coverage parsing and emit:

After the existing `for cmd in commands:` loop (line 155) and before the TDD state machine section (line 157), insert:

```python
    # Emit metrics for each verification command
    import re
    for r in results:
        coverage_pct = None
        if "cov" in r["command"]:
            combined = r["stdout"] + r["stderr"]
            m = re.search(r"TOTAL\s+.*?(\d+)%", combined)
            if m:
                coverage_pct = int(m.group(1))
        emit_fields = {
            "command": r["command"],
            "exit_code": r["exit_code"],
            "passed": r["exit_code"] == 0,
        }
        if coverage_pct is not None:
            emit_fields["coverage_pct"] = coverage_pct
        p.emit_metric(task_id, "verify_run", step_id=state.get("current_step_id", ""), phase_id=state.get("current_phase_id", ""), **emit_fields)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_metrics.py::test_verify_emits_metric -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for subtask_complete emission**

Append to `tests/test_metrics.py`:

```python
def test_plan_update_emits_subtask_complete(tmp_path, monkeypatch):
    """sag_task_plan_update emits subtask_complete when status becomes done."""
    import sagtask
    from sagtask.handlers._plan import _handle_sag_task_plan_update

    task_id = "test-task"
    task_root = tmp_path / task_id
    task_root.mkdir()
    plans_dir = task_root / ".sag_plans"
    plans_dir.mkdir()

    plan = {
        "plan_version": 1,
        "step_id": "s1",
        "subtasks": [{"id": "st-1", "title": "Do thing", "status": "in_progress", "depends_on": []}],
    }
    (plans_dir / "s1.json").write_text(json.dumps(plan))

    state = {
        "sag_task_id": task_id,
        "status": "active",
        "current_phase_id": "p1",
        "current_step_id": "s1",
        "phases": [{"id": "p1", "steps": [{"id": "s1"}]}],
        "methodology_state": {"plan_file": ".sag_plans/s1.json", "subtask_progress": {"total": 1, "completed": 0, "in_progress": 1}},
    }

    p = SagTaskPlugin()
    p._tasks_root = tmp_path
    p._active_task_id = task_id
    monkeypatch.setattr(sagtask._utils, "_sagtask_instance", p)
    p.save_task_state(task_id, state)

    result = _handle_sag_task_plan_update({"sag_task_id": task_id, "subtask_id": "st-1", "status": "done"})
    assert result["ok"] is True

    metrics_file = task_root / ".sag_metrics.jsonl"
    assert metrics_file.exists()
    event = json.loads(metrics_file.read_text().strip())
    assert event["event"] == "subtask_complete"
    assert event["subtask_id"] == "st-1"
    assert event["old_status"] == "in_progress"
    assert event["new_status"] == "done"
```

- [ ] **Step 6: Implement subtask_complete emission in _handle_sag_task_plan_update**

In `src/sagtask/handlers/_plan.py`, in `_handle_sag_task_plan_update`, after the plan file is written (after line 492 `os.replace(...)`) and before progress sync, add:

```python
    # Emit subtask_complete metric on terminal status transitions
    old_status = subtask["status"]
    if new_status in ("done", "failed") and old_status != new_status:
        p.emit_metric(
            task_id, "subtask_complete",
            step_id=state.get("current_step_id", ""),
            phase_id=state.get("current_phase_id", ""),
            subtask_id=subtask_id,
            old_status=old_status,
            new_status=new_status,
        )
```

Note: capture `old_status = subtask["status"]` before the `_update_subtask` call (move it to before line 486).

- [ ] **Step 7: Add emit calls to dispatch, pause, resume, advance**

In `src/sagtask/handlers/_orchestration.py` `_handle_sag_task_dispatch`, after `p.save_task_state(task_id, state)` (after the state save), add:

```python
    p.emit_metric(
        task_id, "subtask_dispatch",
        step_id=state.get("current_step_id", ""),
        phase_id=state.get("current_phase_id", ""),
        subtask_id=subtask_id,
        use_worktree=use_worktree,
    )
```

In `src/sagtask/handlers/_lifecycle.py` `_handle_sag_task_pause`, after `p.save_task_state(task_id, state)` (line 176), add:

```python
    p.emit_metric(
        task_id, "task_pause",
        step_id=state.get("current_step_id", ""),
        phase_id=state.get("current_phase_id", ""),
        reason=reason,
    )
```

In `_handle_sag_task_resume`, after `p.save_task_state(task_id, state)` (line 226), add:

```python
    p.emit_metric(
        task_id, "task_resume",
        step_id=state.get("current_step_id", ""),
        phase_id=state.get("current_phase_id", ""),
    )
```

In `_handle_sag_task_advance`, after state is saved for the non-completion path (after the step transition state is saved, before the return), add:

```python
    p.emit_metric(
        task_id, "step_advance",
        step_id=current_step_id,
        phase_id=current_phase_id,
        from_step=current_step_id,
        to_step=next_step_id,
    )
```

- [ ] **Step 8: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All tests PASS

- [ ] **Step 9: Commit**

```bash
git add src/sagtask/handlers/_plan.py src/sagtask/handlers/_orchestration.py src/sagtask/handlers/_lifecycle.py tests/test_metrics.py
git commit -m "feat(metrics): emit events from verify, plan_update, dispatch, pause, resume, advance"
```

---

### Task 4: Metrics Query Implementation

**Files:**
- Modify: `src/sagtask/handlers/_metrics.py`
- Test: `tests/test_metrics.py`

- [ ] **Step 1: Write the failing test for verification metrics**

Append to `tests/test_metrics.py`:

```python
def test_metrics_query_verification(tmp_path, monkeypatch):
    """sag_task_metrics returns verification stats."""
    import sagtask
    from sagtask.handlers._metrics import _handle_sag_task_metrics

    task_id = "test-task"
    task_root = tmp_path / task_id
    task_root.mkdir()

    # Write sample events
    events = [
        {"ts": "2026-05-12T10:00:00Z", "event": "verify_run", "step_id": "s1", "phase_id": "p1", "command": "pytest", "exit_code": 1, "passed": False},
        {"ts": "2026-05-12T10:01:00Z", "event": "verify_run", "step_id": "s1", "phase_id": "p1", "command": "pytest", "exit_code": 0, "passed": True},
        {"ts": "2026-05-12T10:02:00Z", "event": "verify_run", "step_id": "s1", "phase_id": "p1", "command": "pytest", "exit_code": 0, "passed": True},
    ]
    metrics_file = task_root / ".sag_metrics.jsonl"
    metrics_file.write_text("\n".join(json.dumps(e) for e in events) + "\n")

    state = {
        "sag_task_id": task_id,
        "status": "active",
        "current_phase_id": "p1",
        "current_step_id": "s1",
        "phases": [{"id": "p1", "steps": [{"id": "s1"}]}],
        "methodology_state": {},
    }

    p = SagTaskPlugin()
    p._tasks_root = tmp_path
    p._active_task_id = task_id
    monkeypatch.setattr(sagtask._utils, "_sagtask_instance", p)
    p.save_task_state(task_id, state)

    result = _handle_sag_task_metrics({"sag_task_id": task_id, "scope": "step", "metric": "verification"})
    assert result["ok"] is True
    v = result["verification"]
    assert v["total_runs"] == 3
    assert v["passed"] == 2
    assert v["failed"] == 1
    assert v["pass_rate"] == pytest.approx(0.67, abs=0.01)
    assert v["last_result"] == "passed"
    assert v["streak"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_metrics.py::test_metrics_query_verification -v`
Expected: FAIL — stub handler returns no verification data

- [ ] **Step 3: Implement full _handle_sag_task_metrics**

Replace `src/sagtask/handlers/_metrics.py` with:

```python
"""Metrics query handler for SagTask."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from .._utils import _get_provider

logger = logging.getLogger(__name__)


def _load_events(task_id: str) -> List[Dict[str, Any]]:
    """Load all events from .sag_metrics.jsonl, skipping malformed lines."""
    p = _get_provider()
    task_root = p.get_task_root(task_id)
    metrics_file = task_root / ".sag_metrics.jsonl"
    if not metrics_file.exists():
        return []
    events = []
    for line in metrics_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            logger.debug("Skipping malformed metrics line: %s", line[:80])
    return events


def _filter_by_scope(events: List[Dict[str, Any]], scope: str, state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Filter events by scope (step, phase, or task)."""
    if scope == "task":
        return events
    elif scope == "phase":
        phase_id = state.get("current_phase_id", "")
        return [e for e in events if e.get("phase_id") == phase_id]
    else:  # step (default)
        step_id = state.get("current_step_id", "")
        return [e for e in events if e.get("step_id") == step_id]


def _compute_verification(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute verification stats from verify_run events."""
    verify_events = [e for e in events if e.get("event") == "verify_run"]
    if not verify_events:
        return {}
    total = len(verify_events)
    passed = sum(1 for e in verify_events if e.get("passed"))
    failed = total - passed
    pass_rate = round(passed / total, 2) if total else 0.0
    last_result = "passed" if verify_events[-1].get("passed") else "failed"

    # Compute streak (consecutive same results from the end)
    streak = 0
    last_val = verify_events[-1].get("passed")
    for e in reversed(verify_events):
        if e.get("passed") == last_val:
            streak += 1
        else:
            break
    if not last_val:
        streak = -streak

    return {
        "total_runs": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": pass_rate,
        "last_result": last_result,
        "streak": streak,
    }


def _compute_coverage(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute coverage trend from verify_run events with coverage_pct."""
    coverage_values = [
        e["coverage_pct"] for e in events
        if e.get("event") == "verify_run" and "coverage_pct" in e
    ]
    if not coverage_values:
        return {}

    current = coverage_values[-1]
    trend = "stable"
    if len(coverage_values) >= 6:
        recent = sum(coverage_values[-3:]) / 3
        prior = sum(coverage_values[-6:-3]) / 3
        if recent - prior > 2:
            trend = "improving"
        elif recent - prior < -2:
            trend = "declining"
    elif len(coverage_values) >= 3:
        recent = sum(coverage_values[-3:]) / 3
        first = coverage_values[0]
        if recent - first > 2:
            trend = "improving"
        elif recent - first < -2:
            trend = "declining"

    return {
        "current": current,
        "history": coverage_values,
        "trend": trend,
    }


def _compute_throughput(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute subtask throughput — idempotent by latest state per subtask_id."""
    complete_events = [e for e in events if e.get("event") == "subtask_complete"]
    if not complete_events:
        return {}

    # Track latest status per subtask_id
    latest: Dict[str, str] = {}
    for e in complete_events:
        sid = e.get("subtask_id", "")
        if sid:
            latest[sid] = e.get("new_status", "")

    done = sum(1 for s in latest.values() if s == "done")
    failed = sum(1 for s in latest.values() if s == "failed")

    return {
        "subtasks_total": len(latest),
        "subtasks_done": done,
        "subtasks_failed": failed,
    }


def _handle_sag_task_metrics(args: Dict[str, Any]) -> Dict[str, Any]:
    """Query metrics from the event log."""
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    events = _load_events(task_id)
    if not events:
        return {"ok": True, "message": "No metrics recorded yet."}

    scope = args.get("scope", "step")
    metric = args.get("metric", "all")

    filtered = _filter_by_scope(events, scope, state)
    if not filtered:
        return {"ok": True, "message": f"No metrics for scope '{scope}'."}

    result: Dict[str, Any] = {
        "ok": True,
        "scope": scope,
        "step_id": state.get("current_step_id", ""),
    }

    if metric in ("verification", "all"):
        v = _compute_verification(filtered)
        if v:
            result["verification"] = v

    if metric in ("coverage", "all"):
        c = _compute_coverage(filtered)
        if c:
            result["coverage"] = c

    if metric in ("throughput", "all"):
        t = _compute_throughput(filtered)
        if t:
            result["throughput"] = t

    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_metrics.py::test_metrics_query_verification -v`
Expected: PASS

- [ ] **Step 5: Write additional query tests**

Append to `tests/test_metrics.py`:

```python
def test_metrics_query_coverage_trend(tmp_path, monkeypatch):
    """Coverage trend is computed from history."""
    import sagtask
    from sagtask.handlers._metrics import _handle_sag_task_metrics

    task_id = "test-task"
    task_root = tmp_path / task_id
    task_root.mkdir()

    events = [
        {"ts": f"2026-05-12T10:0{i}:00Z", "event": "verify_run", "step_id": "s1", "phase_id": "p1", "command": "pytest --cov", "exit_code": 0, "passed": True, "coverage_pct": v}
        for i, v in enumerate([60, 62, 64, 70, 75, 80])
    ]
    (task_root / ".sag_metrics.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")

    state = {"sag_task_id": task_id, "status": "active", "current_phase_id": "p1", "current_step_id": "s1", "phases": [{"id": "p1", "steps": [{"id": "s1"}]}], "methodology_state": {}}
    p = SagTaskPlugin()
    p._tasks_root = tmp_path
    p._active_task_id = task_id
    monkeypatch.setattr(sagtask._utils, "_sagtask_instance", p)
    p.save_task_state(task_id, state)

    result = _handle_sag_task_metrics({"sag_task_id": task_id, "metric": "coverage"})
    assert result["ok"] is True
    assert result["coverage"]["current"] == 80
    assert result["coverage"]["trend"] == "improving"


def test_metrics_query_throughput_idempotent(tmp_path, monkeypatch):
    """Throughput counts latest status per subtask, not raw event count."""
    import sagtask
    from sagtask.handlers._metrics import _handle_sag_task_metrics

    task_id = "test-task"
    task_root = tmp_path / task_id
    task_root.mkdir()

    # st-1: in_progress -> done -> failed -> done (final: done)
    events = [
        {"ts": "2026-05-12T10:00:00Z", "event": "subtask_complete", "step_id": "s1", "phase_id": "p1", "subtask_id": "st-1", "old_status": "in_progress", "new_status": "done"},
        {"ts": "2026-05-12T10:01:00Z", "event": "subtask_complete", "step_id": "s1", "phase_id": "p1", "subtask_id": "st-1", "old_status": "done", "new_status": "failed"},
        {"ts": "2026-05-12T10:02:00Z", "event": "subtask_complete", "step_id": "s1", "phase_id": "p1", "subtask_id": "st-1", "old_status": "failed", "new_status": "done"},
        {"ts": "2026-05-12T10:03:00Z", "event": "subtask_complete", "step_id": "s1", "phase_id": "p1", "subtask_id": "st-2", "old_status": "in_progress", "new_status": "failed"},
    ]
    (task_root / ".sag_metrics.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")

    state = {"sag_task_id": task_id, "status": "active", "current_phase_id": "p1", "current_step_id": "s1", "phases": [{"id": "p1", "steps": [{"id": "s1"}]}], "methodology_state": {}}
    p = SagTaskPlugin()
    p._tasks_root = tmp_path
    p._active_task_id = task_id
    monkeypatch.setattr(sagtask._utils, "_sagtask_instance", p)
    p.save_task_state(task_id, state)

    result = _handle_sag_task_metrics({"sag_task_id": task_id, "metric": "throughput"})
    assert result["ok"] is True
    t = result["throughput"]
    assert t["subtasks_total"] == 2
    assert t["subtasks_done"] == 1
    assert t["subtasks_failed"] == 1


def test_metrics_query_empty_log(tmp_path, monkeypatch):
    """No metrics file returns friendly message."""
    import sagtask
    from sagtask.handlers._metrics import _handle_sag_task_metrics

    task_id = "test-task"
    task_root = tmp_path / task_id
    task_root.mkdir()

    state = {"sag_task_id": task_id, "status": "active", "current_phase_id": "p1", "current_step_id": "s1", "phases": [{"id": "p1", "steps": [{"id": "s1"}]}], "methodology_state": {}}
    p = SagTaskPlugin()
    p._tasks_root = tmp_path
    p._active_task_id = task_id
    monkeypatch.setattr(sagtask._utils, "_sagtask_instance", p)
    p.save_task_state(task_id, state)

    result = _handle_sag_task_metrics({"sag_task_id": task_id})
    assert result["ok"] is True
    assert "No metrics" in result["message"]


def test_metrics_handles_malformed_lines(tmp_path, monkeypatch):
    """Malformed JSONL lines are skipped gracefully."""
    import sagtask
    from sagtask.handlers._metrics import _handle_sag_task_metrics

    task_id = "test-task"
    task_root = tmp_path / task_id
    task_root.mkdir()

    content = 'not valid json\n{"ts":"2026-05-12T10:00:00Z","event":"verify_run","step_id":"s1","phase_id":"p1","command":"pytest","exit_code":0,"passed":true}\n'
    (task_root / ".sag_metrics.jsonl").write_text(content)

    state = {"sag_task_id": task_id, "status": "active", "current_phase_id": "p1", "current_step_id": "s1", "phases": [{"id": "p1", "steps": [{"id": "s1"}]}], "methodology_state": {}}
    p = SagTaskPlugin()
    p._tasks_root = tmp_path
    p._active_task_id = task_id
    monkeypatch.setattr(sagtask._utils, "_sagtask_instance", p)
    p.save_task_state(task_id, state)

    result = _handle_sag_task_metrics({"sag_task_id": task_id, "metric": "verification"})
    assert result["ok"] is True
    assert result["verification"]["total_runs"] == 1
```

- [ ] **Step 6: Run all metrics tests**

Run: `python -m pytest tests/test_metrics.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/sagtask/handlers/_metrics.py tests/test_metrics.py
git commit -m "feat(metrics): implement full query handler with verification, coverage, throughput"
```

---

### Task 5: Context Injection

**Files:**
- Modify: `src/sagtask/plugin.py:360-375` (add metrics line before cross-pollination)
- Test: `tests/test_metrics.py`

- [ ] **Step 1: Write the failing test for context injection**

Append to `tests/test_metrics.py`:

```python
def test_context_injection_includes_metrics(tmp_path, monkeypatch):
    """_build_task_context includes metrics summary line."""
    import sagtask

    task_id = "test-task"
    task_root = tmp_path / task_id
    task_root.mkdir()

    events = [
        {"ts": "2026-05-12T10:00:00Z", "event": "verify_run", "step_id": "s1", "phase_id": "p1", "command": "pytest", "exit_code": 1, "passed": False},
        {"ts": "2026-05-12T10:01:00Z", "event": "verify_run", "step_id": "s1", "phase_id": "p1", "command": "pytest --cov", "exit_code": 0, "passed": True, "coverage_pct": 85},
        {"ts": "2026-05-12T10:02:00Z", "event": "verify_run", "step_id": "s1", "phase_id": "p1", "command": "pytest --cov", "exit_code": 0, "passed": True, "coverage_pct": 88},
    ]
    (task_root / ".sag_metrics.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")

    state = {
        "sag_task_id": task_id,
        "status": "active",
        "current_phase_id": "p1",
        "current_step_id": "s1",
        "phases": [{"id": "p1", "name": "Phase 1", "steps": [{"id": "s1", "name": "Step 1"}]}],
        "methodology_state": {"current_methodology": "tdd"},
        "pending_gates": [],
        "artifacts_summary": "",
    }

    p = SagTaskPlugin()
    p._tasks_root = tmp_path
    p._active_task_id = task_id
    monkeypatch.setattr(sagtask._utils, "_sagtask_instance", p)

    context = p._build_task_context(state)
    assert "Verify:" in context
    assert "2/3" in context or "67%" in context
    assert "88%" in context or "Coverage:" in context
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_metrics.py::test_context_injection_includes_metrics -v`
Expected: FAIL — no metrics line in context output

- [ ] **Step 3: Implement metrics context line**

In `src/sagtask/plugin.py`, in `_build_task_context`, before the `cross_context` section (before line 370), add:

```python
        # Metrics summary line
        metrics_line = self._build_metrics_summary(state)
        if metrics_line:
            lines.append(metrics_line)
```

Add the helper method to `SagTaskPlugin` (before `_build_task_context`):

```python
    def _build_metrics_summary(self, state: Dict[str, Any]) -> str:
        """Build one-line metrics summary for context injection."""
        task_id = state.get("sag_task_id", self._active_task_id)
        if not task_id:
            return ""
        task_root = self.get_task_root(task_id)
        metrics_file = task_root / ".sag_metrics.jsonl"
        if not metrics_file.exists():
            return ""

        step_id = state.get("current_step_id", "")
        events = []
        for line in metrics_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                if e.get("step_id") == step_id:
                    events.append(e)
            except json.JSONDecodeError:
                continue

        if not events:
            return ""

        parts = []

        # Verification
        verify_events = [e for e in events if e.get("event") == "verify_run"]
        if verify_events:
            total = len(verify_events)
            passed = sum(1 for e in verify_events if e.get("passed"))
            pct = round(passed / total * 100)
            streak = 0
            last_val = verify_events[-1].get("passed")
            for e in reversed(verify_events):
                if e.get("passed") == last_val:
                    streak += 1
                else:
                    break
            streak_str = f"+{streak}" if last_val else f"-{streak}"
            parts.append(f"Verify: {passed}/{total} passed ({pct}%), streak {streak_str}")

        # Coverage
        cov_values = [e["coverage_pct"] for e in events if e.get("event") == "verify_run" and "coverage_pct" in e]
        if cov_values:
            current = cov_values[-1]
            arrow = "→"  # stable
            if len(cov_values) >= 3:
                recent_avg = sum(cov_values[-3:]) / 3
                first_avg = sum(cov_values[:3]) / 3
                if recent_avg - first_avg > 2:
                    arrow = "↑"
                elif recent_avg - first_avg < -2:
                    arrow = "↓"
            parts.append(f"Coverage: {current}% ({arrow})")

        # Throughput
        complete_events = [e for e in events if e.get("event") == "subtask_complete"]
        if complete_events:
            latest: Dict[str, str] = {}
            for e in complete_events:
                sid = e.get("subtask_id", "")
                if sid:
                    latest[sid] = e.get("new_status", "")
            done = sum(1 for s in latest.values() if s == "done")
            parts.append(f"Subtasks: {done}/{len(latest)} done")

        if not parts:
            return ""
        return "- " + " | ".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_metrics.py::test_context_injection_includes_metrics -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All tests PASS (no regressions)

- [ ] **Step 6: Commit**

```bash
git add src/sagtask/plugin.py tests/test_metrics.py
git commit -m "feat(metrics): add metrics summary to context injection"
```

---

### Task 6: Final Integration Test + CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`
- Test: `tests/test_metrics.py`

- [ ] **Step 1: Write an end-to-end integration test**

Append to `tests/test_metrics.py`:

```python
def test_full_metrics_lifecycle(tmp_path, monkeypatch):
    """End-to-end: create task, verify, query metrics."""
    import sagtask
    from sagtask.handlers._plan import _handle_sag_task_verify
    from sagtask.handlers._metrics import _handle_sag_task_metrics

    task_id = "test-task"
    task_root = tmp_path / task_id
    task_root.mkdir()

    state = {
        "sag_task_id": task_id,
        "status": "active",
        "current_phase_id": "p1",
        "current_step_id": "s1",
        "phases": [{"id": "p1", "steps": [{"id": "s1", "verification": {"commands": ["echo pass", "echo fail && exit 1"]}}]}],
        "methodology_state": {},
    }

    p = SagTaskPlugin()
    p._tasks_root = tmp_path
    p._active_task_id = task_id
    monkeypatch.setattr(sagtask._utils, "_sagtask_instance", p)
    p.save_task_state(task_id, state)

    # Run verify (will produce 2 verify_run events)
    _handle_sag_task_verify({"sag_task_id": task_id})

    # Query metrics
    result = _handle_sag_task_metrics({"sag_task_id": task_id, "metric": "verification"})
    assert result["ok"] is True
    assert result["verification"]["total_runs"] == 2
    assert result["verification"]["passed"] == 1
    assert result["verification"]["failed"] == 1
```

- [ ] **Step 2: Run the integration test**

Run: `python -m pytest tests/test_metrics.py::test_full_metrics_lifecycle -v`
Expected: PASS

- [ ] **Step 3: Update CHANGELOG**

In `CHANGELOG.md`, in the `[Unreleased]` → `### Added` section, add:

```markdown
- `sag_task_metrics` tool — query verification stats, coverage trends, and subtask throughput
- Append-only metrics event log (`.sag_metrics.jsonl`) emitted by verify, dispatch, plan_update, advance, pause, resume
- Metrics summary in context injection (pass rate, coverage trend, subtask progress)
```

- [ ] **Step 4: Run full test suite one final time**

Run: `python -m pytest tests/ -q`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md tests/test_metrics.py
git commit -m "feat(metrics): add integration test and changelog entry"
```
