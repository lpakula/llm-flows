"""Agent launcher -- renders step prompts and launches Pi agents.

Each flow step runs as a separate agent process. The daemon orchestrates
step transitions; the agent receives a self-contained prompt, does the
work, and exits.

Agent output is streamed to a per-step log file.
Agent PID is stored in .llmflows/<flow>/runs/<run_id>/agent.pid for liveness checks.
"""

import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import re

from ..config import AGENT_REGISTRY, KNOWN_LLM_PROVIDERS, SYSTEM_DIR
from ..db.database import get_session
from ..db.models import AgentConfig
from ..utils.paths import space_execution_root
from .context import ContextService

logger = logging.getLogger("llmflows.agent")


class AgentService:
    def __init__(self, space_dir: Path, working_path: Optional[Path] = None):
        """Initialize agent service.

        Args:
            space_dir: .llmflows/ dir in the main space
            working_path: Root of the working directory for the agent
        """
        self.space_dir = space_dir
        self.working_path = working_path or space_dir.parent

    def prepare_and_launch_step(
        self,
        run_id: str,
        step_name: str,
        step_position: int,
        step_content: str,
        flow_name: str,
        model: str = "",
        agent: str = "pi",
        artifacts_dir: Optional[Path] = None,
        gate_failures: Optional[list[dict]] = None,
        resume_prompt: str = "",
        attempt: int = 1,
        user_responses: Optional[list[dict]] = None,
        step_type: str = "agent",
        space_variables: Optional[dict] = None,
        skills: Optional[list[dict]] = None,
        extensions: Optional[list[str]] = None,
        extra_env: Optional[dict[str, str]] = None,
    ) -> tuple[bool, str, str]:
        """Render a step prompt and launch an agent for it.

        Returns (success, prompt_content, log_path).
        """
        # Derive the space root from the working path (not space_dir.parent):
        # inside a runner container the working path is the /workspace mount,
        # while space_dir may still carry a host path from the DB.
        space_root = space_execution_root(str(self.working_path))
        if artifacts_dir is None:
            artifacts_dir = ContextService.get_artifacts_dir(
                space_root, run_id, flow_name,
            )
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        flow_dir = ContextService.get_flow_dir(space_root, flow_name)
        flow_dir.mkdir(parents=True, exist_ok=True)

        wt_llmflows = self.working_path / ".llmflows"
        wt_llmflows.mkdir(parents=True, exist_ok=True)
        self._ensure_gitignore(wt_llmflows)

        context_svc = ContextService(wt_llmflows)

        previous_artifacts = context_svc.collect_artifacts(artifacts_dir)

        is_summary = step_name == "__post_run__"
        step_output_dir = artifacts_dir / ContextService.step_dir_name(step_position, step_name) if not is_summary else None

        spc_vars = space_variables or {}
        step_dir = str(step_output_dir) if step_output_dir else ""
        attachment_dir = str(SYSTEM_DIR / "attachments" / run_id)
        from .audit import FlowAuditService
        audit = FlowAuditService.get_audit(str(space_root), flow_name) if flow_name else None

        prompt_vars = {
            "run_id": run_id,
            "run": {"id": run_id, "dir": str(artifacts_dir)},
            "flow_name": flow_name,
            "flow": {"name": flow_name, "dir": str(flow_dir)},
            "flow_dir": str(flow_dir),
            "space": {"dir": str(space_root)},
            "step_name": step_name,
            "step": {"dir": step_dir},
            "step_content": step_content,
            "artifacts": previous_artifacts,
            "attachment": {"dir": attachment_dir},
            "gate_failures": gate_failures,
            "resume_prompt": resume_prompt,
            "user_responses": user_responses or [],
            "step_type": step_type,
            "space_variables": spc_vars,
            "skills": skills or [],
            "audit_status": audit.status if audit else None,
            "audit_summary": audit.summary if audit else None,
            "audit_findings": audit.findings if audit else None,
        }
        prompt_content = context_svc.render_step_instructions(prompt_vars)
        prompt_content = self._rewrite_attachment_urls(prompt_content)

        prompts_dir = SYSTEM_DIR / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        prompt_md = prompts_dir / f"{run_id}-{ContextService.step_dir_name(step_position, step_name)}.md"
        prompt_md.write_text(prompt_content)

        safe_flow = ContextService._safe_flow_dir(flow_name) if flow_name else "_default"
        run_dir = wt_llmflows / safe_flow / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        attempt_suffix = f"-a{attempt}" if attempt and attempt > 1 else ""
        log_file = run_dir / f"agent-{ContextService.step_dir_name(step_position, step_name)}{attempt_suffix}.log"
        pid_file = run_dir / "agent.pid"
        launched = self._launch_agent(
            self.working_path, prompt_md, log_file, pid_file,
            model=model, agent=agent,
            space_variables=spc_vars,
            extensions=extensions,
            extra_env=extra_env,
        )
        return launched, prompt_content, str(log_file)

    @staticmethod
    def _rewrite_attachment_urls(text: str) -> str:
        """Replace /api/attachments/<run_id>/<file> with absolute local paths."""
        attachments_base = SYSTEM_DIR / "attachments"

        def replace(m: re.Match) -> str:
            run_id, filename = m.group(1), m.group(2)
            abs_path = attachments_base / run_id / filename
            return str(abs_path)

        return re.sub(r"/api/attachments/([^/]+)/([^\s\)\"']+)", replace, text)

    @staticmethod
    def _ensure_gitignore(llmflows_dir: Path) -> None:
        """Ensure .llmflows/ has a .gitignore for ephemeral files."""
        gi = llmflows_dir / ".gitignore"
        entries = {"*/runs/"}
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
        model: str = "", agent: str = "pi",
        space_variables: Optional[dict] = None,
        extensions: Optional[list[str]] = None,
        extra_env: Optional[dict[str, str]] = None,
    ) -> bool:
        """Launch the selected agent backend with output streamed to a log file."""
        reg = AGENT_REGISTRY.get(agent)
        if not reg:
            logger.error("Unknown agent backend: %s", agent)
            return False
        if "binary" not in reg:
            logger.error("Agent '%s' (type=%s) has no binary — cannot launch as subprocess", agent, reg.get("type"))
            return False

        prompt_content = prompt_file.read_text()

        try:
            mcp_config_file = self._write_mcp_config(reg, directory, extra_env)

            cmd = self._build_agent_command(
                reg, prompt_file, prompt_content, model,
                extensions=extensions, mcp_config_file=mcp_config_file,
            )
            env = os.environ.copy()
            venv_bin = str(Path(sys.prefix) / "bin")
            env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")

            session = get_session()
            try:
                for cfg in session.query(AgentConfig).filter_by(agent=agent).all():
                    env[cfg.key] = cfg.value
                if agent == "pi":
                    for provider in KNOWN_LLM_PROVIDERS:
                        for cfg in session.query(AgentConfig).filter_by(agent=provider).all():
                            if cfg.key not in env or not env[cfg.key]:
                                env[cfg.key] = cfg.value
            finally:
                session.close()

            if agent == "pi" and env.get("GEMINI_API_KEY"):
                env.pop("GOOGLE_API_KEY", None)

            for k, v in (space_variables or {}).items():
                env[k] = str(v)
            for k, v in (extra_env or {}).items():
                env[k] = v

            fh = open(log_file, "w")
            proc = subprocess.Popen(
                cmd,
                cwd=str(directory),
                stdin=subprocess.DEVNULL,
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
    def _write_mcp_config(reg: dict, cwd: Path, extra_env: Optional[dict[str, str]] = None) -> Optional[Path]:
        """MCP config for Pi is passed via extensions, not disk config files."""
        return None

    @staticmethod
    def _build_agent_command(reg: dict, prompt_file: Path, prompt_content: str,
                             model: str, extensions: Optional[list[str]] = None,
                             mcp_config_file: Optional[Path] = None) -> list[str]:
        """Build the CLI command list for Pi."""
        binary = reg["binary"]

        if binary == "pi":
            cmd = ["pi", "-p", prompt_content, "--mode", "json"]
            if model:
                cmd.extend(["--model", model])
            for ext in (extensions or []):
                cmd.extend(["--extension", ext])
            return cmd

        raise ValueError(f"Unsupported agent binary: {binary}")

    @staticmethod
    def _resolve_pid_file(
        project_path: str, run_id: str = "", flow_name: str = "",
    ) -> Optional[Path]:
        """Return the agent.pid path for a run, or None if not locatable."""
        if run_id:
            safe_flow = ContextService._safe_flow_dir(flow_name) if flow_name else "_default"
            return Path(project_path) / ".llmflows" / safe_flow / "runs" / run_id / "agent.pid"
        return None

    @staticmethod
    def kill_agent(project_path: str, run_id: str = "", flow_name: str = "") -> bool:
        """Kill the agent process for a run. Returns True if a process was killed."""
        pid_file = AgentService._resolve_pid_file(project_path, run_id, flow_name)
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
    def is_agent_running(project_path: str, run_id: str = "", flow_name: str = "") -> bool:
        """Check if an agent process is alive for a given run."""
        pid_file = AgentService._resolve_pid_file(project_path, run_id, flow_name)
        if not pid_file or not pid_file.exists():
            return False
        try:
            pid = int(pid_file.read_text().strip())
            # Try to reap zombie child first
            try:
                result = os.waitpid(pid, os.WNOHANG)
                if result[0] != 0:
                    pid_file.unlink(missing_ok=True)
                    return False
            except ChildProcessError:
                pass
            os.kill(pid, 0)
            return True
        except (ValueError, ProcessLookupError, PermissionError):
            pid_file.unlink(missing_ok=True)
            return False
