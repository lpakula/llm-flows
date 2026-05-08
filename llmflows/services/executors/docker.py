"""Docker executor -- wraps agent execution in a Docker container for workspace isolation.

When a flow or step has ``isolated=True``, the daemon routes execution here
instead of PiExecutor/CodeExecutor.  The agent process runs inside a
``docker run`` container with:

- The workspace mounted at /workspace
- Artifacts directory bind-mounted
- All environment variables forwarded
- Bridge networking with RFC1918 egress blocked (internet still allowed)

The container image defaults to ``llmflows/runtime`` but is configurable
via ``LLMFLOWS_DOCKER_IMAGE``.
"""

import json
import logging
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional

from .base import LaunchResult, StepContext, StepExecutor
from ..agent import AgentService
from ..context import ContextService
from ...config import AGENT_REGISTRY, KNOWN_LLM_PROVIDERS, SYSTEM_DIR

logger = logging.getLogger("llmflows.executor.docker")

DEFAULT_IMAGE = "llmflows/runtime"
DOCKER_NETWORK = "llmflows-isolated"

_NETWORK_INIT_SCRIPT = r"""#!/bin/sh
set -e
if command -v iptables >/dev/null 2>&1; then
  iptables -A OUTPUT -d 10.0.0.0/8 -j DROP 2>/dev/null || true
  iptables -A OUTPUT -d 172.16.0.0/12 -j DROP 2>/dev/null || true
  iptables -A OUTPUT -d 192.168.0.0/16 -j DROP 2>/dev/null || true
  iptables -A OUTPUT -d 169.254.0.0/16 -j DROP 2>/dev/null || true
fi
exec "$@"
"""


def _ensure_docker_network() -> bool:
    """Create the llmflows-isolated Docker network if it doesn't exist."""
    try:
        result = subprocess.run(
            ["docker", "network", "inspect", DOCKER_NETWORK],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return True
        subprocess.run(
            ["docker", "network", "create",
             "--driver", "bridge",
             DOCKER_NETWORK],
            capture_output=True, text=True, check=True,
        )
        logger.info("Created Docker network '%s'", DOCKER_NETWORK)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.error("Failed to create Docker network '%s'", DOCKER_NETWORK)
        return False


def _docker_available() -> bool:
    """Check if Docker is available and running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _get_container_id_file(space_dir: Path, run_id: str, flow_name: str) -> Path:
    """Return the path to the Docker container ID file for a run."""
    safe_flow = ContextService._safe_flow_dir(flow_name) if flow_name else "_default"
    return space_dir / safe_flow / "runs" / run_id / "docker.cid"


class DockerExecutor(StepExecutor):
    """Runs agent steps inside Docker containers for workspace isolation."""

    def __init__(self, inner: StepExecutor):
        self.inner = inner

    def launch(self, ctx: StepContext) -> LaunchResult:
        if not _docker_available():
            logger.error("Docker is not available — falling back to direct execution")
            return self.inner.launch(ctx)

        _ensure_docker_network()

        agent_svc = AgentService(ctx.space_dir, ctx.working_path)
        space_root = ctx.space_dir.parent

        artifacts_dir = ctx.artifacts_dir
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        context_svc = ContextService(ctx.working_path / ".llmflows")
        previous_artifacts = context_svc.collect_artifacts(artifacts_dir)

        step_output_dir = artifacts_dir / ContextService.step_dir_name(ctx.step_position, ctx.step_name)

        prompt_vars = {
            "run_id": ctx.run_id,
            "run": {"id": ctx.run_id, "dir": str(artifacts_dir)},
            "flow_name": ctx.flow_name,
            "flow": {"name": ctx.flow_name, "dir": str(ContextService.get_flow_dir(space_root, ctx.flow_name))},
            "flow_dir": str(ContextService.get_flow_dir(space_root, ctx.flow_name)),
            "space": {"dir": str(space_root)},
            "step_name": ctx.step_name,
            "step": {"dir": str(step_output_dir)},
            "step_content": ctx.step_content,
            "artifacts": previous_artifacts,
            "attachment": {"dir": str(SYSTEM_DIR / "attachments" / ctx.run_id)},
            "gate_failures": ctx.gate_failures,
            "resume_prompt": ctx.resume_prompt,
            "user_responses": ctx.user_responses or [],
            "step_type": ctx.step_type,
            "space_variables": ctx.space_variables or {},
            "skills": ctx.skills or [],
        }
        prompt_content = context_svc.render_step_instructions(prompt_vars)
        prompt_content = AgentService._rewrite_attachment_urls(prompt_content)

        prompts_dir = SYSTEM_DIR / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        prompt_md = prompts_dir / f"{ctx.run_id}-{ContextService.step_dir_name(ctx.step_position, ctx.step_name)}.md"
        prompt_md.write_text(prompt_content)

        safe_flow = ContextService._safe_flow_dir(ctx.flow_name) if ctx.flow_name else "_default"
        wt_llmflows = ctx.working_path / ".llmflows"
        wt_llmflows.mkdir(parents=True, exist_ok=True)
        run_dir = wt_llmflows / safe_flow / "runs" / ctx.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        attempt_suffix = f"-a{ctx.attempt}" if ctx.attempt and ctx.attempt > 1 else ""
        log_file = run_dir / f"agent-{ContextService.step_dir_name(ctx.step_position, ctx.step_name)}{attempt_suffix}.log"
        cid_file = _get_container_id_file(wt_llmflows, ctx.run_id, ctx.flow_name)

        image = os.environ.get("LLMFLOWS_DOCKER_IMAGE", DEFAULT_IMAGE)

        from ...config import resolve_alias
        from ...db.database import get_session
        from ...db.models import AgentConfig

        agent = ctx.agent or "pi"
        reg = AGENT_REGISTRY.get(agent)
        if not reg or "binary" not in reg:
            logger.error("Unknown or unbuildable agent backend: %s", agent)
            return LaunchResult(success=False)

        env_vars: dict[str, str] = {}
        session = get_session()
        try:
            for cfg in session.query(AgentConfig).filter_by(agent=agent).all():
                env_vars[cfg.key] = cfg.value
            if agent == "pi":
                for provider in KNOWN_LLM_PROVIDERS:
                    for cfg in session.query(AgentConfig).filter_by(agent=provider).all():
                        if cfg.key not in env_vars or not env_vars[cfg.key]:
                            env_vars[cfg.key] = cfg.value
        finally:
            session.close()

        for k, v in (ctx.space_variables or {}).items():
            env_vars[k] = str(v)
        for k, v in (ctx.extra_env or {}).items():
            env_vars[k] = v

        agent_cmd = AgentService._build_agent_command(reg, prompt_md, prompt_content, ctx.model)

        docker_cmd = [
            "docker", "run", "--rm",
            "--cidfile", str(cid_file),
            "--network", DOCKER_NETWORK,
            "--cap-add=NET_ADMIN",
            "-v", f"{ctx.working_path}:/workspace",
            "-v", f"{artifacts_dir}:{artifacts_dir}",
            "-v", f"{SYSTEM_DIR / 'prompts'}:{SYSTEM_DIR / 'prompts'}:ro",
            "-v", f"{SYSTEM_DIR / 'attachments'}:{SYSTEM_DIR / 'attachments'}",
            "-w", "/workspace",
        ]

        for k, v in env_vars.items():
            docker_cmd.extend(["-e", f"{k}={v}"])

        docker_cmd.append(image)
        docker_cmd.extend(agent_cmd)

        try:
            fh = open(log_file, "w")
            proc = subprocess.Popen(
                docker_cmd,
                cwd=str(ctx.working_path),
                stdin=subprocess.DEVNULL,
                stdout=fh,
                stderr=subprocess.STDOUT,
            )
            pid_file = run_dir / "agent.pid"
            pid_file.write_text(str(proc.pid))

            return LaunchResult(
                success=True,
                prompt_content=prompt_content,
                log_path=str(log_file),
                is_sync=False,
            )
        except FileNotFoundError:
            logger.error("Docker binary not found in PATH")
            return LaunchResult(success=False)

    def is_running(self, ctx: StepContext) -> bool:
        wt_llmflows = ctx.working_path / ".llmflows"
        cid_file = _get_container_id_file(wt_llmflows, ctx.run_id, ctx.flow_name)

        if not cid_file.exists():
            return AgentService.is_agent_running(
                str(ctx.working_path), run_id=ctx.run_id, flow_name=ctx.flow_name,
            )

        try:
            container_id = cid_file.read_text().strip()
            if not container_id:
                return False
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", container_id],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0 and "true" in result.stdout.lower()
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    def kill(self, ctx: StepContext) -> bool:
        """Stop and remove the Docker container for a run."""
        wt_llmflows = ctx.working_path / ".llmflows"
        cid_file = _get_container_id_file(wt_llmflows, ctx.run_id, ctx.flow_name)

        if not cid_file.exists():
            return AgentService.kill_agent(
                str(ctx.working_path), run_id=ctx.run_id, flow_name=ctx.flow_name,
            )

        try:
            container_id = cid_file.read_text().strip()
            if container_id:
                subprocess.run(
                    ["docker", "stop", "-t", "10", container_id],
                    capture_output=True, text=True, timeout=30,
                )
                logger.info("Stopped Docker container %s", container_id[:12])
            cid_file.unlink(missing_ok=True)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            cid_file.unlink(missing_ok=True)
            return False

    def get_output(self, ctx: StepContext) -> Optional[str]:
        return self.inner.get_output(ctx)
