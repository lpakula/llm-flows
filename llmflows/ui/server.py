"""FastAPI server for the llmflows web UI."""

import asyncio
import json
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.websockets import WebSocket as _StarletteWebSocket

from .. import __version__
from ..config import AGENT_REGISTRY, KNOWN_AGENTS, KNOWN_MODELS, load_system_config, save_system_config
from ..db.database import get_session, reset_engine
from ..services.agent import AgentService
from ..services.chat import (
    CHAT_SESSIONS_DIR,
    SYSTEM_PROMPT as _CHAT_SYSTEM_PROMPT,
    build_flow_context as _build_flow_context,
    build_pi_env as _build_pi_env,
    build_space_context as _build_space_context,
    get_skill_paths as _get_skill_paths,
    resolve_chat_model as _resolve_chat_model,
)
from ..services.flow import FlowService
from ..services.space import SpaceService
from ..services.run import RunService
from ..services.skill import SkillService

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="llmflows", version=__version__)


# --- Pydantic models ---

class FlowCreate(BaseModel):
    name: str
    description: str = ""
    copy_from: Optional[str] = None
    requirements: Optional[dict] = None


class FlowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    requirements: Optional[dict] = None
    max_concurrent_runs: Optional[int] = None
    max_spend_usd: Optional[float] = None
    starred: Optional[bool] = None
    schedule_cron: Optional[str] = None
    schedule_timezone: Optional[str] = None
    schedule_enabled: Optional[bool] = None


class StepCreate(BaseModel):
    name: str
    content: str = ""
    position: Optional[int] = None
    gates: Optional[list[dict]] = None
    ifs: Optional[list[dict]] = None
    agent_alias: str = "normal"
    step_type: str = "agent"
    allow_max: bool = False
    max_gate_retries: int = 3
    skills: Optional[list[str]] = None
    connectors: Optional[list[str]] = None


class StepUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    position: Optional[int] = None
    gates: Optional[list[dict]] = None
    ifs: Optional[list[dict]] = None
    agent_alias: Optional[str] = None
    step_type: Optional[str] = None
    allow_max: Optional[bool] = None
    max_gate_retries: Optional[int] = None
    skills: Optional[list[str]] = None
    connectors: Optional[list[str]] = None


class StepRespondBody(BaseModel):
    response: str = ""


class ReorderSteps(BaseModel):
    step_ids: list[str]


class ScheduleBody(BaseModel):
    flow_id: str


class DaemonConfigBody(BaseModel):
    poll_interval_seconds: Optional[int] = None
    run_timeout_minutes: Optional[int] = None
    gate_timeout_seconds: Optional[int] = None
    summarizer_language: Optional[str] = None


class GatewayConfigBody(BaseModel):
    telegram_enabled: Optional[bool] = None
    telegram_bot_token: Optional[str] = None
    telegram_allowed_chat_ids: Optional[list[int]] = None
    slack_enabled: Optional[bool] = None
    slack_bot_token: Optional[str] = None
    slack_app_token: Optional[str] = None
    slack_allowed_channel_ids: Optional[list[str]] = None


class ConnectorCreateBody(BaseModel):
    server_id: str
    name: str = ""
    command: str = ""
    env: Optional[dict] = None
    credentials: Optional[dict] = None


class ConnectorUpdateBody(BaseModel):
    name: Optional[str] = None
    command: Optional[str] = None
    env: Optional[dict] = None
    credentials: Optional[dict] = None
    enabled: Optional[bool] = None
    config: Optional[dict] = None


class SpaceSettingsUpdate(BaseModel):
    max_concurrent_tasks: Optional[int] = None


# --- Helpers ---

def _get_services():
    reset_engine()
    session = get_session()
    return session, SpaceService(session)


ATTACHMENTS_DIR = Path.home() / ".llmflows" / "attachments"

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


# --- Root ---

@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


# --- Daemon endpoints ---

@app.get("/api/daemon/status")
async def daemon_status():
    from ..services.daemon import read_pid_file
    pid = read_pid_file()
    return {"running": pid is not None, "pid": pid}


@app.get("/api/daemon/logs")
async def daemon_logs(lines: int = 200):
    log_path = os.path.expanduser("~/.llmflows/daemon.log")
    if not os.path.exists(log_path):
        return {"lines": []}
    with open(log_path, "r") as f:
        all_lines = f.readlines()
    tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
    return {"lines": [line.rstrip() for line in tail]}


@app.get("/api/config/daemon")
async def get_daemon_config():
    config = load_system_config()
    return config.get("daemon", {})


@app.patch("/api/config/daemon")
async def update_daemon_config(body: DaemonConfigBody):
    config = load_system_config()
    if "daemon" not in config:
        config["daemon"] = {}
    if "ui" not in config:
        config["ui"] = {}
    if body.poll_interval_seconds is not None:
        config["daemon"]["poll_interval_seconds"] = body.poll_interval_seconds
    if body.run_timeout_minutes is not None:
        config["daemon"]["run_timeout_minutes"] = body.run_timeout_minutes
    if body.gate_timeout_seconds is not None:
        config["daemon"]["gate_timeout_seconds"] = body.gate_timeout_seconds
    if body.summarizer_language is not None:
        config["daemon"]["summarizer_language"] = body.summarizer_language
    save_system_config(config)
    return config["daemon"]


@app.get("/api/config/gateway")
async def get_gateway_config():
    config = load_system_config()
    channels = config.get("channels", {})
    tg = channels.get("telegram", {})
    sl = channels.get("slack", {})
    return {
        "telegram_enabled": tg.get("enabled", False),
        "telegram_bot_token": tg.get("bot_token", ""),
        "telegram_allowed_chat_ids": tg.get("allowed_chat_ids", []),
        "slack_enabled": sl.get("enabled", False),
        "slack_bot_token": sl.get("bot_token", ""),
        "slack_app_token": sl.get("app_token", ""),
        "slack_allowed_channel_ids": sl.get("allowed_channel_ids", []),
    }


@app.patch("/api/config/gateway")
async def update_gateway_config(body: GatewayConfigBody):
    config = load_system_config()
    if "channels" not in config:
        config["channels"] = {}
    if "telegram" not in config["channels"]:
        config["channels"]["telegram"] = {}
    if "slack" not in config["channels"]:
        config["channels"]["slack"] = {}

    tg = config["channels"]["telegram"]
    if body.telegram_enabled is not None:
        tg["enabled"] = body.telegram_enabled
    if body.telegram_bot_token is not None:
        tg["bot_token"] = body.telegram_bot_token
    if body.telegram_allowed_chat_ids is not None:
        tg["allowed_chat_ids"] = body.telegram_allowed_chat_ids

    sl = config["channels"]["slack"]
    if body.slack_enabled is not None:
        sl["enabled"] = body.slack_enabled
    if body.slack_bot_token is not None:
        sl["bot_token"] = body.slack_bot_token
    if body.slack_app_token is not None:
        sl["app_token"] = body.slack_app_token
    if body.slack_allowed_channel_ids is not None:
        sl["allowed_channel_ids"] = body.slack_allowed_channel_ids

    save_system_config(config)
    _signal_gateway_restart()
    return {
        "telegram_enabled": tg.get("enabled", False),
        "telegram_bot_token": tg.get("bot_token", ""),
        "telegram_allowed_chat_ids": tg.get("allowed_chat_ids", []),
        "slack_enabled": sl.get("enabled", False),
        "slack_bot_token": sl.get("bot_token", ""),
        "slack_app_token": sl.get("app_token", ""),
        "slack_allowed_channel_ids": sl.get("allowed_channel_ids", []),
    }


def _signal_gateway_restart() -> bool:
    """Send SIGUSR1 to the daemon to restart gateway channels. Returns True on success."""
    from ..services.daemon import read_pid_file
    import signal as sig
    pid = read_pid_file()
    if pid is None:
        return False
    try:
        import os
        os.kill(pid, sig.SIGUSR1)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


@app.post("/api/gateway/restart")
async def restart_gateway():
    """Signal the daemon to restart all gateway channels."""
    if not _signal_gateway_restart():
        raise HTTPException(status_code=400, detail="Daemon is not running or not reachable")
    return {"ok": True, "message": "Gateway restart signal sent"}


CONNECTOR_META: dict[str, dict] = {
    "web_search": {
        "description": "Allow agents to search the web and fetch page content.",
        "config_fields": [
            {
                "key": "WEB_SEARCH_PROVIDER",
                "label": "Search Provider",
                "type": "select",
                "target": "env",
                "options": [
                    {"value": "duckduckgo", "label": "DuckDuckGo", "hint": "No API key required"},
                    {"value": "brave", "label": "Brave Search", "hint": "Requires API key"},
                    {"value": "perplexity", "label": "Perplexity Search", "hint": "Requires API key"},
                    {"value": "serpapi", "label": "SerpAPI (Google)", "hint": "Requires API key"},
                ],
            },
            {
                "key": "BRAVE_API_KEY",
                "label": "Brave API Key",
                "type": "secret",
                "target": "credentials",
                "placeholder": "BSA...",
                "show_when": {"WEB_SEARCH_PROVIDER": "brave"},
            },
            {
                "key": "PERPLEXITY_API_KEY",
                "label": "Perplexity API Key",
                "type": "secret",
                "target": "credentials",
                "placeholder": "pplx-...",
                "show_when": {"WEB_SEARCH_PROVIDER": "perplexity"},
            },
            {
                "key": "SERPAPI_API_KEY",
                "label": "SerpAPI Key",
                "type": "secret",
                "target": "credentials",
                "placeholder": "Your SerpAPI key...",
                "show_when": {"WEB_SEARCH_PROVIDER": "serpapi"},
            },
        ],
    },
    "browser": {
        "description": "Allow agents to control a real browser — navigate pages, click, fill forms, take screenshots. Requires Google Chrome.",
        "config_fields": [
            {
                "key": "BROWSER_HEADLESS",
                "label": "Headless Mode",
                "type": "select",
                "target": "env",
                "options": [
                    {"value": "true", "label": "Headless (no visible window)"},
                    {"value": "false", "label": "Headed (visible browser window)"},
                ],
            },
        ],
    },
}

MCP_CATALOG: list[dict] = [
    {
        "server_id": "gmail",
        "name": "Gmail",
        "command": "npx @anthropic/mcp-gmail",
        "category": "Google Workspace",
        "description": "Read, send, and manage emails via the Gmail API.",
        "required_credentials": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"],
        "config_fields": [
            {"key": "GOOGLE_CLIENT_ID", "label": "Client ID", "type": "text",
             "target": "credentials"},
            {"key": "GOOGLE_CLIENT_SECRET", "label": "Client Secret", "type": "secret",
             "target": "credentials"},
            {"key": "GOOGLE_REFRESH_TOKEN", "label": "Refresh Token", "type": "secret",
             "target": "credentials"},
        ],
        "docs_url": "https://github.com/anthropics/anthropic-quickstarts/tree/main/mcp-gmail",
    },
    {
        "server_id": "gdrive",
        "name": "Google Drive",
        "command": "npx @anthropic/mcp-gdrive",
        "category": "Google Workspace",
        "description": "Search, read, and manage files in Google Drive.",
        "required_credentials": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"],
        "config_fields": [
            {"key": "GOOGLE_CLIENT_ID", "label": "Client ID", "type": "text",
             "target": "credentials"},
            {"key": "GOOGLE_CLIENT_SECRET", "label": "Client Secret", "type": "secret",
             "target": "credentials"},
            {"key": "GOOGLE_REFRESH_TOKEN", "label": "Refresh Token", "type": "secret",
             "target": "credentials"},
        ],
        "docs_url": "https://github.com/anthropics/anthropic-quickstarts/tree/main/mcp-gdrive",
    },
    {
        "server_id": "gcalendar",
        "name": "Google Calendar",
        "command": "npx @anthropic/mcp-gcalendar",
        "category": "Google Workspace",
        "description": "View and manage calendar events.",
        "required_credentials": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"],
        "config_fields": [
            {"key": "GOOGLE_CLIENT_ID", "label": "Client ID", "type": "text",
             "target": "credentials"},
            {"key": "GOOGLE_CLIENT_SECRET", "label": "Client Secret", "type": "secret",
             "target": "credentials"},
            {"key": "GOOGLE_REFRESH_TOKEN", "label": "Refresh Token", "type": "secret",
             "target": "credentials"},
        ],
        "docs_url": "https://github.com/anthropics/anthropic-quickstarts/tree/main/mcp-gcalendar",
    },
    {
        "server_id": "youtube",
        "name": "YouTube",
        "command": "npx @mrsknetwork/ytmcp@latest",
        "category": "Google Workspace",
        "description": "Search videos, list playlists, get transcripts, and access private YouTube data.",
        "required_credentials": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"],
        "config_fields": [
            {"key": "GOOGLE_CLIENT_ID", "label": "Client ID", "type": "text",
             "target": "credentials"},
            {"key": "GOOGLE_CLIENT_SECRET", "label": "Client Secret", "type": "secret",
             "target": "credentials"},
            {"key": "GOOGLE_REFRESH_TOKEN", "label": "Refresh Token", "type": "secret",
             "target": "credentials"},
        ],
        "docs_url": "https://github.com/mrsknetwork/ytmcp",
    },
    {
        "server_id": "notion",
        "name": "Notion",
        "command": "npx @modelcontextprotocol/server-notion",
        "category": "Productivity",
        "description": "Search, read, and update Notion pages and databases.",
        "required_credentials": ["NOTION_API_KEY"],
        "config_fields": [
            {"key": "NOTION_API_KEY", "label": "Notion API Key", "type": "secret", "target": "credentials",
             "placeholder": "ntn_..."},
        ],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/notion",
    },
    {
        "server_id": "github",
        "name": "GitHub",
        "command": "npx @modelcontextprotocol/server-github",
        "category": "Developer",
        "description": "Manage repositories, issues, pull requests, and more.",
        "required_credentials": ["GITHUB_TOKEN"],
        "config_fields": [
            {"key": "GITHUB_TOKEN", "label": "GitHub Personal Access Token", "type": "secret",
             "target": "credentials", "placeholder": "ghp_..."},
        ],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/github",
    },
    {
        "server_id": "slack_mcp",
        "name": "Slack",
        "command": "npx @modelcontextprotocol/server-slack",
        "category": "Productivity",
        "description": "Read and send messages in Slack channels.",
        "required_credentials": ["SLACK_BOT_TOKEN"],
        "config_fields": [
            {"key": "SLACK_BOT_TOKEN", "label": "Slack Bot Token", "type": "secret", "target": "credentials",
             "placeholder": "xoxb-..."},
        ],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/slack",
    },
    {
        "server_id": "linear",
        "name": "Linear",
        "command": "npx @modelcontextprotocol/server-linear",
        "category": "Developer",
        "description": "Manage issues and projects in Linear.",
        "required_credentials": ["LINEAR_API_KEY"],
        "config_fields": [
            {"key": "LINEAR_API_KEY", "label": "Linear API Key", "type": "secret", "target": "credentials"},
        ],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/linear",
    },
    {
        "server_id": "postgres",
        "name": "PostgreSQL",
        "command": "npx @modelcontextprotocol/server-postgres",
        "category": "Database",
        "description": "Query and explore PostgreSQL databases.",
        "required_credentials": ["DATABASE_URL"],
        "config_fields": [
            {"key": "DATABASE_URL", "label": "Database URL", "type": "secret", "target": "credentials",
             "placeholder": "postgresql://user:pass@host:5432/db"},
        ],
        "docs_url": "https://github.com/modelcontextprotocol/servers/tree/main/src/postgres",
    },
]


def _connector_response(connector, meta: dict | None = None) -> dict:
    """Build API response for a connector, enriching with metadata."""
    data = connector.to_dict()
    catalog_entry = next((c for c in MCP_CATALOG if c["server_id"] == connector.server_id), None)
    source = meta or catalog_entry or {}
    data["description"] = source.get("description", "")
    data["config_fields"] = source.get("config_fields", [])
    data["required_credentials"] = source.get("required_credentials", [])
    config = {**data.get("env", {}), **data.get("credentials", {})}
    data["config"] = config
    return data


@app.get("/api/connectors")
async def list_connectors():
    from ..db.models import McpConnector
    session = get_session()
    try:
        connectors = session.query(McpConnector).order_by(
            McpConnector.builtin.desc(), McpConnector.server_id
        ).all()
        return [
            _connector_response(c, CONNECTOR_META.get(c.server_id))
            for c in connectors
        ]
    finally:
        session.close()


@app.get("/api/connectors/catalog")
async def get_connector_catalog():
    from ..db.models import McpConnector
    session = get_session()
    try:
        installed_ids = {
            r.server_id for r in session.query(McpConnector.server_id).all()
        }
        return [
            {**entry, "installed": entry["server_id"] in installed_ids}
            for entry in MCP_CATALOG
        ]
    finally:
        session.close()


@app.get("/api/connectors/{server_id}")
async def get_connector(server_id: str):
    from ..db.models import McpConnector
    session = get_session()
    try:
        connector = session.query(McpConnector).filter_by(server_id=server_id).first()
        if not connector:
            raise HTTPException(status_code=404, detail="Connector not found")
        return _connector_response(connector, CONNECTOR_META.get(server_id))
    finally:
        session.close()


GOOGLE_CONNECTOR_IDS = {"gmail", "gdrive", "gcalendar", "youtube"}
GOOGLE_CREDENTIAL_KEYS = {"GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"}


@app.post("/api/connectors")
async def create_connector(body: ConnectorCreateBody):
    from ..db.models import McpConnector
    session = get_session()
    try:
        existing = session.query(McpConnector).filter_by(server_id=body.server_id).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Connector '{body.server_id}' already exists")
        catalog_entry = next((c for c in MCP_CATALOG if c["server_id"] == body.server_id), None)
        name = body.name or (catalog_entry["name"] if catalog_entry else body.server_id)
        command = body.command or (catalog_entry["command"] if catalog_entry else "")

        creds = dict(body.credentials or {})
        if body.server_id in GOOGLE_CONNECTOR_IDS and not (creds.keys() & GOOGLE_CREDENTIAL_KEYS):
            siblings = session.query(McpConnector).filter(
                McpConnector.server_id.in_(GOOGLE_CONNECTOR_IDS - {body.server_id})
            ).all()
            for sib in siblings:
                sib_creds = sib.get_credentials()
                for k in GOOGLE_CREDENTIAL_KEYS:
                    if k not in creds and sib_creds.get(k):
                        creds[k] = sib_creds[k]
                if all(creds.get(k) for k in GOOGLE_CREDENTIAL_KEYS):
                    break

        connector = McpConnector(
            server_id=body.server_id,
            name=name,
            command=command,
            env=json.dumps(body.env or {}),
            credentials=json.dumps(creds),
            enabled=False,
            builtin=False,
        )
        session.add(connector)
        session.commit()
        session.refresh(connector)
        return _connector_response(connector, CONNECTOR_META.get(body.server_id))
    except HTTPException:
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@app.patch("/api/connectors/{server_id}")
async def update_connector(server_id: str, body: ConnectorUpdateBody):
    from ..db.models import McpConnector
    session = get_session()
    try:
        connector = session.query(McpConnector).filter_by(server_id=server_id).first()
        if not connector:
            raise HTTPException(status_code=404, detail="Connector not found")
        if body.name is not None:
            connector.name = body.name
        if body.command is not None and not connector.builtin:
            connector.command = body.command
        if body.config is not None:
            meta = CONNECTOR_META.get(server_id)
            if not meta:
                catalog_entry = next((c for c in MCP_CATALOG if c["server_id"] == server_id), None)
                if catalog_entry:
                    meta = {"config_fields": catalog_entry.get("config_fields", [])}
            env = connector.get_env()
            creds = connector.get_credentials()
            for field in (meta or {}).get("config_fields", []):
                key = field["key"]
                if key in body.config:
                    val = body.config[key]
                    if field.get("type") == "secret" and val == "••••":
                        continue
                    if field.get("target") == "credentials":
                        creds[key] = val
                    else:
                        env[key] = val
            connector.env = json.dumps(env)
            connector.credentials = json.dumps(creds)
        if body.env is not None:
            connector.env = json.dumps(body.env)
        if body.credentials is not None:
            existing_creds = connector.get_credentials()
            for k, v in body.credentials.items():
                if v != "••••":
                    existing_creds[k] = v
            connector.credentials = json.dumps(existing_creds)
        if body.enabled is not None:
            connector.enabled = body.enabled

        session.commit()
        session.refresh(connector)
        return _connector_response(connector, CONNECTOR_META.get(server_id))
    except HTTPException:
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@app.delete("/api/connectors/{server_id}")
async def delete_connector(server_id: str):
    from ..db.models import McpConnector
    session = get_session()
    try:
        connector = session.query(McpConnector).filter_by(server_id=server_id).first()
        if not connector:
            raise HTTPException(status_code=404, detail="Connector not found")
        if connector.builtin:
            raise HTTPException(status_code=400, detail="Cannot delete built-in connectors")
        session.delete(connector)
        session.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@app.post("/api/daemon/stop")
async def stop_daemon():
    import signal
    from ..services.daemon import read_pid_file, remove_pid_file

    pid = read_pid_file()
    if not pid:
        return {"ok": True, "running": False, "pid": None}

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    remove_pid_file()

    for _ in range(20):
        await asyncio.sleep(0.5)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return {"ok": True, "running": False, "pid": None}

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

    return {"ok": True, "running": False, "pid": None}


@app.post("/api/daemon/start")
async def start_daemon():
    import shutil
    import subprocess
    import sys
    from ..services.daemon import read_pid_file

    if read_pid_file():
        pid = read_pid_file()
        return {"ok": True, "running": True, "pid": pid}

    llmflows_bin = shutil.which("llmflows")
    if llmflows_bin:
        cmd = [llmflows_bin, "daemon", "start"]
    else:
        cmd = [sys.executable, "-m", "llmflows", "daemon", "start"]

    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    for _ in range(10):
        await asyncio.sleep(0.5)
        new_pid = read_pid_file()
        if new_pid:
            return {"ok": True, "running": True, "pid": new_pid}

    return {"ok": False, "running": False, "pid": None, "error": "Daemon did not start in time"}


# --- Space endpoints ---

@app.get("/api/spaces")
async def list_spaces():
    session, space_svc = _get_services()
    try:
        spaces = space_svc.list_all()
        return [s.to_dict() for s in spaces]
    finally:
        session.close()


@app.get("/api/spaces/{space_id}")
async def get_space(space_id: str):
    session, space_svc = _get_services()
    try:
        space = space_svc.get(space_id)
        if not space:
            raise HTTPException(status_code=404, detail="Space not found")
        return space.to_dict()
    finally:
        session.close()


class SpaceRegister(BaseModel):
    path: str
    name: Optional[str] = None


class SpaceUpdate(BaseModel):
    name: Optional[str] = None


@app.post("/api/spaces")
async def register_space(body: SpaceRegister):
    """Register a directory as a new llmflows space."""
    space_path = Path(body.path).expanduser().resolve()
    if not space_path.is_dir():
        raise HTTPException(status_code=400, detail="Path does not exist or is not a directory")

    space_name = body.name or space_path.name

    session = get_session()
    try:
        space_svc = SpaceService(session)
        existing = space_svc.get_by_path(str(space_path))
        if existing:
            return existing.to_dict()

        s = space_svc.register(name=space_name, path=str(space_path))

        dot_dir = space_path / ".llmflows"
        dot_dir.mkdir(parents=True, exist_ok=True)

        flow_svc = FlowService(session)
        flow_svc.sync_from_disk(str(space_path), s.id)

        return s.to_dict()
    finally:
        session.close()


@app.get("/api/browse-dirs")
async def browse_dirs(path: str = "~"):
    """List subdirectories of a given path for the folder picker."""
    target = Path(path).expanduser().resolve()
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")

    dirs: list[dict] = []
    try:
        for entry in sorted(target.iterdir()):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                has_git = (entry / ".git").is_dir()
                has_flows = (entry / "flows").is_dir()
                dirs.append({
                    "name": entry.name,
                    "path": str(entry),
                    "has_git": has_git,
                    "has_flows": has_flows,
                })
    except PermissionError:
        pass

    return {
        "current": str(target),
        "parent": str(target.parent) if target.parent != target else None,
        "dirs": dirs,
    }


@app.patch("/api/spaces/{space_id}")
async def update_space(space_id: str, body: SpaceUpdate):
    session, space_svc = _get_services()
    try:
        space = space_svc.get(space_id)
        if not space:
            raise HTTPException(status_code=404, detail="Space not found")
        updates = {}
        if body.name is not None:
            updates["name"] = body.name
        if updates:
            space = space_svc.update(space_id, **updates)
        return space.to_dict()
    finally:
        session.close()


@app.delete("/api/spaces/{space_id}")
async def delete_space(space_id: str):
    session, space_svc = _get_services()
    try:
        if not space_svc.unregister(space_id):
            raise HTTPException(status_code=404, detail="Space not found")
        return {"ok": True}
    finally:
        session.close()


@app.get("/api/spaces/{space_id}/settings")
async def get_space_settings(space_id: str):
    session, space_svc = _get_services()
    try:
        space = space_svc.get(space_id)
        if not space:
            raise HTTPException(status_code=404, detail="Space not found")
        return {
            "max_concurrent_tasks": space.max_concurrent_tasks if space.max_concurrent_tasks is not None else 1,
        }
    finally:
        session.close()


@app.patch("/api/spaces/{space_id}/settings")
async def update_space_settings(space_id: str, body: SpaceSettingsUpdate):
    session, space_svc = _get_services()
    try:
        space = space_svc.get(space_id)
        if not space:
            raise HTTPException(status_code=404, detail="Space not found")

        updates = {}
        if body.max_concurrent_tasks is not None:
            updates["max_concurrent_tasks"] = max(1, body.max_concurrent_tasks)
        if updates:
            space_svc.update(space_id, **updates)
            session.refresh(space)

        return {
            "max_concurrent_tasks": space.max_concurrent_tasks if space.max_concurrent_tasks is not None else 1,
        }
    finally:
        session.close()


class VariableUpdate(BaseModel):
    value: str
    is_env: bool = False


@app.get("/api/flows/{flow_id}/variables")
async def get_flow_variables(flow_id: str):
    session, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        flow = flow_svc.get(flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow not found")
        return flow.get_variables()
    finally:
        session.close()


@app.put("/api/flows/{flow_id}/variables/{key}")
async def set_flow_variable(flow_id: str, key: str, body: VariableUpdate):
    session, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        flow = flow_svc.get(flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow not found")
        variables = flow.get_variables()
        variables[key] = {"value": body.value, "is_env": body.is_env}
        flow_svc.update(flow_id, variables=json.dumps(variables))
        return variables
    finally:
        session.close()


@app.delete("/api/flows/{flow_id}/variables/{key}")
async def delete_flow_variable(flow_id: str, key: str):
    session, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        flow = flow_svc.get(flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow not found")
        variables = flow.get_variables()
        if key not in variables:
            raise HTTPException(status_code=404, detail=f"Variable '{key}' not found")
        del variables[key]
        flow_svc.update(flow_id, variables=json.dumps(variables))
        return variables
    finally:
        session.close()


# --- Schedule flow run ---

@app.post("/api/spaces/{space_id}/schedule")
async def schedule_flow_run(space_id: str, body: ScheduleBody):
    """Schedule a new FlowRun for a flow."""
    session, space_svc = _get_services()
    try:
        space = space_svc.get(space_id)
        if not space:
            raise HTTPException(status_code=404, detail="Space not found")

        run_svc = RunService(session)
        flow_svc = FlowService(session)

        flow = flow_svc.get(body.flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow not found")

        errors = flow_svc.validate_flow(flow.id, space_id=space_id)
        blockers = [w for w in errors if w["warning_type"] in ("missing_alias", "missing_variable")]
        if blockers:
            messages = "; ".join(w["message"] for w in blockers)
            raise HTTPException(status_code=400, detail=messages)

        run = run_svc.enqueue(space_id, body.flow_id)
        return run.to_dict()
    finally:
        session.close()


# --- FlowRun endpoints ---

@app.get("/api/spaces/{space_id}/runs")
async def list_space_runs(space_id: str):
    """All flow runs for a space (for the Board page)."""
    session, space_svc = _get_services()
    try:
        space = space_svc.get(space_id)
        if not space:
            raise HTTPException(status_code=404, detail="Space not found")
        run_svc = RunService(session)
        runs = run_svc.list_by_space(space_id)
        result = []
        for r in runs:
            d = r.to_dict()
            run_att_dir = ATTACHMENTS_DIR / r.id
            if run_att_dir.is_dir():
                d["attachments"] = sorted(
                    [{"name": f.name, "url": f"/api/attachments/{r.id}/{f.name}"}
                     for f in run_att_dir.iterdir() if f.is_file()],
                    key=lambda x: x["name"],
                )
            else:
                d["attachments"] = []
            result.append(d)
        return result
    finally:
        session.close()


@app.get("/api/flows/{flow_id}/runs")
async def list_flow_runs(flow_id: str):
    """All runs for a specific flow."""
    session, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        flow = flow_svc.get(flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow not found")
        run_svc = RunService(session)
        from ..db.models import FlowRun
        runs = (
            session.query(FlowRun)
            .filter_by(flow_id=flow_id)
            .order_by(FlowRun.created_at.desc())
            .all()
        )
        result = []
        for r in runs:
            d = r.to_dict()
            run_att_dir = ATTACHMENTS_DIR / r.id
            if run_att_dir.is_dir():
                d["attachments"] = sorted(
                    [{"name": f.name, "url": f"/api/attachments/{r.id}/{f.name}"}
                     for f in run_att_dir.iterdir() if f.is_file()],
                    key=lambda x: x["name"],
                )
            else:
                d["attachments"] = []
            result.append(d)
        return result
    finally:
        session.close()


class ResumeBody(BaseModel):
    prompt: str = ""


@app.post("/api/runs/{run_id}/pause")
async def pause_run(run_id: str):
    """Pause an active run -- kills agent, marks as paused (not completed)."""
    session, space_svc = _get_services()
    try:
        run_svc = RunService(session)
        run = run_svc.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.completed_at:
            raise HTTPException(status_code=400, detail="Run is already completed")

        space = space_svc.get(run.space_id) if run.space_id else None
        if space:
            AgentService.kill_agent(space.path, run_id=run.id, flow_name=run.flow_name or "")

        run_svc.pause(run_id)
        return {"ok": True}
    finally:
        session.close()


@app.post("/api/runs/{run_id}/resume")
async def resume_run(run_id: str, body: ResumeBody):
    """Resume a paused run, optionally with an additional prompt."""
    session, _ = _get_services()
    try:
        run_svc = RunService(session)
        run = run_svc.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if not run.paused_at:
            raise HTTPException(status_code=400, detail="Run is not paused")
        run_svc.resume(run_id, body.prompt)
        return {"ok": True}
    finally:
        session.close()


@app.post("/api/step-runs/{step_run_id}/complete")
async def complete_step_manually(step_run_id: str):
    """Manually mark a step as completed so the flow can advance."""
    session, _ = _get_services()
    try:
        run_svc = RunService(session)
        sr = run_svc.complete_step_manually(step_run_id)
        if not sr:
            raise HTTPException(status_code=404, detail="StepRun not found")
        return {"ok": True}
    finally:
        session.close()


@app.post("/api/runs/{run_id}/stop")
async def stop_run(run_id: str):
    """Stop or dequeue a run."""
    session, space_svc = _get_services()
    try:
        run_svc = RunService(session)
        run = run_svc.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.completed_at:
            raise HTTPException(status_code=400, detail="Run is already completed")

        if not run.started_at:
            session.delete(run)
            session.commit()
            return {"ok": True, "killed": False, "dequeued": True}

        run_svc.mark_completed(run_id, outcome="cancelled")

        space = space_svc.get(run.space_id) if run.space_id else None
        killed = False
        if space:
            killed = AgentService.kill_agent(space.path, run_id=run.id, flow_name=run.flow_name or "")

        return {"ok": True, "killed": killed, "dequeued": False}
    finally:
        session.close()


@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: str):
    """Delete a completed or queued (not yet started) flow run by ID."""
    session, _ = _get_services()
    try:
        from ..db.models import FlowRun
        run = session.query(FlowRun).filter_by(id=run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.started_at and not run.completed_at:
            raise HTTPException(status_code=400, detail="Cannot delete an active run")
        session.delete(run)
        session.commit()
        return {"ok": True}
    finally:
        session.close()


@app.get("/api/runs/{run_id}/steps")
async def get_run_steps(run_id: str):
    """Return step progress for a run, including all retry attempts."""
    session, _ = _get_services()
    try:
        from ..db.models import FlowRun
        run = session.query(FlowRun).filter_by(id=run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        run_svc = RunService(session)
        flow_svc = FlowService(session)
        step_runs = run_svc.list_step_runs(run_id)

        step_runs_by_name: dict[str, list] = {}
        for sr in step_runs:
            step_runs_by_name.setdefault(sr.step_name, []).append(sr)

        step_run_map = {}
        for name, srs in step_runs_by_name.items():
            step_run_map[name] = max(srs, key=lambda s: s.started_at or s.created_at if hasattr(s, 'created_at') else s.started_at)

        max_started_position = -1
        for sr in step_runs:
            if sr.started_at and sr.step_position > max_started_position:
                max_started_position = sr.step_position

        result = []

        snap_steps = []
        if run.flow_snapshot:
            try:
                snap = json.loads(run.flow_snapshot)
                snap_steps = sorted(snap.get("steps", []), key=lambda s: s.get("position", 0))
            except (json.JSONDecodeError, TypeError):
                pass

        step_sources = snap_steps or []
        if not step_sources and run.flow_name:
            for sname in flow_svc.get_flow_steps(run.flow_name, space_id=run.space_id):
                obj = flow_svc.get_step_obj(run.flow_name, sname, space_id=run.space_id)
                step_sources.append({
                    "name": sname,
                    "ifs": obj.get_ifs() if obj else [],
                    "agent_alias": obj.agent_alias if obj else "normal",
                    "allow_max": bool(obj.allow_max) if obj else False,
                    "max_gate_retries": obj.max_gate_retries if obj else 5,
                })

        from ..services.context import ContextService
        space = run.space

        for position, step_src in enumerate(step_sources):
            step_name = step_src["name"]
            has_ifs = bool(step_src.get("ifs"))
            sr = step_run_map.get(step_name)
            attempts = [s.to_dict() for s in sorted(step_runs_by_name.get(step_name, []), key=lambda s: s.attempt or 0)]
            if sr:
                status = sr.status
                step_data = sr.to_dict()
                if sr.awaiting_user_at and not sr.completed_at and space:
                    try:
                        artifacts_dir = ContextService.get_artifacts_dir(
                            Path(space.path), run_id, run.flow_name or "",
                        )
                        result_file = artifacts_dir / ContextService.step_dir_name(sr.step_position, sr.step_name) / "_result.md"
                        if result_file.exists():
                            step_data["user_message"] = result_file.read_text().strip()
                    except (PermissionError, OSError):
                        pass
            else:
                status = "skipped" if has_ifs and position < max_started_position else "pending"
                step_data = None
            result.append({
                "name": step_name,
                "flow": run.flow_name or "",
                "status": status,
                "has_ifs": has_ifs,
                "step_run": step_data,
                "attempts": attempts,
                "agent_alias": step_src.get("agent_alias", "normal"),
                "step_type": step_src.get("step_type", "agent"),
                "allow_max": bool(step_src.get("allow_max", False)),
                "max_gate_retries": step_src.get("max_gate_retries", 5),
            })

        summary_sr = step_run_map.get("__summarizer__")
        if summary_sr and not any(s["name"] == "__summarizer__" for s in result):
            result.append({
                "name": "__summarizer__",
                "flow": run.flow_name or "",
                "status": summary_sr.status,
                "has_ifs": False,
                "step_run": summary_sr.to_dict(),
                "attempts": [summary_sr.to_dict()],
            })

        return {"steps": result}
    finally:
        session.close()


class _PiLogState:
    """Tracks accumulated cost/tokens across Pi events in a single log stream."""
    __slots__ = ("total_cost", "total_tokens")

    def __init__(self):
        self.total_cost = 0.0
        self.total_tokens = 0

    def accumulate(self, event: dict) -> None:
        if event.get("type") == "message_end":
            msg = event.get("message", {})
            usage = msg.get("usage", {})
            cost = usage.get("cost", {})
            self.total_cost += cost.get("total", 0) or 0
            self.total_tokens += usage.get("totalTokens", 0) or 0


def _filter_pi_event(event: dict, state: _PiLogState) -> dict | None:
    """Filter Pi NDJSON events. Returns cleaned event or None to skip.

    Pi wraps role-based events inside ``{"type": "message_*", "message": {...}}``.
    We unwrap and filter at the message level.
    """
    etype = event.get("type")
    if etype in ("agent_start", "turn_start", "turn_end", "message_start", "message_update"):
        return None
    if etype == "message_end":
        state.accumulate(event)
    if etype == "agent_end":
        result: dict = {"type": "agent_end"}
        if state.total_cost > 0 or state.total_tokens > 0:
            result["cost"] = round(state.total_cost, 6)
            result["tokens"] = state.total_tokens
        return result
    if etype in ("session", "tool_execution_start", "tool_execution_end"):
        return event
    if etype == "message_end":
        msg = event.get("message", {})
        role = msg.get("role")
        if role == "user":
            return None
        if role == "assistant":
            return msg
        if role == "toolResult":
            return msg
        return None

    role = event.get("role")
    if role == "user":
        return None
    if role == "assistant":
        if event.get("stopReason") or event.get("textSignature"):
            return event
        return None
    if role == "toolResult":
        return event if "timestamp" in event else None
    if role:
        return None
    return event


@app.get("/api/step-runs/{step_run_id}/logs")
async def stream_step_run_logs(step_run_id: str, request: Request):
    """SSE endpoint that tails a StepRun's log file."""
    session, _ = _get_services()
    try:
        run_svc = RunService(session)
        sr = run_svc.get_step_run(step_run_id)
        if not sr:
            raise HTTPException(status_code=404, detail="StepRun not found")
        if not sr.log_path:
            raise HTTPException(status_code=404, detail="No log path set for this step run")
        log_path = Path(sr.log_path)
        is_completed = sr.completed_at is not None
    finally:
        session.close()

    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Log file not found on disk")

    def _read_all_events():
        """Read completed log file in one pass — no polling needed."""
        pi_state = _PiLogState()
        with open(log_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    filtered = _filter_pi_event(event, pi_state)
                    if filtered is None:
                        continue
                    yield f"data: {json.dumps(filtered)}\n\n"
                except json.JSONDecodeError:
                    yield f"data: {json.dumps({'type': 'raw', 'text': line})}\n\n"
        yield "data: {\"type\": \"done\"}\n\n"

    if is_completed:
        return StreamingResponse(
            _read_all_events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def tail_log():
        pos = 0
        idle_count = 0
        pi_state = _PiLogState()
        while idle_count < 120:
            if await request.is_disconnected():
                break
            try:
                size = log_path.stat().st_size
            except FileNotFoundError:
                break

            if size > pos:
                idle_count = 0
                with open(log_path, "r") as f:
                    f.seek(pos)
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                            filtered = _filter_pi_event(event, pi_state)
                            if filtered is None:
                                continue
                            yield f"data: {json.dumps(filtered)}\n\n"
                        except json.JSONDecodeError:
                            yield f"data: {json.dumps({'type': 'raw', 'text': line})}\n\n"
                    pos = f.tell()
            else:
                idle_count += 1

            await asyncio.sleep(1)

        yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(
        tail_log(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/runs/{run_id}/logs")
async def stream_run_logs(run_id: str, request: Request):
    """SSE endpoint that tails the agent's NDJSON log file for a FlowRun."""
    session, _ = _get_services()
    try:
        run_svc = RunService(session)
        run = run_svc.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        log_path = Path(run.log_path) if run.log_path else None

        if not log_path or not log_path.exists():
            step_runs = run_svc.list_step_runs(run_id)
            step_logs = [Path(sr.log_path) for sr in step_runs if sr.log_path and Path(sr.log_path).exists()]
            log_path = step_logs[0] if step_logs else None
    finally:
        session.close()

    if not log_path or not log_path.exists():
        raise HTTPException(status_code=404, detail="No log found for this run")

    async def tail_log():
        pos = 0
        idle_count = 0
        pi_state = _PiLogState()
        max_idle = 120
        while idle_count < max_idle:
            if await request.is_disconnected():
                break
            try:
                size = log_path.stat().st_size
            except FileNotFoundError:
                break

            if size > pos:
                idle_count = 0
                with open(log_path, "r") as f:
                    f.seek(pos)
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                            filtered = _filter_pi_event(event, pi_state)
                            if filtered is None:
                                continue
                            yield f"data: {json.dumps(filtered)}\n\n"
                        except json.JSONDecodeError:
                            yield f"data: {json.dumps({'type': 'raw', 'text': line})}\n\n"
                    pos = f.tell()
            else:
                idle_count += 1

            await asyncio.sleep(1)

        yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(
        tail_log(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Attachments ---

@app.get("/api/attachments/{run_id}/{filename}")
async def serve_attachment(run_id: str, filename: str):
    path = ATTACHMENTS_DIR / run_id / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(str(path))


# --- Agent Alias endpoints ---

class AgentAliasUpdate(BaseModel):
    agent: Optional[str] = None
    model: Optional[str] = None


@app.get("/api/agent-aliases")
async def list_agent_aliases(type: Optional[str] = None):
    from ..db.models import AgentAlias
    session, _ = _get_services()
    try:
        q = session.query(AgentAlias).order_by(AgentAlias.type, AgentAlias.position, AgentAlias.name)
        if type:
            q = q.filter_by(type=type)
        aliases = q.all()
        return [a.to_dict() for a in aliases]
    finally:
        session.close()


@app.patch("/api/agent-aliases/{alias_id}")
async def update_agent_alias(alias_id: str, body: AgentAliasUpdate):
    """Update agent/model on a pre-defined alias. Name and type are immutable."""
    from ..db.models import AgentAlias
    session, _ = _get_services()
    try:
        alias = session.query(AgentAlias).filter_by(id=alias_id).first()
        if not alias:
            raise HTTPException(status_code=404, detail="Alias not found")
        if body.agent is not None:
            alias.agent = body.agent
        if body.model is not None:
            alias.model = body.model
        session.commit()
        return alias.to_dict()
    finally:
        session.close()


# --- Queue + dashboard ---

@app.get("/api/queue")
async def global_queue():
    """All active FlowRuns globally (executing first, then pending)."""
    session, space_svc = _get_services()
    try:
        run_svc = RunService(session)
        runs = run_svc.list_active()
        result = []
        for r in runs:
            d = r.to_dict()
            space = space_svc.get(r.space_id) if r.space_id else None
            d["space_name"] = space.name if space else None
            result.append(d)
        return result
    finally:
        session.close()


@app.get("/api/spaces/{space_id}/queue")
async def space_queue(space_id: str):
    """All FlowRuns for space (pending + executing), ordered."""
    session, space_svc = _get_services()
    try:
        space = space_svc.get(space_id)
        if not space:
            raise HTTPException(status_code=404, detail="Space not found")
        run_svc = RunService(session)
        runs = run_svc.list_by_space(space_id)
        active = [r.to_dict() for r in runs if r.completed_at is None]
        return active
    finally:
        session.close()


@app.get("/api/setup-status")
async def setup_status():
    """Check whether initial setup is complete (at least one API key configured)."""
    from ..db.models import AgentConfig, AgentAlias
    import os
    session, _ = _get_services()
    try:
        has_any_key = False
        for name, reg in AGENT_REGISTRY.items():
            api_key_env = reg.get("api_key_env", "")
            if not api_key_env:
                continue
            if os.environ.get(api_key_env):
                has_any_key = True
                break
            cfg = session.query(AgentConfig).filter_by(agent=name, key=api_key_env).first()
            if cfg and cfg.value:
                has_any_key = True
                break
        if not has_any_key:
            for _, cached in _cli_auth_cache.values():
                if cached is not None:
                    has_any_key = True
                    break

        has_configured_alias = False
        for alias in session.query(AgentAlias).all():
            if alias.agent and alias.model:
                has_configured_alias = True
                break

        return {
            "needs_setup": not has_any_key,
            "has_api_key": has_any_key,
            "has_aliases": has_configured_alias,
        }
    finally:
        session.close()


@app.post("/api/setup/configure-provider/{provider}")
async def setup_configure_provider(provider: str):
    """Reconfigure pi alias tiers to use the given provider's default models."""
    from ..config import PROVIDER_DEFAULT_TIERS
    from ..db.models import AgentAlias

    tiers = PROVIDER_DEFAULT_TIERS.get(provider)
    if not tiers:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'")

    session, _ = _get_services()
    try:
        for tier_name, model in tiers.items():
            alias = session.query(AgentAlias).filter_by(type="pi", name=tier_name).first()
            if alias:
                alias.agent = provider
                alias.model = f"{provider}/{model}"
        session.commit()
        return {"ok": True, "provider": provider}
    finally:
        session.close()


@app.get("/api/dashboard")
async def dashboard():
    """System overview: all spaces with active run counts, queue depths."""
    session, space_svc = _get_services()
    try:
        run_svc = RunService(session)
        spaces = space_svc.list_all()
        result = []
        for p in spaces:
            all_runs = run_svc.list_by_space(p.id)
            active_runs = [r for r in all_runs if r.completed_at is None]
            pending_runs = [r for r in active_runs if r.started_at is None]
            executing_runs = [r for r in active_runs if r.started_at is not None]
            recent = [r.to_dict() for r in all_runs if r.completed_at is not None][-5:]

            run_counts = {
                "running": len(executing_runs),
                "queued": len(pending_runs),
            }

            result.append({
                "space": p.to_dict(),
                "run_counts": run_counts,
                "queue_depth": len(pending_runs),
                "active_runs": len(executing_runs),
                "executing": [
                    {
                        "run": r.to_dict(),
                        "agent_active": AgentService.is_agent_running(p.path, run_id=r.id, flow_name=r.flow_name or ""),
                    }
                    for r in executing_runs
                ],
                "recent_completions": recent,
            })
        return result
    finally:
        session.close()


# --- Inbox endpoints ---

@app.get("/api/inbox")
async def get_inbox():
    """Return inbox items (awaiting_user + completed_run), enriched with context."""
    from ..services.context import ContextService
    from ..db.models import Space as SpaceModel, StepRun, FlowRun
    session, _ = _get_services()
    try:
        run_svc = RunService(session)
        inbox_items = run_svc.list_inbox()

        awaiting = []
        completed = []

        for item in inbox_items:
            if item.type == "awaiting_user":
                sr = session.query(StepRun).filter_by(id=item.reference_id).first()
                if not sr or sr.completed_at:
                    run_svc.archive_inbox_item(item.id)
                    continue
                run = session.query(FlowRun).filter_by(id=sr.flow_run_id).first()
                space = session.query(SpaceModel).filter_by(id=item.space_id).first()
                if not run or not space:
                    continue

                step_type = "agent"
                if run.flow_snapshot:
                    try:
                        snap = json.loads(run.flow_snapshot)
                        for s in snap.get("steps", []):
                            if s["name"] == sr.step_name:
                                raw = s.get("step_type", "")
                                step_type = raw if raw in ("agent", "code", "hitl") else "agent"
                                break
                    except (ValueError, KeyError, TypeError):
                        pass

                user_message = ""
                try:
                    artifacts_dir = ContextService.get_artifacts_dir(
                        Path(space.path), run.id, run.flow_name or "",
                    )
                    result_file = artifacts_dir / ContextService.step_dir_name(sr.step_position, sr.step_name) / "_result.md"
                    if result_file.exists():
                        user_message = result_file.read_text().strip()
                except (PermissionError, OSError):
                    pass

                awaiting.append({
                    "inbox_id": item.id,
                    "step_run_id": sr.id,
                    "step_name": sr.step_name,
                    "step_type": step_type,
                    "step_position": sr.step_position,
                    "space_id": space.id,
                    "space_name": space.name,
                    "run_id": run.id,
                    "flow_id": run.flow_id or "",
                    "flow_name": run.flow_name or "",
                    "prompt": sr.prompt or "",
                    "user_message": user_message,
                    "log_path": sr.log_path or "",
                    "awaiting_since": (sr.awaiting_user_at.isoformat() + "Z") if sr.awaiting_user_at else None,
                })

            elif item.type == "completed_run":
                run = session.query(FlowRun).filter_by(id=item.reference_id).first()
                space = session.query(SpaceModel).filter_by(id=item.space_id).first()
                if not run or not space:
                    continue

                run_att_dir = ATTACHMENTS_DIR / run.id
                attachments = []
                if run_att_dir.is_dir():
                    attachments = sorted(
                        [{"name": f.name, "url": f"/api/attachments/{run.id}/{f.name}"}
                         for f in run_att_dir.iterdir() if f.is_file()],
                        key=lambda x: x["name"],
                    )

                completed.append({
                    "inbox_id": item.id,
                    "run_id": run.id,
                    "space_id": space.id,
                    "space_name": space.name,
                    "flow_id": run.flow_id or "",
                    "flow_name": run.flow_name or "",
                    "outcome": run.outcome or "",
                    "summary": run.summary or "",
                    "duration_seconds": run.duration_seconds,
                    "cost_usd": run.cost_usd,
                    "completed_at": (run.completed_at.isoformat() + "Z") if run.completed_at else None,
                    "attachments": attachments,
                })

        return {"awaiting": awaiting, "completed": completed, "count": len(awaiting) + len(completed)}
    finally:
        session.close()


@app.post("/api/inbox/{item_id}/archive")
async def archive_inbox_item(item_id: str):
    """Archive an inbox item (dismiss it)."""
    session, _ = _get_services()
    try:
        run_svc = RunService(session)
        ok = run_svc.archive_inbox_item(item_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Inbox item not found")
        return {"ok": True}
    finally:
        session.close()


@app.post("/api/step-runs/{step_run_id}/respond")
async def respond_to_step(step_run_id: str, body: StepRespondBody):
    """User responds to an awaiting_user step (confirm manual or answer prompt)."""
    session, _ = _get_services()
    try:
        run_svc = RunService(session)
        sr = run_svc.respond_to_step(step_run_id, body.response)
        if not sr:
            raise HTTPException(status_code=404, detail="StepRun not found or not awaiting user")
        return {"ok": True}
    finally:
        session.close()


# --- Flow endpoints (space-scoped) ---

@app.get("/api/spaces/{space_id}/flows")
async def list_space_flows(space_id: str):
    session, space_svc = _get_services()
    try:
        space = space_svc.get(space_id)
        if not space:
            raise HTTPException(status_code=404, detail="Space not found")
        flow_svc = FlowService(session)
        flows = flow_svc.list_by_space(space_id)

        from sqlalchemy import func
        from ..db.models import FlowRun, StepRun
        stats_q = (
            session.query(
                FlowRun.flow_id,
                func.count(FlowRun.id).label("run_count"),
                func.max(FlowRun.created_at).label("last_run_at"),
            )
            .filter(FlowRun.space_id == space_id)
            .group_by(FlowRun.flow_id)
            .all()
        )
        stats_map = {row.flow_id: {"run_count": row.run_count, "last_run_at": row.last_run_at} for row in stats_q}

        cost_q = (
            session.query(
                FlowRun.flow_id,
                func.sum(StepRun.cost_usd).label("total_cost"),
            )
            .join(StepRun, StepRun.flow_run_id == FlowRun.id)
            .filter(FlowRun.space_id == space_id)
            .group_by(FlowRun.flow_id)
            .all()
        )
        cost_map = {row.flow_id: row.total_cost for row in cost_q}

        duration_q = (
            session.query(
                FlowRun.flow_id,
                func.sum(func.julianday(FlowRun.completed_at) - func.julianday(FlowRun.started_at)).label("total_days"),
            )
            .filter(FlowRun.space_id == space_id)
            .filter(FlowRun.started_at.isnot(None))
            .filter(FlowRun.completed_at.isnot(None))
            .group_by(FlowRun.flow_id)
            .all()
        )
        duration_map = {row.flow_id: round(row.total_days * 86400, 1) if row.total_days else None for row in duration_q}

        active_q = (
            session.query(
                FlowRun.flow_id,
                func.count(FlowRun.id).label("active_count"),
            )
            .filter(FlowRun.space_id == space_id)
            .filter(FlowRun.completed_at.is_(None))
            .group_by(FlowRun.flow_id)
            .all()
        )
        active_map = {row.flow_id: row.active_count for row in active_q}

        result = []
        for f in flows:
            s = stats_map.get(f.id, {})
            last_run = s.get("last_run_at")
            result.append({
                "id": f.id,
                "space_id": f.space_id,
                "name": f.name,
                "description": f.description,
                "step_count": len(f.steps),
                "steps": [
                    {"name": st.name, "position": st.position, "step_type": st.step_type or "agent"}
                    for st in sorted(f.steps, key=lambda st: st.position)
                ],
                "run_count": s.get("run_count", 0),
                "total_cost_usd": round(cost_map.get(f.id) or 0, 6),
                "total_duration_seconds": duration_map.get(f.id),
                "last_run_at": last_run.isoformat() if last_run else None,
                "active_run_count": active_map.get(f.id, 0),
                "starred": bool(f.starred),
                "created_at": f.created_at.isoformat() if f.created_at else None,
                "updated_at": f.updated_at.isoformat() if f.updated_at else None,
            })
        return result
    finally:
        session.close()


@app.post("/api/spaces/{space_id}/flows/export")
async def export_space_flows(space_id: str):
    session, space_svc = _get_services()
    try:
        space = space_svc.get(space_id)
        if not space:
            raise HTTPException(status_code=404, detail="Space not found")
        flow_svc = FlowService(session)
        data = flow_svc.export_flows(space_id)
        return JSONResponse(content=data)
    finally:
        session.close()


@app.post("/api/flows/{flow_id}/export")
async def export_flow_to_disk(flow_id: str):
    """Export a single flow as JSON to the space's flows/ directory."""
    session = get_session()
    try:
        flow_svc = FlowService(session)
        flow = flow_svc.get(flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow not found")
        space_svc = SpaceService(session)
        space = space_svc.get(flow.space_id)
        if not space:
            raise HTTPException(status_code=404, detail="Space not found")
        file_path = flow_svc.export_flow_to_disk(flow_id, space.path)
        return {"ok": True, "path": file_path}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        session.close()


@app.post("/api/spaces/{space_id}/flows/import")
async def import_space_flows(space_id: str, file: UploadFile = File(...)):
    session, space_svc = _get_services()
    try:
        space = space_svc.get(space_id)
        if not space:
            raise HTTPException(status_code=404, detail="Space not found")
        content = await file.read()
        data = json.loads(content)
        flow_svc = FlowService(session)
        count = flow_svc._import_flows_data(data, space_id=space_id, skip_existing=False)
        return {"imported": count}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    finally:
        session.close()


@app.get("/api/flows/{flow_id}")
async def get_flow(flow_id: str):
    session, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        flow = flow_svc.get(flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow not found")
        result = flow.to_dict()
        result["warnings"] = flow_svc.validate_flow(flow_id)
        return result
    finally:
        session.close()


@app.get("/api/flows/{flow_id}/validate")
async def validate_flow(flow_id: str):
    session, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        return {"warnings": flow_svc.validate_flow(flow_id)}
    finally:
        session.close()


@app.post("/api/spaces/{space_id}/flows")
async def create_space_flow(space_id: str, body: FlowCreate):
    session, space_svc = _get_services()
    try:
        space = space_svc.get(space_id)
        if not space:
            raise HTTPException(status_code=404, detail="Space not found")
        flow_svc = FlowService(session)
        if body.copy_from:
            flow = flow_svc.duplicate(body.copy_from, body.name, space_id=space_id)
            if not flow:
                raise HTTPException(status_code=404, detail=f"Source flow '{body.copy_from}' not found")
            if body.description:
                flow_svc.update(flow.id, description=body.description)
        else:
            flow = flow_svc.create(
                name=body.name,
                space_id=space_id,
                description=body.description,
                requirements=body.requirements,
            )
        return flow.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        session.close()


@app.patch("/api/flows/{flow_id}")
async def update_flow(flow_id: str, body: FlowUpdate):
    session, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        updates = {}
        if body.name is not None:
            updates["name"] = body.name
        if body.description is not None:
            updates["description"] = body.description
        if body.requirements is not None:
            updates["requirements"] = json.dumps(body.requirements)
        if body.max_concurrent_runs is not None:
            updates["max_concurrent_runs"] = max(1, body.max_concurrent_runs)
        if body.max_spend_usd is not None:
            updates["max_spend_usd"] = body.max_spend_usd if body.max_spend_usd > 0 else None
        if body.starred is not None:
            updates["starred"] = body.starred
        if body.schedule_cron is not None:
            cron_expr = body.schedule_cron.strip() if body.schedule_cron else ""
            if cron_expr:
                from croniter import croniter
                if not croniter.is_valid(cron_expr):
                    raise HTTPException(status_code=400, detail=f"Invalid cron expression: {cron_expr}")
            updates["schedule_cron"] = cron_expr or None
            if not cron_expr:
                updates["schedule_next_at"] = None
                updates["schedule_enabled"] = False
        if body.schedule_timezone is not None:
            updates["schedule_timezone"] = body.schedule_timezone or "UTC"
        if body.schedule_enabled is not None:
            updates["schedule_enabled"] = body.schedule_enabled
            if body.schedule_enabled:
                existing = flow_svc.get(flow_id)
                cron_expr = updates.get("schedule_cron", existing.schedule_cron if existing else None)
                tz_str = updates.get("schedule_timezone", existing.schedule_timezone if existing else None) or "UTC"
                if cron_expr:
                    updates["schedule_next_at"] = _compute_next_run(cron_expr, tz_str)
                else:
                    updates["schedule_enabled"] = False
            else:
                updates["schedule_next_at"] = None
        elif body.schedule_cron is not None and updates.get("schedule_cron"):
            existing = flow_svc.get(flow_id)
            if existing and existing.schedule_enabled:
                tz_str = updates.get("schedule_timezone", existing.schedule_timezone) or "UTC"
                updates["schedule_next_at"] = _compute_next_run(updates["schedule_cron"], tz_str)
        flow = flow_svc.update(flow_id, **updates)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow not found")
        return flow.to_dict()
    finally:
        session.close()


def _compute_next_run(cron_expr: str, tz_str: str = "UTC"):
    """Compute the next UTC datetime for a cron expression in the given timezone."""
    from datetime import datetime, timezone as _tz
    from croniter import croniter
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    tz = ZoneInfo(tz_str) if tz_str != "UTC" else _tz.utc
    now_local = datetime.now(tz)
    cron = croniter(cron_expr, now_local)
    next_local = cron.get_next(datetime)
    return next_local.astimezone(_tz.utc).replace(tzinfo=None)


@app.delete("/api/flows/{flow_id}")
async def delete_flow(flow_id: str):
    session, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        flow_svc.delete(flow_id)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        session.close()


@app.post("/api/flows/{flow_id}/steps")
async def add_flow_step(flow_id: str, body: StepCreate):
    session, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        step = flow_svc.add_step(
            flow_id, body.name, body.content, body.position,
            gates=body.gates, ifs=body.ifs,
            agent_alias=body.agent_alias, step_type=body.step_type,
            allow_max=body.allow_max,
            max_gate_retries=body.max_gate_retries,
            skills=body.skills,
            connectors=body.connectors,
        )
        if not step:
            raise HTTPException(status_code=404, detail="Flow not found")
        return step.to_dict()
    finally:
        session.close()


@app.patch("/api/flows/{flow_id}/steps/{step_id}")
async def update_flow_step(flow_id: str, step_id: str, body: StepUpdate):
    session, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        updates = {}
        if body.name is not None:
            updates["name"] = body.name
        if body.content is not None:
            updates["content"] = body.content
        if body.position is not None:
            updates["position"] = body.position
        if body.gates is not None:
            updates["gates"] = json.dumps(body.gates)
        if body.ifs is not None:
            updates["ifs"] = json.dumps(body.ifs)
        if body.agent_alias is not None:
            updates["agent_alias"] = body.agent_alias
        if body.step_type is not None:
            updates["step_type"] = body.step_type
        if body.allow_max is not None:
            updates["allow_max"] = body.allow_max
        if body.max_gate_retries is not None:
            updates["max_gate_retries"] = body.max_gate_retries
        if body.skills is not None:
            updates["skills"] = json.dumps(body.skills)
        if body.connectors is not None:
            updates["connectors"] = json.dumps(body.connectors)
        step = flow_svc.update_step(step_id, **updates)
        if not step:
            raise HTTPException(status_code=404, detail="Step not found")
        return step.to_dict()
    finally:
        session.close()


@app.delete("/api/flows/{flow_id}/steps/{step_id}")
async def delete_flow_step(flow_id: str, step_id: str):
    session, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        if not flow_svc.remove_step(step_id):
            raise HTTPException(status_code=404, detail="Step not found")
        return {"ok": True}
    finally:
        session.close()


@app.post("/api/flows/{flow_id}/reorder")
async def reorder_flow_steps(flow_id: str, body: ReorderSteps):
    session, _ = _get_services()
    try:
        flow_svc = FlowService(session)
        if not flow_svc.reorder_steps(flow_id, body.step_ids):
            raise HTTPException(status_code=404, detail="Flow not found")
        flow = flow_svc.get(flow_id)
        return flow.to_dict()
    finally:
        session.close()


# --- Skills endpoints ---

@app.get("/api/spaces/{space_id}/skills")
async def list_space_skills(space_id: str):
    """Return discovered skills for a space."""
    session, space_svc = _get_services()
    try:
        space = space_svc.get(space_id)
        if not space:
            raise HTTPException(status_code=404, detail="Space not found")
        skills = SkillService.discover(space.path)
        return [{"name": s.name, "path": s.path, "description": s.description, "compatibility": s.compatibility} for s in skills]
    finally:
        session.close()


@app.get("/api/spaces/{space_id}/skills/{skill_name}/content")
async def get_skill_content(space_id: str, skill_name: str):
    """Return the full SKILL.md content for a skill."""
    session, space_svc = _get_services()
    try:
        space = space_svc.get(space_id)
        if not space:
            raise HTTPException(status_code=404, detail="Space not found")
        content = SkillService.get_content(space.path, skill_name)
        if content is None:
            raise HTTPException(status_code=404, detail="Skill not found")
        return {"content": content}
    finally:
        session.close()


@app.get("/api/agents")
async def list_agents():
    """Return only agents whose binary is found in PATH (ready to use)."""
    import shutil
    return [name for name in KNOWN_AGENTS if shutil.which(AGENT_REGISTRY[name]["binary"])]


_cli_auth_cache: dict[str, tuple[float, dict | None]] = {}
_CLI_AUTH_TTL = 120  # seconds


def _check_cli_auth(binary: str) -> dict | None:
    """Check if a CLI agent has OAuth/login auth configured. Returns auth info or None.

    Only claude CLI supports this (via `claude auth status` → JSON).
    Cursor agent stores auth in the IDE keychain, not accessible from subprocesses.
    """
    import subprocess as _sp
    import time

    now = time.monotonic()
    cached = _cli_auth_cache.get(binary)
    if cached and (now - cached[0]) < _CLI_AUTH_TTL:
        return cached[1]

    result = None
    try:
        proc = _sp.run(
            [binary, "auth", "status"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            if data.get("loggedIn"):
                result = {
                    "method": data.get("authMethod", "oauth"),
                    "email": data.get("email", ""),
                }
    except Exception:
        pass
    _cli_auth_cache[binary] = (now, result)
    return result


@app.get("/api/agents/status")
async def agents_status():
    """Return availability status for all known agents (CLI agents only)."""
    import shutil
    import os
    from ..db.models import AgentConfig
    session, _ = _get_services()
    try:
        result = {}
        auth_futures: dict[str, tuple[str, asyncio.Task]] = {}
        loop = asyncio.get_event_loop()

        for name, reg in AGENT_REGISTRY.items():
            if reg.get("type") != "code":
                continue
            binary_path = shutil.which(reg["binary"])
            api_key_env = reg.get("api_key_env", "")
            has_key = False
            if api_key_env:
                has_key = bool(os.environ.get(api_key_env))
                if not has_key:
                    cfg = session.query(AgentConfig).filter_by(agent=name, key=api_key_env).first()
                    has_key = bool(cfg and cfg.value)
            if binary_path and not has_key:
                auth_futures[name] = loop.run_in_executor(None, _check_cli_auth, reg["binary"])
            result[name] = {
                "label": reg["label"],
                "available": binary_path is not None,
                "binary": reg["binary"],
                "binary_path": binary_path,
                "command": reg["command"],
                "api_key_env": api_key_env,
                "configured": has_key,
                "auth": None,
            }

        for name, future in auth_futures.items():
            auth_info = await future
            if auth_info:
                result[name]["auth"] = auth_info
                result[name]["configured"] = True

        return result
    finally:
        session.close()



@app.get("/api/providers/status")
async def providers_status():
    """Return chat/LLM providers with their config status."""
    from ..db.models import AgentConfig
    import os
    session, _ = _get_services()
    try:
        result = {}
        for name, reg in AGENT_REGISTRY.items():
            if reg.get("type") != "provider":
                continue
            api_key_env = reg.get("api_key_env", "")
            has_key = False
            if api_key_env:
                has_key = bool(os.environ.get(api_key_env))
                if not has_key:
                    cfg = session.query(AgentConfig).filter_by(agent=name, key=api_key_env).first()
                    has_key = bool(cfg and cfg.value)
            result[name] = {
                "label": reg["label"],
                "api_key_env": api_key_env,
                "configured": has_key,
            }
        return result
    finally:
        session.close()


class ValidateKeyBody(BaseModel):
    key: str


@app.post("/api/agents/{agent_name}/validate-key")
async def validate_agent_key(agent_name: str, body: ValidateKeyBody):
    """Validate an API key by making a lightweight call to the provider."""
    import httpx

    reg = AGENT_REGISTRY.get(agent_name)
    if not reg:
        raise HTTPException(status_code=404, detail="Unknown agent/provider")

    key = body.key.strip()
    if not key:
        return {"valid": False, "error": "API key is empty"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            if agent_name == "openai":
                r = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                )
                if r.status_code == 401:
                    return {"valid": False, "error": "Invalid API key"}
                if r.status_code == 200:
                    return {"valid": True}
                return {"valid": False, "error": f"Unexpected response ({r.status_code})"}

            elif agent_name == "anthropic":
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={"model": "claude-haiku-4-5", "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]},
                )
                if r.status_code == 401:
                    return {"valid": False, "error": "Invalid API key"}
                return {"valid": True}

            elif agent_name == "google":
                r = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
                )
                if r.status_code in (401, 403):
                    return {"valid": False, "error": "Invalid API key"}
                if r.status_code == 200:
                    return {"valid": True}
                return {"valid": False, "error": f"Unexpected response ({r.status_code})"}

            elif agent_name == "ollama":
                host = key if key.startswith("http") else f"http://{key}"
                host = host.rstrip("/")
                r = await client.get(f"{host}/api/tags")
                if r.status_code == 200:
                    return {"valid": True}
                return {"valid": False, "error": f"Cannot reach Ollama at {host}"}

            else:
                return {"valid": True}

    except httpx.TimeoutException:
        return {"valid": False, "error": "Connection timed out"}
    except httpx.ConnectError:
        return {"valid": False, "error": "Could not connect to provider"}
    except Exception as e:
        return {"valid": False, "error": str(e)}


@app.get("/api/agents/{agent_name}/config")
async def get_agent_config(agent_name: str):
    from ..db.models import AgentConfig
    session, _ = _get_services()
    try:
        configs = session.query(AgentConfig).filter_by(agent=agent_name).all()
        return [c.to_dict() for c in configs]
    finally:
        session.close()


class AgentConfigBody(BaseModel):
    key: str
    value: str


@app.post("/api/agents/{agent_name}/config")
async def set_agent_config(agent_name: str, body: AgentConfigBody):
    from ..db.models import AgentConfig
    session, _ = _get_services()
    try:
        existing = session.query(AgentConfig).filter_by(agent=agent_name, key=body.key).first()
        if existing:
            existing.value = body.value
        else:
            session.add(AgentConfig(agent=agent_name, key=body.key, value=body.value))
        session.commit()
        configs = session.query(AgentConfig).filter_by(agent=agent_name).all()
        return [c.to_dict() for c in configs]
    finally:
        session.close()


@app.delete("/api/agents/{agent_name}/config/{config_id}")
async def delete_agent_config(agent_name: str, config_id: str):
    from ..db.models import AgentConfig
    session, _ = _get_services()
    try:
        config = session.query(AgentConfig).filter_by(id=config_id, agent=agent_name).first()
        if not config:
            raise HTTPException(status_code=404, detail="Config not found")
        session.delete(config)
        session.commit()
        return {"ok": True}
    finally:
        session.close()


@app.get("/api/models")
async def list_models(agent: Optional[str] = None):
    """Return models for a specific agent, or all models if no agent specified."""
    if agent and agent in AGENT_REGISTRY:
        return AGENT_REGISTRY[agent].get("models", [])
    return KNOWN_MODELS


# --- Chat endpoints ---


class ChatBody(BaseModel):
    message: str
    space_id: Optional[str] = None
    session_id: Optional[str] = None
    tier: Optional[str] = None
    flow_name: Optional[str] = None


@app.post("/api/chat")
async def chat(body: ChatBody):
    """Send a message to the Pi-powered chat assistant. Returns an SSE stream."""
    import shutil as _shutil
    from ..services.chat import build_pi_command

    if not _shutil.which("pi"):
        raise HTTPException(status_code=503, detail="Pi binary not found in PATH")

    session_id = body.session_id or uuid.uuid4().hex[:10]
    session_dir = CHAT_SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    session_file = session_dir / "session"
    system_file = session_dir / "system.md"

    space, space_context = _build_space_context(body.space_id)

    flow_context = ""
    if body.flow_name and space:
        flow_context = _build_flow_context(body.flow_name, space.id)

    skill_paths = _get_skill_paths()
    system_file.write_text(_CHAT_SYSTEM_PROMPT + space_context + flow_context)

    chat_model = _resolve_chat_model(body.tier or "max")

    cmd = build_pi_command(
        message=body.message,
        session_file=session_file,
        system_file=system_file,
        model=chat_model,
        skill_paths=skill_paths,
    )

    env = _build_pi_env()

    _chat_stderr = (CHAT_SESSIONS_DIR / session_id / "stderr.log").open("w")
    logging.getLogger("llmflows.chat").info("Chat command: %s", " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=_chat_stderr,
        env=env,
        cwd=space.path if space else str(Path.home()),
    )

    async def stream():
        total_cost = 0.0
        agent_done = False
        try:
            assert proc.stdout is not None
            buf = b""
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line_bytes, buf = buf.split(b"\n", 1)
                    line = line_bytes.decode(errors="replace").strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ev_type = ev.get("type")
                    if ev_type == "message_update":
                        ame = ev.get("assistantMessageEvent", {})
                        ame_type = ame.get("type")
                        if ame_type == "text_delta":
                            delta = ame.get("delta", "")
                            if delta:
                                yield f"data: {json.dumps({'type': 'text_delta', 'text': delta})}\n\n"
                        elif ame_type == "thinking_start":
                            yield f"data: {json.dumps({'type': 'thinking'})}\n\n"
                        elif ame_type == "thinking_delta":
                            delta = ame.get("delta", "")
                            if delta:
                                yield f"data: {json.dumps({'type': 'thinking_delta', 'text': delta})}\n\n"
                    elif ev_type == "message_end":
                        msg = ev.get("message", {})
                        usage = msg.get("usage", {})
                        cost = usage.get("cost", {})
                        total_cost += cost.get("total", 0) or 0
                    elif ev_type == "agent_end":
                        agent_done = True
                        break
                if agent_done:
                    break
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
        except asyncio.CancelledError:
            if proc.returncode is None:
                proc.terminate()
                await proc.wait()
            raise
        done_payload: dict = {"type": "done", "session_id": session_id}
        if total_cost > 0:
            done_payload["cost_usd"] = round(total_cost, 6)
        yield f"data: {json.dumps(done_payload)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.delete("/api/chat/sessions/{session_id}")
async def delete_chat_session(session_id: str):
    """Delete a chat session and its files."""
    session_dir = CHAT_SESSIONS_DIR / session_id
    if not session_dir.is_dir():
        raise HTTPException(status_code=404, detail="Session not found")
    shutil.rmtree(session_dir, ignore_errors=True)
    return {"ok": True}


@app.websocket("/{path:path}")
async def _ws_reject(ws: _StarletteWebSocket):
    """Reject stray WebSocket connections so they don't crash StaticFiles."""
    await ws.close()


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/{path:path}")
async def spa_fallback(path: str):
    """Serve index.html for any non-API path (SPA client-side routing)."""
    index = STATIC_DIR / "index.html"
    if index.is_file():
        return FileResponse(index)
    return HTMLResponse(
        content=(
            "<html><body style='font-family:monospace;padding:2rem'>"
            "<h2>UI not built</h2>"
            "<p>The React frontend was not compiled during installation.</p>"
            "<p>Run the following inside the package source directory to build it:</p>"
            "<pre>cd llmflows/ui/frontend && npm install && npm run build</pre>"
            "<p>Or reinstall with Node.js available so the build hook can run automatically.</p>"
            "</body></html>"
        ),
        status_code=503,
    )
