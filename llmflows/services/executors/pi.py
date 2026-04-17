"""Pi executor -- runs default and hitl steps via the Pi coding agent.

Pi provides tool-use (read/write/edit/bash) on top of any LLM provider.
This executor reuses AgentService to spawn Pi as a subprocess, identical
to how CodeExecutor works for Cursor/Claude Code.

When web search is enabled in config.toml ([web_search] enabled = true),
the web-search extension is loaded, giving Pi runs access to web_search
and web_fetch tools.

When browser is enabled and BROWSER_WS_ENDPOINT is set in ctx.extra_env,
the browser extension is loaded, giving Pi runs access to browser_navigate,
browser_snapshot, browser_click, browser_fill, and browser_screenshot tools.
"""

import logging
from pathlib import Path
from typing import Optional

from .base import LaunchResult, StepContext, StepExecutor
from ..agent import AgentService

logger = logging.getLogger("llmflows.executor.pi")

_TOOLS_DIR = Path(__file__).resolve().parent.parent.parent / "tools"
_NODE_MODULES = Path.home() / ".llmflows" / "node_modules"
WEB_SEARCH_TOOL = _TOOLS_DIR / "web-search.ts"
BROWSER_TOOL = _TOOLS_DIR / "browser.ts"


def _load_web_search_config() -> dict:
    """Read [web_search] section from config.toml."""
    from ...config import load_system_config
    return load_system_config().get("web_search", {})


def _is_web_search_enabled() -> bool:
    return _load_web_search_config().get("enabled", False)


def _resolve_web_search_env() -> dict[str, str]:
    """Return env vars for the web-search extension."""
    ws = _load_web_search_config()
    env: dict[str, str] = {}
    provider = ws.get("provider", "duckduckgo")
    env["LLMFLOWS_WEB_SEARCH_PROVIDER"] = provider
    if provider == "brave":
        key = ws.get("brave_api_key", "")
        if key:
            env["BRAVE_API_KEY"] = key
    elif provider == "perplexity":
        key = ws.get("perplexity_api_key", "")
        if key:
            env["PERPLEXITY_API_KEY"] = key
    elif provider == "serpapi":
        key = ws.get("serpapi_api_key", "")
        if key:
            env["SERPAPI_API_KEY"] = key
    return env


class PiExecutor(StepExecutor):

    def launch(self, ctx: StepContext) -> LaunchResult:
        agent_svc = AgentService(ctx.space_dir, ctx.working_path)

        extensions = []
        extra_env: dict[str, str] = {}
        if _is_web_search_enabled():
            extensions.append(str(WEB_SEARCH_TOOL))
            extra_env.update(_resolve_web_search_env())

        if ctx.extra_env:
            extra_env.update(ctx.extra_env)
            if ctx.extra_env.get("BROWSER_WS_ENDPOINT"):
                extensions.append(str(BROWSER_TOOL))

        if extensions:
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
                    tail = log.read_bytes()[-262144:]
                    if b'"type":"agent_end"' in tail:
                        logger.info("Pi finished but process still alive — killing")
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
