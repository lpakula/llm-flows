"""System daemon -- host orchestrator for containerised flow runs.

The daemon never executes agents or gates itself: every run is executed by a
RunDaemon inside its own Docker container. The host side only manages
container lifecycle (launch, monitor, cleanup), schedules, and notifications.
Keeping agent execution out of this process is a deliberate isolation
boundary — nothing a flow does can touch the host system.
"""

import logging
import signal
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import load_system_config, SYSTEM_DIR
from ..db.database import get_session, reset_engine
from .context import ContextService
from .flow import FlowService
from .space import SpaceService
from .run import RunService

logger = logging.getLogger("llmflows.daemon")


class Daemon:
    #: Container launch attempts per run before giving up (retried on
    #: subsequent daemon ticks while the run stays active, so a transient
    #: failure — e.g. a port conflict — doesn't instantly error the run).
    MAX_LAUNCH_ATTEMPTS = 3

    #: Seconds between orphan-container cleanup sweeps.
    CONTAINER_CLEANUP_INTERVAL = 300

    def __init__(self):
        self.running = False
        self._stop_event = threading.Event()
        self._reexec = False
        self.config = load_system_config()
        self.poll_interval = self.config["daemon"]["poll_interval_seconds"]
        self._launch_failures: dict[str, int] = {}
        self._last_container_cleanup: float = 0.0
        self._browser_active_runs: set[str] = set()
        self._keep_awake_proc: Optional[subprocess.Popen] = None
        from .gateway.channel import ChannelManager
        self.notifications = ChannelManager()

    @staticmethod
    def _keep_awake_command() -> list[str] | None:
        """Return the platform-specific command to inhibit sleep, or None."""
        if sys.platform == "darwin":
            return ["caffeinate", "-s", "-i"]
        if sys.platform == "linux":
            return [
                "systemd-inhibit",
                "--what=idle:sleep",
                "--who=llmflows",
                "--why=Daemon is running",
                "--mode=block",
                "sleep", "infinity",
            ]
        return None

    def _start_keep_awake(self) -> None:
        """Start a subprocess to prevent the system from sleeping."""
        if not self.config.get("daemon", {}).get("keep_awake", False):
            return
        cmd = self._keep_awake_command()
        if cmd is None:
            logger.info("keep_awake is enabled but not supported on %s", sys.platform)
            return
        try:
            self._keep_awake_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("Started keep-awake (pid=%d, cmd=%s)", self._keep_awake_proc.pid, cmd[0])
        except FileNotFoundError:
            logger.warning("%s binary not found — keep_awake will have no effect", cmd[0])
        except OSError:
            logger.warning("Failed to start keep-awake process", exc_info=True)

    def _stop_keep_awake(self) -> None:
        """Terminate the keep-awake subprocess if running."""
        if self._keep_awake_proc is None:
            return
        if self._keep_awake_proc.poll() is not None:
            self._keep_awake_proc = None
            return
        try:
            self._keep_awake_proc.terminate()
            self._keep_awake_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._keep_awake_proc.kill()
            self._keep_awake_proc.wait(timeout=2)
        except OSError:
            pass
        logger.info("Stopped keep-awake process")
        self._keep_awake_proc = None

    def _finalize_run(self, run_id: str) -> None:
        """Cleanup run-scoped resources."""
        self._launch_failures.pop(run_id, None)
        if run_id in self._browser_active_runs:
            self._browser_active_runs.discard(run_id)
            if not self._browser_active_runs:
                from .browser_host import stop_host_chrome
                stop_host_chrome()

    def _track_browser_run(self, run_id: str) -> None:
        """Mark a run as actively using the host browser."""
        self._browser_active_runs.add(run_id)

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
        signal.signal(signal.SIGUSR2, self._handle_reexec)

        self._start_keep_awake()
        self._warn_if_runner_image_missing()

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
        self._stop_keep_awake()

        from .network import cleanup_network
        try:
            cleanup_network()
        except Exception:
            logger.debug("Runner network cleanup failed (ignoring)", exc_info=True)

        if self._reexec:
            self._do_reexec()

        logger.info("Daemon stopped")

    @staticmethod
    def _warn_if_runner_image_missing() -> None:
        """Log when the runner image is missing (built lazily on first flow run)."""
        from .container import image_exists, image_name

        try:
            tag = image_name()
            if not image_exists(tag):
                logger.warning(
                    "Runner image %s not found — it will be built when the next flow run starts",
                    tag,
                )
        except Exception:
            logger.exception("Runner image check failed (ignoring)")

    def _handle_signal(self, signum, frame):
        logger.info("Received signal %d, stopping", signum)
        self.running = False
        self._stop_event.set()

    def _handle_gateway_restart(self, signum, frame):
        logger.info("Received SIGUSR1, restarting gateway channels")
        self.restart_channels()

    def _handle_reexec(self, signum, frame):
        logger.info("Received SIGUSR2, will re-exec after shutdown")
        self._reexec = True
        self.running = False
        self._stop_event.set()

    def _do_reexec(self) -> None:
        """Replace the current process with a fresh daemon to pick up new code."""
        import os

        self._stop_keep_awake()
        remove_pid_file()
        bin_path = Path(sys.prefix) / "bin" / "llmflows"
        if not bin_path.is_file():
            import shutil
            bin_path = Path(shutil.which("llmflows") or str(bin_path))
        args = [str(bin_path), "daemon", "start", "--foreground"]
        logger.info("Re-exec: %s", " ".join(args))
        os.execv(str(bin_path), args)

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

            self._maybe_cleanup_containers(session)
        finally:
            session.close()

    def _maybe_cleanup_containers(self, session) -> None:
        """Periodically remove orphan containers and stale runner images."""
        import time as _time

        now = _time.monotonic()
        if now - self._last_container_cleanup < self.CONTAINER_CLEANUP_INTERVAL:
            return
        self._last_container_cleanup = now

        from ..db.models import FlowRun as FlowRunModel
        from .container import cleanup_runner_artifacts

        tracked = {
            cid for (cid,) in session.query(FlowRunModel.container_id)
            .filter(FlowRunModel.container_id.isnot(None))
            .all()
            if cid
        }
        try:
            cleanup_runner_artifacts(skip=tracked)
        except Exception:
            logger.exception("Runner artifact cleanup failed (ignoring)")

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

    # ── Core orchestration ────────────────────────────────────────────────────

    def _process_space(
        self, space,
        run_svc: RunService, flow_svc: FlowService,
    ) -> None:
        """Process a single space: manage runner containers for flow runs.

        Step-level logic (agents, gates, post-run analysis) is handled by
        RunDaemon inside each runner container. The orchestrator only manages
        container lifecycle and sends notifications when containers finish.
        """
        from .container import (
            is_container_alive, get_container_exit_code,
            get_container_logs, remove_container, commit_container_to_flow_image,
            flow_version_from_snapshot,
        )

        for run in run_svc.get_runs_with_container(space.id):
            if is_container_alive(run.container_id):
                continue

            run_id = run.id
            container_id = run.container_id
            exit_code = get_container_exit_code(container_id)

            run = run_svc.get(run_id)
            if not run or not run.container_id:
                continue

            if not run.completed_at:
                logger.warning(
                    "Runner container for run %s exited (code=%s) but run not completed — marking error",
                    run.id, exit_code,
                )
                log_tail = get_container_logs(container_id, tail=20).strip()
                summary = f"Runner container exited unexpectedly (exit code {exit_code})."
                if log_tail:
                    summary += f"\n\nContainer log tail:\n{log_tail[-2000:]}"
                run_svc.mark_completed(run.id, outcome="error", summary=summary)

            if run.completed_at and run.outcome == "completed" and run.flow_id:
                if exit_code not in (None, 0):
                    logger.warning(
                        "Run %s completed in DB but container exit code was %s — "
                        "committing runner image anyway",
                        run.id, exit_code,
                    )
                flow_version = flow_version_from_snapshot(run.flow_snapshot)
                ok, commit_err = commit_container_to_flow_image(
                    container_id, run.flow_id, flow_version,
                )
                if ok:
                    logger.info(
                        "Saved runner image for flow %s after run %s",
                        run.flow_id, run.id,
                    )
                else:
                    logger.warning(
                        "Failed to save runner image for flow %s: %s",
                        run.flow_id, commit_err,
                    )

            remove_container(container_id)
            run.container_id = None
            run_svc.session.commit()

            self._close_open_steps(run, run_svc)

            if run.completed_at:
                self._handle_completed_run_notifications(run, space, run_svc)
                self._maybe_create_improvement_inbox(run, space, run_svc)
                self._finalize_run(run.id)

        active_runs = run_svc.get_active_by_space(space.id)

        for run in active_runs:
            if run.paused_at:
                continue

            if run.container_id:
                continue

            active_step = run_svc.get_active_step(run.id)
            if active_step and active_step.awaiting_user_at and not active_step.completed_at:
                continue
            if not run.container_id and run.started_at and not run.completed_at:
                self._launch_run_container(run, space, run_svc, flow_svc)

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

    @staticmethod
    def _close_open_steps(run, run_svc: RunService) -> None:
        """Close any StepRun left open after the run's container exited.

        The container is gone, so no agent process for this run can still be
        alive. Leftover open steps (e.g. a post-run step interrupted mid-way)
        would otherwise stay "running" in the UI forever.
        """
        from ..db.models import StepRun as StepRunModel

        open_steps = (
            run_svc.session.query(StepRunModel)
            .filter_by(flow_run_id=run.id)
            .filter(StepRunModel.started_at.isnot(None))
            .filter(StepRunModel.completed_at.is_(None))
            .all()
        )
        for step_run in open_steps:
            if run.outcome == "cancelled":
                outcome = "cancelled"
            elif run.outcome in (None, "completed"):
                outcome = "completed"
            else:
                outcome = "error"
            logger.info(
                "Closing open step '%s' (outcome=%s) after container exit for run %s",
                step_run.step_name, outcome, run.id,
            )
            run_svc.mark_step_completed(step_run.id, outcome=outcome)

    def _handle_launch_failure(
        self, run, error: str, run_svc: RunService,
    ) -> None:
        """Track a failed container launch; error the run only after retries.

        Keeping the run active (started, no container) between attempts means
        it still counts toward ``max_concurrent_runs``, so failed launches
        can't cause a burst of extra runs for the same flow.
        """
        attempts = self._launch_failures.get(run.id, 0) + 1
        self._launch_failures[run.id] = attempts
        if attempts < self.MAX_LAUNCH_ATTEMPTS:
            logger.warning(
                "Container launch failed for run %s (attempt %d/%d), retrying next tick: %s",
                run.id, attempts, self.MAX_LAUNCH_ATTEMPTS, error,
            )
            return
        self._launch_failures.pop(run.id, None)
        logger.error(
            "Container launch failed for run %s after %d attempts: %s",
            run.id, attempts, error,
        )
        self._finalize_run(run.id)
        run_svc.mark_completed(
            run.id, outcome="error",
            summary=f"Container launch failed after {attempts} attempts: {error}",
        )

    def _launch_run_container(
        self, run, space,
        run_svc: RunService, flow_svc: FlowService,
    ) -> None:
        """Launch a runner container for an active run that has no container."""
        import os
        from .container import launch_run_container
        from .browser_host import flow_needs_host_browser

        if flow_needs_host_browser(run.flow_snapshot, run_svc.session):
            self._track_browser_run(run.id)

        host_home = os.environ.get("LLMFLOWS_HOST_HOME", str(SYSTEM_DIR))
        container_id, error = launch_run_container(
            run_id=run.id,
            space_path=space.path,
            flow_snapshot=run.flow_snapshot,
            host_home=host_home,
            flow_id=run.flow_id,
        )
        if container_id:
            self._launch_failures.pop(run.id, None)
            run.container_id = container_id
            run_svc.session.commit()
            logger.info("Launched runner container %s for run %s", container_id[:12], run.id)
        else:
            self._handle_launch_failure(run, error, run_svc)

    def _handle_completed_run_notifications(self, run, space, run_svc: RunService) -> None:
        """Send notifications for a completed run (after container exits).

        The RunDaemon may already have created the completed_run inbox item
        from inside the container — reuse it instead of duplicating.
        """
        from ..db.models import InboxItem as InboxItemModel

        space_root = Path(space.path)
        artifacts_dir = ContextService.get_artifacts_dir(space_root, run.id, run.flow_name or "")
        inbox_message = ContextService.read_inbox_message(artifacts_dir)
        if not inbox_message:
            return
        try:
            inbox_item = (
                run_svc.session.query(InboxItemModel)
                .filter_by(type="completed_run", reference_id=run.id)
                .filter(InboxItemModel.archived_at.is_(None))
                .first()
            )
            if not inbox_item:
                inbox_item = run_svc.create_inbox_item(
                    type="completed_run", reference_id=run.id,
                    space_id=run.space_id,
                    title=run.flow_name or run.id,
                )
            self.notifications.notify("run.completed", {
                "flow_name": run.flow_name or run.id,
                "run_id": run.id,
                "outcome": run.outcome or "completed",
                "summary": run.summary or "",
                "inbox_message": inbox_message,
                "inbox_id": inbox_item.id,
                "cost_usd": run.cost_usd,
                "duration_seconds": run.duration_seconds,
            })
        except Exception:
            logger.debug("Failed to send completion notification for run %s", run.id, exc_info=True)

    def _maybe_create_improvement_inbox(self, run, space, run_svc: RunService) -> None:
        """Create a flow_improvement inbox item when the post-run step proposed one.

        The post-run analysis runs inside the container; the notification has
        to be sent from the host, where the gateway channels live.
        """
        from ..db.models import InboxItem as InboxItemModel

        space_root = Path(space.path)
        artifacts_dir = ContextService.get_artifacts_dir(space_root, run.id, run.flow_name or "")
        improvement = ContextService.read_improvement(artifacts_dir)
        if not improvement:
            return

        already_exists = (
            run_svc.session.query(InboxItemModel)
            .filter_by(type="flow_improvement", reference_id=run.id)
            .filter(InboxItemModel.archived_at.is_(None))
            .first()
        )
        if already_exists:
            return
        logger.info(
            "Run %s post-run found flow improvement proposal, creating inbox item",
            run.id,
        )
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

    def _start_run(
        self, run, run_svc: RunService,
        flow_svc: FlowService, space,
    ) -> None:
        """Mark run as started, build snapshot, and launch a runner container."""
        import json as _json
        import os

        logger.info("Starting run %s (flow=%s)", run.id, run.flow_name)

        if not run.flow_snapshot:
            snapshot = flow_svc.build_flow_snapshot(run.flow_name, space_id=run.space_id)
            if snapshot:
                run.flow_snapshot = _json.dumps(snapshot)
                run_svc.session.commit()

        run_svc.mark_started(run.id)

        from .container import launch_run_container
        from .browser_host import flow_needs_host_browser

        if flow_needs_host_browser(run.flow_snapshot, run_svc.session):
            self._track_browser_run(run.id)

        host_home = os.environ.get("LLMFLOWS_HOST_HOME", str(SYSTEM_DIR))
        container_id, error = launch_run_container(
            run_id=run.id,
            space_path=space.path,
            flow_snapshot=run.flow_snapshot,
            host_home=host_home,
            flow_id=run.flow_id,
        )
        if container_id:
            self._launch_failures.pop(run.id, None)
            run.container_id = container_id
            run_svc.session.commit()
        else:
            self._handle_launch_failure(run, error, run_svc)


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
