"""Unit tests for OpenCode Mirror Mode wiring in Orchestrator and TelegramAdapter."""

import asyncio
from unittest.mock import AsyncMock, PropertyMock, patch
import pytest
from src.application.orchestrator import AgentOrchestrator
from src.domain.user import AuthPolicy
from src.infrastructure.i18n import t
from src.infrastructure.opencode.mirror import OpenCodeMirror
from src.infrastructure.scheduler.job_scheduler import JobScheduler
from src.infrastructure.security.rate_limiter import UserRateLimiter
from src.infrastructure.telegram.adapter import TelegramAdapter
from src.infrastructure.telegram.auth import TelegramAuthManager
from src.infrastructure.tools.registry import ToolRegistry
from tests.conftest import MockAIProvider


class FakeOpenCodeBridge:
    """Duck-typed fake OpenCodeBridge for testing."""

    def __init__(self):
        self.sessions = [
            {"id": "ses_123", "title": "Existing Session", "model": {"id": "m1"}}
        ]
        self.interrupt_calls = []
        self.set_model_calls = []
        self.set_agent_calls = []
        self.reply_permission_calls = []
        self.prompt_async_calls = []
        self.agents_list = [
            {"id": "plan", "name": "Planner Agent", "description": "Plans complex workflows"}
        ]
        self.models_list = [
            {"id": "gpt-4o", "name": "GPT-4o"}
        ]
        self.commands_list = [
            {"id": "test-cmd", "title": "Test Command", "description": "Runs test"}
        ]
        self.skills_list = [
            {"id": "skill-1", "name": "Skill 1"}
        ]

    async def auto_discover_server(self):
        return "http://127.0.0.1:4096"

    async def list_sessions(self):
        return self.sessions

    async def get_session(self, session_id):
        for s in self.sessions:
            if s["id"] == session_id:
                return s
        return None

    async def create_session(self, title=None):
        new_s = {"id": f"ses_{len(self.sessions) + 1}", "title": title or "new-session"}
        self.sessions.append(new_s)
        return new_s

    async def interrupt(self, session_id):
        self.interrupt_calls.append(session_id)
        return True

    async def set_model(self, session_id, model_id, provider_id):
        self.set_model_calls.append((session_id, model_id, provider_id))
        return True

    async def set_agent(self, session_id, agent):
        self.set_agent_calls.append((session_id, agent))
        return True

    async def list_agents(self):
        return self.agents_list

    async def list_models(self):
        return self.models_list

    async def list_commands(self):
        return self.commands_list

    async def list_skills(self):
        return self.skills_list

    async def reply_permission(self, session_id, request_id, reply, message=None):
        self.reply_permission_calls.append((session_id, request_id, reply, message))
        return True

    async def prompt_async(self, session_id, text):
        self.prompt_async_calls.append((session_id, text))
        return {}

    async def stream_events(self, session_id):
        if False:
            yield {}


class FakeTelegramAdapter(TelegramAdapter):
    """Fake TelegramAdapter capturing sent, edited, and answered callback queries."""

    def __init__(self):
        super().__init__(bot_token="1234567890:MockToken")
        self.sent_messages = []
        self.edited_messages = []
        self.answered_callbacks = []
        self.chat_actions = []

    async def send_message(self, chat_id, text, reply_markup=None, reply_to_message_id=None, parse_mode=None):
        msg_id = len(self.sent_messages) + 1
        self.sent_messages.append({
            "message_id": msg_id,
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        })
        return [msg_id]

    async def edit_message_text(self, chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
        self.edited_messages.append({
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "reply_markup": reply_markup,
        })
        return True

    async def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        self.answered_callbacks.append({
            "callback_query_id": callback_query_id,
            "text": text,
            "show_alert": show_alert,
        })
        return True

    async def send_chat_action(self, chat_id, action="typing"):
        self.chat_actions.append({"chat_id": chat_id, "action": action})
        return True


@pytest.fixture
def mirror_setup(temp_db, mock_config):
    mock_tg = FakeTelegramAdapter()
    mock_ai = MockAIProvider(fixed_response="AI Response")
    tools = ToolRegistry()
    auth_policy = AuthPolicy(allowlist_enabled=False)
    auth_mgr = TelegramAuthManager(policy=auth_policy)
    limiter = UserRateLimiter()
    scheduler = JobScheduler(db=temp_db)
    fake_bridge = FakeOpenCodeBridge()

    orchestrator = AgentOrchestrator(
        config=mock_config,
        telegram_adapter=mock_tg,
        ai_provider=mock_ai,
        db=temp_db,
        tool_registry=tools,
        auth_manager=auth_mgr,
        rate_limiter=limiter,
        scheduler=scheduler,
    )
    orchestrator.opencode_bridge = fake_bridge
    return orchestrator, mock_tg, mock_ai, fake_bridge


@pytest.mark.asyncio
async def test_get_oc_mirror_none_when_no_session(mirror_setup):
    """_get_oc_mirror returns None when no OpenCode session is attached."""
    orchestrator, _, _, _ = mirror_setup
    assert orchestrator._get_oc_mirror(user_id=111, chat_id=222) is None


@pytest.mark.asyncio
async def test_get_oc_mirror_creates_and_caches_mirror(mirror_setup):
    """_get_oc_mirror creates OpenCodeMirror when session is attached and returns cached instance."""
    orchestrator, mock_tg, _, fake_bridge = mirror_setup
    orchestrator._user_active_oc_session[111] = "ses_123"

    mirror1 = orchestrator._get_oc_mirror(user_id=111, chat_id=222)
    assert isinstance(mirror1, OpenCodeMirror)
    assert mirror1.session_id == "ses_123"
    assert mirror1.chat_id == 222

    # Second call returns same cached instance
    mirror2 = orchestrator._get_oc_mirror(user_id=111, chat_id=222)
    assert mirror1 is mirror2


@pytest.mark.asyncio
async def test_attached_plain_message_routes_to_mirror_prompt(mirror_setup):
    """Attached plain message routes to mirror.run_prompt and skips ReAct AI loop."""
    orchestrator, mock_tg, mock_ai, _ = mirror_setup
    orchestrator._user_active_oc_session[111] = "ses_123"

    mirror = orchestrator._get_oc_mirror(user_id=111, chat_id=222)
    mirror.run_prompt = AsyncMock()

    msg = {
        "chat": {"id": 222, "type": "private"},
        "from": {"id": 111, "username": "user1"},
        "text": "Refactor auth module",
    }
    await orchestrator.handle_message(msg)
    await asyncio.sleep(0.01)

    mirror.run_prompt.assert_awaited_once_with("Refactor auth module")
    # ReAct AI provider must NOT have been called
    assert len(mock_ai.recorded_requests) == 0


@pytest.mark.asyncio
async def test_attached_plain_message_warns_when_mirror_running(mirror_setup):
    """Attached message informs user if turn is already actively running."""
    orchestrator, mock_tg, _, _ = mirror_setup
    orchestrator._user_active_oc_session[111] = "ses_123"

    mirror = orchestrator._get_oc_mirror(user_id=111, chat_id=222)
    mirror.run_prompt = AsyncMock()

    with patch.object(OpenCodeMirror, "is_running", new_callable=PropertyMock) as mock_running:
        mock_running.return_value = True
        msg = {
            "chat": {"id": 222, "type": "private"},
            "from": {"id": 111, "username": "user1"},
            "text": "Another prompt",
        }
        await orchestrator.handle_message(msg)
        await asyncio.sleep(0.01)

        mirror.run_prompt.assert_not_called()
        assert len(mock_tg.sent_messages) == 1


@pytest.mark.asyncio
async def test_oc_stop_subcommand(mirror_setup):
    """/oc stop calls mirror.stop() and notifies user."""
    orchestrator, mock_tg, _, _ = mirror_setup
    orchestrator._user_active_oc_session[111] = "ses_123"

    mirror = orchestrator._get_oc_mirror(user_id=111, chat_id=222)
    mirror.stop = AsyncMock()

    msg = {
        "chat": {"id": 222, "type": "private"},
        "from": {"id": 111, "username": "user1"},
        "text": "/oc stop",
    }
    await orchestrator.handle_message(msg)

    mirror.stop.assert_awaited_once()
    assert len(mock_tg.sent_messages) == 1


@pytest.mark.asyncio
async def test_oc_model_subcommand(mirror_setup):
    """/oc model X Y calls bridge.set_model(sid, 'X', 'Y'), defaulting providerID to 9router."""
    orchestrator, mock_tg, _, fake_bridge = mirror_setup
    orchestrator._user_active_oc_session[111] = "ses_123"

    # Explicit provider
    msg1 = {
        "chat": {"id": 222, "type": "private"},
        "from": {"id": 111, "username": "user1"},
        "text": "/oc model claude-3-7-sonnet anthropic",
    }
    await orchestrator.handle_message(msg1)
    assert ("ses_123", "claude-3-7-sonnet", "anthropic") in fake_bridge.set_model_calls

    # Default provider (9router)
    msg2 = {
        "chat": {"id": 222, "type": "private"},
        "from": {"id": 111, "username": "user1"},
        "text": "/oc model ds/deepseek-chat",
    }
    await orchestrator.handle_message(msg2)
    assert ("ses_123", "ds/deepseek-chat", "9router") in fake_bridge.set_model_calls


@pytest.mark.asyncio
async def test_oc_agent_subcommand(mirror_setup):
    """/oc agent plan calls bridge.set_agent(sid, 'plan')."""
    orchestrator, mock_tg, _, fake_bridge = mirror_setup
    orchestrator._user_active_oc_session[111] = "ses_123"

    msg = {
        "chat": {"id": 222, "type": "private"},
        "from": {"id": 111, "username": "user1"},
        "text": "/oc agent plan",
    }
    await orchestrator.handle_message(msg)
    assert ("ses_123", "plan") in fake_bridge.set_agent_calls


@pytest.mark.asyncio
async def test_oc_list_subcommands(mirror_setup):
    """/oc agents, models, commands, skills fetch and format items from bridge."""
    orchestrator, mock_tg, _, _ = mirror_setup

    for sub in ("agents", "models", "commands", "skills"):
        mock_tg.sent_messages.clear()
        msg = {
            "chat": {"id": 222, "type": "private"},
            "from": {"id": 111, "username": "user1"},
            "text": f"/oc {sub}",
        }
        await orchestrator.handle_message(msg)
        assert len(mock_tg.sent_messages) == 1
        assert "OpenCode" in mock_tg.sent_messages[0]["text"]


@pytest.mark.asyncio
async def test_oc_diff_subcommand(mirror_setup):
    """/oc diff calls diff method on bridge if present, or responds unavailable."""
    orchestrator, mock_tg, _, fake_bridge = mirror_setup
    orchestrator._user_active_oc_session[111] = "ses_123"

    # When no diff method
    msg = {
        "chat": {"id": 222, "type": "private"},
        "from": {"id": 111, "username": "user1"},
        "text": "/oc diff",
    }
    await orchestrator.handle_message(msg)
    assert t("oc.diff_unsupported") in mock_tg.sent_messages[0]["text"]

    # When diff method is dynamically added
    fake_bridge.diff = AsyncMock(return_value="+ diff line 1\n- diff line 2")
    mock_tg.sent_messages.clear()
    await orchestrator.handle_message(msg)
    assert "+ diff line 1" in mock_tg.sent_messages[0]["text"]


@pytest.mark.asyncio
async def test_oc_attach_and_detach_manages_mirror(mirror_setup):
    """/oc attach creates mirror and /oc detach stops and removes it."""
    orchestrator, mock_tg, _, fake_bridge = mirror_setup

    # 1. Attach
    msg_attach = {
        "chat": {"id": 222, "type": "private"},
        "from": {"id": 111, "username": "user1"},
        "text": "/oc attach ses_123",
    }
    await orchestrator.handle_message(msg_attach)
    assert orchestrator._user_active_oc_session.get(111) == "ses_123"
    assert 111 in orchestrator._oc_mirrors
    mirror = orchestrator._oc_mirrors[111]
    mirror.stop = AsyncMock()

    # 2. Detach
    msg_detach = {
        "chat": {"id": 222, "type": "private"},
        "from": {"id": 111, "username": "user1"},
        "text": "/oc detach",
    }
    await orchestrator.handle_message(msg_detach)
    mirror.stop.assert_awaited_once()
    assert 111 not in orchestrator._user_active_oc_session
    assert 111 not in orchestrator._oc_mirrors


@pytest.mark.asyncio
async def test_callback_ocperm_once(mirror_setup):
    """Callback ocperm:<sid>:<req>:once calls bridge.reply_permission and updates message."""
    orchestrator, mock_tg, _, fake_bridge = mirror_setup

    cb = {
        "id": "query_p1",
        "data": "ocperm:ses_123:req_perm_1:once",
        "from": {"id": 111, "username": "user1"},
        "message": {"message_id": 55, "chat": {"id": 222}},
    }
    await orchestrator.handle_callback_query(cb)

    assert ("ses_123", "req_perm_1", "once", None) in fake_bridge.reply_permission_calls
    assert len(mock_tg.answered_callbacks) == 1
    assert any(t("oc.permission_once") in m["text"] for m in mock_tg.edited_messages)


@pytest.mark.asyncio
async def test_callback_ocstop(mirror_setup):
    """Callback ocstop:<sid> calls mirror.stop() and updates message."""
    orchestrator, mock_tg, _, _ = mirror_setup
    orchestrator._user_active_oc_session[111] = "ses_123"

    mirror = orchestrator._get_oc_mirror(user_id=111, chat_id=222)
    mirror.stop = AsyncMock()

    cb = {
        "id": "query_s1",
        "data": "ocstop:ses_123",
        "from": {"id": 111, "username": "user1"},
        "message": {"message_id": 66, "chat": {"id": 222}},
    }
    await orchestrator.handle_callback_query(cb)

    mirror.stop.assert_awaited_once()
    assert len(mock_tg.answered_callbacks) == 1
    assert any(t("oc.stopped") in m["text"] for m in mock_tg.edited_messages)
