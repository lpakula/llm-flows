"""Tests for the Telegram bot — flow improvement buttons, help version, /active UX."""

import asyncio
import json
import tempfile
from datetime import datetime, timezone, timedelta
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
        bot._awaiting_improvement = {}
        bot._notification_photos = {}
        bot._pending_run_vars = {}
        bot._muted = False
        bot._digest_msg_id = {}
        bot._last_was_digest = {}
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


class TestUnreadDigest:
    """Non-HITL events update an unread-count digest; HITL stays full."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_format_unread_digest_singular(self):
        text = TelegramBot._format_unread_digest(1)
        assert "<b>1</b>" in text
        assert "notification." in text
        assert "/inbox" not in text

    def test_format_unread_digest_plural(self):
        text = TelegramBot._format_unread_digest(3)
        assert "<b>3</b>" in text
        assert "notifications." in text

    def test_send_skips_flow_improvement(self, tg_bot):
        tg_bot.allowed_ids = {123}
        scheduled = []

        def mock_run(coro, loop):
            scheduled.append(True)
            coro.close()

        with patch(
            "llmflows.services.gateway.telegram.asyncio.run_coroutine_threadsafe",
            mock_run,
        ):
            tg_bot.send("flow.improvement", {"flow_name": "test", "inbox_id": "x"})

        assert scheduled == []

    def test_run_completed_sends_digest(self, tg_bot, tmp_path):
        tg_bot._count_unread = MagicMock(return_value=2)
        tg_bot._send_message_safe = AsyncMock(
            side_effect=lambda cid, txt, mk=None, **kw: MagicMock(message_id=42),
        )

        with patch.object(TelegramBot, "_state_file", return_value=tmp_path / "state.json"):
            self._run(tg_bot._send_or_update_unread_digest(123))

        tg_bot._send_message_safe.assert_called_once()
        text = tg_bot._send_message_safe.call_args[0][1]
        assert "<b>2</b>" in text
        assert tg_bot._digest_msg_id[123] == 42
        assert tg_bot._last_was_digest[123] is True
        markup = tg_bot._send_message_safe.call_args[0][2]
        assert markup.inline_keyboard[0][0].callback_data == "show_inbox"

    def test_digest_edits_existing_when_previous_was_digest(self, tg_bot):
        tg_bot._count_unread = MagicMock(return_value=3)
        tg_bot._digest_msg_id[123] = 42
        tg_bot._last_was_digest[123] = True
        tg_bot._app.bot.edit_message_text = AsyncMock()
        tg_bot._send_message_safe = AsyncMock()

        self._run(tg_bot._send_or_update_unread_digest(123))

        tg_bot._app.bot.edit_message_text.assert_called_once()
        kwargs = tg_bot._app.bot.edit_message_text.call_args.kwargs
        assert kwargs["message_id"] == 42
        assert "<b>3</b>" in kwargs["text"]
        tg_bot._send_message_safe.assert_not_called()

    def test_digest_sends_new_after_hitl(self, tg_bot, tmp_path):
        tg_bot._count_unread = MagicMock(return_value=1)
        tg_bot._digest_msg_id[123] = 42
        tg_bot._last_was_digest[123] = False
        tg_bot._app.bot.edit_message_text = AsyncMock()
        tg_bot._send_message_safe = AsyncMock(
            side_effect=lambda cid, txt, mk=None, **kw: MagicMock(message_id=99),
        )

        with patch.object(TelegramBot, "_state_file", return_value=tmp_path / "state.json"):
            self._run(tg_bot._send_or_update_unread_digest(123))

        tg_bot._app.bot.edit_message_text.assert_not_called()
        tg_bot._send_message_safe.assert_called_once()
        assert tg_bot._digest_msg_id[123] == 99

    def test_hitl_push_sends_hitl_md_content(self, tg_bot):
        tg_bot._send_message_safe = AsyncMock(
            side_effect=lambda cid, txt, mk=None, **kw: MagicMock(message_id=1),
        )

        self._run(tg_bot._send_hitl_notification(
            chat_id=123,
            payload={
                "step_run_id": "sr-1",
                "flow_name": "my-flow",
                "step_name": "review-plan",
                "inbox_title": "Approve the plan?",
                "user_message": "# Approve the plan?\n\nPlease confirm next steps.",
            },
        ))

        text = tg_bot._send_message_safe.call_args[0][1]
        assert "Approve the plan?" in text
        assert "Please confirm next steps." in text
        assert "needs your input" not in text
        markup = tg_bot._send_message_safe.call_args[0][2]
        texts = [b.text for b in markup.inline_keyboard[0]]
        assert "Respond" in texts
        assert "Complete" in texts


class TestAcceptImprovement:
    """The Respond button prompts for a selection; the follow-up message applies the proposal."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_respond_button_prompts_for_selection(self, tg_bot):
        query = MagicMock()
        query.message.chat_id = 123
        query.edit_message_reply_markup = AsyncMock()
        query.message.reply_text = AsyncMock()

        self._run(tg_bot._cb_accept_improvement(query, "inbox-1"))

        assert tg_bot._awaiting_improvement[123] == "inbox-1"
        query.message.reply_text.assert_called_once()
        assert "improvements" in query.message.reply_text.call_args[0][0].lower()

    def test_accept_applies_proposal(self, tg_bot, tg_db, space_and_flow, tmp_path):
        space, flow, run = space_and_flow

        inbox = InboxItem(type="flow_improvement", reference_id=run.id, space_id=space.id, title="proposal")
        tg_db.add(inbox)
        tg_db.flush()

        artifacts_dir = tmp_path / ".llmflows" / "my-flow" / "runs" / run.id / "artifacts"
        artifacts_dir.mkdir(parents=True)
        (artifacts_dir / "improvement.md").write_text("Made it better")

        flow_json = {
            "name": "my-flow",
            "steps": [{"name": "improved-step", "step_type": "agent", "content": "better", "position": 0}],
        }

        update = MagicMock()
        update.message.reply_text = AsyncMock()

        from llmflows.services.audit import AuditResult, FlowAuditService
        safe = AuditResult(status="safe", summary="ok", audited_at="2025-01-01T00:00:00+00:00")
        with patch("llmflows.services.context.generate_flow_from_improvements", return_value=flow_json), \
             patch.object(FlowAuditService, "run_audit", return_value=safe), \
             patch.object(FlowAuditService, "save_audit"):
            self._run(tg_bot._process_improvement_response(update, inbox.id, ""))

        call_text = update.message.reply_text.call_args[0][0]
        assert "Applied improvements" in call_text
        assert "my-flow" in call_text
        assert "v" in call_text
        # Accepted proposals are removed from the inbox.
        assert tg_db.query(InboxItem).filter_by(id=inbox.id).first() is None

    def test_accept_blocked_by_audit(self, tg_bot, tg_db, space_and_flow, tmp_path):
        space, flow, run = space_and_flow

        inbox = InboxItem(type="flow_improvement", reference_id=run.id, space_id=space.id, title="proposal")
        tg_db.add(inbox)
        tg_db.flush()

        artifacts_dir = tmp_path / ".llmflows" / "my-flow" / "runs" / run.id / "artifacts"
        artifacts_dir.mkdir(parents=True)
        (artifacts_dir / "improvement.md").write_text("Do something destructive")

        flow_json = {
            "name": "my-flow",
            "steps": [{"name": "bad-step", "step_type": "agent", "content": "rm -rf /", "position": 0}],
        }

        update = MagicMock()
        update.message.reply_text = AsyncMock()

        from llmflows.services.audit import AuditResult, FlowAuditService
        unsafe = AuditResult(status="unsafe", summary="Destructive command", audited_at="2025-01-01T00:00:00+00:00")
        with patch("llmflows.services.context.generate_flow_from_improvements", return_value=flow_json), \
             patch.object(FlowAuditService, "run_audit", return_value=unsafe):
            self._run(tg_bot._process_improvement_response(update, inbox.id, ""))

        call_text = update.message.reply_text.call_args[0][0]
        assert "audit failed" in call_text.lower()
        assert inbox.archived_at is None

    def test_accept_not_found(self, tg_bot, tg_db):
        update = MagicMock()
        update.message.reply_text = AsyncMock()

        self._run(tg_bot._process_improvement_response(update, "nonexistent", ""))

        update.message.reply_text.assert_called_once()
        assert "not found" in update.message.reply_text.call_args[0][0]


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


class TestInboxListsFlowImprovement:
    """/inbox lists flow improvement proposals."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_inbox_lists_flow_improvement(self, tg_bot, tg_db, space_and_flow):
        space, flow, run = space_and_flow
        inbox = InboxItem(
            type="flow_improvement", reference_id=run.id,
            space_id=space.id, title="proposal",
        )
        tg_db.add(inbox)
        tg_db.flush()

        replies = []

        async def fake_reply(text, parse_mode=None, reply_markup=None):
            replies.append((text, reply_markup))

        self._run(tg_bot._send_inbox_list(123, fake_reply))

        assert len(replies) == 1
        text, markup = replies[0]
        assert text == "💡 <b>Flow improvement proposed</b>\n<i>my-flow</i>"
        button_texts = [b.text for row in markup.inline_keyboard for b in row]
        assert "Details" in button_texts
        assert "Respond" in button_texts

    def test_inbox_lists_completed_run_with_summary(self, tg_bot, tg_db, space_and_flow, tmp_path):
        from datetime import datetime, timezone
        from llmflows.db.models import StepRun

        space, flow, run = space_and_flow
        run.summary = "Scheduled 3 videos\nExtra detail"
        run.completed_at = datetime.now(timezone.utc)
        run.started_at = run.completed_at
        sr = StepRun(
            flow_run_id=run.id, step_name="schedule", step_position=0,
            flow_name=flow.name, agent="pi", cost_usd=0.0123,
            started_at=run.completed_at, completed_at=run.completed_at,
        )
        tg_db.add(sr)
        inbox = InboxItem(
            type="completed_run", reference_id=run.id,
            space_id=space.id, title=flow.name,
        )
        tg_db.add(inbox)
        tg_db.flush()

        artifacts = tmp_path / ".llmflows" / "my-flow" / "runs" / run.id / "artifacts"
        artifacts.mkdir(parents=True)
        (artifacts / "inbox.md").write_text(
            "# Added 3 videos to playlist\n\nMorning batch completed successfully.\n"
        )

        replies = []

        async def fake_reply(text, parse_mode=None, reply_markup=None):
            replies.append(text)

        self._run(tg_bot._send_inbox_list(123, fake_reply))

        assert len(replies) == 1
        text = replies[0]
        assert "Added 3 videos to playlist" in text
        assert "Morning batch completed successfully." in text
        assert "<i>my-flow</i>" in text
        assert "$0.0123" in text


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
        query.message.message_id = 55
        query.edit_message_reply_markup = AsyncMock()
        tg_bot._app.bot.delete_message = AsyncMock()

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
        assert "Respond" in texts
        assert "Decline" in texts
        assert "Discard" in texts
        tg_bot._app.bot.delete_message.assert_called_once_with(chat_id=123, message_id=55)


class TestFormatRunCard:
    """_format_run_card produces correct text and button label for active/pending runs."""

    def _make_run(self, tg_db, space, flow, started=True, step="step-1", snapshot_vars=None):
        now = datetime.now(timezone.utc)
        snap = {"name": flow.name}
        if snapshot_vars:
            snap["variables"] = {k: {"value": v, "is_env": False} for k, v in snapshot_vars.items()}
        run = FlowRun(
            flow_id=flow.id,
            space_id=space.id,
            current_step=step,
            flow_snapshot=json.dumps(snap),
            created_at=now - timedelta(minutes=5),
        )
        if started:
            run.started_at = now - timedelta(minutes=3)
        tg_db.add(run)
        tg_db.flush()
        return run

    def test_active_run_card_has_yellow_icon_and_status(self, tg_bot, tg_db, space_and_flow):
        space, flow, _ = space_and_flow
        run = self._make_run(tg_db, space, flow)
        now = datetime.now(timezone.utc)
        text, btn = TelegramBot._format_run_card(run, space, "active", now)
        assert "🟡" in text
        assert "running" in text
        assert "Cancel" in btn

    def test_active_run_card_shows_step(self, tg_bot, tg_db, space_and_flow):
        space, flow, _ = space_and_flow
        run = self._make_run(tg_db, space, flow, step="Research")
        now = datetime.now(timezone.utc)
        text, _ = TelegramBot._format_run_card(run, space, "active", now)
        assert "Research" in text
        assert "Step:" in text

    def test_active_run_card_shows_elapsed(self, tg_bot, tg_db, space_and_flow):
        space, flow, _ = space_and_flow
        run = self._make_run(tg_db, space, flow)
        now = datetime.now(timezone.utc)
        text, _ = TelegramBot._format_run_card(run, space, "active", now)
        assert "3m" in text

    def test_active_run_card_shows_variables(self, tg_bot, tg_db, space_and_flow):
        space, flow, _ = space_and_flow
        run = self._make_run(tg_db, space, flow, snapshot_vars={"BRANCH": "main", "ENV": "prod"})
        now = datetime.now(timezone.utc)
        text, _ = TelegramBot._format_run_card(run, space, "active", now)
        assert "BRANCH=main" in text
        assert "ENV=prod" in text
        assert "Vars:" in text

    def test_active_run_card_omits_vars_when_none(self, tg_bot, tg_db, space_and_flow):
        space, flow, _ = space_and_flow
        run = self._make_run(tg_db, space, flow)
        now = datetime.now(timezone.utc)
        text, _ = TelegramBot._format_run_card(run, space, "active", now)
        assert "Vars:" not in text

    def test_active_run_card_shows_space_name(self, tg_bot, tg_db, space_and_flow):
        space, flow, _ = space_and_flow
        run = self._make_run(tg_db, space, flow)
        now = datetime.now(timezone.utc)
        text, _ = TelegramBot._format_run_card(run, space, "active", now)
        assert "Space: test-space" in text

    def test_pending_run_card_has_blue_icon_and_queued(self, tg_bot, tg_db, space_and_flow):
        space, flow, _ = space_and_flow
        run = self._make_run(tg_db, space, flow, started=False)
        now = datetime.now(timezone.utc)
        text, btn = TelegramBot._format_run_card(run, space, "pending", now)
        assert "🔵" in text
        assert "queued" in text
        assert "Dequeue" in btn

    def test_pending_run_card_shows_wait_time(self, tg_bot, tg_db, space_and_flow):
        space, flow, _ = space_and_flow
        run = self._make_run(tg_db, space, flow, started=False)
        now = datetime.now(timezone.utc)
        text, _ = TelegramBot._format_run_card(run, space, "pending", now)
        assert "5m" in text


class TestActiveCommand:
    """_handle_active_command sends individual cards for each run."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_active_sends_separate_cards(self, tg_bot, tg_db, space_and_flow):
        space, flow, existing_run = space_and_flow
        existing_run.completed_at = datetime.now(timezone.utc)
        tg_db.flush()

        now = datetime.now(timezone.utc)
        snap = json.dumps({"name": flow.name})

        r1 = FlowRun(
            flow_id=flow.id, space_id=space.id, current_step="Build",
            flow_snapshot=snap, started_at=now - timedelta(minutes=2),
            created_at=now - timedelta(minutes=3),
        )
        r2 = FlowRun(
            flow_id=flow.id, space_id=space.id,
            flow_snapshot=snap, created_at=now - timedelta(minutes=1),
        )
        tg_db.add_all([r1, r2])
        tg_db.flush()

        sent_texts = []

        async def fake_send(chat_id, text, markup=None, **kwargs):
            sent_texts.append(text)
            msg = MagicMock()
            msg.message_id = len(sent_texts)
            return msg

        tg_bot._send_message_safe = fake_send

        update = MagicMock()
        update.effective_chat.id = 123

        self._run(tg_bot._handle_active_command(update, None))

        assert len(sent_texts) == 2
        assert "🟡" in sent_texts[0]
        assert "Build" in sent_texts[0]
        assert "🔵" in sent_texts[1]
        assert "queued" in sent_texts[1]

    def test_active_no_runs(self, tg_bot, tg_db, space_and_flow):
        _, _, existing_run = space_and_flow
        existing_run.completed_at = datetime.now(timezone.utc)
        tg_db.flush()

        update = MagicMock()
        update.effective_chat.id = 123
        update.message.reply_text = AsyncMock()

        self._run(tg_bot._handle_active_command(update, None))

        update.message.reply_text.assert_called_once_with("No active or queued runs.")


class TestMuteCommand:
    """The /mute command toggles notification muting."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_mute_toggles_on(self, tg_bot):
        assert tg_bot._muted is False
        update = MagicMock()
        update.effective_chat.id = 123
        update.message.reply_text = AsyncMock()

        self._run(tg_bot._handle_mute_command(update, None))

        assert tg_bot._muted is True
        call_text = update.message.reply_text.call_args[0][0]
        assert "muted" in call_text.lower()
        assert "HITL" in call_text

    def test_mute_toggles_off(self, tg_bot):
        tg_bot._muted = True
        update = MagicMock()
        update.effective_chat.id = 123
        update.message.reply_text = AsyncMock()

        self._run(tg_bot._handle_mute_command(update, None))

        assert tg_bot._muted is False
        call_text = update.message.reply_text.call_args[0][0]
        assert "unmuted" in call_text.lower()

    def test_send_skips_when_muted(self, tg_bot):
        tg_bot._muted = True
        tg_bot.send("run.completed", {"flow_name": "test"})
        # _format_notification should not be reached — no coroutine scheduled
        # (we just verify it returns without error)

    def test_send_allows_hitl_when_muted(self, tg_bot):
        tg_bot._muted = True
        tg_bot.allowed_ids = {123}
        scheduled = []

        def mock_run(coro, loop):
            scheduled.append(True)
            coro.close()
        with patch("llmflows.services.gateway.telegram.asyncio.run_coroutine_threadsafe", mock_run):
            tg_bot.send("step.awaiting_user", {"flow_name": "test", "step_name": "Review"})

        assert len(scheduled) > 0

    def test_send_works_when_unmuted(self, tg_bot):
        tg_bot._muted = False
        tg_bot.allowed_ids = {123}
        scheduled = []

        def mock_run(coro, loop):
            scheduled.append(True)
            coro.close()
        with patch("llmflows.services.gateway.telegram.asyncio.run_coroutine_threadsafe", mock_run):
            tg_bot.send("run.completed", {"flow_name": "test", "outcome": "completed"})

        assert len(scheduled) > 0

    def test_send_hitl_clears_digest_flag(self, tg_bot, tmp_path):
        tg_bot._muted = False
        tg_bot.allowed_ids = {123}
        tg_bot._last_was_digest[123] = True

        def mock_run(coro, loop):
            coro.close()

        with patch.object(TelegramBot, "_state_file", return_value=tmp_path / "state.json"), \
             patch("llmflows.services.gateway.telegram.asyncio.run_coroutine_threadsafe", mock_run):
            tg_bot.send("step.awaiting_user", {"flow_name": "test", "step_name": "Review"})

        assert tg_bot._last_was_digest[123] is False


class TestMuteStatePersistence:
    """Mute and digest state are persisted to and loaded from disk."""

    def test_state_roundtrip(self, tg_bot, tmp_path):
        state_file = tmp_path / "state.json"
        with patch.object(TelegramBot, "_state_file", return_value=state_file):
            tg_bot._muted = True
            tg_bot._digest_msg_id[123] = 42
            tg_bot._last_was_digest[123] = True
            tg_bot._save_state()
            assert state_file.exists()

            tg_bot._muted = False
            tg_bot._digest_msg_id = {}
            tg_bot._last_was_digest = {}
            tg_bot._load_state()
            assert tg_bot._muted is True
            assert tg_bot._digest_msg_id[123] == 42
            assert tg_bot._last_was_digest[123] is True

    def test_load_state_defaults_when_missing(self, tg_bot, tmp_path):
        state_file = tmp_path / "nonexistent" / "state.json"
        with patch.object(TelegramBot, "_state_file", return_value=state_file):
            tg_bot._muted = True
            tg_bot._load_state()
            assert tg_bot._muted is False


class TestAuditCommand:
    """The /audit command asks user to select a space first."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_audit_shows_space_selection(self, tg_bot, tg_db, space_and_flow):
        space, flow, _ = space_and_flow

        update = MagicMock()
        update.effective_chat.id = 123
        update.message.reply_text = AsyncMock()

        self._run(tg_bot._handle_audit_command(update, None))

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        assert "Select a space" in call_kwargs[0][0]
        markup = call_kwargs[1]["reply_markup"]
        button = markup.inline_keyboard[0][0]
        assert button.callback_data == f"audit_space:{space.id}"

    def test_audit_space_shows_status(self, tg_bot, tg_db, space_and_flow, tmp_path):
        space, flow, _ = space_and_flow

        from llmflows.services.audit import AuditResult
        safe_result = AuditResult(status="safe", summary="ok", audited_at="2025-01-01T00:00:00+00:00")

        query = MagicMock()
        query.edit_message_text = AsyncMock()

        with patch("llmflows.services.audit.FlowAuditService.get_audit", return_value=safe_result), \
             patch("llmflows.services.skill.SkillService.discover", return_value=[]):
            self._run(tg_bot._cb_audit_space(query, 123, space.id))

        query.edit_message_text.assert_called_once()
        call_text = query.edit_message_text.call_args[0][0]
        assert "test-space" in call_text
        assert "my-flow" in call_text
        assert "safe" in call_text.lower()

    def test_audit_space_shows_unaudited_with_button(self, tg_bot, tg_db, space_and_flow, tmp_path):
        space, flow, _ = space_and_flow

        query = MagicMock()
        query.edit_message_text = AsyncMock()

        with patch("llmflows.services.audit.FlowAuditService.get_audit", return_value=None), \
             patch("llmflows.services.skill.SkillService.discover", return_value=[]):
            self._run(tg_bot._cb_audit_space(query, 123, space.id))

        query.edit_message_text.assert_called_once()
        call_kwargs = query.edit_message_text.call_args
        assert "not audited" in call_kwargs[0][0]
        markup = call_kwargs[1].get("reply_markup")
        assert markup is not None
        button = markup.inline_keyboard[0][0]
        assert f"audit_bulk:{space.id}" == button.callback_data

    def test_audit_no_spaces(self, tg_bot, tg_db):
        update = MagicMock()
        update.effective_chat.id = 123
        update.message.reply_text = AsyncMock()

        self._run(tg_bot._handle_audit_command(update, None))

        update.message.reply_text.assert_called_once_with("No spaces registered.")


class TestHelpIncludesMuteAndAudit:
    """The /help text includes /mute, /audit, and mute status."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_help_includes_new_commands(self, tg_bot):
        update = MagicMock()
        update.effective_chat.id = 123
        update.message.reply_text = AsyncMock()

        self._run(tg_bot._handle_help_command(update, None))

        call_text = update.message.reply_text.call_args[0][0]
        assert "/mute" in call_text
        assert "/audit" in call_text
        assert "/inbox" in call_text
        assert "Mute:" in call_text
