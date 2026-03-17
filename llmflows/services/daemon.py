"""System daemon -- watches all projects, consumes pending TaskRuns."""

import logging
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import get_github_token, load_system_config
from ..db.database import get_session, reset_engine
from ..db.models import Integration
from .agent import AgentService
from .project import ProjectService
from .run import RunService
from .task import TaskService
from .worktree import WorktreeService

logger = logging.getLogger("llmflows.daemon")


class Daemon:
    def __init__(self):
        self.running = False
        self._stop_event = threading.Event()
        self.config = load_system_config()
        self.poll_interval = self.config["daemon"]["poll_interval_seconds"]
        self.run_timeout_minutes = self.config["daemon"]["run_timeout_minutes"]

    def start(self) -> None:
        """Start the daemon loop."""
        self.running = True
        self._stop_event.clear()
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        logger.info("Daemon started (poll every %ds)", self.poll_interval)

        while self.running:
            try:
                self._tick()
            except Exception:
                logger.exception("Error in daemon tick")
            self._stop_event.wait(self.poll_interval)

        logger.info("Daemon stopped")

    def _handle_signal(self, signum, frame):
        logger.info("Received signal %d, stopping", signum)
        self.running = False
        self._stop_event.set()

    def _tick(self) -> None:
        """Single daemon tick -- check all projects for actionable transitions."""
        reset_engine()
        session = get_session()
        try:
            project_svc = ProjectService(session)
            task_svc = TaskService(session)
            run_svc = RunService(session)

            for project in project_svc.list_all():
                self._process_project(project, task_svc, run_svc)

            self._poll_integrations(session)
        finally:
            session.close()

    def _get_project_settings(self, project_id: str, session) -> object:
        """Return the ProjectSettings for a project, or a defaults object."""
        from ..db.models import ProjectSettings

        settings = session.query(ProjectSettings).filter_by(project_id=project_id).first()
        if settings:
            return settings

        class _Defaults:
            worktree_enabled = True

        return _Defaults()

    def _process_project(self, project, task_svc: TaskService, run_svc: RunService) -> None:
        """Process a single project: check active runs, pick up pending."""
        settings = self._get_project_settings(project.id, run_svc.session)
        worktree_enabled = settings.worktree_enabled

        active_runs = run_svc.get_active_by_project(project.id)

        for run in active_runs:
            task = task_svc.get(run.task_id)
            if not task:
                continue

            # Determine how to locate the agent process for this task
            if worktree_enabled:
                if not task.worktree_branch:
                    continue
                agent_running = AgentService.is_agent_running(project.path, task.worktree_branch)
            else:
                agent_running = AgentService.is_agent_running(
                    project.path, "", task_id=task.id
                )

            if agent_running:
                if self.run_timeout_minutes and run.started_at:
                    started = run.started_at
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=timezone.utc)
                    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                    if elapsed > self.run_timeout_minutes * 60:
                        logger.warning(
                            "Task %s run %s timed out after %dm (limit %dm)",
                            task.id, run.id, int(elapsed / 60), self.run_timeout_minutes,
                        )
                        AgentService.kill_agent(
                            project.path,
                            task.worktree_branch if worktree_enabled else "",
                            task_id="" if worktree_enabled else task.id,
                        )
                        run_svc.mark_completed(run.id, outcome="timeout")
                        continue
                return

            run_svc.session.refresh(run)
            if run.completed_at:
                continue
            outcome = run.outcome or "completed"
            logger.info("Task %s run %s finished (outcome=%s)", task.id, run.id, outcome)
            run_svc.mark_completed(run.id, outcome=outcome)

            if task.github_issue_number and task.integration:
                self._post_github_result(task, run, project)

        pending = run_svc.get_pending(project.id)
        if pending:
            self._run_task(pending, task_svc, run_svc, project, settings)

    def _poll_integrations(self, session) -> None:
        """Poll all enabled GitHub integrations for @llmflows comments."""
        token = get_github_token()
        if not token:
            return

        integrations = (
            session.query(Integration)
            .filter_by(provider="github", enabled=True)
            .all()
        )
        if not integrations:
            return

        from .github import GitHubService
        gh = GitHubService(token)
        try:
            for integration in integrations:
                try:
                    count = gh.poll_integration(integration, session)
                    if count:
                        logger.info("GitHub: created %d run(s) for %s", count, integration.project.name)
                except Exception:
                    logger.exception("Error polling GitHub integration %s", integration.id)
        finally:
            gh.close()

    def _post_github_result(self, task, run, project) -> None:
        """Post run result back to the GitHub issue."""
        token = get_github_token()
        if not token:
            return

        config = task.integration.get_config()
        repo = config.get("repo", "")
        if not repo:
            return

        from .github import GitHubService
        gh = GitHubService(token)
        try:
            gh.post_run_result(
                repo=repo,
                task=task,
                run_id=run.id,
                summary=run.summary or "",
                branch=task.worktree_branch or "",
            )
        except Exception:
            logger.exception("Error posting GitHub result for run %s", run.id)
        finally:
            gh.close()

    def _run_task(self, run, task_svc: TaskService, run_svc: RunService, project, settings=None) -> None:
        """Set up worktree (if enabled) and launch agent for a pending TaskRun."""
        task = task_svc.get(run.task_id)
        if not task:
            return

        if settings is None:
            settings = self._get_project_settings(project.id, run_svc.session)

        worktree_enabled = settings.worktree_enabled
        logger.info("Running task %s (flow=%s, worktree=%s): %s",
                    task.id, run.flow_name, worktree_enabled, task.description[:60])

        project_dir = Path(project.path) / ".llmflows"

        if worktree_enabled:
            wt_svc = WorktreeService(project.path)
            branch = task.worktree_branch or f"task-{task.id}"

            wt_path = wt_svc.get_worktree_path(branch)
            if not wt_path:
                success, msg = wt_svc.create(branch)
                if not success:
                    logger.error("Failed to create worktree for task %s: %s", task.id, msg)
                    run_svc.mark_completed(run.id, outcome="error")
                    return
                task_svc.update(task.id, worktree_branch=branch)
                wt_path = wt_svc.get_worktree_path(branch)

            if not wt_path:
                logger.error(
                    "Worktree path not found after creation for task %s branch %s",
                    task.id, branch,
                )
                run_svc.mark_completed(run.id, outcome="error")
                return

            working_path = wt_path
            use_task_subdir = False
        else:
            # No worktree — agent runs in the project root
            working_path = Path(project.path)
            use_task_subdir = True

        run_svc.mark_started(run.id)

        history = run_svc.get_history(task.id)
        execution_history = [
            {
                "flow_name": r.flow_name,
                "outcome": r.outcome or "unknown",
                "user_prompt": r.user_prompt or "",
                "summary": r.summary or "",
            }
            for r in history
            if r.outcome != "cancelled"
        ] or None

        agent = AgentService(project_dir, working_path)
        launched, prompt_content, log_path = agent.prepare_and_launch(
            run_id=run.id,
            flow_name=run.flow_name,
            task_name=task.name,
            task_id=task.id,
            task_description=run.user_prompt or task.description,
            task_type=task.type.value,
            execution_history=execution_history,
            model=run.model or "",
            agent=run.agent or "cursor",
            use_task_subdir=use_task_subdir,
        )
        if launched:
            if prompt_content:
                run_svc.set_prompt(run.id, prompt_content)
            if log_path:
                run_svc.set_log_path(run.id, log_path)
        else:
            logger.error("Agent failed to launch for task %s run %s", task.id, run.id)
            run_svc.mark_completed(run.id, outcome="error")


def write_pid_file(pid: int) -> Path:
    """Write daemon PID to ~/.llmflows/daemon.pid."""
    from ..config import ensure_system_dir
    pid_file = ensure_system_dir() / "daemon.pid"
    pid_file.write_text(str(pid))
    return pid_file


def read_pid_file() -> Optional[int]:
    """Read daemon PID from file, return None if not running."""
    from ..config import SYSTEM_DIR
    pid_file = SYSTEM_DIR / "daemon.pid"
    if not pid_file.exists():
        return None
    try:
        pid = int(pid_file.read_text().strip())
        import os
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        pid_file.unlink(missing_ok=True)
        return None


def remove_pid_file() -> None:
    """Remove the daemon PID file."""
    from ..config import SYSTEM_DIR
    pid_file = SYSTEM_DIR / "daemon.pid"
    pid_file.unlink(missing_ok=True)
