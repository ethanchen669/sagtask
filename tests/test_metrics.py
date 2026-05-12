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
        plugin.emit_metric(task_id, "verify_run", step_id="s1", phase_id="p1", passed=True)


def test_metrics_tool_registered():
    """sag_task_metrics is in ALL_TOOL_SCHEMAS and _tool_handlers."""
    from sagtask.schemas import ALL_TOOL_SCHEMAS
    from sagtask.handlers import _tool_handlers

    schema_names = [s["name"] for s in ALL_TOOL_SCHEMAS]
    assert "sag_task_metrics" in schema_names
    assert "sag_task_metrics" in _tool_handlers


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
    p._projects_root = tmp_path
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
    p._projects_root = tmp_path
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


def test_metrics_query_verification(tmp_path, monkeypatch):
    """sag_task_metrics returns verification stats."""
    import sagtask
    from sagtask.handlers._metrics import _handle_sag_task_metrics

    task_id = "test-task"
    task_root = tmp_path / task_id
    task_root.mkdir()

    events = [
        {"ts": "2026-05-12T10:00:00Z", "event": "verify_run", "step_id": "s1", "phase_id": "p1", "command": "pytest", "exit_code": 1, "passed": False},
        {"ts": "2026-05-12T10:01:00Z", "event": "verify_run", "step_id": "s1", "phase_id": "p1", "command": "pytest", "exit_code": 0, "passed": True},
        {"ts": "2026-05-12T10:02:00Z", "event": "verify_run", "step_id": "s1", "phase_id": "p1", "command": "pytest", "exit_code": 0, "passed": True},
    ]
    metrics_file = task_root / ".sag_metrics.jsonl"
    metrics_file.write_text("\n".join(json.dumps(e) for e in events) + "\n")

    state = {"sag_task_id": task_id, "status": "active", "current_phase_id": "p1", "current_step_id": "s1", "phases": [{"id": "p1", "steps": [{"id": "s1"}]}], "methodology_state": {}}
    p = SagTaskPlugin()
    p._projects_root = tmp_path
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
    p._projects_root = tmp_path
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

    events = [
        {"ts": "2026-05-12T10:00:00Z", "event": "subtask_complete", "step_id": "s1", "phase_id": "p1", "subtask_id": "st-1", "old_status": "in_progress", "new_status": "done"},
        {"ts": "2026-05-12T10:01:00Z", "event": "subtask_complete", "step_id": "s1", "phase_id": "p1", "subtask_id": "st-1", "old_status": "done", "new_status": "failed"},
        {"ts": "2026-05-12T10:02:00Z", "event": "subtask_complete", "step_id": "s1", "phase_id": "p1", "subtask_id": "st-1", "old_status": "failed", "new_status": "done"},
        {"ts": "2026-05-12T10:03:00Z", "event": "subtask_complete", "step_id": "s1", "phase_id": "p1", "subtask_id": "st-2", "old_status": "in_progress", "new_status": "failed"},
    ]
    (task_root / ".sag_metrics.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")

    state = {"sag_task_id": task_id, "status": "active", "current_phase_id": "p1", "current_step_id": "s1", "phases": [{"id": "p1", "steps": [{"id": "s1"}]}], "methodology_state": {}}
    p = SagTaskPlugin()
    p._projects_root = tmp_path
    p._active_task_id = task_id
    monkeypatch.setattr(sagtask._utils, "_sagtask_instance", p)
    p.save_task_state(task_id, state)

    result = _handle_sag_task_metrics({"sag_task_id": task_id, "metric": "throughput"})
    assert result["ok"] is True
    t = result["throughput"]
    assert t["subtasks_total"] == 2
    assert t["subtasks_done"] == 1
    assert t["subtasks_failed"] == 1


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
    p._projects_root = tmp_path
    p._active_task_id = task_id
    monkeypatch.setattr(sagtask._utils, "_sagtask_instance", p)
    p.save_task_state(task_id, state)

    result = _handle_sag_task_metrics({"sag_task_id": task_id, "metric": "verification"})
    assert result["ok"] is True
    assert result["verification"]["total_runs"] == 1


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
    p._projects_root = tmp_path
    p._active_task_id = task_id
    monkeypatch.setattr(sagtask._utils, "_sagtask_instance", p)

    context = p._build_task_context(state)
    # Should contain verification stats
    assert "Verify:" in context
    assert "2/3" in context
    # Should contain coverage
    assert "88%" in context
