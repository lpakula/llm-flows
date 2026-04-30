"""Pi executor -- runs default and hitl steps via the Pi coding agent.

Pi provides tool-use (read/write/edit/bash) on top of any LLM provider.
This executor reuses AgentService to spawn Pi as a subprocess, identical
to how CodeExecutor works for Cursor/Claude Code.

All external tools (web search, browser, third-party connectors) are
provided via MCP servers.  When the daemon passes MCP_SERVERS in
ctx.extra_env, we load the mcp-bridge.ts extension which spawns MCP
servers as stdio subprocesses and registers their tools dynamically.
"""

import logging
from pathlib import Path
from typing import Optional

from .base import LaunchResult, StepContext, StepExecutor
from ..agent import AgentService
from ...config import SYSTEM_DIR

logger = logging.getLogger("llmflows.executor.pi")

_TOOLS_DIR = Path(__file__).resolve().parent.parent.parent / "tools"
_NODE_MODULES = SYSTEM_DIR / "node_modules"
MCP_BRIDGE_TOOL = _TOOLS_DIR / "mcp-bridge.ts"


class PiExecutor(StepExecutor):

    def launch(self, ctx: StepContext) -> LaunchResult:
        agent_svc = AgentService(ctx.space_dir, ctx.working_path)

        extensions: list[str] = []
        extra_env: dict[str, str] = {}

        if ctx.extra_env:
            extra_env.update(ctx.extra_env)

        if extra_env.get("MCP_SERVERS"):
            extensions.append(str(MCP_BRIDGE_TOOL))
            extra_env["NODE_PATH"] = str(_NODE_MODULES)

        launched, prompt_content, log_path = agent_svc.prepare_and_launch_step(
            run_id=ctx.run_id,
            step_name=ctx.step_name,
            step_position=ctx.step_position,
            step_content=ctx.step_content,
            flow_name=ctx.flow_name,
            model=ctx.model,
            agent=ctx.agent or "pi",
            artifacts_dir=ctx.artifacts_dir,
            gate_failures=ctx.gate_failures,
            resume_prompt=ctx.resume_prompt,
            attempt=ctx.attempt,
            user_responses=ctx.user_responses,
            step_type=ctx.step_type,
            space_variables=ctx.space_variables,
            skills=ctx.skills,
            extensions=extensions,
            extra_env=extra_env,
        )

        return LaunchResult(
            success=launched,
            prompt_content=prompt_content,
            log_path=log_path,
            is_sync=False,
        )

    def is_running(self, ctx: StepContext) -> bool:
        alive = AgentService.is_agent_running(
            str(ctx.working_path), run_id=ctx.run_id, flow_name=ctx.flow_name,
        )
        if not alive:
            return False
        # Pi may have finished but the process hangs because an extension
        # (e.g. browser) keeps a WebSocket connection alive.
        #
        # The NDJSON log's "agent_end" event is the definitive completion
        # marker — the same signal the UI uses to render "Pi agent finished".
        # It appears exactly once, as the last line.  The line can be 100 KB+
        # (it embeds the full conversation), so we read a generous tail.
        if ctx.log_path:
            try:
                log = Path(ctx.log_path)
                if log.exists() and log.stat().st_size > 0:
                    size = log.stat().st_size
                    # Read last 1MB to handle large agent_end events
                    tail = log.read_bytes()[-1_048_576:]
                    if b'"type":"agent_end"' in tail:
                        logger.info("Pi finished but process still alive — killing")
                        AgentService.kill_agent(
                            str(ctx.working_path), run_id=ctx.run_id, flow_name=ctx.flow_name,
                        )
                        return False
                    # If log hasn't grown in 60s and is large, agent is likely
                    # done but agent_end was truncated — kill to unblock.
                    if size > 1_048_576:
                        mtime = log.stat().st_mtime
                        if (__import__("time").time() - mtime) > 60:
                            logger.warning(
                                "Pi log stale for >60s and agent_end not found — killing (size=%d)",
                                size,
                            )
                            AgentService.kill_agent(
                                str(ctx.working_path), run_id=ctx.run_id, flow_name=ctx.flow_name,
                            )
                            return False
            except Exception:
                pass
        return True

    def get_output(self, ctx: StepContext) -> Optional[str]:
        result_file = ctx.artifacts_dir / ctx.step_dir_name / "_result.md"
        if result_file.exists():
            return result_file.read_text()
        return None
