"""Tests for SagTaskPlugin._get_current_step static method."""
import pytest
from sagtask import SagTaskPlugin


class TestGetCurrentStep:
    def test_returns_step_name_when_found(self):
        state = {
            "current_phase_id": "phase-1",
            "current_step_id": "step-2",
            "phases": [
                {
                    "id": "phase-1",
                    "steps": [
                        {"id": "step-1", "name": "Design"},
                        {"id": "step-2", "name": "Implement"},
                    ],
                }
            ],
        }
        assert SagTaskPlugin._get_current_step(state) == "Implement"

    def test_returns_first_step_name_when_current_step_not_in_list(self):
        state = {
            "current_phase_id": "phase-1",
            "current_step_id": "step-nonexistent",
            "phases": [
                {
                    "id": "phase-1",
                    "steps": [{"id": "step-1", "name": "First"}],
                }
            ],
        }
        assert SagTaskPlugin._get_current_step(state) == "First"

    def test_returns_dash_when_phases_empty(self):
        state = {"current_phase_id": "phase-1", "current_step_id": "step-1", "phases": []}
        assert SagTaskPlugin._get_current_step(state) == "—"

    def test_returns_dash_when_current_phase_not_found(self):
        state = {
            "current_phase_id": "nonexistent",
            "current_step_id": "step-1",
            "phases": [],
        }
        assert SagTaskPlugin._get_current_step(state) == "—"

    def test_returns_step_id_when_name_missing(self):
        state = {
            "current_phase_id": "phase-1",
            "current_step_id": "step-1",
            "phases": [
                {"id": "phase-1", "steps": [{"id": "step-1"}]},
            ],
        }
        assert SagTaskPlugin._get_current_step(state) == "step-1"
