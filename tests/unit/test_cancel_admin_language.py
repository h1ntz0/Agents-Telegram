"""Confirmation gating, /cancel ownership, and /admin access control."""

import pytest

from src.application.orchestrator import AgentOrchestrator
from src.domain.agent import ToolCall
from src.domain.user import AuthPolicy
from src.infrastructure.i18n import t
from src.infrastructure.security.rate_limiter import UserRateLimiter
from src.infrastructure.telegram.adapter import TelegramAdapter
from src.infrastructure.telegram.auth import TelegramAuthManager
from src.infrastructure.tools.registry import ToolRegistry
from src.infrastructure.tools.shell_tool import ShellTool
from tests.conftest import MockAIProvider


class MockTelegramAdapter(TelegramAdapter):
    """Capture outbound telegram calls without network I/O."""

    def __init__(self):
        super().__init__(bot_token="1234567890:MockToken")
        self.sent_messages = []
        self.answered_callbacks = []
        self.edited_messages = []

    async def send_message(self, chat_id, text, reply_markup=None, reply_to_message_id=None):
        self.sent_messages.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return [1]

    async def send_chat_action(self, chat_id, action="typing"):
        return True

    async def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        self.answered_callbacks.append({"id": callback_query_id, "text": text})
        return True

    async def edit_message_text(self, chat_id, message_id, text, reply_markup=None, parse_mode=None):
        self.edited_messages.append({"chat_id": chat_id, "message_id": message_id, "text": text})
        return True


def _message(text, user_id=111):
    return {
        "text": text,
        "chat": {"id": user_id, "type": "private"},
        "from": {"id": user_id, "username": f"user{user_id}"},
    }


def _build(temp_db, mock_config, mock_ai, require_confirmation=True):
    mock_tg = MockTelegramAdapter()
    tools = ToolRegistry(require_confirmation_for_destructive=require_confirmation)
    tools.register(ShellTool(enabled=True))
    orchestrator = AgentOrchestrator(
        config=mock_config,
        telegram_adapter=mock_tg,
        ai_provider=mock_ai,
        db=temp_db,
        tool_registry=tools,
        auth_manager=TelegramAuthManager(policy=AuthPolicy(
            allowlist_enabled=False,
            admin_user_ids=mock_config.telegram.admin_users,
        )),
        rate_limiter=UserRateLimiter(),
    )
    return orchestrator, mock_tg


def _destructive_request():
    tool_call = ToolCall(id="call_1", name="shell_execute", arguments={"command": "rm -rf data"})
    return MockAIProvider(fixed_response="", tool_calls=[tool_call])


@pytest.mark.asyncio
async def test_cancel_clears_the_users_pending_action(temp_db, mock_config):
    """/cancel must discard the confirmation the same user was just shown."""
    orchestrator, mock_tg = _build(temp_db, mock_config, _destructive_request())

    await orchestrator.handle_message(_message("delete the data directory"))
    assert len(orchestrator._pending_actions) == 1

    await orchestrator.handle_message(_message("/cancel"))

    assert orchestrator._pending_actions == {}
    assert mock_tg.sent_messages[-1]["text"] == t("bot.cancel.done")


@pytest.mark.asyncio
async def test_cancel_reports_when_nothing_is_pending(temp_db, mock_config):
    orchestrator, mock_tg = _build(temp_db, mock_config, MockAIProvider())

    await orchestrator.handle_message(_message("/cancel"))

    assert mock_tg.sent_messages[-1]["text"] == t("bot.cancel.none")


@pytest.mark.asyncio
async def test_cancel_does_not_touch_another_users_pending_action(temp_db, mock_config):
    """A second user cannot clear a confirmation they do not own."""
    orchestrator, _ = _build(temp_db, mock_config, _destructive_request())

    await orchestrator.handle_message(_message("delete the data directory", user_id=111))
    assert len(orchestrator._pending_actions) == 1

    await orchestrator.handle_message(_message("/cancel", user_id=222))

    assert len(orchestrator._pending_actions) == 1


@pytest.mark.asyncio
async def test_confirmation_is_skipped_when_the_setting_is_off(temp_db, mock_config):
    """require_confirmation_for_destructive=False runs the tool instead of asking."""
    mock_ai = _destructive_request()
    orchestrator, mock_tg = _build(temp_db, mock_config, mock_ai, require_confirmation=False)

    await orchestrator.handle_message(_message("delete the data directory"))

    assert orchestrator._pending_actions == {}
    assert all("high-risk operation" not in m["text"] for m in mock_tg.sent_messages)
    # The ReAct loop consumed the tool call and asked the model again.
    assert len(mock_ai.recorded_requests) >= 2


@pytest.mark.asyncio
async def test_admin_command_is_closed_when_no_admins_are_configured(temp_db, mock_config):
    mock_config.telegram.admin_users = []
    orchestrator, mock_tg = _build(temp_db, mock_config, MockAIProvider())

    await orchestrator.handle_message(_message("/admin"))

    assert mock_tg.sent_messages[-1]["text"] == t("bot.admin.unconfigured")


@pytest.mark.asyncio
async def test_admin_command_denies_non_admins(temp_db, mock_config):
    mock_config.telegram.admin_users = [111]
    orchestrator, mock_tg = _build(temp_db, mock_config, MockAIProvider())

    await orchestrator.handle_message(_message("/admin", user_id=222))

    assert mock_tg.sent_messages[-1]["text"] == t("bot.admin.denied")


@pytest.mark.asyncio
async def test_admin_command_reports_diagnostics_to_admins(temp_db, mock_config):
    mock_config.telegram.admin_users = [111]
    orchestrator, mock_tg = _build(temp_db, mock_config, MockAIProvider())

    await orchestrator.handle_message(_message("/admin", user_id=111))

    report = mock_tg.sent_messages[-1]["text"]
    assert report.startswith(t("bot.admin.stats").split("\n")[0])
    assert mock_config.storage.database_path in report


@pytest.mark.asyncio
async def test_language_switch_is_persisted_per_user(temp_db, mock_config):
    orchestrator, mock_tg = _build(temp_db, mock_config, MockAIProvider())

    await orchestrator.handle_message(_message("/lang id"))

    assert await orchestrator._get_user_language(111) == "id"
    # A different user keeps the deployment default.
    assert await orchestrator._get_user_language(222) == "en"

    orchestrator._user_language.clear()
    assert await orchestrator._get_user_language(111) == "id"


@pytest.mark.asyncio
async def test_language_command_rejects_unknown_codes(temp_db, mock_config):
    orchestrator, mock_tg = _build(temp_db, mock_config, MockAIProvider())

    await orchestrator.handle_message(_message("/lang klingon"))

    assert mock_tg.sent_messages[-1]["text"] == t("bot.lang.unknown", value="klingon", options="en, id")
    assert await orchestrator._get_user_language(111) == "en"
