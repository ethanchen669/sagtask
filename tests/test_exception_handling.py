"""Tests that exceptions are logged, not silently swallowed."""
import logging
import subprocess
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

import sagtask


class TestExceptionLogging:
    """Verify that caught exceptions produce log output instead of being silently dropped."""

    def test_advance_logs_git_commit_error(self, isolated_sagtask, sample_phases, caplog):
        """Git commit failure in advance should be logged as warning, not swallowed."""
        p = isolated_sagtask
        task_id = "exc-test"
        task_root = p.get_task_root(task_id)
        task_root.mkdir(parents=True, exist_ok=True)

        # Initialize a real git repo in the task root so the commit path is entered
        subprocess.run(["git", "init"], cwd=str(task_root), capture_output=True, timeout=5)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(task_root), capture_output=True, timeout=5)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(task_root), capture_output=True, timeout=5)
        (task_root / "dummy.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=str(task_root), capture_output=True, timeout=5)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(task_root), capture_output=True, timeout=5)

        # Save task state with current step set
        state = {
            "sag_task_id": task_id,
            "name": "Exception Test",
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "current_phase_id": "phase-1",
            "current_step_id": "step-1",
            "phases": sample_phases,
            "pending_gates": [],
            "artifacts_summary": "",
            "decisions": [],
            "executions": [],
            "relationships": [],
            "artifact_summaries": [],
        }
        p.save_task_state(task_id, state)

        original_run = subprocess.run

        def failing_run(cmd, **kwargs):
            if isinstance(cmd, list) and len(cmd) > 0 and cmd[0] == "git" and "commit" in cmd:
                raise OSError("git not found")
            return original_run(cmd, **kwargs)

        with patch("sagtask.subprocess.run", side_effect=failing_run):
            with caplog.at_level(logging.WARNING):
                sagtask._handle_sag_task_advance({"sag_task_id": task_id})

        assert any("git" in record.message.lower() or "commit" in record.message.lower()
                    for record in caplog.records), \
            f"No git error logged. Log records: {[r.message for r in caplog.records]}"

    def test_scan_artifacts_logs_error_on_git_failure(self, isolated_sagtask, caplog):
        """Git failure during artifact scan should be logged as debug, not swallowed."""
        p = isolated_sagtask
        task_id = "scan-exc-test"
        task_root = p.get_task_root(task_id)
        task_root.mkdir(parents=True, exist_ok=True)

        # No git repo in task_root — but we need one for the scan to attempt git commands
        subprocess.run(["git", "init"], cwd=str(task_root), capture_output=True, timeout=5)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(task_root), capture_output=True, timeout=5)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(task_root), capture_output=True, timeout=5)
        (task_root / "dummy.txt").write_text("data")
        subprocess.run(["git", "add", "."], cwd=str(task_root), capture_output=True, timeout=5)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(task_root), capture_output=True, timeout=5)

        # Patch subprocess.run so git commands in _scan_git_artifacts raise
        original_run = subprocess.run

        def failing_run(cmd, **kwargs):
            if isinstance(cmd, list) and len(cmd) > 0 and cmd[0] == "git":
                raise OSError("simulated git failure")
            return original_run(cmd, **kwargs)

        with patch("sagtask.subprocess.run", side_effect=failing_run):
            with caplog.at_level(logging.DEBUG):
                result = p._scan_git_artifacts(task_id)

        assert result == [], f"Expected empty list on failure, got {result}"
        assert any("git artifact scan step failed" in record.message.lower()
                    for record in caplog.records), \
            f"No scan error logged. Log records: {[r.message for r in caplog.records]}"
