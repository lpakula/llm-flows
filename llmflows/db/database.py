"""Database connection and initialization (PostgreSQL)."""

import os
from pathlib import Path

from alembic import command as _alembic
from alembic.config import Config as _AlembicConfig
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import AGENT_REGISTRY, SYSTEM_DIR, ensure_system_dir

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _get_database_url() -> str:
    """Resolve the database URL from env or start bundled Postgres."""
    url = os.environ.get("DATABASE_URL")
    if url:
        if url.startswith("sqlite:"):
            raise RuntimeError(
                "SQLite is no longer supported. Set DATABASE_URL to a PostgreSQL "
                "URL (e.g. postgresql://llmflows:llmflows@localhost:5433/llmflows) "
                "or unset it to use the bundled Postgres container."
            )
        return url
    from ..services.postgres import ensure_postgres

    return ensure_postgres()


def get_runner_database_url() -> str | None:
    """DATABASE_URL as seen from inside runner/chat containers."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    from ..services.postgres import runner_database_url

    return runner_database_url(url)


def _alembic_cfg(url: str) -> _AlembicConfig:
    cfg = _AlembicConfig()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg

_engine = None
_SessionLocal = None


def _seed_agent_aliases(session):
    """Create 3 tiers (max/normal/mini) for pi aliases, using Pi as the default agent."""
    from .models import AgentAlias
    if session.query(AgentAlias).count() > 0:
        return
    pos = 0
    for alias_type in ("pi",):
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


def init_db(*, seed: bool = True) -> Path:
    """Initialize the database and run any pending migrations."""
    ensure_system_dir()
    url = _get_database_url()
    _alembic.upgrade(_alembic_cfg(url), "head")

    engine = create_engine(url, echo=False, pool_pre_ping=True)
    session = sessionmaker(bind=engine)()
    try:
        if seed:
            _seed_agent_aliases(session)
        _seed_mcp_connectors(session)
    finally:
        session.close()

    return SYSTEM_DIR


def get_engine():
    """Get or create the database engine."""
    global _engine
    if _engine is not None:
        return _engine

    _engine = create_engine(_get_database_url(), echo=False, pool_pre_ping=True)
    return _engine


def get_session() -> Session:
    """Get a new database session."""
    global _SessionLocal
    engine = get_engine()
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=engine)
    return _SessionLocal()


def get_db():
    """Context manager for database sessions."""
    session = get_session()
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
