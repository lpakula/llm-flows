"""LLM executor -- direct LLM API calls via litellm.

Synchronous: launch() blocks until the LLM responds, writes output to
_result.md, and returns with is_sync=True.  Supports provider-native tools
like web_search.
"""

import logging
import os
from typing import Optional

from .base import LaunchResult, StepContext, StepExecutor

logger = logging.getLogger("llmflows.executor.llm")

TOOL_MAP = {
    "openai": {
        "web_search": {"type": "web_search"},
    },
    "anthropic": {
        "web_search": {"type": "web_search_20260209", "name": "web_search"},
    },
    "google": {
        "web_search": {"google_search": {}},
    },
}


def _build_litellm_tools(provider: str, tool_names: list[str]) -> list[dict]:
    """Map abstract tool names to provider-native tool payloads."""
    provider_tools = TOOL_MAP.get(provider, {})
    result = []
    for name in tool_names:
        payload = provider_tools.get(name)
        if payload:
            result.append(payload)
        else:
            logger.warning("Tool '%s' not supported by provider '%s'", name, provider)
    return result


def _load_api_key(provider: str) -> Optional[str]:
    """Load API key from AgentConfig DB or environment."""
    from ...config import AGENT_REGISTRY
    reg = AGENT_REGISTRY.get(provider, {})
    env_var = reg.get("api_key_env", "")

    if env_var and os.environ.get(env_var):
        return os.environ[env_var]

    try:
        from ...db.database import get_session
        from ...db.models import AgentConfig
        session = get_session()
        try:
            cfg = session.query(AgentConfig).filter_by(
                agent=provider, key=env_var,
            ).first()
            if cfg and cfg.value:
                return cfg.value
        finally:
            session.close()
    except Exception:
        pass

    return None


def _build_previous_context(ctx: StepContext) -> str:
    """Build a context block from previous step artifacts."""
    parts = []
    if ctx.gate_failures:
        parts.append("## Previous Attempt Failed\n")
        for f in ctx.gate_failures:
            parts.append(f"- Gate `{f.get('command', '')}`: {f.get('message', '')}")
            if f.get("output"):
                parts.append(f"```\n{f['output']}\n```")
    if ctx.user_responses:
        parts.append("\n## User Responses\n")
        for ur in ctx.user_responses:
            parts.append(f"### {ur.get('step_name', '')}\n> {ur.get('user_response', '')}")
    if ctx.resume_prompt:
        parts.append(f"\n## Additional Context\n{ctx.resume_prompt}")
    return "\n".join(parts)


class LLMExecutor(StepExecutor):

    def launch(self, ctx: StepContext) -> LaunchResult:
        import litellm

        api_key = _load_api_key(ctx.agent)
        if api_key:
            env_var = f"{ctx.agent.upper()}_API_KEY"
            os.environ[env_var] = api_key

        model = f"{ctx.agent}/{ctx.model}" if "/" not in ctx.model else ctx.model

        messages = []

        system_msg = (
            "You are an autonomous AI agent executing a step of a larger workflow. "
            "Follow the instructions precisely and provide a thorough response."
        )
        messages.append({"role": "system", "content": system_msg})

        user_parts = []
        extra_context = _build_previous_context(ctx)
        if extra_context:
            user_parts.append(extra_context)
        user_parts.append(ctx.step_content)
        messages.append({"role": "user", "content": "\n\n".join(user_parts)})

        kwargs: dict = {
            "model": model,
            "messages": messages,
        }

        if ctx.tools:
            native_tools = _build_litellm_tools(ctx.agent, ctx.tools)
            if native_tools:
                kwargs["tools"] = native_tools

        try:
            logger.info(
                "LLM call: model=%s tools=%s step=%s",
                model, ctx.tools, ctx.step_name,
            )
            response = litellm.completion(**kwargs)
            output = response.choices[0].message.content or ""
        except Exception as e:
            logger.error("LLM call failed for step '%s': %s", ctx.step_name, e)
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
