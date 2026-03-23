"""SQLAlchemy models for llmflows."""

import secrets
import string
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Integer, String, Text
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


class Project(Base):
    __tablename__ = "projects"

    id: str = Column(String(6), primary_key=True, default=generate_id)
    name: str = Column(String(255), nullable=False)
    path: str = Column(Text, nullable=False, unique=True)
    integrations: str = Column(Text, default="{}")
    default_model: str = Column(String(100), default="auto")
    default_agent: str = Column(String(50), default="cursor")
    default_flow_chain: str = Column(Text, default='["default"]')
    aliases: str = Column(Text, default="{}")
    created_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    tasks = relationship("Task", back_populates="project", cascade="all, delete-orphan")
    integrations_rel = relationship("Integration", back_populates="project",
                                    cascade="all, delete-orphan")
    settings = relationship("ProjectSettings", back_populates="project",
                            uselist=False, cascade="all, delete-orphan")

    def _parse_flow_chain(self) -> list[str]:
        import json
        try:
            return json.loads(self.default_flow_chain or '["default"]')
        except (json.JSONDecodeError, TypeError):
            return ["default"]

    def get_aliases(self) -> dict:
        """Return all aliases, ensuring 'default' always exists.

        Migrates from legacy default_model/default_agent/default_flow_chain
        columns if 'default' is not yet present in the aliases dict.
        """
        import json
        try:
            result = json.loads(self.aliases or "{}")
        except (json.JSONDecodeError, TypeError):
            result = {}
        if "default" not in result:
            result["default"] = {
                "agent": self.default_agent or "cursor",
                "model": self.default_model or "auto",
                "flow_chain": self._parse_flow_chain(),
            }
        return result

    def get_alias(self, name: str) -> dict | None:
        return self.get_aliases().get(name)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "aliases": self.get_aliases(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Integration(Base):
    __tablename__ = "integrations"

    id: str = Column(String(6), primary_key=True, default=generate_id)
    project_id: str = Column(String(6), ForeignKey("projects.id"), nullable=False)
    provider: str = Column(String(50), nullable=False)
    enabled: bool = Column(Boolean, default=True)
    config: str = Column(Text, default="{}")
    last_polled_at: datetime = Column(DateTime, nullable=True)
    created_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                                  onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="integrations_rel")
    tasks = relationship("Task", back_populates="integration")

    def get_config(self) -> dict:
        import json
        try:
            return json.loads(self.config or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "provider": self.provider,
            "enabled": self.enabled,
            "config": self.get_config(),
            "last_polled_at": self.last_polled_at.isoformat() if self.last_polled_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ProjectSettings(Base):
    __tablename__ = "project_settings"

    id: str = Column(String(6), primary_key=True, default=generate_id)
    project_id: str = Column(String(6), ForeignKey("projects.id"), nullable=False, unique=True)
    # When False the daemon runs the agent in the project root without creating a worktree.
    # Useful for orchestrator/manager repos whose flows trigger changes in other repos.
    worktree_enabled: bool = Column(Boolean, default=True)
    created_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                                  onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="settings")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "worktree_enabled": self.worktree_enabled if self.worktree_enabled is not None else True,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Task(Base):
    __tablename__ = "tasks"

    id: str = Column(String(6), primary_key=True, default=generate_id)
    project_id: str = Column(String(6), ForeignKey("projects.id"), nullable=False)
    integration_id: str = Column(String(6), ForeignKey("integrations.id"), nullable=True)
    name: str = Column(String(255), default="")
    description: str = Column(Text, default="")
    type: TaskType = Column(SQLEnum(TaskType), default=TaskType.FEATURE)
    worktree_branch: str = Column(String(255), default="")
    github_issue_number: int = Column(Integer, nullable=True)
    github_comment_id: int = Column(Integer, nullable=True)
    created_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="tasks")
    integration = relationship("Integration", back_populates="tasks")
    runs = relationship("TaskRun", back_populates="task", cascade="all, delete-orphan",
                        order_by="TaskRun.created_at")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "integration_id": self.integration_id,
            "name": self.name,
            "description": self.description,
            "type": self.type.value,
            "worktree_branch": self.worktree_branch,
            "github_issue_number": self.github_issue_number,
            "github_comment_id": self.github_comment_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Flow(Base):
    __tablename__ = "flows"

    id: str = Column(String(6), primary_key=True, default=generate_id)
    name: str = Column(String(255), nullable=False, unique=True)
    description: str = Column(Text, default="")
    created_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                                  onupdate=lambda: datetime.now(timezone.utc))

    steps = relationship("FlowStep", back_populates="flow", cascade="all, delete-orphan",
                         order_by="FlowStep.position")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
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
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TaskRun(Base):
    __tablename__ = "task_runs"

    id: str = Column(String(6), primary_key=True, default=generate_id)
    project_id: str = Column(String(6), ForeignKey("projects.id"), nullable=False)
    task_id: str = Column(String(6), ForeignKey("tasks.id"), nullable=False)
    flow_name: str = Column(String(255), nullable=False, default="default")
    flow_chain: str = Column(Text, default="[]")
    model: str = Column(String(100), nullable=False, default="")
    agent: str = Column(String(50), nullable=False, default="cursor")
    current_step: str = Column(String(255), default="")
    outcome: str = Column(String(50), nullable=True)
    log_path: str = Column(Text, default="")
    user_prompt: str = Column(Text, default="")
    prompt: str = Column(Text, default="")
    summary: str = Column(Text, default="")
    steps_completed: str = Column(Text, default="[]")
    created_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at: datetime = Column(DateTime, nullable=True)
    completed_at: datetime = Column(DateTime, nullable=True)

    task = relationship("Task", back_populates="runs")

    @property
    def status(self) -> str:
        if self.completed_at:
            return "completed"
        if self.started_at:
            return "running"
        return "queued"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "flow_name": self.flow_name,
            "flow_chain": self.flow_chain,
            "model": self.model,
            "agent": self.agent or "cursor",
            "current_step": self.current_step,
            "status": self.status,
            "outcome": self.outcome,
            "log_path": self.log_path,
            "user_prompt": self.user_prompt,
            "prompt": self.prompt,
            "summary": self.summary,
            "steps_completed": self.steps_completed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
