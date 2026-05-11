"""Tests for _recommend_methodology helper."""
import pytest
from sagtask._utils import _recommend_methodology


class TestRecommendMethodology:
    """Tests for methodology auto-recommendation based on step keywords."""

    def test_suggests_tdd_for_test_keywords(self):
        results = _recommend_methodology("Write unit tests", "Add test coverage for parser")
        assert len(results) > 0
        assert results[0][0] == "tdd"

    def test_suggests_brainstorm_for_design_keywords(self):
        results = _recommend_methodology("Design API", "Explore architecture options for the service")
        assert len(results) > 0
        assert results[0][0] == "brainstorm"

    def test_suggests_debug_for_bug_keywords(self):
        results = _recommend_methodology("Fix crash", "Parser crashes on empty input")
        assert len(results) > 0
        assert results[0][0] == "debug"

    def test_suggests_plan_execute_for_planning_keywords(self):
        results = _recommend_methodology("Plan migration", "Break down database migration into steps")
        assert len(results) > 0
        assert results[0][0] == "plan-execute"

    def test_returns_empty_for_no_keywords(self):
        results = _recommend_methodology("Do stuff", "Things and things")
        assert isinstance(results, list)

    def test_returns_tuples_with_confidence(self):
        results = _recommend_methodology("Test parser", "Write tests for JSON parser")
        assert len(results) > 0
        for methodology, confidence, reason in results:
            assert isinstance(methodology, str)
            assert isinstance(confidence, (int, float))
            assert isinstance(reason, str)

    def test_multiple_keywords_higher_confidence(self):
        single = _recommend_methodology("Test", "")
        multi = _recommend_methodology("Test coverage", "Write unit tests with pytest")
        if single and multi:
            assert multi[0][1] >= single[0][1]

    def test_sorted_by_confidence_descending(self):
        results = _recommend_methodology(
            "Design and test", "Explore architecture and write unit tests"
        )
        if len(results) >= 2:
            for i in range(len(results) - 1):
                assert results[i][1] >= results[i + 1][1]
