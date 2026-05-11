# Modularize `__init__.py` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the 2023-line `__init__.py` into focused modules while maintaining 100% backward compatibility for all existing tests.

**Architecture:** Move code into focused modules (`_utils.py`, `schemas.py`, `plugin.py`, `handlers/`, `hooks.py`), then re-export everything from `__init__.py` so `import sagtask` + `sagtask._handle_sag_task_*` still works. Each task extracts one module, runs full test suite to verify no regressions, and commits.

**Tech Stack:** Python 3.10+, pytest

---

## File Structure

```
src/sagtask/
├── __init__.py          ← Thin re-export layer (~80 lines)
├── _utils.py            ← _validate_task_id, _get_github_owner, _utcnow_iso, _get_provider, constants
├── schemas.py           ← All 14 tool schemas + ALL_TOOL_SCHEMAS list
├── plugin.py            ← SagTaskPlugin class
├── handlers/
│   ├── __init__.py      ← _tool_handlers dispatch map + re-exports
│   ├── _lifecycle.py    ← create, status, pause, resume, advance, approve
│   ├── _git.py          ← list, commit, branch, git_log
│   └── _plan.py         ← relate, verify, plan, plan_update (TDD state machine stays with verify)
├── hooks.py             ← _on_pre_llm_call, _on_session_start
```

**Backward compatibility:** `__init__.py` re-exports every symbol that tests currently access via `import sagtask` or `from sagtask import ...`. Zero test changes required.

---

### Task 1: Create `_utils.py` — shared constants and helpers

**Files:**
- Create: `src/sagtask/_utils.py`
- Modify: `src/sagtask/__init__.py` (remove moved code, import from `_utils`)
- Modify: `tests/conftest.py` (set `_utils._sagtask_instance` in fixture)

**Context:** Extract the shared constants and utility functions that both `plugin.py` and `handlers/` need. `_get_provider()` is the critical piece — handlers call it to access the singleton.

- [ ] **Step 1: Create `src/sagtask/_utils.py`**

```python
"""Shared constants and utility functions for SagTask."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .plugin import SagTaskPlugin

logger = __import__("logging").getLogger(__name__)

SUBPROCESS_TIMEOUT = 30
VERIFY_OUTPUT_MAX_LEN = 2000
SCHEMA_VERSION = 2

_TASK_ID_RE = re.compile(r"^[a-zA-Z0-9-]{1,64}$")

_sagtask_instance: Optional["SagTaskPlugin"] = None


def _validate_task_id(task_id: str) -> str | None:
    """Validate task_id format. Returns error message or None."""
    if not task_id:
        return "task_id is required"
    if len(task_id) > 64:
        return f"task_id too long ({len(task_id)} > 64 chars)"
    if not _TASK_ID_RE.match(task_id):
        return f"task_id must be alphanumeric with hyphens, got: {task_id!r}"
    return None


def _get_github_owner() -> str:
    """Return the configured GitHub owner for repo creation."""
    import os
    return os.environ.get("SAGTASK_GITHUB_OWNER", "ethanchen669")


def _utcnow_iso() -> str:
    """Return current UTC time as ISO 8601 with Z suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _get_provider() -> "SagTaskPlugin":
    """Return the singleton SagTaskPlugin instance."""
    if _sagtask_instance is None:
        raise RuntimeError("SagTaskPlugin not registered. Call register(ctx) first.")
    return _sagtask_instance
```

- [ ] **Step 2: Update `__init__.py` to import from `_utils`**

Replace the constants and utility function definitions in `__init__.py` with imports:

```python
# At the top of __init__.py, after the docstring and stdlib imports:
from sagtask import _utils as _utils  # import module for mutation access
from sagtask._utils import (
    SCHEMA_VERSION,
    SUBPROCESS_TIMEOUT,
    VERIFY_OUTPUT_MAX_LEN,
    _get_github_owner,
    _get_provider,
    _utcnow_iso,
    _validate_task_id,
)
```

**Critical:** Do NOT `from sagtask._utils import _sagtask_instance` — that creates a local copy that goes stale. Instead, `register()` will set `_utils._sagtask_instance` directly (see Task 8). `_get_provider()` in `_utils.py` reads `_utils._sagtask_instance`, so they stay in sync.

For test backward compatibility (`sagtask._sagtask_instance`), add a property-like re-export in `__init__.py`:

```python
# Re-export for test compatibility: sagtask._sagtask_instance = None
_sagtask_instance = None
```

And in `register()` (Task 8), set both `_utils._sagtask_instance` and the module-level `_sagtask_instance`.

Remove from `__init__.py`:
- `_SUBPROCESS_TIMEOUT` constant (line ~38)
- `_VERIFY_OUTPUT_MAX_LEN` constant (line ~40)
- `SCHEMA_VERSION` constant (line ~42)
- `_validate_task_id` function (lines 46-58)
- `_get_github_owner` function (lines 60-69)
- `_utcnow_iso` function (lines 71-73)
- `_sagtask_instance` declaration (lines 469-470)
- `_get_provider` function (lines 472-477)
- `_TASK_ID_RE` regex (line ~44)

- [ ] **Step 3: Update `tests/conftest.py`**

The `isolated_sagtask` fixture must set `_utils._sagtask_instance` so `_get_provider()` works in tests:

```python
@pytest.fixture
def isolated_sagtask(tmp_path):
    """Create an isolated SagTaskPlugin with tmp_path as projects_root."""
    sagtask._sagtask_instance = None
    sagtask._utils._sagtask_instance = None
    plugin = sagtask.SagTaskPlugin()
    plugin._hermes_home = tmp_path / "hermes"
    plugin._projects_root = tmp_path / "hermes" / "sag_tasks"
    plugin._projects_root.mkdir(parents=True)
    sagtask._sagtask_instance = plugin
    sagtask._utils._sagtask_instance = plugin
    yield plugin
    sagtask._sagtask_instance = None
    sagtask._utils._sagtask_instance = None
```

- [ ] **Step 4: Run full test suite**

Run: `PYTHONPATH=src python -m pytest tests/ --tb=short`
Expected: All 152 PASS (no regressions)

- [ ] **Step 5: Commit**

```bash
git add src/sagtask/_utils.py src/sagtask/__init__.py tests/conftest.py
git commit -m "refactor: extract _utils.py — shared constants and helpers"
```

---

### Task 2: Create `schemas.py` — all tool schema definitions

**Files:**
- Create: `src/sagtask/schemas.py`
- Modify: `src/sagtask/__init__.py` (remove schemas, import from `schemas`)

**Context:** Tool schemas are pure data dicts with no logic. They can be extracted cleanly with zero dependencies on other sagtask modules.

- [ ] **Step 1: Create `src/sagtask/schemas.py`**

Read lines 76-463 from `__init__.py` (the 14 `TASK_*_SCHEMA` dicts + `ALL_TOOL_SCHEMAS` list) and move them into `schemas.py`:

```python
"""Tool schema definitions for SagTask."""
from __future__ import annotations
from typing import Any, Dict, List

# ── Task Create ────────────────────────────────────────────────────────────
TASK_CREATE_SCHEMA: Dict[str, Any] = {
    # ... exact content from __init__.py ...
}

# ... all 14 schemas ...

ALL_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    TASK_CREATE_SCHEMA,
    TASK_STATUS_SCHEMA,
    TASK_PAUSE_SCHEMA,
    TASK_RESUME_SCHEMA,
    TASK_ADVANCE_SCHEMA,
    TASK_APPROVE_SCHEMA,
    TASK_LIST_SCHEMA,
    TASK_COMMIT_SCHEMA,
    TASK_BRANCH_SCHEMA,
    TASK_GIT_LOG_SCHEMA,
    TASK_RELATE_SCHEMA,
    TASK_VERIFY_SCHEMA,
    TASK_PLAN_SCHEMA,
    TASK_PLAN_UPDATE_SCHEMA,
]
```

- [ ] **Step 2: Update `__init__.py` to import from `schemas`**

Replace lines 76-463 with:

```python
from sagtask.schemas import (
    ALL_TOOL_SCHEMAS,
    TASK_ADVANCE_SCHEMA,
    TASK_APPROVE_SCHEMA,
    TASK_BRANCH_SCHEMA,
    TASK_COMMIT_SCHEMA,
    TASK_CREATE_SCHEMA,
    TASK_GIT_LOG_SCHEMA,
    TASK_LIST_SCHEMA,
    TASK_PAUSE_SCHEMA,
    TASK_PLAN_SCHEMA,
    TASK_PLAN_UPDATE_SCHEMA,
    TASK_RELATE_SCHEMA,
    TASK_RESUME_SCHEMA,
    TASK_STATUS_SCHEMA,
    TASK_VERIFY_SCHEMA,
)
```

- [ ] **Step 3: Run full test suite**

Run: `PYTHONPATH=src python -m pytest tests/ --tb=short`
Expected: All 152 PASS

- [ ] **Step 4: Commit**

```bash
git add src/sagtask/schemas.py src/sagtask/__init__.py
git commit -m "refactor: extract schemas.py — tool schema definitions"
```

---

### Task 3: Create `plugin.py` — SagTaskPlugin class

**Files:**
- Create: `src/sagtask/plugin.py`
- Modify: `src/sagtask/__init__.py` (remove class, import from `plugin`)

**Context:** The plugin class contains all instance methods and static helper methods. It depends on `_utils` for constants and helpers.

- [ ] **Step 1: Create `src/sagtask/plugin.py`**

Move the `SagTaskPlugin` class (lines 484-1117 of `__init__.py`) into `plugin.py`:

```python
"""SagTaskPlugin — core plugin class for task management."""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._utils import (
    SCHEMA_VERSION,
    SUBPROCESS_TIMEOUT,
    _get_github_owner,
    _utcnow_iso,
)

logger = logging.getLogger(__name__)


class SagTaskPlugin:
    """Hermes plugin that provides per-task Git repos with lifecycle management."""

    # ... exact content of the class from __init__.py ...
```

- [ ] **Step 2: Update `__init__.py` to import from `plugin`**

Replace the class definition with:

```python
from sagtask.plugin import SagTaskPlugin
```

- [ ] **Step 3: Run full test suite**

Run: `PYTHONPATH=src python -m pytest tests/ --tb=short`
Expected: All 152 PASS

- [ ] **Step 4: Commit**

```bash
git add src/sagtask/plugin.py src/sagtask/__init__.py
git commit -m "refactor: extract plugin.py — SagTaskPlugin class"
```

---

### Task 4: Create `handlers/__init__.py` and `handlers/_lifecycle.py`

**Files:**
- Create: `src/sagtask/handlers/__init__.py`
- Create: `src/sagtask/handlers/_lifecycle.py`
- Modify: `src/sagtask/__init__.py` (remove lifecycle handlers, import from handlers)

**Context:** Lifecycle handlers manage task state transitions: create, status, pause, resume, advance, approve. These are the core CRUD operations.

- [ ] **Step 1: Create `src/sagtask/handlers/__init__.py`**

```python
"""SagTask tool handlers."""
from __future__ import annotations

from ._lifecycle import (
    _handle_sag_task_advance,
    _handle_sag_task_approve,
    _handle_sag_task_create,
    _handle_sag_task_pause,
    _handle_sag_task_resume,
    _handle_sag_task_status,
)
from ._git import (
    _handle_sag_task_branch,
    _handle_sag_task_commit,
    _handle_sag_task_git_log,
    _handle_sag_task_list,
)
from ._plan import (
    _handle_sag_task_plan,
    _handle_sag_task_plan_update,
    _handle_sag_task_relate,
    _handle_sag_task_verify,
)

_tool_handlers = {
    "sag_task_create": _handle_sag_task_create,
    "sag_task_status": _handle_sag_task_status,
    "sag_task_pause": _handle_sag_task_pause,
    "sag_task_resume": _handle_sag_task_resume,
    "sag_task_advance": _handle_sag_task_advance,
    "sag_task_approve": _handle_sag_task_approve,
    "sag_task_list": _handle_sag_task_list,
    "sag_task_commit": _handle_sag_task_commit,
    "sag_task_branch": _handle_sag_task_branch,
    "sag_task_git_log": _handle_sag_task_git_log,
    "sag_task_relate": _handle_sag_task_relate,
    "sag_task_verify": _handle_sag_task_verify,
    "sag_task_plan": _handle_sag_task_plan,
    "sag_task_plan_update": _handle_sag_task_plan_update,
}

__all__ = [
    "_tool_handlers",
    "_handle_sag_task_create",
    "_handle_sag_task_status",
    "_handle_sag_task_pause",
    "_handle_sag_task_resume",
    "_handle_sag_task_advance",
    "_handle_sag_task_approve",
    "_handle_sag_task_list",
    "_handle_sag_task_commit",
    "_handle_sag_task_branch",
    "_handle_sag_task_git_log",
    "_handle_sag_task_relate",
    "_handle_sag_task_verify",
    "_handle_sag_task_plan",
    "_handle_sag_task_plan_update",
]
```

- [ ] **Step 2: Create `src/sagtask/handlers/_lifecycle.py`**

Move these handlers from `__init__.py`:
- `_handle_sag_task_create` (line 1127)
- `_handle_sag_task_status` (line 1193)
- `_handle_sag_task_pause` (line 1240)
- `_handle_sag_task_resume` (line 1291)
- `_handle_sag_task_advance` (line 1345)
- `_handle_sag_task_approve` (line 1456)

```python
"""Lifecycle handlers — create, status, pause, resume, advance, approve."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from .._utils import _get_provider, _utcnow_iso, _validate_task_id

logger = logging.getLogger(__name__)

# ... exact content of the 6 handlers from __init__.py ...
```

- [ ] **Step 3: Update `__init__.py`**

Remove the 6 lifecycle handler functions and the `_tool_handlers` dict. Add:

```python
from sagtask.handlers import _tool_handlers  # noqa: F401 — re-export for register()
from sagtask.handlers._lifecycle import (  # noqa: F401 — re-export for tests
    _handle_sag_task_advance,
    _handle_sag_task_approve,
    _handle_sag_task_create,
    _handle_sag_task_pause,
    _handle_sag_task_resume,
    _handle_sag_task_status,
)
```

- [ ] **Step 4: Run full test suite**

Run: `PYTHONPATH=src python -m pytest tests/ --tb=short`
Expected: All 152 PASS

- [ ] **Step 5: Commit**

```bash
git add src/sagtask/handlers/ src/sagtask/__init__.py
git commit -m "refactor: extract handlers/_lifecycle.py — create, status, pause, resume, advance, approve"
```

---

### Task 5: Create `handlers/_git.py` — git operation handlers

**Files:**
- Create: `src/sagtask/handlers/_git.py`
- Modify: `src/sagtask/__init__.py` (remove git handlers)

**Context:** Git-related handlers: list, commit, branch, git_log.

- [ ] **Step 1: Create `src/sagtask/handlers/_git.py`**

Move these handlers from `__init__.py`:
- `_handle_sag_task_list` (line 1499)
- `_handle_sag_task_commit` (line 1529)
- `_handle_sag_task_branch` (line 1556)
- `_handle_sag_task_git_log` (line 1582)

```python
"""Git operation handlers — list, commit, branch, git_log."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from .._utils import _get_provider, _utcnow_iso, _validate_task_id

logger = logging.getLogger(__name__)

# ... exact content of the 4 handlers from __init__.py ...
```

- [ ] **Step 2: Update `__init__.py`**

Remove the 4 git handler functions. Add:

```python
from sagtask.handlers._git import (  # noqa: F401
    _handle_sag_task_branch,
    _handle_sag_task_commit,
    _handle_sag_task_git_log,
    _handle_sag_task_list,
)
```

- [ ] **Step 3: Run full test suite**

Run: `PYTHONPATH=src python -m pytest tests/ --tb=short`
Expected: All 152 PASS

- [ ] **Step 4: Commit**

```bash
git add src/sagtask/handlers/_git.py src/sagtask/__init__.py
git commit -m "refactor: extract handlers/_git.py — list, commit, branch, git_log"
```

---

### Task 6: Create `handlers/_plan.py` — plan, verify, relate handlers

**Files:**
- Create: `src/sagtask/handlers/_plan.py`
- Modify: `src/sagtask/__init__.py` (remove remaining handlers)

**Context:** Plan/verify/relate handlers. The TDD state machine lives in `_handle_sag_task_verify` and stays with the verify handler.

- [ ] **Step 1: Create `src/sagtask/handlers/_plan.py`**

Move these handlers from `__init__.py`:
- `_handle_sag_task_relate` (line 1594)
- `_handle_sag_task_verify` (line 1658)
- `_handle_sag_task_plan` (line 1757)
- `_handle_sag_task_plan_update` (line 1811)

```python
"""Plan, verify, and relate handlers — including TDD state machine."""
from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Any, Dict, List, Optional

from .._utils import (
    VERIFY_OUTPUT_MAX_LEN,
    SUBPROCESS_TIMEOUT,
    _get_provider,
    _utcnow_iso,
    _validate_task_id,
)

logger = logging.getLogger(__name__)

# ... exact content of the 4 handlers from __init__.py ...
```

- [ ] **Step 2: Update `__init__.py`**

Remove the 4 handler functions. Add:

```python
from sagtask.handlers._plan import (  # noqa: F401
    _handle_sag_task_plan,
    _handle_sag_task_plan_update,
    _handle_sag_task_relate,
    _handle_sag_task_verify,
)
```

- [ ] **Step 3: Run full test suite**

Run: `PYTHONPATH=src python -m pytest tests/ --tb=short`
Expected: All 152 PASS

- [ ] **Step 4: Commit**

```bash
git add src/sagtask/handlers/_plan.py src/sagtask/__init__.py
git commit -m "refactor: extract handlers/_plan.py — relate, verify, plan, plan_update"
```

---

### Task 7: Create `hooks.py` — hook callbacks

**Files:**
- Create: `src/sagtask/hooks.py`
- Modify: `src/sagtask/__init__.py` (remove hooks, clean up imports)

**Context:** Hook callbacks for LLM context injection and session initialization.

- [ ] **Step 1: Create `src/sagtask/hooks.py`**

Move from `__init__.py`:
- `_on_pre_llm_call` (line 1922)
- `_on_session_start` (line 1961)

```python
"""Hook callbacks for SagTask — registered via ctx.register_hook()."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from ._utils import _get_provider

logger = logging.getLogger(__name__)


def _on_pre_llm_call(
    session_id: str,
    user_message: str,
    conversation_history: List[Any],
    **kwargs,
) -> Dict[str, Any]:
    # ... exact content from __init__.py ...


def _on_session_start(
    session_id: str,
    **kwargs,
) -> None:
    # ... exact content from __init__.py ...
```

- [ ] **Step 2: Update `__init__.py`**

Remove the 2 hook functions. Add:

```python
from sagtask.hooks import _on_pre_llm_call, _on_session_start  # noqa: F401
```

- [ ] **Step 3: Run full test suite**

Run: `PYTHONPATH=src python -m pytest tests/ --tb=short`
Expected: All 152 PASS

- [ ] **Step 4: Commit**

```bash
git add src/sagtask/hooks.py src/sagtask/__init__.py
git commit -m "refactor: extract hooks.py — pre_llm_call and session_start callbacks"
```

---

### Task 8: Final cleanup of `__init__.py` — register function + re-exports

**Files:**
- Modify: `src/sagtask/__init__.py`

**Context:** After all extractions, `__init__.py` should be a thin re-export layer with `register()`. The critical piece is the `_sagtask_instance` singleton — `register()` must set it in `_utils` so `_get_provider()` works.

- [ ] **Step 1: Write final `__init__.py`**

The final `__init__.py` should look like this:

```python
"""SagTask — Task management plugin for Hermes Agent.

Single-file plugin that provides per-task Git repos with multi-phase
lifecycle management, human-in-the-loop approval gates, and cross-session
recovery.

Storage layout (under ~/.hermes/sag_tasks/<task_id>/):
  .sag_task_state.json   ← ❌ NOT in Git (machine-readable state)
  .sag_executions/       ← ❌ NOT in Git (pause snapshots)
  .sag_plans/            ← ✅ In Git (subtask plans per step)
  <everything else>      ← ✅ In Git (task artifacts)
"""
from __future__ import annotations

# Re-export module for register() to mutate _utils._sagtask_instance
from sagtask import _utils as _utils  # noqa: F401

# Re-export utilities for test backward compatibility
from sagtask._utils import (  # noqa: F401
    SCHEMA_VERSION,
    SUBPROCESS_TIMEOUT,
    VERIFY_OUTPUT_MAX_LEN,
    _get_github_owner,
    _get_provider,
    _utcnow_iso,
    _validate_task_id,
)

# Re-export schemas
from sagtask.schemas import (  # noqa: F401
    ALL_TOOL_SCHEMAS,
    TASK_ADVANCE_SCHEMA,
    TASK_APPROVE_SCHEMA,
    TASK_BRANCH_SCHEMA,
    TASK_COMMIT_SCHEMA,
    TASK_CREATE_SCHEMA,
    TASK_GIT_LOG_SCHEMA,
    TASK_LIST_SCHEMA,
    TASK_PAUSE_SCHEMA,
    TASK_PLAN_SCHEMA,
    TASK_PLAN_UPDATE_SCHEMA,
    TASK_RELATE_SCHEMA,
    TASK_RESUME_SCHEMA,
    TASK_STATUS_SCHEMA,
    TASK_VERIFY_SCHEMA,
)

# Re-export plugin class
from sagtask.plugin import SagTaskPlugin  # noqa: F401

# Re-export handler dispatch map
from sagtask.handlers import _tool_handlers  # noqa: F401

# Re-export individual handlers for test backward compatibility
from sagtask.handlers._lifecycle import (  # noqa: F401
    _handle_sag_task_advance,
    _handle_sag_task_approve,
    _handle_sag_task_create,
    _handle_sag_task_pause,
    _handle_sag_task_resume,
    _handle_sag_task_status,
)
from sagtask.handlers._git import (  # noqa: F401
    _handle_sag_task_branch,
    _handle_sag_task_commit,
    _handle_sag_task_git_log,
    _handle_sag_task_list,
)
from sagtask.handlers._plan import (  # noqa: F401
    _handle_sag_task_plan,
    _handle_sag_task_plan_update,
    _handle_sag_task_relate,
    _handle_sag_task_verify,
)

# Re-export hooks
from sagtask.hooks import _on_pre_llm_call, _on_session_start  # noqa: F401


# ─────────────────────────────────────────────────────────────────────────────
# Plugin registration — singleton guard + hook + tool registration
# ─────────────────────────────────────────────────────────────────────────────

# Module-level alias for test backward compatibility (tests do sagtask._sagtask_instance = None)
_sagtask_instance = None


def register(ctx) -> None:
    """Register SagTask as a user plugin.

    - Registers task_* tools via ctx.register_tool()
    - Registers pre_llm_call hook for per-turn context injection
    - Registers on_session_start hook for sagtask root initialization
    """
    import logging
    logger = logging.getLogger(__name__)

    global _sagtask_instance
    if _sagtask_instance is not None:
        logger.debug("SagTaskPlugin already registered, skipping")
        return

    instance = SagTaskPlugin()

    # Set in both places: _utils for _get_provider(), __init__ for test backward compat
    _utils._sagtask_instance = instance
    _sagtask_instance = instance

    # ── Tools ────────────────────────────────────────────────────────────────
    for schema in ALL_TOOL_SCHEMAS:
        tool_name = schema["name"]
        handler = _tool_handlers.get(tool_name)
        if not handler:
            logger.warning("No handler registered for tool: %s", tool_name)
            continue
        ctx.register_tool(
            name=tool_name,
            toolset="memory",
            schema=schema,
            handler=handler,
            description=schema.get("description", ""),
        )
        logger.debug("Registered tool: %s", tool_name)

    # ── Hooks ───────────────────────────────────────────────────────────────
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    ctx.register_hook("on_session_start", _on_session_start)
    logger.info("SagTask plugin registered (tools=%d, hooks=pre_llm_call+on_session_start)", len(_tool_handlers))
```

- [ ] **Step 2: Run full test suite with coverage**

Run: `PYTHONPATH=src python -m pytest tests/ --cov=sagtask --cov-report=term-missing --tb=short`
Expected: All 152 PASS, coverage ≥ 80%

- [ ] **Step 3: Verify file sizes**

Run: `wc -l src/sagtask/*.py src/sagtask/handlers/*.py`
Expected:
- `__init__.py` < 120 lines
- Each module < 500 lines
- Total unchanged (~2023 lines)

- [ ] **Step 4: Final commit**

```bash
git add src/sagtask/__init__.py
git commit -m "refactor: finalize __init__.py as thin re-export layer with register()"
```

---

## Self-Review Notes

**Backward compatibility guarantee:** Every symbol currently accessed as `sagtask.X` or `from sagtask import X` is re-exported from `__init__.py`.

**Singleton pattern:** `_sagtask_instance` lives in both `_utils.py` (for `_get_provider()`) and `__init__.py` (for test backward compat). `register()` sets both: `_utils._sagtask_instance = instance` and `_sagtask_instance = instance`. Tests that do `sagtask._sagtask_instance = None` mutate the `__init__` copy — the `isolated_sagtask` fixture also sets `_utils._sagtask_instance` via the plugin constructor, so both stay in sync.

**Circular dependency prevention:** `_utils.py` has no imports from `plugin.py`, `handlers/`, or `hooks.py`. The dependency graph is strictly: `__init__.py` → all modules → `_utils.py` only. `handlers/` submodules import from `.._utils` (relative), not from `sagtask` (absolute), avoiding circular imports.

**What stays in `__init__.py`:** Only imports + `register()` + `_sagtask_instance` module-level alias. This is the public API surface.
