"""Telegram bot for llm-flows — notifications and human-step responses.

Pushes notifications for run completion/error/timeout and awaiting_user steps.
Allows responding to prompt steps and completing manual steps directly from Telegram.
"""

import asyncio
import logging
import re
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("llmflows.telegram")

_MD_TABLE_RE = re.compile(r"((?:^\|.+\|$\n?)+)", re.MULTILINE)
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


class TelegramBot:
    """Telegram bot for notifications and human-step responses."""

    subscribed_events = [
        "run.completed",
        "run.timeout",
        "step.awaiting_user",
    ]

    def __init__(self, config: dict[str, Any], session_factory, notification_service=None):
        self.config = config
        self.session_factory = session_factory
        self.bot_token = config["bot_token"]
        self.allowed_ids: set[int] = set(config.get("allowed_chat_ids", []))
        self._active_chats: set[int] = set()
        self._awaiting_response: dict[int, str] = {}  # chat_id -> step_run_id
        self._notification_photos: dict[str, list[tuple[int, int]]] = {}
        self._app = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

        if notification_service:
            notification_service.register(self)

    def start_background(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="telegram-bot")
        self._thread.start()
        logger.info("Telegram bot started in background thread")

    def stop(self) -> None:
        if self._app and self._loop:
            asyncio.run_coroutine_threadsafe(self._app.stop(), self._loop)
        logger.info("Telegram bot stopped")

    def _run(self) -> None:
        try:
            from telegram.ext import (
                Application, MessageHandler, CallbackQueryHandler, filters,
            )
        except ImportError:
            logger.error(
                "python-telegram-bot is not installed. "
                "Install it with: pip install 'python-telegram-bot>=20'"
            )
            return

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        from telegram.request import HTTPXRequest
        request = HTTPXRequest(
            connect_timeout=10,
            read_timeout=10,
            connection_pool_size=4,
        )
        app = (
            Application.builder()
            .token(self.bot_token)
            .request(request)
            .build()
        )

        app.add_handler(CallbackQueryHandler(self._handle_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))

        self._app = app

        try:
            self._loop.run_until_complete(app.initialize())
            self._loop.run_until_complete(app.start())
            self._loop.run_until_complete(
                app.updater.start_polling(
                    drop_pending_updates=True,
                    poll_interval=1.0,
                    timeout=10,
                )
            )
            self._loop.run_forever()
        except Exception:
            logger.exception("Telegram bot crashed")
        finally:
            self._loop.close()

    def _is_allowed(self, chat_id: int) -> bool:
        if not self.allowed_ids:
            return True
        return chat_id in self.allowed_ids

    # ── Message handler (prompt responses) ───────────────────────────────────

    async def _handle_message(self, update, context) -> None:
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            return
        self._active_chats.add(chat_id)

        step_run_id = self._awaiting_response.pop(chat_id, None)
        if not step_run_id:
            await update.message.reply_text(
                "No pending prompt to respond to. "
                "Responses are collected when a step is awaiting your input."
            )
            return

        response_text = update.message.text or ""

        from ..run import RunService
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
        if data.startswith("respond:"):
            step_run_id = data[len("respond:"):]
            self._awaiting_response[chat_id] = step_run_id
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                "Type your response for this step:"
            )

        elif data.startswith("complete:"):
            step_run_id = data[len("complete:"):]
            from ..run import RunService
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
            from ..run import RunService
            session = self.session_factory()
            try:
                run_svc = RunService(session)
                run_svc.archive_inbox_item(inbox_id)
                try:
                    await query.edit_message_text("Dismissed.")
                except Exception:
                    await query.edit_message_reply_markup(reply_markup=None)
            finally:
                session.close()

            photo_msgs = self._notification_photos.pop(inbox_id, [])
            for cid, message_id in photo_msgs:
                try:
                    await self._app.bot.delete_message(chat_id=cid, message_id=message_id)
                except Exception:
                    logger.debug("Failed to delete attachment message %s", message_id)

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

    async def _send_notification(self, chat_id: int, text: str, event: str, payload: dict) -> None:
        inbox_id = payload.get("inbox_id")
        step_run_id = payload.get("step_run_id")
        step_type = payload.get("step_type", "agent")

        markup = None
        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            buttons = []

            if event == "step.awaiting_user" and step_run_id:
                buttons.append(InlineKeyboardButton("Respond", callback_data=f"respond:{step_run_id}"))

            if inbox_id:
                buttons.append(InlineKeyboardButton("Dismiss", callback_data=f"dismiss:{inbox_id}"))

            if buttons:
                markup = InlineKeyboardMarkup([buttons])
        except ImportError:
            pass

        att_files: list[Path] = []
        if event == "run.completed":
            run_id = payload.get("run_id")
            if run_id:
                att_dir = Path.home() / ".llmflows" / "attachments" / run_id
                if att_dir.is_dir():
                    for f in sorted(att_dir.iterdir()):
                        if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                            size_mb = f.stat().st_size / (1024 * 1024)
                            if size_mb <= 10:
                                att_files.append(f)

        html = _to_telegram_html(text)
        text_msg = await self._app.bot.send_message(
            chat_id=chat_id,
            text=html,
            parse_mode="HTML",
            reply_markup=markup if not att_files else None,
        )

        if att_files:
            photo_msgs: list[tuple[int, int]] = [(chat_id, text_msg.message_id)]
            for i, f in enumerate(att_files):
                is_last = i == len(att_files) - 1
                last_markup = markup if is_last else None
                try:
                    size_mb = f.stat().st_size / (1024 * 1024)
                    msg = None
                    if size_mb <= 5:
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
            summary = payload.get("summary")
            text = f"**{name}** — {outcome}"
            if summary:
                text += f"\n\n{summary}"
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
