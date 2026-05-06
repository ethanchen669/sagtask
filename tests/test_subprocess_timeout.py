"""Tests that subprocess calls use timeout."""
from unittest.mock import MagicMock
import sagtask
from sagtask import _SUBPROCESS_TIMEOUT


class TestSubprocessTimeout:
    def test_ensure_git_repo_uses_timeout(self, isolated_sagtask, monkeypatch):
        call_args = []

        def fake_run(cmd, **kwargs):
            call_args.append(kwargs)
            mock = MagicMock()
            mock.returncode = 0
            mock.stdout = ""
            mock.stderr = ""
            return mock

        monkeypatch.setattr("subprocess.run", fake_run)
        isolated_sagtask.ensure_git_repo("test-timeout")

        for kwargs in call_args:
            assert kwargs.get("timeout") == _SUBPROCESS_TIMEOUT, f"Wrong timeout in: {kwargs}"

    def test_git_push_uses_timeout(self, isolated_sagtask, monkeypatch):
        call_args = []

        def fake_run(cmd, **kwargs):
            call_args.append(kwargs)
            mock = MagicMock()
            mock.returncode = 0
            mock.stdout = ""
            mock.stderr = ""
            return mock

        monkeypatch.setattr("subprocess.run", fake_run)
        isolated_sagtask.git_push("test-timeout")

        for kwargs in call_args:
            assert kwargs.get("timeout") == _SUBPROCESS_TIMEOUT, f"Wrong timeout in: {kwargs}"
