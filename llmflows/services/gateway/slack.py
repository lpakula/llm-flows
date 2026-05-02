"""Slack channel for llm-flows — notifications and human-step responses.

Uses slack-bolt with Socket Mode (persistent WebSocket, no public endpoint needed).
Mirrors Telegram bot functionality: run triggers, active run listing,
step responses, and daemon event notifications.
"""

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from ...config import SYSTEM_DIR
from ..chat import ChatService

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
    from datetime import timezone as _tz
    s = start if start.tzinfo else start.replace(tzinfo=_tz.utc)
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
    """Slack channel via Socket Mode — notifications and human-step responses."""

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
        self._chat_service = ChatService(session_factory)
        self._app = None
        self._handler = None
        self._thread: threading.Thread | None = None

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

        @app.action(re.compile(r"^(space|run|respond|complete|dismiss|chatspace|chatflow):"))
        def handle_action(ack, body, say):
            ack()
            self._handle_action(body, say)

    # ── App mention handler (commands via @bot) ──────────────────────────────

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
        elif text.startswith("chatend"):
            self._cmd_chat_end(channel, say, event)
        elif text.startswith("chat"):
            self._cmd_chat(channel, say)
        else:
            say(
                text="Available commands: `run`, `active`, `chat`, `chatend`",
                channel=channel,
            )

    # ── DM handler (prompt responses) ────────────────────────────────────────

    def _handle_dm(self, event: dict, say) -> None:
        channel = event.get("channel", "")
        thread_ts = event.get("thread_ts", "")
        text = event.get("text", "")

        if event.get("bot_id"):
            return

        # HITL takes priority
        step_run_id = self._awaiting_response.pop(thread_ts, None) if thread_ts else None
        if step_run_id:
            from ..run import RunService
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

        # Top-level DM commands
        text_lower = text.strip().lower()
        if text_lower.startswith("run"):
            self._cmd_run(channel, say)
            return
        if text_lower.startswith("active"):
            self._cmd_active(channel, say)
            return
        if text_lower.startswith("chatend"):
            self._cmd_chat_end(channel, say, event)
            return
        if text_lower.startswith("chat"):
            self._cmd_chat(channel, say)
            return
        say(
            text="Use `run`, `active`, `chat`, or `chatend`.",
            channel=channel,
        )

    # ── Action handler (button clicks) ───────────────────────────────────────

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
            space_id = value
            self._cb_select_space(channel, space_id, say, message_ts)

        elif action_id.startswith("run:"):
            self._cb_enqueue_run(channel, value, say, message_ts)

        elif action_id.startswith("respond:"):
            step_run_id = value
            self._awaiting_response[message_ts] = step_run_id
            say(text="Type your response in this thread:", channel=channel, thread_ts=message_ts)

        elif action_id.startswith("complete:"):
            step_run_id = value
            from ..run import RunService
            session = self.session_factory()
            try:
                run_svc = RunService(session)
                sr = run_svc.complete_step_manually(step_run_id)
                if sr:
                    run_svc.archive_inbox_by_reference(step_run_id)
                    say(text="Step marked as completed.", channel=channel, thread_ts=message_ts)
                else:
                    say(text="Step not found.", channel=channel, thread_ts=message_ts)
            finally:
                session.close()

        elif action_id.startswith("dismiss:"):
            inbox_id = value
            from ..run import RunService
            session = self.session_factory()
            try:
                run_svc = RunService(session)
                run_svc.archive_inbox_item(inbox_id)
                say(text="Dismissed.", channel=channel, thread_ts=message_ts)
            finally:
                session.close()

    # ── Commands ─────────────────────────────────────────────────────────────

    def _cmd_run(self, channel: str, say) -> None:
        from ..space import SpaceService

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
        from ..space import SpaceService
        from ..run import RunService
        from datetime import datetime, timezone

        session = self.session_factory()
        try:
            spaces = SpaceService(session).list_all()
            run_svc = RunService(session)
            now = datetime.now(timezone.utc)

            lines: list[str] = []
            for space in spaces:
                active = run_svc.get_active_by_space(space.id)
                pending = run_svc.get_all_pending(space.id)
                if not active and not pending:
                    continue
                lines.append(f"*{space.name}*")
                for r in active:
                    step = r.current_step or "starting"
                    elapsed = _format_elapsed(r.started_at, now)
                    lines.append(f"  :large_green_circle: {r.flow_name or '?'} — _{step}_  {elapsed}")
                for r in pending:
                    waited = _format_elapsed(r.created_at, now)
                    lines.append(f"  :hourglass_flowing_sand: {r.flow_name or '?'} — queued {waited}")

            if not lines:
                say(text="No active or queued runs.", channel=channel)
                return

            say(text="\n".join(lines), channel=channel)
        finally:
            session.close()

    # ── Chat commands ──────────────────────────────────────────────────────

    def _cmd_chat(self, channel: str, say) -> None:
        from ..space import SpaceService

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

    # ── Chat callback helpers ──────────────────────────────────────────────

    def _cb_chat_select_space(self, channel: str, space_id: str, say, message_ts: str) -> None:
        from ..space import SpaceService
        from ..flow import FlowService

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
        from ..space import SpaceService
        from ..flow import FlowService

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

    # ── Chat reply handler ─────────────────────────────────────────────────

    def _chat_reply(
        self, channel: str, thread_ts: str, text: str,
        session: _ChatSession, say,
    ) -> None:
        """Send user message to Pi and relay the response in-thread."""
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

    # ── Callback helpers ─────────────────────────────────────────────────────

    def _cb_select_space(self, channel: str, space_id: str, say, message_ts: str) -> None:
        from ..space import SpaceService
        from ..flow import FlowService

        session = self.session_factory()
        try:
            space = SpaceService(session).get(space_id)
            if not space:
                say(text="Space not found.", channel=channel)
                return
            flows = FlowService(session).list_by_space(space_id)
            if not flows:
                say(text=f"No flows in *{space.name}*.", channel=channel)
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
            say(blocks=blocks, text=f"{space.name} — select a flow:", channel=channel)
        finally:
            session.close()

    def _cb_enqueue_run(self, channel: str, payload: str, say, message_ts: str) -> None:
        from ..run import RunService
        from ..flow import FlowService

        parts = payload.split(":", 1)
        if len(parts) != 2:
            say(text="Invalid selection.", channel=channel)
            return
        space_id, flow_id = parts

        session = self.session_factory()
        try:
            flow_svc = FlowService(session)
            flow = flow_svc.get(flow_id)
            if not flow:
                say(text="Flow not found.", channel=channel)
                return

            run_svc = RunService(session)
            run = run_svc.enqueue(space_id, flow_id)
            say(text=f"Queued *{flow.name}*\nRun `{run.id}`", channel=channel)
        finally:
            session.close()

    # ── Channel interface: outbound notifications ────────────────────────────

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
                self._app.client.chat_postMessage(
                    channel=channel_id,
                    text=text,
                    blocks=blocks,
                )
            except Exception:
                logger.warning("Failed to send notification to channel %s", channel_id)

    def _build_notification_blocks(self, text: str, event: str, payload: dict) -> list[dict]:
        step_run_id = payload.get("step_run_id")
        inbox_id = payload.get("inbox_id")

        blocks: list[dict] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": _to_slack_mrkdwn(text)}},
        ]

        buttons = []
        if event == "step.awaiting_user" and step_run_id:
            buttons.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "Respond"},
                "action_id": f"respond:{step_run_id}",
                "value": step_run_id,
            })
        if inbox_id:
            buttons.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "Dismiss"},
                "action_id": f"dismiss:{inbox_id}",
                "value": inbox_id,
            })
        if buttons:
            blocks.append({"type": "actions", "elements": buttons})

        if event == "run.completed":
            run_id = payload.get("run_id")
            if run_id:
                att_dir = SYSTEM_DIR / "attachments" / run_id
                if att_dir.is_dir():
                    for f in sorted(att_dir.iterdir()):
                        if f.is_file():
                            size_mb = f.stat().st_size / (1024 * 1024)
                            if size_mb <= 10:
                                try:
                                    for channel_id in (self.allowed_channels or self._active_channels):
                                        self._app.client.files_upload_v2(
                                            channel=channel_id,
                                            file=str(f),
                                            title=f.name,
                                        )
                                except Exception:
                                    logger.warning("Failed to upload attachment %s", f)

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
