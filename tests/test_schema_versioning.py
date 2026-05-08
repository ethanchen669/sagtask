"""Tests for schema versioning in task state."""
import json
import pytest
from sagtask import (
    SCHEMA_VERSION,
    _handle_sag_task_create,
    _get_provider,
)


class TestSchemaVersioning:
    def test_new_task_has_schema_version(self, isolated_sagtask, mock_git, sample_phases):
        """Newly created tasks should have schema_version=2."""
        _handle_sag_task_create({
            "sag_task_id": "schema-test",
            "name": "Schema Test",
            "phases": sample_phases,
        })
        p = _get_provider()
        state = p.load_task_state("schema-test")
        assert state["schema_version"] == SCHEMA_VERSION

    def test_old_state_without_version_gets_migrated(self, isolated_sagtask, mock_git, sample_phases):
        """Old state without schema_version should get schema_version added on save."""
        p = _get_provider()
        task_id = "migrate-test"
        task_root = p.get_task_root(task_id)
        task_root.mkdir(parents=True, exist_ok=True)

        # Simulate an old state file without schema_version
        old_state = {
            "sag_task_id": task_id,
            "name": "Migrate Test",
            "status": "active",
        }
        p.save_task_state(task_id, old_state)

        saved = json.loads(p.get_task_state_path(task_id).read_text())
        assert saved["schema_version"] == SCHEMA_VERSION

    def test_methodology_state_initialized(self, isolated_sagtask, mock_git, sample_phases):
        """New tasks should have methodology_state with current_methodology='none'."""
        _handle_sag_task_create({
            "sag_task_id": "method-test",
            "name": "Method Test",
            "phases": sample_phases,
        })
        p = _get_provider()
        state = p.load_task_state("method-test")
        assert "methodology_state" in state
        ms = state["methodology_state"]
        assert ms["current_methodology"] == "none"
        assert ms["tdd_phase"] is None
        assert ms["plan_file"] is None
        assert ms["last_verification"] is None
        assert ms["review_state"] is None
        assert ms["subtask_progress"]["total"] == 0

    def test_old_task_gets_methodology_state_backfilled(self, isolated_sagtask, mock_git, sample_phases):
        """Old state without methodology_state should get it backfilled on save."""
        p = _get_provider()
        task_id = "backfill-test"
        task_root = p.get_task_root(task_id)
        task_root.mkdir(parents=True, exist_ok=True)

        # Simulate an old state file with schema_version but no methodology_state
        old_state = {
            "sag_task_id": task_id,
            "name": "Backfill Test",
            "status": "active",
            "schema_version": SCHEMA_VERSION,
        }
        p.save_task_state(task_id, old_state)

        saved = json.loads(p.get_task_state_path(task_id).read_text())
        assert "methodology_state" in saved
        ms = saved["methodology_state"]
        assert ms["current_methodology"] == "none"
        assert ms["tdd_phase"] is None
        assert ms["plan_file"] is None
        assert ms["last_verification"] is None
        assert ms["review_state"] is None
        assert ms["subtask_progress"] == {"total": 0, "completed": 0, "in_progress": 0}
