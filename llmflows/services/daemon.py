"""System daemon -- watches all projects, orchestrates step-per-run execution."""

import json
import logging
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import load_system_config, resolve_alias
from ..db.database import get_session, reset_engine
from ..db.models import Project
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
        finally:
            session.close()

    @staticmethod
    def _get_snapshot_steps(run) -> list[str]:
        """Return ordered step names from a run's flow_snapshot JSON, or [] if none."""
        if not run.flow_snapshot:
            return []
        try:
            snap = json.loads(run.flow_snapshot)
            return [s["name"] for s in sorted(snap.get("steps", []), key=lambda s: s.get("position", 0))]
        except (json.JSONDecodeError, KeyError, TypeError):
            return []

    @staticmethod
    def _get_snapshot_step(run, step_name: str) -> Optional[dict]:
        """Return a step dict from the run's flow_snapshot, or None."""
        if not run.flow_snapshot:
            return None
        try:
            snap = json.loads(run.flow_snapshot)
            for s in snap.get("steps", []):
                if s["name"] == step_name:
                    return s
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
        return None

    @staticmethod
    def _set_task_status(task_id: str, status: str, run_svc: RunService) -> None:
        """Update a task's status using the run service's session."""
        TaskService(run_svc.session).update(task_id, task_status=status)

    @staticmethod
    def _build_execution_history(run_svc: RunService, task_id: str, current_run_id: str) -> list[dict]:
        """Build execution history from previous completed runs for the same task."""
        history = run_svc.get_history(task_id)
        return [
            {
                "flow_name": r.flow_name,
                "outcome": r.outcome or "unknown",
                "user_prompt": r.user_prompt or "",
                "summary": r.summary or "",
            }
            for r in history
            if r.outcome != "cancelled" and r.id != current_run_id
        ] or None

    # ── Core orchestration ────────────────────────────────────────────────────

    def _process_project(
        self, project, task_svc: TaskService,
        run_svc: RunService, flow_svc: FlowService,
    ) -> None:
        """Process a single project: orchestrate active runs step-by-step, pick up pending."""
        is_git = project.is_git_repo if project.is_git_repo is not None else True

        active_runs = run_svc.get_active_by_project(project.id)

        for run in active_runs:
            if run.paused_at:
                continue

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
                if active_step.awaiting_user_at and not active_step.completed_at:
                    continue
                self._process_active_step(
                    run, task, project, active_step, working_path,
                    is_git, use_task_subdir, run_svc, flow_svc, task_svc,
                )
            else:
                if not run.current_step:
                    self._launch_first_step(
                        run, task, project, working_path,
                        is_git, use_task_subdir, run_svc, flow_svc, task_svc,
                    )
                else:
                    latest = run_svc.get_latest_step_run(run.id, run.current_step)
                    if latest and latest.completed_at:
                        snap_steps = self._get_snapshot_steps(run)
                        if snap_steps:
                            try:
                                idx = snap_steps.index(run.current_step)
                                pos = idx
                            except ValueError:
                                pos = latest.step_position
                        else:
                            pos = latest.step_position
                        self._advance_to_next_step(
                            run, task, working_path, use_task_subdir,
                            run.current_step, pos, run.flow_name or "",
                            run_svc, flow_svc, task_svc,
                        )
                    else:
                        self._relaunch_current_step(
                            run, task, working_path, use_task_subdir,
                            run_svc, flow_svc,
                        )

        # Concurrency gate: only start runs for new tasks if under the limit
        max_tasks = project.max_concurrent_tasks or 1
        in_progress_task_ids = {
            t.id for t in task_svc.list_by_project(project.id)
            if t.task_status == "in_progress"
        }

        for pending in run_svc.get_all_pending(project.id):
            if pending.task_id in in_progress_task_ids:
                self._start_run(pending, task_svc, run_svc, flow_svc, project)
            elif len(in_progress_task_ids) < max_tasks:
                in_progress_task_ids.add(pending.task_id)
                self._start_run(pending, task_svc, run_svc, flow_svc, project)

    def _relaunch_current_step(
        self, run, task, working_path: Path, use_task_subdir: bool,
        run_svc: RunService, flow_svc: FlowService,
    ) -> None:
        """Re-launch a step that has no active step_run (e.g. after retry_step)."""
        step_name = run.current_step
        flow_name = run.flow_name or ""
        position = 0
        steps = self._get_snapshot_steps(run) or flow_svc.get_flow_steps(flow_name, project_id=run.project_id)
        if step_name in steps:
            position = steps.index(step_name)
        self._launch_step(
            run, task, working_path, use_task_subdir,
            step_name, position, flow_name,
            run_svc, flow_svc,
        )

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
                completed_time = sum(
                    sr.duration_seconds for sr in run_svc.list_step_runs(run.id)
                    if sr.id != step_run.id and sr.duration_seconds is not None
                )
                step_started = step_run.started_at
                if step_started.tzinfo is None:
                    step_started = step_started.replace(tzinfo=timezone.utc)
                current_step_time = (datetime.now(timezone.utc) - step_started).total_seconds()
                elapsed = completed_time + current_step_time
                if elapsed > self.run_timeout_minutes * 60:
                    logger.warning(
                        "Task %s run %s timed out after %dm (step '%s')",
                        task.id, run.id, int(elapsed / 60), step_run.step_name,
                    )
                    AgentService.kill_agent(
                        project.path,
                        task.worktree_branch if is_git else "",
                        task_id="" if is_git else task.id,
                    )
                    run_svc.mark_step_completed(step_run.id, outcome="timeout")
                    run_svc.mark_completed(run.id, outcome="timeout")
                    task_svc.update(run.task_id, task_status="stopped")
            return

        run_svc.session.refresh(step_run)
        if step_run.completed_at:
            return

        # Refresh run to detect a cancellation that raced with the agent dying.
        run_svc.session.refresh(run)
        if run.completed_at:
            logger.info(
                "Task %s run %s was cancelled while step '%s' was stopping, skipping gate evaluation",
                task.id, run.id, step_run.step_name,
            )
            run_svc.mark_step_completed(step_run.id, outcome="cancelled")
            return

        prompt_file = Path.home() / ".llmflows" / "prompts" / f"{task.id}-{run.id}-{step_run.step_position:02d}-{step_run.step_name}.md"
        prompt_file.unlink(missing_ok=True)

        # Auto-publish step attachments to the shared task attachments directory.
        project_root = Path(task.project.path)
        step_artifacts = ContextService.get_artifacts_dir(project_root, task.id, run.id) / \
            f"{step_run.step_position:02d}-{step_run.step_name}" / "attachments"
        if step_artifacts.is_dir():
            self._publish_attachments(step_artifacts, task.id)

        snap_step_def = self._get_snapshot_step(run, step_run.step_name)
        step_type = (snap_step_def or {}).get("step_type", "agent")
        if step_type in ("manual", "prompt"):
            run_svc.mark_awaiting_user(step_run.id)
            run_svc.create_inbox_item(
                type="awaiting_user", reference_id=step_run.id,
                task_id=task.id, project_id=task.project_id,
                title=f"{task.name or task.id} — {step_run.step_name} ({step_type})",
            )
            logger.info(
                "Task %s run %s step '%s' awaiting user (%s)",
                task.id, run.id, step_run.step_name, step_type,
            )
            return

        run_svc.mark_step_completed(step_run.id, outcome="completed")
        logger.info(
            "Task %s run %s step '%s' completed",
            task.id, run.id, step_run.step_name,
        )

        if step_run.step_name == "__one_shot__":
            artifacts_dir = ContextService.get_artifacts_dir(Path(task.project.path), task.id, run.id)
            summary = ContextService.read_summary_artifact(artifacts_dir, task_id=task.id)
            logger.info("Task %s run %s one-shot completed", task.id, run.id)
            run_svc.mark_completed(run.id, outcome="completed", summary=summary)
            self._maybe_create_completed_inbox(run, task, run_svc)
            task_svc.update(run.task_id, task_status="completed")
            return

        gate_timeout = load_system_config().get("daemon", {}).get("gate_timeout_seconds", 60)
        project_root = Path(task.project.path)
        artifact_dir = ContextService.get_artifacts_dir(project_root, task.id, run.id)
        step_artifact_dir = artifact_dir / f"{step_run.step_position:02d}-{step_run.step_name}"
        step_vars = {
            "run.id": run.id,
            "task.id": run.task_id,
            "flow.name": step_run.flow_name,
            "artifacts_output_dir": str(step_artifact_dir),
        }

        # Resolve step definition from snapshot or live template
        snap_step = self._get_snapshot_step(run, step_run.step_name)
        step_obj = flow_svc.get_step_obj(step_run.flow_name, step_run.step_name, project_id=run.project_id)
        step_src = snap_step or step_obj
        max_retries = None  # None = unlimited
        step_allow_max = False
        if step_src:
            max_retries = step_src.get("max_gate_retries") if snap_step else getattr(step_obj, 'max_gate_retries', None)
            step_allow_max = bool(step_src.get("allow_max") if snap_step else getattr(step_obj, 'allow_max', False))

        gates = list(snap_step.get("gates", []) if snap_step else (step_obj.get_gates() if step_obj else []))

        if step_run.step_name != "__summary__":
            gates.insert(0, {
                "command": f'test -d "{step_artifact_dir}" && test "$(ls -A "{step_artifact_dir}")"',
                "message": f"Step '{step_run.step_name}' must produce output artifacts in {step_artifact_dir}",
            })

        # Re-check cancellation immediately before running gates — the run may have been
        # cancelled between the agent dying and gate evaluation starting.
        run_svc.session.refresh(run)
        if run.completed_at:
            logger.info(
                "Task %s run %s was cancelled before gate evaluation for step '%s', skipping",
                task.id, run.id, step_run.step_name,
            )
            run_svc.mark_step_completed(step_run.id, outcome="cancelled")
            return

        if gates:
            failures = evaluate_gates(gates, working_path, timeout=gate_timeout, variables=step_vars)
            if failures:
                total_completed = len([
                    sr for sr in run_svc.list_step_runs(run.id)
                    if sr.step_name == step_run.step_name and sr.completed_at
                ])
                retry_count = max(0, total_completed - 1)
                unlimited = max_retries is None or max_retries == 0
                # Do not retry if the run was cancelled while gates were running.
                run_svc.session.refresh(run)
                if run.completed_at:
                    logger.info(
                        "Task %s run %s cancelled during gate evaluation for step '%s', skipping retry",
                        task.id, run.id, step_run.step_name,
                    )
                    run_svc.mark_step_completed(step_run.id, outcome="cancelled")
                    return

                if unlimited or retry_count < max_retries:
                    is_last_retry = not unlimited and (retry_count + 1 >= max_retries)
                    use_max = step_allow_max and is_last_retry
                    limit_str = "∞" if unlimited else str(max_retries)
                    logger.warning(
                        "Task %s run %s step '%s' gate failed (retry %d/%s%s), retrying",
                        task.id, run.id, step_run.step_name,
                        retry_count + 1, limit_str,
                        " [escalating to max]" if use_max else "",
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
                        force_alias="max" if use_max else None,
                    )
                    return
                else:
                    logger.error(
                        "Task %s run %s step '%s' gate failed after %d retries, marking interrupted",
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
            summary = ContextService.read_summary_artifact(artifacts_dir, task_id=task.id)
            logger.info("Task %s run %s completed", task.id, run.id)
            run_svc.mark_completed(run.id, outcome="completed", summary=summary)
            self._maybe_create_completed_inbox(run, task, run_svc)
            task_svc.update(run.task_id, task_status="completed")
            return

        next_flow = current_flow
        next_position = current_position + 1

        # Use snapshot if available, otherwise fall back to template
        snap_steps = self._get_snapshot_steps(run)
        if snap_steps:
            try:
                idx = snap_steps.index(current_step_name)
                next_step_name = snap_steps[idx + 1] if idx + 1 < len(snap_steps) else None
            except ValueError:
                next_step_name = None
        else:
            next_step_name = flow_svc.get_next_step(current_flow, current_step_name, project_id=run.project_id)

        if not next_step_name:
            self._launch_summary_step(
                run, task, working_path, use_task_subdir,
                next_position, run_svc, flow_svc, task_svc,
            )
            return

        while next_step_name:
            snap_step = self._get_snapshot_step(run, next_step_name)
            step_obj = flow_svc.get_step_obj(next_flow, next_step_name, project_id=run.project_id)
            step_src = snap_step or step_obj
            if not step_src:
                break
            ifs = snap_step.get("ifs", []) if snap_step else (step_obj.get_ifs() if step_obj else [])
            if not ifs or evaluate_ifs(ifs, working_path, timeout=gate_timeout, variables=step_vars):
                break
            logger.info(
                "Task %s run %s: IF conditions not met for step '%s', skipping",
                task.id, run.id, next_step_name,
            )
            if snap_steps:
                try:
                    idx = snap_steps.index(next_step_name)
                    nxt = snap_steps[idx + 1] if idx + 1 < len(snap_steps) else None
                except ValueError:
                    nxt = None
            else:
                nxt = flow_svc.get_next_step(next_flow, next_step_name, project_id=run.project_id)
            next_position += 1
            next_step_name = nxt

        if not next_step_name:
            self._launch_summary_step(
                run, task, working_path, use_task_subdir,
                next_position, run_svc, flow_svc, task_svc,
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
        run_svc: RunService, flow_svc: FlowService, task_svc: TaskService,
    ) -> None:
        """Launch the first step of a run that has been started but has no steps yet."""
        # No flow selected -- run as one-shot prompt-only
        if not run.flow_name:
            self._launch_one_shot(
                run, task, working_path, use_task_subdir,
                run_svc, flow_svc,
            )
            return

        if run.one_shot:
            if run.flow_name and flow_svc.has_human_steps(run.flow_name, project_id=run.project_id):
                logger.warning(
                    "Task %s run %s: one-shot disabled — flow '%s' contains manual/prompt steps",
                    task.id, run.id, run.flow_name,
                )
            else:
                self._launch_one_shot(
                    run, task, working_path, use_task_subdir,
                    run_svc, flow_svc,
                )
                return

        # Build and persist flow snapshot if not already done
        if not run.flow_snapshot:
            snapshot = flow_svc.build_flow_snapshot(run.flow_name, project_id=run.project_id)
            if not snapshot:
                logger.error("Flow '%s' not found for task %s run %s", run.flow_name, task.id, run.id)
                run_svc.mark_completed(run.id, outcome="error")
                self._set_task_status(task.id, "stopped", run_svc)
                return
            run.flow_snapshot = json.dumps(snapshot)
            run_svc.session.commit()

        gate_timeout = load_system_config().get("daemon", {}).get("gate_timeout_seconds", 60)
        step_vars = {"run.id": run.id, "task.id": run.task_id, "flow.name": run.flow_name}

        steps = self._get_snapshot_steps(run)
        if not steps:
            logger.error("Flow '%s' has no steps for task %s run %s", run.flow_name, task.id, run.id)
            run_svc.mark_completed(run.id, outcome="error")
            self._set_task_status(task.id, "stopped", run_svc)
            return

        first_step = steps[0]
        position = 0

        while first_step:
            snap_step = self._get_snapshot_step(run, first_step)
            if not snap_step:
                break
            ifs = snap_step.get("ifs", [])
            if not ifs or evaluate_ifs(ifs, working_path, timeout=gate_timeout, variables=step_vars):
                break
            logger.info("Task %s run %s: IF conditions not met for step '%s', skipping",
                        task.id, run.id, first_step)
            try:
                idx = steps.index(first_step)
                nxt = steps[idx + 1] if idx + 1 < len(steps) else None
            except ValueError:
                nxt = None
            position += 1
            first_step = nxt

        if not first_step:
            self._launch_summary_step(
                run, task, working_path, use_task_subdir,
                position, run_svc, flow_svc, task_svc,
            )
            return

        self._launch_step(
            run, task, working_path, use_task_subdir,
            first_step, position, run.flow_name,
            run_svc, flow_svc,
        )

    def _launch_one_shot(
        self, run, task, working_path: Path, use_task_subdir: bool,
        run_svc: RunService, flow_svc: FlowService,
    ) -> None:
        """Assemble all steps into a single prompt and launch one agent."""
        gate_timeout = load_system_config().get("daemon", {}).get("gate_timeout_seconds", 60)

        collected_steps = []
        active_flow = run.flow_name or "default"

        if run.flow_name:
            step_vars = {"run.id": run.id, "task.id": run.task_id, "flow.name": run.flow_name}
            step_names = flow_svc.get_flow_steps(run.flow_name, project_id=run.project_id)
            for sname in step_names:
                step_obj = flow_svc.get_step_obj(run.flow_name, sname, project_id=run.project_id)
                if not step_obj:
                    continue
                ifs = step_obj.get_ifs()
                if ifs and not evaluate_ifs(ifs, working_path, timeout=gate_timeout, variables=step_vars):
                    continue
                content = (step_obj.content or "").rstrip()
                if content:
                    content = _interpolate(content, step_vars)
                gates = list(step_obj.get_gates())
                collected_steps.append({
                    "name": sname,
                    "content": content,
                    "gates": gates,
                })

        project_root = Path(task.project.path)
        artifacts_dir = ContextService.get_artifacts_dir(project_root, task.id, run.id)
        ctx = ContextService(working_path / ".llmflows")
        summary_content = ctx.render_summary_step({
            "artifacts_output_dir": str(artifacts_dir),
        })
        collected_steps.append({
            "name": "summary",
            "content": summary_content,
            "gates": [],
        })

        # One-shot always uses the max alias — no fallback
        resolved_agent, resolved_model = resolve_alias(run_svc.session, "max")

        step_run = run_svc.create_step_run(
            run_id=run.id,
            step_name="__one_shot__",
            step_position=0,
            flow_name=active_flow,
            agent=resolved_agent,
            model=resolved_model,
        )
        run_svc.update_run_step(run.id, "__one_shot__", active_flow)

        wt_display = str(working_path) if working_path != project_root else None
        execution_history = self._build_execution_history(run_svc, task.id, run.id)
        prompt_content = ctx.render_one_shot({
            "task_id": task.id,
            "task_name": task.name or "",
            "task_description": task.description or "",
            "user_prompt": run.user_prompt or task.description or "",
            "worktree_path": wt_display,
            "steps": collected_steps,
            "artifacts_output_dir": str(artifacts_dir),
            "execution_history": execution_history,
        })

        project_dir = Path(task.project.path) / ".llmflows"
        agent_svc = AgentService(project_dir, working_path)

        if use_task_subdir:
            wt_llmflows = working_path / ".llmflows" / task.id
        else:
            wt_llmflows = working_path / ".llmflows"
        wt_llmflows.mkdir(parents=True, exist_ok=True)

        prompts_dir = Path.home() / ".llmflows" / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = prompts_dir / f"{task.id}-{run.id}-00-__one_shot__.md"
        prompt_file.write_text(prompt_content)

        log_file = wt_llmflows / f"agent-{run.id}-00-__one_shot__.log"
        pid_file = wt_llmflows / "agent.pid"

        launched = agent_svc._launch_agent(
            working_path, prompt_file, log_file, pid_file,
            model=resolved_model, agent=resolved_agent,
        )

        if launched:
            run_svc.set_step_prompt(step_run.id, prompt_content)
            run_svc.set_step_log_path(step_run.id, str(log_file))
            logger.info(
                "Launched one-shot run for task %s run %s (agent=%s, model=%s, steps=%d)",
                task.id, run.id, resolved_agent, resolved_model, len(collected_steps),
            )
        else:
            logger.error("Failed to launch one-shot agent for task %s run %s", task.id, run.id)
            run_svc.mark_step_completed(step_run.id, outcome="error")
            run_svc.mark_completed(run.id, outcome="error")
            self._set_task_status(task.id, "stopped", run_svc)

    def _launch_step(
        self, run, task, working_path: Path, use_task_subdir: bool,
        step_name: str, step_position: int, flow_name: str,
        run_svc: RunService, flow_svc: FlowService,
        gate_failures: Optional[list[dict]] = None,
        force_alias: Optional[str] = None,
    ) -> None:
        """Create a StepRun, render prompt, and launch agent for a step."""
        # Get step definition from snapshot or live template
        snap_step = self._get_snapshot_step(run, step_name)
        step_obj = flow_svc.get_step_obj(flow_name, step_name, project_id=run.project_id)
        step_content = ((snap_step or {}).get("content", "") or (step_obj.content if step_obj else "") or "").rstrip()

        project_root = Path(task.project.path)
        artifacts_dir = ContextService.get_artifacts_dir(project_root, task.id, run.id)
        step_artifact_dir = artifacts_dir / f"{step_position:02d}-{step_name}"
        step_vars = {
            "run.id": run.id,
            "task.id": run.task_id,
            "flow.name": flow_name,
            "artifacts_output_dir": str(step_artifact_dir),
        }
        for sr in run_svc.list_step_runs(run.id):
            if sr.completed_at and sr.user_response:
                step_vars[f"steps.{sr.step_name}.user_response"] = sr.user_response
        if step_content:
            from .gate import _interpolate
            step_content = _interpolate(step_content, step_vars)

        step_type = (snap_step or {}).get("step_type") or getattr(step_obj, 'step_type', None) or "agent"

        # Resolve agent/model from alias
        alias_name = force_alias or (snap_step or {}).get("agent_alias") or getattr(step_obj, 'agent_alias', None) or "standard"
        try:
            resolved_agent, resolved_model = resolve_alias(run_svc.session, alias_name)
        except ValueError:
            resolved_agent, resolved_model = "cursor", ""

        # Track attempt number
        attempt = len([
            sr for sr in run_svc.list_step_runs(run.id)
            if sr.step_name == step_name
        ]) + 1

        step_run = run_svc.create_step_run(
            run_id=run.id,
            step_name=step_name,
            step_position=step_position,
            flow_name=flow_name,
            agent=resolved_agent,
            model=resolved_model,
        )
        step_run.attempt = attempt
        if gate_failures:
            import json as _json
            step_run.gate_failures = _json.dumps(gate_failures)
        run_svc.session.commit()

        run_svc.update_run_step(run.id, step_name, flow_name)

        project_dir = Path(task.project.path) / ".llmflows"
        agent_svc = AgentService(project_dir, working_path)

        execution_history = self._build_execution_history(run_svc, task.id, run.id)

        user_responses = []
        for sr in run_svc.list_step_runs(run.id):
            if sr.completed_at and sr.user_response:
                snap_def = self._get_snapshot_step(run, sr.step_name)
                sr_step_type = (snap_def or {}).get("step_type", "agent")
                user_responses.append({
                    "step_name": sr.step_name,
                    "step_type": sr_step_type,
                    "user_response": sr.user_response,
                })

        resume_prompt = run.resume_prompt or ""
        if resume_prompt:
            run.resume_prompt = ""
            run_svc.session.commit()

        launched, prompt_content, log_path = agent_svc.prepare_and_launch_step(
            run_id=run.id,
            task_id=task.id,
            task_name=task.name or "",
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
            execution_history=execution_history,
            resume_prompt=resume_prompt,
            attempt=attempt,
            user_responses=user_responses,
            step_type=step_type,
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
            self._set_task_status(task.id, "stopped", run_svc)

    def _launch_summary_step(
        self, run, task, working_path: Path, use_task_subdir: bool,
        step_position: int, run_svc: RunService, flow_svc: FlowService,
        task_svc: TaskService,
    ) -> None:
        """Launch the auto-appended summary step."""
        project_root = Path(task.project.path)
        artifacts_dir = ContextService.get_artifacts_dir(project_root, task.id, run.id)
        ctx = ContextService(working_path / ".llmflows")
        summary_content = ctx.render_summary_step({
            "artifacts_output_dir": str(artifacts_dir),
        })

        try:
            resolved_agent, resolved_model = resolve_alias(run_svc.session, "low")
        except ValueError:
            resolved_agent, resolved_model = "cursor", ""

        flow_label = run.flow_name or "default"
        step_run = run_svc.create_step_run(
            run_id=run.id,
            step_name="__summary__",
            step_position=step_position,
            flow_name=flow_label,
            agent=resolved_agent,
            model=resolved_model,
        )

        run_svc.update_run_step(run.id, "__summary__", flow_label)

        project_dir = Path(task.project.path) / ".llmflows"
        agent_svc = AgentService(project_dir, working_path)

        launched, prompt_content, log_path = agent_svc.prepare_and_launch_step(
            run_id=run.id,
            task_id=task.id,
            task_name=task.name or "",
            task_description=task.description or "",
            user_prompt=run.user_prompt or task.description or "",
            step_name="__summary__",
            step_position=step_position,
            step_content=summary_content,
            flow_name=flow_label,
            model=resolved_model,
            agent=resolved_agent,
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
            summary = ContextService.read_summary_artifact(artifacts_dir, task_id=task.id)
            run_svc.mark_completed(run.id, outcome="completed", summary=summary)
            self._maybe_create_completed_inbox(run, task, run_svc)
            task_svc.update(task.id, task_status="completed")

    @staticmethod
    def _maybe_create_completed_inbox(run, task, run_svc: RunService) -> None:
        """Create a completed_run inbox item if the project opts in."""
        try:
            project = run_svc.session.query(Project).filter_by(id=task.project_id).first()
            if project and project.inbox_completed_runs is not False:
                run_svc.create_inbox_item(
                    type="completed_run", reference_id=run.id,
                    task_id=task.id, project_id=task.project_id,
                    title=task.name or task.id,
                )
        except Exception:
            logger.debug("Failed to create completed inbox item for run %s", run.id, exc_info=True)

    @staticmethod
    def _publish_attachments(src_dir: Path, task_id: str) -> None:
        """Copy files from a step's attachments/ subdirectory into the shared task attachments."""
        dest_dir = Path.home() / ".llmflows" / "attachments" / task_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        import shutil
        for f in src_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, dest_dir / f.name)
                logger.debug("Published attachment %s for task %s", f.name, task_id)

    def _start_run(
        self, run, task_svc: TaskService, run_svc: RunService,
        flow_svc: FlowService, project,
    ) -> None:
        """Set up worktree (if enabled) and mark run as started for step orchestration."""
        task = task_svc.get(run.task_id)
        if not task:
            return

        is_git = project.is_git_repo if project.is_git_repo is not None else True
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
                    task_svc.update(task.id, task_status="stopped")
                    return
                task_svc.update(task.id, worktree_branch=branch)
                wt_path = wt_svc.get_worktree_path(branch)

            if not wt_path:
                logger.error("Worktree path not found for task %s branch %s", task.id, branch)
                run_svc.mark_completed(run.id, outcome="error")
                task_svc.update(task.id, task_status="stopped")
                return

        run_svc.mark_started(run.id)
        task_svc.update(run.task_id, task_status="in_progress")


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
