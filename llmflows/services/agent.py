"""Agent launcher -- writes prompt and launches coding agents.

Supports multiple agent backends (Cursor, Claude Code, Codex).
Agent output is streamed to .llmflows/agent-{run_id}.log in the working directory.
Agent PID is stored in .llmflows/agent.pid for liveness checks.

When worktrees are enabled (the default) the working directory is the worktree
root and ephemeral files live in ``<worktree>/.llmflows/``.

When worktrees are disabled (manager/orchestrator repos) the working directory
is the project root and ephemeral files live in
``<project>/.llmflows/<task_id>/`` so that concurrent task runs don't collide.
"""

import logging
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional

from ..config import AGENT_REGISTRY
from .context import ContextService

logger = logging.getLogger("llmflows.agent")


class AgentService:
    def __init__(self, project_dir: Path, worktree_path: Optional[Path] = None):
        """Initialize agent service.

        Args:
            project_dir: .llmflows/ dir in the main project
            worktree_path: Path to the worktree root (if launching in a worktree)
        """
        self.project_dir = project_dir
        self.worktree_path = worktree_path or project_dir.parent

    def prepare_and_launch(
        self,
        run_id: str,
        flow_name: str,
        task_name: str,
        task_id: str,
        task_description: str = "",
        task_type: str = "feature",
        execution_history: Optional[list[dict]] = None,
        model: str = "",
        agent: str = "cursor",
        use_task_subdir: bool = False,
        recovery: bool = False,
        recovery_context: Optional[dict] = None,
    ) -> tuple[bool, str, str]:
        """Write prompt in the working directory, then launch the selected agent.

        When ``use_task_subdir`` is True (worktree disabled) ephemeral files go
        into ``<working_dir>/.llmflows/<task_id>/`` instead of
        ``<working_dir>/.llmflows/`` so multiple tasks sharing the same project
        root do not collide.

        When ``recovery`` is True the agent is resuming an interrupted run.
        The flow/task_id/run_id files are left as-is and ``resume.md`` is
        rendered instead of ``start.md``.

        Returns (success, prompt_content, log_path).
        """
        if use_task_subdir:
            wt_llmflows = self.worktree_path / ".llmflows" / task_id
        else:
            wt_llmflows = self.worktree_path / ".llmflows"
        wt_llmflows.mkdir(parents=True, exist_ok=True)
        self._ensure_gitignore(wt_llmflows)
        context_svc = ContextService(wt_llmflows)

        if not recovery:
            (wt_llmflows / "flow").write_text(flow_name)
            (wt_llmflows / "task_id").write_text(task_id)
            (wt_llmflows / "run_id").write_text(run_id)

        if recovery and recovery_context:
            prompt_vars = {
                "flow_name": flow_name,
                "task_id": task_id,
                "task_description": task_description,
                "worktree_path": str(self.worktree_path) if self.worktree_path != self.project_dir.parent else None,
                "execution_history": execution_history or [],
                **recovery_context,
            }
            prompt_content = context_svc.render_recovery_instructions(prompt_vars)
        else:
            prompt_vars = {
                "flow_name": flow_name,
                "task_id": task_id,
                "task_name": task_name,
                "task_description": task_description,
                "task_type": task_type,
                "execution_history": execution_history or [],
            }
            prompt_content = context_svc.render_start_instructions(prompt_vars)

        prompts_dir = Path.home() / ".llmflows" / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        prompt_md = prompts_dir / f"{task_id}.md"
        prompt_md.write_text(prompt_content)

        if recovery:
            self._archive_agent_log(wt_llmflows, run_id, recovery_context)

        log_file = wt_llmflows / f"agent-{run_id}.log"
        pid_file = wt_llmflows / "agent.pid"
        launched = self._launch_agent(
            self.worktree_path, prompt_md, log_file, pid_file,
            model=model, agent=agent,
        )
        return launched, prompt_content, str(log_file)

    @staticmethod
    def _archive_agent_log(
        llmflows_dir: Path, run_id: str, recovery_context: Optional[dict] = None,
    ) -> None:
        """Rename the current agent log so the new attempt gets a clean file."""
        current_log = llmflows_dir / f"agent-{run_id}.log"
        if not current_log.exists():
            return
        attempt = (recovery_context or {}).get("recovery_attempt", 1)
        archived = llmflows_dir / f"agent-{run_id}.attempt-{attempt}.log"
        try:
            current_log.rename(archived)
        except OSError:
            pass

    @staticmethod
    def _ensure_gitignore(llmflows_dir: Path) -> None:
        """Ensure .llmflows/ has a .gitignore for ephemeral files."""
        gi = llmflows_dir / ".gitignore"
        entries = {"agent-*.log", "agent.pid", "flow", "task_id", "run_id"}
        if gi.exists():
            existing = gi.read_text()
            missing = [e for e in sorted(entries) if e not in existing]
            if not missing:
                return
            content = existing.rstrip("\n") + "\n" + "\n".join(missing) + "\n"
        else:
            content = "\n".join(sorted(entries)) + "\n"
        gi.write_text(content)

    def _launch_agent(
        self, directory: Path, prompt_file: Path, log_file: Path, pid_file: Path,
        model: str = "", agent: str = "cursor",
    ) -> bool:
        """Launch the selected agent backend with output streamed to a log file."""
        reg = AGENT_REGISTRY.get(agent)
        if not reg:
            logger.error("Unknown agent backend: %s", agent)
            return False

        prompt_content = prompt_file.read_text()

        try:
            cmd = self._build_agent_command(reg, prompt_file, prompt_content, model)
            env = os.environ.copy()
            env["IS_SANDBOX"] = "1"

            fh = open(log_file, "w")
            proc = subprocess.Popen(
                cmd,
                cwd=str(directory),
                stdout=fh,
                stderr=subprocess.STDOUT,
                env=env,
            )
            pid_file.write_text(str(proc.pid))
            return True
        except FileNotFoundError:
            logger.error("Agent binary '%s' not found in PATH", reg["binary"])
            return False

    @staticmethod
    def _build_agent_command(reg: dict, prompt_file: Path, prompt_content: str,
                             model: str) -> list[str]:
        """Build the CLI command list for a given agent backend."""
        binary = reg["binary"]
        mode = reg["prompt_mode"]

        if binary == "agent":
            cmd = ["agent", "-p", "-f", str(prompt_file),
                   "--output-format", "stream-json"]
            if model:
                cmd.extend(["--model", model])
            return cmd

        if binary == "claude":
            cmd = ["claude", "-p", prompt_content,
                   "--output-format", "stream-json", "--verbose",
                   "--dangerously-skip-permissions"]
            if model:
                cmd.extend(["--model", model])
            return cmd

        if binary == "codex":
            cmd = ["codex", "exec", "--json", prompt_content]
            return cmd

        if binary == "qwen":
            cmd = ["qwen", "-p", prompt_content, "-y",
                   "--output-format", "stream-json"]
            if model and model != "default":
                cmd.extend(["--model", model])
            return cmd

        # Fallback for unknown but registered agents
        cmd = [binary]
        if mode == "file":
            cmd.extend(["-f", str(prompt_file)])
        elif mode == "arg":
            cmd.append(prompt_content)
        return cmd

    @staticmethod
    def _resolve_pid_file(
        project_path: str, worktree_branch: str, task_id: str = ""
    ) -> Optional[Path]:
        """Return the agent.pid path for a task, or None if not locatable.

        When *worktree_branch* is set the pid file lives inside the worktree.
        When it is empty and *task_id* is provided the pid file lives in the
        project-level task subdir (no-git mode).
        """
        if worktree_branch:
            from .worktree import WorktreeService
            wt_path = WorktreeService(project_path).get_worktree_path(worktree_branch)
            if not wt_path:
                return None
            return wt_path / ".llmflows" / "agent.pid"
        if task_id:
            return Path(project_path) / ".llmflows" / task_id / "agent.pid"
        return None

    @staticmethod
    def kill_agent(project_path: str, worktree_branch: str, task_id: str = "") -> bool:
        """Kill the agent process for a task. Returns True if a process was killed."""
        pid_file = AgentService._resolve_pid_file(project_path, worktree_branch, task_id)
        if not pid_file or not pid_file.exists():
            return False
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            for _ in range(10):
                time.sleep(0.5)
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
            else:
                os.kill(pid, signal.SIGKILL)
            logger.info("Killed agent process %d", pid)
            pid_file.unlink(missing_ok=True)
            return True
        except (ValueError, ProcessLookupError, PermissionError):
            pid_file.unlink(missing_ok=True)
            return False

    @staticmethod
    def is_agent_running(project_path: str, worktree_branch: str, task_id: str = "") -> bool:
        """Check if an agent process is alive for a given task."""
        pid_file = AgentService._resolve_pid_file(project_path, worktree_branch, task_id)
        if not pid_file or not pid_file.exists():
            return False
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            return True
        except (ValueError, ProcessLookupError, PermissionError):
            pid_file.unlink(missing_ok=True)
            return False
