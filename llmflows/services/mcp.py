"""MCP service -- builds MCP_SERVERS config for agent runs.

With stdio transport, MCP servers are spawned on demand by mcp-bridge.ts
as subprocesses of each agent run.  No long-lived processes to manage.

This module provides a single helper that reads connector configs from DB
and builds the MCP_SERVERS JSON that gets passed to the bridge.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger("llmflows.mcp")

_LLMFLOWS_DIR = Path.home() / ".llmflows"
_NODE_MODULES = _LLMFLOWS_DIR / "node_modules"
_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"

BUILTIN_COMMANDS: dict[str, str] = {
    "web_search": "mcp-server-web-search.ts",
    "browser": "mcp-server-browser.ts",
}


def get_mcp_servers(connector_ids: list[str] | None = None) -> list[dict]:
    """Build MCP_SERVERS entries for enabled connectors.

    If connector_ids is provided, only include those connectors (must also be
    enabled in DB).  None means include all enabled connectors.

    Returns a list of dicts: [{server_id, command, args, env}, ...]
    """
    from ..db.database import get_session
    from ..db.models import McpConnector

    session = get_session()
    try:
        query = session.query(McpConnector).filter_by(enabled=True)
        connectors = query.all()

        if connector_ids is not None:
            filter_set = set(connector_ids)
            connectors = [c for c in connectors if c.server_id in filter_set]

        result = []
        for c in connectors:
            entry = _build_entry(c)
            if entry:
                result.append(entry)
        return result
    finally:
        session.close()


def _build_entry(connector) -> dict | None:
    """Build a single MCP_SERVERS entry from a connector record."""
    server_id = connector.server_id

    env_vars: dict[str, str] = {}
    for k, v in connector.get_env().items():
        val = str(v)
        if val.startswith("~"):
            val = os.path.expanduser(val)
        env_vars[k] = val
    for k, v in connector.get_credentials().items():
        env_vars[k] = str(v)

    env_vars["NODE_PATH"] = str(_NODE_MODULES)

    if server_id == "browser":
        env_vars.setdefault("BROWSER_USER_DATA_DIR", str(_LLMFLOWS_DIR / "browser-profile"))

    if server_id in BUILTIN_COMMANDS:
        script = _TOOLS_DIR / BUILTIN_COMMANDS[server_id]
        tsx_bin = _NODE_MODULES / ".bin" / "tsx"
        return {
            "server_id": server_id,
            "command": str(tsx_bin),
            "args": [str(script)],
            "env": env_vars,
        }

    command_str = connector.command.strip()
    if not command_str:
        logger.warning("Connector '%s' has no command, skipping", server_id)
        return None

    parts = command_str.split()
    command = parts[0]
    args = parts[1:]

    if command == "npx" and "-y" not in args:
        args.insert(0, "-y")

    return {
        "server_id": server_id,
        "command": command,
        "args": args,
        "env": env_vars,
    }
