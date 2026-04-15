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

logger = logging.getLogger("llmflows.daemon")


class Daemon:
    def __init__(self):
        self.running = False
        self._stop_event = threading.Event()
        self.config = load_system_config()
        self.poll_interval = self.config["daemon"]["poll_interval_seconds"]
        self.run_timeout_minutes = self.config["daemon"]["run_timeout_minutes"]
        from .gateway.notifications import NotificationService
        self.notifications = NotificationService()
        self._telegram = None

    @staticmethod
    def _build_step_vars(base_vars: dict, project) -> dict:
        """Build template variables by merging base vars with project-level variables."""
        merged = dict(base_vars)
        for k, v in project.get_variables().items():
            merged[f"project.{k}"] = v
        return merged

    def _maybe_start_telegram(self) -> None:
        """Start the Telegram bot if configured."""
        tg_config = self.config.get("telegram", {})
        if not tg_config.get("enabled") or not tg_config.get("bot_token"):
            return
        try:
            from .gateway.telegram import TelegramBot
            from ..db.database import get_session

            self._telegram = TelegramBot(
                config=tg_config,
                session_factory=get_session,
                notification_service=self.notifications,
            )
            self._telegram.start_background()
            logger.info("Telegram bot started")
        except Exception:
            logger.exception("Failed to start Telegram bot")

    def start(self) -> None:
        """Start the daemon loop."""
        self.running = True
        self._stop_event.clear()
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        self._maybe_start_telegram()

        logger.info("Daemon started (poll every %ds)", self.poll_interval)

        while self.running:
            try:
                self._tick()
            except Exception:
                logger.exception("Error in daemon tick")
            self._stop_event.wait(self.poll_interval)

        if self._telegram:
            self._telegram.stop()
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
            run_svc = RunService(session)
            flow_svc = FlowService(session)

            for project in project_svc.list_all():
                self._process_project(project, run_svc, flow_svc)
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

    # ── Core orchestration ────────────────────────────────────────────────────

    def _process_project(
        self, project,
        run_svc: RunService, flow_svc: FlowService,
    ) -> None:
        """Process a single project: orchestrate active runs step-by-step, pick up pending."""
        working_path = Path(project.path)

        active_runs = run_svc.get_active_by_project(project.id)

        for run in active_runs:
            if run.paused_at:
                continue

            active_step = run_svc.get_active_step(run.id)

            if active_step:
                if active_step.awaiting_user_at and not active_step.completed_at:
                    continue
                self._process_active_step(
                    run, project, active_step, working_path,
                    run_svc, flow_svc,
                )
            else:
                if not run.current_step:
                    self._launch_first_step(
                        run, project, working_path,
                        run_svc, flow_svc,
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
                            run, working_path,
                            run.current_step, pos, run.flow_name or "",
                            run_svc, flow_svc,
                        )
                    else:
                        self._relaunch_current_step(
                            run, working_path,
                            run_svc, flow_svc,
                        )

        max_concurrent = project.max_concurrent_tasks or 1
        active_count = len(active_runs)

        for pending in run_svc.get_all_pending(project.id):
            if active_count < max_concurrent:
                active_count += 1
                self._start_run(pending, run_svc, flow_svc, project)

    def _relaunch_current_step(
        self, run, working_path: Path,
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
            run, working_path,
            step_name, position, flow_name,
            run_svc, flow_svc,
        )

    def _process_active_step(
        self, run, project, step_run,
        working_path: Path,
        run_svc: RunService, flow_svc: FlowService,
    ) -> None:
        """Handle a running step: check liveness, evaluate gates on completion, advance."""
        agent_running = AgentService.is_agent_running(project.path, run_id=run.id)

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
                        "Run %s timed out after %dm (step '%s')",
                        run.id, int(elapsed / 60), step_run.step_name,
                    )
                    AgentService.kill_agent(project.path, run_id=run.id)
                    run_svc.mark_step_completed(step_run.id, outcome="timeout")
                    run_svc.mark_completed(run.id, outcome="timeout")
                    self.notifications.notify("run.timeout", {
                        "flow_name": run.flow_name or run.id,
                        "run_id": run.id,
                        "project_name": project.name,
                        "timeout_minutes": int(elapsed / 60),
                    })
            return

        run_svc.session.refresh(step_run)
        if step_run.completed_at:
            return

        run_svc.session.refresh(run)
        if run.completed_at:
            logger.info(
                "Run %s was cancelled while step '%s' was stopping, skipping gate evaluation",
                run.id, step_run.step_name,
            )
            run_svc.mark_step_completed(step_run.id, outcome="cancelled")
            return

        prompt_file = Path.home() / ".llmflows" / "prompts" / f"{run.id}-{step_run.step_position:02d}-{step_run.step_name}.md"
        prompt_file.unlink(missing_ok=True)

        project_root = Path(project.path)
        step_artifacts = ContextService.get_artifacts_dir(project_root, run.id) / \
            f"{step_run.step_position:02d}-{step_run.step_name}" / "attachments"
        if step_artifacts.is_dir():
            self._publish_attachments(step_artifacts, run.id)

        snap_step_def = self._get_snapshot_step(run, step_run.step_name)
        step_type = (snap_step_def or {}).get("step_type", "agent")
        if step_type == "manual":
            run_svc.mark_awaiting_user(step_run.id)
            inbox_item = run_svc.create_inbox_item(
                type="awaiting_user", reference_id=step_run.id,
                project_id=run.project_id,
                title=f"{run.flow_name or run.id} — {step_run.step_name} (manual)",
            )
            logger.info(
                "Run %s step '%s' awaiting user (%s)",
                run.id, step_run.step_name, step_type,
            )
            user_message = ""
            try:
                result_file = ContextService.get_artifacts_dir(
                    project_root, run.id,
                ) / f"{step_run.step_position:02d}-{step_run.step_name}" / "_result.md"
                if result_file.exists():
                    user_message = result_file.read_text().strip()
            except (PermissionError, OSError):
                pass
            self.notifications.notify("step.awaiting_user", {
                "flow_name": run.flow_name or run.id,
                "run_id": run.id,
                "step_name": step_run.step_name,
                "step_run_id": step_run.id,
                "step_type": step_type,
                "inbox_id": inbox_item.id,
                "user_message": user_message,
            })
            return

        run_svc.mark_step_completed(step_run.id, outcome="completed")
        logger.info(
            "Run %s step '%s' completed",
            run.id, step_run.step_name,
        )

        if step_run.step_name == "__one_shot__":
            artifacts_dir = ContextService.get_artifacts_dir(Path(project.path), run.id)
            summary = ContextService.read_summary_artifact(artifacts_dir)
            logger.info("Run %s one-shot completed", run.id)
            run_svc.mark_completed(run.id, outcome="completed", summary=summary)
            self._maybe_create_completed_inbox(run, run_svc)
            return

        gate_timeout = load_system_config().get("daemon", {}).get("gate_timeout_seconds", 60)
        project_root = Path(project.path)
        artifact_dir = ContextService.get_artifacts_dir(project_root, run.id)
        step_artifact_dir = artifact_dir / f"{step_run.step_position:02d}-{step_run.step_name}"
        step_vars = self._build_step_vars({
            "run.id": run.id,
            "flow.name": step_run.flow_name,
            "artifacts_dir": str(step_artifact_dir),
        }, project)

        snap_step = self._get_snapshot_step(run, step_run.step_name)
        step_obj = flow_svc.get_step_obj(step_run.flow_name, step_run.step_name, project_id=run.project_id)
        step_src = snap_step or step_obj
        max_retries = None
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

        run_svc.session.refresh(run)
        if run.completed_at:
            logger.info(
                "Run %s was cancelled before gate evaluation for step '%s', skipping",
                run.id, step_run.step_name,
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
                run_svc.session.refresh(run)
                if run.completed_at:
                    logger.info(
                        "Run %s cancelled during gate evaluation for step '%s', skipping retry",
                        run.id, step_run.step_name,
                    )
                    run_svc.mark_step_completed(step_run.id, outcome="cancelled")
                    return

                if unlimited or retry_count < max_retries:
                    is_last_retry = not unlimited and (retry_count + 1 >= max_retries)
                    use_max = step_allow_max and is_last_retry
                    limit_str = "∞" if unlimited else str(max_retries)
                    logger.warning(
                        "Run %s step '%s' gate failed (retry %d/%s%s), retrying",
                        run.id, step_run.step_name,
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
                        run, working_path,
                        step_run.step_name, step_run.step_position,
                        step_run.flow_name, run_svc, flow_svc,
                        gate_failures=gate_failure_info,
                        force_alias="max" if use_max else None,
                    )
                    return
                else:
                    logger.error(
                        "Run %s step '%s' gate failed after %d retries, marking interrupted",
                        run.id, step_run.step_name, retry_count,
                    )
                    run_svc.mark_completed(run.id, outcome="interrupted")
                    self.notifications.notify("run.completed", {
                        "flow_name": run.flow_name or run.id,
                        "run_id": run.id,
                        "outcome": "interrupted",
                        "summary": f"Step '{step_run.step_name}' failed gate checks after {retry_count} retries.",
                    })
                    return

        self._advance_to_next_step(
            run, working_path,
            step_run.step_name, step_run.step_position, step_run.flow_name,
            run_svc, flow_svc,
        )

    def _advance_to_next_step(
        self, run, working_path: Path,
        current_step_name: str, current_position: int, current_flow: str,
        run_svc: RunService, flow_svc: FlowService,
    ) -> None:
        """Determine the next step and launch it, or complete the run."""
        gate_timeout = load_system_config().get("daemon", {}).get("gate_timeout_seconds", 60)
        project = run_svc.session.query(Project).filter_by(id=run.project_id).first()
        step_vars = self._build_step_vars({
            "run.id": run.id,
            "flow.name": current_flow,
        }, project)

        if current_step_name == "__summary__":
            artifacts_dir = ContextService.get_artifacts_dir(Path(project.path), run.id)
            summary = ContextService.read_summary_artifact(artifacts_dir)
            logger.info("Run %s completed", run.id)
            run_svc.mark_completed(run.id, outcome="completed", summary=summary)
            self._maybe_create_completed_inbox(run, run_svc)
            return

        next_flow = current_flow
        next_position = current_position + 1

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
                run, working_path,
                next_position, run_svc, flow_svc,
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
                "Run %s: IF conditions not met for step '%s', skipping",
                run.id, next_step_name,
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
                run, working_path,
                next_position, run_svc, flow_svc,
            )
            return

        self._launch_step(
            run, working_path,
            next_step_name, next_position, next_flow,
            run_svc, flow_svc,
        )

    def _launch_first_step(
        self, run, project, working_path: Path,
        run_svc: RunService, flow_svc: FlowService,
    ) -> None:
        """Launch the first step of a run that has been started but has no steps yet."""
        flow_name = run.flow_name
        if not flow_name:
            self._launch_one_shot(
                run, working_path,
                run_svc, flow_svc,
            )
            return

        if run.one_shot:
            if flow_name and flow_svc.has_human_steps(flow_name, project_id=run.project_id):
                logger.warning(
                    "Run %s: one-shot disabled — flow '%s' contains manual/prompt steps",
                    run.id, flow_name,
                )
            else:
                self._launch_one_shot(
                    run, working_path,
                    run_svc, flow_svc,
                )
                return

        if not run.flow_snapshot:
            snapshot = flow_svc.build_flow_snapshot(flow_name, project_id=run.project_id)
            if not snapshot:
                logger.error("Flow '%s' not found for run %s", flow_name, run.id)
                run_svc.mark_completed(run.id, outcome="error")
                return
            run.flow_snapshot = json.dumps(snapshot)
            run_svc.session.commit()

        gate_timeout = load_system_config().get("daemon", {}).get("gate_timeout_seconds", 60)
        step_vars = self._build_step_vars({
            "run.id": run.id, "flow.name": flow_name,
        }, project)

        steps = self._get_snapshot_steps(run)
        if not steps:
            logger.error("Flow '%s' has no steps for run %s", flow_name, run.id)
            run_svc.mark_completed(run.id, outcome="error")
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
            logger.info("Run %s: IF conditions not met for step '%s', skipping",
                        run.id, first_step)
            try:
                idx = steps.index(first_step)
                nxt = steps[idx + 1] if idx + 1 < len(steps) else None
            except ValueError:
                nxt = None
            position += 1
            first_step = nxt

        if not first_step:
            self._launch_summary_step(
                run, working_path,
                position, run_svc, flow_svc,
            )
            return

        self._launch_step(
            run, working_path,
            first_step, position, flow_name,
            run_svc, flow_svc,
        )

    def _launch_one_shot(
        self, run, working_path: Path,
        run_svc: RunService, flow_svc: FlowService,
    ) -> None:
        """Assemble all steps into a single prompt and launch one agent."""
        gate_timeout = load_system_config().get("daemon", {}).get("gate_timeout_seconds", 60)
        project = run_svc.session.query(Project).filter_by(id=run.project_id).first()

        collected_steps = []
        active_flow = run.flow_name or "default"

        if run.flow_name:
            step_vars = self._build_step_vars({
                "run.id": run.id, "flow.name": run.flow_name,
            }, project)
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

        project_root = Path(project.path)
        artifacts_dir = ContextService.get_artifacts_dir(project_root, run.id)
        ctx = ContextService(working_path / ".llmflows")
        summary_content = ctx.render_summary_step({
            "artifacts_dir": str(artifacts_dir),
        })
        collected_steps.append({
            "name": "summary",
            "content": summary_content,
            "gates": [],
        })

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

        prompt_content = ctx.render_one_shot({
            "run_id": run.id,
            "flow_name": run.flow_name or "",
            "steps": collected_steps,
            "artifacts_dir": str(artifacts_dir),
        })

        project_dir = Path(project.path) / ".llmflows"
        agent_svc = AgentService(project_dir, working_path)

        wt_llmflows = working_path / ".llmflows" / run.id
        wt_llmflows.mkdir(parents=True, exist_ok=True)

        prompts_dir = Path.home() / ".llmflows" / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = prompts_dir / f"{run.id}-00-__one_shot__.md"
        prompt_file.write_text(prompt_content)

        log_file = wt_llmflows / f"agent-{run.id}-00-__one_shot__.log"
        pid_file = wt_llmflows / "agent.pid"

        launched = agent_svc._launch_agent(
            working_path, prompt_file, log_file, pid_file,
            model=resolved_model, agent=resolved_agent,
            project_variables=project.get_variables(),
        )

        if launched:
            run_svc.set_step_prompt(step_run.id, prompt_content)
            run_svc.set_step_log_path(step_run.id, str(log_file))
            logger.info(
                "Launched one-shot run %s (agent=%s, model=%s, steps=%d)",
                run.id, resolved_agent, resolved_model, len(collected_steps),
            )
        else:
            logger.error("Failed to launch one-shot agent for run %s", run.id)
            run_svc.mark_step_completed(step_run.id, outcome="error")
            run_svc.mark_completed(run.id, outcome="error")

    def _launch_step(
        self, run, working_path: Path,
        step_name: str, step_position: int, flow_name: str,
        run_svc: RunService, flow_svc: FlowService,
        gate_failures: Optional[list[dict]] = None,
        force_alias: Optional[str] = None,
    ) -> None:
        """Create a StepRun, render prompt, and launch agent for a step."""
        snap_step = self._get_snapshot_step(run, step_name)
        step_obj = flow_svc.get_step_obj(flow_name, step_name, project_id=run.project_id)
        step_content = ((snap_step or {}).get("content", "") or (step_obj.content if step_obj else "") or "").rstrip()

        project = run_svc.session.query(Project).filter_by(id=run.project_id).first()
        project_root = Path(project.path)
        artifacts_dir = ContextService.get_artifacts_dir(project_root, run.id)
        step_artifact_dir = artifacts_dir / f"{step_position:02d}-{step_name}"
        step_vars = self._build_step_vars({
            "run.id": run.id,
            "flow.name": flow_name,
            "artifacts_dir": str(step_artifact_dir),
        }, project)
        for sr in run_svc.list_step_runs(run.id):
            if sr.completed_at and sr.user_response:
                step_vars[f"steps.{sr.step_name}.user_response"] = sr.user_response
        if step_content:
            from .gate import _interpolate
            step_content = _interpolate(step_content, step_vars)

        step_type = (snap_step or {}).get("step_type") or getattr(step_obj, 'step_type', None) or "agent"

        alias_name = force_alias or (snap_step or {}).get("agent_alias") or getattr(step_obj, 'agent_alias', None) or "standard"
        try:
            resolved_agent, resolved_model = resolve_alias(run_svc.session, alias_name)
        except ValueError:
            resolved_agent, resolved_model = "cursor", ""

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

        project_dir = Path(project.path) / ".llmflows"
        agent_svc = AgentService(project_dir, working_path)

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

        skill_names = (snap_step or {}).get("skills") or (step_obj.get_skills() if step_obj else []) or []
        skill_refs: list[dict] = []
        if skill_names:
            from .skill import SkillService
            for info in SkillService.resolve_skills(project.path, skill_names):
                skill_refs.append({"name": info.name, "description": info.description, "path": info.path})

        launched, prompt_content, log_path = agent_svc.prepare_and_launch_step(
            run_id=run.id,
            step_name=step_name,
            step_position=step_position,
            step_content=step_content,
            flow_name=flow_name,
            model=resolved_model,
            agent=resolved_agent,
            gate_failures=gate_failures,
            resume_prompt=resume_prompt,
            attempt=attempt,
            user_responses=user_responses,
            step_type=step_type,
            project_variables=project.get_variables(),
            skills=skill_refs,
        )

        if launched:
            if prompt_content:
                run_svc.set_step_prompt(step_run.id, prompt_content)
            if log_path:
                run_svc.set_step_log_path(step_run.id, log_path)
            logger.info(
                "Launched step '%s' (pos=%d, agent=%s, model=%s) for run %s",
                step_name, step_position, resolved_agent, resolved_model,
                run.id,
            )
        else:
            logger.error(
                "Failed to launch step '%s' for run %s",
                step_name, run.id,
            )
            run_svc.mark_step_completed(step_run.id, outcome="error")
            run_svc.mark_completed(run.id, outcome="error")

    def _launch_summary_step(
        self, run, working_path: Path,
        step_position: int, run_svc: RunService, flow_svc: FlowService,
    ) -> None:
        """Launch the auto-appended summary step."""
        project = run_svc.session.query(Project).filter_by(id=run.project_id).first()
        project_root = Path(project.path)
        artifacts_dir = ContextService.get_artifacts_dir(project_root, run.id)
        ctx = ContextService(working_path / ".llmflows")
        summary_content = ctx.render_summary_step({
            "artifacts_dir": str(artifacts_dir),
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

        project_dir = Path(project.path) / ".llmflows"
        agent_svc = AgentService(project_dir, working_path)

        launched, prompt_content, log_path = agent_svc.prepare_and_launch_step(
            run_id=run.id,
            step_name="__summary__",
            step_position=step_position,
            step_content=summary_content,
            flow_name=flow_label,
            model=resolved_model,
            agent=resolved_agent,
            project_variables=project.get_variables(),
        )

        if launched:
            if prompt_content:
                run_svc.set_step_prompt(step_run.id, prompt_content)
            if log_path:
                run_svc.set_step_log_path(step_run.id, log_path)
            logger.info("Launched summary step for run %s", run.id)
        else:
            logger.error("Failed to launch summary step for run %s", run.id)
            run_svc.mark_step_completed(step_run.id, outcome="error")
            artifacts_dir = ContextService.get_artifacts_dir(Path(project.path), run.id)
            summary = ContextService.read_summary_artifact(artifacts_dir)
            run_svc.mark_completed(run.id, outcome="completed", summary=summary)
            self._maybe_create_completed_inbox(run, run_svc)

    def _maybe_create_completed_inbox(self, run, run_svc: RunService) -> None:
        """Create a completed_run inbox item and send notification if the project opts in."""
        inbox_id = None
        try:
            inbox_item = run_svc.create_inbox_item(
                type="completed_run", reference_id=run.id,
                project_id=run.project_id,
                title=run.flow_name or run.id,
            )
            inbox_id = inbox_item.id
        except Exception:
            logger.debug("Failed to create completed inbox item for run %s", run.id, exc_info=True)
        self.notifications.notify("run.completed", {
            "flow_name": run.flow_name or run.id,
            "run_id": run.id,
            "outcome": run.outcome or "completed",
            "summary": run.summary or "",
            "inbox_id": inbox_id,
        })

    @staticmethod
    def _publish_attachments(src_dir: Path, run_id: str) -> None:
        """Copy files from a step's attachments/ subdirectory into the run-scoped attachments dir."""
        dest_dir = Path.home() / ".llmflows" / "attachments" / run_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        import shutil
        for f in src_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, dest_dir / f.name)
                logger.debug("Published attachment %s for run %s", f.name, run_id)

    def _start_run(
        self, run, run_svc: RunService,
        flow_svc: FlowService, project,
    ) -> None:
        """Mark run as started for step orchestration."""
        logger.info("Starting run %s (flow=%s)", run.id, run.flow_name)
        run_svc.mark_started(run.id)


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
