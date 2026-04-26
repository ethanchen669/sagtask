"""MemTaskProvider — per-task Git repos with human-in-the-loop approval gates.

Storage layout (per confirmed design):
  ~/.hermes/projects/<task_id>/
  ├── .git/                    ← Task Git repo (lazy init)
  ├── .gitignore               ← Ignores: task_state.json, artifacts/, executions/
  ├── task_state.json         ← Machine-readable state (NOT in Git)
  ├── task.md                  ← Human-readable (in Git, optional)
  ├── src/                     ← ✅ In Git
  ├── tests/                   ← ✅ In Git
  ├── docs/                    ← ✅ In Git
  ├── artifacts/               ← ⚠️ Git-ignored (manual cleanup)
  └── executions/              ← ⚠️ Git-ignored (snapshot on pause)

Git branch strategy: one branch per Step (step/phase-X/step-Y-description)
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from agent.memory_provider import MemoryProvider  # bundled hermes-agent
except ImportError:
    from hermes_agent.agent.memory_provider import MemoryProvider  # user plugin context

logger = logging.getLogger(__name__)

MEMTASK_PROVIDER = "memtask"

# Tool schemas exposed by this provider
try:
    from .providers.tools import (
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
    )
except ModuleNotFoundError:
    # User plugin context: _hermes_user_memory.memtask doesn't have a parent
    # package in sys.modules, so use absolute import from the memtask package
    from memtask.providers.tools import (
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
    )

ALL_TOOL_SCHEMAS = [
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
]


class MemTaskProvider(MemoryProvider):
    """Long-running task management with per-task Git repos and approval gates."""

    def __init__(self):
        self._hermes_home: Optional[Path] = None
        self._projects_root: Optional[Path] = None
        self._active_task_id: Optional[str] = None
        self._active_execution_id: Optional[str] = None
        self._prefetch_result: str = ""
        self._prefetch_lock = threading.Lock()

    # ── Basic properties ──────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return MEMTASK_PROVIDER

    # ── Core lifecycle ─────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Always available — local storage only, no credentials needed."""
        return True

    def initialize(self, session_id: str, **kwargs) -> None:
        """Set up projects root directory and restore active task from disk."""
        hermes_home = kwargs.get("hermes_home")
        if not hermes_home:
            hermes_home = Path.home() / ".hermes"
        else:
            hermes_home = Path(hermes_home)

        self._hermes_home = hermes_home
        self._projects_root = hermes_home / "projects"
        self._projects_root.mkdir(parents=True, exist_ok=True)

        # Restore any task that was active before this session
        self._restore_active_task()
        logger.debug(
            "MemTaskProvider initialized, projects_root=%s, active_task=%s",
            self._projects_root,
            self._active_task_id,
        )

    # ── Storage helpers ────────────────────────────────────────────────────────

    def get_task_root(self, task_id: str) -> Path:
        """Return the root directory for a task."""
        return self._projects_root / task_id

    def get_task_state_path(self, task_id: str) -> Path:
        """Return the task_state.json path for a task."""
        return self.get_task_root(task_id) / "task_state.json"

    def get_gitignore_path(self, task_id: str) -> Path:
        """Return the .gitignore path for a task."""
        return self.get_task_root(task_id) / ".gitignore"

    # ── Git repo management ────────────────────────────────────────────────────

    def ensure_git_repo(self, task_id: str) -> bool:
        """Lazily initialize a Git repo for a task on first push.

        Returns True if repo now exists (either was already there or newly created).
        """
        task_root = self.get_task_root(task_id)
        git_dir = task_root / ".git"

        if git_dir.exists():
            return True

        # Create .gitignore first
        gitignore = self.get_gitignore_path(task_id)
        if not gitignore.exists():
            task_root.mkdir(parents=True, exist_ok=True)
            gitignore.write_text(
                "task_state.json\nartifacts/\nexecutions/\n__pycache__/\n*.pyc\n"
            )

        # Init git repo
        import subprocess

        result = subprocess.run(
            ["git", "init"],
            cwd=str(task_root),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("git init failed for %s: %s", task_root, result.stderr)
            return False

        # Create remote reference (repo must exist on GitHub first — see create_github_repo)
        # Task repos use per-task GitHub repos: charlenchen/<task_id>
        remote_url = f"git@github.com:charlenchen/{task_id}.git"
        subprocess.run(
            ["git", "remote", "add", "origin", remote_url],
            cwd=str(task_root),
            capture_output=True,
        )

        # Create initial commit on main
        subprocess.run(
            ["git", "add", ".gitignore"],
            cwd=str(task_root),
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=str(task_root),
            capture_output=True,
        )
        logger.info("Git repo initialized for task %s", task_id)
        return True

    def create_github_repo(self, task_id: str) -> bool:
        """Create a GitHub repo for a task using the gh CLI.

        Returns True if repo was created or already exists.
        """
        import subprocess

        # Check if repo already exists
        result = subprocess.run(
            ["gh", "repo", "view", f"charlenchen/{task_id}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logger.debug("GitHub repo charlenchen/%s already exists", task_id)
            return True

        # Create the repo (public by default)
        result = subprocess.run(
            ["gh", "repo", "create", task_id, "--source", str(self.get_task_root(task_id)), "--push"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("Failed to create GitHub repo charlenchen/%s: %s", task_id, result.stderr)
            return False

        logger.info("GitHub repo created: charlenchen/%s", task_id)
        return True

    def git_push(self, task_id: str, branch: str = "main") -> bool:
        """Push the current branch to the remote origin."""
        import subprocess

        task_root = str(self.get_task_root(task_id))
        result = subprocess.run(
            ["git", "push", "-u", "origin", branch],
            cwd=task_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # If remote doesn't exist yet, create it first
            if "Repository not found" in result.stderr or "does not exist" in result.stderr:
                if self.create_github_repo(task_id):
                    result = subprocess.run(
                        ["git", "push", "-u", "origin", branch],
                        cwd=task_root,
                        capture_output=True,
                        text=True,
                    )
            if result.returncode != 0:
                logger.error("git push failed for task %s: %s", task_id, result.stderr)
                return False
        return True

    def git_branch(self, task_id: str, branch_name: str) -> bool:
        """Create and switch to a new branch."""
        import subprocess

        task_root = str(self.get_task_root(task_id))
        for cmd in [
            ["git", "checkout", "-b", branch_name],
            ["git", "push", "-u", "origin", branch_name],
        ]:
            result = subprocess.run(cmd, cwd=task_root, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error("git branch command failed: %s", result.stderr)
                return False
        return True

    def git_checkout(self, task_id: str, branch: str) -> bool:
        """Switch to an existing branch."""
        import subprocess

        result = subprocess.run(
            ["git", "checkout", branch],
            cwd=str(self.get_task_root(task_id)),
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def git_log(self, task_id: str, max_count: int = 20) -> List[Dict[str, str]]:
        """Return recent commit history as list of dicts."""
        import subprocess

        result = subprocess.run(
            ["git", "log", f"--max-count={max_count}", "--oneline"],
            cwd=str(self.get_task_root(task_id)),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []
        return [{"hash": line.split()[0], "message": " ".join(line.split()[1:])}
                for line in result.stdout.strip().split("\n") if line]

    # ── Task state management ─────────────────────────────────────────────────

    def _restore_active_task(self) -> None:
        """Restore the active task from the most recent session state.

        Since task_state.json is per-task (not per-session), we look at which
        tasks have a paused execution and make that the active task.
        For now, we track the last active task_id in a provider-level marker file.
        """
        marker = self._projects_root / ".active_task"
        if marker.exists():
            task_id = marker.read_text().strip()
            if task_id and self.get_task_state_path(task_id).exists():
                self._active_task_id = task_id

    def _set_active_task(self, task_id: Optional[str]) -> None:
        """Mark a task as the active task for this session."""
        self._active_task_id = task_id
        marker = self._projects_root / ".active_task"
        if task_id:
            marker.write_text(task_id)
        elif marker.exists():
            marker.unlink()

    def load_task_state(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Load task_state.json for a task."""
        path = self.get_task_state_path(task_id)
        if not path.exists():
            return None
        import json

        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load task_state for %s: %s", task_id, e)
            return None

    def save_task_state(self, task_id: str, state: Dict[str, Any]) -> None:
        """Write task_state.json (only on Phase/Step/Gate changes — not every sync_turn)."""
        path = self.get_task_state_path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        import json

        path.write_text(json.dumps(state, indent=2, ensure_ascii=False))
        logger.debug("task_state.json written for task %s", task_id)

    # ── MemoryProvider core methods ────────────────────────────────────────────

    def system_prompt_block(self) -> str:
        """Return a static block for the system prompt when a task is active."""
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
            "# MemTask — Active Task",
            f"Task: `{self._active_task_id}`  Status: **{status}**",
            f"Phase: {current_phase}  Step: {current_step}",
        ]
        if pending_gates:
            lines.append(f"⏳ Awaiting approval: {', '.join(pending_gates)}")
        lines.append("")
        lines.append(
            "Use `task_status`, `task_pause`, `task_advance`, or `task_approve` to manage this task."
        )
        return "\n".join(lines)

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Inject current task context before each turn."""
        if not self._active_task_id:
            return ""

        with self._prefetch_lock:
            return self._prefetch_result

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        """No-op: task state is only written on Phase/Step/Gate changes (per confirmed design)."""
        pass

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Return all project management tool schemas."""
        return ALL_TOOL_SCHEMAS

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        """Dispatch a tool call to the appropriate handler."""
        from .providers.task_tools import (
            handle_task_create,
            handle_task_status,
            handle_task_pause,
            handle_task_resume,
            handle_task_advance,
            handle_task_approve,
            handle_task_list,
            handle_task_commit,
            handle_task_branch,
            handle_task_git_log,
            handle_task_relate,
        )

        handler_map = {
            "task_create": handle_task_create,
            "task_status": handle_task_status,
            "task_pause": handle_task_pause,
            "task_resume": handle_task_resume,
            "task_advance": handle_task_advance,
            "task_approve": handle_task_approve,
            "task_list": handle_task_list,
            "task_commit": handle_task_commit,
            "task_branch": handle_task_branch,
            "task_git_log": handle_task_git_log,
            "task_relate": handle_task_relate,
        }

        handler = handler_map.get(tool_name)
        if not handler:
            import json

            return json.dumps({"error": f"Unknown tool: {tool_name}"})

        result = handler(self, args)
        import json

        return json.dumps(result, ensure_ascii=False)

    def shutdown(self) -> None:
        """Clean shutdown — save any pending state."""
        logger.debug("MemTaskProvider shutting down")

    # ── Optional hooks ────────────────────────────────────────────────────────

    def on_turn_start(self, turn_number: int, message: str, **kwargs) -> None:
        """Called at the start of each turn — update prefetch cache."""
        if not self._active_task_id:
            return

        state = self.load_task_state(self._active_task_id)
        if not state:
            return

        # Build a compact summary for injection
        status = state.get("status", "unknown")
        current_phase = self._get_current_phase(state)
        current_step = self._get_current_step(state)
        pending_gates = state.get("pending_gates", [])
        artifacts = state.get("artifacts_summary", "")

        lines = [f"## Active Task: {self._active_task_id}"]
        lines.append(f"- Status: **{status}**")
        lines.append(f"- Phase: {current_phase}  |  Step: {current_step}")
        if pending_gates:
            lines.append(f"- ⏳ Awaiting approval: {', '.join(pending_gates)}")
        if artifacts:
            lines.append(f"- Recent artifacts: {artifacts}")

        # Cross-pollination context injection
        cross_context = self._build_cross_pollination_context(state)
        if cross_context:
            lines.append("")
            lines.append(cross_context)

        with self._prefetch_lock:
            self._prefetch_result = "\n".join(lines)

    def _build_cross_pollination_context(self, state: Dict[str, Any]) -> str:
        """Build prefetch text for cross-pollination related tasks."""
        relationships = state.get("relationships", [])
        cross_tasks = [
            r for r in relationships if r.get("relationship") == "cross-pollination"
        ]
        if not cross_tasks:
            return ""

        # Enforce N≤2
        cross_tasks = cross_tasks[:2]

        lines = ["## Related Task Context (Cross-Pollination)"]
        for rel in cross_tasks:
            related_id = rel.get("task_id")
            summaries = self._generate_artifact_summaries(related_id)
            if not summaries:
                continue

            lines.append(f"\n### {related_id}")
            # Enforce M≤3, truncate each at 200 chars
            for s in summaries[:3]:
                path = s.get("path", "")
                summary = s.get("summary", "")
                lines.append(f"[{path}]")
                lines.append(summary)
            lines.append(
                f"→ Use `task_status(task_id=\"{related_id}\")` to see full context"
            )

        overflow = len(cross_tasks) - 2
        if overflow > 0:
            lines.append(f"\n...and {overflow} more related task(s)")

        return "\n".join(lines)

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        """Extract task conclusions at end of session."""
        # Could extract "conclusion" from the conversation and write to task.md
        pass

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
        """Extract active task progress before context compression."""
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
            f"[MemTask] Active task `{self._active_task_id}` — status: {status}, "
            f"phase: {current_phase}, step: {current_step}"
        ]
        if pending_gates:
            lines.append(f"  Pending approval gates: {', '.join(pending_gates)}")

        return "\n".join(lines)

    def on_memory_write(self, action: str, target: str, content: str) -> None:
        """Mirror built-in memory writes to the active task's docs/ directory."""
        if not self._active_task_id:
            return

        docs_dir = self.get_task_root(self._active_task_id) / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{target}_{action}_{len(content)}.md"
        # Sanitize filename
        import re

        filename = re.sub(r"[^a-zA-Z0-9_-]", "_", filename)
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
        phases = state.get("phases", [])
        current_phase_id = state.get("current_phase_id", "")
        for p in phases:
            if p.get("id") == current_phase_id:
                steps = p.get("steps", [])
                current_step_id = state.get("current_step_id", "")
                for s in steps:
                    if s.get("id") == current_step_id:
                        return s.get("name", current_step_id)
                if steps:
                    return steps[0].get("name", "—")
        return current_step_id or "—"

    # ── Artifact summaries ───────────────────────────────────────────────────────

    MAX_ARTIFACT_SUMMARIES = 3
    SUMMARY_TRUNCATE_AT = 200

    def _generate_artifact_summaries(
        self, task_id: str, force: bool = False
    ) -> List[Dict[str, Any]]:
        """Generate or refresh artifact_summaries for a task.

        Returns cached summaries from task_state if:
        - they exist AND force=False (cached, fresh until next task_advance)
        - artifacts/ directory is empty or missing

        Otherwise scans artifacts/ and generates summaries on-demand.
        """
        state = self.load_task_state(task_id)
        if not state:
            return []

        # Return cached if exists and not forcing refresh
        if not force:
            cached = state.get("artifact_summaries", [])
            if cached:
                return cached

        task_root = self.get_task_root(task_id)
        artifacts_dir = task_root / "artifacts"
        if not artifacts_dir.exists():
            return []

        # Collect files, sort by mtime descending, limit to MAX
        files = sorted(
            artifacts_dir.rglob("*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        files = [f for f in files if f.is_file()]
        files = files[: self.MAX_ARTIFACT_SUMMARIES]

        summaries = []
        for f in files:
            summary = self._summarize_artifact_file(f, task_id)
            summaries.append(summary)

        # Cache in task_state
        if summaries:
            state["artifact_summaries"] = summaries
            self.save_task_state(task_id, state)

        return summaries

    def _summarize_artifact_file(self, path: Path, task_id: str) -> Dict[str, str]:
        """Generate a one-line summary for an artifact file."""
        try:
            size = path.stat().st_size
        except OSError:
            size = 0

        # Compute relative path from task root: artifacts/...
        task_root = self.get_task_root(task_id)
        try:
            rel_path = str(path.relative_to(task_root))
        except ValueError:
            rel_path = str(path)

        text_extensions = {".md", ".py", ".yaml", ".yml", ".json", ".txt", ".csv", ".log"}
        if path.suffix.lower() in text_extensions:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                # Take first non-empty line or first 200 chars
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
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }

# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Register MemTask as a memory provider plugin."""
    ctx.register_memory_provider(MemTaskProvider())
