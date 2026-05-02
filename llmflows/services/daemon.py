"""System daemon -- watches all spaces, orchestrates step-per-run execution."""

import json
import logging
import signal
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import load_system_config, resolve_alias, KNOWN_LLM_PROVIDERS, SYSTEM_DIR
from ..db.database import get_session, reset_engine
from ..db.models import Space
from .agent import AgentService
from .context import ContextService
from .executors import get_executor, StepContext
from .flow import FlowService, _normalize_step_type
from .gate import evaluate_gates, evaluate_ifs
from .mcp import get_mcp_servers
from .space import SpaceService
from .run import RunService

_step_dir_name = ContextService.step_dir_name

logger = logging.getLogger("llmflows.daemon")


def _register_user_responses(step_vars: dict, step_runs: list) -> None:
    """Register user responses from completed HITL steps as ``{{hitl.response.N}}``."""
    idx = 0
    for sr in step_runs:
        if sr.completed_at and sr.user_response:
            step_vars[f"hitl.response.{idx}"] = sr.user_response
            idx += 1


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
        self._browser_active_runs: set[str] = set()
        from .gateway.channel import ChannelManager
        self.notifications = ChannelManager()

    @staticmethod
    def _build_step_vars(base_vars: dict, space, flow_snapshot=None) -> dict:
        """Build template variables by merging base vars with flow-level variables."""
        merged = dict(base_vars)
        if space and hasattr(space, "path"):
            merged["space.dir"] = space.path
        flow_vars = {}
        if flow_snapshot and isinstance(flow_snapshot, dict):
            flow_vars = flow_snapshot.get("variables", {})
        for k, v in flow_vars.items():
            merged[f"flow.{k}"] = v["value"]
            merged[f"space.{k}"] = v["value"]
        return merged

    def _finalize_run(self, run_id: str) -> None:
        """Cleanup run-scoped resources."""
        if run_id in self._browser_active_runs:
            self._browser_active_runs.discard(run_id)
            if not self._browser_active_runs:
                self._kill_cdp_browser()

    def _track_browser_run(self, run_id: str) -> None:
        """Mark a run as actively using the browser."""
        self._browser_active_runs.add(run_id)

    @staticmethod
    def _kill_cdp_browser() -> None:
        """Kill the detached Chrome process listening on CDP port 9222."""
        import subprocess
        try:
            out = subprocess.check_output(
                ["lsof", "-ti", "tcp:9222"], text=True, stderr=subprocess.DEVNULL,
            ).strip()
            for pid in out.splitlines():
                pid = pid.strip()
                if pid:
                    subprocess.call(["kill", pid], stderr=subprocess.DEVNULL)
            logger.debug("Killed idle CDP browser (pids: %s)", out.replace("\n", ", "))
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

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
        self._launch_post_run_step(
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
    def _step_requires_connector(snap_step: dict | None, connector: str) -> bool:
        """Check if a snapshot step declares a specific connector requirement."""
        if not snap_step:
            return False
        return connector in snap_step.get("connectors", snap_step.get("mcp", snap_step.get("tools", [])))

    def _build_channels(self) -> list:
        """Build channel instances from config (lazy import, only if enabled)."""
        channels_config = self.config.get("channels", {})
        result = []

        tg_config = channels_config.get("telegram", {})
        if tg_config.get("enabled") and tg_config.get("bot_token"):
            try:
                from .gateway.telegram import TelegramBot
                result.append(TelegramBot(config=tg_config, session_factory=get_session))
            except Exception:
                logger.exception("Failed to create Telegram channel")

        slack_config = channels_config.get("slack", {})
        if slack_config.get("enabled") and slack_config.get("bot_token") and slack_config.get("app_token"):
            try:
                from .gateway.slack import SlackChannel
                result.append(SlackChannel(config=slack_config, session_factory=get_session))
            except Exception:
                logger.exception("Failed to create Slack channel")

        return result

    def restart_channels(self) -> None:
        """Rebuild and restart all channels from current config."""
        self.config = load_system_config()
        new_channels = self._build_channels()
        self.notifications.restart_all(new_channels)

    def start(self) -> None:
        """Start the daemon loop."""
        self.running = True
        self._stop_event.clear()
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGUSR1, self._handle_gateway_restart)

        for ch in self._build_channels():
            self.notifications.register(ch)
        self.notifications.start_all()

        logger.info("Daemon started (poll every %ds)", self.poll_interval)

        while self.running:
            try:
                self._tick()
            except Exception:
                logger.exception("Error in daemon tick")
            self._stop_event.wait(self.poll_interval)

        self.notifications.stop_all()
        logger.info("Daemon stopped")

    def _handle_signal(self, signum, frame):
        logger.info("Received signal %d, stopping", signum)
        self.running = False
        self._stop_event.set()

    def _handle_gateway_restart(self, signum, frame):
        logger.info("Received SIGUSR1, restarting gateway channels")
        self.restart_channels()

    def _tick(self) -> None:
        """Single daemon tick -- check all spaces for actionable transitions."""
        reset_engine()
        session = get_session()
        try:
            space_svc = SpaceService(session)
            run_svc = RunService(session)
            flow_svc = FlowService(session)

            self._check_schedules(flow_svc, run_svc, session)

            for space in space_svc.list_all():
                self._process_space(space, run_svc, flow_svc)
        finally:
            session.close()

    def _check_schedules(
        self, flow_svc: FlowService, run_svc: RunService, session,
    ) -> None:
        """Enqueue runs for flows whose schedule_next_at has passed."""
        from ..db.models import Flow as FlowModel
        now = datetime.now(timezone.utc)
        due_flows = (
            session.query(FlowModel)
            .filter(
                FlowModel.schedule_enabled == True,  # noqa: E712
                FlowModel.schedule_cron.isnot(None),
                FlowModel.schedule_next_at.isnot(None),
                FlowModel.schedule_next_at <= now,
            )
            .all()
        )
        for flow in due_flows:
            try:
                warnings = flow_svc.validate_flow(flow.id, space_id=flow.space_id)
                blockers = [w for w in warnings if w["warning_type"] in ("missing_alias", "missing_variable")]
                if blockers:
                    logger.warning(
                        "Skipping scheduled run for flow %s (%s): %s",
                        flow.name, flow.id,
                        "; ".join(w["message"] for w in blockers),
                    )
                else:
                    run = run_svc.enqueue(flow.space_id, flow.id)
                    logger.info(
                        "Scheduled run %s for flow %s (%s)",
                        run.id, flow.name, flow.id,
                    )
            except Exception:
                logger.exception("Failed to enqueue scheduled run for flow %s", flow.id)
            try:
                tz_str = flow.schedule_timezone or "UTC"
                flow.schedule_next_at = self._compute_next_schedule(flow.schedule_cron, tz_str)
                session.commit()
            except Exception:
                logger.exception("Failed to compute next schedule for flow %s", flow.id)

    @staticmethod
    def _compute_next_schedule(cron_expr: str, tz_str: str = "UTC"):
        from croniter import croniter
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_str) if tz_str != "UTC" else timezone.utc
        now_local = datetime.now(tz)
        cron = croniter(cron_expr, now_local)
        next_local = cron.get_next(datetime)
        return next_local.astimezone(timezone.utc).replace(tzinfo=None)

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
    def _env_variables_from_snapshot(snap: Optional[dict]) -> dict[str, str]:
        """Extract only env-flagged variables from a snapshot as ``{KEY: value}``."""
        if not snap:
            return {}
        return {k: v["value"] for k, v in snap.get("variables", {}).items() if v.get("is_env")}

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

        self._process_async_post_run_steps(space, run_svc, flow_svc)

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

    def _process_async_post_run_steps(
        self, space, run_svc: RunService, flow_svc: FlowService,
    ) -> None:
        """Monitor post-run steps that are running on already-completed runs.

        These steps were launched asynchronously after the run completed.
        Failures here never affect the run's outcome.
        """
        from ..db.models import StepRun as StepRunModel, FlowRun as FlowRunModel

        post_run_steps = (
            run_svc.session.query(StepRunModel)
            .join(FlowRunModel, StepRunModel.flow_run_id == FlowRunModel.id)
            .filter(
                FlowRunModel.space_id == space.id,
                FlowRunModel.completed_at.isnot(None),
                StepRunModel.step_name == "__post_run__",
                StepRunModel.started_at.isnot(None),
                StepRunModel.completed_at.is_(None),
            )
            .all()
        )

        working_path = Path(space.path)
        for step_run in post_run_steps:
            run = run_svc.get(step_run.flow_run_id)
            if not run:
                continue
            try:
                self._process_active_step(
                    run, space, step_run, working_path,
                    run_svc, flow_svc,
                )
            except Exception:
                logger.exception(
                    "Error processing async post-run step for run %s (ignoring)",
                    run.id,
                )
                try:
                    run_svc.mark_step_completed(step_run.id, outcome="error")
                except Exception:
                    pass

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

        # Grace period: if the step was started very recently, don't trust a
        # "not running" signal — the process may not have fully spawned yet.
        if not agent_running and step_run.started_at:
            started = step_run.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - started).total_seconds()
            if age < 15:
                logger.debug(
                    "Run %s step '%s' appears dead after %.0fs — too early, skipping",
                    run.id, step_run.step_name, age,
                )
                return

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
                    self._launch_post_run_step(
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

        started = step_run.started_at
        if started and started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        step_age = (datetime.now(timezone.utc) - started).total_seconds() if started else 0
        logger.info(
            "Run %s step '%s' agent stopped (ran %.0fs, pid_file=%s)",
            run.id, step_run.step_name, step_age,
            step_run.log_path or "?",
        )

        run_svc.session.refresh(step_run)
        if step_run.completed_at:
            return

        run_svc.session.refresh(run)
        if run.completed_at and step_run.step_name != "__post_run__":
            logger.info(
                "Run %s was cancelled while step '%s' was stopping, skipping gate evaluation",
                run.id, step_run.step_name,
            )
            run_svc.mark_step_completed(step_run.id, outcome="cancelled")
            return

        prompt_file = SYSTEM_DIR / "prompts" / f"{run.id}-{_step_dir_name(step_run.step_position, step_run.step_name)}.md"
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
            from .context import HITL_FILE
            step_dir = ContextService.get_artifacts_dir(
                space_root, run.id, run.flow_name or "",
            ) / _step_dir_name(step_run.step_position, step_run.step_name)
            hitl_file = step_dir / HITL_FILE

            if not hitl_file.exists():
                run_svc.mark_step_completed(step_run.id, outcome="completed")
                logger.warning(
                    "Run %s step '%s' missing hitl.md, relaunching",
                    run.id, step_run.step_name,
                )
                self._launch_step(
                    run, working_path,
                    step_run.step_name, step_run.step_position,
                    step_run.flow_name, run_svc, flow_svc,
                    gate_failures=[{
                        "command": f'test -f "{hitl_file}"',
                        "message": f"hitl step must produce {HITL_FILE} in the step artifacts directory",
                        "output": "",
                    }],
                )
                return

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
                user_message = hitl_file.read_text().strip()
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
            "flow.dir": str(flow_dir),
            "run.dir": str(artifact_dir),
            "step.dir": str(step_artifact_dir),
            "attachment.dir": str(SYSTEM_DIR / "attachments" / run.id),
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

        if step_run.step_name != "__post_run__":
            gates.insert(0, {
                "command": f'test -d "{step_artifact_dir}" && test "$(ls -A "{step_artifact_dir}")"',
                "message": f"Step '{step_run.step_name}' must produce output artifacts in {step_artifact_dir}",
            })

        run_svc.session.refresh(run)
        if run.completed_at and step_run.step_name != "__post_run__":
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
                    self._launch_post_run_step(
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
        space_root = Path(space.path)
        artifacts_dir = ContextService.get_artifacts_dir(space_root, run.id, run.flow_name or "")
        flow_dir = ContextService.get_flow_dir(space_root, run.flow_name or "")
        step_vars = self._build_step_vars({
            "run.id": run.id,
            "flow.name": current_flow,
            "flow.dir": str(flow_dir),
            "run.dir": str(artifacts_dir),
            "attachment.dir": str(SYSTEM_DIR / "attachments" / run.id),
        }, space, flow_snapshot=self._get_snapshot(run))
        _register_user_responses(step_vars, run_svc.list_step_runs(run.id))

        if current_step_name == "__post_run__":
            self._handle_post_run_completion(
                run, run_svc, flow_svc, working_path, current_position,
            )
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
            self._complete_run(run, run_svc)
            return

        while next_step_name:
            snap_step = self._get_snapshot_step(run, next_step_name)
            step_obj = flow_svc.get_step_obj(next_flow, next_step_name, space_id=run.space_id)
            step_src = snap_step or step_obj
            if not step_src:
                break
            ifs = snap_step.get("ifs", []) if snap_step else (step_obj.get_ifs() if step_obj else [])
            step_vars["step.dir"] = str(artifacts_dir / _step_dir_name(next_position, next_step_name))
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
            self._complete_run(run, run_svc)
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
        space_root = Path(space.path)
        artifacts_dir = ContextService.get_artifacts_dir(space_root, run.id, flow_name)
        flow_dir = ContextService.get_flow_dir(space_root, flow_name)
        step_vars = self._build_step_vars({
            "run.id": run.id, "flow.name": flow_name,
            "flow.dir": str(flow_dir),
            "run.dir": str(artifacts_dir),
            "attachment.dir": str(SYSTEM_DIR / "attachments" / run.id),
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
            step_vars["step.dir"] = str(artifacts_dir / _step_dir_name(position, first_step))
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
            self._complete_run(run, run_svc)
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
            "flow.dir": str(flow_dir),
            "run.dir": str(artifacts_dir),
            "step.dir": str(step_artifact_dir),
            "attachment.dir": str(SYSTEM_DIR / "attachments" / run.id),
        }, space, flow_snapshot=self._get_snapshot(run))
        _register_user_responses(step_vars, run_svc.list_step_runs(run.id))
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
            self._launch_post_run_step(
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
        _ss = snap_step or {}
        needed_connectors = _ss.get("connectors", _ss.get("mcp", _ss.get("tools", [])))
        if needed_connectors:
            if "browser" in (needed_connectors or []):
                self._track_browser_run(run.id)
            servers = get_mcp_servers(needed_connectors)
            if servers:
                extra_env["MCP_SERVERS"] = json.dumps(servers)
                extra_env["BROWSER_ARTIFACTS_DIR"] = str(step_artifact_dir)

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
            space_variables=self._env_variables_from_snapshot(self._get_snapshot(run)),
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
                    user_message = ""
                    try:
                        from .context import HITL_FILE
                        hitl_file = artifacts_dir / _step_dir_name(step_position, step_name) / HITL_FILE
                        if hitl_file.exists():
                            user_message = hitl_file.read_text().strip()
                    except (PermissionError, OSError):
                        pass
                    user_message = user_message or result.output or ""
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
            self._launch_post_run_step(
                run, working_path,
                step_run.step_position + 1, run_svc, flow_svc,
                error_context={
                    "outcome": "error",
                    "failed_step": step_name,
                    "error_details": f"Failed to launch agent for step '{step_name}'.",
                    "log_tail": _read_log_tail(step_run.log_path or ""),
                },
            )

    def _complete_run(
        self, run, run_svc: RunService,
    ) -> None:
        """Complete the run immediately, then launch post-run analysis async.

        The post-run step analyses flow health and proposes improvements.
        It runs after the run is already marked completed — failures in the
        post-run step never affect the run's outcome.
        """
        space = run_svc.session.query(Space).filter_by(id=run.space_id).first()
        working_path = Path(space.path)
        space_root = Path(space.path)
        artifacts_dir = ContextService.get_artifacts_dir(space_root, run.id, run.flow_name or "")

        summary = (
            ContextService.read_summary_artifact(artifacts_dir)
            or ContextService.read_inbox_message(artifacts_dir)
            or ContextService.read_last_step_result(artifacts_dir)
        )
        outcome = run.outcome or "completed"
        logger.info("Run %s completed (outcome=%s)", run.id, outcome)
        self._finalize_run(run.id)
        run_svc.mark_completed(run.id, outcome=outcome, summary=summary)
        self._maybe_create_completed_inbox(run, run_svc, artifacts_dir)

        last_step_runs = run_svc.list_step_runs(run.id)
        last_pos = max((sr.step_position for sr in last_step_runs), default=-1) + 1
        flow_svc = FlowService(run_svc.session)
        try:
            self._launch_post_run_step(
                run, working_path, last_pos, run_svc, flow_svc,
            )
        except Exception:
            logger.exception("Post-run step failed to launch for run %s (run already completed)", run.id)

    def _launch_post_run_step(
        self, run, working_path: Path,
        step_position: int, run_svc: RunService, flow_svc: FlowService,
        error_context: dict | None = None,
    ) -> None:
        """Launch the post-run analysis step.

        Analyses the run for errors/inefficiencies and optionally proposes
        flow improvements via ``improvement.md`` + ``flow.json``.
        """
        space = run_svc.session.query(Space).filter_by(id=run.space_id).first()
        space_root = Path(space.path)
        artifacts_dir = ContextService.get_artifacts_dir(space_root, run.id, run.flow_name or "")
        ctx = ContextService(working_path / ".llmflows")
        daemon_config = load_system_config().get("daemon", {})
        language = daemon_config.get("post_run_language") or daemon_config.get("summarizer_language", "English")

        flow_version = 1
        flow = run.flow
        if flow:
            flow_version = flow.version or 1

        flow_dir = ContextService.get_flow_dir(space_root, run.flow_name or "")
        memory_files = ContextService.read_rejected_proposals(flow_dir)

        post_run_vars = {
            "run": {"id": run.id, "dir": str(artifacts_dir)},
            "flow_name": run.flow_name or "",
            "flow_version": flow_version,
            "outcome": run.outcome or "completed",
            "language": language,
            "memory_files": memory_files,
        }
        if error_context:
            post_run_vars.update(error_context)

        post_run_content = ctx.render_post_run_step(post_run_vars)

        try:
            post_run_agent, resolved_model = resolve_alias(run_svc.session, "pi", "mini")
            if post_run_agent in KNOWN_LLM_PROVIDERS:
                if "/" not in resolved_model:
                    resolved_model = f"{post_run_agent}/{resolved_model}"
                post_run_agent = "pi"
        except ValueError:
            logger.warning("No 'mini' alias configured — skipping post-run step for run %s", run.id)
            return

        flow_label = run.flow_name or "default"
        step_run = run_svc.create_step_run(
            run_id=run.id,
            step_name="__post_run__",
            step_position=step_position,
            flow_name=flow_label,
            agent=post_run_agent,
            model=resolved_model,
        )

        run_svc.update_run_step(run.id, "__post_run__", flow_label)

        space_dir = Path(space.path) / ".llmflows"
        agent_svc = AgentService(space_dir, working_path)

        launched, prompt_content, log_path = agent_svc.prepare_and_launch_step(
            run_id=run.id,
            step_name="__post_run__",
            step_position=step_position,
            step_content=post_run_content,
            flow_name=flow_label,
            model=resolved_model,
            agent=post_run_agent,
            space_variables=self._env_variables_from_snapshot(self._get_snapshot(run)),
        )

        if launched:
            if prompt_content:
                run_svc.set_step_prompt(step_run.id, prompt_content)
            if log_path:
                run_svc.set_step_log_path(step_run.id, log_path)
            logger.info("Launched post-run step for run %s", run.id)
        else:
            logger.error("Failed to launch post-run step for run %s (run already completed, ignoring)", run.id)
            run_svc.mark_step_completed(step_run.id, outcome="error")

    def _handle_post_run_completion(
        self, run, run_svc: RunService, flow_svc: FlowService,
        working_path: Path, step_position: int,
    ) -> None:
        """Check post-run artifacts for a flow proposal.

        The run may still have ``completed_at = NULL`` (error/interrupt paths
        set outcome but skip ``mark_completed``).  We must finalise it here so
        it stops being treated as active.
        """
        space = run_svc.session.query(Space).filter_by(id=run.space_id).first()
        space_root = Path(space.path)
        artifacts_dir = ContextService.get_artifacts_dir(space_root, run.id, run.flow_name or "")

        new_summary = ContextService.read_summary_artifact(artifacts_dir)
        if new_summary and run.summary != new_summary:
            run.summary = new_summary
            run_svc.session.commit()

        from ..db.models import StepRun as StepRunModel, InboxItem as InboxItemModel
        step_run = (
            run_svc.session.query(StepRunModel)
            .filter_by(flow_run_id=run.id, step_name="__post_run__")
            .first()
        )
        if step_run and not step_run.completed_at:
            run_svc.mark_step_completed(step_run.id, outcome="completed")

        if not run.completed_at:
            run_svc.mark_completed(run.id, outcome=run.outcome or "completed")

        flow_json = ContextService.read_flow_json(artifacts_dir)
        if flow_json:
            already_exists = (
                run_svc.session.query(InboxItemModel)
                .filter_by(type="flow_improvement", reference_id=run.id)
                .filter(InboxItemModel.archived_at.is_(None))
                .first()
            )
            if not already_exists:
                logger.info(
                    "Run %s post-run found flow improvement proposal, creating inbox item",
                    run.id,
                )
                improvement = ContextService.read_improvement(artifacts_dir)
                try:
                    inbox_item = run_svc.create_inbox_item(
                        type="flow_improvement",
                        reference_id=run.id,
                        space_id=run.space_id,
                        title=f"{run.flow_name or run.id} — Flow Improvement Proposal",
                    )
                    self.notifications.notify("flow.improvement", {
                        "flow_name": run.flow_name or run.id,
                        "run_id": run.id,
                        "inbox_id": inbox_item.id,
                        "improvement": improvement,
                    })
                except Exception:
                    logger.exception("Failed to create flow improvement inbox for run %s", run.id)
        logger.info("Post-run step finished for run %s", run.id)

    def _maybe_create_completed_inbox(self, run, run_svc: RunService, artifacts_dir: Path) -> None:
        """Create a completed_run inbox item and send notification only if inbox.md exists."""
        inbox_message = ContextService.read_inbox_message(artifacts_dir)
        if not inbox_message:
            return
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
            "inbox_message": inbox_message,
            "inbox_id": inbox_id,
            "cost_usd": run.cost_usd,
            "duration_seconds": run.duration_seconds,
        })

    @staticmethod
    def _publish_attachments(src_dir: Path, run_id: str) -> None:
        """Copy files from a step's attachments/ subdirectory into the run-scoped attachments dir."""
        dest_dir = SYSTEM_DIR / "attachments" / run_id
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
    pid_file = SYSTEM_DIR / "daemon.pid"
    pid_file.unlink(missing_ok=True)
