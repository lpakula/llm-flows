"""Connector tool hints for chat and flow step prompts."""

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
    "google_workspace": (
        "**Google Workspace** — Gmail, Calendar, Drive, Docs, Sheets, Slides, and Contacts. "
        "Gmail extras (always available with this connector): `archive_email` (remove INBOX), "
        "`remove_label` (e.g. INBOX, UNREAD, STARRED)."
    ),
    "youtube": (
        "**YouTube** — search videos, list playlists, get transcripts, and access private data."
    ),
    "google_tasks": (
        "**Google Tasks** — `list-task-lists`, `list-tasks`, `create-task`, `update-task`, "
        "`complete-task`, `delete-task`. Manage Google Tasks lists and items."
    ),
    "notion": (
        "**Notion** — search, read, and update Notion pages and databases. "
        "Use a personal access token (PAT), not an internal connection."
    ),
    "github": (
        "**GitHub** — MCP tools include `list_commits`, `get_commit`, `search_repositories`, "
        "`get_file_contents`, `list_issues`, and more. To fetch recent commits, call "
        "`list_commits` with `owner`, `repo`, and `sha` (branch name, e.g. `main` or `develop`). "
        "Do **not** use `git clone`, `git pull`, `curl`, or Python scripts to call the GitHub API."
    ),
    "slack_mcp": "**Slack** — read and send messages in Slack channels.",
    "linear": "**Linear** — manage issues and projects in Linear.",
    "postgres": "**PostgreSQL** — query and explore PostgreSQL databases.",
}

_FLOW_CONNECTOR_RULES = (
    "Use these MCP tools directly when the step instructions require external data or actions. "
    "Do **not** substitute bash, curl, Python scripts, `git clone`, or raw HTTP/API calls when "
    "an MCP tool can do the job. Do **not** embed tokens or credentials in shell commands."
)


def build_tools_section(connector_ids: list[str], *, for_flow_step: bool = False) -> str:
    """Build a markdown section describing available connector tools."""
    if not connector_ids:
        return ""

    lines = ["You have the following MCP tools available for this session:\n"]
    for cid in connector_ids:
        hint = CONNECTOR_TOOL_HINTS.get(cid)
        if hint:
            lines.append(f"- {hint}")
        else:
            lines.append(f"- **{cid}** — third-party connector (tools registered dynamically).")
    lines.append("")
    if for_flow_step:
        lines.append(_FLOW_CONNECTOR_RULES)
    else:
        lines.append(
            "Use these tools directly when the user asks. Do NOT tell the user to do things "
            "manually when you have the tools to do it. Do NOT use shell commands like `open` "
            "to open URLs — use browser tools instead if available."
        )
        if "browser" in connector_ids or "browser-host" in connector_ids:
            lines.append(
                "Browser tools work without a registered space — use them for connector setup, "
                "OAuth portals, and external websites even when no space is selected."
            )
    return "\n".join(lines)
