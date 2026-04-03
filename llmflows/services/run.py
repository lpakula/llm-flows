"""Run service -- manages TaskRun and StepRun lifecycle."""

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..db.models import StepRun, Task, TaskRun


class RunService:
    def __init__(self, session: Session):
        self.session = session

    def enqueue(self, project_id: str, task_id: str, flow_name: str = "default",
                user_prompt: str = "", flow_chain: Optional[list[str]] = None,
                model: str = "", agent: str = "cursor",
                step_overrides: Optional[dict] = None,
                one_shot: bool = False) -> TaskRun:
        """Create a TaskRun in the queue.

        flow_chain is an ordered list of flows to execute in sequence within a single run.
        flow_name is set to the first flow in the chain (or flow_name if chain is empty).
        user_prompt falls back to task.description when not provided.
        step_overrides is a dict keyed by "flow/step" with {"agent": ..., "model": ...}.
        """
        task = self.session.query(Task).filter_by(id=task_id).first()
        if not task:
            raise ValueError(f"Task '{task_id}' not found")

        chain = flow_chain or [flow_name]
        active_flow = chain[0] if chain else flow_name

        run = TaskRun(
            project_id=project_id,
            task_id=task_id,
            flow_name=active_flow,
            flow_chain=json.dumps(chain),
            model=model,
            agent=agent,
            user_prompt=user_prompt or task.description or "",
            step_overrides=json.dumps(step_overrides or {}),
            one_shot=one_shot,
        )
        self.session.add(run)
        self.session.commit()
        return run

    def get_pending(self, project_id: str) -> Optional[TaskRun]:
        """Return the oldest TaskRun with no started_at (daemon picks this up)."""
        return (
            self.session.query(TaskRun)
            .filter_by(project_id=project_id)
            .filter(TaskRun.started_at.is_(None))
            .filter(TaskRun.completed_at.is_(None))
            .order_by(TaskRun.created_at)
            .first()
        )

    def mark_started(self, run_id: str) -> Optional[TaskRun]:
        """Set started_at on the run."""
        run = self.session.query(TaskRun).filter_by(id=run_id).first()
        if not run:
            return None
        run.started_at = datetime.now(timezone.utc)
        self.session.commit()
        return run

    def mark_completed(
        self, run_id: str, outcome: str = "completed",
        summary: str = "",
    ) -> Optional[TaskRun]:
        """Set completed_at and outcome on the run."""
        run = self.session.query(TaskRun).filter_by(id=run_id).first()
        if not run:
            return None

        run.completed_at = datetime.now(timezone.utc)
        run.outcome = outcome
        if summary:
            run.summary = summary

        self.session.commit()
        return run

    def update_run_step(self, run_id: str, step_name: str, flow_name: str = "") -> Optional[TaskRun]:
        """Update current_step/flow_name on a run (called by daemon during orchestration)."""
        run = self.session.query(TaskRun).filter_by(id=run_id).first()
        if not run:
            return None
        run.current_step = step_name
        if flow_name:
            run.flow_name = flow_name

        try:
            completed = json.loads(run.steps_completed or "[]")
        except (json.JSONDecodeError, TypeError):
            completed = []
        if step_name not in completed:
            completed.append(step_name)
        run.steps_completed = json.dumps(completed)

        self.session.commit()
        return run

    # ── StepRun CRUD ──────────────────────────────────────────────────────────

    def create_step_run(
        self, run_id: str, step_name: str, step_position: int,
        flow_name: str, agent: str = "cursor", model: str = "",
    ) -> StepRun:
        """Create a new StepRun and mark it started."""
        step_run = StepRun(
            run_id=run_id,
            step_name=step_name,
            step_position=step_position,
            flow_name=flow_name,
            agent=agent,
            model=model,
            started_at=datetime.now(timezone.utc),
        )
        self.session.add(step_run)
        self.session.commit()
        return step_run

    def mark_step_completed(
        self, step_run_id: str, outcome: str = "completed",
    ) -> Optional[StepRun]:
        """Mark a StepRun as completed."""
        sr = self.session.query(StepRun).filter_by(id=step_run_id).first()
        if not sr:
            return None
        sr.completed_at = datetime.now(timezone.utc)
        sr.outcome = outcome
        self.session.commit()
        return sr

    def set_step_log_path(self, step_run_id: str, log_path: str) -> Optional[StepRun]:
        """Store the log file path on a StepRun."""
        sr = self.session.query(StepRun).filter_by(id=step_run_id).first()
        if not sr:
            return None
        sr.log_path = log_path
        self.session.commit()
        return sr

    def set_step_prompt(self, step_run_id: str, prompt: str) -> Optional[StepRun]:
        """Store the rendered prompt on a StepRun."""
        sr = self.session.query(StepRun).filter_by(id=step_run_id).first()
        if not sr:
            return None
        sr.prompt = prompt
        self.session.commit()
        return sr

    def get_active_step(self, run_id: str) -> Optional[StepRun]:
        """Get the currently running StepRun for a TaskRun."""
        return (
            self.session.query(StepRun)
            .filter_by(run_id=run_id)
            .filter(StepRun.started_at.isnot(None))
            .filter(StepRun.completed_at.is_(None))
            .order_by(StepRun.started_at.desc())
            .first()
        )

    def list_step_runs(self, run_id: str) -> list[StepRun]:
        """All StepRuns for a TaskRun, ordered by position."""
        return (
            self.session.query(StepRun)
            .filter_by(run_id=run_id)
            .order_by(StepRun.step_position, StepRun.started_at)
            .all()
        )

    def get_step_run(self, step_run_id: str) -> Optional[StepRun]:
        """Get a StepRun by ID."""
        return self.session.query(StepRun).filter_by(id=step_run_id).first()

    def get_active(self, task_id: str) -> Optional[TaskRun]:
        """Get the current active run (no completed_at)."""
        return (
            self.session.query(TaskRun)
            .filter_by(task_id=task_id)
            .filter(TaskRun.completed_at.is_(None))
            .order_by(TaskRun.created_at.desc())
            .first()
        )

    def get_active_by_project(self, project_id: str) -> list[TaskRun]:
        """All active runs for a project (started but not completed)."""
        return (
            self.session.query(TaskRun)
            .filter_by(project_id=project_id)
            .filter(TaskRun.completed_at.is_(None))
            .filter(TaskRun.started_at.isnot(None))
            .order_by(TaskRun.created_at)
            .all()
        )

    def get_history(self, task_id: str) -> list[TaskRun]:
        """All completed runs for a task (execution memory)."""
        return (
            self.session.query(TaskRun)
            .filter_by(task_id=task_id)
            .filter(TaskRun.completed_at.isnot(None))
            .order_by(TaskRun.created_at)
            .all()
        )

    def list_by_task(self, task_id: str) -> list[TaskRun]:
        """All runs for a task, newest first."""
        return (
            self.session.query(TaskRun)
            .filter_by(task_id=task_id)
            .order_by(TaskRun.created_at.desc())
            .all()
        )

    def list_by_project(self, project_id: str) -> list[TaskRun]:
        """All runs for a project (active + history)."""
        return (
            self.session.query(TaskRun)
            .filter_by(project_id=project_id)
            .order_by(TaskRun.created_at)
            .all()
        )

    def list_active(self) -> list[TaskRun]:
        """All runs globally that are not completed, executing first."""
        return (
            self.session.query(TaskRun)
            .filter(TaskRun.completed_at.is_(None))
            .order_by(TaskRun.started_at.desc().nullslast(), TaskRun.created_at)
            .all()
        )

    def get(self, run_id: str) -> Optional[TaskRun]:
        """Get a run by ID."""
        return self.session.query(TaskRun).filter_by(id=run_id).first()
