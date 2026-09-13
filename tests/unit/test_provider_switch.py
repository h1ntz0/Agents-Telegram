"""S1/S2/S3: runtime ``/provider`` switching so providers besides 9router are usable.

Proves the user-visible contract: a Telegram user can switch the ACTIVE provider at
runtime (persisted), and subsequent prompts are routed to that provider's real
endpoint — without editing .env or restarting the bot.
"""

import httpx
import pytest
from unittest.mock import AsyncMock, patch

from src.application.config_manager import ProviderCredential
from src.application.orchestrator import AgentOrchestrator
from src.domain.user import AuthPolicy
from src.infrastructure.scheduler.job_scheduler import JobScheduler
from src.infrastructure.security.rate_limiter import UserRateLimiter
from src.infrastructure.telegram.adapter import TelegramAdapter
from src.infrastructure.telegram.auth import TelegramAuthManager
from src.infrastructure.tools.registry import ToolRegistry
from tests.conftest import MockAIProvider

USER_ID = 7
CHAT_ID = 7


class _CapturingTelegram(TelegramAdapter):
    """Captures outbound messages instead of hitting the Telegram API."""

    def __init__(self):
        super().__init__(bot_token="1234567890:MockToken")
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None, reply_to_message_id=None, parse_mode=None):
        self.sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return [len(self.sent)]

    async def send_chat_action(self, chat_id, action="typing"):
        return True

    async def edit_message_text(self, chat_id, message_id, text, reply_markup=None, parse_mode=None):
        self.sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return True


def _msg(text: str, user_id: int = USER_ID, chat_id: int = CHAT_ID):
    return {
        "chat": {"id": chat_id, "type": "private"},
        "from": {"id": user_id, "username": "tester"},
        "text": text,
    }


@pytest.fixture
def switch_setup(temp_db, mock_config):
    """Orchestrator with per-provider credentials for anthropic + google."""
    mock_config.providers = {
        "anthropic": ProviderCredential(api_key="sk-ant-test", base_url=""),
        "google": ProviderCredential(api_key="AIza-test", base_url=""),
    }
    tg = _CapturingTelegram()
    orch = AgentOrchestrator(
        config=mock_config,
        telegram_adapter=tg,
        ai_provider=MockAIProvider(),
        db=temp_db,
        tool_registry=ToolRegistry(),
        auth_manager=TelegramAuthManager(policy=AuthPolicy(allowlist_enabled=False)),
        rate_limiter=UserRateLimiter(),
        scheduler=JobScheduler(db=temp_db),
    )
    return orch, tg


# --------------------------------------------------------------------------- #
# S1 — happy path: switch then route to the new provider
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_provider_switch_routes_next_prompt_to_new_provider(switch_setup):
    orch, tg = switch_setup

    await orch.handle_message(_msg("/provider anthropic"))
    assert "anthropic" in tg.sent[-1]["text"].lower()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(
            200, json={"content": [{"type": "text", "text": "hello from anthropic"}]}
        )
        await orch.handle_message(_msg("ping"))

    assert mock_post.call_args is not None, "prompt was not routed to the anthropic provider"
    assert mock_post.call_args[0][0] == "https://api.anthropic.com/v1/messages"
    assert mock_post.call_args[1]["headers"]["x-api-key"] == "sk-ant-test"


@pytest.mark.asyncio
async def test_provider_switch_persists_for_the_user(switch_setup):
    orch, tg = switch_setup
    await orch.handle_message(_msg("/provider google"))
    assert await orch._get_user_provider(USER_ID) == "google"

    # Simulate a fresh process: drop the in-memory cache, keep the same DB.
    orch._user_active_provider.clear()
    assert await orch._get_user_provider(USER_ID) == "google"


@pytest.mark.asyncio
async def test_status_reflects_active_provider_after_switch(switch_setup):
    orch, tg = switch_setup
    await orch.handle_message(_msg("/provider google"))
    await orch.handle_message(_msg("/status"))
    assert "GOOGLE" in tg.sent[-1]["text"]


# --------------------------------------------------------------------------- #
# S2 — edge cases
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_provider_command_without_args_lists_providers(switch_setup):
    orch, tg = switch_setup
    await orch.handle_message(_msg("/provider"))
    text = tg.sent[-1]["text"].lower()
    for name in ("9router", "openai", "anthropic", "google", "deepseek"):
        assert name in text


@pytest.mark.asyncio
async def test_provider_command_rejects_unknown_provider(switch_setup):
    orch, tg = switch_setup
    await orch.handle_message(_msg("/provider bogus"))
    text = tg.sent[-1]["text"].lower()
    assert "unknown" in text or "tidak dikenal" in text
    assert await orch._get_user_provider(USER_ID) == "openai"  # unchanged


@pytest.mark.asyncio
async def test_provider_switch_without_credentials_is_refused(switch_setup):
    orch, tg = switch_setup
    # openrouter has no credentials configured in the fixture
    await orch.handle_message(_msg("/provider openrouter"))
    text = tg.sent[-1]["text"].lower()
    assert "credential" in text or "api key" in text
    assert await orch._get_user_provider(USER_ID) == "openai"  # unchanged


# --------------------------------------------------------------------------- #
# S3 — adjacent regression: 9router default + /model still works
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_default_provider_is_unchanged_without_switch(switch_setup):
    orch, tg = switch_setup
    assert await orch._get_user_provider(USER_ID) == "openai"


@pytest.mark.asyncio
async def test_model_command_still_switches_model_on_active_provider(switch_setup):
    orch, tg = switch_setup
    await orch.handle_message(_msg("/model some-model-name"))
    assert await orch._get_user_model(USER_ID) == "some-model-name"
