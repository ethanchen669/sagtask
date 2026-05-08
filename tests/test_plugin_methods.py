"""Tests for SagTaskPlugin instance methods."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import sagtask


class TestPluginProperties:
    def test_name(self, isolated_sagtask):
        assert isolated_sagtask.name == "sagtask"

    def test_is_available(self, isolated_sagtask):
        assert isolated_sagtask.is_available() is True


class TestInitialize:
    def test_initialize_with_hermes_home(self, isolated_sagtask, tmp_path):
        hermes = tmp_path / "custom_hermes"
        isolated_sagtask.initialize("s1", hermes_home=str(hermes))
        assert isolated_sagtask._hermes_home == hermes
        assert isolated_sagtask._projects_root == hermes / "sag_tasks"
        assert isolated_sagtask._projects_root.exists()

    def test_initialize_without_hermes_home(self, isolated_sagtask, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        plugin = sagtask.SagTaskPlugin()
        plugin.initialize("s1")
        assert plugin._hermes_home == tmp_path / ".hermes"


class TestEnsureGitRepo:
    def test_ensure_git_repo_already_exists(self, isolated_sagtask, mock_git):
        task_id = "test-git-exists"
        sagtask._handle_sag_task_create({
            "sag_task_id": task_id,
            "name": "Git Test",
            "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        # .git already created by mock_git during create
        result = isolated_sagtask.ensure_git_repo(task_id)
        assert result is True

    def test_ensure_git_repo_init_fails(self, isolated_sagtask):
        task_id = "test-git-fail"
        task_root = isolated_sagtask._projects_root / task_id
        task_root.mkdir(parents=True)
        with patch("sagtask.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error")
            result = isolated_sagtask.ensure_git_repo(task_id)
            assert result is False


class TestCreateGithubRepo:
    def test_repo_already_exists(self, isolated_sagtask):
        task_id = "test-gh-exists"
        with patch("sagtask.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="repo found")
            result = isolated_sagtask.create_github_repo(task_id)
            assert result is True

    def test_repo_create_success(self, isolated_sagtask):
        task_id = "test-gh-create"
        with patch("sagtask.subprocess.run") as mock_run:
            # First call: repo view fails, second call: repo create succeeds
            mock_run.side_effect = [
                MagicMock(returncode=1, stderr="not found"),
                MagicMock(returncode=0, stdout="created"),
            ]
            result = isolated_sagtask.create_github_repo(task_id)
            assert result is True

    def test_repo_create_failure(self, isolated_sagtask):
        task_id = "test-gh-fail"
        with patch("sagtask.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=1, stderr="not found"),
                MagicMock(returncode=1, stderr="create failed"),
            ]
            result = isolated_sagtask.create_github_repo(task_id)
            assert result is False


class TestGitPush:
    def test_push_success(self, isolated_sagtask):
        task_id = "test-push"
        with patch("sagtask.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = isolated_sagtask.git_push(task_id)
            assert result is True

    def test_push_repo_not_found_then_create(self, isolated_sagtask):
        task_id = "test-push-create"
        with patch("sagtask.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=1, stderr="Repository not found"),
                MagicMock(returncode=0, stdout="repo view"),  # create_github_repo view
                MagicMock(returncode=0, stdout="repo created"),  # create_github_repo create
                MagicMock(returncode=0, stdout="", stderr=""),  # retry push
            ]
            result = isolated_sagtask.git_push(task_id)
            assert result is True

    def test_push_permanent_failure(self, isolated_sagtask):
        task_id = "test-push-fail"
        with patch("sagtask.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="permission denied")
            result = isolated_sagtask.git_push(task_id)
            assert result is False


class TestGitCheckout:
    def test_checkout_success(self, isolated_sagtask):
        task_id = "test-checkout"
        with patch("sagtask.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = isolated_sagtask.git_checkout(task_id, "main")
            assert result is True

    def test_checkout_failure(self, isolated_sagtask):
        task_id = "test-checkout-fail"
        with patch("sagtask.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="branch not found")
            result = isolated_sagtask.git_checkout(task_id, "nonexistent")
            assert result is False


class TestGitLog:
    def test_log_success(self, isolated_sagtask):
        task_id = "test-log"
        with patch("sagtask.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="abc1234 first commit\ndef5678 second commit\n",
                stderr="",
            )
            log = isolated_sagtask.git_log(task_id, max_count=5)
            assert len(log) == 2
            assert log[0]["hash"] == "abc1234"
            assert log[0]["message"] == "first commit"

    def test_log_failure(self, isolated_sagtask):
        task_id = "test-log-fail"
        with patch("sagtask.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error")
            log = isolated_sagtask.git_log(task_id)
            assert log == []


class TestRestoreActiveTask:
    def test_restore_with_valid_marker(self, isolated_sagtask, mock_git):
        task_id = "test-restore"
        sagtask._handle_sag_task_create({
            "sag_task_id": task_id,
            "name": "Restore Test",
            "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        marker = isolated_sagtask._projects_root / ".active_task"
        marker.write_text(task_id)
        isolated_sagtask._active_task_id = None
        isolated_sagtask._restore_active_task()
        assert isolated_sagtask._active_task_id == task_id

    def test_restore_no_marker(self, isolated_sagtask):
        isolated_sagtask._active_task_id = None
        isolated_sagtask._restore_active_task()
        assert isolated_sagtask._active_task_id is None

    def test_restore_invalid_task(self, isolated_sagtask):
        marker = isolated_sagtask._projects_root / ".active_task"
        marker.write_text("nonexistent_task")
        isolated_sagtask._active_task_id = None
        isolated_sagtask._restore_active_task()
        assert isolated_sagtask._active_task_id is None


class TestSetActiveTask:
    def test_set_active_task(self, isolated_sagtask):
        isolated_sagtask._set_active_task("task-1")
        assert isolated_sagtask._active_task_id == "task-1"
        marker = isolated_sagtask._projects_root / ".active_task"
        assert marker.read_text() == "task-1"

    def test_clear_active_task(self, isolated_sagtask):
        marker = isolated_sagtask._projects_root / ".active_task"
        marker.write_text("task-1")
        isolated_sagtask._set_active_task(None)
        assert isolated_sagtask._active_task_id is None
        assert not marker.exists()


class TestLoadTaskState:
    def test_load_valid_state(self, isolated_sagtask, mock_git):
        task_id = "test-load"
        sagtask._handle_sag_task_create({
            "sag_task_id": task_id,
            "name": "Load Test",
            "phases": [{"id": "p1", "name": "P1", "steps": [{"id": "s1", "name": "S1"}]}],
        })
        state = isolated_sagtask.load_task_state(task_id)
        assert state is not None
        assert state["name"] == "Load Test"

    def test_load_missing_task(self, isolated_sagtask):
        state = isolated_sagtask.load_task_state("nonexistent")
        assert state is None

    def test_load_corrupted_json(self, isolated_sagtask):
        task_id = "test-corrupted"
        task_root = isolated_sagtask._projects_root / task_id
        task_root.mkdir(parents=True)
        state_path = task_root / ".sag_task_state.json"
        state_path.write_text("not valid json {{{")
        state = isolated_sagtask.load_task_state(task_id)
        assert state is None
