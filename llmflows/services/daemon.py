"""System daemon -- watches all projects, orchestrates step-per-run execution."""

import json
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
from .context import ContextService
from .flow import FlowService
from .gate import evaluate_gates, evaluate_ifs, _interpolate
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
        self.max_step_retries = self.config["daemon"].get("max_recovery_attempts", 3)

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
            flow_svc = FlowService(session)

            for project in project_svc.list_all():
                self._process_project(project, task_svc, run_svc, flow_svc)

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
            is_git_repo = True

        return _Defaults()

    # ── Core orchestration ────────────────────────────────────────────────────

    def _process_project(
        self, project, task_svc: TaskService,
        run_svc: RunService, flow_svc: FlowService,
    ) -> None:
        """Process a single project: orchestrate active runs step-by-step, pick up pending."""
        settings = self._get_project_settings(project.id, run_svc.session)
        is_git = getattr(settings, "is_git_repo", True)
        if is_git is None:
            is_git = True

        active_runs = run_svc.get_active_by_project(project.id)

        for run in active_runs:
            task = task_svc.get(run.task_id)
            if not task:
                continue

            working_path, use_task_subdir = self._resolve_working_path(
                project, task, is_git,
            )
            if working_path is None:
                continue

            active_step = run_svc.get_active_step(run.id)

            if active_step:
                self._process_active_step(
                    run, task, project, active_step, working_path,
                    is_git, use_task_subdir, run_svc, flow_svc, task_svc,
                )
            else:
                if not run.current_step:
                    self._launch_first_step(
                        run, task, project, working_path,
                        is_git, use_task_subdir, run_svc, flow_svc,
                    )

        pending = run_svc.get_pending(project.id)
        if pending:
            self._start_run(pending, task_svc, run_svc, flow_svc, project, settings)

    def _resolve_working_path(
        self, project, task, is_git: bool,
    ) -> tuple[Optional[Path], bool]:
        """Resolve the working directory for a task. Returns (path, use_task_subdir)."""
        if is_git:
            if not task.worktree_branch:
                return None, False
            wt_svc = WorktreeService(project.path)
            wt_path = wt_svc.get_worktree_path(task.worktree_branch)
            return wt_path, False
        return Path(project.path), True

    def _process_active_step(
        self, run, task, project, step_run,
        working_path: Path, is_git: bool, use_task_subdir: bool,
        run_svc: RunService, flow_svc: FlowService, task_svc: TaskService,
    ) -> None:
        """Handle a running step: check liveness, evaluate gates on completion, advance."""
        if is_git:
            agent_running = AgentService.is_agent_running(project.path, task.worktree_branch)
        else:
            agent_running = AgentService.is_agent_running(project.path, "", task_id=task.id)

        if agent_running:
            if self.run_timeout_minutes and step_run.started_at:
                started = step_run.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                if elapsed > self.run_timeout_minutes * 60:
                    logger.warning(
                        "Task %s run %s step '%s' timed out after %dm",
                        task.id, run.id, step_run.step_name, int(elapsed / 60),
                    )
                    AgentService.kill_agent(
                        project.path,
                        task.worktree_branch if is_git else "",
                        task_id="" if is_git else task.id,
                    )
                    run_svc.mark_step_completed(step_run.id, outcome="timeout")
                    run_svc.mark_completed(run.id, outcome="timeout")
            return

        run_svc.session.refresh(step_run)
        if step_run.completed_at:
            return

        run_svc.mark_step_completed(step_run.id, outcome="completed")
        logger.info(
            "Task %s run %s step '%s' completed",
            task.id, run.id, step_run.step_name,
        )

        gate_timeout = load_system_config().get("daemon", {}).get("gate_timeout_seconds", 60)
        step_vars = {
            "run.id": run.id,
            "task.id": run.task_id,
            "flow.name": step_run.flow_name,
        }

        step_obj = flow_svc.get_step_obj(step_run.flow_name, step_run.step_name)
        gates = list(step_obj.get_gates()) if step_obj else []

        if step_run.step_name != "__summary__":
            project_root = Path(task.project.path)
            artifact_dir = ContextService.get_artifacts_dir(project_root, task.id, run.id)
            step_artifact_dir = artifact_dir / f"{step_run.step_position:02d}-{step_run.step_name}"
            gates.insert(0, {
                "command": f'test -d "{step_artifact_dir}" && test "$(ls -A "{step_artifact_dir}")"',
                "message": f"Step '{step_run.step_name}' must produce output artifacts in {step_artifact_dir}",
            })

        if gates:
            failures = evaluate_gates(gates, working_path, timeout=gate_timeout, variables=step_vars)
            if failures:
                retry_count = len([
                    sr for sr in run_svc.list_step_runs(run.id)
                    if sr.step_name == step_run.step_name and sr.completed_at
                ])
                if retry_count < self.max_step_retries:
                    logger.warning(
                        "Task %s run %s step '%s' gate failed (attempt %d/%d), retrying",
                        task.id, run.id, step_run.step_name,
                        retry_count + 1, self.max_step_retries,
                    )
                    gate_failure_info = [
                        {
                            "command": f["command"],
                            "message": f["message"],
                            "output": f.get("stderr", ""),
                        }
                        for f in failures
                    ]
                    self._launch_step(
                        run, task, working_path, use_task_subdir,
                        step_run.step_name, step_run.step_position,
                        step_run.flow_name, run_svc, flow_svc,
                        gate_failures=gate_failure_info,
                    )
                    return
                else:
                    logger.error(
                        "Task %s run %s step '%s' gate failed after %d attempts, marking interrupted",
                        task.id, run.id, step_run.step_name, retry_count,
                    )
                    run_svc.mark_completed(run.id, outcome="interrupted")
                    return

        self._advance_to_next_step(
            run, task, working_path, use_task_subdir,
            step_run.step_name, step_run.step_position, step_run.flow_name,
            run_svc, flow_svc, task_svc,
        )

    def _advance_to_next_step(
        self, run, task, working_path: Path, use_task_subdir: bool,
        current_step_name: str, current_position: int, current_flow: str,
        run_svc: RunService, flow_svc: FlowService, task_svc: TaskService,
    ) -> None:
        """Determine the next step and launch it, or complete the run."""
        gate_timeout = load_system_config().get("daemon", {}).get("gate_timeout_seconds", 60)
        step_vars = {
            "run.id": run.id,
            "task.id": run.task_id,
            "flow.name": current_flow,
        }

        if current_step_name == "__summary__":
            artifacts_dir = ContextService.get_artifacts_dir(Path(task.project.path), task.id, run.id)
            summary = ContextService.read_summary_artifact(artifacts_dir)
            logger.info("Task %s run %s completed", task.id, run.id)
            run_svc.mark_completed(run.id, outcome="completed", summary=summary)
            if task.github_issue_number and task.integration:
                self._post_github_result(task, run, task.project)
            return

        next_step_name = flow_svc.get_next_step(current_flow, current_step_name)
        next_flow = current_flow
        next_position = current_position + 1

        if not next_step_name:
            try:
                chain = json.loads(run.flow_chain or "[]")
            except (json.JSONDecodeError, TypeError):
                chain = []
            if next_flow in chain:
                idx = chain.index(next_flow)
                if idx + 1 < len(chain):
                    next_flow = chain[idx + 1]
                    steps = flow_svc.get_flow_steps(next_flow)
                    next_step_name = steps[0] if steps else None
                    step_vars["flow.name"] = next_flow

        if not next_step_name:
            self._launch_summary_step(
                run, task, working_path, use_task_subdir,
                next_position, run_svc, flow_svc,
            )
            return

        while next_step_name:
            step_obj = flow_svc.get_step_obj(next_flow, next_step_name)
            if not step_obj:
                break
            ifs = step_obj.get_ifs()
            if not ifs or evaluate_ifs(ifs, working_path, timeout=gate_timeout, variables=step_vars):
                break
            logger.info(
                "Task %s run %s: IF conditions not met for step '%s', skipping",
                task.id, run.id, next_step_name,
            )
            nxt = flow_svc.get_next_step(next_flow, next_step_name)
            next_position += 1
            if nxt:
                next_step_name = nxt
            else:
                next_step_name = None

        if not next_step_name:
            self._launch_summary_step(
                run, task, working_path, use_task_subdir,
                next_position, run_svc, flow_svc,
            )
            return

        self._launch_step(
            run, task, working_path, use_task_subdir,
            next_step_name, next_position, next_flow,
            run_svc, flow_svc,
        )

    def _launch_first_step(
        self, run, task, project, working_path: Path,
        is_git: bool, use_task_subdir: bool,
        run_svc: RunService, flow_svc: FlowService,
    ) -> None:
        """Launch the first step of a run that has been started but has no steps yet."""
        gate_timeout = load_system_config().get("daemon", {}).get("gate_timeout_seconds", 60)
        step_vars = {"run.id": run.id, "task.id": run.task_id, "flow.name": run.flow_name}

        steps = flow_svc.get_flow_steps(run.flow_name)
        if not steps:
            logger.error("Flow '%s' has no steps for task %s run %s", run.flow_name, task.id, run.id)
            run_svc.mark_completed(run.id, outcome="error")
            return

        first_step = steps[0]
        position = 0

        while first_step:
            step_obj = flow_svc.get_step_obj(run.flow_name, first_step)
            if not step_obj:
                break
            ifs = step_obj.get_ifs()
            if not ifs or evaluate_ifs(ifs, working_path, timeout=gate_timeout, variables=step_vars):
                break
            logger.info("Task %s run %s: IF conditions not met for step '%s', skipping",
                        task.id, run.id, first_step)
            nxt = flow_svc.get_next_step(run.flow_name, first_step)
            position += 1
            first_step = nxt

        if not first_step:
            self._launch_summary_step(
                run, task, working_path, use_task_subdir,
                position, run_svc, flow_svc,
            )
            return

        self._launch_step(
            run, task, working_path, use_task_subdir,
            first_step, position, run.flow_name,
            run_svc, flow_svc,
        )

    def _launch_step(
        self, run, task, working_path: Path, use_task_subdir: bool,
        step_name: str, step_position: int, flow_name: str,
        run_svc: RunService, flow_svc: FlowService,
        gate_failures: Optional[list[dict]] = None,
    ) -> None:
        """Create a StepRun, render prompt, and launch agent for a step."""
        step_obj = flow_svc.get_step_obj(flow_name, step_name)
        step_content = (step_obj.content or "").rstrip() if step_obj else ""

        step_vars = {"run.id": run.id, "task.id": run.task_id, "flow.name": flow_name}
        if step_content:
            from .gate import _interpolate
            step_content = _interpolate(step_content, step_vars)

        try:
            overrides = json.loads(run.step_overrides or "{}")
        except (json.JSONDecodeError, TypeError):
            overrides = {}
        override_key = f"{flow_name}/{step_name}"
        step_cfg = overrides.get(override_key, {})
        resolved_agent = step_cfg.get("agent") or run.agent or "cursor"
        resolved_model = step_cfg.get("model") or run.model or ""

        step_run = run_svc.create_step_run(
            run_id=run.id,
            step_name=step_name,
            step_position=step_position,
            flow_name=flow_name,
            agent=resolved_agent,
            model=resolved_model,
        )

        run_svc.update_run_step(run.id, step_name, flow_name)

        project_dir = Path(task.project.path) / ".llmflows"
        agent_svc = AgentService(project_dir, working_path)

        launched, prompt_content, log_path = agent_svc.prepare_and_launch_step(
            run_id=run.id,
            task_id=task.id,
            task_description=task.description or "",
            user_prompt=run.user_prompt or task.description or "",
            step_name=step_name,
            step_position=step_position,
            step_content=step_content,
            flow_name=flow_name,
            model=resolved_model,
            agent=resolved_agent,
            gate_failures=gate_failures,
            use_task_subdir=use_task_subdir,
        )

        if launched:
            if prompt_content:
                run_svc.set_step_prompt(step_run.id, prompt_content)
            if log_path:
                run_svc.set_step_log_path(step_run.id, log_path)
            logger.info(
                "Launched step '%s' (pos=%d, agent=%s, model=%s) for task %s run %s",
                step_name, step_position, resolved_agent, resolved_model,
                task.id, run.id,
            )
        else:
            logger.error(
                "Failed to launch step '%s' for task %s run %s",
                step_name, task.id, run.id,
            )
            run_svc.mark_step_completed(step_run.id, outcome="error")
            run_svc.mark_completed(run.id, outcome="error")

    def _launch_summary_step(
        self, run, task, working_path: Path, use_task_subdir: bool,
        step_position: int, run_svc: RunService, flow_svc: FlowService,
    ) -> None:
        """Launch the auto-appended summary step."""
        project_root = Path(task.project.path)
        artifacts_dir = ContextService.get_artifacts_dir(project_root, task.id, run.id)
        ctx = ContextService(working_path / ".llmflows")
        summary_content = ctx.render_summary_step({
            "artifacts_output_dir": str(artifacts_dir),
        })

        step_run = run_svc.create_step_run(
            run_id=run.id,
            step_name="__summary__",
            step_position=step_position,
            flow_name=run.flow_name,
            agent=run.agent or "cursor",
            model=run.model or "",
        )

        run_svc.update_run_step(run.id, "__summary__", run.flow_name)

        project_dir = Path(task.project.path) / ".llmflows"
        agent_svc = AgentService(project_dir, working_path)

        launched, prompt_content, log_path = agent_svc.prepare_and_launch_step(
            run_id=run.id,
            task_id=task.id,
            task_description=task.description or "",
            user_prompt=run.user_prompt or task.description or "",
            step_name="__summary__",
            step_position=step_position,
            step_content=summary_content,
            flow_name=run.flow_name,
            model=run.model or "",
            agent=run.agent or "cursor",
            use_task_subdir=use_task_subdir,
        )

        if launched:
            if prompt_content:
                run_svc.set_step_prompt(step_run.id, prompt_content)
            if log_path:
                run_svc.set_step_log_path(step_run.id, log_path)
            logger.info("Launched summary step for task %s run %s", task.id, run.id)
        else:
            logger.error("Failed to launch summary step for task %s run %s", task.id, run.id)
            run_svc.mark_step_completed(step_run.id, outcome="error")
            artifacts_dir = ContextService.get_artifacts_dir(Path(task.project.path), task.id, run.id)
            summary = ContextService.read_summary_artifact(artifacts_dir)
            run_svc.mark_completed(run.id, outcome="completed", summary=summary)

    def _start_run(
        self, run, task_svc: TaskService, run_svc: RunService,
        flow_svc: FlowService, project, settings=None,
    ) -> None:
        """Set up worktree (if enabled) and mark run as started for step orchestration."""
        task = task_svc.get(run.task_id)
        if not task:
            return

        if settings is None:
            settings = self._get_project_settings(project.id, run_svc.session)

        is_git = getattr(settings, "is_git_repo", True)
        if is_git is None:
            is_git = True
        logger.info("Starting run for task %s (flow=%s, is_git=%s): %s",
                    task.id, run.flow_name, is_git, (task.description or "")[:60])

        if is_git:
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
                logger.error("Worktree path not found for task %s branch %s", task.id, branch)
                run_svc.mark_completed(run.id, outcome="error")
                return

        run_svc.mark_started(run.id)

    # ── GitHub integration ────────────────────────────────────────────────────

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
