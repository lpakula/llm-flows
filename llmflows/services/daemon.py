"""System daemon -- watches all spaces, orchestrates step-per-run execution."""

import json
import logging
import signal
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import load_system_config, resolve_alias, KNOWN_LLM_PROVIDERS
from ..db.database import get_session, reset_engine
from ..db.models import Space
from .agent import AgentService
from .context import ContextService
from .executors import get_executor, StepContext
from .flow import FlowService, _normalize_step_type
from .gate import evaluate_gates, evaluate_ifs
from .browser import BrowserService
from .space import SpaceService
from .run import RunService

_step_dir_name = ContextService.step_dir_name

logger = logging.getLogger("llmflows.daemon")


def _extract_pi_cost(log_path: Path) -> tuple[float, int]:
    """Parse a Pi NDJSON log file and return (total_cost_usd, total_tokens)."""
    total_cost = 0.0
    total_tokens = 0
    try:
        with open(log_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if ev.get("type") != "message_end":
                    continue
                msg = ev.get("message", {})
                usage = msg.get("usage", {})
                cost = usage.get("cost", {})
                total_cost += cost.get("total", 0) or 0
                total_tokens += usage.get("totalTokens", 0) or 0
    except (FileNotFoundError, PermissionError, OSError):
        pass
    return round(total_cost, 6), total_tokens


_LOG_TAIL_LIMIT = 8_000


def _read_log_tail(log_path: str, limit: int = _LOG_TAIL_LIMIT) -> str:
    """Read the last *limit* characters of a log file, or return empty on failure."""
    if not log_path:
        return ""
    try:
        text = Path(log_path).read_text(errors="replace")
        if len(text) > limit:
            return "...(truncated)\n" + text[-limit:]
        return text
    except (FileNotFoundError, PermissionError, OSError):
        return ""


class Daemon:
    def __init__(self):
        self.running = False
        self._stop_event = threading.Event()
        self.config = load_system_config()
        self.poll_interval = self.config["daemon"]["poll_interval_seconds"]
        self.run_timeout_minutes = self.config["daemon"]["run_timeout_minutes"]
        from .gateway.notifications import NotificationService
        self.notifications = NotificationService()
        self.browser_service = BrowserService()
        self._telegram = None

    @staticmethod
    def _build_step_vars(base_vars: dict, space, flow_snapshot=None) -> dict:
        """Build template variables by merging base vars with flow-level variables."""
        merged = dict(base_vars)
        flow_vars = {}
        if flow_snapshot and isinstance(flow_snapshot, dict):
            flow_vars = flow_snapshot.get("variables", {})
        for k, v in flow_vars.items():
            merged[f"flow.{k}"] = v
            merged[f"space.{k}"] = v
        return merged

    def _finalize_run(self, run_id: str) -> None:
        """Cleanup run-scoped resources (browser, etc.)."""
        self.browser_service.cleanup(run_id)

    def _check_max_spend(
        self, run, space, step_run,
        working_path: Path,
        run_svc: RunService, flow_svc: FlowService,
    ) -> bool:
        """Check if the run's cumulative cost exceeds the flow's max_spend_usd. Returns True if cancelled."""
        flow = run.flow
        if not flow or not flow.max_spend_usd:
            return False
        run_svc.session.refresh(run)
        total_cost = run.cost_usd or 0
        if total_cost <= flow.max_spend_usd:
            return False
        logger.warning(
            "Run %s exceeded max spend $%.4f (limit $%.2f, step '%s')",
            run.id, total_cost, flow.max_spend_usd, step_run.step_name,
        )
        AgentService.kill_agent(space.path, run_id=run.id, flow_name=run.flow_name or "")
        run_svc.mark_step_completed(step_run.id, outcome="max_spend")
        self._finalize_run(run.id)
        run.outcome = "max_spend"
        run_svc.session.commit()
        self._launch_summary_step(
            run, working_path,
            step_run.step_position + 1, run_svc, flow_svc,
            error_context={
                "outcome": "max_spend",
                "failed_step": step_run.step_name,
                "error_details": f"Run exceeded the spending limit: ${total_cost:.4f} spent vs ${flow.max_spend_usd:.2f} allowed.",
                "log_tail": _read_log_tail(step_run.log_path or ""),
            },
        )
        self.notifications.notify("run.max_spend", {
            "flow_name": run.flow_name or run.id,
            "run_id": run.id,
            "space_name": space.name,
            "cost_usd": total_cost,
            "max_spend_usd": flow.max_spend_usd,
        })
        return True

    @staticmethod
    def _flow_requires_browser(run) -> bool:
        """Check if the run's flow snapshot declares a browser tool requirement."""
        if not run.flow_snapshot:
            return False
        try:
            snap = json.loads(run.flow_snapshot)
            tools = snap.get("requirements", {}).get("tools", [])
            return "browser" in tools
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            return False

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

        self.browser_service.cleanup_all()
        if self._telegram:
            self._telegram.stop()
        logger.info("Daemon stopped")

    def _handle_signal(self, signum, frame):
        logger.info("Received signal %d, stopping", signum)
        self.running = False
        self._stop_event.set()

    def _tick(self) -> None:
        """Single daemon tick -- check all spaces for actionable transitions."""
        reset_engine()
        session = get_session()
        try:
            space_svc = SpaceService(session)
            run_svc = RunService(session)
            flow_svc = FlowService(session)

            for space in space_svc.list_all():
                self._process_space(space, run_svc, flow_svc)
        finally:
            session.close()

    @staticmethod
    def _get_snapshot(run) -> Optional[dict]:
        """Parse and return the run's flow_snapshot as a dict, or None."""
        if not run.flow_snapshot:
            return None
        try:
            return json.loads(run.flow_snapshot)
        except (json.JSONDecodeError, TypeError):
            return None

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

    def _process_space(
        self, space,
        run_svc: RunService, flow_svc: FlowService,
    ) -> None:
        """Process a single space: orchestrate active runs step-by-step, pick up pending."""
        working_path = Path(space.path)

        active_runs = run_svc.get_active_by_space(space.id)

        for run in active_runs:
            if run.paused_at:
                continue

            active_step = run_svc.get_active_step(run.id)

            if active_step:
                if active_step.awaiting_user_at and not active_step.completed_at:
                    continue
                self._process_active_step(
                    run, space, active_step, working_path,
                    run_svc, flow_svc,
                )
            else:
                if not run.current_step:
                    self._launch_first_step(
                        run, space, working_path,
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

        active_by_flow: dict[str, int] = {}
        for r in active_runs:
            fid = r.flow_id or ""
            active_by_flow[fid] = active_by_flow.get(fid, 0) + 1

        for pending in run_svc.get_all_pending(space.id):
            fid = pending.flow_id or ""
            flow_obj = flow_svc.get(fid) if fid else None
            max_concurrent = (flow_obj.max_concurrent_runs if flow_obj and flow_obj.max_concurrent_runs else None) or 1
            current = active_by_flow.get(fid, 0)
            if current < max_concurrent:
                active_by_flow[fid] = current + 1
                self._start_run(pending, run_svc, flow_svc, space)

    def _process_active_step(
        self, run, space, step_run,
        working_path: Path,
        run_svc: RunService, flow_svc: FlowService,
    ) -> None:
        """Handle a running step: check liveness, evaluate gates on completion, advance."""
        snap_step_def = self._get_snapshot_step(run, step_run.step_name)
        step_type = _normalize_step_type(
            (snap_step_def or {}).get("step_type")
        )
        executor = get_executor(step_type)

        space_root = Path(space.path)
        artifacts_dir = ContextService.get_artifacts_dir(space_root, run.id, run.flow_name or "")
        ctx = StepContext(
            run_id=run.id,
            step_name=step_run.step_name,
            step_position=step_run.step_position,
            step_content="",
            flow_name=step_run.flow_name,
            agent=step_run.agent or "cursor",
            model=step_run.model or "",
            step_type=step_type,
            working_path=working_path,
            space_dir=Path(space.path) / ".llmflows",
            artifacts_dir=artifacts_dir,
            log_path=step_run.log_path or "",
        )
        agent_running = executor.is_running(ctx)

        if agent_running:
            if step_run.agent == "pi" and step_run.log_path:
                c, t = _extract_pi_cost(Path(step_run.log_path))
                if c or t:
                    step_run.cost_usd = c or None
                    step_run.token_count = t or None
                    run_svc.session.commit()

            if self._check_max_spend(run, space, step_run, working_path, run_svc, flow_svc):
                return

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
                    elapsed_mins = int(elapsed / 60)
                    logger.warning(
                        "Run %s timed out after %dm (step '%s')",
                        run.id, elapsed_mins, step_run.step_name,
                    )
                    AgentService.kill_agent(space.path, run_id=run.id, flow_name=run.flow_name or "")
                    run_svc.mark_step_completed(step_run.id, outcome="timeout")
                    self._finalize_run(run.id)
                    run.outcome = "timeout"
                    run_svc.session.commit()
                    self._launch_summary_step(
                        run, working_path,
                        step_run.step_position + 1, run_svc, flow_svc,
                        error_context={
                            "outcome": "timeout",
                            "failed_step": step_run.step_name,
                            "error_details": f"Run timed out after {elapsed_mins}m (limit: {self.run_timeout_minutes}m).",
                            "log_tail": _read_log_tail(step_run.log_path or ""),
                        },
                    )
                    self.notifications.notify("run.timeout", {
                        "flow_name": run.flow_name or run.id,
                        "run_id": run.id,
                        "space_name": space.name,
                        "timeout_minutes": elapsed_mins,
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

        prompt_file = Path.home() / ".llmflows" / "prompts" / f"{run.id}-{_step_dir_name(step_run.step_position, step_run.step_name)}.md"
        prompt_file.unlink(missing_ok=True)

        space_root = Path(space.path)
        step_artifacts = ContextService.get_artifacts_dir(space_root, run.id, run.flow_name or "") / \
            _step_dir_name(step_run.step_position, step_run.step_name) / "attachments"
        if step_artifacts.is_dir():
            self._publish_attachments(step_artifacts, run.id)

        if step_run.agent == "pi" and step_run.log_path:
            c, t = _extract_pi_cost(Path(step_run.log_path))
            if c or t:
                step_run.cost_usd = c or None
                step_run.token_count = t or None
                run_svc.session.commit()

        if step_type == "hitl":
            run_svc.mark_awaiting_user(step_run.id)
            inbox_item = run_svc.create_inbox_item(
                type="awaiting_user", reference_id=step_run.id,
                space_id=run.space_id,
                title=f"{run.flow_name or run.id} — {step_run.step_name} (hitl)",
            )
            logger.info(
                "Run %s step '%s' awaiting user (%s)",
                run.id, step_run.step_name, step_type,
            )
            user_message = ""
            try:
                result_file = ContextService.get_artifacts_dir(
                    space_root, run.id, run.flow_name or "",
                ) / _step_dir_name(step_run.step_position, step_run.step_name) / "_result.md"
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

        cost_usd, token_count = None, None
        if step_run.agent == "pi" and step_run.log_path:
            cost_usd, token_count = _extract_pi_cost(Path(step_run.log_path))
            cost_usd = cost_usd or None
            token_count = token_count or None
        run_svc.mark_step_completed(
            step_run.id, outcome="completed",
            cost_usd=cost_usd, token_count=token_count,
        )
        logger.info(
            "Run %s step '%s' completed%s",
            run.id, step_run.step_name,
            f" (${cost_usd:.4f}, {token_count} tokens)" if cost_usd else "",
        )

        self._post_step_completion(
            run, space, step_run, working_path, run_svc, flow_svc,
        )

    def _post_step_completion(
        self, run, space, step_run,
        working_path: Path,
        run_svc: RunService, flow_svc: FlowService,
    ) -> None:
        """Run gate evaluation and advance after a step completes (shared by sync and async paths)."""
        gate_timeout = load_system_config().get("daemon", {}).get("gate_timeout_seconds", 60)
        space_root = Path(space.path)
        artifact_dir = ContextService.get_artifacts_dir(space_root, run.id, run.flow_name or "")
        step_artifact_dir = artifact_dir / _step_dir_name(step_run.step_position, step_run.step_name)
        flow_dir = ContextService.get_flow_dir(space_root, run.flow_name or "")
        step_vars = self._build_step_vars({
            "run.id": run.id,
            "flow.name": step_run.flow_name,
            "flow_dir": str(flow_dir),
            "artifacts_dir": str(step_artifact_dir),
        }, space, flow_snapshot=self._get_snapshot(run))

        snap_step = self._get_snapshot_step(run, step_run.step_name)
        step_obj = flow_svc.get_step_obj(step_run.flow_name, step_run.step_name, space_id=run.space_id)
        step_src = snap_step or step_obj
        max_retries = None
        step_allow_max = False
        if step_src:
            max_retries = step_src.get("max_gate_retries") if snap_step else getattr(step_obj, 'max_gate_retries', None)
            step_allow_max = bool(step_src.get("allow_max") if snap_step else getattr(step_obj, 'allow_max', False))

        gates = list(snap_step.get("gates", []) if snap_step else (step_obj.get_gates() if step_obj else []))

        if step_run.step_name != "__summarizer__":
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
                    self._finalize_run(run.id)
                    run.outcome = "interrupted"
                    run_svc.session.commit()
                    self._launch_summary_step(
                        run, working_path,
                        step_run.step_position + 1, run_svc, flow_svc,
                        error_context={
                            "outcome": "interrupted",
                            "failed_step": step_run.step_name,
                            "error_details": f"Step '{step_run.step_name}' failed gate checks after {retry_count} retries.",
                            "log_tail": _read_log_tail(step_run.log_path or ""),
                        },
                    )
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
        space = run_svc.session.query(Space).filter_by(id=run.space_id).first()
        flow_dir = ContextService.get_flow_dir(Path(space.path), run.flow_name or "")
        step_vars = self._build_step_vars({
            "run.id": run.id,
            "flow.name": current_flow,
            "flow_dir": str(flow_dir),
        }, space, flow_snapshot=self._get_snapshot(run))

        if current_step_name == "__summarizer__":
            artifacts_dir = ContextService.get_artifacts_dir(Path(space.path), run.id, run.flow_name or "")
            summary = ContextService.read_summary_artifact(artifacts_dir)
            outcome = run.outcome or "completed"
            logger.info("Run %s completed (outcome=%s)", run.id, outcome)
            self._finalize_run(run.id)
            run_svc.mark_completed(run.id, outcome=outcome, summary=summary)
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
            next_step_name = flow_svc.get_next_step(current_flow, current_step_name, space_id=run.space_id)

        if not next_step_name:
            self._launch_summary_step(
                run, working_path,
                next_position, run_svc, flow_svc,
            )
            return

        while next_step_name:
            snap_step = self._get_snapshot_step(run, next_step_name)
            step_obj = flow_svc.get_step_obj(next_flow, next_step_name, space_id=run.space_id)
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
                nxt = flow_svc.get_next_step(next_flow, next_step_name, space_id=run.space_id)
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
        self, run, space, working_path: Path,
        run_svc: RunService, flow_svc: FlowService,
    ) -> None:
        """Launch the first step of a run that has been started but has no steps yet."""
        flow_name = run.flow_name
        if not flow_name:
            logger.error("Run %s has no flow_name, cannot launch", run.id)
            self._finalize_run(run.id)
            run_svc.mark_completed(run.id, outcome="error")
            return

        if not run.flow_snapshot:
            snapshot = flow_svc.build_flow_snapshot(flow_name, space_id=run.space_id)
            if not snapshot:
                logger.error("Flow '%s' not found for run %s", flow_name, run.id)
                self._finalize_run(run.id)
                run_svc.mark_completed(run.id, outcome="error")
                return
            run.flow_snapshot = json.dumps(snapshot)
            run_svc.session.commit()

        gate_timeout = load_system_config().get("daemon", {}).get("gate_timeout_seconds", 60)
        step_vars = self._build_step_vars({
            "run.id": run.id, "flow.name": flow_name,
        }, space, flow_snapshot=self._get_snapshot(run))

        steps = self._get_snapshot_steps(run)
        if not steps:
            logger.error("Flow '%s' has no steps for run %s", flow_name, run.id)
            self._finalize_run(run.id)
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

    def _launch_step(
        self, run, working_path: Path,
        step_name: str, step_position: int, flow_name: str,
        run_svc: RunService, flow_svc: FlowService,
        gate_failures: Optional[list[dict]] = None,
        force_alias: Optional[str] = None,
    ) -> None:
        """Create a StepRun, render prompt, and launch executor for a step."""
        snap_step = self._get_snapshot_step(run, step_name)
        step_obj = flow_svc.get_step_obj(flow_name, step_name, space_id=run.space_id)
        step_content = ((snap_step or {}).get("content", "") or (step_obj.content if step_obj else "") or "").rstrip()

        space = run_svc.session.query(Space).filter_by(id=run.space_id).first()
        space_root = Path(space.path)
        artifacts_dir = ContextService.get_artifacts_dir(space_root, run.id, run.flow_name or "")
        step_artifact_dir = artifacts_dir / _step_dir_name(step_position, step_name)
        flow_dir = ContextService.get_flow_dir(space_root, run.flow_name or "")
        step_vars = self._build_step_vars({
            "run.id": run.id,
            "flow.name": flow_name,
            "flow_dir": str(flow_dir),
            "artifacts_dir": str(step_artifact_dir),
        }, space, flow_snapshot=self._get_snapshot(run))
        for sr in run_svc.list_step_runs(run.id):
            if sr.completed_at and sr.user_response:
                step_vars[f"steps.{sr.step_name}.user_response"] = sr.user_response
        if step_content:
            from .gate import _interpolate
            step_content = _interpolate(step_content, step_vars)

        step_type = _normalize_step_type(
            (snap_step or {}).get("step_type")
            or getattr(step_obj, 'step_type', None)
        )

        alias_name = force_alias or (snap_step or {}).get("agent_alias") or getattr(step_obj, 'agent_alias', None) or "normal"
        alias_type = "code" if step_type == "code" else "pi"
        try:
            resolved_agent, resolved_model = resolve_alias(run_svc.session, alias_type, alias_name)
            if alias_type == "pi" and resolved_agent in KNOWN_LLM_PROVIDERS:
                if "/" not in resolved_model:
                    resolved_model = f"{resolved_agent}/{resolved_model}"
                resolved_agent = "pi"
        except ValueError as exc:
            logger.error(
                "Run %s step '%s': %s — aborting run",
                run.id, step_name, exc,
            )
            self._finalize_run(run.id)
            run.outcome = "error"
            run_svc.session.commit()
            self._launch_summary_step(
                run, working_path,
                step_position, run_svc, flow_svc,
                error_context={
                    "outcome": "error",
                    "failed_step": step_name,
                    "error_details": str(exc),
                    "log_tail": "",
                },
            )
            return

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

        user_responses = []
        for sr in run_svc.list_step_runs(run.id):
            if sr.completed_at and sr.user_response:
                snap_def = self._get_snapshot_step(run, sr.step_name)
                sr_step_type = _normalize_step_type(
                    (snap_def or {}).get("step_type")
                )
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
            for info in SkillService.resolve_skills(space.path, skill_names):
                skill_refs.append({"name": info.name, "description": info.description, "path": info.path})

        extra_env: dict[str, str] = {}
        browser_config = load_system_config().get("browser", {})
        if self._flow_requires_browser(run) and browser_config.get("enabled", False):
            headless = browser_config.get("headless", True)
            try:
                ws = self.browser_service.ensure_browser(run.id, headless=headless)
                extra_env["BROWSER_WS_ENDPOINT"] = ws
                extra_env["BROWSER_ARTIFACTS_DIR"] = str(step_artifact_dir)
            except Exception:
                logger.exception("Failed to start browser for run %s", run.id)

        space_dir = Path(space.path) / ".llmflows"
        executor = get_executor(step_type)
        ctx = StepContext(
            run_id=run.id,
            step_name=step_name,
            step_position=step_position,
            step_content=step_content,
            flow_name=flow_name,
            agent=resolved_agent,
            model=resolved_model,
            step_type=step_type,
            working_path=working_path,
            space_dir=space_dir,
            artifacts_dir=artifacts_dir,
            gate_failures=gate_failures,
            resume_prompt=resume_prompt,
            attempt=attempt,
            user_responses=user_responses,
            space_variables=self._get_snapshot(run).get("variables", {}) if self._get_snapshot(run) else {},
            skills=skill_refs,
            extra_env=extra_env,
        )
        result = executor.launch(ctx)

        if result.success:
            if result.prompt_content:
                run_svc.set_step_prompt(step_run.id, result.prompt_content)
            if result.log_path:
                run_svc.set_step_log_path(step_run.id, result.log_path)
            logger.info(
                "Launched step '%s' (pos=%d, type=%s, agent=%s, model=%s) for run %s",
                step_name, step_position, step_type, resolved_agent, resolved_model,
                run.id,
            )

            if result.is_sync:
                run_svc.mark_step_completed(step_run.id, outcome="completed")
                logger.info("Run %s step '%s' completed (sync)", run.id, step_name)

                if step_type == "hitl":
                    run_svc.mark_awaiting_user(step_run.id)
                    inbox_item = run_svc.create_inbox_item(
                        type="awaiting_user", reference_id=step_run.id,
                        space_id=run.space_id,
                        title=f"{run.flow_name or run.id} — {step_name} (hitl)",
                    )
                    user_message = result.output or ""
                    self.notifications.notify("step.awaiting_user", {
                        "flow_name": run.flow_name or run.id,
                        "run_id": run.id,
                        "step_name": step_name,
                        "step_run_id": step_run.id,
                        "step_type": step_type,
                        "inbox_id": inbox_item.id,
                        "user_message": user_message,
                    })
                else:
                    self._post_step_completion(
                        run, space, step_run, working_path,
                        run_svc, flow_svc,
                    )
        else:
            logger.error(
                "Failed to launch step '%s' for run %s",
                step_name, run.id,
            )
            run_svc.mark_step_completed(step_run.id, outcome="error")
            self._finalize_run(run.id)
            run.outcome = "error"
            run_svc.session.commit()
            self._launch_summary_step(
                run, working_path,
                step_run.step_position + 1, run_svc, flow_svc,
                error_context={
                    "outcome": "error",
                    "failed_step": step_name,
                    "error_details": f"Failed to launch agent for step '{step_name}'.",
                    "log_tail": _read_log_tail(step_run.log_path or ""),
                },
            )

    def _launch_summary_step(
        self, run, working_path: Path,
        step_position: int, run_svc: RunService, flow_svc: FlowService,
        error_context: dict | None = None,
    ) -> None:
        """Launch the auto-appended summary step.

        When *error_context* is provided the error summary template is used
        instead of the normal one, giving the AI context about the failure.
        """
        space = run_svc.session.query(Space).filter_by(id=run.space_id).first()
        space_root = Path(space.path)
        artifacts_dir = ContextService.get_artifacts_dir(space_root, run.id, run.flow_name or "")
        ctx = ContextService(working_path / ".llmflows")
        summarizer_language = load_system_config().get("daemon", {}).get("summarizer_language", "English")

        if error_context:
            summary_content = ctx.render_error_summary_step({
                "artifacts_dir": str(artifacts_dir),
                "summarizer_language": summarizer_language,
                **error_context,
            })
        else:
            summary_content = ctx.render_summary_step({
                "artifacts_dir": str(artifacts_dir),
                "summarizer_language": summarizer_language,
            })

        try:
            summary_agent, resolved_model = resolve_alias(run_svc.session, "pi", "mini")
        except ValueError:
            logger.warning("No 'mini' alias configured — skipping summary step for run %s", run.id)
            outcome = run.outcome or "completed"
            self._finalize_run(run.id)
            run_svc.mark_completed(run.id, outcome=outcome, summary="")
            self._maybe_create_completed_inbox(run, run_svc)
            return

        flow_label = run.flow_name or "default"
        step_run = run_svc.create_step_run(
            run_id=run.id,
            step_name="__summarizer__",
            step_position=step_position,
            flow_name=flow_label,
            agent=summary_agent,
            model=resolved_model,
        )

        run_svc.update_run_step(run.id, "__summarizer__", flow_label)

        space_dir = Path(space.path) / ".llmflows"
        agent_svc = AgentService(space_dir, working_path)

        launched, prompt_content, log_path = agent_svc.prepare_and_launch_step(
            run_id=run.id,
            step_name="__summarizer__",
            step_position=step_position,
            step_content=summary_content,
            flow_name=flow_label,
            model=resolved_model,
            agent=summary_agent,
            space_variables=self._get_snapshot(run).get("variables", {}) if self._get_snapshot(run) else {},
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
            artifacts_dir = ContextService.get_artifacts_dir(Path(space.path), run.id, run.flow_name or "")
            summary = ContextService.read_summary_artifact(artifacts_dir)
            self._finalize_run(run.id)
            outcome = run.outcome or "completed"
            run_svc.mark_completed(run.id, outcome=outcome, summary=summary)
            self._maybe_create_completed_inbox(run, run_svc)

    def _maybe_create_completed_inbox(self, run, run_svc: RunService) -> None:
        """Create a completed_run inbox item and send notification if the space opts in."""
        inbox_id = None
        try:
            inbox_item = run_svc.create_inbox_item(
                type="completed_run", reference_id=run.id,
                space_id=run.space_id,
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
            "cost_usd": run.cost_usd,
            "duration_seconds": run.duration_seconds,
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
        flow_svc: FlowService, space,
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
