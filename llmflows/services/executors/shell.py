"""Shell executor -- runs step content as a shell command.

Synchronous: launch() blocks until the command finishes, captures
stdout/stderr to _result.md, and returns with is_sync=True.
"""

import logging
import subprocess
from typing import Optional

from .base import LaunchResult, StepContext, StepExecutor

logger = logging.getLogger("llmflows.executor.shell")


class ShellExecutor(StepExecutor):

    def launch(self, ctx: StepContext) -> LaunchResult:
        command = ctx.step_content.strip()
        if not command:
            return LaunchResult(
                success=False, output="No command specified in step content.",
                is_sync=True,
            )

        env = None
        if ctx.space_variables:
            import os
            env = os.environ.copy()
            for k, v in ctx.space_variables.items():
                env[k] = str(v)

        logger.info("Shell exec: step=%s cmd=%s", ctx.step_name, command[:120])
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(ctx.working_path),
                capture_output=True,
                text=True,
                timeout=600,
                env=env,
            )
            parts = []
            if result.stdout:
                parts.append(f"## stdout\n\n```\n{result.stdout}\n```")
            if result.stderr:
                parts.append(f"## stderr\n\n```\n{result.stderr}\n```")
            parts.append(f"\n**Exit code:** {result.returncode}")
            output = "\n\n".join(parts)
            success = result.returncode == 0
        except subprocess.TimeoutExpired:
            output = "## Error\n\nCommand timed out after 600 seconds."
            success = False
        except Exception as e:
            output = f"## Error\n\nFailed to execute command: {e}"
            success = False

        step_output_dir = ctx.artifacts_dir / f"{ctx.step_position:02d}-{ctx.step_name}"
        step_output_dir.mkdir(parents=True, exist_ok=True)
        result_file = step_output_dir / "_result.md"
        result_file.write_text(output)

        return LaunchResult(
            success=success,
            prompt_content=command,
            output=output,
            is_sync=True,
        )

    def is_running(self, ctx: StepContext) -> bool:
        return False

    def get_output(self, ctx: StepContext) -> Optional[str]:
        result_file = ctx.artifacts_dir / f"{ctx.step_position:02d}-{ctx.step_name}" / "_result.md"
        if result_file.exists():
            return result_file.read_text()
        return None
