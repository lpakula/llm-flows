"""Host OAuth support for Google connectors in Docker runner containers.

Google Workspace stores credentials/tokens under ``~/.google-workspace-mcp/``.
YouTube stores tokens at ``~/.ytmcp_tokens.json`` and uses a localhost OAuth
callback on port 31415. Google Tasks stores tokens under
``~/.config/google-tasks-mcp/`` and uses localhost ports 3500–3505.
Runner containers must mount these from the orchestrator host and publish
OAuth callback ports when interactive sign-in is still needed.
"""

import json
import logging
import os
import socket
from pathlib import Path
from typing import Optional

logger = logging.getLogger("llmflows.google_host")

GOOGLE_CONNECTOR_IDS = frozenset({"google_workspace", "youtube", "google_tasks"})
YOUTUBE_OAUTH_PORT = 31415
GOOGLE_TASKS_OAUTH_PORT_START = 3500
GOOGLE_TASKS_OAUTH_PORT_END = 3505
GWS_CONFIG_DIR = ".google-workspace-mcp"
YOUTUBE_TOKEN_FILE = ".ytmcp_tokens.json"
GOOGLE_TASKS_CONFIG_DIR = ".config/google-tasks-mcp"
GOOGLE_TASKS_TOKEN_FILE = "tokens.json"


def host_user_home() -> Path:
    """Real user home on the orchestrator host (not LLMFLOWS_HOME)."""
    return Path(os.environ.get("LLMFLOWS_USER_HOME", str(Path.home())))


def default_google_oauth_credentials_path() -> Path:
    """Default Desktop OAuth client JSON shared with Google Workspace setup."""
    return host_user_home() / GWS_CONFIG_DIR / "credentials.json"


def google_tasks_token_path() -> Path:
    return host_user_home() / GOOGLE_TASKS_CONFIG_DIR / GOOGLE_TASKS_TOKEN_FILE


def flow_google_connectors(flow_snapshot: Optional[str]) -> set[str]:
    """Return Google connector IDs referenced by a flow snapshot."""
    if not flow_snapshot:
        return set()
    try:
        snap = json.loads(flow_snapshot)
    except (json.JSONDecodeError, TypeError):
        return set()

    needed: set[str] = set()
    for step in snap.get("steps", []):
        connectors = step.get("connectors", step.get("mcp", step.get("tools", []))) or []
        for cid in connectors:
            if cid in GOOGLE_CONNECTOR_IDS:
                needed.add(cid)
    return needed


def google_oauth_volume_args(needed: set[str]) -> list[str]:
    """Docker volume mounts for Google OAuth files on the orchestrator host."""
    if not needed:
        return []

    user_home = host_user_home()
    args: list[str] = []

    if "google_workspace" in needed or "google_tasks" in needed:
        gws_dir = user_home / GWS_CONFIG_DIR
        gws_dir.mkdir(parents=True, exist_ok=True)
        if "google_workspace" in needed:
            args.extend(["-v", f"{gws_dir}:/root/{GWS_CONFIG_DIR}"])
            # Shadow the OAuth client secret read-only so a runner can refresh
            # token.json but never tamper with the credentials themselves.
            creds = gws_dir / "credentials.json"
            if creds.is_file():
                args.extend(["-v", f"{creds}:/root/{GWS_CONFIG_DIR}/credentials.json:ro"])
            logger.info("Mounting Google Workspace config from %s", gws_dir)
        elif "google_tasks" in needed:
            # Tasks reuses the Workspace Desktop OAuth client JSON.
            creds = gws_dir / "credentials.json"
            if creds.is_file():
                args.extend(["-v", f"{creds}:/root/{GWS_CONFIG_DIR}/credentials.json:ro"])
                logger.info("Mounting Google OAuth credentials for Tasks from %s", creds)

    if "youtube" in needed:
        token_file = user_home / YOUTUBE_TOKEN_FILE
        if not token_file.exists():
            token_file.touch(mode=0o600)
        args.extend(["-v", f"{token_file}:/root/{YOUTUBE_TOKEN_FILE}"])
        logger.info("Mounting YouTube token file from %s", token_file)

    if "google_tasks" in needed:
        tasks_dir = user_home / GOOGLE_TASKS_CONFIG_DIR
        tasks_dir.mkdir(parents=True, exist_ok=True)
        args.extend(["-v", f"{tasks_dir}:/root/{GOOGLE_TASKS_CONFIG_DIR}"])
        logger.info("Mounting Google Tasks config from %s", tasks_dir)

    return args


def _port_in_use(port: int) -> bool:
    """Check whether a TCP port is already bound on the host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
            return False
        except OSError:
            return True


def youtube_port_args(needed: set[str]) -> list[str]:
    """Publish YouTube OAuth callback port to the orchestrator host.

    Only one container can bind the host port, so publishing it
    unconditionally breaks concurrent runs (``docker run`` fails with "port is
    already allocated" and the container is left in ``Created`` state). The
    port is only needed for the interactive OAuth sign-in flow, so skip it
    when a token already exists or when another container holds the port.
    """
    if "youtube" not in needed:
        return []
    token = host_user_home() / YOUTUBE_TOKEN_FILE
    if token.is_file() and token.stat().st_size > 2:
        return []
    if _port_in_use(YOUTUBE_OAUTH_PORT):
        logger.warning(
            "YouTube OAuth port %d already in use — launching container without "
            "the callback port (interactive sign-in unavailable for this run)",
            YOUTUBE_OAUTH_PORT,
        )
        return []
    return ["-p", f"{YOUTUBE_OAUTH_PORT}:{YOUTUBE_OAUTH_PORT}"]


def google_tasks_port_args(needed: set[str]) -> list[str]:
    """Publish Google Tasks OAuth callback ports (3500–3505) when needed."""
    if "google_tasks" not in needed:
        return []
    token = google_tasks_token_path()
    if token.is_file() and token.stat().st_size > 2:
        return []
    # Skip the whole range if the first port is taken — another run may be
    # mid-auth; avoid docker-run failures on concurrent containers.
    if _port_in_use(GOOGLE_TASKS_OAUTH_PORT_START):
        logger.warning(
            "Google Tasks OAuth port %d already in use — launching without "
            "callback ports (interactive sign-in unavailable for this run)",
            GOOGLE_TASKS_OAUTH_PORT_START,
        )
        return []
    return [
        "-p",
        f"{GOOGLE_TASKS_OAUTH_PORT_START}-{GOOGLE_TASKS_OAUTH_PORT_END}:"
        f"{GOOGLE_TASKS_OAUTH_PORT_START}-{GOOGLE_TASKS_OAUTH_PORT_END}",
    ]


def google_connector_status(server_id: str) -> list[dict]:
    """Setup status checks for Google connectors (UI health hints)."""
    user_home = host_user_home()
    if server_id == "google_workspace":
        creds = user_home / GWS_CONFIG_DIR / "credentials.json"
        if creds.is_file():
            token = user_home / GWS_CONFIG_DIR / "token.json"
            if token.is_file():
                return [{"text": "credentials.json and token.json found", "status": "ok"}]
            return [
                {"text": "credentials.json found", "status": "ok"},
                {"text": "token.json missing — OAuth required on first use", "status": "warn"},
            ]
        return [{"text": f"credentials.json not found at {creds}", "status": "error"}]

    if server_id == "youtube":
        token = user_home / YOUTUBE_TOKEN_FILE
        if token.is_file() and token.stat().st_size > 2:
            return [{"text": "OAuth token found", "status": "ok"}]
        return [{"text": "OAuth token missing — sign in on first private-data use", "status": "warn"}]

    if server_id == "google_tasks":
        creds = default_google_oauth_credentials_path()
        status: list[dict] = []
        if creds.is_file():
            status.append({"text": f"OAuth credentials found at {creds}", "status": "ok"})
        else:
            status.append({
                "text": f"OAuth credentials not found at {creds} — set up Google Workspace or point GOOGLE_OAUTH_CREDENTIALS at your Desktop client JSON",
                "status": "error",
            })
        token = google_tasks_token_path()
        if token.is_file() and token.stat().st_size > 2:
            status.append({"text": "Tasks OAuth token found", "status": "ok"})
        else:
            status.append({
                "text": "Tasks OAuth token missing — authenticate on first use (or run: npx @scottie-will/google-tasks-mcp auth)",
                "status": "warn",
            })
        return status

    return []
