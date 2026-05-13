"""SagTaskPlugin -- core plugin class for task management."""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ._utils import (
    SAGTASK_PROVIDER,
    SCHEMA_VERSION,
    _SUBPROCESS_TIMEOUT,
    _VERIFY_OUTPUT_MAX_LEN,
    _get_github_owner,
    _utcnow_iso,
)

logger = logging.getLogger(__name__)


class SagTaskPlugin:
    """Long-running task management with per-task Git repos and approval gates."""

    MAX_ARTIFACT_SUMMARIES = 3
    SUMMARY_TRUNCATE_AT = 200

    def __init__(self):
        self._hermes_home: Optional[Path] = None
        self._projects_root: Optional[Path] = None
        self._active_task_id: Optional[str] = None
        self._active_execution_id: Optional[str] = None

    @property
    def name(self) -> str:
        return SAGTASK_PROVIDER

    def is_available(self) -> bool:
        """Always available -- local storage only, no credentials needed."""
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
            gitignore.write_text(".sag_task_state.json\n.sag_artifacts/\n.sag_executions/\n.sag_worktrees/\n.sag_metrics.jsonl\n__pycache__/\n*.pyc\n")
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
            "# SagTask -- Active Task",
            f"Task: `{self._active_task_id}`  Status: **{status}**",
            f"Phase: {current_phase}  Step: {current_step}",
        ]
        if pending_gates:
            lines.append(f"Awaiting approval: {', '.join(pending_gates)}")
        lines.append("")
        lines.append("Use `sag_task_status`, `sag_task_pause`, `sag_task_advance`, or `sag_task_approve` to manage this sag long term task.")
        return "\n".join(lines)

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        # Lazy import to avoid circular dependency (schemas import triggers sagtask init)
        from sagtask.schemas import ALL_TOOL_SCHEMAS  # noqa: F811
        return ALL_TOOL_SCHEMAS

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        """Dispatch a tool call to the appropriate handler."""
        # Lazy import to avoid circular dependency (__init__ imports plugin)
        from . import _tool_handlers  # noqa: F811
        handler = _tool_handlers.get(tool_name)
        if not handler:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        result = handler(args)
        return json.dumps(result, ensure_ascii=False)

    def create_worktree(self, task_id: str, subtask_id: str) -> Optional[Path]:
        """Create a git worktree for isolated subtask execution.

        Returns the worktree path, or None on failure.
        """
        task_root = self.get_task_root(task_id)
        worktree_dir = task_root / ".sag_worktrees" / subtask_id
        if worktree_dir.exists():
            return worktree_dir

        branch_name = f"worktree/{subtask_id}"
        try:
            result = subprocess.run(
                ["git", "worktree", "add", "-b", branch_name, str(worktree_dir)],
                cwd=str(task_root),
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
            if result.returncode != 0:
                logger.warning("git worktree add failed: %s", result.stderr)
                return None
            return worktree_dir
        except Exception as e:
            logger.warning("Failed to create worktree: %s", e)
            return None

    def remove_worktree(self, task_id: str, subtask_id: str, force: bool = False) -> bool:
        """Remove a git worktree after subtask completion."""
        task_root = self.get_task_root(task_id)
        worktree_dir = task_root / ".sag_worktrees" / subtask_id
        if not worktree_dir.exists():
            return True

        try:
            cmd = ["git", "worktree", "remove", str(worktree_dir)]
            if force:
                cmd.append("--force")
            result = subprocess.run(
                cmd,
                cwd=str(task_root),
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
            if result.returncode != 0 and not force:
                logger.warning(
                    "Worktree has uncommitted changes, use force=True to remove: %s",
                    result.stderr.strip(),
                )
            return result.returncode == 0
        except Exception as e:
            logger.warning("Failed to remove worktree: %s", e)
            return False

    def emit_metric(self, task_id: str, event: str, step_id: str = "", phase_id: str = "", **fields) -> None:
        """Append one metric event to .sag_metrics.jsonl."""
        task_root = self.get_task_root(task_id)
        metrics_file = task_root / ".sag_metrics.jsonl"
        self._ensure_metrics_gitignored(task_root)
        entry = {"ts": _utcnow_iso(), "event": event, "step_id": step_id, "phase_id": phase_id, **fields}
        try:
            with open(metrics_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug("Failed to write metric: %s", e)

    def _ensure_metrics_gitignored(self, task_root: Path) -> None:
        """Ensure .sag_metrics.jsonl is in .gitignore for existing task repos."""
        gitignore = task_root / ".gitignore"
        if not gitignore.exists():
            return
        content = gitignore.read_text(encoding="utf-8")
        if ".sag_metrics.jsonl" not in content:
            with open(gitignore, "a", encoding="utf-8") as f:
                f.write(".sag_metrics.jsonl\n")

    def shutdown(self) -> None:
        logger.debug("SagTaskPlugin shutting down")

    # -- Optional hooks --------------------------------------------------------

    def _build_metrics_summary(self, state: Dict[str, Any]) -> str:
        """Build one-line metrics summary for context injection."""
        task_id = state.get("sag_task_id", self._active_task_id)
        if not task_id:
            return ""
        task_root = self.get_task_root(task_id)
        metrics_file = task_root / ".sag_metrics.jsonl"
        if not metrics_file.exists():
            return ""

        step_id = state.get("current_step_id", "")
        events = []
        for line in metrics_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                if e.get("step_id") == step_id:
                    events.append(e)
            except json.JSONDecodeError:
                continue

        if not events:
            return ""

        parts = []

        # Verification
        verify_events = [e for e in events if e.get("event") == "verify_run"]
        if verify_events:
            total = len(verify_events)
            passed = sum(1 for e in verify_events if e.get("passed"))
            pct = round(passed / total * 100)
            streak = 0
            last_val = verify_events[-1].get("passed")
            for e in reversed(verify_events):
                if e.get("passed") == last_val:
                    streak += 1
                else:
                    break
            streak_str = f"+{streak}" if last_val else f"-{streak}"
            parts.append(f"Verify: {passed}/{total} passed ({pct}%), streak {streak_str}")

        # Coverage
        cov_values = [e["coverage_pct"] for e in events if e.get("event") == "verify_run" and "coverage_pct" in e]
        if cov_values:
            from .handlers._metrics import compute_coverage_trend
            current = cov_values[-1]
            trend = compute_coverage_trend(cov_values)
            arrow = {"improving": "↑", "declining": "↓", "stable": "→"}[trend]
            parts.append(f"Coverage: {current}% ({arrow})")

        # Throughput
        complete_events = [e for e in events if e.get("event") == "subtask_complete"]
        if complete_events:
            latest: Dict[str, str] = {}
            for e in complete_events:
                sid = e.get("subtask_id", "")
                if sid:
                    latest[sid] = e.get("new_status", "")
            done = sum(1 for s in latest.values() if s == "done")
            plan_total = state.get("methodology_state", {}).get("subtask_progress", {}).get("total", 0)
            total = plan_total if plan_total > 0 else len(latest)
            parts.append(f"Subtasks: {done}/{total} done")

        if not parts:
            return ""
        return "- " + " | ".join(parts)

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
            lines.append(f"- Awaiting approval: {', '.join(pending_gates)}")
        if artifacts:
            lines.append(f"- Recent artifacts: {artifacts}")

        if include_methodology:
            ms = state.get("methodology_state", {})
            methodology = ms.get("current_methodology", "none")
            if methodology and methodology != "none":
                lines.append(f"- Methodology: **{methodology}**")
                tdd_phase = ms.get("tdd_phase")
                if tdd_phase and methodology == "tdd":
                    lines.append(f"- TDD phase: {tdd_phase.upper()}")
                brainstorm_phase = ms.get("brainstorm_phase")
                if brainstorm_phase and methodology == "brainstorm":
                    selected = ms.get("brainstorm_selected")
                    phase_text = brainstorm_phase
                    if selected:
                        phase_text = f"selected option {selected}"
                    lines.append(f"- Brainstorm phase: {phase_text}")
                debug_phase = ms.get("debug_phase")
                if debug_phase and methodology == "debug":
                    hypothesis = ms.get("debug_hypothesis", "")
                    phase_text = debug_phase
                    if hypothesis and debug_phase == "diagnose":
                        phase_text = f"diagnosing: {hypothesis}"
                    elif debug_phase == "fix":
                        phase_text = "fixing"
                    lines.append(f"- Debug phase: {phase_text}")
                progress = ms.get("subtask_progress", {})
                total = progress.get("total", 0)
                completed = progress.get("completed", 0)
                if total > 0:
                    lines.append(f"- Plan progress: {completed}/{total} subtasks completed")
                    in_progress_count = progress.get("in_progress", 0)
                    if in_progress_count > 0:
                        lines.append(f"- Active dispatches: {in_progress_count} subtask(s) in-progress")

            step_obj = self._get_current_step_object(state)
            if step_obj and step_obj.get("verification"):
                last_v = ms.get("last_verification")
                if last_v:
                    v_status = "passed" if last_v.get("passed") else "failed"
                    lines.append(f"- Verification: {v_status}")
                else:
                    lines.append("- Verification: pending")

        # Metrics summary line
        metrics_line = self._build_metrics_summary(state)
        if metrics_line:
            lines.append(metrics_line)

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
                "Tests must fail initially -- no implementation yet.",
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
            lines.append(f"-> Use `sag_task_status(task_id=\"{related_id}\")` to see full context")
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
            f"[SagTask] Active task `{self._active_task_id}` -- status: {status}, "
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

    # -- State helpers ---------------------------------------------------------

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

        # 1. Diff HEAD~1 vs HEAD -- what changed in the last commit
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
                                   ("..." if len(tracked_files) > 5 else ""),
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
                    sample = sample[: self.SUMMARY_TRUNCATE_AT] + "..."
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
