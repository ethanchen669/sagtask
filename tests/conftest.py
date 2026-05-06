"""Shared fixtures for SagTask tests."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock
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
