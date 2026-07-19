"""Telegram bot for llm-flows — notifications and human-step responses.

Pushes HITL messages in full; other inbox events update a single unread-count
digest message. Flow improvement proposals are inbox-only (no push).
Allows responding to prompt steps and completing manual steps directly from Telegram.
"""

import asyncio
import json
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...db.models import FlowRun, InboxItem, Space as SpaceModel, StepRun
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
    return _format_duration(secs)


def _format_duration(secs: float | int | None) -> str:
    if secs is None:
        return ""
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m"
    hours, mins = divmod(mins, 60)
    return f"{hours}h{mins}m"


def _esc_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _truncate_preview(text: str, max_len: int = 180) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_len:
        return collapsed
    return collapsed[: max_len - 1].rstrip() + "…"


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
        self._awaiting_improvement: dict[int, str] = {}  # chat_id -> inbox_id
        self._notification_photos: dict[str, list[tuple[int, int]]] = {}
        self._pending_run_vars: dict[int, dict] = {}  # chat_id -> {space_id, flow_id, flow_name, vars: [{key, current}], overrides: {}, pending_idx: int}
        self._muted: bool = False
        self._digest_msg_id: dict[int, int] = {}  # chat_id -> last unread-digest message_id
        self._last_was_digest: dict[int, bool] = {}  # chat_id -> previous push was unread digest
        self._app = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._load_pending_run_vars()
        self._load_state()

    @staticmethod
    def _pending_state_file() -> Path:
        from ...config import ensure_system_dir
        d = ensure_system_dir() / "telegram"
        d.mkdir(parents=True, exist_ok=True)
        return d / "pending.json"

    def _load_pending_run_vars(self) -> None:
        """Restore pending /run variable collection state across daemon restarts."""
        try:
            f = self._pending_state_file()
            if f.exists():
                data = json.loads(f.read_text())
                self._pending_run_vars = {int(k): v for k, v in data.items()}
        except (OSError, ValueError, TypeError):
            self._pending_run_vars = {}

    def _save_pending_run_vars(self) -> None:
        try:
            f = self._pending_state_file()
            f.write_text(json.dumps({str(k): v for k, v in self._pending_run_vars.items()}))
        except OSError:
            logger.exception("Failed to persist telegram pending state")

    @staticmethod
    def _state_file() -> Path:
        from ...config import ensure_system_dir
        d = ensure_system_dir() / "telegram"
        d.mkdir(parents=True, exist_ok=True)
        return d / "state.json"

    def _load_state(self) -> None:
        self._muted = False
        self._digest_msg_id = {}
        self._last_was_digest = {}
        try:
            f = self._state_file()
            if f.exists():
                data = json.loads(f.read_text())
                self._muted = bool(data.get("muted", False))
                digest = data.get("digest") or {}
                for chat_key, entry in digest.items():
                    chat_id = int(chat_key)
                    if isinstance(entry, dict):
                        msg_id = entry.get("message_id")
                        if msg_id is not None:
                            self._digest_msg_id[chat_id] = int(msg_id)
                        self._last_was_digest[chat_id] = bool(entry.get("last_was_digest", False))
        except (OSError, ValueError, TypeError):
            pass

    def _save_state(self) -> None:
        try:
            f = self._state_file()
            chat_ids = set(self._digest_msg_id) | set(self._last_was_digest)
            digest = {
                str(cid): {
                    "message_id": self._digest_msg_id[cid],
                    "last_was_digest": self._last_was_digest.get(cid, False),
                }
                for cid in chat_ids
                if cid in self._digest_msg_id
            }
            f.write_text(json.dumps({"muted": self._muted, "digest": digest}))
        except OSError:
            logger.exception("Failed to persist telegram state")

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

            future = asyncio.run_coroutine_threadsafe(_shutdown(), self._loop)
            try:
                future.result(timeout=15)
            except Exception:
                logger.debug("Telegram shutdown future timed out", exc_info=True)
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=5)
        self._app = None
        self._loop = None
        self._thread = None
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
        app.add_handler(CommandHandler("mute", self._handle_mute_command))
        app.add_handler(CommandHandler("audit", self._handle_audit_command))
        app.add_handler(CommandHandler("upgrade", self._handle_upgrade_command))
        app.add_handler(CommandHandler("help", self._handle_help_command))
        app.add_handler(CallbackQueryHandler(self._handle_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))

        self._app = app

        try:
            self._loop.run_until_complete(app.initialize())
            self._loop.run_until_complete(
                app.bot.delete_webhook(drop_pending_updates=True)
            )
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
            BotCommand("mute", "Toggle notification mute"),
            BotCommand("audit", "Security audit status"),
            BotCommand("upgrade", "Upgrade llmflows & restart"),
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

            runs: list[tuple[FlowRun, SpaceModel, str]] = []
            for space in spaces:
                for r in run_svc.get_active_by_space(space.id):
                    runs.append((r, space, "active"))
                for r in run_svc.get_all_pending(space.id):
                    runs.append((r, space, "pending"))

            if not runs:
                await update.message.reply_text("No active or queued runs.")
                return

            for r, space, kind in runs:
                await self._send_active_run_card(update, r, space, kind, now)
        finally:
            session.close()

    @staticmethod
    def _format_run_card(
        run: "FlowRun", space: "SpaceModel", kind: str, now: datetime,
    ) -> tuple[str, str]:
        """Build HTML text and cancel/dequeue button label for one run."""
        flow_label = run.flow_name or "?"
        if kind == "active":
            status = run.status
            if status == "awaiting_user":
                icon, status_label = "🟠", "awaiting input"
            elif status == "paused":
                icon, status_label = "⏸️", "paused"
            else:
                icon, status_label = "🟡", "running"
            elapsed = _format_elapsed(run.started_at, now)
            step = run.current_step or "starting"
            lines = [
                f"{icon} <b>{flow_label}</b>",
                f"Status: {status_label}  ·  {elapsed}",
                f"Step: <i>{step}</i>",
            ]
            btn_label = f"Cancel {flow_label}"
        else:
            waited = _format_elapsed(run.created_at, now)
            lines = [
                f"🔵 <b>{flow_label}</b>",
                f"Status: queued  ·  {waited}",
            ]
            btn_label = f"Dequeue {flow_label}"

        lines.append(f"Space: {space.name}")

        run_vars = run.run_variables
        if run_vars:
            var_parts = [f"{k}={v}" for k, v in run_vars.items()]
            lines.append(f"Vars: <code>{', '.join(var_parts)}</code>")

        return "\n".join(lines), btn_label

    async def _send_active_run_card(
        self, update, run: "FlowRun", space: "SpaceModel", kind: str, now: datetime,
    ) -> None:
        text, btn_label = self._format_run_card(run, space, kind, now)
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(
            btn_label, callback_data=f"cancelrun:{run.id}",
        )]])
        await self._send_message_safe(
            update.effective_chat.id, text, markup,
        )

    # ── /inbox command — list inbox items ────────────────────────────────────

    async def _handle_inbox_command(self, update, context) -> None:
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            return
        self._active_chats.add(chat_id)
        await self._send_inbox_list(chat_id, update.message.reply_text)

    async def _send_inbox_list(self, chat_id: int, reply) -> None:
        """List active inbox items (including silent flow improvements)."""
        session = self.session_factory()
        try:
            run_svc = RunService(session)
            items = run_svc.list_inbox()
            if not items:
                await reply("Inbox is empty.")
                return

            now = datetime.now(timezone.utc)
            sent = 0

            for item in items:
                space = session.query(SpaceModel).filter_by(id=item.space_id).first()

                if item.type == "awaiting_user":
                    sr = session.query(StepRun).filter_by(id=item.reference_id).first()
                    if not sr or sr.completed_at:
                        run_svc.archive_inbox_item(item.id)
                        continue
                    run = session.query(FlowRun).filter_by(id=sr.flow_run_id).first()
                    flow_name = (run.flow_name if run else None) or "?"
                    waited = _format_elapsed(sr.awaiting_user_at or item.created_at, now)

                    user_message = ""
                    if space and run:
                        try:
                            from ..context import HITL_FILE
                            artifacts_dir = ContextService.get_artifacts_dir(
                                Path(space.path), run.id, run.flow_name or "",
                            )
                            hitl_file = (
                                artifacts_dir
                                / ContextService.step_dir_name(sr.step_position, sr.step_name)
                                / HITL_FILE
                            )
                            if hitl_file.exists():
                                user_message = hitl_file.read_text().strip()
                        except (PermissionError, OSError):
                            pass
                    hitl_title, _ = ContextService.parse_inbox_message(user_message)
                    headline = hitl_title or sr.step_name.replace("-", " ")
                    text = (
                        f"⏳ <b>{_esc_html(headline)}</b>\n"
                        f"<i>{_esc_html(flow_name)}</i> · waiting {waited}"
                    )
                    buttons = [
                        [
                            InlineKeyboardButton("Details", callback_data=f"inbox_detail:{item.id}"),
                            InlineKeyboardButton("Respond", callback_data=f"respond:{sr.id}"),
                        ],
                    ]
                    await reply(
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

                    inbox_message = ""
                    if space:
                        try:
                            artifacts_dir = ContextService.get_artifacts_dir(
                                Path(space.path), run.id, run.flow_name or "",
                            )
                            inbox_message = ContextService.read_inbox_message(artifacts_dir)
                        except (PermissionError, OSError):
                            pass
                    inbox_title, inbox_body = ContextService.parse_inbox_message(inbox_message)
                    if inbox_title:
                        headline = inbox_title
                        preview = inbox_body
                    elif (run.summary or "").strip():
                        parts = run.summary.strip().split("\n", 1)
                        headline = parts[0].strip()
                        preview = parts[1].strip() if len(parts) > 1 else ""
                    else:
                        headline = flow_name
                        preview = ""

                    meta: list[str] = []
                    dur = _format_duration(run.duration_seconds)
                    if dur:
                        meta.append(dur)
                    if run.cost_usd is not None:
                        meta.append(f"${run.cost_usd:.4f}")
                    sub = f"<i>{_esc_html(flow_name)}</i>"
                    if meta:
                        sub += f" · {' · '.join(meta)}"

                    lines = [f"{emoji} <b>{_esc_html(headline)}</b>"]
                    if preview:
                        lines.append(_esc_html(_truncate_preview(preview)))
                    lines.append(sub)
                    text = "\n".join(lines)
                    buttons = [
                        [
                            InlineKeyboardButton("Details", callback_data=f"inbox_detail:{item.id}"),
                            InlineKeyboardButton("Archive", callback_data=f"dismiss:{item.id}"),
                        ],
                    ]
                    await reply(
                        text, parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(buttons),
                    )
                    sent += 1

                elif item.type == "flow_improvement":
                    run = session.query(FlowRun).filter_by(id=item.reference_id).first()
                    if not run:
                        run_svc.archive_inbox_item(item.id)
                        continue
                    flow_name = run.flow_name or "?"
                    text = (
                        f"💡 <b>Flow improvement proposed</b>\n"
                        f"<i>{_esc_html(flow_name)}</i>"
                    )
                    buttons = [
                        [
                            InlineKeyboardButton("Details", callback_data=f"inbox_detail:{item.id}"),
                            InlineKeyboardButton("Respond", callback_data=f"accept_improvement:{item.id}"),
                        ],
                    ]
                    await reply(
                        text, parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(buttons),
                    )
                    sent += 1

            if not sent:
                await reply("Inbox is empty.")
        finally:
            session.close()

    # ── /upgrade command — pull latest version and restart ──────────────────

    async def _handle_upgrade_command(self, update, context) -> None:
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            return
        self._active_chats.add(chat_id)

        await update.message.reply_text("Upgrading llmflows…")

        from ...services.upgrade import (
            pip_upgrade, kill_ui_processes,
            start_ui_background, trigger_daemon_reexec,
        )

        loop = asyncio.get_event_loop()
        success, old_ver, new_ver, output = await loop.run_in_executor(
            None, pip_upgrade,
        )

        if not success:
            short = output[:800] if len(output) > 800 else output
            await update.message.reply_text(
                f"Upgrade failed:\n<pre>{short}</pre>",
                parse_mode="HTML",
            )
            return

        if old_ver == new_ver:
            await update.message.reply_text(
                f"Already at latest version (<code>{old_ver}</code>).",
                parse_mode="HTML",
            )
            return

        killed = await loop.run_in_executor(None, kill_ui_processes)
        ui_pid = await loop.run_in_executor(
            None, lambda: start_ui_background(no_daemon=True),
        )

        parts = [f"Upgraded <code>{old_ver}</code> → <code>{new_ver}</code>"]
        if killed:
            parts.append(f"UI restarted (pid {ui_pid})" if ui_pid else "UI stopped")
        parts.append("Restarting daemon…")
        await update.message.reply_text("\n".join(parts), parse_mode="HTML")

        trigger_daemon_reexec()

    # ── /mute command — toggle notification mute ───────────────────────────

    async def _handle_mute_command(self, update, context) -> None:
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            return
        self._active_chats.add(chat_id)

        self._muted = not self._muted
        self._save_state()

        if self._muted:
            await update.message.reply_text(
                "🔇 Notifications muted. HITL steps still notify.",
            )
        else:
            await update.message.reply_text("🔔 Notifications unmuted.")

    # ── /audit command — show security audit status ────────────────────────

    async def _handle_audit_command(self, update, context) -> None:
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
                [InlineKeyboardButton(s.name, callback_data=f"audit_space:{s.id}")]
                for s in spaces
            ]
            await update.message.reply_text(
                "Select a space:",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        finally:
            session.close()

    # ── /help — show commands and chat ID ───────────────────────────────────

    async def _handle_help_command(self, update, context) -> None:
        from ... import __version__
        chat_id = update.effective_chat.id
        self._active_chats.add(chat_id)
        mute_status = "on" if self._muted else "off"
        await update.message.reply_text(
            f"<b>llmflows bot</b> v{__version__}\n\n"
            f"Chat ID: <code>{chat_id}</code>\n"
            f"Mute: {mute_status}\n\n"
            f"<b>Commands:</b>\n"
            f"/run — Start a flow\n"
            f"/active — List active &amp; queued runs\n"
            f"/inbox — Show inbox items\n"
            f"/mute — Toggle notification mute\n"
            f"/audit — Security audit status\n"
            f"/upgrade — Upgrade &amp; restart\n"
            f"/help — Show this message",
            parse_mode="HTML",
        )

    # ── Message handler (prompt responses + variable collection) ────────────

    async def _handle_message(self, update, context) -> None:
        chat_id = update.effective_chat.id
        if not self._is_allowed(chat_id):
            return
        self._active_chats.add(chat_id)

        inbox_id = self._awaiting_improvement.pop(chat_id, None)
        if inbox_id:
            selection = update.message.text or ""
            await self._process_improvement_response(update, inbox_id, selection)
            return

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
                self._save_pending_run_vars()
                next_key = pending["vars"][next_idx]["key"]
                await update.message.reply_text(
                    f"Enter value for <code>{next_key}</code>:",
                    parse_mode="HTML",
                )
            else:
                ctx = self._pending_run_vars.pop(chat_id)
                self._save_pending_run_vars()
                session = self.session_factory()
                try:
                    run_svc = RunService(session)
                    try:
                        run = run_svc.enqueue(ctx["space_id"], ctx["flow_id"], run_variables=ctx["overrides"])
                    except ValueError as e:
                        await update.message.reply_text(f"Cannot run {ctx['flow_name']}: {e}")
                        return
                    await update.message.reply_text(
                        f"Queued <b>{ctx['flow_name']}</b>\nRun <code>{run.id}</code>",
                        parse_mode="HTML",
                    )
                finally:
                    session.close()
            return

        await update.message.reply_text(
            "No pending prompt to respond to. Use /run to start a flow.",
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

        if data == "show_inbox":
            await self._send_inbox_list(chat_id, query.message.reply_text)
            return

        if data.startswith("cancelrun:"):
            await self._cb_cancel_run(query, data[len("cancelrun:"):])
            return

        if data.startswith("audit_space:"):
            await self._cb_audit_space(query, chat_id, data[len("audit_space:"):])
            return

        if data.startswith("audit_bulk:"):
            await self._cb_audit_bulk(query, chat_id, data[len("audit_bulk:"):])
            return

        if data.startswith("accept_improvement:"):
            await self._cb_accept_improvement(query, data[len("accept_improvement:"):])
            return

        if data.startswith("decline_improvement:"):
            await self._cb_decline_improvement(query, data[len("decline_improvement:"):])
            return

        if data.startswith("discard_improvement:"):
            await self._cb_discard_improvement(query, data[len("discard_improvement:"):])
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
                    await self._refresh_unread_digest(chat_id)
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
            await self._refresh_unread_digest(chat_id)

    # ── Cancel run callback ─────────────────────────────────────────────────

    async def _cb_cancel_run(self, query, run_id: str) -> None:
        session = self.session_factory()
        try:
            run_svc = RunService(session)
            run = run_svc.get(run_id)
            if not run:
                await query.edit_message_text("Run not found.")
                return
            if run.completed_at:
                await query.edit_message_text(f"Run <code>{run_id}</code> already completed.", parse_mode="HTML")
                return

            flow_label = run.flow_name or run_id
            if not run.started_at:
                session.delete(run)
                session.commit()
                await query.edit_message_text(f"Dequeued <b>{flow_label}</b> (<code>{run_id}</code>)", parse_mode="HTML")
                return

            _, _killed = run_svc.cancel_run(run_id)
            await query.edit_message_text(f"Cancelled <b>{flow_label}</b> (<code>{run_id}</code>)", parse_mode="HTML")
        finally:
            session.close()

    # ── Audit space callback ─────────────────────────────────────────────

    async def _cb_audit_space(self, query, chat_id: int, space_id: str) -> None:
        from ..audit import FlowAuditService, SecurityAuditService
        from ..skill import SkillService

        session = self.session_factory()
        try:
            space = SpaceService(session).get(space_id)
            if not space:
                await query.edit_message_text("Space not found.")
                return

            counts = {"safe": 0, "unsafe": 0, "error": 0, "unaudited": 0}
            lines: list[str] = [f"<b>{space.name}</b>"]

            flows = FlowService(session).list_by_space(space.id)
            for f in flows:
                audit = FlowAuditService.get_audit(space.path, f.name)
                if audit is None:
                    icon, status = "❓", "not audited"
                    counts["unaudited"] += 1
                elif audit.status == "safe":
                    icon, status = "✅", "safe"
                    counts["safe"] += 1
                elif audit.status == "unsafe":
                    icon, status = "⚠️", "unsafe"
                    counts["unsafe"] += 1
                else:
                    icon, status = "⏳", audit.status
                    counts["error"] += 1
                lines.append(f"  {icon} {f.name} — {status}")

            for skill_info in SkillService.discover(space.path):
                audit = SecurityAuditService.get_audit(space.path, skill_info.name)
                if audit is None:
                    icon, status = "❓", "not audited"
                    counts["unaudited"] += 1
                elif audit.status == "safe":
                    icon, status = "✅", "safe"
                    counts["safe"] += 1
                elif audit.status == "unsafe":
                    icon, status = "⚠️", "unsafe"
                    counts["unsafe"] += 1
                else:
                    icon, status = "⏳", audit.status
                    counts["error"] += 1
                lines.append(f"  {icon} 📄 {skill_info.name} — {status}")

            summary = " · ".join(
                f"{v} {k}" for k, v in counts.items() if v > 0
            )
            text = "\n".join(lines) + f"\n\n{summary}"

            needs_audit = counts["unsafe"] + counts["error"] + counts["unaudited"]
            markup = None
            if needs_audit > 0:
                markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        f"Run Bulk Audit ({needs_audit})",
                        callback_data=f"audit_bulk:{space_id}",
                    ),
                ]])

            await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
        finally:
            session.close()

    # ── Bulk audit callback ────────────────────────────────────────────────

    async def _cb_audit_bulk(self, query, chat_id: int, space_id: str) -> None:
        await query.edit_message_reply_markup(reply_markup=None)
        await self._send_message_safe(chat_id, "Running security audit…")

        from ..audit import FlowAuditService, SecurityAuditService
        from ..skill import SkillService

        loop = asyncio.get_event_loop()

        def _do_bulk():
            results = {"audited": 0, "safe": 0, "unsafe": 0, "error": 0}
            session = self.session_factory()
            try:
                space = SpaceService(session).get(space_id)
                if not space:
                    return results
                flows = FlowService(session).list_by_space(space.id)
                for f in flows:
                    existing = FlowAuditService.get_audit(space.path, f.name)
                    if existing is None or existing.status in ("unsafe", "error"):
                        try:
                            r = FlowAuditService.run_audit(space.path, f.name, f.to_dict())
                            results["audited"] += 1
                            results[r.status] = results.get(r.status, 0) + 1
                        except Exception:
                            results["error"] += 1
                            logger.warning("Audit failed for flow %s", f.name, exc_info=True)

                for skill_info in SkillService.discover(space.path):
                    existing = SecurityAuditService.get_audit(space.path, skill_info.name)
                    if existing is None or existing.status in ("unsafe", "error"):
                        try:
                            r = SecurityAuditService.run_audit(space.path, skill_info.name)
                            results["audited"] += 1
                            results[r.status] = results.get(r.status, 0) + 1
                        except Exception:
                            results["error"] += 1
                            logger.warning("Audit failed for skill %s", skill_info.name, exc_info=True)
            finally:
                session.close()
            return results

        results = await loop.run_in_executor(None, _do_bulk)
        summary_parts = [f"Audited {results['audited']} items"]
        if results["safe"]:
            summary_parts.append(f"✅ {results['safe']} safe")
        if results["unsafe"]:
            summary_parts.append(f"⚠️ {results['unsafe']} unsafe")
        if results["error"]:
            summary_parts.append(f"⏳ {results['error']} errors")
        await self._send_message_safe(chat_id, " · ".join(summary_parts))

    # ── Flow improvement callbacks ─────────────────────────────────────────

    async def _cb_accept_improvement(self, query, inbox_id: str) -> None:
        chat_id = query.message.chat_id
        self._awaiting_improvement[chat_id] = inbox_id
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "Which improvements to apply? (empty = all):"
        )

    async def _process_improvement_response(self, update, inbox_id: str, selection: str) -> None:
        from ..audit import FlowAuditService
        from ..context import ContextService, generate_flow_from_improvements

        session = self.session_factory()
        try:
            item = session.query(InboxItem).filter_by(id=inbox_id).first()
            if not item or item.type != "flow_improvement":
                await update.message.reply_text("Improvement proposal not found.")
                return
            if item.archived_at:
                await update.message.reply_text("Already handled.")
                return

            run = session.query(FlowRun).filter_by(id=item.reference_id).first()
            space = session.query(SpaceModel).filter_by(id=item.space_id).first()
            if not run or not space or not run.flow_id:
                await update.message.reply_text("Run or flow not found.")
                return

            artifacts_dir = ContextService.get_artifacts_dir(
                Path(space.path), run.id, run.flow_name or "",
            )
            improvement_text = ContextService.read_improvement(artifacts_dir)
            if not improvement_text:
                await update.message.reply_text("No improvement proposal found.")
                return

            flow_svc = FlowService(session)
            current_flow = flow_svc.export_flow_dict(run.flow_id)
            flow_json = generate_flow_from_improvements(current_flow, improvement_text, selection)

            flow_obj = flow_svc.get(run.flow_id)
            flow_name = (flow_obj.name if flow_obj else None) or run.flow_name or "?"

            audit_result = FlowAuditService.run_audit(space.path, flow_name, flow_json)
            if audit_result.status == "unsafe":
                await update.message.reply_text(
                    f"❌ Security audit failed for <b>{flow_name}</b>: {audit_result.summary}",
                    parse_mode="HTML",
                )
                return

            flow = flow_svc.apply_flow_proposal(run.flow_id, flow_json)
            if not flow:
                await update.message.reply_text("Failed to apply proposal.")
                return

            FlowAuditService.save_audit(space.path, flow.name, audit_result)

            if selection.strip():
                ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                flow_dir = ContextService.get_flow_dir(Path(space.path), run.flow_name or "")
                entry = (
                    f"## Skipped improvements ({ts})\n\n"
                    f"From run {run.id}, the user approved only: \"{selection.strip()}\"\n\n"
                    f"The full proposal was:\n\n{improvement_text}\n\n"
                    "Do not re-propose the items that were not selected."
                )
                ContextService.append_memory(flow_dir, entry)

            RunService(session).archive_inbox_item(inbox_id)
            await update.message.reply_text(
                f"✅ Applied improvements for <b>{flow_name}</b> (v{flow.version})",
                parse_mode="HTML",
            )
            await self._refresh_unread_digest(update.effective_chat.id)
        except ValueError as e:
            await update.message.reply_text(f"Error: {e}")
        finally:
            session.close()

    async def _cb_decline_improvement(self, query, inbox_id: str) -> None:
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

        tracked = self._notification_photos.pop(inbox_id, [])
        chat_id = query.message.chat_id
        try:
            await self._app.bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
        except Exception:
            try:
                await query.edit_message_text("Declined.")
            except Exception:
                pass
        for cid, message_id in tracked:
            if message_id == query.message.message_id:
                continue
            try:
                await self._app.bot.delete_message(chat_id=cid, message_id=message_id)
            except Exception:
                logger.debug("Failed to delete message %s", message_id)
        await self._refresh_unread_digest(chat_id)

    async def _cb_discard_improvement(self, query, inbox_id: str) -> None:
        session = self.session_factory()
        try:
            RunService(session).archive_inbox_item(inbox_id)
        finally:
            session.close()

        tracked = self._notification_photos.pop(inbox_id, [])
        chat_id = query.message.chat_id
        try:
            await self._app.bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
        except Exception:
            try:
                await query.edit_message_text("Discarded.")
            except Exception:
                pass
        for cid, message_id in tracked:
            if message_id == query.message.message_id:
                continue
            try:
                await self._app.bot.delete_message(chat_id=cid, message_id=message_id)
            except Exception:
                logger.debug("Failed to delete message %s", message_id)
        await self._refresh_unread_digest(chat_id)

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
                self._save_pending_run_vars()
                first_var = empty_vars[0]["key"]
                await query.edit_message_text(
                    f"<b>{flow.name}</b> needs variable values.\n\n"
                    f"Enter value for <code>{first_var}</code>:",
                    parse_mode="HTML",
                )
                return

            run_svc = RunService(session)
            try:
                run = run_svc.enqueue(space_id, flow_id)
            except ValueError as e:
                await query.edit_message_text(f"Cannot run {flow.name}: {e}")
                return
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

                user_message = ""
                if space and run:
                    try:
                        from ..context import HITL_FILE
                        artifacts_dir = ContextService.get_artifacts_dir(
                            Path(space.path), run.id, run.flow_name or "",
                        )
                        hitl_file = (
                            artifacts_dir
                            / ContextService.step_dir_name(sr.step_position, sr.step_name)
                            / HITL_FILE
                        )
                        if hitl_file.exists():
                            user_message = hitl_file.read_text().strip()
                    except (PermissionError, OSError):
                        pass

                if user_message:
                    text = _to_telegram_html(user_message)
                else:
                    text = "<i>No message from this step.</i>"

                markup = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("Respond", callback_data=f"respond:{sr.id}"),
                        InlineKeyboardButton("Complete", callback_data=f"complete:{sr.id}"),
                    ],
                ])
                sent_ids = await self._send_detail_chunks(chat_id, text, markup, inbox_id)
                self._notification_photos[inbox_id] = sent_ids
                await self._delete_inbox_list_message(query)

            elif item.type == "completed_run":
                run = session.query(FlowRun).filter_by(id=item.reference_id).first()
                if not run:
                    await query.edit_message_text("Run not found.")
                    return

                detail = ""
                if space:
                    try:
                        artifacts_dir = ContextService.get_artifacts_dir(
                            Path(space.path), run.id, run.flow_name or "",
                        )
                        detail = ContextService.read_inbox_message(artifacts_dir)
                    except (PermissionError, OSError):
                        pass
                if not detail:
                    detail = (run.summary or "").strip()

                if detail:
                    text = _to_telegram_html(detail)
                else:
                    text = "<i>No summary available.</i>"

                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("Archive", callback_data=f"dismiss:{inbox_id}")],
                ])
                sent_ids = await self._send_detail_chunks(chat_id, text, markup, inbox_id)
                self._notification_photos[inbox_id] = sent_ids
                await self._delete_inbox_list_message(query)

            elif item.type == "flow_improvement":
                run = session.query(FlowRun).filter_by(id=item.reference_id).first()
                if not run:
                    await query.edit_message_text("Run not found.")
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

                text = f"<b>{flow_name}</b> — flow improvement proposed\n"
                if improvement_text:
                    detail_html = _to_telegram_html(improvement_text)
                    text += f"\n{detail_html}"
                else:
                    text += "\n<i>No improvement details available.</i>"

                markup = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("Respond", callback_data=f"accept_improvement:{inbox_id}"),
                        InlineKeyboardButton("Decline", callback_data=f"decline_improvement:{inbox_id}"),
                        InlineKeyboardButton("Discard", callback_data=f"discard_improvement:{inbox_id}"),
                    ],
                ])
                sent_ids = await self._send_detail_chunks(chat_id, text, markup, inbox_id)
                self._notification_photos[inbox_id] = sent_ids
                await self._delete_inbox_list_message(query)
        finally:
            session.close()

    async def _delete_inbox_list_message(self, query) -> None:
        """Remove the /inbox card after Details opens the full message."""
        try:
            await self._app.bot.delete_message(
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
            )
        except Exception:
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass

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

        # Flow improvements are inbox-only — surfaced via /inbox.
        if event == "flow.improvement":
            return

        if self._muted and event != "step.awaiting_user":
            return

        targets = self.allowed_ids or self._active_chats
        if not targets:
            return

        if event == "step.awaiting_user":
            for chat_id in targets:
                self._last_was_digest[chat_id] = False
                self._save_state()
                try:
                    asyncio.run_coroutine_threadsafe(
                        self._send_hitl_notification(chat_id, payload),
                        self._loop,
                    )
                except Exception:
                    logger.warning("Failed to send notification to chat %s", chat_id)
            return

        # Non-HITL events: bump/edit a single unread-count digest message.
        for chat_id in targets:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._send_or_update_unread_digest(chat_id),
                    self._loop,
                )
            except Exception:
                logger.warning("Failed to send unread digest to chat %s", chat_id)

    def _count_unread(self) -> int:
        session = self.session_factory()
        try:
            return RunService(session).count_inbox()
        finally:
            session.close()

    @staticmethod
    def _format_unread_digest(count: int) -> str:
        noun = "notification" if count == 1 else "notifications"
        return f"📬 You have <b>{count}</b> unread {noun}."

    def _unread_digest_markup(self):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("View", callback_data="show_inbox")],
        ])

    async def _send_or_update_unread_digest(self, chat_id: int) -> None:
        """Send or edit the unread-count digest for a chat."""
        count = self._count_unread()
        if count <= 0:
            return

        text = self._format_unread_digest(count)
        markup = self._unread_digest_markup()

        if self._last_was_digest.get(chat_id) and chat_id in self._digest_msg_id:
            msg_id = self._digest_msg_id[chat_id]
            try:
                await self._app.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
                return
            except Exception:
                logger.debug(
                    "Failed to edit unread digest for chat %s, sending new",
                    chat_id, exc_info=True,
                )

        msg = await self._send_message_safe(chat_id, text, markup)
        if msg:
            self._digest_msg_id[chat_id] = msg.message_id
            self._last_was_digest[chat_id] = True
            self._save_state()

    async def _refresh_unread_digest(self, chat_id: int) -> None:
        """Update or clear the digest after inbox items change."""
        if chat_id not in self._digest_msg_id:
            return
        count = self._count_unread()
        msg_id = self._digest_msg_id[chat_id]
        if count <= 0:
            try:
                await self._app.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception:
                try:
                    await self._app.bot.edit_message_text(
                        chat_id=chat_id, message_id=msg_id, text="Inbox is empty.",
                    )
                except Exception:
                    pass
            self._digest_msg_id.pop(chat_id, None)
            self._last_was_digest[chat_id] = False
            self._save_state()
            return
        if not self._last_was_digest.get(chat_id):
            return
        try:
            await self._app.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=self._format_unread_digest(count),
                parse_mode="HTML",
                reply_markup=self._unread_digest_markup(),
            )
        except Exception:
            logger.debug("Failed to refresh unread digest for chat %s", chat_id, exc_info=True)

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

    async def _send_hitl_notification(self, chat_id: int, payload: dict) -> None:
        """Push a HITL notification matching the UI/inbox content (hitl.md)."""
        step_run_id = payload.get("step_run_id")
        user_message = (payload.get("user_message") or "").strip()
        flow_name = payload.get("flow_name") or "?"
        title = (
            payload.get("inbox_title")
            or (payload.get("step_name") or "HITL").replace("-", " ")
        )

        if user_message:
            text = _to_telegram_html(user_message)
        else:
            text = (
                f"⏳ <b>{_esc_html(title)}</b>\n"
                f"<i>{_esc_html(flow_name)}</i>"
            )

        markup = None
        if step_run_id:
            markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("Respond", callback_data=f"respond:{step_run_id}"),
                InlineKeyboardButton("Complete", callback_data=f"complete:{step_run_id}"),
            ]])

        chunks = _split_message(text)
        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1
            msg = await self._send_message_safe(chat_id, chunk, markup if is_last else None)
            if not msg:
                return

    async def _send_notification(self, chat_id: int, text: str, event: str, payload: dict) -> None:
        """Send a full notification. Prefer _send_hitl_notification for HITL."""
        step_run_id = payload.get("step_run_id")

        markup = None
        if event == "step.awaiting_user" and step_run_id:
            markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("Respond", callback_data=f"respond:{step_run_id}"),
            ]])

        html = _to_telegram_html(text)
        chunks = _split_message(html)

        for i, chunk in enumerate(chunks):
            is_last_chunk = i == len(chunks) - 1
            chunk_markup = markup if is_last_chunk else None
            msg = await self._send_message_safe(chat_id, chunk, chunk_markup)
            if not msg:
                return

    @staticmethod
    def _format_notification(event: str, payload: dict) -> str | None:
        name = payload.get("flow_name") or "?"

        if event == "step.awaiting_user":
            # Prefer full hitl.md content (same as UI inbox).
            user_message = (payload.get("user_message") or "").strip()
            if user_message:
                return user_message
            title = (
                payload.get("inbox_title")
                or (payload.get("step_name") or "HITL").replace("-", " ")
            )
            return f"**{title}**\n*{name}*"

        # Kept for tests / backwards compatibility; non-HITL uses unread digest.
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

        if event == "flow.improvement":
            text = f"**{name}** — flow improvement proposed."
            improvement = payload.get("improvement")
            if improvement:
                text += f"\n\n{improvement}"
            return text

        return None
