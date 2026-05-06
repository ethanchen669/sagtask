"""Tests for sag_task_id input validation."""
import pytest
from sagtask import _validate_task_id


class TestValidateTaskId:
    def test_valid_ids(self):
        assert _validate_task_id("my-task") is None
        assert _validate_task_id("task_v2") is None
        assert _validate_task_id("sc-mrp-v1") is None
        assert _validate_task_id("a") is None
        assert _validate_task_id("A1b2C3") is None

    def test_rejects_empty(self):
        assert _validate_task_id("") == "task_id cannot be empty"

    def test_rejects_path_traversal(self):
        assert _validate_task_id("../../etc") == "Invalid task_id format"
        assert _validate_task_id("..%2F..%2Fetc") == "Invalid task_id format"

    def test_rejects_special_chars(self):
        assert _validate_task_id("task name") == "Invalid task_id format"
        assert _validate_task_id("task@name") == "Invalid task_id format"
        assert _validate_task_id("task/name") == "Invalid task_id format"

    def test_rejects_too_long(self):
        long_id = "a" * 64
        assert _validate_task_id(long_id) is None
        too_long = "a" * 65
        assert _validate_task_id(too_long) == "task_id must be 64 characters or less"

    def test_rejects_starting_with_hyphen(self):
        assert _validate_task_id("-task") == "Invalid task_id format"
