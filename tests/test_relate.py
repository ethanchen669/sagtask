"""Tests for _handle_sag_task_relate — cross-pollination relationship management."""
from unittest.mock import MagicMock, patch
import sagtask


class TestRelate:
    def _create_two_tasks(self, isolated_sagtask, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "task-a",
            "name": "Task A",
            "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        sagtask._handle_sag_task_create({
            "sag_task_id": "task-b",
            "name": "Task B",
            "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        isolated_sagtask._active_task_id = "task-a"

    def test_no_active_task(self, isolated_sagtask):
        isolated_sagtask._active_task_id = None
        result = sagtask._handle_sag_task_relate({})
        assert result["ok"] is False
        assert "No active task" in result["error"]

    def test_task_not_found(self, isolated_sagtask):
        isolated_sagtask._active_task_id = "nonexistent"
        result = sagtask._handle_sag_task_relate({"sag_task_id": "nonexistent"})
        assert result["ok"] is False

    def test_list_action(self, isolated_sagtask, mock_git):
        self._create_two_tasks(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_relate({"action": "list"})
        assert result["ok"] is True
        assert "relationships" in result

    def test_add_requires_related_task_id(self, isolated_sagtask, mock_git):
        self._create_two_tasks(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_relate({"action": "add", "relationship": "related"})
        assert result["ok"] is False
        assert "related_task_id" in result["error"]

    def test_add_requires_relationship(self, isolated_sagtask, mock_git):
        self._create_two_tasks(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_relate({"action": "add", "related_task_id": "task-b"})
        assert result["ok"] is False
        assert "relationship" in result["error"]

    def test_add_invalid_action(self, isolated_sagtask, mock_git):
        self._create_two_tasks(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_relate({
            "action": "invalid",
            "related_task_id": "task-b",
            "relationship": "related",
        })
        assert result["ok"] is False
        assert "add" in result["error"]

    def test_add_related_task_not_found(self, isolated_sagtask, mock_git):
        self._create_two_tasks(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_relate({
            "action": "add",
            "related_task_id": "nonexistent",
            "relationship": "related",
        })
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_add_success(self, isolated_sagtask, mock_git):
        self._create_two_tasks(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_relate({
            "action": "add",
            "related_task_id": "task-b",
            "relationship": "cross-pollination",
        })
        assert result["ok"] is True
        assert result["total_relationships"] == 1

    def test_add_duplicate(self, isolated_sagtask, mock_git):
        self._create_two_tasks(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_relate({
            "action": "add",
            "related_task_id": "task-b",
            "relationship": "related",
        })
        result = sagtask._handle_sag_task_relate({
            "action": "add",
            "related_task_id": "task-b",
            "relationship": "related",
        })
        assert result["ok"] is False
        assert "already" in result["error"]

    def test_add_max_cross_pollination(self, isolated_sagtask, mock_git):
        self._create_two_tasks(isolated_sagtask, mock_git)
        # Explicitly target task-a for all relate calls
        # Add 1 cross-pollination (count=1, max is 2)
        sagtask._handle_sag_task_relate({
            "sag_task_id": "task-a",
            "action": "add", "related_task_id": "task-b", "relationship": "cross-pollination",
        })
        # Create a third task and add it as cross-pollination (count=2, now at max)
        with patch("sagtask.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            sagtask._handle_sag_task_create({
                "sag_task_id": "task-c",
                "name": "Task C",
                "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
            })
        sagtask._handle_sag_task_relate({
            "sag_task_id": "task-a",
            "action": "add", "related_task_id": "task-c", "relationship": "cross-pollination",
        })
        # Now at max (2). Try adding a 3rd cross-pollination (should fail)
        with patch("sagtask.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            sagtask._handle_sag_task_create({
                "sag_task_id": "task-d",
                "name": "Task D",
                "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
            })
        result = sagtask._handle_sag_task_relate({
            "sag_task_id": "task-a",
            "action": "add", "related_task_id": "task-d", "relationship": "cross-pollination",
        })
        assert result["ok"] is False
        assert "Max" in result["error"]

    def test_remove_success(self, isolated_sagtask, mock_git):
        self._create_two_tasks(isolated_sagtask, mock_git)
        sagtask._handle_sag_task_relate({
            "action": "add",
            "related_task_id": "task-b",
            "relationship": "related",
        })
        result = sagtask._handle_sag_task_relate({
            "action": "remove",
            "related_task_id": "task-b",
            "relationship": "related",
        })
        assert result["ok"] is True
        assert result["total_relationships"] == 0

    def test_remove_not_in_list(self, isolated_sagtask, mock_git):
        self._create_two_tasks(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_relate({
            "action": "remove",
            "related_task_id": "task-b",
            "relationship": "related",
        })
        assert result["ok"] is False
        assert "not in" in result["error"]
