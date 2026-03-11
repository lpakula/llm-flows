"""Database connection and initialization for central ~/.llmflows/llmflows.db."""

from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from ..config import SYSTEM_DB, ensure_system_dir
from .models import Base

_engine = None
_SessionLocal = None


def get_db_path() -> Path:
    """Return the path to the central database."""
    return SYSTEM_DB


def init_db() -> Path:
    """Initialize the central database schema and seed default flows."""
    ensure_system_dir()
    engine = create_engine(f"sqlite:///{SYSTEM_DB}", echo=False)
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    if "projects" in inspector.get_table_names():
        existing = {c["name"] for c in inspector.get_columns("projects")}
        if "aliases" not in existing:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE projects ADD COLUMN aliases TEXT DEFAULT '{}'"))
                conn.commit()

    session = sessionmaker(bind=engine)()
    try:
        from ..services.flow import FlowService
        flow_svc = FlowService(session)
        flow_svc.seed_defaults()
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
    """Reset the global engine (for testing)."""
    global _engine, _SessionLocal
    _engine = None
    _SessionLocal = None
