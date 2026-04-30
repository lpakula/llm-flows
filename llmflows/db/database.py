"""Database connection and initialization for central ~/.llmflows/llmflows.db."""

from pathlib import Path
from typing import Optional

from alembic import command as _alembic
from alembic.config import Config as _AlembicConfig
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import AGENT_REGISTRY, SYSTEM_DB, ensure_system_dir

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _alembic_cfg(url: str) -> _AlembicConfig:
    cfg = _AlembicConfig()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg

_engine = None
_SessionLocal = None


def get_db_path() -> Path:
    """Return the path to the central database."""
    return SYSTEM_DB


def _seed_agent_aliases(session):
    """Seed default agent aliases if the table is empty.

    Creates 3 tiers (max/normal/low) for each type (code/chat),
    using the first registered agent of that type as the default.
    """
    from .models import AgentAlias
    if session.query(AgentAlias).count() > 0:
        return
    pos = 0
    for alias_type in ("code", "pi"):
        default_agent = None
        default_tiers = None
        for agent_key, reg in AGENT_REGISTRY.items():
            if reg.get("type") == alias_type and reg.get("tiers"):
                default_agent = agent_key
                default_tiers = reg["tiers"]
                break
        if not default_agent or not default_tiers:
            continue
        for tier_name in ("max", "normal", "mini"):
            model = default_tiers.get(tier_name, "")
            if model:
                session.add(AgentAlias(
                    name=tier_name, type=alias_type,
                    agent=default_agent, model=model, position=pos,
                ))
                pos += 1
    session.commit()


def _seed_mcp_connectors(session):
    """Seed built-in MCP connectors (browser, web_search) if not present."""
    from .models import McpConnector

    BUILTINS = [
        {
            "server_id": "web_search",
            "name": "Web Search",
            "command": "tsx mcp-server-web-search.ts",
            "enabled": True,
            "builtin": True,
        },
        {
            "server_id": "browser",
            "name": "Browser",
            "command": "tsx mcp-server-browser.ts",
            "enabled": False,
            "builtin": True,
            "env": '{"BROWSER_USER_DATA_DIR": "$HOME/.llmflows/browser-profile", "BROWSER_HEADLESS": "false"}',
        },
    ]
    for b in BUILTINS:
        existing = session.query(McpConnector).filter_by(server_id=b["server_id"]).first()
        if not existing:
            session.add(McpConnector(**b))
        elif b.get("env") and not existing.env:
            existing.env = b["env"]
    session.commit()


def _migrate_tool_config_to_mcp(session):
    """One-time migration: copy [browser] and [web_search] TOML config into McpConnector rows."""
    import json
    from ..config import load_system_config, save_system_config
    from .models import McpConnector

    config = load_system_config()
    migrated = False

    ws_toml = config.get("web_search", {})
    if ws_toml and any(k != "enabled" for k in ws_toml):
        row = session.query(McpConnector).filter_by(server_id="web_search").first()
        if row:
            env = row.get_env()
            creds = row.get_credentials()
            if ws_toml.get("provider"):
                env["WEB_SEARCH_PROVIDER"] = ws_toml["provider"]
            for key in ("brave_api_key", "perplexity_api_key", "serpapi_api_key"):
                if ws_toml.get(key):
                    creds[key.upper()] = ws_toml[key]
            row.env = json.dumps(env)
            row.credentials = json.dumps(creds)
            if ws_toml.get("enabled") is not None:
                row.enabled = ws_toml["enabled"]
            migrated = True

    br_toml = config.get("browser", {})
    if br_toml and any(k != "enabled" for k in br_toml):
        row = session.query(McpConnector).filter_by(server_id="browser").first()
        if row:
            env = row.get_env()
            if br_toml.get("headless") is not None:
                env["BROWSER_HEADLESS"] = str(br_toml["headless"]).lower()
            if br_toml.get("user_data_dir"):
                env["BROWSER_USER_DATA_DIR"] = br_toml["user_data_dir"]
            row.env = json.dumps(env)
            if br_toml.get("enabled") is not None:
                row.enabled = br_toml["enabled"]
            migrated = True

    if migrated:
        session.commit()
        for old_key in ("web_search", "browser"):
            config.pop(old_key, None)
        if "mcp" not in config:
            config["mcp"] = {"enabled": True, "port_range_start": 19100}
        save_system_config(config)


def init_db() -> Path:
    """Initialize the database and run any pending migrations."""
    ensure_system_dir()
    url = f"sqlite:///{SYSTEM_DB}"
    _alembic.upgrade(_alembic_cfg(url), "head")

    engine = create_engine(url, echo=False)
    session = sessionmaker(bind=engine)()
    try:
        _seed_agent_aliases(session)
        _seed_mcp_connectors(session)
        _migrate_tool_config_to_mcp(session)
    finally:
        session.close()

    return SYSTEM_DB


def get_engine(db_path: Optional[Path] = None):
    """Get or create the database engine."""
    global _engine
    if _engine is not None:
        return _engine

    path = db_path or SYSTEM_DB
    if not path.exists():
        raise FileNotFoundError(
            "No llmflows database found. Run 'llmflows register' to register a space."
        )
    _engine = create_engine(f"sqlite:///{path}", echo=False)
    return _engine


def get_session(db_path: Optional[Path] = None) -> Session:
    """Get a new database session."""
    global _SessionLocal
    engine = get_engine(db_path)
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=engine)
    return _SessionLocal()


def get_db(db_path: Optional[Path] = None):
    """Context manager for database sessions."""
    session = get_session(db_path)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine():
    """Reset the global engine, disposing the old connection pool to avoid fd leaks."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
