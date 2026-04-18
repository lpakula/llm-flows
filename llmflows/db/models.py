"""SQLAlchemy models for llmflows."""

import secrets
import string
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, relationship


def generate_id() -> str:
    """Generate a 6-character alphanumeric ID."""
    chars = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(6))


class Base(DeclarativeBase):
    pass


class AgentAlias(Base):
    __tablename__ = "agent_aliases"
    __table_args__ = (
        UniqueConstraint("type", "name", name="uq_agent_alias_type_name"),
    )

    id: str = Column(String(6), primary_key=True, default=generate_id)
    name: str = Column(String(50), nullable=False)
    type: str = Column(String(20), nullable=False, default="code")
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
            "type": self.type,
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


class Space(Base):
    __tablename__ = "spaces"

    id: str = Column(String(6), primary_key=True, default=generate_id)
    name: str = Column(String(255), nullable=False)
    path: str = Column(Text, nullable=False, unique=True)
    is_git_repo: bool = Column(Boolean, default=True)
    max_concurrent_tasks: int = Column(Integer, default=1)
    inbox_completed_runs: bool = Column(Boolean, default=True)
    variables: str = Column(Text, default="{}")
    created_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    flows = relationship("Flow", back_populates="space", cascade="all, delete-orphan")
    flow_runs = relationship("FlowRun", back_populates="space", cascade="all, delete-orphan",
                             order_by="FlowRun.created_at")

    def get_variables(self) -> dict:
        """Parse variables JSON into a dict."""
        import json
        try:
            return json.loads(self.variables or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "max_concurrent_tasks": self.max_concurrent_tasks if self.max_concurrent_tasks is not None else 1,
            "variables": self.get_variables(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Flow(Base):
    __tablename__ = "flows"
    __table_args__ = (
        UniqueConstraint("space_id", "name", name="uq_flow_space_name"),
    )

    id: str = Column(String(6), primary_key=True, default=generate_id)
    space_id: str = Column(String(6), ForeignKey("spaces.id"), nullable=False)
    name: str = Column(String(255), nullable=False)
    description: str = Column(Text, default="")
    requirements: str = Column(Text, default="{}")
    variables: str = Column(Text, default="{}")
    max_concurrent_runs: int = Column(Integer, default=1)
    max_spend_usd: float = Column(Float, nullable=True)
    starred: bool = Column(Boolean, default=False)
    schedule_cron: str = Column(String(100), nullable=True)
    schedule_timezone: str = Column(String(64), nullable=True)
    schedule_next_at: datetime = Column(DateTime, nullable=True)
    schedule_enabled: bool = Column(Boolean, default=False)
    created_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                                  onupdate=lambda: datetime.now(timezone.utc))

    space = relationship("Space", back_populates="flows")
    steps = relationship("FlowStep", back_populates="flow", cascade="all, delete-orphan",
                         order_by="FlowStep.position")

    def get_requirements(self) -> dict:
        import json
        try:
            raw = json.loads(self.requirements or "{}")
        except (json.JSONDecodeError, TypeError):
            raw = {}
        return {
            "tools": raw.get("tools", []),
        }

    def get_variables(self) -> dict:
        import json
        try:
            return json.loads(self.variables or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "space_id": self.space_id,
            "name": self.name,
            "description": self.description,
            "requirements": self.get_requirements(),
            "variables": self.get_variables(),
            "max_concurrent_runs": self.max_concurrent_runs if self.max_concurrent_runs is not None else 1,
            "max_spend_usd": self.max_spend_usd,
            "starred": bool(self.starred),
            "schedule_cron": self.schedule_cron,
            "schedule_timezone": self.schedule_timezone or "UTC",
            "schedule_next_at": self.schedule_next_at.isoformat() if self.schedule_next_at else None,
            "schedule_enabled": bool(self.schedule_enabled),
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
    agent_alias: str = Column(String(50), default="normal")
    step_type: str = Column(String(20), default="agent")
    allow_max: bool = Column(Boolean, default=False)
    max_gate_retries: int = Column(Integer, default=5)
    skills: str = Column(Text, default="[]")
    tools: str = Column(Text, default="[]")
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

    def get_skills(self) -> list[str]:
        """Parse skills JSON into a list of skill names."""
        import json
        try:
            return json.loads(self.skills or "[]")
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
            "agent_alias": self.agent_alias or "normal",
            "step_type": self.step_type or "code",
            "allow_max": bool(self.allow_max),
            "max_gate_retries": self.max_gate_retries if self.max_gate_retries is not None else 5,
            "skills": self.get_skills(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class FlowRun(Base):
    __tablename__ = "flow_runs"

    id: str = Column(String(6), primary_key=True, default=generate_id)
    space_id: str = Column(String(6), ForeignKey("spaces.id"), nullable=False)
    flow_id: str = Column(String(6), ForeignKey("flows.id"), nullable=True)
    flow_snapshot: str = Column(Text, nullable=True)
    current_step: str = Column(String(255), default="")
    outcome: str = Column(String(50), nullable=True)
    log_path: str = Column(Text, default="")
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

    space = relationship("Space", back_populates="flow_runs")
    flow = relationship("Flow")
    step_runs = relationship("StepRun", back_populates="run", cascade="all, delete-orphan",
                             order_by="StepRun.step_position")

    @property
    def flow_name(self) -> str | None:
        """Derive flow name from the related Flow object."""
        if self.flow:
            return self.flow.name
        if self.flow_snapshot:
            import json
            try:
                snap = json.loads(self.flow_snapshot)
                return snap.get("name")
            except (json.JSONDecodeError, TypeError):
                pass
        return None

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

    @property
    def cost_usd(self) -> float | None:
        if not self.step_runs:
            return None
        total = sum(sr.cost_usd for sr in self.step_runs if sr.cost_usd is not None)
        return round(total, 6) if total else None

    @property
    def token_count(self) -> int | None:
        if not self.step_runs:
            return None
        total = sum(sr.token_count for sr in self.step_runs if sr.token_count is not None)
        return total or None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "space_id": self.space_id,
            "flow_id": self.flow_id,
            "flow_name": self.flow_name,
            "current_step": self.current_step,
            "status": self.status,
            "outcome": self.outcome,
            "log_path": self.log_path,
            "prompt": self.prompt,
            "summary": self.summary,
            "steps_completed": self.steps_completed,
            "recovery_count": self.recovery_count or 0,
            "paused_at": self.paused_at.isoformat() if self.paused_at else None,
            "resume_prompt": self.resume_prompt or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "cost_usd": self.cost_usd,
            "token_count": self.token_count,
        }


class InboxItem(Base):
    __tablename__ = "inbox_items"

    id: str = Column(String(6), primary_key=True, default=generate_id)
    type: str = Column(String(32), nullable=False)
    reference_id: str = Column(String(6), nullable=False)
    space_id: str = Column(String(6), ForeignKey("spaces.id"), nullable=False)
    title: str = Column(Text, default="")
    created_at: datetime = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    archived_at: datetime = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "reference_id": self.reference_id,
            "space_id": self.space_id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
        }


class StepRun(Base):
    __tablename__ = "step_runs"

    id: str = Column(String(6), primary_key=True, default=generate_id)
    flow_run_id: str = Column(String(6), ForeignKey("flow_runs.id"), nullable=False)
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
    cost_usd: float = Column(Float, nullable=True)
    token_count: int = Column(Integer, nullable=True)
    started_at: datetime = Column(DateTime, nullable=True)
    completed_at: datetime = Column(DateTime, nullable=True)
    awaiting_user_at: datetime = Column(DateTime, nullable=True)

    run = relationship("FlowRun", back_populates="step_runs")

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
        end = self.completed_at or (self.run and self.run.completed_at) or datetime.now(timezone.utc)
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
            "run_id": self.flow_run_id,
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
            "cost_usd": self.cost_usd,
            "token_count": self.token_count,
        }
