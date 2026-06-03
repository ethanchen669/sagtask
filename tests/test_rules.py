"""Tests for the rules module."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import sagtask
from sagtask.rules import (
    DEFAULT_RULES,
    build_rules_context_line,
    get_default_rule_ids,
    handle_sag_task_rules,
    load_global_rules,
    merge_rules,
    save_global_rules,
    select_rules_for_context,
)


# ── Default rules ───────────────────────────────────────────────────────────

class TestDefaultRules:
    def test_default_rules_count(self):
        assert len(DEFAULT_RULES) == 12

    def test_default_rules_have_required_fields(self):
        for r in DEFAULT_RULES:
            assert "id" in r
            assert "content" in r
            assert "category" in r
            assert r["enabled"] is True

    def test_default_rule_ids_unique(self):
        ids = [r["id"] for r in DEFAULT_RULES]
        assert len(ids) == len(set(ids))

    def test_get_default_rule_ids(self):
        ids = get_default_rule_ids()
        assert len(ids) == 12
        assert ids[0] == "rule-1"
        assert ids[-1] == "rule-12"


# ── Global rules persistence ───────────────────────────────────────────────

class TestGlobalRulesPersistence:
    def test_load_global_rules_creates_defaults(self, tmp_path):
        hermes_home = tmp_path / "hermes"
        hermes_home.mkdir(parents=True)
        data = load_global_rules(hermes_home)
        assert data["version"] == 1
        assert len(data["rules"]) == 12

    def test_save_and_load_global_rules(self, tmp_path):
        hermes_home = tmp_path / "hermes"
        hermes_home.mkdir(parents=True)
        custom = {"version": 1, "rules": [{"id": "r1", "content": "test", "category": "thinking", "enabled": True}]}
        save_global_rules(hermes_home, custom)
        loaded = load_global_rules(hermes_home)
        assert len(loaded["rules"]) == 1
        assert loaded["rules"][0]["id"] == "r1"

    def test_load_global_rules_handles_corrupt_file(self, tmp_path):
        hermes_home = tmp_path / "hermes"
        hermes_home.mkdir(parents=True)
        rules_path = hermes_home / "sag_tasks" / ".rules.json"
        rules_path.parent.mkdir(parents=True)
        rules_path.write_text("not json!!!")
        data = load_global_rules(hermes_home)
        assert len(data["rules"]) == 12  # fallback to defaults


# ── Merge rules ─────────────────────────────────────────────────────────────

class TestMergeRules:
    def test_merge_empty_task_rules(self):
        global_rules = [{"id": "rule-1", "content": "g1", "category": "c", "enabled": True}]
        merged = merge_rules(global_rules, [])
        assert len(merged) == 1
        assert merged[0]["content"] == "g1"

    def test_merge_task_overrides_global(self):
        global_rules = [{"id": "rule-1", "content": "global", "category": "c", "enabled": True}]
        task_rules = [{"id": "rule-1", "content": "overridden", "category": "c", "enabled": True}]
        merged = merge_rules(global_rules, task_rules)
        assert len(merged) == 1
        assert merged[0]["content"] == "overridden"

    def test_merge_adds_task_rules(self):
        global_rules = [{"id": "rule-1", "content": "g", "category": "c", "enabled": True}]
        task_rules = [{"id": "custom-1", "content": "t", "category": "c", "enabled": True}]
        merged = merge_rules(global_rules, task_rules)
        assert len(merged) == 2
        ids = {r["id"] for r in merged}
        assert "rule-1" in ids
        assert "custom-1" in ids


# ── Smart selection ─────────────────────────────────────────────────────────

class TestSmartSelection:
    def _all_rules(self):
        return list(DEFAULT_RULES)

    def test_first_turn_returns_all(self):
        selected = select_rules_for_context(self._all_rules(), is_first_turn=True)
        assert len(selected) == 12

    def test_tdd_selects_rule9(self):
        selected = select_rules_for_context(self._all_rules(), methodology="tdd")
        ids = {r["id"] for r in selected}
        assert "rule-9" in ids

    def test_brainstorm_selects_rules(self):
        selected = select_rules_for_context(self._all_rules(), methodology="brainstorm")
        ids = {r["id"] for r in selected}
        assert "rule-1" in ids
        assert "rule-7" in ids

    def test_debug_selects_rules(self):
        selected = select_rules_for_context(self._all_rules(), methodology="debug")
        ids = {r["id"] for r in selected}
        assert "rule-12" in ids
        assert "rule-4" in ids

    def test_pending_gates_selects_rules(self):
        selected = select_rules_for_context(self._all_rules(), has_pending_gates=True)
        ids = {r["id"] for r in selected}
        assert "rule-3" in ids
        assert "rule-10" in ids

    def test_no_special_state_returns_core(self):
        selected = select_rules_for_context(self._all_rules())
        ids = {r["id"] for r in selected}
        assert ids == {"rule-1", "rule-2", "rule-12"}

    def test_disabled_rules_excluded(self):
        rules = self._all_rules()
        rules[0]["enabled"] = False  # disable rule-1
        selected = select_rules_for_context(rules, is_first_turn=True)
        ids = {r["id"] for r in selected}
        assert "rule-1" not in ids
        assert len(selected) == 11


# ── Context line builder ────────────────────────────────────────────────────

class TestContextLineBuilder:
    def test_empty_rules_returns_empty(self):
        assert build_rules_context_line([]) == ""

    def test_single_rule(self):
        rules = [{"id": "rule-1", "content": "test rule", "category": "c", "enabled": True}]
        line = build_rules_context_line(rules)
        assert line.startswith("- Rules: ")
        assert "[rule-1]" in line
        assert "test rule" in line

    def test_multiple_rules(self):
        rules = [
            {"id": "rule-1", "content": "first", "category": "c", "enabled": True},
            {"id": "rule-2", "content": "second", "category": "c", "enabled": True},
        ]
        line = build_rules_context_line(rules)
        assert "[rule-1]" in line
        assert "[rule-2]" in line
        assert " | " in line

    def test_long_content_truncated(self):
        rules = [{"id": "rule-1", "content": "x" * 100, "category": "c", "enabled": True}]
        line = build_rules_context_line(rules)
        assert "..." in line


# ── Tool handler ────────────────────────────────────────────────────────────

class TestRulesHandler:
    @pytest.fixture
    def setup(self, isolated_sagtask, mock_git, sample_phases):
        p = isolated_sagtask
        result = sagtask._handle_sag_task_create(
            {"sag_task_id": "test-rules", "name": "Test", "phases": sample_phases}
        )
        assert result["ok"]
        return p

    def test_list_global_rules(self, setup):
        result = handle_sag_task_rules({"action": "list"})
        assert result["ok"]
        assert result["count"] == 12

    def test_list_task_rules(self, setup):
        result = handle_sag_task_rules({"action": "list", "task_id": "test-rules"})
        assert result["ok"]
        # Task has 12 default rule references, but they are just {"id": "rule-N"} stubs
        # Merge with global defaults should produce 12 rules
        assert result["count"] == 12

    def test_add_global_rule(self, setup):
        result = handle_sag_task_rules({
            "action": "add", "content": "test global rule", "category": "quality"
        })
        assert result["ok"]
        assert result["scope"] == "global"
        # Verify it persists
        listed = handle_sag_task_rules({"action": "list"})
        assert listed["count"] == 13

    def test_add_task_rule(self, setup):
        result = handle_sag_task_rules({
            "action": "add", "content": "task only rule", "task_id": "test-rules", "rule_id": "custom-1"
        })
        assert result["ok"]
        assert result["scope"] == "task"

    def test_update_rule(self, setup):
        handle_sag_task_rules({
            "action": "add", "content": "original", "rule_id": "upd-1"
        })
        result = handle_sag_task_rules({
            "action": "update", "rule_id": "upd-1", "content": "updated"
        })
        assert result["ok"]

    def test_remove_rule(self, setup):
        handle_sag_task_rules({
            "action": "add", "content": "to remove", "rule_id": "rm-1"
        })
        result = handle_sag_task_rules({
            "action": "remove", "rule_id": "rm-1"
        })
        assert result["ok"]

    def test_toggle_rule(self, setup):
        # Toggle a default rule
        result = handle_sag_task_rules({
            "action": "toggle", "rule_id": "rule-1", "task_id": "test-rules"
        })
        assert result["ok"]

    def test_add_requires_content(self, setup):
        result = handle_sag_task_rules({"action": "add"})
        assert not result["ok"]
        assert "content" in result["error"]

    def test_update_requires_rule_id(self, setup):
        result = handle_sag_task_rules({"action": "update", "content": "x"})
        assert not result["ok"]
        assert "rule_id" in result["error"]

    def test_unknown_action(self, setup):
        result = handle_sag_task_rules({"action": "bogus"})
        assert not result["ok"]
        assert "Unknown action" in result["error"]


# ── Create task includes rules ──────────────────────────────────────────────

class TestCreateTaskRules:
    def test_create_includes_default_rules(self, isolated_sagtask, mock_git, sample_phases):
        result = sagtask._handle_sag_task_create(
            {"sag_task_id": "rules-check", "name": "Test", "phases": sample_phases}
        )
        assert result["ok"]
        p = isolated_sagtask
        state = p.load_task_state("rules-check")
        assert "rules" in state
        assert len(state["rules"]) == 12
        assert state["rules"][0]["id"] == "rule-1"
