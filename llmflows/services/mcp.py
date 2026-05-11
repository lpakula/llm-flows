"""MCP service -- builds MCP_SERVERS config for agent runs.

With stdio transport, MCP servers are spawned on demand by mcp-bridge.ts
as subprocesses of each agent run.  No long-lived processes to manage.

This module provides a single helper that reads connector configs from DB
and builds the MCP_SERVERS JSON that gets passed to the bridge.
"""

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

from ..config import SYSTEM_DIR

logger = logging.getLogger("llmflows.mcp")

_LLMFLOWS_DIR = SYSTEM_DIR
_NODE_MODULES = SYSTEM_DIR / "node_modules"
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

    resolved = _find_binary(command)
    if resolved:
        command = resolved

    return {
        "server_id": server_id,
        "command": command,
        "args": args,
        "env": env_vars,
    }


_EXTRA_BIN_PATHS: list[Path] = [
    Path.home() / ".maestro" / "bin",
    Path.home() / ".local" / "bin",
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
]


def _find_binary(name: str) -> str | None:
    """Locate a binary by name, checking PATH and common install locations."""
    found = shutil.which(name)
    if found:
        return found
    for extra_dir in _EXTRA_BIN_PATHS:
        candidate = extra_dir / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def check_connector_health(server_id: str) -> dict:
    """Verify a connector is usable: binary exists and MCP server responds.

    Returns {"ok": bool, "binary_found": bool, "server_responsive": bool,
             "binary_path": str|None, "error": str|None, "tools": list|None}
    """
    from ..db.database import get_session
    from ..db.models import McpConnector

    session = get_session()
    try:
        connector = session.query(McpConnector).filter_by(server_id=server_id).first()
        if not connector:
            return {"ok": False, "binary_found": False, "server_responsive": False,
                    "binary_path": None, "error": f"Connector '{server_id}' not found", "tools": None}
    finally:
        session.close()

    if server_id in BUILTIN_COMMANDS:
        script = _TOOLS_DIR / BUILTIN_COMMANDS[server_id]
        tsx_bin = _NODE_MODULES / ".bin" / "tsx"
        binary_path = str(tsx_bin) if tsx_bin.exists() else None
        return {"ok": tsx_bin.exists() and script.exists(), "binary_found": tsx_bin.exists(),
                "server_responsive": script.exists(), "binary_path": binary_path,
                "error": None if (tsx_bin.exists() and script.exists()) else "Built-in server files missing",
                "tools": None}

    command_str = connector.command.strip()
    if not command_str:
        return {"ok": False, "binary_found": False, "server_responsive": False,
                "binary_path": None, "error": "No command configured", "tools": None}

    parts = command_str.split()
    binary = parts[0]
    args = parts[1:]

    binary_path = _find_binary(binary)
    if not binary_path:
        return {"ok": False, "binary_found": False, "server_responsive": False,
                "binary_path": None, "error": f"Binary '{binary}' not found in PATH", "tools": None}

    return _mcp_handshake(binary_path, args, connector)


def _mcp_handshake(binary_path: str, args: list[str], connector) -> dict:
    """Spawn the MCP server and perform an initialize + tools/list handshake.

    MCP stdio servers are long-running — they don't exit after processing.
    We write requests, read responses with a timeout, then terminate.
    """
    import threading
    import time

    env = os.environ.copy()
    extra = os.pathsep.join(str(p) for p in _EXTRA_BIN_PATHS if p.is_dir())
    if extra:
        env["PATH"] = extra + os.pathsep + env.get("PATH", "")
    for k, v in connector.get_env().items():
        val = str(v)
        if val.startswith("~"):
            val = os.path.expanduser(val)
        env[k] = val
    for k, v in connector.get_credentials().items():
        env[k] = str(v)

    init_request = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05",
                   "capabilities": {},
                   "clientInfo": {"name": "llmflows-healthcheck", "version": "1.0.0"}}
    }) + "\n"

    tools_request = json.dumps({
        "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
    }) + "\n"

    try:
        proc = subprocess.Popen(
            [binary_path] + args,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, text=True,
        )
    except Exception as e:
        return {"ok": False, "binary_found": True, "server_responsive": False,
                "binary_path": binary_path, "error": str(e), "tools": None}

    # Give server a moment to start (or crash)
    time.sleep(1)
    exit_code = proc.poll()
    if exit_code is not None:
        stderr = (proc.stderr.read() if proc.stderr else "").strip()
        first_useful_line = ""
        for line in stderr.splitlines():
            line = line.strip()
            if line and not line.startswith("/") and "integer expression" not in line:
                first_useful_line = line
                break
        error = first_useful_line or stderr[:200] or f"Server exited with code {exit_code}"
        return {"ok": False, "binary_found": True, "server_responsive": False,
                "binary_path": binary_path, "error": error, "tools": None}

    # Server is running — send handshake
    stdout_lines: list[str] = []

    def _read_stdout():
        assert proc.stdout is not None
        for line in proc.stdout:
            stdout_lines.append(line)

    reader = threading.Thread(target=_read_stdout, daemon=True)
    reader.start()

    try:
        assert proc.stdin is not None
        proc.stdin.write(init_request)
        proc.stdin.write(tools_request)
        proc.stdin.flush()

        reader.join(timeout=10)
    except (BrokenPipeError, OSError):
        pass
    finally:
        proc.kill()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass

    tools = []
    got_response = False
    for line in stdout_lines:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            got_response = True
            if msg.get("id") == 2 and "result" in msg:
                tools = [t.get("name", "") for t in msg["result"].get("tools", [])]
        except json.JSONDecodeError:
            continue

    if got_response:
        return {"ok": True, "binary_found": True, "server_responsive": True,
                "binary_path": binary_path, "error": None, "tools": tools or None}

    return {"ok": False, "binary_found": True, "server_responsive": False,
            "binary_path": binary_path,
            "error": "Server started but did not respond to MCP handshake",
            "tools": None}
