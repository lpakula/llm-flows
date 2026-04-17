"""Run service -- manages FlowRun and StepRun lifecycle."""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from ..db.models import FlowRun, InboxItem, Space, StepRun


class RunService:
    def __init__(self, session: Session):
        self.session = session

    def enqueue(self, space_id: str, flow_id: str) -> FlowRun:
        """Create a FlowRun in the queue."""
        run = FlowRun(
            space_id=space_id,
            flow_id=flow_id,
        )
        self.session.add(run)
        self.session.commit()
        return run

    def get_pending(self, space_id: str) -> Optional[FlowRun]:
        """Return the oldest FlowRun with no started_at (daemon picks this up)."""
        return (
            self.session.query(FlowRun)
            .filter_by(space_id=space_id)
            .filter(FlowRun.started_at.is_(None))
            .filter(FlowRun.completed_at.is_(None))
            .order_by(FlowRun.created_at)
            .first()
        )

    def get_all_pending(self, space_id: str) -> list[FlowRun]:
        """Return all pending FlowRuns for a space, oldest first."""
        return (
            self.session.query(FlowRun)
            .filter_by(space_id=space_id)
            .filter(FlowRun.started_at.is_(None))
            .filter(FlowRun.completed_at.is_(None))
            .order_by(FlowRun.created_at)
            .all()
        )

    def mark_started(self, run_id: str) -> Optional[FlowRun]:
        """Set started_at on the run."""
        run = self.session.query(FlowRun).filter_by(id=run_id).first()
        if not run:
            return None
        run.started_at = datetime.now(timezone.utc)
        self.session.commit()
        return run

    def mark_completed(
        self, run_id: str, outcome: str = "completed",
        summary: str = "",
    ) -> Optional[FlowRun]:
        """Set completed_at and outcome on the run."""
        run = self.session.query(FlowRun).filter_by(id=run_id).first()
        if not run:
            return None

        run.completed_at = datetime.now(timezone.utc)
        run.outcome = outcome
        if summary:
            run.summary = summary

        self.session.commit()
        return run

    def pause(self, run_id: str) -> Optional[FlowRun]:
        """Pause an active run."""
        run = self.session.query(FlowRun).filter_by(id=run_id).first()
        if not run or run.completed_at:
            return None
        run.paused_at = datetime.now(timezone.utc)
        self.session.commit()
        return run

    def resume(self, run_id: str, prompt: str = "") -> Optional[FlowRun]:
        """Resume a paused run, optionally with an additional prompt."""
        run = self.session.query(FlowRun).filter_by(id=run_id).first()
        if not run or not run.paused_at:
            return None
        run.paused_at = None
        if prompt:
            run.resume_prompt = prompt
        self.session.commit()
        return run

    def retry_step(self, run_id: str, step_name: str) -> Optional[FlowRun]:
        """Re-activate an interrupted run and re-launch a step from scratch.

        Deletes all StepRuns at or after the retried step's position, and cleans
        up the corresponding artifact directories so the daemon starts clean.
        """
        run = self.session.query(FlowRun).filter_by(id=run_id).first()
        if not run:
            return None

        pivot_step = self.session.query(StepRun).filter_by(
            flow_run_id=run_id, step_name=step_name,
        ).order_by(StepRun.step_position).first()
        pivot_position = pivot_step.step_position if pivot_step else 0

        steps_to_delete = self.session.query(StepRun).filter(
            StepRun.flow_run_id == run_id,
            StepRun.step_position >= pivot_position,
        ).all()

        if steps_to_delete and run.space:
            from .context import ContextService
            artifacts_dir = ContextService.get_artifacts_dir(
                Path(run.space.path), run_id, run.flow_name or "",
            )
            for sr in steps_to_delete:
                step_artifact_dir = artifacts_dir / ContextService.step_dir_name(sr.step_position, sr.step_name)
                if step_artifact_dir.exists():
                    shutil.rmtree(step_artifact_dir, ignore_errors=True)

        for sr in steps_to_delete:
            self.session.delete(sr)

        run.completed_at = None
        run.outcome = None
        run.current_step = step_name
        run.resume_prompt = ""
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

    def update_run_step(self, run_id: str, step_name: str, flow_name: str = "") -> Optional[FlowRun]:
        """Update current_step on a run (called by daemon during orchestration)."""
        run = self.session.query(FlowRun).filter_by(id=run_id).first()
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

    # ── StepRun CRUD ──────────────────────────────────────────────────────────

    def create_step_run(
        self, run_id: str, step_name: str, step_position: int,
        flow_name: str, agent: str = "cursor", model: str = "",
    ) -> StepRun:
        """Create a new StepRun and mark it started."""
        step_run = StepRun(
            flow_run_id=run_id,
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
        cost_usd: float | None = None, token_count: int | None = None,
    ) -> Optional[StepRun]:
        """Mark a StepRun as completed."""
        sr = self.session.query(StepRun).filter_by(id=step_run_id).first()
        if not sr:
            return None
        sr.completed_at = datetime.now(timezone.utc)
        sr.outcome = outcome
        if cost_usd is not None:
            sr.cost_usd = cost_usd
        if token_count is not None:
            sr.token_count = token_count
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
        """Get the currently running StepRun for a FlowRun."""
        return (
            self.session.query(StepRun)
            .filter_by(flow_run_id=run_id)
            .filter(StepRun.started_at.isnot(None))
            .filter(StepRun.completed_at.is_(None))
            .order_by(StepRun.started_at.desc())
            .first()
        )

    def list_step_runs(self, run_id: str) -> list[StepRun]:
        """All StepRuns for a FlowRun, ordered by position."""
        return (
            self.session.query(StepRun)
            .filter_by(flow_run_id=run_id)
            .order_by(StepRun.step_position, StepRun.started_at)
            .all()
        )

    def get_step_run(self, step_run_id: str) -> Optional[StepRun]:
        """Get a StepRun by ID."""
        return self.session.query(StepRun).filter_by(id=step_run_id).first()

    def get_active_by_space(self, space_id: str) -> list[FlowRun]:
        """All active runs for a space (started but not completed)."""
        return (
            self.session.query(FlowRun)
            .filter_by(space_id=space_id)
            .filter(FlowRun.completed_at.is_(None))
            .filter(FlowRun.started_at.isnot(None))
            .order_by(FlowRun.created_at)
            .all()
        )

    def list_by_space(self, space_id: str) -> list[FlowRun]:
        """All runs for a space (active + history)."""
        return (
            self.session.query(FlowRun)
            .filter_by(space_id=space_id)
            .order_by(FlowRun.created_at)
            .all()
        )

    def list_active(self) -> list[FlowRun]:
        """All runs globally that are not completed, executing first."""
        return (
            self.session.query(FlowRun)
            .filter(FlowRun.completed_at.is_(None))
            .order_by(FlowRun.started_at.desc().nullslast(), FlowRun.created_at)
            .all()
        )

    def get(self, run_id: str) -> Optional[FlowRun]:
        """Get a run by ID."""
        return self.session.query(FlowRun).filter_by(id=run_id).first()

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
        self.archive_inbox_by_reference(step_run_id)
        self.session.commit()
        return sr

    def list_awaiting_user(self) -> list[dict]:
        """Return all steps awaiting user action, with space context."""
        from .context import ContextService

        rows = (
            self.session.query(StepRun, FlowRun, Space)
            .join(FlowRun, StepRun.flow_run_id == FlowRun.id)
            .join(Space, FlowRun.space_id == Space.id)
            .filter(StepRun.awaiting_user_at.isnot(None))
            .filter(StepRun.completed_at.is_(None))
            .order_by(StepRun.awaiting_user_at)
            .all()
        )
        results = []
        for sr, run, space in rows:
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
                    Path(space.path), run.id, run.flow_name or "",
                )
                result_file = artifacts_dir / ContextService.step_dir_name(sr.step_position, sr.step_name) / "_result.md"
                if result_file.exists():
                    user_message = result_file.read_text().strip()
            except (PermissionError, OSError):
                pass

            results.append({
                "step_run_id": sr.id,
                "step_name": sr.step_name,
                "step_type": step_type,
                "step_position": sr.step_position,
                "space_id": space.id,
                "space_name": space.name,
                "run_id": run.id,
                "flow_name": run.flow_name or "",
                "prompt": sr.prompt or "",
                "user_message": user_message,
                "log_path": sr.log_path or "",
                "awaiting_since": (sr.awaiting_user_at.isoformat() + "Z") if sr.awaiting_user_at else None,
            })
        return results

    def list_completed_for_inbox(self) -> list[dict]:
        """Return recently completed runs with summaries."""
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        rows = (
            self.session.query(FlowRun, Space)
            .join(Space, FlowRun.space_id == Space.id)
            .filter(FlowRun.completed_at.isnot(None))
            .filter(FlowRun.completed_at >= cutoff)
            .filter(FlowRun.summary.isnot(None))
            .filter(FlowRun.summary != "")
            .order_by(FlowRun.completed_at.desc())
            .all()
        )
        return [
            {
                "run_id": run.id,
                "space_id": space.id,
                "space_name": space.name,
                "flow_name": run.flow_name or "",
                "outcome": run.outcome or "",
                "summary": run.summary or "",
                "duration_seconds": run.duration_seconds,
                "completed_at": (run.completed_at.isoformat() + "Z") if run.completed_at else None,
            }
            for run, space in rows
        ]

    def get_latest_step_run(self, run_id: str, step_name: str) -> Optional[StepRun]:
        """Get the most recent StepRun for a given step name in a run."""
        return (
            self.session.query(StepRun)
            .filter_by(flow_run_id=run_id, step_name=step_name)
            .order_by(StepRun.started_at.desc())
            .first()
        )

    # ── Inbox helpers ───────────────────────────────────────────────────────

    def create_inbox_item(
        self, type: str, reference_id: str, space_id: str, title: str = "",
    ) -> InboxItem:
        item = InboxItem(
            type=type, reference_id=reference_id,
            space_id=space_id, title=title,
        )
        self.session.add(item)
        self.session.commit()
        return item

    def archive_inbox_item(self, item_id: str) -> bool:
        item = self.session.query(InboxItem).filter_by(id=item_id).first()
        if not item:
            return False
        self.session.delete(item)
        self.session.commit()
        return True

    def archive_inbox_by_reference(self, reference_id: str) -> None:
        """Delete all inbox items matching a reference_id (e.g. when user responds to a step)."""
        (
            self.session.query(InboxItem)
            .filter_by(reference_id=reference_id)
            .delete()
        )
        self.session.commit()

    def count_inbox(self) -> int:
        return self.session.query(InboxItem).count()

    def list_inbox(self) -> list[InboxItem]:
        return (
            self.session.query(InboxItem)
            .order_by(InboxItem.created_at.desc())
            .all()
        )
