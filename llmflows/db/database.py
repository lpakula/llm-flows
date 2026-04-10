"""Database connection and initialization for central ~/.llmflows/llmflows.db."""

from pathlib import Path
from typing import Optional

from alembic import command as _alembic
from alembic.config import Config as _AlembicConfig
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import SYSTEM_DB, ensure_system_dir

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
    """Seed default agent aliases if the table is empty."""
    from .models import AgentAlias
    if session.query(AgentAlias).count() > 0:
        return
    defaults = [
        ("max", "cursor", "claude-4.6-opus-max-thinking", 0),
        ("high", "cursor", "claude-4.6-sonnet-medium-thinking", 1),
        ("standard", "cursor", "composer-2", 2),
        ("fast", "cursor", "composer-2-fast", 3),
        ("low", "cursor", "gemini-3-flash", 4),
    ]
    for name, agent, model, pos in defaults:
        session.add(AgentAlias(name=name, agent=agent, model=model, position=pos))
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
            "No llmflows database found. Run 'llmflows register' to register a project."
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
