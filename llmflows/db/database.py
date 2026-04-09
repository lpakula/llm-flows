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


def _add_column_if_missing(engine, inspector, table: str, column: str, column_def: str):
    """Add a column to a table if it doesn't exist yet."""
    if table not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns(table)}
    if column not in existing:
        with engine.connect() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}"))
            conn.commit()


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
    """Initialize the central database schema and seed defaults."""
    ensure_system_dir()
    engine = create_engine(f"sqlite:///{SYSTEM_DB}", echo=False)
    Base.metadata.create_all(engine)

    inspector = inspect(engine)

    # Legacy project columns (kept for old DBs but no longer used in code)
    _add_column_if_missing(engine, inspector, "projects", "aliases", "TEXT DEFAULT '{}'")

    _add_column_if_missing(engine, inspector, "project_settings", "is_git_repo", "BOOLEAN DEFAULT 1")

    # FlowStep migrations
    _add_column_if_missing(engine, inspector, "flow_steps", "ifs", "TEXT DEFAULT '[]'")
    _add_column_if_missing(engine, inspector, "flow_steps", "agent_alias", "VARCHAR(50) DEFAULT 'standard'")
    _add_column_if_missing(engine, inspector, "flow_steps", "allow_max", "BOOLEAN DEFAULT 0")
    _add_column_if_missing(engine, inspector, "flow_steps", "max_gate_retries", "INTEGER DEFAULT 3")

    # Drop legacy columns no longer in the ORM
    if "task_runs" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("task_runs")}
        for legacy_col in ("model", "agent"):
            if legacy_col in existing_cols:
                with engine.connect() as conn:
                    conn.execute(text(f"ALTER TABLE task_runs DROP COLUMN {legacy_col}"))
                    conn.commit()

    # TaskRun migrations
    _add_column_if_missing(engine, inspector, "task_runs", "recovery_count", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(engine, inspector, "task_runs", "step_overrides", "TEXT DEFAULT '{}'")
    _add_column_if_missing(engine, inspector, "task_runs", "one_shot", "BOOLEAN DEFAULT 0")
    _add_column_if_missing(engine, inspector, "task_runs", "run_flow_id", "VARCHAR(6)")
    _add_column_if_missing(engine, inspector, "task_runs", "paused_at", "DATETIME")
    _add_column_if_missing(engine, inspector, "task_runs", "resume_prompt", "TEXT DEFAULT ''")

    # Task migrations
    _add_column_if_missing(engine, inspector, "tasks", "default_flow_name", "VARCHAR(255)")
    _add_column_if_missing(engine, inspector, "tasks", "task_status", "VARCHAR(50) DEFAULT 'backlog'")
    # Migrate legacy status values to current set
    with engine.connect() as conn:
        conn.execute(text("UPDATE tasks SET task_status = 'in_progress' WHERE task_status IN ('failed', 'stopped')"))
        conn.commit()

    # StepRun migrations
    _add_column_if_missing(engine, inspector, "step_runs", "attempt", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(engine, inspector, "step_runs", "gate_failures", "TEXT DEFAULT ''")

    # Flow.project_id migration
    _add_column_if_missing(engine, inspector, "flows", "project_id", "VARCHAR(6)")

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
    """Reset the global engine (for testing)."""
    global _engine, _SessionLocal
    _engine = None
    _SessionLocal = None
