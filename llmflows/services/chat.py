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

from ..config import SYSTEM_DIR
from ..utils.node_modules import resolve_node_modules

logger = logging.getLogger("llmflows.chat")

CHAT_SESSIONS_DIR = SYSTEM_DIR / "chat-sessions"
_BUNDLED_SKILLS_DIR = Path(__file__).resolve().parent.parent / "defaults" / "skills"
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
- **Connectors** — external services (Gmail, Notion, browser, etc.) are declared per step via `connectors`; see Building flows below. \
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
- Help users configure connectors (OAuth, API keys) — see connector setup below
- Follow best practices from your loaded skills when creating flows

## Connector setup

Configuring connectors (Notion, GitHub, Google, etc.) does **not** require a registered space. \
When browser or other connector tools are enabled for this chat session, use them immediately — \
follow the llmflows-connectors skill. Do **not** tell the user to select a space, start the daemon, \
or register a project before opening a browser or walking through an external setup portal.

## Building flows

When a user wants to build a flow, start by asking one simple question: \
**"What do you want to automate?"**

Then ask follow-up questions to understand the goal better — the more you know, the better the flow. \
Ask about things like: where the data comes from, what the final output should look like, \
whether it should pause for human review, how often it will run, etc.

Keep questions short and conversational. Ask one or two at a time, not a big list.

When you have enough context, present the planned flow to the user before creating it:
1. Show a short summary of each step — name, what it does, which **connectors** it needs, and why
2. Ask the user to confirm or adjust ("Does this look good? Want to change anything?")
3. Only after the user confirms, write the flow and import it

### Step connectors (mandatory)

Every step that uses an external service **must** declare the connector in its `connectors` array. \
Connectors are **per step** — enabling a connector in Settings does **not** attach it to a run. \
Without the right `connectors` on a step, the run agent only gets bash/read/write and cannot call Gmail, Notion, etc.

Before writing flow JSON, map each step to connectors:
- Gmail, Calendar, Drive, Docs, Sheets, Slides, Contacts → `google_workspace`
- YouTube (search, playlists, transcripts, private data) → `youtube`
- Notion pages/databases → `notion`
- GitHub repos, issues, PRs → `github`
- Slack messages → `slack_mcp`
- Linear issues → `linear`
- PostgreSQL queries → `postgres`
- Web search / fetch pages → `web_search`
- Browser automation → `browser`

Steps that only read/write local files or use prior step artifacts need no connectors. \
`hitl` steps usually need no connectors unless they must keep a browser session alive.

After writing the JSON, **verify** every step whose content uses a service has the matching connector declared — \
this is a common mistake that makes flows fail silently (the agent improvises with shell instead of MCP tools).

**IMPORTANT: ALWAYS wait for explicit user confirmation before writing files or running import commands.** \
This applies to new flows AND changes to existing flows. Never implement changes without the user saying \
"yes", "go ahead", "do it", "looks good", or similar explicit approval. \
If the user describes a change, first explain what you'll do, then ask for confirmation.

NEVER ask about implementation details like steps, tools, gates, agent aliases, or step types. \
You are the expert — figure those out yourself. The user describes the goal, you design the automation.

**NEVER add a gate like `test -f {{step.dir}}/_result.md`** — the daemon already enforces that every step \
produces artifacts. Adding this check is redundant and noisy.

**`inbox.md` belongs in `{{run.dir}}/inbox.md`** — NOT in `{{step.dir}}`. The daemon looks for it at the \
run artifacts root. If you want a gate to ensure it was written, use `test -f {{run.dir}}/inbox.md`.

**Gate paths** — gates run with cwd = space project root. Use `{{step.dir}}/file`, `{{run.dir}}/file`, etc. \
Never hardcode host paths. Relative paths like `test -f package.json` only work for files at the space root.

### How to create and update flows

1. Write the flow JSON file to the `flows/` directory in the space root (create the directory if needed)
2. The file must follow the llmflows flow JSON format (see your loaded skills for the schema)
3. Show the user what you plan to change and ask for confirmation before writing or importing
4. When the user confirms, run: `llmflows flow import flows/<flow-name>.json`

When running inside the Docker chat container, your cwd is `/workspace` (the space root). \
Write files to `flows/` relative to cwd and import with the same relative path. \
The space is already registered — do **not** run `llmflows register` on `/workspace`.

To iterate on a flow, edit the JSON file in `flows/` and re-import. \
The import command upserts by name — it will update an existing flow if one with the same name exists.

When the user is chatting from the flow page, they may prefer editing steps in the UI directly. \
For JSON import, bump the `"version"` field when re-importing an existing flow (import rejects same/lower versions). \
UI edits bump the flow version automatically.

### How to review and improve existing flows

When the user is chatting about a specific flow, the flow details are provided in the context below. \
Review it and suggest concrete improvements.

To review a flow:
1. Run `llmflows flow export` to get all flows, or export a specific flow
2. Analyze the steps, gates, IFs, and overall structure
3. Suggest improvements — better gates, missing IFs, step content improvements, \
agent alias optimization, or structural changes
4. **Always present proposed changes and wait for user confirmation before implementing them**

### Security audit

Flows and skills go through a security audit (pattern scan + LLM analysis). \
The audit status is shown in the flow context below when available.

If the user asks about security findings:
- Explain what was flagged and why it could be dangerous
- Suggest concrete fixes to make the flow pass the audit
- When proposing flow changes, avoid patterns that trigger audit failures: \
destructive commands without safeguards, credential exfiltration, obfuscated code, \
or unauthorized network access

### How to inspect runs and diagnose failures

Use these CLI commands to investigate:
- `llmflows run list` — list recent runs
- `llmflows run show <run-id>` — show run details (status, steps, cost)
- `llmflows run logs <run-id>` — show full logs for a run
- `llmflows flow show <name>` — show flow definition and steps


"""

from .connector_hints import build_tools_section as _build_connector_tools_section

_NO_TOOLS_SECTION = """\
You have your built-in tools available: bash, read, write, edit. \
Use bash to run CLI commands like `llmflows flow list`, `llmflows run list`, etc. \
No external connectors (browser, web search) are enabled for this session — \
if the user needs those, tell them to add tools using the + tool button next to the Agent selector.\
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
    return _build_connector_tools_section(connector_ids, for_flow_step=False)


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
    from .audit import FlowAuditService
    from .flow import FlowService
    from ..db.database import get_session as _gs
    from ..db.models import FlowRun, StepRun, Space as _SpaceModel
    from ..utils.paths import normalize_gate_failures_for_display

    def _format_gate_failures(failures: list[dict], space_host_path: str | None) -> list[str]:
        lines: list[str] = []
        for failure in normalize_gate_failures_for_display(
            failures, space_host_path=space_host_path,
        ):
            lines.append(f"- **{failure.get('message', 'Gate failed')}**")
            if failure.get("command"):
                lines.append(f"  - command: `{failure['command']}`")
            stderr = failure.get("stderr") or failure.get("output") or ""
            if stderr:
                lines.append(f"  - stderr: `{stderr[:500]}`")
        return lines

    def _run_failure_lines(run: FlowRun, space_host_path: str | None, db) -> list[str]:
        if run.outcome not in ("error", "interrupted", "cancelled"):
            return []

        lines = [f"#### Run `{run.id}` — {run.outcome}"]
        step_runs = (
            db.query(StepRun)
            .filter_by(flow_run_id=run.id)
            .order_by(StepRun.step_position.desc(), StepRun.started_at.desc())
            .all()
        )

        failed_step = None
        failures: list[dict] = []
        for sr in step_runs:
            if sr.outcome == "gate_failed" or sr.gate_failures:
                failed_step = sr
                if sr.gate_failures:
                    try:
                        parsed = json.loads(sr.gate_failures)
                        if isinstance(parsed, list):
                            failures = parsed
                    except (json.JSONDecodeError, TypeError):
                        pass
                break

        if failed_step and failures:
            lines.append(
                f"Failed at step **{failed_step.step_name}** "
                f"(attempt {failed_step.attempt}):"
            )
            lines.extend(_format_gate_failures(failures, space_host_path))
        elif failed_step:
            lines.append(f"Failed at step **{failed_step.step_name}** (gate_failed).")
        elif run.summary:
            preview = run.summary[:800].strip()
            lines.append(f"Summary: {preview}")

        return lines

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

        _space = db.query(_SpaceModel).filter_by(id=space_id).first()
        if _space:
            audit = FlowAuditService.get_audit(_space.path, flow_name)
            if audit and audit.status in ("unsafe", "error"):
                parts.append(f"### Security audit — {audit.status.upper()}\n")
                if audit.summary:
                    parts.append(f"{audit.summary}\n")
                if audit.findings:
                    parts.append("Findings:")
                    for f in audit.findings:
                        parts.append(f"- {f}")
                parts.append("")
            elif audit and audit.status == "safe":
                parts.append("### Security audit\n\nPassed — no issues found.\n")
            else:
                parts.append("### Security audit\n\nNo audit has been run yet.\n")

        runs = (
            db.query(FlowRun)
            .filter_by(flow_id=flow.id)
            .order_by(FlowRun.created_at.desc())
            .limit(3)
            .all()
        )
        if runs:
            parts.append("### Recent runs\n")
            space_host = _space.path if _space else None
            failure_blocks: list[str] = []
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

                diag = _run_failure_lines(run, space_host, db)
                if diag:
                    failure_blocks.append("\n".join(diag))

            parts.append("")
            if failure_blocks:
                parts.append("### Failure details (for diagnosis)\n")
                parts.append(
                    "Use these gate failures and summaries when the user asks why a run failed "
                    "or how to fix the flow.\n"
                )
                parts.extend(failure_blocks)
                parts.append("")
            parts.append(
                "For deeper investigation, use `llmflows run logs <run-id>` "
                "or `llmflows run show <run-id>`.\n"
            )

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
    space_context = (
        "\n## Current space\n\n"
        "No space is selected. You can still answer questions, use browser/web search tools, "
        "and help configure connectors — a space is **not** required for those tasks.\n\n"
        "A space is only required to create or import flows. If the user wants to build a flow, "
        "ask them to select or register a space first.\n"
    )

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
        space_context = (
            f"\n## Current space\n"
            f"- Name: {space.name}\n"
            f"- Path: {space.path}\n"
            f"- Working directory (Docker chat): `/workspace` (same root as the path above)\n"
            f"- Flows directory: `flows/` (relative to cwd)\n\n"
            "Write flow JSON to `flows/<name>.json` and import with "
            "`llmflows flow import flows/<name>.json`. "
            "Do not run `llmflows register` — this space is already registered.\n"
        )

    return space, space_context


def build_pi_mcp_env(
    connector_ids: list[str] | None = None,
    *,
    runner: bool = False,
    artifacts_dir: Path | str | None = None,
) -> dict[str, str]:
    """Return MCP env vars for Pi when connectors are selected.

    connector_ids: if provided, only include those connectors (must also be
    enabled in DB).  None means include all enabled connectors.

    runner: set True when Pi runs inside a Docker runner/chat container so
    headed browser config uses host Chrome via CDP.

    artifacts_dir: directory for browser screenshots (optional).
    """
    from .mcp import get_mcp_servers

    servers = get_mcp_servers(connector_ids, runner=runner)
    if not servers:
        return {}
    env: dict[str, str] = {"MCP_SERVERS": json.dumps(servers)}
    ids = connector_ids or []
    if artifacts_dir and ("browser" in ids or "browser-host" in ids):
        env["BROWSER_ARTIFACTS_DIR"] = str(artifacts_dir)
    return env


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

    Callers must merge ``build_pi_mcp_env(connector_ids)`` into the process
    environment — chat runs Pi inside Docker and does not inherit host env.
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

    mcp_env = build_pi_mcp_env(connector_ids)
    if mcp_env:
        from .executors.pi import MCP_BRIDGE_TOOL

        ext_path = str(MCP_BRIDGE_TOOL)
        from ..utils.paths import CONTAINER_HOME, host_path_to_container_path
        if str(session_file).startswith(CONTAINER_HOME):
            ext_path = host_path_to_container_path(ext_path)
        cmd.extend(["--extension", ext_path])

    return cmd


def build_pi_env() -> dict[str, str]:
    """Build the full environment for Pi, including MCP server URLs."""
    env = resolve_chat_env()
    env["NODE_PATH"] = str(resolve_node_modules())
    if env.get("GEMINI_API_KEY"):
        env.pop("GOOGLE_API_KEY", None)

    ollama_host = env.get("OLLAMA_HOST")
    if ollama_host:
        from ..config import ensure_pi_ollama_provider
        ensure_pi_ollama_provider(ollama_host)

    return env


def build_chat_container_env(space_path: str | None = None) -> dict[str, str]:
    """Environment variables to pass into the chat Docker container.

    Only forwards API keys and llmflows settings — not the full host
    ``os.environ`` (which can include IDE paths that confuse Pi in Docker).

    ``space_path``: host path of the selected space. When set, runner-style
    ``LLMFLOWS_SPACE_HOST_PATH`` is included so CLI commands like
    ``llmflows flow import`` resolve the space from cwd ``/workspace``.
    """
    from ..db.database import get_session
    from ..db.models import AgentConfig

    env: dict[str, str] = {
        "LLMFLOWS_RUNNER": "1",
        "LLMFLOWS_HOME": "/root/.llmflows",
        "NODE_PATH": "/opt/llmflows/tools/node_modules",
    }
    if space_path:
        env["LLMFLOWS_SPACE_HOST_PATH"] = str(Path(space_path).expanduser().resolve())
    for key in ("LLMFLOWS_DEV_HOME", "OLLAMA_HOST"):
        val = os.environ.get(key)
        if val:
            env[key] = val

    from .container import dev_container_env_vars
    env.update(dev_container_env_vars())

    session = get_session()
    try:
        for cfg in session.query(AgentConfig).all():
            if cfg.value:
                env[cfg.key] = cfg.value
    finally:
        session.close()

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

        connector_ids = get_enabled_connector_ids()
        cmd = build_pi_command(
            message=message,
            session_file=session_file,
            system_file=system_file,
            model=model,
            skill_paths=skill_paths,
            mode="json",
            connector_ids=connector_ids,
        )

        env = build_pi_env()
        env.update(build_pi_mcp_env(connector_ids))
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
