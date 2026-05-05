"""Slack channel for llm-flows — notifications and human-step responses.

Uses slack-bolt with Socket Mode (persistent WebSocket, no public endpoint needed).
Full feature parity with Telegram bot: run triggers (with variable collection),
active run listing (with cancel/dequeue), inbox browsing, upgrade, help,
flow improvement accept/decline, step responses, chat sessions, and daemon
event notifications.
"""

import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...config import SYSTEM_DIR
from ...db.models import FlowRun, InboxItem, Space as SpaceModel, StepRun
from ..chat import ChatService
from ..context import ContextService
from ..flow import FlowService
from ..run import RunService
from ..space import SpaceService

logger = logging.getLogger("llmflows.slack")

_chat_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="slack-chat")

_SLACK_MAX_LEN = 3000


def _split_message(text: str, max_len: int = _SLACK_MAX_LEN) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, max_len)
        if cut <= 0:
            cut = max_len
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


def _to_slack_mrkdwn(text: str) -> str:
    """Convert common markdown to Slack mrkdwn format."""
    result = text
    result = re.sub(r"#{1,6}\s+(.+)", r"*\1*", result)
    result = re.sub(r"\[(.+?)\]\((.+?)\)", r"<\2|\1>", result)
    result = re.sub(r"~~(.+?)~~", r"~\1~", result)
    return result


def _format_elapsed(start, now) -> str:
    if not start:
        return ""
    s = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
    secs = int((now - s).total_seconds())
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m"
    hours, mins = divmod(mins, 60)
    return f"{hours}h{mins}m"


@dataclass
class _ChatSession:
    session_id: str
    space_id: str
    space_name: str
    anchor_ts: str
    channel: str
    flow_name: str | None = None


class SlackChannel:
    """Slack channel via Socket Mode — full parity with Telegram bot."""

    name = "slack"
    subscribed_events = [
        "run.completed",
        "run.timeout",
        "step.awaiting_user",
        "flow.improvement",
    ]

    def __init__(self, config: dict[str, Any], session_factory):
        self.config = config
        self.session_factory = session_factory
        self.bot_token = config["bot_token"]
        self.app_token = config["app_token"]
        self.allowed_channels: set[str] = set(config.get("allowed_channel_ids", []))
        self._active_channels: set[str] = set()
        self._awaiting_response: dict[str, str] = {}  # thread_ts -> step_run_id
        self._chat_sessions: dict[str, _ChatSession] = {}  # thread_ts -> session
        self._chat_pending_space: dict[str, str] = {}  # message_ts -> space_id
        self._notification_messages: dict[str, list[tuple[str, str]]] = {}  # inbox_id -> [(channel, ts)]
        self._pending_run_vars: dict[str, dict] = {}  # channel_id -> {space_id, flow_id, flow_name, vars, overrides, pending_idx}
        self._chat_service = ChatService(session_factory)
        self._app = None
        self._handler = None
        self._thread: threading.Thread | None = None
        self._load_pending_run_vars()

    # ── Pending variable state persistence ────────────────────────────────

    @staticmethod
    def _pending_state_file() -> Path:
        from ...config import ensure_system_dir
        d = ensure_system_dir() / "slack"
        d.mkdir(parents=True, exist_ok=True)
        return d / "pending.json"

    def _load_pending_run_vars(self) -> None:
        try:
            f = self._pending_state_file()
            if f.exists():
                data = json.loads(f.read_text())
                self._pending_run_vars = dict(data)
        except (OSError, ValueError, TypeError):
            self._pending_run_vars = {}

    def _save_pending_run_vars(self) -> None:
        try:
            f = self._pending_state_file()
            f.write_text(json.dumps(self._pending_run_vars))
        except OSError:
            logger.exception("Failed to persist slack pending state")

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="slack-bot")
        self._thread.start()
        logger.info("Slack bot started in background thread")

    def stop(self) -> None:
        if self._handler:
            try:
                self._handler.close()
            except Exception:
                pass
        logger.info("Slack bot stopped")

    def _run(self) -> None:
        try:
            from slack_bolt import App
            from slack_bolt.adapter.socket_mode import SocketModeHandler
        except ImportError:
            logger.error(
                "slack-bolt is not installed. "
                "Install it with: pip install 'slack-bolt>=1.18'"
            )
            return

        self._app = App(token=self.bot_token)
        self._register_handlers()

        try:
            self._handler = SocketModeHandler(self._app, self.app_token)
            self._handler.start()
        except Exception:
            logger.exception("Slack bot crashed")

    def _is_allowed(self, channel_id: str) -> bool:
        if not self.allowed_channels:
            return True
        return channel_id in self.allowed_channels

    def _register_handlers(self) -> None:
        app = self._app

        @app.event("app_mention")
        def handle_mention(event, say):
            self._handle_mention(event, say)

        @app.event("message")
        def handle_message(event, say):
            if event.get("channel_type") == "im":
                self._handle_dm(event, say)

        @app.action(re.compile(
            r"^(space|run|respond|complete|dismiss|chatspace|chatflow"
            r"|cancelrun|inbox_detail|accept_improvement|decline_improvement):"
        ))
        def handle_action(ack, body, say):
            ack()
            self._handle_action(body, say)

    # ── App mention handler (commands via @bot) ──────────────────────────

    def _handle_mention(self, event: dict, say) -> None:
        channel = event.get("channel", "")
        if not self._is_allowed(channel):
            return
        self._active_channels.add(channel)

        text = re.sub(r"<@\w+>\s*", "", event.get("text", "")).strip().lower()

        if text.startswith("run"):
            self._cmd_run(channel, say)
        elif text.startswith("active"):
            self._cmd_active(channel, say)
        elif text.startswith("inbox"):
            self._cmd_inbox(channel, say)
        elif text.startswith("upgrade"):
            self._cmd_upgrade(channel, say)
        elif text.startswith("chatend"):
            self._cmd_chat_end(channel, say, event)
        elif text.startswith("chat"):
            self._cmd_chat(channel, say)
        elif text.startswith("help"):
            self._cmd_help(channel, say)
        else:
            self._cmd_help(channel, say)

    # ── DM handler (prompt responses + variable collection) ──────────────

    def _handle_dm(self, event: dict, say) -> None:
        channel = event.get("channel", "")
        thread_ts = event.get("thread_ts", "")
        text = event.get("text", "")

        if event.get("bot_id"):
            return

        # HITL takes priority
        step_run_id = self._awaiting_response.pop(thread_ts, None) if thread_ts else None
        if step_run_id:
            session = self.session_factory()
            try:
                run_svc = RunService(session)
                sr = run_svc.respond_to_step(step_run_id, text)
                if sr:
                    say(text="Response recorded. Step will continue.", channel=channel, thread_ts=thread_ts)
                else:
                    say(text="Step not found or no longer awaiting response.", channel=channel, thread_ts=thread_ts)
            finally:
                session.close()
            return

        # Chat session (thread-based)
        chat_session = self._chat_sessions.get(thread_ts) if thread_ts else None
        if chat_session:
            self._chat_reply(channel, thread_ts, text, chat_session, say)
            return

        # Variable collection for run
        pending = self._pending_run_vars.get(channel)
        if pending:
            value = text.strip()
            idx = pending["pending_idx"]
            var_key = pending["vars"][idx]["key"]
            pending["overrides"][var_key] = value

            next_idx = idx + 1
            if next_idx < len(pending["vars"]):
                pending["pending_idx"] = next_idx
                self._save_pending_run_vars()
                next_key = pending["vars"][next_idx]["key"]
                say(text=f"Enter value for `{next_key}`:", channel=channel)
            else:
                ctx = self._pending_run_vars.pop(channel)
                self._save_pending_run_vars()
                session = self.session_factory()
                try:
                    run_svc = RunService(session)
                    run = run_svc.enqueue(ctx["space_id"], ctx["flow_id"], run_variables=ctx["overrides"])
                    say(text=f"Queued *{ctx['flow_name']}*\nRun `{run.id}`", channel=channel)
                finally:
                    session.close()
            return

        # Top-level DM commands
        text_lower = text.strip().lower()
        if text_lower.startswith("run"):
            self._cmd_run(channel, say)
        elif text_lower.startswith("active"):
            self._cmd_active(channel, say)
        elif text_lower.startswith("inbox"):
            self._cmd_inbox(channel, say)
        elif text_lower.startswith("upgrade"):
            self._cmd_upgrade(channel, say)
        elif text_lower.startswith("chatend"):
            self._cmd_chat_end(channel, say, event)
        elif text_lower.startswith("chat"):
            self._cmd_chat(channel, say)
        elif text_lower.startswith("help"):
            self._cmd_help(channel, say)
        else:
            say(
                text="Use `run`, `active`, `inbox`, `chat`, `chatend`, `upgrade`, or `help`.",
                channel=channel,
            )

    # ── Action handler (button clicks) ───────────────────────────────────

    def _handle_action(self, body: dict, say) -> None:
        action = body.get("actions", [{}])[0]
        action_id = action.get("action_id", "")
        value = action.get("value", "")
        channel = body.get("channel", {}).get("id", "")
        message_ts = body.get("message", {}).get("ts", "")

        if action_id.startswith("chatspace:"):
            self._cb_chat_select_space(channel, value, say, message_ts)

        elif action_id.startswith("chatflow:"):
            self._cb_chat_select_flow(channel, value, say, message_ts)

        elif action_id.startswith("space:"):
            self._cb_select_space(channel, value, say, message_ts)

        elif action_id.startswith("run:"):
            self._cb_enqueue_run(channel, value, say, message_ts)

        elif action_id.startswith("respond:"):
            step_run_id = value
            self._awaiting_response[message_ts] = step_run_id
            say(text="Type your response in this thread:", channel=channel, thread_ts=message_ts)

        elif action_id.startswith("complete:"):
            step_run_id = value
            session = self.session_factory()
            try:
                run_svc = RunService(session)
                sr = run_svc.complete_step_manually(step_run_id)
                if sr:
                    run_svc.archive_inbox_by_reference(step_run_id)
                    self._update_message(channel, message_ts, "Step marked as completed.")
                else:
                    self._update_message(channel, message_ts, "Step not found.")
            finally:
                session.close()

        elif action_id.startswith("dismiss:"):
            inbox_id = value
            session = self.session_factory()
            try:
                run_svc = RunService(session)
                run_svc.archive_inbox_item(inbox_id)
            finally:
                session.close()

            tracked = self._notification_messages.pop(inbox_id, [])
            try:
                self._app.client.chat_delete(channel=channel, ts=message_ts)
            except Exception:
                self._update_message(channel, message_ts, "Archived.")
            for ch, ts in tracked:
                if ts == message_ts:
                    continue
                try:
                    self._app.client.chat_delete(channel=ch, ts=ts)
                except Exception:
                    logger.debug("Failed to delete message %s", ts)

        elif action_id.startswith("cancelrun:"):
            self._cb_cancel_run(channel, value, say, message_ts)

        elif action_id.startswith("inbox_detail:"):
            self._cb_inbox_detail(channel, value, say, message_ts)

        elif action_id.startswith("accept_improvement:"):
            self._cb_accept_improvement(channel, value, say, message_ts)

        elif action_id.startswith("decline_improvement:"):
            self._cb_decline_improvement(channel, value, say, message_ts)

    # ── Helper: update or post message ───────────────────────────────────

    def _update_message(self, channel: str, ts: str, text: str, blocks: list | None = None) -> None:
        try:
            kwargs: dict[str, Any] = {"channel": channel, "ts": ts, "text": text}
            if blocks is not None:
                kwargs["blocks"] = blocks
            else:
                kwargs["blocks"] = []
            self._app.client.chat_update(**kwargs)
        except Exception:
            logger.debug("Failed to update message %s", ts, exc_info=True)

    # ── Commands ─────────────────────────────────────────────────────────

    def _cmd_help(self, channel: str, say) -> None:
        from ... import __version__
        say(
            text=(
                f"*llmflows bot* v{__version__}\n\n"
                f"Channel: `{channel}`\n\n"
                f"*Commands:*\n"
                f"`run` — Start a flow\n"
                f"`active` — List active & queued runs\n"
                f"`inbox` — Show inbox items\n"
                f"`chat` — Start a chat session\n"
                f"`chatend` — End a chat session\n"
                f"`upgrade` — Upgrade & restart\n"
                f"`help` — Show this message"
            ),
            channel=channel,
        )

    def _cmd_run(self, channel: str, say) -> None:
        session = self.session_factory()
        try:
            spaces = SpaceService(session).list_all()
            if not spaces:
                say(text="No spaces registered.", channel=channel)
                return
            blocks = [
                {"type": "section", "text": {"type": "mrkdwn", "text": "*Select a space:*"}},
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": s.name},
                            "action_id": f"space:{s.id}",
                            "value": s.id,
                        }
                        for s in spaces
                    ],
                },
            ]
            say(blocks=blocks, text="Select a space:", channel=channel)
        finally:
            session.close()

    def _cmd_active(self, channel: str, say) -> None:
        session = self.session_factory()
        try:
            spaces = SpaceService(session).list_all()
            run_svc = RunService(session)
            now = datetime.now(timezone.utc)

            runs: list[tuple[FlowRun, SpaceModel, str]] = []
            for space in spaces:
                for r in run_svc.get_active_by_space(space.id):
                    runs.append((r, space, "active"))
                for r in run_svc.get_all_pending(space.id):
                    runs.append((r, space, "pending"))

            if not runs:
                say(text="No active or queued runs.", channel=channel)
                return

            for r, space, kind in runs:
                self._send_active_run_card(channel, say, r, space, kind, now)
        finally:
            session.close()

    def _send_active_run_card(
        self, channel: str, say, run: "FlowRun", space: "SpaceModel",
        kind: str, now: datetime,
    ) -> None:
        flow_label = run.flow_name or "?"
        if kind == "active":
            status = run.status
            if status == "awaiting_user":
                icon, status_label = ":large_orange_circle:", "awaiting input"
            elif status == "paused":
                icon, status_label = ":double_vertical_bar:", "paused"
            else:
                icon, status_label = ":large_yellow_circle:", "running"
            elapsed = _format_elapsed(run.started_at, now)
            step = run.current_step or "starting"
            lines = [
                f"{icon} *{flow_label}*",
                f"Status: {status_label}  ·  {elapsed}",
                f"Step: _{step}_",
            ]
            btn_label = f"Cancel {flow_label}"
        else:
            waited = _format_elapsed(run.created_at, now)
            lines = [
                f":large_blue_circle: *{flow_label}*",
                f"Status: queued  ·  {waited}",
            ]
            btn_label = f"Dequeue {flow_label}"

        lines.append(f"Space: {space.name}")

        run_vars = run.run_variables
        if run_vars:
            var_parts = [f"{k}={v}" for k, v in run_vars.items()]
            lines.append(f"Vars: `{', '.join(var_parts)}`")

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
            {
                "type": "actions",
                "elements": [{
                    "type": "button",
                    "text": {"type": "plain_text", "text": btn_label},
                    "action_id": f"cancelrun:{run.id}",
                    "value": run.id,
                }],
            },
        ]
        say(blocks=blocks, text="\n".join(lines), channel=channel)

    def _cmd_inbox(self, channel: str, say) -> None:
        session = self.session_factory()
        try:
            run_svc = RunService(session)
            items = run_svc.list_inbox()
            if not items:
                say(text="Inbox is empty.", channel=channel)
                return

            now = datetime.now(timezone.utc)
            sent = 0

            for item in items:
                space = session.query(SpaceModel).filter_by(id=item.space_id).first()
                space_name = space.name if space else "?"

                if item.type == "awaiting_user":
                    sr = session.query(StepRun).filter_by(id=item.reference_id).first()
                    if not sr or sr.completed_at:
                        run_svc.archive_inbox_item(item.id)
                        continue
                    run = session.query(FlowRun).filter_by(id=sr.flow_run_id).first()
                    flow_name = (run.flow_name if run else None) or "?"
                    waited = _format_elapsed(sr.awaiting_user_at or item.created_at, now)
                    text = f":hourglass: *{flow_name}* — {sr.step_name}\n_{space_name}_ · waiting {waited}"
                    blocks = [
                        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
                        {
                            "type": "actions",
                            "elements": [
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "Details"},
                                    "action_id": f"inbox_detail:{item.id}",
                                    "value": item.id,
                                },
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "Respond"},
                                    "action_id": f"respond:{sr.id}",
                                    "value": sr.id,
                                },
                            ],
                        },
                    ]
                    say(blocks=blocks, text=text, channel=channel)
                    sent += 1

                elif item.type == "completed_run":
                    run = session.query(FlowRun).filter_by(id=item.reference_id).first()
                    if not run:
                        run_svc.archive_inbox_item(item.id)
                        continue
                    flow_name = run.flow_name or "?"
                    outcome = run.outcome or "completed"
                    emoji = ":white_check_mark:" if outcome == "completed" else ":x:"
                    meta: list[str] = []
                    if run.duration_seconds is not None:
                        secs = int(run.duration_seconds)
                        if secs < 60:
                            meta.append(f"{secs}s")
                        elif secs < 3600:
                            meta.append(f"{secs // 60}m")
                        else:
                            meta.append(f"{secs // 3600}h{(secs % 3600) // 60}m")
                    if run.cost_usd is not None:
                        meta.append(f"${run.cost_usd:.4f}")
                    meta_str = f"  ({' · '.join(meta)})" if meta else ""
                    text = f"{emoji} *{flow_name}* — {outcome}{meta_str}\n_{space_name}_"
                    blocks = [
                        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
                        {
                            "type": "actions",
                            "elements": [
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "Details"},
                                    "action_id": f"inbox_detail:{item.id}",
                                    "value": item.id,
                                },
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "Archive"},
                                    "action_id": f"dismiss:{item.id}",
                                    "value": item.id,
                                },
                            ],
                        },
                    ]
                    say(blocks=blocks, text=text, channel=channel)
                    sent += 1

                elif item.type == "flow_improvement":
                    run = session.query(FlowRun).filter_by(id=item.reference_id).first()
                    if not run:
                        run_svc.archive_inbox_item(item.id)
                        continue
                    flow_name = run.flow_name or "?"
                    text = f":bulb: *{flow_name}* — flow improvement proposed"
                    blocks = [
                        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
                        {
                            "type": "actions",
                            "elements": [
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "Details"},
                                    "action_id": f"inbox_detail:{item.id}",
                                    "value": item.id,
                                },
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "Accept"},
                                    "action_id": f"accept_improvement:{item.id}",
                                    "value": item.id,
                                    "style": "primary",
                                },
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "Decline"},
                                    "action_id": f"decline_improvement:{item.id}",
                                    "value": item.id,
                                    "style": "danger",
                                },
                            ],
                        },
                    ]
                    say(blocks=blocks, text=text, channel=channel)
                    sent += 1

            if not sent:
                say(text="Inbox is empty.", channel=channel)
        finally:
            session.close()

    def _cmd_upgrade(self, channel: str, say) -> None:
        say(text="Upgrading llmflows…", channel=channel)

        from ...services.upgrade import (
            pip_upgrade, kill_ui_processes,
            start_ui_background, trigger_daemon_reexec,
        )

        success, old_ver, new_ver, output = pip_upgrade()

        if not success:
            short = output[:800] if len(output) > 800 else output
            say(text=f"Upgrade failed:\n```{short}```", channel=channel)
            return

        if old_ver == new_ver:
            say(text=f"Already at latest version (`{old_ver}`).", channel=channel)
            return

        killed = kill_ui_processes()
        ui_pid = start_ui_background(no_daemon=True)

        parts = [f"Upgraded `{old_ver}` → `{new_ver}`"]
        if killed:
            parts.append(f"UI restarted (pid {ui_pid})" if ui_pid else "UI stopped")
        parts.append("Restarting daemon…")
        say(text="\n".join(parts), channel=channel)

        trigger_daemon_reexec()

    # ── Chat commands ────────────────────────────────────────────────────

    def _cmd_chat(self, channel: str, say) -> None:
        session = self.session_factory()
        try:
            spaces = SpaceService(session).list_all()
            if not spaces:
                say(text="No spaces registered.", channel=channel)
                return
            blocks = [
                {"type": "section", "text": {"type": "mrkdwn", "text": "*Select a space for chat:*"}},
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": s.name},
                            "action_id": f"chatspace:{s.id}",
                            "value": s.id,
                        }
                        for s in spaces
                    ],
                },
            ]
            say(blocks=blocks, text="Select a space for chat:", channel=channel)
        finally:
            session.close()

    def _cmd_chat_end(self, channel: str, say, event: dict) -> None:
        thread_ts = event.get("thread_ts", "")
        ended = False
        if thread_ts and thread_ts in self._chat_sessions:
            session = self._chat_sessions.pop(thread_ts)
            self._chat_service.end_session(session.session_id)
            say(text="━━━ Chat ended ━━━", channel=channel, thread_ts=thread_ts)
            ended = True

        if not ended:
            to_remove = [
                ts for ts, s in self._chat_sessions.items()
                if s.channel == channel
            ]
            for ts in to_remove:
                session = self._chat_sessions.pop(ts)
                self._chat_service.end_session(session.session_id)
                say(text="━━━ Chat ended ━━━", channel=channel, thread_ts=ts)
                ended = True

        if not ended:
            say(text="No active chat session.", channel=channel)

    # ── Chat callback helpers ────────────────────────────────────────────

    def _cb_chat_select_space(self, channel: str, space_id: str, say, message_ts: str) -> None:
        session = self.session_factory()
        try:
            space = SpaceService(session).get(space_id)
            if not space:
                say(text="Space not found.", channel=channel)
                return
            self._chat_pending_space[message_ts] = space_id
            flows = FlowService(session).list_by_space(space_id)
            elements = [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": f.name},
                    "action_id": f"chatflow:{space_id}:{f.id}",
                    "value": f"{space_id}:{f.id}",
                }
                for f in flows
            ]
            elements.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "Skip (no flow)"},
                "action_id": f"chatflow:{space_id}:skip",
                "value": f"{space_id}:skip",
            })
            blocks = [
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*{space.name}* — select a flow (or skip):"}},
                {"type": "actions", "elements": elements},
            ]
            try:
                self._app.client.chat_update(
                    channel=channel, ts=message_ts,
                    blocks=blocks, text=f"{space.name} — select a flow:",
                )
            except Exception:
                say(blocks=blocks, text=f"{space.name} — select a flow:", channel=channel)
        finally:
            session.close()

    def _cb_chat_select_flow(self, channel: str, payload: str, say, message_ts: str) -> None:
        parts = payload.split(":", 1)
        if len(parts) != 2:
            say(text="Invalid selection.", channel=channel)
            return
        space_id, flow_id = parts
        self._chat_pending_space.pop(message_ts, None)

        session = self.session_factory()
        try:
            space = SpaceService(session).get(space_id)
            if not space:
                say(text="Space not found.", channel=channel)
                return

            flow_name = None
            if flow_id != "skip":
                flow = FlowService(session).get(flow_id)
                flow_name = flow.name if flow else None

            label = flow_name or space.name
            anchor_text = f"━━━ Chat: {label} ({space.name}) ━━━\nReply in this thread to chat. Say `chatend` to stop."

            try:
                self._app.client.chat_update(
                    channel=channel, ts=message_ts,
                    text=anchor_text, blocks=[],
                )
                anchor_ts = message_ts
            except Exception:
                resp = say(text=anchor_text, channel=channel)
                anchor_ts = resp.get("ts", message_ts) if isinstance(resp, dict) else message_ts

            session_id = self._chat_service.new_session_id()
            self._chat_sessions[anchor_ts] = _ChatSession(
                session_id=session_id,
                space_id=space_id,
                space_name=space.name,
                anchor_ts=anchor_ts,
                channel=channel,
                flow_name=flow_name,
            )
        finally:
            session.close()

    # ── Chat reply handler ───────────────────────────────────────────────

    def _chat_reply(
        self, channel: str, thread_ts: str, text: str,
        session: _ChatSession, say,
    ) -> None:
        text_lower = text.strip().lower()
        if text_lower == "chatend":
            self._chat_sessions.pop(thread_ts, None)
            self._chat_service.end_session(session.session_id)
            say(text="━━━ Chat ended ━━━", channel=channel, thread_ts=thread_ts)
            return

        thinking_resp = self._app.client.chat_postMessage(
            channel=channel, thread_ts=thread_ts,
            text="_Thinking..._",
        )
        thinking_ts = thinking_resp.get("ts", "") if thinking_resp else ""

        def _run_pi():
            return self._chat_service.send_message(
                session_id=session.session_id,
                message=text,
                space_id=session.space_id,
                flow_name=session.flow_name,
                channel_name="Slack",
            )

        try:
            future = _chat_executor.submit(_run_pi)
            response = future.result(timeout=300)
        except Exception:
            response = "Error running the chat agent."

        formatted = _to_slack_mrkdwn(response)
        chunks = _split_message(formatted)

        if thinking_ts and chunks:
            try:
                self._app.client.chat_update(
                    channel=channel, ts=thinking_ts,
                    text=chunks[0],
                )
                chunks = chunks[1:]
            except Exception:
                pass

        for chunk in chunks:
            say(text=chunk, channel=channel, thread_ts=thread_ts)

    # ── Run callback helpers ─────────────────────────────────────────────

    def _cb_select_space(self, channel: str, space_id: str, say, message_ts: str) -> None:
        session = self.session_factory()
        try:
            space = SpaceService(session).get(space_id)
            if not space:
                say(text="Space not found.", channel=channel)
                return
            flows = FlowService(session).list_by_space(space_id)
            if not flows:
                self._update_message(channel, message_ts, f"No flows in *{space.name}*.")
                return
            blocks = [
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*{space.name}* — select a flow:"}},
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": f.name},
                            "action_id": f"run:{space_id}:{f.id}",
                            "value": f"{space_id}:{f.id}",
                        }
                        for f in flows
                    ],
                },
            ]
            self._update_message(channel, message_ts, f"{space.name} — select a flow:", blocks)
        finally:
            session.close()

    def _cb_enqueue_run(self, channel: str, payload: str, say, message_ts: str) -> None:
        parts = payload.split(":", 1)
        if len(parts) != 2:
            say(text="Invalid selection.", channel=channel)
            return
        space_id, flow_id = parts

        session = self.session_factory()
        try:
            flow = FlowService(session).get(flow_id)
            if not flow:
                self._update_message(channel, message_ts, "Flow not found.")
                return

            flow_vars = flow.get_variables()
            empty_vars = [
                {"key": k, "current": v.get("value", "")}
                for k, v in flow_vars.items()
                if not v.get("value")
            ]

            if empty_vars:
                self._pending_run_vars[channel] = {
                    "space_id": space_id,
                    "flow_id": flow_id,
                    "flow_name": flow.name,
                    "vars": empty_vars,
                    "overrides": {},
                    "pending_idx": 0,
                }
                self._save_pending_run_vars()
                first_var = empty_vars[0]["key"]
                self._update_message(
                    channel, message_ts,
                    f"*{flow.name}* needs variable values.\n\nEnter value for `{first_var}`:",
                )
                return

            run_svc = RunService(session)
            run = run_svc.enqueue(space_id, flow_id)
            self._update_message(
                channel, message_ts,
                f"Queued *{flow.name}*\nRun `{run.id}`",
            )
        finally:
            session.close()

    # ── Cancel run callback ──────────────────────────────────────────────

    def _cb_cancel_run(self, channel: str, run_id: str, say, message_ts: str) -> None:
        session = self.session_factory()
        try:
            run_svc = RunService(session)
            run = run_svc.get(run_id)
            if not run:
                self._update_message(channel, message_ts, "Run not found.")
                return
            if run.completed_at:
                self._update_message(channel, message_ts, f"Run `{run_id}` already completed.")
                return

            flow_label = run.flow_name or run_id
            if not run.started_at:
                session.delete(run)
                session.commit()
                self._update_message(channel, message_ts, f"Dequeued *{flow_label}* (`{run_id}`)")
                return

            run_svc.mark_completed(run_id, outcome="cancelled")
            space = session.query(SpaceModel).filter_by(id=run.space_id).first()
            if space:
                from ..agent import AgentService
                AgentService.kill_agent(space.path, run_id=run.id, flow_name=run.flow_name or "")
            self._update_message(channel, message_ts, f"Cancelled *{flow_label}* (`{run_id}`)")
        finally:
            session.close()

    # ── Inbox detail callback ────────────────────────────────────────────

    def _cb_inbox_detail(self, channel: str, inbox_id: str, say, message_ts: str) -> None:
        session = self.session_factory()
        try:
            run_svc = RunService(session)
            item = session.query(InboxItem).filter_by(id=inbox_id).first()
            if not item:
                self._update_message(channel, message_ts, "Inbox item not found.")
                return

            space = session.query(SpaceModel).filter_by(id=item.space_id).first()

            if item.type == "awaiting_user":
                sr = session.query(StepRun).filter_by(id=item.reference_id).first()
                if not sr or sr.completed_at:
                    run_svc.archive_inbox_item(item.id)
                    self._update_message(channel, message_ts, "This step has already been completed.")
                    return
                run = session.query(FlowRun).filter_by(id=sr.flow_run_id).first()
                flow_name = (run.flow_name if run else None) or "?"

                user_message = ""
                if space:
                    try:
                        artifacts_dir = ContextService.get_artifacts_dir(
                            Path(space.path), run.id, run.flow_name or "",
                        )
                        result_file = artifacts_dir / ContextService.step_dir_name(
                            sr.step_position, sr.step_name,
                        ) / "_result.md"
                        if result_file.exists():
                            user_message = result_file.read_text().strip()
                    except (PermissionError, OSError):
                        pass

                text = f"*{flow_name}* — {sr.step_name}\n"
                if user_message:
                    text += f"\n{_to_slack_mrkdwn(user_message)}"
                else:
                    text += "\n_No message from this step._"

                blocks = [
                    {"type": "section", "text": {"type": "mrkdwn", "text": text}},
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Respond"},
                                "action_id": f"respond:{sr.id}",
                                "value": sr.id,
                            },
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Complete"},
                                "action_id": f"complete:{sr.id}",
                                "value": sr.id,
                            },
                        ],
                    },
                ]
                sent_ids = self._send_detail_chunks(channel, text, blocks)
                self._notification_messages[inbox_id] = sent_ids
                self._update_message(channel, message_ts, f"*{flow_name}* — {sr.step_name} (see below)")

            elif item.type == "completed_run":
                run = session.query(FlowRun).filter_by(id=item.reference_id).first()
                if not run:
                    self._update_message(channel, message_ts, "Run not found.")
                    return
                flow_name = run.flow_name or "?"
                outcome = run.outcome or "completed"

                text = f"*{flow_name}* — {outcome}\n"
                if run.summary:
                    text += f"\n{_to_slack_mrkdwn(run.summary)}"
                else:
                    text += "\n_No summary available._"

                blocks = [
                    {"type": "section", "text": {"type": "mrkdwn", "text": text}},
                    {
                        "type": "actions",
                        "elements": [{
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Archive"},
                            "action_id": f"dismiss:{inbox_id}",
                            "value": inbox_id,
                        }],
                    },
                ]
                sent_ids = self._send_detail_chunks(channel, text, blocks)
                self._notification_messages[inbox_id] = sent_ids
                self._update_message(channel, message_ts, f"*{flow_name}* — {outcome} (see below)")

            elif item.type == "flow_improvement":
                run = session.query(FlowRun).filter_by(id=item.reference_id).first()
                if not run:
                    self._update_message(channel, message_ts, "Run not found.")
                    return
                flow_name = run.flow_name or "?"

                improvement_text = ""
                if space:
                    try:
                        artifacts_dir = ContextService.get_artifacts_dir(
                            Path(space.path), run.id, run.flow_name or "",
                        )
                        improvement_text = ContextService.read_improvement(artifacts_dir)
                    except (PermissionError, OSError):
                        pass

                text = f"*{flow_name}* — flow improvement proposed\n"
                if improvement_text:
                    text += f"\n{_to_slack_mrkdwn(improvement_text)}"
                else:
                    text += "\n_No improvement details available._"

                blocks = [
                    {"type": "section", "text": {"type": "mrkdwn", "text": text}},
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Accept"},
                                "action_id": f"accept_improvement:{inbox_id}",
                                "value": inbox_id,
                                "style": "primary",
                            },
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Decline"},
                                "action_id": f"decline_improvement:{inbox_id}",
                                "value": inbox_id,
                                "style": "danger",
                            },
                        ],
                    },
                ]
                sent_ids = self._send_detail_chunks(channel, text, blocks)
                self._notification_messages[inbox_id] = sent_ids
                self._update_message(channel, message_ts, f"*{flow_name}* — improvement (see below)")
        finally:
            session.close()

    def _send_detail_chunks(
        self, channel: str, text: str, action_blocks: list[dict],
    ) -> list[tuple[str, str]]:
        """Send detail text in chunks, attaching action buttons to the last one."""
        chunks = _split_message(text)
        sent: list[tuple[str, str]] = []
        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1
            blocks: list[dict] = [{"type": "section", "text": {"type": "mrkdwn", "text": chunk}}]
            if is_last:
                for b in action_blocks:
                    if b.get("type") == "actions":
                        blocks.append(b)
            try:
                resp = self._app.client.chat_postMessage(
                    channel=channel, text=chunk, blocks=blocks,
                )
                ts = resp.get("ts", "")
                if ts:
                    sent.append((channel, ts))
            except Exception:
                logger.warning("Failed to send detail chunk to %s", channel)
        return sent

    # ── Flow improvement callbacks ───────────────────────────────────────

    def _cb_accept_improvement(self, channel: str, inbox_id: str, say, message_ts: str) -> None:
        session = self.session_factory()
        try:
            item = session.query(InboxItem).filter_by(id=inbox_id).first()
            if not item or item.type != "flow_improvement":
                self._update_message(channel, message_ts, "Improvement proposal not found.")
                return
            if item.archived_at:
                self._update_message(channel, message_ts, "Already handled.")
                return

            run = session.query(FlowRun).filter_by(id=item.reference_id).first()
            space = session.query(SpaceModel).filter_by(id=item.space_id).first()
            if not run or not space or not run.flow_id:
                self._update_message(channel, message_ts, "Run or flow not found.")
                return

            artifacts_dir = ContextService.get_artifacts_dir(
                Path(space.path), run.id, run.flow_name or "",
            )
            flow_json = ContextService.read_flow_json(artifacts_dir)
            if not flow_json or not flow_json.get("steps"):
                self._update_message(channel, message_ts, "No valid flow proposal found.")
                return

            flow = FlowService(session).apply_flow_proposal(run.flow_id, flow_json)
            if not flow:
                self._update_message(channel, message_ts, "Failed to apply proposal.")
                return

            RunService(session).archive_inbox_item(inbox_id)
            flow_name = run.flow_name or "?"
            self._update_message(
                channel, message_ts,
                f":white_check_mark: Accepted improvement for *{flow_name}* (v{flow.version})",
            )
        finally:
            session.close()

    def _cb_decline_improvement(self, channel: str, inbox_id: str, say, message_ts: str) -> None:
        session = self.session_factory()
        try:
            item = session.query(InboxItem).filter_by(id=inbox_id).first()
            if item and item.type == "flow_improvement":
                run = session.query(FlowRun).filter_by(id=item.reference_id).first()
                space = session.query(SpaceModel).filter_by(id=item.space_id).first()
                if run and space:
                    artifacts_dir = ContextService.get_artifacts_dir(
                        Path(space.path), run.id, run.flow_name or "",
                    )
                    improvement = ContextService.read_improvement(artifacts_dir)
                    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                    entry_parts = [f"## Rejected proposal ({ts})", ""]
                    if improvement:
                        entry_parts.append(f"**Proposal:** {improvement}")
                        entry_parts.append("")
                    entry_parts.append(f"**Run:** {run.id}")
                    flow_dir = ContextService.get_flow_dir(Path(space.path), run.flow_name or "")
                    ContextService.append_memory(flow_dir, "\n".join(entry_parts))

            RunService(session).archive_inbox_item(inbox_id)
        finally:
            session.close()

        tracked = self._notification_messages.pop(inbox_id, [])
        try:
            self._app.client.chat_delete(channel=channel, ts=message_ts)
        except Exception:
            self._update_message(channel, message_ts, "Declined.")
        for ch, ts in tracked:
            if ts == message_ts:
                continue
            try:
                self._app.client.chat_delete(channel=ch, ts=ts)
            except Exception:
                logger.debug("Failed to delete message %s", ts)

    # ── Channel interface: outbound notifications ────────────────────────

    def send(self, event: str, payload: dict[str, Any]) -> None:
        if not self._app:
            return

        text = self._format_notification(event, payload)
        if not text:
            return

        targets = self.allowed_channels or self._active_channels
        for channel_id in targets:
            try:
                blocks = self._build_notification_blocks(text, event, payload)
                resp = self._app.client.chat_postMessage(
                    channel=channel_id,
                    text=text,
                    blocks=blocks,
                )

                inbox_id = payload.get("inbox_id")
                if inbox_id and resp.get("ts"):
                    msgs = self._notification_messages.setdefault(inbox_id, [])
                    msgs.append((channel_id, resp["ts"]))

                if event == "run.completed":
                    self._upload_attachments(channel_id, payload)
            except Exception:
                logger.warning("Failed to send notification to channel %s", channel_id)

    def _upload_attachments(self, channel_id: str, payload: dict) -> None:
        run_id = payload.get("run_id")
        if not run_id:
            return
        att_dir = SYSTEM_DIR / "attachments" / run_id
        if not att_dir.is_dir():
            return
        try:
            for f in sorted(att_dir.iterdir()):
                if f.is_file():
                    size_mb = f.stat().st_size / (1024 * 1024)
                    if size_mb <= 10:
                        try:
                            self._app.client.files_upload_v2(
                                channel=channel_id,
                                file=str(f),
                                title=f.name,
                            )
                        except Exception:
                            logger.warning("Failed to upload attachment %s", f)
        except OSError:
            logger.debug("Error reading attachments dir %s", att_dir, exc_info=True)

    def _build_notification_blocks(self, text: str, event: str, payload: dict) -> list[dict]:
        step_run_id = payload.get("step_run_id")
        inbox_id = payload.get("inbox_id")

        blocks: list[dict] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": _to_slack_mrkdwn(text)}},
        ]

        buttons: list[dict] = []
        if event == "step.awaiting_user" and step_run_id:
            buttons.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "Respond"},
                "action_id": f"respond:{step_run_id}",
                "value": step_run_id,
            })
        if event == "flow.improvement" and inbox_id:
            buttons.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "Accept"},
                "action_id": f"accept_improvement:{inbox_id}",
                "value": inbox_id,
                "style": "primary",
            })
            buttons.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "Decline"},
                "action_id": f"decline_improvement:{inbox_id}",
                "value": inbox_id,
                "style": "danger",
            })
        elif inbox_id:
            buttons.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "Dismiss"},
                "action_id": f"dismiss:{inbox_id}",
                "value": inbox_id,
            })
        if buttons:
            blocks.append({"type": "actions", "elements": buttons})

        return blocks

    @staticmethod
    def _format_notification(event: str, payload: dict) -> str | None:
        name = payload.get("flow_name") or "?"

        if event == "run.completed":
            outcome = payload.get("outcome", "completed")
            inbox_message = payload.get("inbox_message") or payload.get("summary")
            text = f"*{name}* — {outcome}"

            meta: list[str] = []
            dur = payload.get("duration_seconds")
            if dur is not None:
                secs = int(dur)
                if secs < 60:
                    meta.append(f"{secs}s")
                elif secs < 3600:
                    meta.append(f"{secs // 60}m")
                else:
                    meta.append(f"{secs // 3600}h{(secs % 3600) // 60}m")
            cost = payload.get("cost_usd")
            if cost is not None:
                meta.append(f"${cost:.4f}")
            if meta:
                text += f"  ({' · '.join(meta)})"

            if inbox_message:
                text += f"\n\n{inbox_message}"
            return text

        if event == "run.timeout":
            mins = payload.get("timeout_minutes", "?")
            return f"*{name}* timed out after {mins}min."

        if event == "step.awaiting_user":
            step_name = payload.get("step_name", "?")
            text = f"*{name}* — step _{step_name}_ needs your input."
            user_message = payload.get("user_message")
            if user_message:
                text += f"\n\n{user_message}"
            return text

        if event == "flow.improvement":
            text = f"*{name}* — flow improvement proposed."
            improvement = payload.get("improvement")
            if improvement:
                text += f"\n\n{improvement}"
            return text

        return None
