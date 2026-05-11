"""Shared constants and utility functions for SagTask."""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Optional

logger = __import__("logging").getLogger(__name__)

SAGTASK_PROVIDER = "sagtask"
_TASK_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_DEFAULT_GITHUB_OWNER = "ethanchen669"
_SUBPROCESS_TIMEOUT = 30
_VERIFY_OUTPUT_MAX_LEN = 2000
SCHEMA_VERSION = 2

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
