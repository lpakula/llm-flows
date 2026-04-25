"""Telegram bot for llm-flows — notifications and human-step responses.

Pushes notifications for run completion/error/timeout and awaiting_user steps.
Allows responding to prompt steps and completing manual steps directly from Telegram.
"""

import asyncio
import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...db.models import FlowRun, InboxItem, Space as SpaceModel, StepRun
from ..chat import ChatService
from ..context import ContextService
from ..flow import FlowService
from ..run import RunService
from ..space import SpaceService

try:
    from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application, CallbackQueryHandler, CommandHandler,
        MessageHandler, filters,
    )
    from telegram.request import HTTPXRequest
except ImportError:
    BotCommand = None  # type: ignore[assignment,misc]

logger = logging.getLogger("llmflows.telegram")

_MD_TABLE_RE = re.compile(r"((?:^\|.+\|$\n?)+)", re.MULTILINE)


@dataclass
class _ChatSession:
    session_id: str
    space_id: str
    space_name: str
    anchor_message_id: int
    flow_name: str | None = None
_TG_MAX_LEN = 4096


def _split_message(text: str, max_len: int = _TG_MAX_LEN) -> list[str]:
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


def _to_telegram_html(text: str) -> str:
    """Convert markdown to Telegram-compatible HTML."""

    def _table_to_cards(m: re.Match) -> str:
        lines = m.group(1).strip().splitlines()
        headers: list[str] = []
        data_rows: list[list[str]] = []
        for line in lines:
            stripped = line.strip().strip("|")
            if re.fullmatch(r"[\s\-:|]+", stripped):
                continue
            cells = [c.strip() for c in stripped.split("|")]
            if not headers:
                headers = cells
            else:
                data_rows.append(cells)
        if not headers or not data_rows:
            return m.group(0)
        entries = []
        for row in data_rows:
            parts = []
            for i, h in enumerate(headers):
                val = row[i] if i < len(row) else ""
                if not val or val == "—":
                    continue
                parts.append(f"{h}: {val}")
            entries.append("\n".join(parts))
        return "\n\n".join(entries)

    result = text
    result = result.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    result = _MD_TABLE_RE.sub(_table_to_cards, result)
    result = re.sub(r"```\w*\n(.*?)```", r"<pre>\1</pre>", result, flags=re.DOTALL)
    result = re.sub(r"`(.+?)`", r"<code>\1</code>", result)
    result = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", result)
    result = re.sub(r"__(.+?)__", r"<b>\1</b>", result)
    result = re.sub(r"(?<!\w)\*(?!\*)(.+?)(?<!\*)\*(?!\w)", r"<i>\1</i>", result)
    result = re.sub(r"(?<!\w)_(?!_)(.+?)(?<!_)_(?!\w)", r"<i>\1</i>", result)
    result = re.sub(r"~~(.+?)~~", r"<s>\1</s>", result)
    result = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', result)
    result = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", result, flags=re.MULTILINE)
    result = re.sub(r"^[\-\*]\s+", "• ", result, flags=re.MULTILINE)
    result = re.sub(r"^-{3,}$", "───", result, flags=re.MULTILINE)

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


class TelegramBot:
    """Telegram channel — notifications and human-step responses."""

    name = "telegram"
    subscribed_events = [
        "run.completed",
        "run.timeout",
        "step.awaiting_user",
    ]

    def __init__(self, config: dict[str, Any], session_factory):
        self.config = config
        self.session_factory = session_factory
        self.bot_token = config["bot_token"]
        self.allowed_ids: set[int] = set(config.get("allowed_chat_ids", []))
        self._active_chats: set[int] = set()
        self._awaiting_response: dict[int, str] = {}  # chat_id -> step_run_id
        self._notification_photos: dict[str, list[tuple[int, int]]] = {}
        self._chat_sessions: dict[int, _ChatSession] = {}  # chat_id -> session
        self._chat_pending_space: dict[int, str] = {}  # chat_id -> space_id (mid-selection)
        self._pending_run_vars: dict[int, dict] = {}  # chat_id -> {space_id, flow_id, flow_name, vars: [{key, current}], overrides: {}, pending_idx: int}
        self._chat_service = ChatService(session_factory)
        self._app = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="telegram-bot")
        self._thread.start()
        logger.info("Telegram bot started in background thread")

    def stop(self) -> None:
        if self._app and self._loop and self._loop.is_running():
            async def _shutdown():
                try:
                    if self._app.updater and self._app.updater.running:
                        await self._app.updater.stop()
                    await self._app.stop()
                    await self._app.shutdown()
                except Exception:
                    logger.debug("Error during Telegram shutdown", exc_info=True)
                finally:
                    self._loop.stop()

            asyncio.run_coroutine_threadsafe(_shutdown(), self._loop)
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=10)
        logger.info("Telegram bot stopped")

    def _run(self) -> None:
        if BotCommand is None:
            logger.error(
                "python-telegram-bot is not installed. "
                "Install it with: pip install 'python-telegram-bot>=20'"
            )
            return

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        request = HTTPXRequest(
            connect_timeout=10,
            read_timeout=35,
            connection_pool_size=4,
        )
        app = (
            Application.builder()
            .token(self.bot_token)
            .request(request)
            .build()
        )

        app.add_handler(CommandHandler("run", self._handle_run_command))
        app.add_handler(CommandHandler("active", self._handle_active_command))
        app.add_handler(CommandHandler("inbox", self._handle_inbox_command))
        app.add_handler(CommandHandler("chat", self._handle_chat_command))
        app.add_handler(CommandHandler("chatend", self._handle_chat_end_command))
        app.add_handler(CommandHandler("help", self._handle_help_command))
        app.add_handler(CallbackQueryHandler(self._handle_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))

        self._app = app

        try:
            self._loop.run_until_complete(app.initialize())
            self._loop.run_until_complete(self._register_commands())
            self._loop.run_until_complete(app.start())
            self._loop.run_until_complete(
                app.updater.start_polling(
                    drop_pending_updates=True,
                    poll_interval=0.0,
                    timeout=30,
                )
            )
            self._loop.run_forever()
        except Exception:
            logger.exception("Telegram bot crashed")
        finally:
            self._loop.close()

    async def _register_commands(self) -> None:
        await self._app.bot.set_my_commands([
            BotCommand("run", "Start a flow"),
            BotCommand("active", "List active & queued runs"),
            BotCommand("inbox", "Show inbox items"),
            BotCommand("chat", "Chat with the assistant"),
            BotCommand("chatend", "End chat session"),
            BotCommand("help", "Show commands & chat ID"),
        ])
        logger.info("Telegram bot commands registered")

    def _is_allowed(self, chat_id: int) -> bool:
        if not self.allowed_ids:
            return True
        return chat_id in self.allowed_ids

    # ── /run command — space → flow → enqueue ───────────────────────────────

    async def _handle_run_command(self, update, context) -> None:
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            return
        self._active_chats.add(chat_id)

        session = self.session_factory()
        try:
            spaces = SpaceService(session).list_all()
            if not spaces:
                await update.message.reply_text("No spaces registered.")
                return
            buttons = [
                [InlineKeyboardButton(s.name, callback_data=f"space:{s.id}")]
                for s in spaces
            ]
            await update.message.reply_text(
                "Select a space:",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        finally:
            session.close()

    # ── /active command — list running & queued runs ────────────────────────

    async def _handle_active_command(self, update, context) -> None:
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            return
        self._active_chats.add(chat_id)

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
                lines.append(f"<b>{space.name}</b>")
                for r in active:
                    step = r.current_step or "starting"
                    elapsed = _format_elapsed(r.started_at, now)
                    lines.append(f"  🟢 {r.flow_name or '?'} — <i>{step}</i>  {elapsed}")
                for r in pending:
                    waited = _format_elapsed(r.created_at, now)
                    lines.append(f"  ⏳ {r.flow_name or '?'} — queued {waited}")

            if not lines:
                await update.message.reply_text("No active or queued runs.")
                return

            await update.message.reply_text(
                "\n".join(lines),
                parse_mode="HTML",
            )
        finally:
            session.close()

    # ── /inbox command — list inbox items ────────────────────────────────────

    async def _handle_inbox_command(self, update, context) -> None:
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            return
        self._active_chats.add(chat_id)

        session = self.session_factory()
        try:
            run_svc = RunService(session)
            items = run_svc.list_inbox()
            if not items:
                await update.message.reply_text("Inbox is empty.")
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
                    text = f"⏳ <b>{flow_name}</b> — {sr.step_name}\n<i>{space_name}</i> · waiting {waited}"
                    buttons = [
                        [
                            InlineKeyboardButton("Details", callback_data=f"inbox_detail:{item.id}"),
                            InlineKeyboardButton("Respond", callback_data=f"respond:{sr.id}"),
                        ],
                    ]
                    await update.message.reply_text(
                        text, parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(buttons),
                    )
                    sent += 1

                elif item.type == "completed_run":
                    run = session.query(FlowRun).filter_by(id=item.reference_id).first()
                    if not run:
                        run_svc.archive_inbox_item(item.id)
                        continue
                    flow_name = run.flow_name or "?"
                    outcome = run.outcome or "completed"
                    emoji = "✅" if outcome == "completed" else "❌"
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
                    text = f"{emoji} <b>{flow_name}</b> — {outcome}{meta_str}\n<i>{space_name}</i>"
                    buttons = [
                        [
                            InlineKeyboardButton("Details", callback_data=f"inbox_detail:{item.id}"),
                            InlineKeyboardButton("Archive", callback_data=f"dismiss:{item.id}"),
                        ],
                    ]
                    await update.message.reply_text(
                        text, parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(buttons),
                    )
                    sent += 1

            if not sent:
                await update.message.reply_text("Inbox is empty.")
        finally:
            session.close()

    # ── /help — show commands and chat ID ───────────────────────────────────

    async def _handle_help_command(self, update, context) -> None:
        chat_id = update.effective_chat.id
        self._active_chats.add(chat_id)
        chat_status = ""
        session = self._chat_sessions.get(chat_id)
        if session:
            label = session.flow_name or session.space_name
            chat_status = f"\n\n<i>Active chat: {label}</i>"
        await update.message.reply_text(
            f"<b>llmflows bot</b>\n\n"
            f"Chat ID: <code>{chat_id}</code>\n\n"
            f"<b>Commands:</b>\n"
            f"/run — Start a flow\n"
            f"/active — List active &amp; queued runs\n"
            f"/inbox — Show inbox items\n"
            f"/chat — Chat with the assistant\n"
            f"/chatend — End chat session\n"
            f"/help — Show this message"
            f"{chat_status}",
            parse_mode="HTML",
        )

    # ── Message handler (prompt responses + chat) ──────────────────────────

    async def _handle_message(self, update, context) -> None:
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            return
        self._active_chats.add(chat_id)

        # HITL takes priority over chat
        step_run_id = self._awaiting_response.pop(chat_id, None)
        if step_run_id:
            response_text = update.message.text or ""
            session = self.session_factory()
            try:
                run_svc = RunService(session)
                sr = run_svc.respond_to_step(step_run_id, response_text)
                if sr:
                    await update.message.reply_text("Response recorded. Step will continue.")
                else:
                    await update.message.reply_text("Step not found or no longer awaiting response.")
            finally:
                session.close()
            return

        # Variable collection for /run
        pending = self._pending_run_vars.get(chat_id)
        if pending:
            value = (update.message.text or "").strip()
            idx = pending["pending_idx"]
            var_key = pending["vars"][idx]["key"]
            pending["overrides"][var_key] = value

            next_idx = idx + 1
            if next_idx < len(pending["vars"]):
                pending["pending_idx"] = next_idx
                next_key = pending["vars"][next_idx]["key"]
                await update.message.reply_text(
                    f"Enter value for <code>{next_key}</code>:",
                    parse_mode="HTML",
                )
            else:
                ctx = self._pending_run_vars.pop(chat_id)
                session = self.session_factory()
                try:
                    run_svc = RunService(session)
                    run = run_svc.enqueue(ctx["space_id"], ctx["flow_id"], run_variables=ctx["overrides"])
                    await update.message.reply_text(
                        f"Queued <b>{ctx['flow_name']}</b>\nRun <code>{run.id}</code>",
                        parse_mode="HTML",
                    )
                finally:
                    session.close()
            return

        # Chat session
        chat_session = self._chat_sessions.get(chat_id)
        if chat_session:
            await self._chat_reply(update, chat_id, chat_session)
            return

        await update.message.reply_text(
            "No pending prompt to respond to. "
            "Use /chat to start a chat session."
        )

    # ── Callback handler ─────────────────────────────────────────────────────

    async def _handle_callback(self, update, context) -> None:
        query = update.callback_query
        chat_id = query.message.chat_id
        if not self._is_allowed(chat_id):
            return

        await query.answer()
        data = query.data or ""

        try:
            await self._dispatch_callback(query, chat_id, data)
        except Exception:
            logger.exception("Error handling callback %s", data[:30])
            try:
                await query.message.reply_text("Something went wrong. Please try again.")
            except Exception:
                pass

    async def _dispatch_callback(self, query, chat_id: int, data: str) -> None:
        if data.startswith("space:"):
            await self._cb_select_space(query, data[len("space:"):])
            return

        if data.startswith("run:"):
            await self._cb_enqueue_run(query, data[len("run:"):])
            return

        if data.startswith("inbox_detail:"):
            await self._cb_inbox_detail(query, data[len("inbox_detail:"):])
            return

        if data.startswith("chatspace:"):
            await self._cb_chat_select_space(query, chat_id, data[len("chatspace:"):])
            return

        if data.startswith("chatflow:"):
            await self._cb_chat_select_flow(query, chat_id, data[len("chatflow:"):])
            return

        if data.startswith("respond:"):
            step_run_id = data[len("respond:"):]
            self._awaiting_response[chat_id] = step_run_id
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                "Type your response for this step:"
            )

        elif data.startswith("complete:"):
            step_run_id = data[len("complete:"):]
            session = self.session_factory()
            try:
                run_svc = RunService(session)
                sr = run_svc.complete_step_manually(step_run_id)
                if sr:
                    run_svc.archive_inbox_by_reference(step_run_id)
                    await query.edit_message_text("Step marked as completed.")
                else:
                    await query.edit_message_text("Step not found.")
            finally:
                session.close()

        elif data.startswith("dismiss:"):
            inbox_id = data[len("dismiss:"):]
            session = self.session_factory()
            try:
                run_svc = RunService(session)
                run_svc.archive_inbox_item(inbox_id)
            finally:
                session.close()

            tracked = self._notification_photos.pop(inbox_id, [])
            try:
                await self._app.bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
            except Exception:
                try:
                    await query.edit_message_text("Archived.")
                except Exception:
                    pass
            for cid, message_id in tracked:
                if message_id == query.message.message_id:
                    continue
                try:
                    await self._app.bot.delete_message(chat_id=cid, message_id=message_id)
                except Exception:
                    logger.debug("Failed to delete message %s", message_id)

    # ── /chat command — start a chat session ─────────────────────────────────

    async def _handle_chat_command(self, update, context) -> None:
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            return
        self._active_chats.add(chat_id)

        if chat_id in self._chat_sessions:
            session = self._chat_sessions[chat_id]
            label = session.flow_name or session.space_name
            await update.message.reply_text(
                f"Chat session already active (<b>{label}</b>). "
                f"Use /chatend to stop it first.",
                parse_mode="HTML",
            )
            return

        session = self.session_factory()
        try:
            spaces = SpaceService(session).list_all()
            if not spaces:
                await update.message.reply_text("No spaces registered.")
                return
            buttons = [
                [InlineKeyboardButton(s.name, callback_data=f"chatspace:{s.id}")]
                for s in spaces
            ]
            await update.message.reply_text(
                "Select a space for chat:",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        finally:
            session.close()

    async def _handle_chat_end_command(self, update, context) -> None:
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            return
        self._active_chats.add(chat_id)

        session = self._chat_sessions.pop(chat_id, None)
        self._chat_pending_space.pop(chat_id, None)
        if not session:
            await update.message.reply_text("No active chat session.")
            return

        self._chat_service.end_session(session.session_id)
        try:
            await self._app.bot.send_message(
                chat_id=chat_id,
                text="━━━ Chat ended ━━━",
                reply_to_message_id=session.anchor_message_id,
            )
        except Exception:
            await update.message.reply_text("━━━ Chat ended ━━━")

    # ── /chat callback helpers ─────────────────────────────────────────────

    async def _cb_chat_select_space(self, query, chat_id: int, space_id: str) -> None:
        session = self.session_factory()
        try:
            space = SpaceService(session).get(space_id)
            if not space:
                await query.edit_message_text("Space not found.")
                return
            self._chat_pending_space[chat_id] = space_id
            flows = FlowService(session).list_by_space(space_id)
            buttons = [
                [InlineKeyboardButton(f.name, callback_data=f"chatflow:{space_id}:{f.id}")]
                for f in flows
            ]
            buttons.append([InlineKeyboardButton("Skip (no flow)", callback_data=f"chatflow:{space_id}:skip")])
            await query.edit_message_text(
                f"<b>{space.name}</b> — select a flow (or skip):",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        finally:
            session.close()

    async def _cb_chat_select_flow(self, query, chat_id: int, payload: str) -> None:
        parts = payload.split(":", 1)
        if len(parts) != 2:
            await query.edit_message_text("Invalid selection.")
            return
        space_id, flow_id = parts

        self._chat_pending_space.pop(chat_id, None)

        session = self.session_factory()
        try:
            space = SpaceService(session).get(space_id)
            if not space:
                await query.edit_message_text("Space not found.")
                return

            flow_name = None
            if flow_id != "skip":
                flow = FlowService(session).get(flow_id)
                flow_name = flow.name if flow else None

            label = flow_name or space.name
            anchor_text = f"━━━ Chat: {label} ({space.name}) ━━━\nSend messages to chat. /chatend to stop."
            await query.edit_message_text(anchor_text)
            anchor_message_id = query.message.message_id

            session_id = self._chat_service.new_session_id()
            self._chat_sessions[chat_id] = _ChatSession(
                session_id=session_id,
                space_id=space_id,
                space_name=space.name,
                anchor_message_id=anchor_message_id,
                flow_name=flow_name,
            )
        finally:
            session.close()

    # ── Chat reply handler ─────────────────────────────────────────────────

    async def _chat_reply(self, update, chat_id: int, session: _ChatSession) -> None:
        """Send user message to Pi and relay the response."""
        message_text = update.message.text or ""

        typing_task = asyncio.ensure_future(self._keep_typing(chat_id))
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._chat_service.send_message(
                    session_id=session.session_id,
                    message=message_text,
                    space_id=session.space_id,
                    flow_name=session.flow_name,
                    channel_name="Telegram",
                ),
            )
        finally:
            typing_task.cancel()

        html = _to_telegram_html(response)
        chunks = _split_message(html)
        for chunk in chunks:
            await self._send_message_safe(
                chat_id, chunk,
                reply_to_message_id=session.anchor_message_id,
            )

    async def _keep_typing(self, chat_id: int) -> None:
        """Send 'typing...' indicator every 4 seconds until cancelled."""
        try:
            while True:
                await self._app.bot.send_chat_action(chat_id=chat_id, action="typing")
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    # ── /run callback helpers ────────────────────────────────────────────────

    async def _cb_select_space(self, query, space_id: str) -> None:
        session = self.session_factory()
        try:
            space = SpaceService(session).get(space_id)
            if not space:
                await query.edit_message_text("Space not found.")
                return
            flows = FlowService(session).list_by_space(space_id)
            if not flows:
                await query.edit_message_text(f"No flows in <b>{space.name}</b>.", parse_mode="HTML")
                return
            buttons = [
                [InlineKeyboardButton(f.name, callback_data=f"run:{space_id}:{f.id}")]
                for f in flows
            ]
            await query.edit_message_text(
                f"<b>{space.name}</b> — select a flow:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        finally:
            session.close()

    async def _cb_enqueue_run(self, query, payload: str) -> None:
        parts = payload.split(":", 1)
        if len(parts) != 2:
            await query.edit_message_text("Invalid selection.")
            return
        space_id, flow_id = parts
        chat_id = query.message.chat_id

        session = self.session_factory()
        try:
            flow = FlowService(session).get(flow_id)
            if not flow:
                await query.edit_message_text("Flow not found.")
                return

            flow_vars = flow.get_variables()
            empty_vars = [
                {"key": k, "current": v.get("value", "")}
                for k, v in flow_vars.items()
                if not v.get("value")
            ]

            if empty_vars:
                self._pending_run_vars[chat_id] = {
                    "space_id": space_id,
                    "flow_id": flow_id,
                    "flow_name": flow.name,
                    "vars": empty_vars,
                    "overrides": {},
                    "pending_idx": 0,
                }
                first_var = empty_vars[0]["key"]
                await query.edit_message_text(
                    f"<b>{flow.name}</b> needs variable values.\n\n"
                    f"Enter value for <code>{first_var}</code>:",
                    parse_mode="HTML",
                )
                return

            run_svc = RunService(session)
            run = run_svc.enqueue(space_id, flow_id)
            await query.edit_message_text(
                f"Queued <b>{flow.name}</b>\nRun <code>{run.id}</code>",
                parse_mode="HTML",
            )
        finally:
            session.close()

    # ── /inbox detail callback ─────────────────────────────────────────────

    async def _cb_inbox_detail(self, query, inbox_id: str) -> None:
        chat_id = query.message.chat_id
        session = self.session_factory()
        try:
            run_svc = RunService(session)
            item = session.query(InboxItem).filter_by(id=inbox_id).first()
            if not item:
                await query.edit_message_text("Inbox item not found.")
                return

            space = session.query(SpaceModel).filter_by(id=item.space_id).first()

            if item.type == "awaiting_user":
                sr = session.query(StepRun).filter_by(id=item.reference_id).first()
                if not sr or sr.completed_at:
                    run_svc.archive_inbox_item(item.id)
                    await query.edit_message_text("This step has already been completed.")
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

                text = f"<b>{flow_name}</b> — {sr.step_name}\n"
                if user_message:
                    detail_html = _to_telegram_html(user_message)
                    text += f"\n{detail_html}"
                else:
                    text += "\n<i>No message from this step.</i>"

                markup = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("Respond", callback_data=f"respond:{sr.id}"),
                        InlineKeyboardButton("Complete", callback_data=f"complete:{sr.id}"),
                    ],
                ])
                sent_ids = await self._send_detail_chunks(chat_id, text, markup, inbox_id)
                self._notification_photos[inbox_id] = sent_ids
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except Exception:
                    pass

            elif item.type == "completed_run":
                run = session.query(FlowRun).filter_by(id=item.reference_id).first()
                if not run:
                    await query.edit_message_text("Run not found.")
                    return
                flow_name = run.flow_name or "?"
                outcome = run.outcome or "completed"

                text = f"<b>{flow_name}</b> — {outcome}\n"
                if run.summary:
                    summary_html = _to_telegram_html(run.summary)
                    text += f"\n{summary_html}"
                else:
                    text += "\n<i>No summary available.</i>"

                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("Archive", callback_data=f"dismiss:{inbox_id}")],
                ])
                sent_ids = await self._send_detail_chunks(chat_id, text, markup, inbox_id)
                self._notification_photos[inbox_id] = sent_ids
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except Exception:
                    pass
        finally:
            session.close()

    async def _send_detail_chunks(
        self, chat_id: int, text: str, markup, inbox_id: str,
    ) -> list[tuple[int, int]]:
        """Send detail text in chunks, attaching markup to the last one. Returns sent message IDs."""
        chunks = _split_message(text)
        sent: list[tuple[int, int]] = []
        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1
            msg = await self._send_message_safe(chat_id, chunk, markup if is_last else None)
            if msg:
                sent.append((chat_id, msg.message_id))
        return sent

    # ── NotificationChannel interface ────────────────────────────────────────

    def send(self, event: str, payload: dict[str, Any]) -> None:
        if not self._app or not self._loop:
            return

        text = self._format_notification(event, payload)
        if not text:
            return

        targets = self.allowed_ids or self._active_chats
        for chat_id in targets:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._send_notification(chat_id, text, event, payload),
                    self._loop,
                )
            except Exception:
                logger.warning("Failed to send notification to chat %s", chat_id)

    async def _send_message_safe(
        self, chat_id: int, text: str, markup=None,
        reply_to_message_id: int | None = None,
    ) -> Any:
        """Send a message with HTML, falling back to plain text on failure."""
        try:
            return await self._app.bot.send_message(
                chat_id=chat_id, text=text,
                parse_mode="HTML", reply_markup=markup,
                reply_to_message_id=reply_to_message_id,
            )
        except Exception:
            logger.debug("HTML send failed, retrying as plain text", exc_info=True)
        try:
            plain = re.sub(r"<[^>]+>", "", text)
            return await self._app.bot.send_message(
                chat_id=chat_id, text=plain, reply_markup=markup,
                reply_to_message_id=reply_to_message_id,
            )
        except Exception:
            logger.warning("Failed to send message to chat %s", chat_id, exc_info=True)
            return None

    async def _send_notification(self, chat_id: int, text: str, event: str, payload: dict) -> None:
        inbox_id = payload.get("inbox_id")
        step_run_id = payload.get("step_run_id")

        markup = None
        buttons = []
        if event == "step.awaiting_user" and step_run_id:
            buttons.append(InlineKeyboardButton("Respond", callback_data=f"respond:{step_run_id}"))
        if inbox_id:
            buttons.append(InlineKeyboardButton("Dismiss", callback_data=f"dismiss:{inbox_id}"))
        if buttons:
            markup = InlineKeyboardMarkup([buttons])

        att_files: list[Path] = []
        if event == "run.completed":
            run_id = payload.get("run_id")
            if run_id:
                att_dir = Path.home() / ".llmflows" / "attachments" / run_id
                if att_dir.is_dir():
                    try:
                        for f in sorted(att_dir.iterdir()):
                            if f.is_file():
                                size_mb = f.stat().st_size / (1024 * 1024)
                                if size_mb <= 10:
                                    att_files.append(f)
                    except OSError:
                        logger.debug("Error reading attachments dir %s", att_dir, exc_info=True)

        html = _to_telegram_html(text)
        chunks = _split_message(html)

        last_text_msg = None
        for i, chunk in enumerate(chunks):
            is_last_chunk = i == len(chunks) - 1
            chunk_markup = markup if is_last_chunk and not att_files else None
            msg = await self._send_message_safe(chat_id, chunk, chunk_markup)
            if msg:
                last_text_msg = msg
            else:
                return

        if att_files:
            photo_msgs: list[tuple[int, int]] = []
            if last_text_msg:
                photo_msgs.append((chat_id, last_text_msg.message_id))
            _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
            _AUDIO_EXTS = {".mp3", ".m4a", ".ogg", ".wav", ".flac"}
            for i, f in enumerate(att_files):
                is_last = i == len(att_files) - 1
                last_markup = markup if is_last else None
                try:
                    ext = f.suffix.lower()
                    msg = None
                    if ext in _AUDIO_EXTS:
                        msg = await self._app.bot.send_audio(
                            chat_id=chat_id, audio=open(f, "rb"),
                            caption=f.name, reply_markup=last_markup,
                        )
                    elif ext in _IMAGE_EXTS and f.stat().st_size / (1024 * 1024) <= 5:
                        msg = await self._app.bot.send_photo(
                            chat_id=chat_id, photo=open(f, "rb"),
                            caption=f.name, reply_markup=last_markup,
                        )
                    else:
                        msg = await self._app.bot.send_document(
                            chat_id=chat_id, document=open(f, "rb"),
                            caption=f.name, reply_markup=last_markup,
                        )
                    if msg:
                        photo_msgs.append((chat_id, msg.message_id))
                except Exception:
                    logger.warning("Failed to send attachment %s to chat %s", f, chat_id)
            if inbox_id:
                self._notification_photos[inbox_id] = photo_msgs

    @staticmethod
    def _format_notification(event: str, payload: dict) -> str | None:
        name = payload.get("flow_name") or "?"

        if event == "run.completed":
            outcome = payload.get("outcome", "completed")
            inbox_message = payload.get("inbox_message") or payload.get("summary")
            text = f"**{name}** — {outcome}"

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
            return f"**{name}** timed out after {mins}min."

        if event == "step.awaiting_user":
            step_name = payload.get("step_name", "?")
            text = f"**{name}** — step *{step_name}* needs your input."
            user_message = payload.get("user_message")
            if user_message:
                text += f"\n\n{user_message}"
            return text

        return None
