"""Agent launcher -- writes prompt and launches coding agents.

Supports multiple agent backends (Cursor, Claude Code, Codex).
Agent output is streamed to .llmflows/agent-{run_id}.log in the worktree.
Agent PID is stored in .llmflows/agent.pid for liveness checks.
"""

import logging
import os
import shutil
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
    ) -> tuple[bool, str, str]:
        """Write prompt in the worktree, then launch the selected agent.

        Returns (success, prompt_content, log_path).
        """
        wt_llmflows = self.worktree_path / ".llmflows"
        wt_llmflows.mkdir(parents=True, exist_ok=True)
        self._ensure_gitignore(wt_llmflows)
        context_svc = ContextService(wt_llmflows)

        (wt_llmflows / "flow").write_text(flow_name)
        (wt_llmflows / "task_id").write_text(task_id)
        (wt_llmflows / "run_id").write_text(run_id)

        self._copy_cursor_rule()

        from ..utils.git import _run_git, get_worktree_diff
        worktree_str = str(self.worktree_path)
        log_output = _run_git(["log", "main..HEAD", "--oneline"], cwd=worktree_str)
        git_log = log_output.strip() if log_output else ""
        git_diff_stat = get_worktree_diff(base="main", cwd=worktree_str)

        prompt_vars = {
            "flow_name": flow_name,
            "task_id": task_id,
            "task_name": task_name,
            "task_description": task_description,
            "task_type": task_type,
            "execution_history": execution_history or [],
            "git_log": git_log,
            "git_diff_stat": git_diff_stat,
        }
        prompt_content = context_svc.render_start_instructions(prompt_vars)

        prompts_dir = Path.home() / ".llmflows" / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        prompt_md = prompts_dir / f"{task_id}.md"
        prompt_md.write_text(prompt_content)

        log_file = wt_llmflows / f"agent-{run_id}.log"
        pid_file = wt_llmflows / "agent.pid"
        launched = self._launch_agent(
            self.worktree_path, prompt_md, log_file, pid_file,
            model=model, agent=agent,
        )
        return launched, prompt_content, str(log_file)

    def _copy_cursor_rule(self) -> None:
        """Copy .cursor/rules/llmflows.md from main project into worktree."""
        main_project = self.project_dir.parent
        rule_src = main_project / ".cursor" / "rules" / "llmflows.md"
        if not rule_src.exists():
            return

        rule_dest_dir = self.worktree_path / ".cursor" / "rules"
        rule_dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rule_src, rule_dest_dir / "llmflows.md")

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

            fh = open(log_file, "w")
            proc = subprocess.Popen(
                cmd,
                cwd=str(directory),
                stdout=fh,
                stderr=subprocess.STDOUT,
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
            cmd = ["claude", "-p", prompt_content, "--output-format", "json"]
            if model:
                cmd.extend(["--model", model])
            return cmd

        if binary == "codex":
            cmd = ["codex", "exec", "--json", prompt_content]
            return cmd

        # Fallback for unknown but registered agents
        cmd = [binary]
        if mode == "file":
            cmd.extend(["-f", str(prompt_file)])
        elif mode == "arg":
            cmd.append(prompt_content)
        return cmd

    @staticmethod
    def kill_agent(project_path: str, worktree_branch: str) -> bool:
        """Kill the agent process for a worktree. Returns True if a process was killed."""
        if not worktree_branch:
            return False
        from .worktree import WorktreeService
        wt_svc = WorktreeService(project_path)
        wt_path = wt_svc.get_worktree_path(worktree_branch)
        if not wt_path:
            return False
        pid_file = wt_path / ".llmflows" / "agent.pid"
        if not pid_file.exists():
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
    def is_agent_running(project_path: str, worktree_branch: str) -> bool:
        """Check if an agent process is alive for a given worktree."""
        if not worktree_branch:
            return False
        from .worktree import WorktreeService
        wt_svc = WorktreeService(project_path)
        wt_path = wt_svc.get_worktree_path(worktree_branch)
        if not wt_path:
            return False
        pid_file = wt_path / ".llmflows" / "agent.pid"
        if not pid_file.exists():
            return False
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            return True
        except (ValueError, ProcessLookupError, PermissionError):
            pid_file.unlink(missing_ok=True)
            return False
