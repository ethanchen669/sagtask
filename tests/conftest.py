"""Shared fixtures for SagTask tests."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import sagtask


@pytest.fixture
def isolated_sagtask(tmp_path):
    """Create an isolated SagTaskPlugin with tmp_path as projects_root."""
    sagtask._sagtask_instance = None
    plugin = sagtask.SagTaskPlugin()
    plugin._hermes_home = tmp_path / "hermes"
    plugin._projects_root = tmp_path / "hermes" / "sag_tasks"
    plugin._projects_root.mkdir(parents=True)
    sagtask._sagtask_instance = plugin
    yield plugin
    sagtask._sagtask_instance = None


@pytest.fixture
def mock_git(isolated_sagtask):
    """Mock git/gh subprocess calls so no real git operations occur."""
    with patch("sagtask.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        yield mock_run


@pytest.fixture
def sample_phases():
    """Standard test phases with gates."""
    return [
        {
            "id": "phase-1",
            "name": "Design",
            "steps": [
                {"id": "step-1", "name": "Data Model"},
                {"id": "step-2", "name": "Migration Script"},
            ],
        },
        {
            "id": "phase-2",
            "name": "Implementation",
            "steps": [
                {"id": "step-3", "name": "BOM Engine"},
            ],
        },
    ]


@pytest.fixture
def sample_phases_with_methodology():
    """Test phases with methodology and verification configured."""
    return [
        {
            "id": "phase-1",
            "name": "Design",
            "steps": [
                {
                    "id": "step-1",
                    "name": "Data Model",
                    "methodology": {"type": "tdd", "config": {"coverage_threshold": 80}},
                    "verification": {"commands": ["pytest"], "must_pass": True},
                },
                {"id": "step-2", "name": "Migration Script"},
            ],
        },
        {
            "id": "phase-2",
            "name": "Implementation",
            "steps": [
                {"id": "step-3", "name": "BOM Engine"},
            ],
        },
    ]
