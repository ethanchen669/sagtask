"""Shared constants and utility functions for SagTask."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = __import__("logging").getLogger(__name__)

SAGTASK_PROVIDER = "sagtask"
_TASK_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_DEFAULT_GITHUB_OWNER = "ethanchen669"
_SUBPROCESS_TIMEOUT = 30
_VERIFY_OUTPUT_MAX_LEN = 2000
SCHEMA_VERSION = 2

# Debug phase constants
DEBUG_PHASE_REPRODUCE = "reproduce"
DEBUG_PHASE_DIAGNOSE = "diagnose"
DEBUG_PHASE_FIX = "fix"

_sagtask_instance: Optional["SagTaskPlugin"] = None


def _validate_task_id(task_id: str) -> str | None:
    """Validate task_id format. Returns error message or None if valid."""
    if not task_id:
        return "task_id cannot be empty"
    if len(task_id) > 64:
        return "task_id must be 64 characters or less"
    if not _TASK_ID_RE.match(task_id):
        return "Invalid task_id format"
    return None


def _get_github_owner() -> str:
    """Return GitHub owner from SAGTASK_GITHUB_OWNER env var or default."""
    return os.environ.get("SAGTASK_GITHUB_OWNER", _DEFAULT_GITHUB_OWNER)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _get_provider() -> "SagTaskPlugin":
    """Get the registered SagTaskPlugin instance (set by register())."""
    if _sagtask_instance is None:
        raise RuntimeError("SagTaskPlugin not registered. Call register(ctx) first.")
    return _sagtask_instance


def _load_plan(plan_path: Path) -> Optional[Dict[str, Any]]:
    """Load and return plan JSON, or None on error."""
    if not plan_path.exists():
        return None
    try:
        return json.loads(plan_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


# Methodology recommendation keywords
_METHODOLOGY_KEYWORDS: Dict[str, Dict[str, Any]] = {
    "tdd": {
        "keywords": ["test", "coverage", "unit test", "pytest", "spec", "assert", "tdd"],
        "reason": "Step involves testing or test-driven development",
    },
    "brainstorm": {
        "keywords": ["design", "explore", "architect", "option", "trade-off", "evaluate", "compare"],
        "reason": "Step involves design exploration or evaluation",
    },
    "debug": {
        "keywords": ["bug", "fix", "crash", "error", "broken", "fail", "regression", "debug"],
        "reason": "Step involves fixing a bug or debugging",
    },
    "plan-execute": {
        "keywords": ["plan", "break down", "decompose", "migration", "refactor", "phase"],
        "reason": "Step involves planning or breaking work into phases",
    },
}


def _recommend_methodology(
    step_name: str, step_description: str
) -> List[Tuple[str, float, str]]:
    """Recommend methodology based on step name and description.

    Returns list of (methodology, confidence, reason) sorted by confidence descending.
    """
    text = f"{step_name} {step_description}".lower()
    results: List[Tuple[str, float, str]] = []

    for methodology, config in _METHODOLOGY_KEYWORDS.items():
        keywords = config["keywords"]
        matches = sum(1 for kw in keywords if kw in text)
        if matches > 0:
            confidence = min(matches / len(keywords), 1.0)
            results.append((methodology, confidence, config["reason"]))

    results.sort(key=lambda x: x[1], reverse=True)
    return results
