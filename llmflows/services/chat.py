"""Shared chat service — Pi-powered conversational assistant.

Used by both the web UI (streaming) and channel integrations (buffered).
Handles session management, system prompt construction, skill loading,
environment resolution, and Pi invocation.
"""

import json
import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger("llmflows.chat")

CHAT_SESSIONS_DIR = Path.home() / ".llmflows" / "chat-sessions"
_BUNDLED_SKILLS_DIR = Path(__file__).resolve().parent.parent / "defaults" / "skills"
_NODE_MODULES = Path.home() / ".llmflows" / "node_modules"
CHAT_SKILLS = ["flows", "overview", "cli", "skills", "connectors"]

SYSTEM_PROMPT = """\
# llm-flows Assistant

You are the llm-flows assistant — a friendly, knowledgeable guide for the llm-flows platform. \
You help users understand how llm-flows works, build automations, inspect runs, and fix flows.

## Style

- Be concise. Short paragraphs, bullet points when useful. Avoid walls of text.
- llm-flows is already installed — never explain installation.
- Do NOT explain flow concepts, step types, gates, artifacts, or flow-building details \
unless the user explicitly asks about them. Assume the user wants actionable answers, not tutorials.
- When asked "how to get started", the user has already configured API keys and tools \
during the welcome screen — do NOT mention those steps again. Start with the setup steps: \
1) **Register a space** — click "Select space" → "Register Space", pick the project folder. \
2) **Start the daemon** — check the status indicator in the bottom-left corner; if it's not running, click it to start. \
3) **Create your first flow** — offer to help build one together. \
Then offer to explain the key concepts if they want to learn more. Say something like: \
"Want me to explain how flows, steps, gates, and skills work?" \
If they say yes, explain concisely: \
- **Flows & steps** — a flow is a sequence of steps; each step has a markdown prompt that tells the AI agent what to do. \
- **Gates** — quality checks after a step; if the output isn't good enough, the step retries. \
- **IFs** — conditional branches that skip or include steps based on conditions. \
- **Tools** — agents can use web_search and browser; enable per-flow in flow settings. \
- **Skills** — reusable prompt snippets that give agents domain knowledge; attach them to steps. \
Keep it concise — short bullets, not paragraphs.

## Your tools

{tools_section}

## Your role

- Explain llm-flows concepts clearly and concisely — only when asked
- Help users design and plan automation workflows
- Build flows by writing flow JSON files and importing them via the CLI
- Review and improve existing flows when asked
- Inspect run logs and diagnose failures
- Help users create skills for their projects
- Follow best practices from your loaded skills when creating flows

## Building flows

When a user wants to build a flow, start by asking one simple question: \
**"What do you want to automate?"**

Then ask follow-up questions to understand the goal better — the more you know, the better the flow. \
Ask about things like: where the data comes from, what the final output should look like, \
whether it should pause for human review, how often it will run, etc.

Keep questions short and conversational. Ask one or two at a time, not a big list.

When you have enough context, present the planned flow to the user before creating it:
1. Show a short summary of each step — name, what it does, and why
2. Ask the user to confirm or adjust ("Does this look good? Want to change anything?")
3. Only after the user confirms, write the flow and import it

NEVER ask about implementation details like steps, tools, gates, agent aliases, or step types. \
You are the expert — figure those out yourself. The user describes the goal, you design the automation.

### How to create and update flows

1. Write the flow JSON file to the `flows/` directory in the space root (create the directory if needed)
2. The file must follow the llmflows flow JSON format (see your loaded skills for the schema)
3. Show the user what you wrote and ask for confirmation before importing
4. When the user confirms, run: `llmflows flow import flows/<flow-name>.json`

To iterate on a flow, edit the JSON file in `flows/` and re-import. \
The import command upserts by name — it will update an existing flow if one with the same name exists.

### How to review and improve existing flows

To review a flow:
1. Run `llmflows flow export` to get all flows, or export a specific flow
2. Analyze the steps, gates, IFs, and overall structure
3. Suggest improvements — better gates, missing IFs, step content improvements, \
agent alias optimization, or structural changes

When the user is chatting about a specific flow, the flow details are provided in the context below. \
Review it and suggest concrete improvements.

### How to inspect runs and diagnose failures

Use these CLI commands to investigate:
- `llmflows run list` — list recent runs
- `llmflows run show <run-id>` — show run details (status, steps, cost)
- `llmflows run logs <run-id>` — show full logs for a run
- `llmflows flow show <name>` — show flow definition and steps


"""

CONNECTOR_TOOL_HINTS: dict[str, str] = {
    "browser": (
        "**Browser** — `browser_navigate`, `browser_snapshot`, `browser_click`, "
        "`browser_fill`, `browser_screenshot`. Open web pages, read page content, "
        "click buttons/links, fill forms, and take screenshots. "
        "When asked to open a page, call `browser_navigate` immediately — do NOT "
        "ask for URLs, do NOT say you can't, do NOT use shell `open` commands."
    ),
    "web_search": (
        "**Web Search** — `web_search`, `web_fetch`. Search the web for information "
        "and fetch/read web page content as text."
    ),
    "google_workspace": "**Google Workspace** — Gmail, Calendar, Drive, Docs, Sheets, Slides, and Contacts.",
    "youtube": "**YouTube** — search videos, list playlists, get transcripts, and access private data.",
    "notion": "**Notion** — search, read, and update Notion pages and databases.",
    "github": "**GitHub** — manage repositories, issues, pull requests, and more.",
    "slack_mcp": "**Slack** — read and send messages in Slack channels.",
    "linear": "**Linear** — manage issues and projects in Linear.",
    "postgres": "**PostgreSQL** — query and explore PostgreSQL databases.",
}

_NO_TOOLS_SECTION = """\
No tools are enabled for this chat session. \
Do NOT attempt to use any tool calls (browser, web search, etc.) or shell commands \
like `open` to open URLs. If the user asks for something that requires tools, \
tell them to add tools using the + tool button next to the Agent selector.\
"""


def get_enabled_connector_ids() -> list[str]:
    """Return server_ids of all enabled MCP connectors."""
    from ..db.database import get_session
    from ..db.models import McpConnector

    session = get_session()
    try:
        rows = session.query(McpConnector).filter_by(enabled=True).all()
        return [r.server_id for r in rows]
    finally:
        session.close()


def build_tools_section(connector_ids: list[str]) -> str:
    """Build the tools section of the system prompt for the given connectors."""
    if not connector_ids:
        return _NO_TOOLS_SECTION

    lines = ["You have the following tools available for this session:\n"]
    for cid in connector_ids:
        hint = CONNECTOR_TOOL_HINTS.get(cid)
        if hint:
            lines.append(f"- {hint}")
        else:
            lines.append(f"- **{cid}** — third-party connector (tools registered dynamically).")
    lines.append("")
    lines.append(
        "Use these tools directly when the user asks. Do NOT tell the user to do things "
        "manually when you have the tools to do it. Do NOT use shell commands like `open` "
        "to open URLs — use browser tools instead if available."
    )
    return "\n".join(lines)


def build_system_prompt(connector_ids: list[str] | None = None) -> str:
    """Build the full system prompt with a dynamic tools section.

    connector_ids: the connectors selected for this chat session.
    None means no connectors selected (no tools).
    """
    section = build_tools_section(connector_ids or [])
    return SYSTEM_PROMPT.replace("{tools_section}", section)


def resolve_chat_env() -> dict[str, str]:
    """Build environment with LLM provider API keys for Pi."""
    env = os.environ.copy()
    from ..db.database import get_session
    from ..db.models import AgentConfig
    from ..config import KNOWN_LLM_PROVIDERS

    session = get_session()
    try:
        for cfg in session.query(AgentConfig).filter_by(agent="pi").all():
            env[cfg.key] = cfg.value
        for provider in KNOWN_LLM_PROVIDERS:
            for cfg in session.query(AgentConfig).filter_by(agent=provider).all():
                if cfg.key not in env or not env[cfg.key]:
                    env[cfg.key] = cfg.value
    finally:
        session.close()
    return env


def build_flow_context(flow_name: str, space_id: str) -> str:
    """Build rich flow context for the chat system prompt."""
    from .flow import FlowService
    from ..db.database import get_session as _gs
    from ..db.models import FlowRun

    db = _gs()
    try:
        flow_svc = FlowService(db)
        flow = flow_svc.get_by_name(flow_name, space_id=space_id)
        if not flow:
            return f"\n## Active flow\n\nThe user is asking about flow **{flow_name}** but it was not found.\n"

        parts = [f"\n## Active flow: {flow_name}\n"]
        parts.append("The user is chatting about this specific flow.\n")

        snapshot = flow_svc.build_flow_snapshot(flow_name, space_id=space_id)
        if snapshot:
            parts.append("### Flow definition\n```json\n" + json.dumps(snapshot, indent=2) + "\n```\n")

        warnings = flow_svc.validate_flow(flow.id, space_id=space_id)
        if warnings:
            parts.append("### Configuration warnings\n")
            for w in warnings:
                prefix = f"**{w['step_name']}**: " if w.get("step_name") else ""
                parts.append(f"- {prefix}{w['message']}")
            parts.append("")

        runs = (
            db.query(FlowRun)
            .filter_by(flow_id=flow.id)
            .order_by(FlowRun.created_at.desc())
            .limit(3)
            .all()
        )
        if runs:
            parts.append("### Recent runs\n")
            for run in runs:
                status = "completed" if run.completed_at else ("running" if run.started_at else "queued")
                if run.outcome:
                    status = run.outcome
                line = f"- **{run.id}** — {status}"
                if run.duration_seconds is not None:
                    line += f", {run.duration_seconds:.0f}s"
                if run.cost_usd:
                    line += f", ${run.cost_usd:.4f}"
                if run.summary:
                    summary_preview = run.summary[:300].replace("\n", " ")
                    line += f"\n  > {summary_preview}"
                parts.append(line)
            parts.append("")
            parts.append("For deeper investigation, use `llmflows run logs <run-id>` or `llmflows run show <run-id>`.\n")

        return "\n".join(parts)
    except Exception:
        return f"\n## Active flow: {flow_name}\n\nCould not load flow details.\n"
    finally:
        db.close()


def get_skill_paths() -> list[Path]:
    """Return paths to bundled chat skills."""
    paths: list[Path] = []
    for skill_name in CHAT_SKILLS:
        candidate = _BUNDLED_SKILLS_DIR / skill_name
        if candidate.is_dir():
            paths.append(candidate)
    return paths


def resolve_chat_model(tier: str = "max") -> str:
    """Resolve the Pi alias to a model string."""
    from ..config import resolve_alias, KNOWN_LLM_PROVIDERS
    from ..db.database import get_session as _get_db_session

    try:
        db = _get_db_session()
        chat_agent, chat_model = resolve_alias(db, "pi", tier)
        if chat_agent in KNOWN_LLM_PROVIDERS:
            if "/" not in chat_model:
                chat_model = f"{chat_agent}/{chat_model}"
        db.close()
        return chat_model
    except (ValueError, Exception):
        return ""


def build_space_context(space_id: str | None, session_factory=None) -> tuple[Any, str]:
    """Resolve space and build space context string.

    Returns (space_object_or_None, context_string).
    """
    from .space import SpaceService

    space = None
    space_context = "\nNo space is currently selected. You can answer questions but cannot create flows — ask the user to select a space first.\n"

    if space_id:
        if session_factory:
            session = session_factory()
        else:
            from ..db.database import get_session
            session = get_session()
        try:
            space = SpaceService(session).get(space_id)
        finally:
            session.close()

    if space:
        flows_dir = Path(space.path) / "flows"
        space_context = f"\n## Current space\n- Name: {space.name}\n- Path: {space.path}\n- Flows directory: {flows_dir}\n\nWrite flow JSON files to the flows/ directory and import them with `llmflows flow import`.\n"

    return space, space_context


def build_pi_command(
    message: str,
    session_file: Path,
    system_file: Path,
    model: str = "",
    skill_paths: list[Path] | None = None,
    mode: str = "json",
    connector_ids: list[str] | None = None,
) -> list[str]:
    """Build the pi CLI command.

    connector_ids: if provided, only include these connectors (must also be
    enabled in DB).  None means include all enabled connectors.
    """
    cmd = [
        "pi", "-p", message,
        "--mode", mode,
        "--session", str(session_file),
        "--append-system-prompt", str(system_file),
    ]
    if model:
        cmd.extend(["--model", model])
    for sp in (skill_paths or []):
        cmd.extend(["--skill", str(sp)])

    from .executors.pi import MCP_BRIDGE_TOOL
    from .mcp import get_mcp_servers

    servers = get_mcp_servers(connector_ids)
    if servers:
        import json as _json
        import os
        os.environ["MCP_SERVERS"] = _json.dumps(servers)
        cmd.extend(["--extension", str(MCP_BRIDGE_TOOL)])

    return cmd


def build_pi_env() -> dict[str, str]:
    """Build the full environment for Pi, including MCP server URLs."""
    env = resolve_chat_env()
    env["NODE_PATH"] = str(_NODE_MODULES)
    if env.get("GEMINI_API_KEY"):
        env.pop("GOOGLE_API_KEY", None)

    ollama_host = env.get("OLLAMA_HOST")
    if ollama_host:
        from ..config import ensure_pi_ollama_provider
        ensure_pi_ollama_provider(ollama_host)

    return env


class ChatService:
    """Shared chat service for channels (buffered responses)."""

    def __init__(self, session_factory=None):
        self.session_factory = session_factory
        self.sessions_dir = CHAT_SESSIONS_DIR
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def send_message(
        self,
        session_id: str,
        message: str,
        space_id: str | None = None,
        flow_name: str | None = None,
        tier: str = "max",
        channel_name: str = "channel",
    ) -> str:
        """Send a message to Pi and return the full response text (blocking)."""
        if not shutil.which("pi"):
            return "Error: Pi binary not found in PATH."

        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        session_file = session_dir / "session"
        system_file = session_dir / "system.md"

        space, space_context = build_space_context(space_id, self.session_factory)

        flow_context = ""
        if flow_name and space:
            flow_context = build_flow_context(flow_name, space.id)

        channel_context = ""
        if channel_name:
            channel_context = f"\n## Channel\n\nThe user is chatting through {channel_name}. Keep responses concise — messaging platforms have length limits.\n"
        system_prompt = build_system_prompt(connector_ids=get_enabled_connector_ids())
        system_file.write_text(system_prompt + channel_context + space_context + flow_context)

        model = resolve_chat_model(tier)
        skill_paths = get_skill_paths()

        cmd = build_pi_command(
            message=message,
            session_file=session_file,
            system_file=system_file,
            model=model,
            skill_paths=skill_paths,
            mode="json",
            connector_ids=[],
        )

        env = build_pi_env()
        cwd = space.path if space else str(Path.home())

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                env=env,
                cwd=cwd,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            return "Response timed out after 5 minutes."
        except Exception as e:
            logger.warning("Pi subprocess failed: %s", e)
            return "Error running the chat agent."

        return self._extract_response(proc.stdout.decode(errors="replace"))

    def end_session(self, session_id: str) -> None:
        """Delete a chat session."""
        session_dir = self.sessions_dir / session_id
        if session_dir.is_dir():
            shutil.rmtree(session_dir, ignore_errors=True)

    def new_session_id(self) -> str:
        return uuid.uuid4().hex[:10]

    @staticmethod
    def _extract_response(output: str) -> str:
        """Extract assistant text from Pi's JSON-mode output."""
        parts: list[str] = []
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            ev_type = ev.get("type")
            if ev_type == "message_update":
                ame = ev.get("assistantMessageEvent", {})
                if ame.get("type") == "text_delta":
                    delta = ame.get("delta", "")
                    if delta:
                        parts.append(delta)
        return "".join(parts) or "No response from the assistant."
