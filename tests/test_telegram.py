"""Tests for the Telegram bot — flow improvement buttons and help version."""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from llmflows.db.models import Base, Flow, FlowRun, FlowStep, InboxItem, Space
from llmflows.services.gateway.telegram import TelegramBot, _to_telegram_html


@pytest.fixture
def tg_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def tg_bot(tg_db):
    factory = MagicMock(return_value=tg_db)
    with patch.dict("sys.modules", {"telegram": MagicMock(), "telegram.ext": MagicMock(), "telegram.request": MagicMock()}):
        bot = TelegramBot.__new__(TelegramBot)
        bot.config = {"bot_token": "fake"}
        bot.session_factory = factory
        bot.bot_token = "fake"
        bot.allowed_ids = set()
        bot._active_chats = set()
        bot._awaiting_response = {}
        bot._notification_photos = {}
        bot._pending_run_vars = {}
        bot._app = MagicMock()
        bot._loop = MagicMock()
    return bot


@pytest.fixture
def space_and_flow(tg_db, tmp_path):
    space = Space(name="test-space", path=str(tmp_path))
    tg_db.add(space)
    tg_db.flush()

    flow = Flow(name="my-flow", space_id=space.id)
    tg_db.add(flow)
    tg_db.flush()

    step = FlowStep(flow_id=flow.id, name="step-1", position=0, step_type="agent", content="do stuff")
    tg_db.add(step)
    tg_db.flush()

    run = FlowRun(flow_id=flow.id, space_id=space.id, outcome="completed")
    tg_db.add(run)
    tg_db.flush()

    return space, flow, run


class TestFormatNotification:
    """_format_notification produces the right text for each event type."""

    def test_flow_improvement_event(self):
        text = TelegramBot._format_notification("flow.improvement", {
            "flow_name": "my-flow",
            "improvement": "Combine steps 2 and 3.",
        })
        assert "my-flow" in text
        assert "improvement proposed" in text
        assert "Combine steps 2 and 3." in text

    def test_run_completed_event(self):
        text = TelegramBot._format_notification("run.completed", {
            "flow_name": "deploy",
            "outcome": "completed",
            "duration_seconds": 120,
        })
        assert "deploy" in text
        assert "completed" in text
        assert "2m" in text

    def test_unknown_event_returns_none(self):
        assert TelegramBot._format_notification("unknown.event", {}) is None


class TestNotificationButtons:
    """_send_notification attaches the correct buttons per event type."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_flow_improvement_has_accept_decline(self, tg_bot):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        sent_markup = {}

        async def fake_send(chat_id, text, parse_mode=None, reply_markup=None, reply_to_message_id=None):
            sent_markup["markup"] = reply_markup
            msg = MagicMock()
            msg.message_id = 1
            return msg

        tg_bot._app.bot.send_message = fake_send
        tg_bot._send_message_safe = AsyncMock(side_effect=lambda cid, txt, mk=None, **kw: MagicMock(message_id=1))

        self._run(tg_bot._send_notification(
            chat_id=123,
            text="test",
            event="flow.improvement",
            payload={"inbox_id": "inbox-1"},
        ))

        mk = tg_bot._send_message_safe.call_args
        assert mk is not None
        markup = mk[0][2] if len(mk[0]) > 2 else mk[1].get("markup")
        if markup is None and len(mk[0]) > 2:
            markup = mk[0][2]

        assert markup is not None
        buttons = markup.inline_keyboard[0]
        texts = [b.text for b in buttons]
        assert "Accept" in texts
        assert "Decline" in texts
        assert "Dismiss" not in texts

    def test_run_completed_has_dismiss(self, tg_bot):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        tg_bot._send_message_safe = AsyncMock(side_effect=lambda cid, txt, mk=None, **kw: MagicMock(message_id=1))

        self._run(tg_bot._send_notification(
            chat_id=123,
            text="test",
            event="run.completed",
            payload={"inbox_id": "inbox-2"},
        ))

        mk = tg_bot._send_message_safe.call_args
        markup = mk[0][2] if len(mk[0]) > 2 else None
        assert markup is not None
        buttons = markup.inline_keyboard[0]
        texts = [b.text for b in buttons]
        assert "Dismiss" in texts
        assert "Accept" not in texts


class TestAcceptImprovement:
    """_cb_accept_improvement applies the flow proposal and archives the inbox item."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_accept_applies_proposal(self, tg_bot, tg_db, space_and_flow, tmp_path):
        space, flow, run = space_and_flow

        inbox = InboxItem(type="flow_improvement", reference_id=run.id, space_id=space.id, title="proposal")
        tg_db.add(inbox)
        tg_db.flush()

        artifacts_dir = tmp_path / ".llmflows" / "my-flow" / "runs" / run.id / "artifacts"
        artifacts_dir.mkdir(parents=True)
        flow_json = {
            "name": "my-flow",
            "steps": [{"name": "improved-step", "type": "agent", "content": "better"}],
        }
        (artifacts_dir / "flow.json").write_text(json.dumps(flow_json))
        (artifacts_dir / "improvement.md").write_text("Made it better")

        query = MagicMock()
        query.edit_message_text = AsyncMock()

        self._run(tg_bot._cb_accept_improvement(query, inbox.id))

        query.edit_message_text.assert_called_once()
        call_text = query.edit_message_text.call_args[0][0]
        assert "Accepted" in call_text
        assert "my-flow" in call_text
        assert "v" in call_text

    def test_accept_not_found(self, tg_bot, tg_db):
        query = MagicMock()
        query.edit_message_text = AsyncMock()

        self._run(tg_bot._cb_accept_improvement(query, "nonexistent"))

        query.edit_message_text.assert_called_once()
        assert "not found" in query.edit_message_text.call_args[0][0]


class TestDeclineImprovement:
    """_cb_decline_improvement archives the inbox item and cleans up messages."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_decline_archives_item(self, tg_bot, tg_db, space_and_flow):
        space, flow, run = space_and_flow

        inbox = InboxItem(type="flow_improvement", reference_id=run.id, space_id=space.id, title="proposal")
        tg_db.add(inbox)
        tg_db.flush()

        query = MagicMock()
        query.message.chat_id = 123
        query.message.message_id = 42
        query.edit_message_text = AsyncMock()
        tg_bot._app.bot.delete_message = AsyncMock()

        self._run(tg_bot._cb_decline_improvement(query, inbox.id))

        tg_bot._app.bot.delete_message.assert_called_once()


class TestHelpVersion:
    """The /help command includes the llmflows version."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_help_includes_version(self, tg_bot):
        update = MagicMock()
        update.effective_chat.id = 123
        update.message.reply_text = AsyncMock()

        self._run(tg_bot._handle_help_command(update, None))

        call_text = update.message.reply_text.call_args[0][0]
        assert "llmflows bot" in call_text
        assert " v" in call_text


class TestInboxDetailFlowImprovement:
    """_cb_inbox_detail handles flow_improvement items with accept/decline buttons."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_detail_shows_accept_decline(self, tg_bot, tg_db, space_and_flow, tmp_path):
        space, flow, run = space_and_flow

        inbox = InboxItem(type="flow_improvement", reference_id=run.id, space_id=space.id, title="proposal")
        tg_db.add(inbox)
        tg_db.flush()

        artifacts_dir = tmp_path / ".llmflows" / "my-flow" / "runs" / run.id / "artifacts"
        artifacts_dir.mkdir(parents=True)
        (artifacts_dir / "improvement.md").write_text("Proposed improvement details")

        query = MagicMock()
        query.message.chat_id = 123
        query.edit_message_reply_markup = AsyncMock()

        sent_markups = []

        async def fake_send_safe(chat_id, text, markup=None, **kwargs):
            sent_markups.append(markup)
            msg = MagicMock()
            msg.message_id = 99
            return msg

        tg_bot._send_message_safe = fake_send_safe

        self._run(tg_bot._cb_inbox_detail(query, inbox.id))

        last_markup = next((m for m in reversed(sent_markups) if m is not None), None)
        assert last_markup is not None
        buttons = last_markup.inline_keyboard[0]
        texts = [b.text for b in buttons]
        assert "Accept" in texts
        assert "Decline" in texts
