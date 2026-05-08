"""Tests for _handle_sag_task_commit, _handle_sag_task_branch, _handle_sag_task_list."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import sagtask


class TestCommitHandler:
    def test_no_active_task(self, isolated_sagtask):
        isolated_sagtask._active_task_id = None
        result = sagtask._handle_sag_task_commit({"message": "test"})
        assert result["ok"] is False
        assert "No active task" in result["error"]

    def test_not_git_repo(self, isolated_sagtask, mock_git):
        task_id = "test-commit-no-git"
        task_root = isolated_sagtask._projects_root / task_id
        task_root.mkdir(parents=True)
        isolated_sagtask._active_task_id = task_id
        result = sagtask._handle_sag_task_commit({
            "sag_task_id": task_id,
            "message": "test commit",
        })
        assert result["ok"] is False
        assert "not a Git repo" in result["error"]

    def test_commit_success(self, isolated_sagtask, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-commit-ok",
            "name": "Commit OK",
            "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        # Create .git dir since git init is mocked
        task_root = isolated_sagtask.get_task_root("test-commit-ok")
        (task_root / ".git").mkdir(exist_ok=True)
        mock_git.return_value = MagicMock(returncode=0, stdout="abc123", stderr="")
        result = sagtask._handle_sag_task_commit({
            "sag_task_id": "test-commit-ok",
            "message": "my commit",
        })
        assert result["ok"] is True

    def test_commit_failure(self, isolated_sagtask, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-commit-fail",
            "name": "Commit Fail",
            "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        # Create .git dir since git init is mocked
        task_root = isolated_sagtask.get_task_root("test-commit-fail")
        (task_root / ".git").mkdir(exist_ok=True)
        # git add succeeds, git commit fails
        mock_git.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # git add
            MagicMock(returncode=1, stderr="nothing to commit"),  # git commit
        ]
        result = sagtask._handle_sag_task_commit({
            "sag_task_id": "test-commit-fail",
            "message": "empty commit",
        })
        assert result["ok"] is False
        assert "failed" in result["error"]


class TestBranchHandler:
    def test_no_active_task(self, isolated_sagtask):
        isolated_sagtask._active_task_id = None
        result = sagtask._handle_sag_task_branch({"branch_name": "test"})
        assert result["ok"] is False
        assert "No active task" in result["error"]

    def test_auto_branch_name(self, isolated_sagtask, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-auto-branch",
            "name": "Auto Branch",
            "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        mock_git.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = sagtask._handle_sag_task_branch({"sag_task_id": "test-auto-branch"})
        assert result["ok"] is True
        assert "step/" in result["branch_name"]

    def test_branch_task_not_found(self, isolated_sagtask):
        # Need a task to exist so load_task_state returns None (no state file)
        task_id = "test-branch-nostate"
        task_root = isolated_sagtask._projects_root / task_id
        task_root.mkdir(parents=True)
        result = sagtask._handle_sag_task_branch({
            "sag_task_id": task_id,
        })
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_branch_failure(self, isolated_sagtask, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-branch-fail",
            "name": "Branch Fail",
            "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        mock_git.return_value = MagicMock(returncode=1, stderr="branch exists")
        result = sagtask._handle_sag_task_branch({
            "sag_task_id": "test-branch-fail",
            "branch_name": "existing",
        })
        assert result["ok"] is False
        assert "Failed" in result["error"]


class TestListHandler:
    def test_list_empty_root(self, isolated_sagtask):
        isolated_sagtask._projects_root = isolated_sagtask._projects_root / "empty"
        result = sagtask._handle_sag_task_list({})
        assert result["ok"] is True
        assert result["tasks"] == []

    def test_list_skips_dotfiles(self, isolated_sagtask, mock_git):
        hidden = isolated_sagtask._projects_root / ".hidden"
        hidden.mkdir()
        result = sagtask._handle_sag_task_list({})
        assert result["ok"] is True
        assert len(result["tasks"]) == 0

    def test_list_skips_dirs_without_state(self, isolated_sagtask, mock_git):
        no_state = isolated_sagtask._projects_root / "no-state-task"
        no_state.mkdir()
        result = sagtask._handle_sag_task_list({})
        assert result["ok"] is True
        assert len(result["tasks"]) == 0

    def test_list_filter_by_status(self, isolated_sagtask, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "list-active",
            "name": "Active",
            "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        result = sagtask._handle_sag_task_list({"status_filter": "paused"})
        assert result["ok"] is True
        assert len(result["tasks"]) == 0

        result = sagtask._handle_sag_task_list({"status_filter": "active"})
        assert result["ok"] is True
        assert len(result["tasks"]) == 1


class TestGitLogHandler:
    def test_no_active_task(self, isolated_sagtask):
        isolated_sagtask._active_task_id = None
        result = sagtask._handle_sag_task_git_log({})
        assert result["ok"] is False

    def test_git_log_success(self, isolated_sagtask, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-log",
            "name": "Log Test",
            "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        mock_git.return_value = MagicMock(
            returncode=0, stdout="abc1234 first commit\n", stderr=""
        )
        result = sagtask._handle_sag_task_git_log({"sag_task_id": "test-log"})
        assert result["ok"] is True
        assert len(result["commits"]) == 1
