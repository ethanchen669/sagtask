"""Tests for sag_task_review tool."""
import json
import pytest
import sagtask


class TestReview:
    def _create_task_with_step(self, plugin, mock_git):
        sagtask._handle_sag_task_create({
            "sag_task_id": "test-review",
            "name": "Test Review",
            "phases": [{
                "id": "phase-1",
                "name": "Phase 1",
                "steps": [{
                    "id": "step-1",
                    "name": "Build Parser",
                    "description": "Build a JSON parser",
                    "methodology": {"type": "tdd", "config": {"coverage_threshold": 80}},
                    "verification": {"commands": ["pytest"], "must_pass": True},
                }],
            }],
        })

    def test_review_returns_context(self, isolated_sagtask, mock_git):
        self._create_task_with_step(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_review({
            "sag_task_id": "test-review",
            "scope": "step",
        })
        assert result["ok"] is True
        assert "context" in result
        assert "scope" in result

    def test_review_includes_spec_criteria(self, isolated_sagtask, mock_git):
        self._create_task_with_step(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_review({
            "sag_task_id": "test-review",
            "scope": "step",
        })
        context = result["context"].lower()
        assert "spec" in context or "requirement" in context or "verification" in context

    def test_review_includes_quality_criteria(self, isolated_sagtask, mock_git):
        self._create_task_with_step(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_review({
            "sag_task_id": "test-review",
            "scope": "step",
        })
        context = result["context"].lower()
        assert "quality" in context or "readable" in context or "test" in context

    def test_review_scope_step(self, isolated_sagtask, mock_git):
        self._create_task_with_step(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_review({
            "sag_task_id": "test-review",
            "scope": "step",
        })
        assert result["scope"] == "step"
        assert "Build Parser" in result["context"]

    def test_review_scope_phase(self, isolated_sagtask, mock_git):
        self._create_task_with_step(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_review({
            "sag_task_id": "test-review",
            "scope": "phase",
        })
        assert result["scope"] == "phase"
        assert "Phase 1" in result["context"]

    def test_review_default_scope(self, isolated_sagtask, mock_git):
        self._create_task_with_step(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_review({
            "sag_task_id": "test-review",
        })
        assert result["ok"] is True
        assert result["scope"] == "step"

    def test_review_no_task(self, isolated_sagtask, mock_git):
        result = sagtask._handle_sag_task_review({"scope": "step"})
        assert result["ok"] is False
        assert "error" in result

    def test_review_includes_verification_commands(self, isolated_sagtask, mock_git):
        self._create_task_with_step(isolated_sagtask, mock_git)
        result = sagtask._handle_sag_task_review({
            "sag_task_id": "test-review",
            "scope": "step",
        })
        assert "pytest" in result["context"]
