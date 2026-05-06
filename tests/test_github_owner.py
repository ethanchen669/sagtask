"""Tests for configurable GitHub owner."""
import pytest
from sagtask import _get_github_owner


class TestGetGitHubOwner:
    def test_returns_env_var_when_set(self, monkeypatch):
        monkeypatch.setenv("SAGTASK_GITHUB_OWNER", "myorg")
        assert _get_github_owner() == "myorg"

    def test_returns_default_when_env_not_set(self, monkeypatch):
        monkeypatch.delenv("SAGTASK_GITHUB_OWNER", raising=False)
        assert _get_github_owner() == "ethanchen669"
