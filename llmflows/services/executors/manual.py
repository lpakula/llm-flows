"""Manual executor -- LLM generates user-facing content, then awaits user response.

Uses the same LLM call as LLMExecutor to generate content, writes it to
_result.md, then returns with is_sync=True.  The daemon handles the
awaiting_user / inbox logic after this executor completes.
"""

import logging
import os
from typing import Optional

from .base import LaunchResult, StepContext, StepExecutor

logger = logging.getLogger("llmflows.executor.manual")


class ManualExecutor(StepExecutor):

    def launch(self, ctx: StepContext) -> LaunchResult:
        import litellm
        from .llm import _load_api_key, _build_litellm_tools, _build_previous_context

        api_key = _load_api_key(ctx.agent)
        if api_key:
            env_var = f"{ctx.agent.upper()}_API_KEY"
            os.environ[env_var] = api_key

        model = f"{ctx.agent}/{ctx.model}" if "/" not in ctx.model else ctx.model

        system_msg = (
            "You are an autonomous AI agent executing a step of a larger workflow. "
            "Your output will be shown directly to a human user in a UI card. "
            "The user has a text input field to type a response and a Submit button.\n\n"
            "- Present your analysis, options, or question clearly -- format for a human reader\n"
            "- Use headers, numbered lists, pros/cons tables where appropriate\n"
            "- End with a clear, specific question the user should answer\n"
            "- The user will reply with a short text answer -- frame your question so a brief response is sufficient"
        )

        messages = [
            {"role": "system", "content": system_msg},
        ]

        user_parts = []
        extra_context = _build_previous_context(ctx)
        if extra_context:
            user_parts.append(extra_context)
        user_parts.append(ctx.step_content)
        messages.append({"role": "user", "content": "\n\n".join(user_parts)})

        kwargs: dict = {"model": model, "messages": messages}
        if ctx.tools:
            native_tools = _build_litellm_tools(ctx.agent, ctx.tools)
            if native_tools:
                kwargs["tools"] = native_tools

        try:
            logger.info("Manual LLM call: model=%s step=%s", model, ctx.step_name)
            response = litellm.completion(**kwargs)
            output = response.choices[0].message.content or ""
        except Exception as e:
            logger.error("Manual LLM call failed for step '%s': %s", ctx.step_name, e)
            output = f"## Error\n\nLLM call failed: {e}"

        step_output_dir = ctx.artifacts_dir / f"{ctx.step_position:02d}-{ctx.step_name}"
        step_output_dir.mkdir(parents=True, exist_ok=True)
        result_file = step_output_dir / "_result.md"
        result_file.write_text(output)

        return LaunchResult(
            success=True,
            prompt_content=messages[-1]["content"],
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
