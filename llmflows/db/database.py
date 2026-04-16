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
    for alias_type in ("code", "chat"):
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


def init_db() -> Path:
    """Initialize the database and run any pending migrations."""
    ensure_system_dir()
    url = f"sqlite:///{SYSTEM_DB}"
    _alembic.upgrade(_alembic_cfg(url), "head")

    engine = create_engine(url, echo=False)
    session = sessionmaker(bind=engine)()
    try:
        _seed_agent_aliases(session)
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
