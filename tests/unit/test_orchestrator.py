"""Unit tests for orchestrator logic, authorization checks, and command execution."""

import pytest
from src.application.orchestrator import AgentOrchestrator
from src.domain.agent import ToolCall
from src.domain.user import AuthPolicy
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
        self.chat_actions = []

    async def send_message(self, chat_id, text, reply_markup=None, reply_to_message_id=None):
        self.sent_messages.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return [1]

    async def send_chat_action(self, chat_id, action="typing"):
        self.chat_actions.append({"chat_id": chat_id, "action": action})
        return True


@pytest.mark.asyncio
async def test_unauthorized_user_is_blocked(temp_db, mock_config):
    mock_tg = MockTelegramAdapter()
    mock_ai = MockAIProvider(fixed_response="Hello")
    tools = ToolRegistry()
    auth_policy = AuthPolicy(allowlist_enabled=True, allowed_user_ids={111})
    auth_mgr = TelegramAuthManager(policy=auth_policy)
    limiter = UserRateLimiter()

    orchestrator = AgentOrchestrator(
        config=mock_config,
        telegram_adapter=mock_tg,
        ai_provider=mock_ai,
        db=temp_db,
        tool_registry=tools,
        auth_manager=auth_mgr,
        rate_limiter=limiter,
    )

    unauthorized_msg = {
        "text": "Hello bot",
        "chat": {"id": 999, "type": "private"},
        "from": {"id": 999, "username": "intruder"}
    }
    await orchestrator.handle_message(unauthorized_msg)

    assert len(mock_tg.sent_messages) == 1
    assert "not authorized" in mock_tg.sent_messages[0]["text"]


@pytest.mark.asyncio
async def test_authorized_user_start_command(temp_db, mock_config):
    mock_tg = MockTelegramAdapter()
    mock_ai = MockAIProvider()
    tools = ToolRegistry()
    auth_policy = AuthPolicy(allowlist_enabled=True, allowed_user_ids={111})
    auth_mgr = TelegramAuthManager(policy=auth_policy)
    limiter = UserRateLimiter()

    orchestrator = AgentOrchestrator(
        config=mock_config,
        telegram_adapter=mock_tg,
        ai_provider=mock_ai,
        db=temp_db,
        tool_registry=tools,
        auth_manager=auth_mgr,
        rate_limiter=limiter,
    )

    start_msg = {
        "text": "/start",
        "chat": {"id": 111, "type": "private"},
        "from": {"id": 111, "username": "valid_user"}
    }
    await orchestrator.handle_message(start_msg)

    assert len(mock_tg.sent_messages) == 1
    assert "Online" in mock_tg.sent_messages[0]["text"]


@pytest.mark.asyncio
async def test_destructive_tool_triggers_confirmation(temp_db, mock_config):
    mock_tg = MockTelegramAdapter()
    # Mock AI wanting to run a shell command
    tool_call = ToolCall(id="call_1", name="shell_execute", arguments={"command": "rm -rf data"})
    mock_ai = MockAIProvider(fixed_response="", tool_calls=[tool_call])

    tools = ToolRegistry(require_confirmation_for_destructive=True)
    tools.register(ShellTool(enabled=True))

    auth_policy = AuthPolicy(allowlist_enabled=False)
    auth_mgr = TelegramAuthManager(policy=auth_policy)
    limiter = UserRateLimiter()

    orchestrator = AgentOrchestrator(
        config=mock_config,
        telegram_adapter=mock_tg,
        ai_provider=mock_ai,
        db=temp_db,
        tool_registry=tools,
        auth_manager=auth_mgr,
        rate_limiter=limiter,
    )

    user_msg = {
        "text": "Please delete the data directory",
        "chat": {"id": 111, "type": "private"},
        "from": {"id": 111, "username": "valid_user"}
    }
    await orchestrator.handle_message(user_msg)

    assert len(mock_tg.sent_messages) == 1
    sent = mock_tg.sent_messages[0]
    assert "high-risk operation" in sent["text"]
    assert sent["reply_markup"] is not None
    assert "inline_keyboard" in sent["reply_markup"]


@pytest.mark.asyncio
async def test_switch_model_command_and_callback(temp_db, mock_config):
    mock_tg = MockTelegramAdapter()
    mock_ai = MockAIProvider(fixed_response="Model test")
    tools = ToolRegistry()
    auth_policy = AuthPolicy(allowlist_enabled=False)
    auth_mgr = TelegramAuthManager(policy=auth_policy)
    limiter = UserRateLimiter()

    orchestrator = AgentOrchestrator(
        config=mock_config,
        telegram_adapter=mock_tg,
        ai_provider=mock_ai,
        db=temp_db,
        tool_registry=tools,
        auth_manager=auth_mgr,
        rate_limiter=limiter,
    )

    # Test /model without args -> shows keyboard
    await orchestrator.handle_message({
        "text": "/model",
        "chat": {"id": 111, "type": "private"},
        "from": {"id": 111, "username": "user1"}
    })
    assert len(mock_tg.sent_messages) == 1
    assert "inline_keyboard" in mock_tg.sent_messages[0]["reply_markup"]

    # Test /model with args -> switches model immediately
    await orchestrator.handle_message({
        "text": "/model ag/gemini-3.7-flash-high",
        "chat": {"id": 111, "type": "private"},
        "from": {"id": 111, "username": "user1"}
    })
    assert "switched to: ag/gemini-3.7-flash-high" in mock_tg.sent_messages[1]["text"]
    assert orchestrator._user_active_model[111] == "ag/gemini-3.7-flash-high"
