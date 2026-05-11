"""SagTask — Task management plugin for Hermes Agent.

Per-task Git repos with human-in-the-loop approval gates and cross-session
recovery. SagTask overlays task-management context on top of any existing
memory provider — it does NOT replace it.

INSTALLATION (user plugin):
  git clone https://github.com/ethanchen669/sagtask.git ~/.hermes/plugins/sagtask
  Restart the Hermes gateway.

STORAGE LAYOUT:
  ~/.hermes/sag_tasks/<task_id>/
  ├── .git/                           ← Task Git repo (lazy init)
  ├── .gitignore                      ← Ignores: .sag_task_state.json, .sag_artifacts/, .sag_executions/
  ├── .sag_task_state.json            ← Machine-readable state (NOT in Git)
  ├── src/                            ← ✅ In Git
  ├── tests/                          ← ✅ In Git
  ├── docs/                           ← ✅ In Git
  ├── .sag_plans/                     ← ✅ In Git (subtask plans are valuable artifacts)
  ├── .sag_artifacts/                 ← ⚠️ Git-ignored (manual cleanup)
  └── .sag_executions/                ← ⚠️ Git-ignored (snapshot on pause)
SagTask — user plugin (standalone, NOT a memory provider).
Context is injected via pre_llm_call hook.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ── Re-exported from _utils for backward compatibility ────────────────────────
from ._utils import (  # noqa: E402
    SAGTASK_PROVIDER,
    SCHEMA_VERSION,
    _DEFAULT_GITHUB_OWNER,
    _SUBPROCESS_TIMEOUT,
    _TASK_ID_RE,
    _VERIFY_OUTPUT_MAX_LEN,
    _get_github_owner,
    _get_provider,
    _utcnow_iso,
    _validate_task_id,
)
from . import _utils  # noqa: E402


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

# ─────────────────────────────────────────────────────────────────────────────
# Singleton instance — set by register(), used by tool handlers
# ─────────────────────────────────────────────────────────────────────────────

# Backward-compat alias — the canonical storage lives in _utils._sagtask_instance.
# Tests do ``sagtask._sagtask_instance = None`` so we keep this variable here.
_sagtask_instance: Optional["SagTaskPlugin"] = None


# ─────────────────────────────────────────────────────────────────────────────
# SagTaskPlugin (must be defined before handlers below, since handlers reference it)
# ─────────────────────────────────────────────────────────────────────────────


class SagTaskPlugin:
    """Long-running task management with per-task Git repos and approval gates."""

    MAX_ARTIFACT_SUMMARIES = 3
    SUMMARY_TRUNCATE_AT = 200

    def __init__(self):
        self._hermes_home: Optional[Path] = None
        self._projects_root: Optional[Path] = None
        self._active_task_id: Optional[str] = None
        self._active_execution_id: Optional[str] = None
        self._prefetch_result: str = ""
        self._prefetch_lock = threading.Lock()

    @property
    def name(self) -> str:
        return SAGTASK_PROVIDER

    def is_available(self) -> bool:
        """Always available — local storage only, no credentials needed."""
        return True

    def initialize(self, session_id: str, **kwargs) -> None:
        hermes_home = kwargs.get("hermes_home")
        if not hermes_home:
            hermes_home = Path.home() / ".hermes"
        else:
            hermes_home = Path(hermes_home)
        self._hermes_home = hermes_home
        self._projects_root = hermes_home / "sag_tasks"
        self._projects_root.mkdir(parents=True, exist_ok=True)
        self._restore_active_task()
        logger.debug(
            "SagTaskPlugin initialized, projects_root=%s, active_task=%s",
            self._projects_root,
            self._active_task_id,
        )

    def get_task_root(self, task_id: str) -> Path:
        return self._projects_root / task_id

    def get_task_state_path(self, task_id: str) -> Path:
        return self.get_task_root(task_id) / ".sag_task_state.json"

    def get_gitignore_path(self, task_id: str) -> Path:
        return self.get_task_root(task_id) / ".gitignore"

    def ensure_git_repo(self, task_id: str) -> bool:
        task_root = self.get_task_root(task_id)
        git_dir = task_root / ".git"
        if git_dir.exists():
            return True
        gitignore = self.get_gitignore_path(task_id)
        if not gitignore.exists():
            task_root.mkdir(parents=True, exist_ok=True)
            gitignore.write_text(".sag_task_state.json\n.sag_artifacts/\n.sag_executions/\n__pycache__/\n*.pyc\n")
        result = subprocess.run(["git", "init"], cwd=str(task_root), capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)
        if result.returncode != 0:
            logger.error("git init failed for %s: %s", task_root, result.stderr)
            return False
        remote_url = f"git@github.com:{_get_github_owner()}/{task_id}.git"
        subprocess.run(["git", "remote", "add", "origin", remote_url], cwd=str(task_root), capture_output=True, timeout=_SUBPROCESS_TIMEOUT)
        subprocess.run(["git", "add", ".gitignore"], cwd=str(task_root), capture_output=True, timeout=_SUBPROCESS_TIMEOUT)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(task_root), capture_output=True, timeout=_SUBPROCESS_TIMEOUT)
        logger.info("Git repo initialized for task %s", task_id)
        return True

    def create_github_repo(self, task_id: str) -> bool:
        result = subprocess.run(["gh", "repo", "view", f"{_get_github_owner()}/{task_id}"], capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)
        if result.returncode == 0:
            logger.debug(f"GitHub repo {_get_github_owner()}/%s already exists", task_id)
            return True
        result = subprocess.run(
            ["gh", "repo", "create", task_id, "--source", str(self.get_task_root(task_id)), "--push"],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        if result.returncode != 0:
            logger.error(f"Failed to create GitHub repo {_get_github_owner()}/%s: %s", task_id, result.stderr)
            return False
        logger.info(f"GitHub repo created: {_get_github_owner()}/%s", task_id)
        return True

    def git_push(self, task_id: str, branch: str = "main") -> bool:
        task_root = str(self.get_task_root(task_id))
        result = subprocess.run(["git", "push", "-u", "origin", branch], cwd=task_root, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)
        if result.returncode != 0:
            if "Repository not found" in result.stderr or "does not exist" in result.stderr:
                if self.create_github_repo(task_id):
                    result = subprocess.run(
                        ["git", "push", "-u", "origin", branch], cwd=task_root, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT
                    )
            if result.returncode != 0:
                logger.error("git push failed for task %s: %s", task_id, result.stderr)
                return False
        return True

    def git_branch(self, task_id: str, branch_name: str) -> bool:
        task_root = str(self.get_task_root(task_id))
        for cmd in [["git", "checkout", "-b", branch_name], ["git", "push", "-u", "origin", branch_name]]:
            result = subprocess.run(cmd, cwd=task_root, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)
            if result.returncode != 0:
                logger.error("git branch command failed: %s", result.stderr)
                return False
        return True

    def git_checkout(self, task_id: str, branch: str) -> bool:
        result = subprocess.run(
            ["git", "checkout", branch], cwd=str(self.get_task_root(task_id)), capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT
        )
        return result.returncode == 0

    def git_log(self, task_id: str, max_count: int = 20) -> List[Dict[str, str]]:
        result = subprocess.run(
            ["git", "log", f"--max-count={max_count}", "--oneline"],
            cwd=str(self.get_task_root(task_id)),
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        if result.returncode != 0:
            return []
        return [
            {"hash": line.split()[0], "message": " ".join(line.split()[1:])}
            for line in result.stdout.strip().split("\n")
            if line
        ]

    def _restore_active_task(self) -> None:
        marker = self._projects_root / ".active_task"
        if marker.exists():
            task_id = marker.read_text().strip()
            if task_id and self.get_task_state_path(task_id).exists():
                self._active_task_id = task_id

    def _set_active_task(self, task_id: Optional[str]) -> None:
        self._active_task_id = task_id
        marker = self._projects_root / ".active_task"
        if task_id:
            marker.write_text(task_id)
        elif marker.exists():
            marker.unlink()

    def load_task_state(self, task_id: str) -> Optional[Dict[str, Any]]:
        path = self.get_task_state_path(task_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load task_state for %s: %s", task_id, e)
            return None

    @staticmethod
    def _ensure_schema_version(state: Dict[str, Any]) -> Dict[str, Any]:
        if state.get("schema_version") != SCHEMA_VERSION:
            state = {**state, "schema_version": SCHEMA_VERSION}
        if "methodology_state" not in state:
            state = {
                **state,
                "methodology_state": {
                    "current_methodology": "none",
                    "tdd_phase": None,
                    "plan_file": None,
                    "subtask_progress": {"total": 0, "completed": 0, "in_progress": 0},
                    "last_verification": None,
                    "review_state": None,
                },
            }
        return state

    def save_task_state(self, task_id: str, state: Dict[str, Any]) -> None:
        state = self._ensure_schema_version(state)
        path = self.get_task_state_path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, ensure_ascii=False))
        logger.debug("sag_task_state.json written for task %s", task_id)

    def system_prompt_block(self) -> str:
        if not self._active_task_id:
            return ""
        state = self.load_task_state(self._active_task_id)
        if not state:
            return ""
        status = state.get("status", "unknown")
        current_phase = self._get_current_phase(state)
        current_step = self._get_current_step(state)
        pending_gates = state.get("pending_gates", [])
        lines = [
            "# SagTask — Active Task",
            f"Task: `{self._active_task_id}`  Status: **{status}**",
            f"Phase: {current_phase}  Step: {current_step}",
        ]
        if pending_gates:
            lines.append(f"⏳ Awaiting approval: {', '.join(pending_gates)}")
        lines.append("")
        lines.append("Use `sag_task_status`, `sag_task_pause`, `sag_task_advance`, or `sag_task_approve` to manage this sag long term task.")
        return "\n".join(lines)

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if not self._active_task_id:
            return ""
        with self._prefetch_lock:
            return self._prefetch_result

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        pass

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return ALL_TOOL_SCHEMAS

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        """Dispatch a tool call to the appropriate handler."""
        handler = _tool_handlers.get(tool_name)
        if not handler:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        result = handler(args)
        return json.dumps(result, ensure_ascii=False)

    def shutdown(self) -> None:
        logger.debug("SagTaskPlugin shutting down")

    # ── Optional hooks ────────────────────────────────────────────────────────

    def _build_task_context(self, state: Dict[str, Any], include_methodology: bool = True) -> str:
        """Build task context string shared by on_turn_start and pre_llm_call."""
        status = state.get("status", "unknown")
        current_phase = self._get_current_phase(state)
        current_step = self._get_current_step(state)
        pending_gates = state.get("pending_gates", [])
        artifacts = state.get("artifacts_summary", "")

        lines = [
            f"## Active Task: {self._active_task_id}",
            f"- Status: **{status}**",
            f"- Phase: {current_phase}  |  Step: {current_step}",
        ]
        if pending_gates:
            lines.append(f"- ⏳ Awaiting approval: {', '.join(pending_gates)}")
        if artifacts:
            lines.append(f"- Recent artifacts: {artifacts}")

        if include_methodology:
            ms = state.get("methodology_state", {})
            methodology = ms.get("current_methodology", "none")
            if methodology and methodology != "none":
                lines.append(f"- Methodology: **{methodology}**")
                tdd_phase = ms.get("tdd_phase")
                if tdd_phase and methodology == "tdd":
                    lines.append(f"- ⚠️ TDD phase: {tdd_phase.upper()}")
                progress = ms.get("subtask_progress", {})
                total = progress.get("total", 0)
                completed = progress.get("completed", 0)
                if total > 0:
                    lines.append(f"- Plan progress: {completed}/{total} subtasks completed")

            step_obj = self._get_current_step_object(state)
            if step_obj and step_obj.get("verification"):
                last_v = ms.get("last_verification")
                if last_v:
                    v_status = "✓ passed" if last_v.get("passed") else "✗ failed"
                    lines.append(f"- Verification: {v_status}")
                else:
                    lines.append("- Verification: pending")

        cross_context = self._build_cross_pollination_context(state)
        if cross_context:
            lines.append("")
            lines.append(cross_context)

        return "\n".join(lines)

    def _generate_plan(
        self, step: Dict[str, Any], granularity: str = "medium"
    ) -> Dict[str, Any]:
        """Generate a subtask plan for a step based on its methodology and description."""
        methodology = step.get("methodology", {}).get("type", "none")
        step_name = step.get("name", "Unnamed Step")
        step_desc = step.get("description") or step_name

        subtasks: List[Dict[str, Any]] = []
        st_id = 0

        def _add_subtask(title: str, context: str, depends_on: Optional[List[str]] = None) -> str:
            nonlocal st_id
            st_id += 1
            sid = f"st-{st_id}"
            subtasks.append({
                "id": sid,
                "title": title,
                "status": "pending",
                "depends_on": depends_on or [],
                "context": context,
            })
            return sid

        if methodology == "tdd":
            red_id = _add_subtask(
                f"RED: Write failing test for {step_name}",
                f"Write test(s) that capture the expected behavior described in: {step_desc}. "
                "Tests must fail initially — no implementation yet.",
            )
            green_id = _add_subtask(
                f"GREEN: Implement {step_name} to pass tests",
                f"Write the minimal implementation that makes all tests pass. "
                f"Context: {step_desc}",
                depends_on=[red_id],
            )
            _add_subtask(
                f"REFACTOR: Clean up {step_name}",
                "Refactor implementation and tests for clarity and maintainability. "
                "All tests must continue passing.",
                depends_on=[green_id],
            )
            if granularity == "fine":
                _add_subtask(
                    f"Verify coverage for {step_name}",
                    f"Run pytest with --cov for {step_name} and verify coverage meets the configured threshold.",
                    depends_on=[green_id],
                )
        elif methodology == "brainstorm":
            _add_subtask(
                f"Explore design options for {step_name}",
                f"Brainstorm 2-3 approaches for: {step_desc}. "
                "Document trade-offs for each approach.",
            )
            _add_subtask(
                f"Select and document design for {step_name}",
                "Present options and select the best approach. Document the decision.",
                depends_on=[f"st-{st_id}"],
            )
            _add_subtask(
                f"Implement {step_name} per selected design",
                "Implement the selected approach from the previous subtask.",
                depends_on=[f"st-{st_id}"],
            )
        else:
            _add_subtask(
                f"Plan: Analyze requirements for {step_name}",
                f"Analyze what needs to be done for: {step_desc}. "
                "Identify dependencies and edge cases.",
            )
            _add_subtask(
                f"Implement: {step_name}",
                f"Implement the solution for: {step_desc}.",
                depends_on=[f"st-{st_id}"],
            )
            _add_subtask(
                f"Verify: Test {step_name}",
                "Write tests and verify the implementation works correctly.",
                depends_on=[f"st-{st_id}"],
            )

        return {
            "plan_version": 1,
            "step_id": step.get("id", ""),
            "generated_at": _utcnow_iso(),
            "methodology": methodology,
            "granularity": granularity,
            "subtasks": subtasks,
        }

    def on_turn_start(self, turn_number: int, message: str, **kwargs) -> None:
        if not self._active_task_id:
            return
        state = self.load_task_state(self._active_task_id)
        if not state:
            return
        with self._prefetch_lock:
            self._prefetch_result = self._build_task_context(state, include_methodology=False)

    def _build_cross_pollination_context(self, state: Dict[str, Any]) -> str:
        relationships = state.get("relationships", [])
        cross_tasks = [r for r in relationships if r.get("relationship") == "cross-pollination"]
        if not cross_tasks:
            return ""
        cross_tasks = cross_tasks[:2]
        lines = ["## Related Task Context (Cross-Pollination)"]
        for rel in cross_tasks:
            related_id = rel.get("sag_task_id")
            summaries = self._generate_artifact_summaries(related_id)
            if not summaries:
                continue
            lines.append(f"\n### {related_id}")
            for s in summaries[:3]:
                path = s.get("path", "")
                summary = s.get("summary", "")
                lines.append(f"[{path}]")
                lines.append(summary)
            lines.append(f"→ Use `sag_task_status(task_id=\"{related_id}\")` to see full context")
        overflow = len(cross_tasks) - 2
        if overflow > 0:
            lines.append(f"\n...and {overflow} more related task(s)")
        return "\n".join(lines)

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        pass

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
        if not self._active_task_id:
            return ""
        state = self.load_task_state(self._active_task_id)
        if not state:
            return ""
        current_phase = self._get_current_phase(state)
        current_step = self._get_current_step(state)
        status = state.get("status", "unknown")
        pending_gates = state.get("pending_gates", [])
        lines = [
            f"[SagTask] Active task `{self._active_task_id}` — status: {status}, "
            f"phase: {current_phase}, step: {current_step}"
        ]
        if pending_gates:
            lines.append(f"  Pending approval gates: {', '.join(pending_gates)}")
        return "\n".join(lines)

    def on_memory_write(self, action: str, target: str, content: str) -> None:
        if not self._active_task_id:
            return
        docs_dir = self.get_task_root(self._active_task_id) / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        filename = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{target}_{action}_{len(content)}.md")
        (docs_dir / filename).write_text(content)

    # ── State helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _get_current_phase(state: Dict[str, Any]) -> str:
        phases = state.get("phases", [])
        current = state.get("current_phase_id", "")
        for p in phases:
            if p.get("id") == current:
                return p.get("name", current)
        return current or "—"

    @staticmethod
    def _get_current_step(state: Dict[str, Any]) -> str:
        current_step_id = state.get("current_step_id", "")
        phases = state.get("phases", [])
        current_phase_id = state.get("current_phase_id", "")
        for p in phases:
            if p.get("id") == current_phase_id:
                steps = p.get("steps", [])
                for s in steps:
                    if s.get("id") == current_step_id:
                        return s.get("name", current_step_id)
                if steps:
                    return steps[0].get("name", "—")
        return "—"

    @staticmethod
    def _get_current_step_object(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return the current step dict from phases, or None."""
        phases = state.get("phases", [])
        current_phase_id = state.get("current_phase_id", "")
        current_step_id = state.get("current_step_id", "")
        for p in phases:
            if p.get("id") == current_phase_id:
                for s in p.get("steps", []):
                    if s.get("id") == current_step_id:
                        return s
        return None

    def _scan_git_artifacts(self, task_id: str) -> List[Dict[str, Any]]:
        """Scan git diff of the last commit for changed/added files in this step.

        Returns a list of artifact summaries from git-diff sources.
        """
        task_root = self.get_task_root(task_id)
        git_dir = task_root / ".git"
        if not git_dir.exists():
            return []

        summaries: List[Dict[str, Any]] = []

        # 1. Diff HEAD~1 vs HEAD — what changed in the last commit
        try:
            count_result = subprocess.run(
                ["git", "rev-list", "--count", "HEAD"],
                cwd=str(task_root),
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
            commit_count = int(count_result.stdout.strip() or "0")
            if commit_count >= 2:
                result = subprocess.run(
                    ["git", "diff", "--stat", "HEAD~1", "HEAD"],
                    cwd=str(task_root),
                    capture_output=True,
                    text=True,
                    timeout=_SUBPROCESS_TIMEOUT,
                )
                if result.returncode == 0 and result.stdout.strip():
                    lines = result.stdout.strip().splitlines()
                    for line in lines[-self.MAX_ARTIFACT_SUMMARIES:]:
                        parts = line.split()
                        if len(parts) >= 4:
                            file_path = parts[0]
                            additions = parts[1] if len(parts) > 1 else "0"
                            deletions = parts[3] if len(parts) > 3 else "0"
                            summaries.append({
                                "path": file_path,
                                "summary": f"+{additions} -{deletions} (git diff HEAD~1..HEAD)",
                                "generated_at": _utcnow_iso(),
                                "source": "git_diff",
                            })
        except Exception as e:
            logger.debug("Git artifact scan step failed for %s: %s", task_id, e)

        # 2. List files changed (staged + unstaged) since last commit
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(task_root),
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.strip().splitlines()[:self.MAX_ARTIFACT_SUMMARIES]:
                    # Format: XY path, XY is status like M=, A=, D=, ??=
                    if len(line) < 4:
                        continue
                    status = line[:2].strip()
                    file_path = line[3:].strip()
                    summaries.append({
                        "path": file_path,
                        "summary": f"Git status: {status} (uncommitted)",
                        "generated_at": _utcnow_iso(),
                        "source": "git_status",
                    })
        except Exception as e:
            logger.debug("Git artifact scan step failed for %s: %s", task_id, e)

        # 3. List all tracked files (show file tree snapshot)
        try:
            result = subprocess.run(
                ["git", "ls-files", "--stage"],
                cwd=str(task_root),
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().splitlines()
                tracked_files = [l.split(maxsplit=3)[-1] for l in lines if len(l.split(maxsplit=3)) >= 4]
                # Filter out .sag_* meta files
                tracked_files = [f for f in tracked_files if not f.startswith(".sag_")]
                if tracked_files:
                    summaries.append({
                        "path": ".git/ls-files (tracked)",
                        "summary": f"{len(tracked_files)} tracked file(s): {', '.join(tracked_files[:5])}" +
                                   ("…" if len(tracked_files) > 5 else ""),
                        "generated_at": _utcnow_iso(),
                        "source": "git_ls_files",
                    })
        except Exception as e:
            logger.debug("Git artifact scan step failed for %s: %s", task_id, e)

        return summaries

    def _generate_artifact_summaries(self, task_id: str, force: bool = False) -> List[Dict[str, Any]]:
        state = self.load_task_state(task_id)
        if not state:
            return []
        if not force:
            cached = state.get("artifact_summaries", [])
            if cached:
                return cached

        all_summaries: List[Dict[str, Any]] = []

        # Source 1: .sag_artifacts/ directory (manual artifact storage)
        task_root = self.get_task_root(task_id)
        artifacts_dir = task_root / ".sag_artifacts"
        if artifacts_dir.exists():
            files = sorted(artifacts_dir.rglob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
            files = [f for f in files if f.is_file()][: self.MAX_ARTIFACT_SUMMARIES]
            for f in files:
                summary = self._summarize_artifact_file(f, task_id)
                summary["source"] = "artifact_dir"
                all_summaries.append(summary)

        # Source 2: Git diff (auto-captured on advance)
        git_summaries = self._scan_git_artifacts(task_id)
        for s in git_summaries:
            if s not in all_summaries:  # deduplicate
                all_summaries.append(s)

        # Deduplicate by path
        seen_paths: Set[str] = set()
        unique_summaries: List[Dict[str, Any]] = []
        for s in all_summaries:
            if s.get("path") not in seen_paths:
                seen_paths.add(s.get("path", ""))
                unique_summaries.append(s)

        # Trim to limit
        unique_summaries = unique_summaries[: self.MAX_ARTIFACT_SUMMARIES]
        state["artifact_summaries"] = unique_summaries
        self.save_task_state(task_id, state)
        return unique_summaries

    def _summarize_artifact_file(self, path: Path, task_id: str) -> Dict[str, Any]:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        task_root = self.get_task_root(task_id)
        try:
            rel_path = str(path.relative_to(task_root))
        except ValueError:
            rel_path = str(path)
        text_extensions = {".md", ".py", ".yaml", ".yml", ".json", ".txt", ".csv", ".log"}
        if path.suffix.lower() in text_extensions:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                lines = [l.strip() for l in content.splitlines() if l.strip()]
                sample = lines[0] if lines else content[: self.SUMMARY_TRUNCATE_AT]
                if len(sample) > self.SUMMARY_TRUNCATE_AT:
                    sample = sample[: self.SUMMARY_TRUNCATE_AT] + "…"
                summary_text = sample or "(empty file)"
            except OSError:
                summary_text = f"File, {size} bytes"
        else:
            summary_text = f"Binary file, {size} bytes"
        return {
            "path": rel_path,
            "summary": summary_text,
            "generated_at": _utcnow_iso(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Tool handlers — all inlined here (no providers/ subpackage needed)
# Each accesses the singleton via _get_provider()
# ─────────────────────────────────────────────────────────────────────────────

MAX_CROSS_POLLINATION = 2


def _handle_sag_task_create(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args["sag_task_id"]
    validation_err = _validate_task_id(task_id)
    if validation_err:
        return {"ok": False, "error": validation_err}
    name = args["name"]
    description = args.get("description", "")
    phases = args.get("phases", [])

    task_root = p.get_task_root(task_id)
    task_root.mkdir(parents=True, exist_ok=True)

    # Determine initial methodology from first step's methodology config
    first_step = (phases[0]["steps"][0] if phases and phases[0].get("steps") else None) or {}
    first_methodology = first_step.get("methodology", {})
    initial_methodology = first_methodology.get("type", "none") if first_methodology else "none"

    state = {
        "sag_task_id": task_id,
        "name": name,
        "description": description,
        "status": "active",
        "created_at": _utcnow_iso(),
        "updated_at": _utcnow_iso(),
        "current_phase_id": phases[0]["id"] if phases else "",
        "current_step_id": phases[0]["steps"][0]["id"] if phases and phases[0].get("steps") else "",
        "phases": phases,
        "pending_gates": [],
        "artifacts_summary": "",
        "decisions": [],
        "executions": [],
        "relationships": [],
        "artifact_summaries": [],
        "schema_version": SCHEMA_VERSION,
        "methodology_state": {
            "current_methodology": initial_methodology,
            "tdd_phase": None,
            "plan_file": None,
            "subtask_progress": {"total": 0, "completed": 0, "in_progress": 0},
            "last_verification": None,
            "review_state": None,
        },
    }

    p.save_task_state(task_id, state)

    gitignore = p.get_gitignore_path(task_id)
    gitignore.write_text(".sag_task_state.json\n.sag_artifacts/\n.sag_executions/\n__pycache__/\n*.pyc\n")

    p.ensure_git_repo(task_id)
    p.create_github_repo(task_id)
    p.git_push(task_id, branch="main")
    p._set_active_task(task_id)

    return {
        "ok": True,
        "sag_task_id": task_id,
        "name": name,
        "status": "active",
        "current_phase": state["current_phase_id"],
        "current_step": state["current_step_id"],
        "message": f"Task '{name}' created with {len(phases)} phase(s). Git repo initialized.",
    }


def _handle_sag_task_status(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    verbose = args.get("verbose", False)

    if not task_id:
        return {"ok": False, "error": "No active sag long term task. Use sag_task_list to find a sag long term task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    current_phase = p._get_current_phase(state)
    current_step = p._get_current_step(state)

    result = {
        "ok": True,
        "sag_task_id": task_id,
        "name": state.get("name"),
        "description": state.get("description"),
        "status": state.get("status"),
        "current_phase": current_phase,
        "current_step": current_step,
        "pending_gates": state.get("pending_gates", []),
        "artifacts_summary": state.get("artifacts_summary", ""),
        "relationships": state.get("relationships", []),
        "artifact_summaries": state.get("artifact_summaries", []),
    }

    if verbose:
        result["phases"] = state.get("phases", [])
        result["decisions"] = state.get("decisions", [])
        result["git_log"] = p.git_log(task_id)

        task_root = p.get_task_root(task_id)
        executions_dir = task_root / ".sag_executions"
        paused = []
        if executions_dir.exists():
            for f in executions_dir.glob("*.json"):
                data = json.loads(f.read_text())
                if data.get("status") == "paused":
                    paused.append(data.get("execution_id"))
        result["paused_executions"] = paused

    return result


def _handle_sag_task_pause(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    reason = args.get("reason", "")

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    execution_id = f"exec-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    paused_ctx = {
        "execution_id": execution_id,
        "sag_task_id": task_id,
        "status": "paused",
        "paused_at": _utcnow_iso(),
        "reason": reason,
        "gate_id": state.get("current_gate_id", ""),
        "step_id": state.get("current_step_id", ""),
        "phase_id": state.get("current_phase_id", ""),
        "pending_tool_calls": [],
        "pending_tool_results": [],
        "artifacts_summary": state.get("artifacts_summary", ""),
        "session_context_summary": reason or "Paused by user request",
    }

    task_root = p.get_task_root(task_id)
    executions_dir = task_root / ".sag_executions"
    executions_dir.mkdir(parents=True, exist_ok=True)
    (executions_dir / f"{execution_id}.json").write_text(json.dumps(paused_ctx, indent=2, ensure_ascii=False))

    state = {
        **state,
        "status": "paused",
        "updated_at": _utcnow_iso(),
        "executions": [*state.get("executions", []), execution_id],
    }
    p.save_task_state(task_id, state)

    return {
        "ok": True,
        "sag_task_id": task_id,
        "execution_id": execution_id,
        "status": "paused",
        "message": f"Task paused. Use task_resume('{task_id}') to continue.",
    }


def _handle_sag_task_resume(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id

    if not task_id:
        return {"ok": False, "error": "No active task."}

    task_root = p.get_task_root(task_id)
    executions_dir = task_root / ".sag_executions"

    if not executions_dir.exists():
        return {"ok": False, "error": f"No paused executions found for task '{task_id}'."}

    paused_files = sorted(executions_dir.glob("*.json"), reverse=True)
    paused_ctx = None
    resume_execution_id = None
    for f in paused_files:
        data = json.loads(f.read_text())
        if data.get("status") == "paused":
            paused_ctx = data
            resume_execution_id = f.stem
            break

    if not paused_ctx:
        return {"ok": False, "error": "No paused execution found."}

    state = p.load_task_state(task_id)
    state = {
        **state,
        "status": "active",
        "current_phase_id": paused_ctx.get("phase_id", state.get("current_phase_id")),
        "current_step_id": paused_ctx.get("step_id", state.get("current_step_id")),
        "updated_at": _utcnow_iso(),
    }

    paused_ctx["status"] = "resumed"
    paused_ctx["resumed_at"] = _utcnow_iso()
    (executions_dir / f"{resume_execution_id}.json").write_text(json.dumps(paused_ctx, indent=2, ensure_ascii=False))

    p.save_task_state(task_id, state)
    p._set_active_task(task_id)

    return {
        "ok": True,
        "sag_task_id": task_id,
        "execution_id": resume_execution_id,
        "status": "active",
        "current_phase": paused_ctx.get("phase_id"),
        "current_step": paused_ctx.get("step_id"),
        "recovery_instruction": paused_ctx.get("session_context_summary", ""),
        "message": f"Task resumed from execution {resume_execution_id}.",
    }


def _handle_sag_task_advance(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    commit_message = args.get("commit_message", "")
    artifacts_summary = args.get("artifacts_summary", "")

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    # Check verification requirements before advancing
    step_obj = p._get_current_step_object(state)
    if step_obj:
        verification = step_obj.get("verification", {})
        if verification.get("must_pass", False):
            ms = state.get("methodology_state", {})
            last_v = ms.get("last_verification")
            if not last_v or not last_v.get("passed", False):
                return {
                    "ok": False,
                    "error": "Verification not passed. Run sag_task_verify before advancing.",
                    "last_verification": last_v,
                }

    # Reset tdd_phase on advance (step completed)
    ms = state.get("methodology_state", {})
    if ms.get("tdd_phase"):
        state = {
            **state,
            "methodology_state": {**ms, "tdd_phase": None},
        }

    phases = state.get("phases", [])
    current_phase_id = state.get("current_phase_id", "")
    current_step_id = state.get("current_step_id", "")

    phase_idx = next((i for i, ph in enumerate(phases) if ph.get("id") == current_phase_id), -1)
    if phase_idx == -1:
        return {"ok": False, "error": f"Phase '{current_phase_id}' not found."}

    steps = phases[phase_idx].get("steps", [])
    step_idx = next((i for i, s in enumerate(steps) if s.get("id") == current_step_id), -1)

    next_phase_id = current_phase_id
    next_step_id = current_step_id

    if step_idx < len(steps) - 1:
        next_step_id = steps[step_idx + 1]["id"]
    elif phase_idx < len(phases) - 1:
        next_phase_id = phases[phase_idx + 1]["id"]
        next_step_id = phases[phase_idx + 1]["steps"][0]["id"] if phases[phase_idx + 1].get("steps") else ""
    else:
        state = {
            **state,
            "status": "completed",
            "updated_at": _utcnow_iso(),
        }
        p.save_task_state(task_id, state)
        return {
            "ok": True,
            "sag_task_id": task_id,
            "status": "completed",
            "message": "All phases completed. Task finished!",
        }

    task_root = p.get_task_root(task_id)

    if (task_root / ".git").exists():
        short_name = current_step_id or "current"
        msg = commit_message or f"WIP: [{short_name}] {steps[step_idx].get('name', '')}"
        try:
            subprocess.run(["git", "add", "-A"], cwd=str(task_root), capture_output=True, timeout=_SUBPROCESS_TIMEOUT)
            subprocess.run(["git", "commit", "-m", msg], cwd=str(task_root), capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)
        except Exception as e:
            logger.warning("Git commit failed for task %s: %s", task_id, e)

    # Auto-generate artifact_summaries from git diff (if not manually provided)
    # Runs AFTER git commit so git diff HEAD~1..HEAD captures this step's changes
    if not artifacts_summary:
        auto_summaries = p._generate_artifact_summaries(task_id, force=True)
        if auto_summaries:
            artifacts_summary = "; ".join(
                f"{s['path']}: {s['summary']}" for s in auto_summaries[:3]
            )

    state = {
        **state,
        "current_phase_id": next_phase_id,
        "current_step_id": next_step_id,
        "updated_at": _utcnow_iso(),
        **({"artifacts_summary": artifacts_summary} if artifacts_summary else {}),
    }
    p.save_task_state(task_id, state)

    branch_name = f"step/{next_phase_id}/{next_step_id}"
    p.git_branch(task_id, branch_name)

    return {
        "ok": True,
        "sag_task_id": task_id,
        "previous_phase": current_phase_id,
        "previous_step": current_step_id,
        "current_phase": next_phase_id,
        "current_step": next_step_id,
        "message": f"Advanced to {next_phase_id}/{next_step_id}. New branch '{branch_name}' created.",
    }


def _handle_sag_task_approve(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    gate_id = args.get("gate_id")
    decision = args.get("decision")
    comment = args.get("comment", "")

    if not task_id:
        return {"ok": False, "error": "No active task."}
    if not gate_id:
        return {"ok": False, "error": "gate_id is required."}
    if not decision:
        return {"ok": False, "error": "decision is required."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    approval_record = {
        "gate_id": gate_id,
        "decision": decision,
        "comment": comment,
        "approved_at": _utcnow_iso(),
    }

    pending = [g for g in state.get("pending_gates", []) if g != gate_id]
    state["pending_gates"] = pending
    state["updated_at"] = _utcnow_iso()
    state["decisions"] = state.get("decisions", []) + [approval_record]
    p.save_task_state(task_id, state)

    if decision == "Approve":
        return _handle_sag_task_advance({"sag_task_id": task_id, "commit_message": f"[Gate {gate_id}] Approved: {comment}"})

    return {
        "ok": True,
        "sag_task_id": task_id,
        "gate_id": gate_id,
        "decision": decision,
        "message": f"Gate '{gate_id}' recorded as '{decision}'.",
    }


def _handle_sag_task_list(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    status_filter = args.get("status_filter", "all")
    projects_root = p._projects_root

    tasks = []
    if not projects_root.exists():
        return {"ok": True, "tasks": []}

    for task_dir in sorted(projects_root.iterdir()):
        if task_dir.is_dir() and not task_dir.name.startswith("."):
            task_id = task_dir.name
            state = p.load_task_state(task_id)
            if not state:
                continue
            status = state.get("status", "unknown")
            if status_filter != "all" and status != status_filter:
                continue
            tasks.append({
                "sag_task_id": task_id,
                "name": state.get("name"),
                "status": status,
                "current_phase": p._get_current_phase(state),
                "current_step": p._get_current_step(state),
                "updated_at": state.get("updated_at", ""),
            })

    return {"ok": True, "tasks": tasks}


def _handle_sag_task_commit(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    message = args.get("message", "")

    if not task_id:
        return {"ok": False, "error": "No active task."}

    task_root = p.get_task_root(task_id)
    git_dir = task_root / ".git"
    if not git_dir.exists():
        return {"ok": False, "error": f"Task '{task_id}' is not a Git repo. Run task_advance to initialize."}

    subprocess.run(["git", "add", "-A"], cwd=str(task_root), capture_output=True, timeout=_SUBPROCESS_TIMEOUT)
    result = subprocess.run(["git", "commit", "-m", message], cwd=str(task_root), capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)

    if result.returncode != 0:
        return {"ok": False, "error": f"Git commit failed: {result.stderr}"}

    return {
        "ok": True,
        "sag_task_id": task_id,
        "message": message,
        "commit_hash": result.stdout.strip(),
    }


def _handle_sag_task_branch(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    branch_name = args.get("branch_name")

    if not task_id:
        return {"ok": False, "error": "No active task."}

    if not branch_name:
        state = p.load_task_state(task_id)
        if not state:
            return {"ok": False, "error": f"Task '{task_id}' not found."}
        branch_name = f"step/{state.get('current_phase_id')}/{state.get('current_step_id')}"

    success = p.git_branch(task_id, branch_name)
    if not success:
        return {"ok": False, "error": f"Failed to create branch '{branch_name}'."}

    return {
        "ok": True,
        "sag_task_id": task_id,
        "branch_name": branch_name,
        "message": f"Branch '{branch_name}' created and checked out.",
    }


def _handle_sag_task_git_log(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    max_count = args.get("max_count", 20)

    if not task_id:
        return {"ok": False, "error": "No active task."}

    log = p.git_log(task_id, max_count=max_count)
    return {"ok": True, "sag_task_id": task_id, "commits": log}


def _handle_sag_task_relate(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    related_task_id = args.get("related_task_id")
    relationship = args.get("relationship")
    action = args.get("action")

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    if action == "list":
        rels = state.get("relationships", [])
        return {"ok": True, "sag_task_id": task_id, "relationships": rels}

    if not related_task_id:
        return {"ok": False, "error": "related_task_id is required."}
    if not relationship:
        return {"ok": False, "error": "relationship is required."}
    if action not in ("add", "remove"):
        return {"ok": False, "error": "action must be 'add' or 'remove'."}

    related_state = p.load_task_state(related_task_id)
    if not related_state:
        return {"ok": False, "error": f"Related task '{related_task_id}' not found."}

    relationships = state.get("relationships", [])

    if action == "add":
        cross_poll_count = sum(1 for r in relationships if r.get("relationship") == "cross-pollination")
        if cross_poll_count >= MAX_CROSS_POLLINATION:
            return {
                "ok": False,
                "error": f"Max {MAX_CROSS_POLLINATION} cross-pollination relationships allowed. "
                f"Use task_relate with action='remove' to remove one first.",
            }
        existing = [r for r in relationships if r.get("sag_task_id") == related_task_id]
        if existing:
            return {"ok": False, "error": f"Task '{related_task_id}' is already in the relationships list."}
        relationships.append({"sag_task_id": related_task_id, "relationship": relationship})

    elif action == "remove":
        before = len(relationships)
        relationships = [r for r in relationships if r.get("sag_task_id") != related_task_id]
        if len(relationships) == before:
            return {"ok": False, "error": f"Task '{related_task_id}' was not in the relationships list."}

    state["relationships"] = relationships
    state["updated_at"] = _utcnow_iso()
    p.save_task_state(task_id, state)

    return {
        "ok": True,
        "sag_task_id": task_id,
        "relationship": relationship,
        "related_task_id": related_task_id,
        "action": action,
        "total_relationships": len(relationships),
    }


def _handle_sag_task_verify(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    step = p._get_current_step_object(state)
    if not step:
        return {"ok": False, "error": "Cannot find current step in task phases."}

    verification = step.get("verification", {})
    commands = verification.get("commands", [])

    if not commands:
        return {
            "ok": True,
            "passed": True,
            "message": "No verification configured for this step.",
        }

    task_root = p.get_task_root(task_id)
    cwd_raw = verification.get("cwd") or str(task_root)
    cwd_path = Path(cwd_raw).resolve()
    try:
        cwd_path.relative_to(task_root.resolve())
    except ValueError:
        return {"ok": False, "error": f"cwd '{cwd_raw}' is outside task root."}
    cwd = str(cwd_path)

    results = []
    all_passed = True

    for cmd in commands:
        logger.warning("sag_task_verify executing: cmd=%r cwd=%s", cmd, cwd)
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=cwd,
                capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
            )
            results.append({
                "command": cmd,
                "exit_code": proc.returncode,
                "stdout": proc.stdout[:_VERIFY_OUTPUT_MAX_LEN],
                "stderr": proc.stderr[:_VERIFY_OUTPUT_MAX_LEN],
            })
            if proc.returncode != 0:
                all_passed = False
        except subprocess.TimeoutExpired:
            results.append({
                "command": cmd,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {_SUBPROCESS_TIMEOUT}s",
            })
            all_passed = False
        except Exception as e:
            results.append({
                "command": cmd,
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
            })
            all_passed = False

    # TDD state machine: auto-transition phase based on verification result
    tdd_phase_update: Dict[str, Any] = {}
    step_obj_for_tdd = p._get_current_step_object(state)
    if step_obj_for_tdd:
        m_type = step_obj_for_tdd.get("methodology", {}).get("type", "none")
        if m_type == "tdd":
            tdd_phase_update["tdd_phase"] = "green" if all_passed else "red"

    state = {
        **state,
        "methodology_state": {
            **state.get("methodology_state", {}),
            "last_verification": {
                "passed": all_passed,
                "timestamp": _utcnow_iso(),
                "results": results,
            },
            **tdd_phase_update,
        },
    }
    p.save_task_state(task_id, state)

    return {
        "ok": True,
        "passed": all_passed,
        "results": results,
        "message": f"Verification {'passed' if all_passed else 'failed'} ({len(results)} commands).",
    }


def _handle_sag_task_plan(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    granularity = args.get("granularity", "medium")

    valid_granularities = {"fine", "medium", "coarse"}
    if granularity not in valid_granularities:
        return {"ok": False, "error": f"Invalid granularity '{granularity}'. Must be one of: {', '.join(sorted(valid_granularities))}"}

    if not task_id:
        return {"ok": False, "error": "No active task."}

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    step_obj = p._get_current_step_object(state)
    if not step_obj:
        return {"ok": False, "error": "Cannot find current step in task phases."}

    step_id = step_obj.get("id", "unknown")
    task_root = p.get_task_root(task_id)
    plans_dir = task_root / ".sag_plans"
    plan_path = plans_dir / f"{step_id}.json"

    if plan_path.exists():
        return {"ok": False, "error": f"Plan already exists for step '{step_id}'. Delete it first or use plan_update."}

    plan = p._generate_plan(step_obj, granularity)
    plans_dir.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False))

    total = len(plan["subtasks"])
    state = {
        **state,
        "methodology_state": {
            **state.get("methodology_state", {}),
            "plan_file": f".sag_plans/{step_id}.json",
            "subtask_progress": {"total": total, "completed": 0, "in_progress": 0},
        },
    }
    p.save_task_state(task_id, state)

    return {
        "ok": True,
        "sag_task_id": task_id,
        "step_id": step_id,
        "plan_file": f".sag_plans/{step_id}.json",
        "total_subtasks": total,
        "subtasks": [{"id": st["id"], "title": st["title"]} for st in plan["subtasks"]],
        "message": f"Plan generated with {total} subtasks for step '{step_id}'.",
    }


def _handle_sag_task_plan_update(args: Dict[str, Any]) -> Dict[str, Any]:
    p = _get_provider()
    task_id = args.get("sag_task_id") or p._active_task_id
    subtask_id = args.get("subtask_id", "")
    new_status = args.get("status", "")
    context = args.get("context")

    if not task_id:
        return {"ok": False, "error": "No active task."}

    valid_statuses = {"pending", "in_progress", "done", "failed"}
    if new_status not in valid_statuses:
        return {
            "ok": False,
            "error": f"Invalid status '{new_status}'. Must be one of: {', '.join(sorted(valid_statuses))}",
        }

    state = p.load_task_state(task_id)
    if not state:
        return {"ok": False, "error": f"Task '{task_id}' not found."}

    ms = state.get("methodology_state", {})
    plan_file = ms.get("plan_file")
    if not plan_file:
        return {"ok": False, "error": "No plan found for current step. Run sag_task_plan first."}

    task_root = p.get_task_root(task_id)
    plan_path = (task_root / plan_file).resolve()
    try:
        plan_path.relative_to(task_root.resolve())
    except ValueError:
        return {"ok": False, "error": f"Plan path '{plan_file}' is outside task root."}
    if not plan_path.exists():
        return {"ok": False, "error": f"Plan file '{plan_file}' not found on disk."}

    try:
        plan = json.loads(plan_path.read_text())
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"Plan file '{plan_file}' is corrupted: {e}"}

    subtask = next((s for s in plan["subtasks"] if s["id"] == subtask_id), None)
    if not subtask:
        return {"ok": False, "error": f"Subtask '{subtask_id}' not found in plan."}

    updated_subtasks = [
        {**s, "status": new_status, **(({"result": context}) if context else {})}
        if s["id"] == subtask_id else s
        for s in plan["subtasks"]
    ]
    plan = {**plan, "subtasks": updated_subtasks}

    # Atomic write: temp file then os.replace
    tmp_path = plan_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False))
    os.replace(str(tmp_path), str(plan_path))

    # Sync progress counts
    subtasks = plan["subtasks"]
    total = len(subtasks)
    completed = sum(1 for s in subtasks if s["status"] == "done")
    in_progress = sum(1 for s in subtasks if s["status"] == "in_progress")

    state = {
        **state,
        "methodology_state": {
            **ms,
            "subtask_progress": {
                "total": total,
                "completed": completed,
                "in_progress": in_progress,
            },
        },
    }
    p.save_task_state(task_id, state)

    return {
        "ok": True,
        "sag_task_id": task_id,
        "subtask_id": subtask_id,
        "status": new_status,
        "progress": {"total": total, "completed": completed, "in_progress": in_progress},
        "message": f"Subtask '{subtask_id}' -> {new_status}. Progress: {completed}/{total}.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Handler dispatch map — used by register() to call ctx.register_tool()
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Hook callbacks — registered via ctx.register_hook()
# ─────────────────────────────────────────────────────────────────────────────

def _on_pre_llm_call(
    session_id: str,
    user_message: str,
    conversation_history: List[Any],
    is_first_turn: bool,
    model: str,
    platform: str,
    sender_id: str,
    **kwargs,
) -> Dict[str, Any]:
    """pre_llm_call hook — inject task context before each LLM call.

    Returns {"context": "..."} to be appended to the user message,
    or {} to skip injection.
    """
    p = _get_provider()

    # Ensure projects root is initialized
    if p._projects_root is None:
        hermes_home = kwargs.get("hermes_home")
        if hermes_home:
            p._hermes_home = Path(hermes_home)
        else:
            p._hermes_home = Path.home() / ".hermes"
        p._projects_root = p._hermes_home / "sag_tasks"
        p._projects_root.mkdir(parents=True, exist_ok=True)
        p._restore_active_task()

    if not p._active_task_id:
        return {}

    state = p.load_task_state(p._active_task_id)
    if not state:
        return {}

    context_text = p._build_task_context(state, include_methodology=True)
    return {"context": context_text}


def _on_session_start(
    session_id: str,
    model: str,
    platform: str,
    **kwargs,
) -> None:
    """on_session_start hook — restore active task marker on session start."""
    p = _get_provider()
    if p._projects_root is None:
        hermes_home = kwargs.get("hermes_home")
        if hermes_home:
            p._hermes_home = Path(hermes_home)
        else:
            p._hermes_home = Path.home() / ".hermes"
        p._projects_root = p._hermes_home / "sag_tasks"
        p._projects_root.mkdir(parents=True, exist_ok=True)
    p._restore_active_task()
    logger.debug(
        "SagTask on_session_start: session_id=%s, active_task=%s",
        session_id,
        p._active_task_id,
    )


# ----------------------------------------------------------------------------
# Plugin registration — singleton guard + hook + tool registration
# -----------------------------------------------------------------------------


def register(ctx) -> None:
    """Register SagTask as a user plugin.

    - Registers task_* tools via ctx.register_tool()
    - Registers pre_llm_call hook for per-turn context injection
    - Registers on_session_start hook for sagtask root initialization
    """
    global _sagtask_instance
    if _sagtask_instance is not None:
        logger.debug("SagTaskPlugin already registered, skipping")
        return

    _sagtask_instance = SagTaskPlugin()
    _utils._sagtask_instance = _sagtask_instance

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
