"""Pi executor -- runs default and hitl steps via the Pi coding agent.

Pi provides tool-use (read/write/edit/bash) on top of any LLM provider.
This executor reuses AgentService to spawn Pi as a subprocess, identical
to how CodeExecutor works for Cursor/Claude Code.
"""

import logging
from typing import Optional

from .base import LaunchResult, StepContext, StepExecutor
from ..agent import AgentService

logger = logging.getLogger("llmflows.executor.pi")


class PiExecutor(StepExecutor):

    def launch(self, ctx: StepContext) -> LaunchResult:
        worktree = ctx.worktree_path or ctx.working_path
        agent_svc = AgentService(ctx.space_dir, worktree)

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
        )

        return LaunchResult(
            success=launched,
            prompt_content=prompt_content,
            log_path=log_path,
            is_sync=False,
        )

    def is_running(self, ctx: StepContext) -> bool:
        return AgentService.is_agent_running(
            str(ctx.working_path), run_id=ctx.run_id,
        )

    def get_output(self, ctx: StepContext) -> Optional[str]:
        result_file = ctx.artifacts_dir / f"{ctx.step_position:02d}-{ctx.step_name}" / "_result.md"
        if result_file.exists():
            return result_file.read_text()
        return None
