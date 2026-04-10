"""Run service -- manages TaskRun and StepRun lifecycle."""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from ..db.models import Project, StepRun, Task, TaskRun


class RunService:
    def __init__(self, session: Session):
        self.session = session

    def enqueue(self, project_id: str, task_id: str,
                flow_name: Optional[str] = None,
                user_prompt: str = "",
                one_shot: bool = False) -> TaskRun:
        """Create a TaskRun in the queue.

        flow_name is the flow to use (None = prompt-only run).
        user_prompt falls back to task.description when not provided.
        """
        task = self.session.query(Task).filter_by(id=task_id).first()
        if not task:
            raise ValueError(f"Task '{task_id}' not found")

        run = TaskRun(
            project_id=project_id,
            task_id=task_id,
            flow_name=flow_name,
            user_prompt=user_prompt or task.description or "",
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

    def pause(self, run_id: str) -> Optional[TaskRun]:
        """Pause an active run."""
        run = self.session.query(TaskRun).filter_by(id=run_id).first()
        if not run or run.completed_at:
            return None
        run.paused_at = datetime.now(timezone.utc)
        self.session.commit()
        return run

    def resume(self, run_id: str, prompt: str = "") -> Optional[TaskRun]:
        """Resume a paused run, optionally with an additional prompt."""
        run = self.session.query(TaskRun).filter_by(id=run_id).first()
        if not run or not run.paused_at:
            return None
        run.paused_at = None
        if prompt:
            run.resume_prompt = prompt
        self.session.commit()
        return run

    def retry_step(self, run_id: str, step_name: str, prompt: str = "") -> Optional[TaskRun]:
        """Re-activate an interrupted run and re-launch a step from scratch.

        Deletes all StepRuns at or after the retried step's position, and cleans
        up the corresponding artifact directories so the daemon starts clean.
        This prevents stale downstream StepRuns from confusing the daemon.
        """
        run = self.session.query(TaskRun).filter_by(id=run_id).first()
        if not run:
            return None

        # Find the position of the step being retried
        pivot_step = self.session.query(StepRun).filter_by(
            run_id=run_id, step_name=step_name,
        ).order_by(StepRun.step_position).first()
        pivot_position = pivot_step.step_position if pivot_step else 0

        # Delete all StepRuns at or after this position (retried step + all downstream)
        steps_to_delete = self.session.query(StepRun).filter(
            StepRun.run_id == run_id,
            StepRun.step_position >= pivot_position,
        ).all()

        if steps_to_delete and run.task and run.task.project:
            from .context import ContextService
            artifacts_dir = ContextService.get_artifacts_dir(
                Path(run.task.project.path), run.task_id, run_id,
            )
            for sr in steps_to_delete:
                step_artifact_dir = artifacts_dir / f"{sr.step_position:02d}-{sr.step_name}"
                if step_artifact_dir.exists():
                    shutil.rmtree(step_artifact_dir, ignore_errors=True)

        for sr in steps_to_delete:
            self.session.delete(sr)

        run.completed_at = None
        run.outcome = None
        run.current_step = step_name
        run.resume_prompt = prompt if prompt else ""
        self.session.commit()
        return run

    def complete_step_manually(self, step_run_id: str) -> Optional[StepRun]:
        """Manually mark a step as completed (e.g. after a manual fix)."""
        sr = self.session.query(StepRun).filter_by(id=step_run_id).first()
        if not sr:
            return None
        sr.completed_at = datetime.now(timezone.utc)
        sr.outcome = "manual"
        self.session.commit()
        return sr

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

    # ── Human step support ─────────────────────────────────────────────────────

    def mark_awaiting_user(self, step_run_id: str) -> Optional[StepRun]:
        """Transition a step to awaiting_user state (agent finished, waiting for human)."""
        sr = self.session.query(StepRun).filter_by(id=step_run_id).first()
        if not sr:
            return None
        sr.awaiting_user_at = datetime.now(timezone.utc)
        self.session.commit()
        return sr

    def respond_to_step(self, step_run_id: str, response: str = "") -> Optional[StepRun]:
        """User responds to an awaiting_user step, completing it."""
        sr = self.session.query(StepRun).filter_by(id=step_run_id).first()
        if not sr or not sr.awaiting_user_at:
            return None
        sr.user_response = response
        sr.completed_at = datetime.now(timezone.utc)
        sr.outcome = "completed"
        self.session.commit()
        return sr

    def list_awaiting_user(self) -> list[dict]:
        """Return all steps awaiting user action, with task/project context."""
        from .context import ContextService

        rows = (
            self.session.query(StepRun, TaskRun, Task, Project)
            .join(TaskRun, StepRun.run_id == TaskRun.id)
            .join(Task, TaskRun.task_id == Task.id)
            .join(Project, TaskRun.project_id == Project.id)
            .filter(StepRun.awaiting_user_at.isnot(None))
            .filter(StepRun.completed_at.is_(None))
            .order_by(StepRun.awaiting_user_at)
            .all()
        )
        results = []
        for sr, run, task, project in rows:
            step_type = "agent"
            if run.flow_snapshot:
                try:
                    snap = json.loads(run.flow_snapshot)
                    for s in snap.get("steps", []):
                        if s["name"] == sr.step_name:
                            step_type = s.get("step_type", "agent")
                            break
                except (ValueError, KeyError, TypeError):
                    pass

            user_message = ""
            try:
                artifacts_dir = ContextService.get_artifacts_dir(
                    Path(project.path), task.id, run.id,
                )
                result_file = artifacts_dir / f"{sr.step_position:02d}-{sr.step_name}" / "_result.md"
                if result_file.exists():
                    user_message = result_file.read_text().strip()
            except (PermissionError, OSError):
                pass

            results.append({
                "step_run_id": sr.id,
                "step_name": sr.step_name,
                "step_type": step_type,
                "step_position": sr.step_position,
                "task_id": task.id,
                "task_name": task.name or task.description[:60] if task.description else "",
                "project_id": project.id,
                "project_name": project.name,
                "run_id": run.id,
                "flow_name": sr.flow_name,
                "prompt": sr.prompt or "",
                "user_message": user_message,
                "log_path": sr.log_path or "",
                "awaiting_since": sr.awaiting_user_at.isoformat() if sr.awaiting_user_at else None,
            })
        return results

    def get_latest_step_run(self, run_id: str, step_name: str) -> Optional[StepRun]:
        """Get the most recent StepRun for a given step name in a run."""
        return (
            self.session.query(StepRun)
            .filter_by(run_id=run_id, step_name=step_name)
            .order_by(StepRun.started_at.desc())
            .first()
        )
