"""Rules module — development rules with smart context injection."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── 12 built-in default rules ───────────────────────────────────────────────

DEFAULT_RULES: List[Dict[str, Any]] = [
    {
        "id": "rule-1",
        "content": "先思考再编码。明确假设，不确定时提问，存在歧义时展示多种方案。",
        "category": "thinking",
        "enabled": True,
    },
    {
        "id": "rule-2",
        "content": "简单优先。最小代码解决问题，不做投机性设计，不做未请求的功能。",
        "category": "thinking",
        "enabled": True,
    },
    {
        "id": "rule-3",
        "content": "精准变更。只动必要的代码，不重构未请求的部分，匹配现有风格。",
        "category": "process",
        "enabled": True,
    },
    {
        "id": "rule-4",
        "content": "目标驱动。定义验证标准，循环直到达标，而非按死板步骤执行。",
        "category": "process",
        "enabled": True,
    },
    {
        "id": "rule-5",
        "content": "LLM 只做判断。分类、起草、摘要、提取用 LLM，路由、重试、确定性转换用代码。",
        "category": "quality",
        "enabled": True,
    },
    {
        "id": "rule-6",
        "content": "Token 预算不可超。每任务 4000，每会话 30000，接近上限时摘要并重启。",
        "category": "quality",
        "enabled": True,
    },
    {
        "id": "rule-7",
        "content": "暴露冲突，不取平均。模式矛盾时选一个并解释，标记另一个待清理。",
        "category": "thinking",
        "enabled": True,
    },
    {
        "id": "rule-8",
        "content": "先读后写。添加代码前检查导出、调用者、共享工具，不清楚就问。",
        "category": "process",
        "enabled": True,
    },
    {
        "id": "rule-9",
        "content": "测试验证意图。测试应编码行为为何重要，不能因业务逻辑变更而仍然通过。",
        "category": "quality",
        "enabled": True,
    },
    {
        "id": "rule-10",
        "content": "每步检查点。总结进度、验证状态、剩余工作，迷失时停下重述位置。",
        "category": "process",
        "enabled": True,
    },
    {
        "id": "rule-11",
        "content": "匹配代码库惯例。一致性优先于个人偏好，有分歧显式提出而非静默修改。",
        "category": "style",
        "enabled": True,
    },
    {
        "id": "rule-12",
        "content": "失败大声说。跳过测试却说「测试通过」是误导，默认暴露不确定性。",
        "category": "quality",
        "enabled": True,
    },
]

_DEFAULT_RULE_IDS = [r["id"] for r in DEFAULT_RULES]

# ── Smart selection mapping ─────────────────────────────────────────────────

_METHODOLOGY_RULES: Dict[str, List[str]] = {
    "tdd": ["rule-9"],
    "brainstorm": ["rule-1", "rule-7"],
    "debug": ["rule-12", "rule-4"],
    "plan-execute": ["rule-4", "rule-10"],
    "review": ["rule-3", "rule-11"],
    "parallel-agents": ["rule-5", "rule-10"],
}

_GATE_RULES = ["rule-3", "rule-10"]
_DEFAULT_CORE_RULES = ["rule-1", "rule-2", "rule-12"]


# ── Global rules persistence ───────────────────────────────────────────────

def _global_rules_path(hermes_home: Path) -> Path:
    return hermes_home / "sag_tasks" / ".rules.json"


def load_global_rules(hermes_home: Path) -> Dict[str, Any]:
    """Load global rules from ~/.hermes/sag_tasks/.rules.json."""
    path = _global_rules_path(hermes_home)
    if not path.exists():
        return {"version": 1, "rules": list(DEFAULT_RULES)}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data.get("rules"), list):
            return {"version": 1, "rules": list(DEFAULT_RULES)}
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load global rules: %s", e)
        return {"version": 1, "rules": list(DEFAULT_RULES)}


def save_global_rules(hermes_home: Path, rules_data: Dict[str, Any]) -> None:
    """Atomic write global rules."""
    path = _global_rules_path(hermes_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rules_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


# ── Merge & select ─────────────────────────────────────────────────────────

def merge_rules(global_rules: List[Dict[str, Any]], task_rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge global defaults with task overrides. Task rules win on same id.
    Task rules that are just stubs (only 'id', no 'content') are skipped
    and the global version is kept."""
    by_id: Dict[str, Dict[str, Any]] = {}
    for r in global_rules:
        by_id[r["id"]] = dict(r)
    for r in task_rules:
        if "content" in r:
            by_id[r["id"]] = dict(r)
        elif r["id"] not in by_id:
            by_id[r["id"]] = dict(r)
    return list(by_id.values())


def select_rules_for_context(
    all_rules: List[Dict[str, Any]],
    *,
    methodology: str = "none",
    has_pending_gates: bool = False,
    is_first_turn: bool = False,
) -> List[Dict[str, Any]]:
    """Smart selection based on methodology, gates, and turn state."""
    enabled = [r for r in all_rules if r.get("enabled", True)]
    enabled_ids = {r["id"] for r in enabled}

    if is_first_turn:
        return enabled

    candidate_ids: set = set()

    if methodology in _METHODOLOGY_RULES:
        candidate_ids.update(_METHODOLOGY_RULES[methodology])

    if has_pending_gates:
        candidate_ids.update(_GATE_RULES)

    if not candidate_ids:
        candidate_ids.update(_DEFAULT_CORE_RULES)

    return [r for r in enabled if r["id"] in candidate_ids and r["id"] in enabled_ids]


def build_rules_context_line(rules: List[Dict[str, Any]]) -> str:
    """Format selected rules as L2.5 context line."""
    if not rules:
        return ""
    parts = []
    for r in rules:
        rid = r["id"]
        content = r["content"]
        # Truncate long rules for context efficiency
        if len(content) > 60:
            content = content[:57] + "..."
        parts.append(f"[{rid}] {content}")
    return "- Rules: " + " | ".join(parts)


# ── Default rule IDs for new tasks ─────────────────────────────────────────

def get_default_rule_ids() -> List[str]:
    """Return the list of default rule IDs to embed in new task state."""
    return list(_DEFAULT_RULE_IDS)


# ── Tool handler ───────────────────────────────────────────────────────────

def handle_sag_task_rules(args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """Tool handler: list / add / update / remove / toggle rules."""
    from ._utils import _get_provider

    p = _get_provider()
    action = args.get("action", "list")
    task_id = args.get("task_id")
    rule_id = args.get("rule_id", "")
    content = args.get("content", "")
    category = args.get("category", "thinking")
    enabled = args.get("enabled", True)

    if action == "list":
        global_data = load_global_rules(p._hermes_home)
        global_rules = global_data.get("rules", [])
        effective_task_id = task_id or p._active_task_id

        if effective_task_id:
            state = p.load_task_state(effective_task_id)
            task_rules = state.get("rules", [])
            merged = merge_rules(global_rules, task_rules)
        else:
            merged = global_rules

        return {
            "ok": True,
            "rules": [
                {"id": r["id"], "content": r["content"], "category": r.get("category", ""), "enabled": r.get("enabled", True)}
                for r in merged
            ],
            "count": len(merged),
        }

    if action == "add":
        if not content:
            return {"ok": False, "error": "content is required for add"}

        new_id = rule_id or f"rule-custom-{os.urandom(4).hex()}"
        new_rule = {"id": new_id, "content": content, "category": category, "enabled": enabled}

        if task_id:
            state = p.load_task_state(task_id)
            task_rules = state.get("rules", [])
            # Check duplicate
            if any(r["id"] == new_id for r in task_rules):
                return {"ok": False, "error": f"Rule '{new_id}' already exists in task"}
            task_rules.append(new_rule)
            state["rules"] = task_rules
            p.save_task_state(task_id, state)
            return {"ok": True, "rule": new_rule, "scope": "task", "task_id": task_id}
        else:
            global_data = load_global_rules(p._hermes_home)
            rules = global_data.get("rules", [])
            if any(r["id"] == new_id for r in rules):
                return {"ok": False, "error": f"Rule '{new_id}' already exists globally"}
            rules.append(new_rule)
            global_data["rules"] = rules
            save_global_rules(p._hermes_home, global_data)
            return {"ok": True, "rule": new_rule, "scope": "global"}

    if action == "update":
        if not rule_id:
            return {"ok": False, "error": "rule_id is required for update"}
        if not content:
            return {"ok": False, "error": "content is required for update"}

        if task_id:
            state = p.load_task_state(task_id)
            task_rules = state.get("rules", [])
            found = False
            for r in task_rules:
                if r["id"] == rule_id:
                    r["content"] = content
                    if category:
                        r["category"] = category
                    found = True
                    break
            if not found:
                task_rules.append({"id": rule_id, "content": content, "category": category, "enabled": enabled})
            state["rules"] = task_rules
            p.save_task_state(task_id, state)
            return {"ok": True, "rule_id": rule_id, "scope": "task"}
        else:
            global_data = load_global_rules(p._hermes_home)
            rules = global_data.get("rules", [])
            found = False
            for r in rules:
                if r["id"] == rule_id:
                    r["content"] = content
                    if category:
                        r["category"] = category
                    found = True
                    break
            if not found:
                return {"ok": False, "error": f"Rule '{rule_id}' not found globally"}
            global_data["rules"] = rules
            save_global_rules(p._hermes_home, global_data)
            return {"ok": True, "rule_id": rule_id, "scope": "global"}

    if action == "remove":
        if not rule_id:
            return {"ok": False, "error": "rule_id is required for remove"}

        if task_id:
            state = p.load_task_state(task_id)
            task_rules = state.get("rules", [])
            state["rules"] = [r for r in task_rules if r["id"] != rule_id]
            p.save_task_state(task_id, state)
            return {"ok": True, "removed": rule_id, "scope": "task"}
        else:
            global_data = load_global_rules(p._hermes_home)
            rules = global_data.get("rules", [])
            global_data["rules"] = [r for r in rules if r["id"] != rule_id]
            save_global_rules(p._hermes_home, global_data)
            return {"ok": True, "removed": rule_id, "scope": "global"}

    if action == "toggle":
        if not rule_id:
            return {"ok": False, "error": "rule_id is required for toggle"}

        if task_id:
            state = p.load_task_state(task_id)
            task_rules = state.get("rules", [])
            for r in task_rules:
                if r["id"] == rule_id:
                    r["enabled"] = not r.get("enabled", True)
                    break
            else:
                return {"ok": False, "error": f"Rule '{rule_id}' not found in task"}
            state["rules"] = task_rules
            p.save_task_state(task_id, state)
            return {"ok": True, "rule_id": rule_id, "scope": "task"}
        else:
            global_data = load_global_rules(p._hermes_home)
            rules = global_data.get("rules", [])
            for r in rules:
                if r["id"] == rule_id:
                    r["enabled"] = not r.get("enabled", True)
                    break
            else:
                return {"ok": False, "error": f"Rule '{rule_id}' not found globally"}
            global_data["rules"] = rules
            save_global_rules(p._hermes_home, global_data)
            return {"ok": True, "rule_id": rule_id, "scope": "global"}

    return {"ok": False, "error": f"Unknown action: {action}. Use list/add/update/remove/toggle."}
