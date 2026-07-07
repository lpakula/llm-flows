"""Per-run daemon -- executes a single flow run inside a container, then exits.

This is the counterpart to the orchestrator daemon. The orchestrator launches
a container for each run; inside that container, RunDaemon picks up the run,
progresses through steps (launch agent -> poll -> gates -> advance), and exits
when the run completes or errors.

Agents are still launched via subprocess.Popen inside the container -- the
isolation boundary is the container itself, not individual agent processes.
"""

import json
import logging
import signal
import time
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
from .run import RunService

_step_dir_name = ContextService.step_dir_name

logger = logging.getLogger("llmflows.run_daemon")


def _register_user_responses(step_vars: dict, step_runs: list) -> None:
    """Register user responses from completed HITL steps as ``{{hitl.response.N}}``."""
    idx = 0
    for sr in step_runs:
        if sr.completed_at and sr.user_response:
            step_vars[f"hitl.response.{idx}"] = sr.user_response
            idx += 1


def _read_log_tail(log_path: str, limit: int = 8_000) -> str:
    """Read the last *limit* characters of a log file."""
    if not log_path:
        return ""
    try:
        text = Path(log_path).read_text(errors="replace")
        if len(text) > limit:
            return "...(truncated)\n" + text[-limit:]
        return text
    except (FileNotFoundError, PermissionError, OSError):
        return ""


def _extract_pi_cost(log_path: Path) -> tuple[float, int]:
    """Parse a Pi NDJSON log file and return (total_cost_usd, total_tokens)."""
    total_cost = 0.0
    total_tokens = 0
    try:
        size = log_path.stat().st_size
        if size > 100 * 1024 * 1024:
            return 0.0, 0
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


class RunDaemon:
    """Executes a single flow run inside a container, then exits."""

    CONTAINER_WORKSPACE = "/workspace"

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.config = load_system_config()
        self.poll_interval = self.config["daemon"].get("poll_interval_seconds", 5)
        self.run_timeout_minutes = self.config["daemon"].get("run_timeout_minutes", 0)
        self.max_log_size_bytes = self.config["daemon"].get("max_log_size_mb", 500) * 1024 * 1024
        self._cost_offsets: dict[str, tuple[int, float, int]] = {}
        self._running = True
        self._space_id: Optional[str] = None

    def _get_space(self, session) -> "Space":
        """Get the space with path overridden to the container workspace.

        Returns a detached (expunged) Space object so the path change
        doesn't get flushed to the DB.
        """
        space = session.query(Space).filter_by(id=self._space_id).first()
        session.expunge(space)
        space.path = self.CONTAINER_WORKSPACE
        return space

    def run(self) -> int:
        """Block until the run completes. Returns 0 on success, 1 on error."""
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        logger.info("RunDaemon starting for run %s", self.run_id)

        session = get_session()
        try:
            run_svc = RunService(session)
            flow_svc = FlowService(session)

            run = run_svc.get(self.run_id)
            if not run:
                logger.error("Run %s not found", self.run_id)
                return 1

            space = session.query(Space).filter_by(id=run.space_id).first()
            if not space:
                logger.error("Space not found for run %s", self.run_id)
                return 1
            self._space_id = space.id

            working_path = Path(self.CONTAINER_WORKSPACE)
            session.expunge(space)
            space.path = self.CONTAINER_WORKSPACE

            if not run.started_at:
                run_svc.mark_started(self.run_id)

            while self._running:
                session.close()
                session = get_session()
                run_svc = RunService(session)
                flow_svc = FlowService(session)

                run = run_svc.get(self.run_id)
                if not run:
                    logger.error("Run %s disappeared from DB", self.run_id)
                    return 1

                if run.paused_at:
                    time.sleep(self.poll_interval)
                    session.close()
                    continue

                space = self._get_space(session)
                working_path = Path(self.CONTAINER_WORKSPACE)

                active_step = run_svc.get_active_step(run.id)

                if run.completed_at and not active_step:
                    logger.info("Run %s already completed (outcome=%s)", self.run_id, run.outcome)
                    return 0

                if active_step:
                    if active_step.awaiting_user_at and not active_step.completed_at:
                        time.sleep(self.poll_interval)
                        session.close()
                        continue
                    self._process_active_step(
                        run, space, active_step, working_path, run_svc, flow_svc,
                    )
                else:
                    if run.completed_at:
                        # Run finished; only post-run steps may still be active.
                        time.sleep(self.poll_interval)
                    elif not run.current_step:
                        self._launch_first_step(run, space, working_path, run_svc, flow_svc)
                    else:
                        latest = run_svc.get_latest_step_run(run.id, run.current_step)
                        if latest and latest.completed_at:
                            snap_steps = self._get_snapshot_steps(run)
                            if snap_steps:
                                try:
                                    pos = snap_steps.index(run.current_step)
                                except ValueError:
                                    pos = latest.step_position
                            else:
                                pos = latest.step_position
                            self._advance_to_next_step(
                                run, working_path,
                                run.current_step, pos, run.flow_name or "",
                                run_svc, flow_svc,
                            )

                session.close()
                time.sleep(self.poll_interval)

        except Exception:
            logger.exception("RunDaemon fatal error for run %s", self.run_id)
            return 1
        finally:
            try:
                session.close()
            except Exception:
                pass

        logger.info("RunDaemon exiting for run %s", self.run_id)
        return 0

    def _handle_signal(self, signum, frame):
        logger.info("RunDaemon received signal %d, stopping", signum)
        self._running = False

    # ── Snapshot helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _get_snapshot(run) -> Optional[dict]:
        if not run.flow_snapshot:
            return None
        try:
            return json.loads(run.flow_snapshot)
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _env_variables_from_snapshot(snap: Optional[dict]) -> dict[str, str]:
        if not snap:
            return {}
        return {k: v["value"] for k, v in snap.get("variables", {}).items() if v.get("is_env")}

    @staticmethod
    def _get_snapshot_steps(run) -> list[str]:
        if not run.flow_snapshot:
            return []
        try:
            snap = json.loads(run.flow_snapshot)
            return [s["name"] for s in sorted(snap.get("steps", []), key=lambda s: s.get("position", 0))]
        except (json.JSONDecodeError, KeyError, TypeError):
            return []

    @staticmethod
    def _get_snapshot_step(run, step_name: str) -> Optional[dict]:
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
    def _build_step_vars(base_vars: dict, space, flow_snapshot=None) -> dict:
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

    # ── Cost tracking ─────────────────────────────────────────────────────────

    def _extract_pi_cost_incremental(self, log_path_str: str) -> tuple[float, int]:
        offset, total_cost, total_tokens = self._cost_offsets.get(log_path_str, (0, 0.0, 0))
        try:
            log_path = Path(log_path_str)
            size = log_path.stat().st_size
            if size <= offset:
                return round(total_cost, 6), total_tokens
            with open(log_path, "r") as f:
                f.seek(offset)
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
                new_offset = f.tell()
            self._cost_offsets[log_path_str] = (new_offset, total_cost, total_tokens)
        except (FileNotFoundError, PermissionError, OSError):
            pass
        return round(total_cost, 6), total_tokens

    # ── Step execution ────────────────────────────────────────────────────────

    def _process_active_step(
        self, run, space, step_run,
        working_path: Path,
        run_svc: RunService, flow_svc: FlowService,
    ) -> None:
        """Handle a running step: check liveness, evaluate gates on completion, advance."""
        snap_step_def = self._get_snapshot_step(run, step_run.step_name)
        step_type = _normalize_step_type((snap_step_def or {}).get("step_type"))
        executor = get_executor(step_type)

        space_root = Path(space.path)
        artifacts_dir = ContextService.get_artifacts_dir(space_root, run.id, run.flow_name or "")
        ctx = StepContext(
            run_id=run.id,
            step_name=step_run.step_name,
            step_position=step_run.step_position,
            step_content="",
            flow_name=step_run.flow_name,
            agent=step_run.agent or "pi",
            model=step_run.model or "",
            step_type=step_type,
            working_path=working_path,
            space_dir=Path(space.path) / ".llmflows",
            artifacts_dir=artifacts_dir,
            log_path=step_run.log_path or "",
        )
        agent_running = executor.is_running(ctx)

        if not agent_running and step_run.started_at:
            started = step_run.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - started).total_seconds()
            if age < 15:
                return

        if agent_running:
            if step_run.agent == "pi" and step_run.log_path:
                c, t = self._extract_pi_cost_incremental(step_run.log_path)
                if c or t:
                    step_run.cost_usd = c or None
                    step_run.token_count = t or None
                    run_svc.session.commit()

            if self._check_max_spend(run, space, step_run, working_path, run_svc, flow_svc):
                return

            if self.max_log_size_bytes and step_run.log_path and step_run.step_name != "__post_run__":
                try:
                    log_size = Path(step_run.log_path).stat().st_size
                    if log_size > self.max_log_size_bytes:
                        size_mb = log_size / (1024 * 1024)
                        limit_mb = self.max_log_size_bytes / (1024 * 1024)
                        logger.warning(
                            "Run %s step '%s' log exceeded size limit (%.0fMB > %.0fMB)",
                            run.id, step_run.step_name, size_mb, limit_mb,
                        )
                        AgentService.kill_agent(space.path, run_id=run.id, flow_name=run.flow_name or "")
                        run_svc.mark_step_completed(step_run.id, outcome="log_overflow")
                        run_svc.mark_completed(run.id, outcome="log_overflow")
                        self._launch_post_run_step(run, working_path, step_run.step_position + 1, run_svc, flow_svc, error_context={
                            "outcome": "log_overflow",
                            "failed_step": step_run.step_name,
                            "error_details": f"Agent log exceeded size limit ({size_mb:.0f}MB > {limit_mb:.0f}MB).",
                            "log_tail": _read_log_tail(step_run.log_path or ""),
                        })
                        return
                except OSError:
                    pass

            if self.run_timeout_minutes and step_run.started_at and step_run.step_name != "__post_run__":
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
                    logger.warning("Run %s timed out after %dm", run.id, elapsed_mins)
                    AgentService.kill_agent(space.path, run_id=run.id, flow_name=run.flow_name or "")
                    run_svc.mark_step_completed(step_run.id, outcome="timeout")
                    run_svc.mark_completed(run.id, outcome="timeout")
                    self._launch_post_run_step(run, working_path, step_run.step_position + 1, run_svc, flow_svc, error_context={
                        "outcome": "timeout",
                        "failed_step": step_run.step_name,
                        "error_details": f"Run timed out after {elapsed_mins}m (limit: {self.run_timeout_minutes}m).",
                        "log_tail": _read_log_tail(step_run.log_path or ""),
                    })
            return

        # Agent stopped
        started = step_run.started_at
        if started and started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        step_age = (datetime.now(timezone.utc) - started).total_seconds() if started else 0
        logger.info("Run %s step '%s' agent stopped (ran %.0fs)", run.id, step_run.step_name, step_age)

        run_svc.session.refresh(step_run)
        if step_run.completed_at:
            return

        run_svc.session.refresh(run)
        if run.completed_at and step_run.step_name != "__post_run__":
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
            c, t = self._extract_pi_cost_incremental(step_run.log_path)
            if c or t:
                step_run.cost_usd = c or None
                step_run.token_count = t or None
                run_svc.session.commit()
            self._cost_offsets.pop(step_run.log_path, None)

        if step_type == "hitl":
            from .context import HITL_FILE
            step_dir = ContextService.get_artifacts_dir(
                space_root, run.id, run.flow_name or "",
            ) / _step_dir_name(step_run.step_position, step_run.step_name)
            hitl_file = step_dir / HITL_FILE

            if not hitl_file.exists():
                run_svc.mark_step_completed(step_run.id, outcome="completed")
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
            run_svc.create_inbox_item(
                type="awaiting_user", reference_id=step_run.id,
                space_id=run.space_id,
                title=f"{run.flow_name or run.id} — {step_run.step_name} (hitl)",
            )
            logger.info("Run %s step '%s' awaiting user", run.id, step_run.step_name)
            return

        cost_usd, token_count = None, None
        if step_run.agent == "pi" and step_run.log_path:
            cost_usd, token_count = self._extract_pi_cost_incremental(step_run.log_path)
            cost_usd = cost_usd or None
            token_count = token_count or None
            self._cost_offsets.pop(step_run.log_path, None)
        run_svc.mark_step_completed(step_run.id, outcome="completed", cost_usd=cost_usd, token_count=token_count)
        logger.info("Run %s step '%s' completed", run.id, step_run.step_name)

        self._post_step_completion(run, space, step_run, working_path, run_svc, flow_svc)

    def _check_max_spend(self, run, space, step_run, working_path, run_svc, flow_svc) -> bool:
        """Check if the run's cumulative cost exceeds the flow's max_spend_usd."""
        if step_run.step_name == "__post_run__":
            return False
        flow = run.flow
        if not flow or not flow.max_spend_usd:
            return False
        run_svc.session.refresh(run)
        total_cost = run.cost_usd or 0
        if total_cost <= flow.max_spend_usd:
            return False
        logger.warning("Run %s exceeded max spend $%.4f (limit $%.2f)", run.id, total_cost, flow.max_spend_usd)
        AgentService.kill_agent(space.path, run_id=run.id, flow_name=run.flow_name or "")
        run_svc.mark_step_completed(step_run.id, outcome="max_spend")
        run_svc.mark_completed(run.id, outcome="max_spend")
        self._launch_post_run_step(run, working_path, step_run.step_position + 1, run_svc, flow_svc, error_context={
            "outcome": "max_spend",
            "failed_step": step_run.step_name,
            "error_details": f"Run exceeded the spending limit: ${total_cost:.4f} spent vs ${flow.max_spend_usd:.2f} allowed.",
            "log_tail": _read_log_tail(step_run.log_path or ""),
        })
        return True

    def _post_step_completion(self, run, space, step_run, working_path, run_svc, flow_svc) -> None:
        """Run gate evaluation and advance after a step completes."""
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
                    return

                gate_failure_info = [
                    {"command": f["command"], "message": f["message"], "output": f.get("stderr", "")}
                    for f in failures
                ]

                if unlimited or retry_count < max_retries:
                    is_last_retry = not unlimited and (retry_count + 1 >= max_retries)
                    use_max = step_allow_max and is_last_retry
                    logger.warning("Run %s step '%s' gate failed (retry %d), retrying", run.id, step_run.step_name, retry_count + 1)
                    self._launch_step(
                        run, working_path,
                        step_run.step_name, step_run.step_position,
                        step_run.flow_name, run_svc, flow_svc,
                        gate_failures=gate_failure_info,
                        force_alias="max" if use_max else None,
                    )
                    return
                else:
                    logger.error("Run %s step '%s' gate failed after %d retries", run.id, step_run.step_name, retry_count)
                    step_run.outcome = "gate_failed"
                    step_run.gate_failures = json.dumps(gate_failure_info)
                    run_svc.session.commit()
                    run_svc.mark_completed(run.id, outcome="interrupted")
                    self._launch_post_run_step(run, working_path, step_run.step_position + 1, run_svc, flow_svc, error_context={
                        "outcome": "interrupted",
                        "failed_step": step_run.step_name,
                        "error_details": f"Step '{step_run.step_name}' failed gate checks after {retry_count} retries.",
                        "log_tail": _read_log_tail(step_run.log_path or ""),
                    })
                    return

        self._advance_to_next_step(
            run, working_path,
            step_run.step_name, step_run.step_position, step_run.flow_name,
            run_svc, flow_svc,
        )

    def _advance_to_next_step(self, run, working_path, current_step_name, current_position, current_flow, run_svc, flow_svc) -> None:
        """Determine the next step and launch it, or complete the run."""
        gate_timeout = load_system_config().get("daemon", {}).get("gate_timeout_seconds", 60)
        space = self._get_space(run_svc.session)
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
            self._handle_post_run_completion(run, run_svc, flow_svc, working_path, current_position)
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
            logger.info("Run %s: IF conditions not met for step '%s', skipping", run.id, next_step_name)
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

        self._launch_step(run, working_path, next_step_name, next_position, next_flow, run_svc, flow_svc)

    def _launch_first_step(self, run, space, working_path, run_svc, flow_svc) -> None:
        """Launch the first step of a run."""
        flow_name = run.flow_name
        if not flow_name:
            logger.error("Run %s has no flow_name", run.id)
            run_svc.mark_completed(run.id, outcome="error")
            return

        if not run.flow_snapshot:
            snapshot = flow_svc.build_flow_snapshot(flow_name, space_id=run.space_id)
            if not snapshot:
                logger.error("Flow '%s' not found for run %s", flow_name, run.id)
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
            logger.info("Run %s: IF conditions not met for step '%s', skipping", run.id, first_step)
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

        self._launch_step(run, working_path, first_step, position, flow_name, run_svc, flow_svc)

    def _launch_step(self, run, working_path, step_name, step_position, flow_name, run_svc, flow_svc, gate_failures=None, force_alias=None) -> None:
        """Create a StepRun, render prompt, and launch executor for a step."""
        snap_step = self._get_snapshot_step(run, step_name)
        step_obj = flow_svc.get_step_obj(flow_name, step_name, space_id=run.space_id)
        step_content = ((snap_step or {}).get("content", "") or (step_obj.content if step_obj else "") or "").rstrip()

        space = self._get_space(run_svc.session)
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
            from .gate import render_step_content
            step_content = render_step_content(step_content, step_vars)

        step_type = _normalize_step_type(
            (snap_step or {}).get("step_type") or getattr(step_obj, 'step_type', None)
        )

        alias_name = force_alias or (snap_step or {}).get("agent_alias") or getattr(step_obj, 'agent_alias', None) or "normal"
        alias_type = "pi"
        try:
            resolved_agent, resolved_model = resolve_alias(run_svc.session, alias_type, alias_name)
            if alias_type == "pi" and resolved_agent in KNOWN_LLM_PROVIDERS:
                if "/" not in resolved_model:
                    resolved_model = f"{resolved_agent}/{resolved_model}"
                resolved_agent = "pi"
        except ValueError as exc:
            logger.error("Run %s step '%s': %s", run.id, step_name, exc)
            run_svc.mark_completed(run.id, outcome="error")
            self._launch_post_run_step(run, working_path, step_position, run_svc, flow_svc, error_context={
                "outcome": "error", "failed_step": step_name, "error_details": str(exc), "log_tail": "",
            })
            return

        attempt = len([sr for sr in run_svc.list_step_runs(run.id) if sr.step_name == step_name]) + 1

        step_run = run_svc.create_step_run(
            run_id=run.id, step_name=step_name, step_position=step_position,
            flow_name=flow_name, agent=resolved_agent, model=resolved_model,
        )
        step_run.attempt = attempt
        if gate_failures:
            step_run.prev_gate_failures = json.dumps(gate_failures)
        run_svc.session.commit()

        run_svc.update_run_step(run.id, step_name, flow_name)

        user_responses = []
        for sr in run_svc.list_step_runs(run.id):
            if sr.completed_at and sr.user_response:
                snap_def = self._get_snapshot_step(run, sr.step_name)
                sr_step_type = _normalize_step_type((snap_def or {}).get("step_type"))
                user_responses.append({
                    "step_name": sr.step_name, "step_type": sr_step_type, "user_response": sr.user_response,
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
            servers = get_mcp_servers(needed_connectors)
            if servers:
                extra_env["MCP_SERVERS"] = json.dumps(servers)
                extra_env["BROWSER_ARTIFACTS_DIR"] = str(step_artifact_dir)

        space_dir = Path(space.path) / ".llmflows"
        executor = get_executor(step_type)
        ctx = StepContext(
            run_id=run.id, step_name=step_name, step_position=step_position,
            step_content=step_content, flow_name=flow_name,
            agent=resolved_agent, model=resolved_model, step_type=step_type,
            working_path=working_path, space_dir=space_dir, artifacts_dir=artifacts_dir,
            gate_failures=gate_failures, resume_prompt=resume_prompt, attempt=attempt,
            user_responses=user_responses,
            space_variables=self._env_variables_from_snapshot(self._get_snapshot(run)),
            skills=skill_refs, extra_env=extra_env,
        )
        result = executor.launch(ctx)

        if result.success:
            if result.prompt_content:
                run_svc.set_step_prompt(step_run.id, result.prompt_content)
            if result.log_path:
                run_svc.set_step_log_path(step_run.id, result.log_path)
            logger.info("Launched step '%s' (agent=%s, model=%s) for run %s", step_name, resolved_agent, resolved_model, run.id)

            if result.is_sync:
                run_svc.mark_step_completed(step_run.id, outcome="completed")
                if step_type == "hitl":
                    run_svc.mark_awaiting_user(step_run.id)
                    run_svc.create_inbox_item(
                        type="awaiting_user", reference_id=step_run.id,
                        space_id=run.space_id,
                        title=f"{run.flow_name or run.id} — {step_name} (hitl)",
                    )
                else:
                    self._post_step_completion(run, space, step_run, working_path, run_svc, flow_svc)
        else:
            logger.error("Failed to launch step '%s' for run %s", step_name, run.id)
            run_svc.mark_step_completed(step_run.id, outcome="error")
            run_svc.mark_completed(run.id, outcome="error")
            self._launch_post_run_step(run, working_path, step_run.step_position + 1, run_svc, flow_svc, error_context={
                "outcome": "error", "failed_step": step_name,
                "error_details": f"Failed to launch agent for step '{step_name}'.",
                "log_tail": _read_log_tail(step_run.log_path or ""),
            })

    def _complete_run(self, run, run_svc) -> None:
        """Mark run as completed, create inbox items, and launch post-run step."""
        space = self._get_space(run_svc.session)
        working_path = Path(self.CONTAINER_WORKSPACE)
        space_root = working_path
        artifacts_dir = ContextService.get_artifacts_dir(space_root, run.id, run.flow_name or "")

        summary = (
            ContextService.read_summary_artifact(artifacts_dir)
            or ContextService.read_inbox_message(artifacts_dir)
            or ContextService.read_last_step_result(artifacts_dir)
        )
        outcome = run.outcome or "completed"
        logger.info("Run %s completed (outcome=%s)", run.id, outcome)
        run_svc.mark_completed(run.id, outcome=outcome, summary=summary)

        inbox_message = ContextService.read_inbox_message(artifacts_dir)
        if inbox_message:
            try:
                run_svc.create_inbox_item(
                    type="completed_run", reference_id=run.id,
                    space_id=run.space_id,
                    title=run.flow_name or run.id,
                )
            except Exception:
                logger.debug("Failed to create inbox item for run %s", run.id, exc_info=True)

        last_step_runs = run_svc.list_step_runs(run.id)
        last_pos = max((sr.step_position for sr in last_step_runs), default=-1) + 1
        flow_svc = FlowService(run_svc.session)
        try:
            self._launch_post_run_step(run, working_path, last_pos, run_svc, flow_svc)
        except Exception:
            logger.exception("Post-run step failed to launch for run %s", run.id)

    def _launch_post_run_step(self, run, working_path, step_position, run_svc, flow_svc, error_context=None) -> None:
        """Launch the post-run analysis step."""
        space = self._get_space(run_svc.session)
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
        rejected_proposals = ContextService.read_rejected_proposals(flow_dir)

        from .audit import FlowAuditService
        audit = FlowAuditService.get_audit(space.path, run.flow_name or "")

        post_run_vars = {
            "run": {"id": run.id, "dir": str(artifacts_dir)},
            "flow_name": run.flow_name or "",
            "flow_version": flow_version,
            "outcome": run.outcome or "completed",
            "language": language,
            "rejected_proposals": rejected_proposals,
            "audit_status": audit.status if audit else None,
            "audit_summary": audit.summary if audit else None,
            "audit_findings": audit.findings if audit else None,
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

        step_run = run_svc.create_step_run(
            run_id=run.id, step_name="__post_run__", step_position=step_position,
            flow_name=run.flow_name or "default", agent=post_run_agent, model=resolved_model,
        )
        run_svc.update_run_step(run.id, "__post_run__", run.flow_name or "default")

        space_dir = Path(space.path) / ".llmflows"
        agent_svc = AgentService(space_dir, working_path)
        launched, prompt_content, log_path = agent_svc.prepare_and_launch_step(
            run_id=run.id, step_name="__post_run__", step_position=step_position,
            step_content=post_run_content, flow_name=run.flow_name or "default",
            model=resolved_model, agent=post_run_agent,
            space_variables=self._env_variables_from_snapshot(self._get_snapshot(run)),
        )

        if launched:
            if prompt_content:
                run_svc.set_step_prompt(step_run.id, prompt_content)
            if log_path:
                run_svc.set_step_log_path(step_run.id, log_path)
            logger.info("Launched post-run step for run %s", run.id)
        else:
            logger.error("Failed to launch post-run step for run %s", run.id)
            run_svc.mark_step_completed(step_run.id, outcome="error")

    def _handle_post_run_completion(self, run, run_svc, flow_svc, working_path, step_position) -> None:
        """Handle post-run step finishing."""
        space = self._get_space(run_svc.session)
        space_root = Path(space.path)
        artifacts_dir = ContextService.get_artifacts_dir(space_root, run.id, run.flow_name or "")

        new_summary = ContextService.read_summary_artifact(artifacts_dir)
        if new_summary and run.summary != new_summary:
            run.summary = new_summary
            run_svc.session.commit()

        from ..db.models import StepRun as StepRunModel
        step_run = (
            run_svc.session.query(StepRunModel)
            .filter_by(flow_run_id=run.id, step_name="__post_run__")
            .first()
        )
        if step_run and not step_run.completed_at:
            run_svc.mark_step_completed(step_run.id, outcome="completed")

        if not run.completed_at:
            run_svc.mark_completed(run.id, outcome=run.outcome or "completed")

        logger.info("Post-run step finished for run %s", run.id)

    @staticmethod
    def _publish_attachments(src_dir: Path, run_id: str) -> None:
        """Copy files from a step's attachments/ subdirectory into the run-scoped attachments dir."""
        dest_dir = SYSTEM_DIR / "attachments" / run_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        import shutil
        for f in src_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, dest_dir / f.name)
