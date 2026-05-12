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
