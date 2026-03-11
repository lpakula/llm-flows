"""Run service -- manages TaskRun lifecycle (queue + execution history)."""

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..db.models import Task, TaskRun


class RunService:
    def __init__(self, session: Session):
        self.session = session

    def enqueue(self, project_id: str, task_id: str, flow_name: str = "default",
                user_prompt: str = "", flow_chain: Optional[list[str]] = None,
                model: str = "", agent: str = "cursor") -> TaskRun:
        """Create a TaskRun in the queue.

        flow_chain is an ordered list of flows to execute in sequence within a single run.
        flow_name is set to the first flow in the chain (or flow_name if chain is empty).
        user_prompt falls back to task.description when not provided.
        model is the LLM model to use for this run.
        agent is the agent backend to use (cursor, claude-code, codex).
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

    def get_next_flow_in_chain(self, task_id: str) -> Optional[str]:
        """Return the next flow after the current one in the chain, or None if done."""
        run = self.get_active(task_id)
        if not run:
            return None
        try:
            chain = json.loads(run.flow_chain or "[]")
        except (json.JSONDecodeError, TypeError):
            chain = []
        if not chain or run.flow_name not in chain:
            return None
        idx = chain.index(run.flow_name)
        return chain[idx + 1] if idx + 1 < len(chain) else None

    def advance_to_next_flow(self, task_id: str, next_flow: str) -> Optional[TaskRun]:
        """Switch the active run to the next flow in the chain."""
        run = self.get_active(task_id)
        if not run:
            return None
        run.flow_name = next_flow
        run.current_step = None
        self.session.commit()
        return run

    def update_step(self, task_id: str, step_name: str) -> Optional[TaskRun]:
        """Update current_step on the active run and append to steps_completed."""
        run = self.get_active(task_id)
        if not run:
            return None

        run.current_step = step_name

        try:
            completed = json.loads(run.steps_completed or "[]")
        except (json.JSONDecodeError, TypeError):
            completed = []
        if step_name not in completed:
            completed.append(step_name)
        run.steps_completed = json.dumps(completed)

        self.session.commit()
        return run

    def mark_completed(
        self, run_id: str, outcome: str = "completed", steps_completed: Optional[list[str]] = None,
    ) -> Optional[TaskRun]:
        """Set completed_at and outcome on the run, clear current_step."""
        run = self.session.query(TaskRun).filter_by(id=run_id).first()
        if not run:
            return None

        run.completed_at = datetime.now(timezone.utc)
        run.outcome = outcome
        run.current_step = None

        if steps_completed:
            run.steps_completed = json.dumps(steps_completed)

        self.session.commit()
        return run

    def set_log_path(self, run_id: str, log_path: str) -> Optional[TaskRun]:
        """Store the log file path on the run."""
        run = self.session.query(TaskRun).filter_by(id=run_id).first()
        if not run:
            return None
        run.log_path = log_path
        self.session.commit()
        return run

    def set_prompt(self, run_id: str, prompt: str) -> Optional[TaskRun]:
        """Store the rendered prompt on the run."""
        run = self.session.query(TaskRun).filter_by(id=run_id).first()
        if not run:
            return None
        run.prompt = prompt
        self.session.commit()
        return run

    def set_summary(self, task_id: str, summary: str,
                    run_id: Optional[str] = None) -> Optional[TaskRun]:
        """Set the summary on a run and mark it as completed.

        Sets completed_at so the run is properly finalized regardless of
        whether a daemon is monitoring (inline --start mode needs this).
        Prefers run_id when provided (avoids race condition with mark_completed).
        Falls back to get_active(task_id) for backward compatibility.
        """
        if run_id:
            run = self.session.query(TaskRun).filter_by(id=run_id).first()
        else:
            run = self.get_active(task_id)
        if not run:
            return None
        run.summary = summary
        run.outcome = "completed"
        if not run.completed_at:
            run.completed_at = datetime.now(timezone.utc)
        self.session.commit()
        return run

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
