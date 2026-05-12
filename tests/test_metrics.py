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
