"""SQLAlchemy models for llmflows."""

import secrets
import string
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Integer, String, Text, UniqueConstraint  # noqa: F401
from sqlalchemy.orm import DeclarativeBase, relationship


def generate_id() -> str:
    """Generate a 6-character alphanumeric ID."""
    chars = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(6))


class Base(DeclarativeBase):
    pass


class TaskType(str, Enum):
    FEATURE = "feature"
    FIX = "fix"
    REFACTOR = "refactor"
    CHORE = "chore"


class AgentAlias(Base):
    __tablename__ = "agent_aliases"

    id: str = Column(String(6), primary_key=True, default=generate_id)
    name: str = Column(String(50), nullable=False, unique=True)
    agent: str = Column(String(50), nullable=False, default="cursor")
    model: str = Column(String(100), nullable=False)
    position: int = Column(Integer, default=0)
    created_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                                  onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "agent": self.agent,
            "model": self.model,
            "position": self.position or 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AgentConfig(Base):
    __tablename__ = "agent_configs"

    id: str = Column(String(6), primary_key=True, default=generate_id)
    agent: str = Column(String(50), nullable=False)
    key: str = Column(String(255), nullable=False)
    value: str = Column(Text, default="")

    __table_args__ = (UniqueConstraint("agent", "key", name="uq_agent_config_key"),)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent": self.agent,
            "key": self.key,
            "value": self.value,
        }


class Project(Base):
    __tablename__ = "projects"

    id: str = Column(String(6), primary_key=True, default=generate_id)
    name: str = Column(String(255), nullable=False)
    path: str = Column(Text, nullable=False, unique=True)
    is_git_repo: bool = Column(Boolean, default=True)
    created_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    tasks = relationship("Task", back_populates="project", cascade="all, delete-orphan")
    flows = relationship("Flow", back_populates="project", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "is_git_repo": self.is_git_repo if self.is_git_repo is not None else True,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Task(Base):
    __tablename__ = "tasks"

    id: str = Column(String(6), primary_key=True, default=generate_id)
    project_id: str = Column(String(6), ForeignKey("projects.id"), nullable=False)
    name: str = Column(String(255), default="")
    description: str = Column(Text, default="")
    type: TaskType = Column(SQLEnum(TaskType), default=TaskType.FEATURE)
    default_flow_name: str = Column(String(255), nullable=True, default=None)
    task_status: str = Column(String(50), default="backlog")
    worktree_branch: str = Column(String(255), default="")
    created_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="tasks")
    runs = relationship("TaskRun", back_populates="task", cascade="all, delete-orphan",
                        order_by="TaskRun.created_at")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "type": self.type.value,
            "default_flow_name": self.default_flow_name,
            "task_status": self.task_status or "backlog",
            "worktree_branch": self.worktree_branch,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Flow(Base):
    __tablename__ = "flows"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_flow_project_name"),
    )

    id: str = Column(String(6), primary_key=True, default=generate_id)
    project_id: str = Column(String(6), ForeignKey("projects.id"), nullable=False)
    name: str = Column(String(255), nullable=False)
    description: str = Column(Text, default="")
    created_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                                  onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="flows")
    steps = relationship("FlowStep", back_populates="flow", cascade="all, delete-orphan",
                         order_by="FlowStep.position")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "steps": [s.to_dict() for s in self.steps],
        }


class FlowStep(Base):
    __tablename__ = "flow_steps"

    id: str = Column(String(6), primary_key=True, default=generate_id)
    flow_id: str = Column(String(6), ForeignKey("flows.id"), nullable=False)
    name: str = Column(String(255), nullable=False)
    position: int = Column(Integer, nullable=False, default=0)
    content: str = Column(Text, default="")
    gates: str = Column(Text, default="[]")
    ifs: str = Column(Text, default="[]")
    agent_alias: str = Column(String(50), default="standard")
    step_type: str = Column(String(20), default="agent")
    allow_max: bool = Column(Boolean, default=False)
    max_gate_retries: int = Column(Integer, default=5)
    created_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                                  onupdate=lambda: datetime.now(timezone.utc))

    flow = relationship("Flow", back_populates="steps")

    def get_gates(self) -> list[dict]:
        """Parse gates JSON into a list of gate dicts."""
        import json
        try:
            return json.loads(self.gates or "[]")
        except (json.JSONDecodeError, TypeError):
            return []

    def get_ifs(self) -> list[dict]:
        """Parse ifs JSON into a list of if-condition dicts."""
        import json
        try:
            return json.loads(self.ifs or "[]")
        except (json.JSONDecodeError, TypeError):
            return []

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "flow_id": self.flow_id,
            "name": self.name,
            "position": self.position,
            "content": self.content,
            "gates": self.get_gates(),
            "ifs": self.get_ifs(),
            "agent_alias": self.agent_alias or "standard",
            "step_type": self.step_type or "agent",
            "allow_max": bool(self.allow_max),
            "max_gate_retries": self.max_gate_retries if self.max_gate_retries is not None else 5,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TaskRun(Base):
    __tablename__ = "task_runs"

    id: str = Column(String(6), primary_key=True, default=generate_id)
    project_id: str = Column(String(6), ForeignKey("projects.id"), nullable=False)
    task_id: str = Column(String(6), ForeignKey("tasks.id"), nullable=False)
    flow_name: str = Column(String(255), nullable=True, default=None)
    flow_snapshot: str = Column(Text, nullable=True)
    current_step: str = Column(String(255), default="")
    outcome: str = Column(String(50), nullable=True)
    log_path: str = Column(Text, default="")
    user_prompt: str = Column(Text, default="")
    prompt: str = Column(Text, default="")
    summary: str = Column(Text, default="")
    steps_completed: str = Column(Text, default="[]")
    recovery_count: int = Column(Integer, nullable=False, default=0)
    one_shot: bool = Column(Boolean, default=False)
    paused_at: datetime = Column(DateTime, nullable=True)
    resume_prompt: str = Column(Text, default="")
    created_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at: datetime = Column(DateTime, nullable=True)
    completed_at: datetime = Column(DateTime, nullable=True)

    task = relationship("Task", back_populates="runs")
    step_runs = relationship("StepRun", back_populates="run", cascade="all, delete-orphan",
                             order_by="StepRun.step_position")

    @property
    def status(self) -> str:
        if self.completed_at:
            if self.outcome and self.outcome not in ("completed",):
                return self.outcome
            return "completed"
        if self.paused_at:
            return "paused"
        if self.started_at:
            for sr in self.step_runs:
                if sr.awaiting_user_at and not sr.completed_at:
                    return "awaiting_user"
            return "running"
        return "queued"

    @property
    def duration_seconds(self) -> float | None:
        if not self.step_runs:
            if not self.started_at:
                return None
            end = self.completed_at or datetime.now(timezone.utc)
            start = self.started_at if self.started_at.tzinfo else self.started_at.replace(tzinfo=timezone.utc)
            end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
            return (end - start).total_seconds()
        total = sum(sr.duration_seconds for sr in self.step_runs if sr.duration_seconds is not None)
        return total or None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "flow_name": self.flow_name,
            "current_step": self.current_step,
            "status": self.status,
            "outcome": self.outcome,
            "log_path": self.log_path,
            "user_prompt": self.user_prompt,
            "prompt": self.prompt,
            "summary": self.summary,
            "steps_completed": self.steps_completed,
            "recovery_count": self.recovery_count or 0,
            "one_shot": bool(self.one_shot),
            "paused_at": self.paused_at.isoformat() if self.paused_at else None,
            "resume_prompt": self.resume_prompt or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
        }


class StepRun(Base):
    __tablename__ = "step_runs"

    id: str = Column(String(6), primary_key=True, default=generate_id)
    run_id: str = Column(String(6), ForeignKey("task_runs.id"), nullable=False)
    step_name: str = Column(String(255), nullable=False)
    step_position: int = Column(Integer, nullable=False)
    flow_name: str = Column(String(255), nullable=False)
    agent: str = Column(String(50), nullable=False, default="cursor")
    model: str = Column(String(100), nullable=False, default="")
    log_path: str = Column(Text, default="")
    prompt: str = Column(Text, default="")
    outcome: str = Column(String(50), nullable=True)
    attempt: int = Column(Integer, nullable=False, default=1)
    gate_failures: str = Column(Text, default="")
    user_response: str = Column(Text, default="")
    started_at: datetime = Column(DateTime, nullable=True)
    completed_at: datetime = Column(DateTime, nullable=True)
    awaiting_user_at: datetime = Column(DateTime, nullable=True)

    run = relationship("TaskRun", back_populates="step_runs")

    @property
    def status(self) -> str:
        if self.completed_at:
            return self.outcome or "completed"
        if self.awaiting_user_at:
            return "awaiting_user"
        if self.started_at:
            return "running"
        return "pending"

    @property
    def duration_seconds(self) -> float | None:
        if not self.started_at:
            return None
        end = self.completed_at or datetime.now(timezone.utc)
        start = self.started_at if self.started_at.tzinfo else self.started_at.replace(tzinfo=timezone.utc)
        end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
        return (end - start).total_seconds()

    def to_dict(self) -> dict:
        import json as _json
        gf = []
        if self.gate_failures:
            try:
                gf = _json.loads(self.gate_failures)
            except (ValueError, TypeError):
                pass
        return {
            "id": self.id,
            "run_id": self.run_id,
            "step_name": self.step_name,
            "step_position": self.step_position,
            "flow_name": self.flow_name,
            "agent": self.agent or "cursor",
            "model": self.model,
            "log_path": self.log_path,
            "prompt": self.prompt,
            "status": self.status,
            "outcome": self.outcome,
            "attempt": self.attempt or 1,
            "gate_failures": gf,
            "user_response": self.user_response or "",
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "awaiting_user_at": self.awaiting_user_at.isoformat() if self.awaiting_user_at else None,
            "duration_seconds": self.duration_seconds,
        }
