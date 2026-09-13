"""E2E tests for the setup wizard: interactive flow, headless install, and config merging."""

import os
from unittest.mock import AsyncMock, patch
import pytest
from src.application.setup_wizard import SetupOptions, SetupError, SetupWizard
from src.domain.user import TelegramUser
from src.infrastructure.telegram.adapter import TelegramAdapter

WIZARD = "src.application.setup_wizard"


def _patch_network():
    """Make every outbound call in the wizard inert so the test never needs a network."""
    return [
        patch.object(TelegramAdapter, "get_me", return_value=TelegramUser(id=1, username="test_bot", is_bot=True)),
        patch.object(TelegramAdapter, "set_my_commands", new=AsyncMock(return_value=True)),
        patch.object(TelegramAdapter, "close", new=AsyncMock(return_value=None)),
        patch(f"{WIZARD}.fetch_available_models_ex", new=AsyncMock(return_value=([], False))),
        patch("src.infrastructure.ai.anthropic_provider.AnthropicProvider.validate_credentials", return_value=True),
        patch("src.infrastructure.ai.openai_provider.OpenAIProvider.validate_credentials", return_value=True),
    ]


@pytest.mark.asyncio
async def test_setup_wizard_e2e(tmp_path):
    """The interactive wizard writes a complete, usable .env from prompted answers."""
    env_file = str(tmp_path / ".env.wizard_test")
    wizard = SetupWizard(env_path=env_file)

    prompts = [
        "1",                  # Language (1 = English)
        "1001, 1002",         # Allowed Telegram users
        "3",                  # Provider choice (3 = anthropic)
        "1",                  # Model choice (1 = first claude model)
        "My Bot",             # Agent name
        "Direct & Helpful",   # Personality
        "Helpful prompt",     # System prompt
        "Asia/Jakarta",       # Timezone
        "n",                  # Configure advanced? (n)
        "y",                  # Save configuration? (y)
    ]
    secrets = [
        "1234567890:ValidMockToken1234567890123456",  # Bot token
        "sk-ant-test-key-mock12345678901234567890",   # Anthropic API key
    ]

    contexts = _patch_network()
    with patch.object(wizard, "_prompt", side_effect=prompts), \
         patch.object(wizard, "_prompt_secret", side_effect=secrets), \
         contexts[0], contexts[1], contexts[2], contexts[3], contexts[4], contexts[5]:

        success = await wizard.run(advanced=False, non_interactive=False)
        assert success is True
        assert os.path.exists(env_file)

        with open(env_file, "r", encoding="utf-8") as f:
            content = f.read()

        assert "AI_PROVIDER=anthropic" in content
        assert "AGENT_NAME=My Bot" in content
        assert "AI_MODEL=" in content and "claude" in content
        assert "TELEGRAM_BOT_TOKEN=1234567890:ValidMockToken1234567890123456" in content
        assert "TIMEZONE=Asia/Jakarta" in content
        assert "UI_LANG=en" in content


@pytest.mark.asyncio
async def test_headless_setup_needs_no_prompts(tmp_path):
    """Non-interactive setup completes from flags alone, so Docker and CI can install it."""
    env_file = str(tmp_path / ".env.headless")
    wizard = SetupWizard(env_path=env_file)

    options = SetupOptions(
        non_interactive=True,
        bot_token="1234567890:HeadlessToken1234567890123456",
        provider="anthropic",
        model="claude-3-5-sonnet-20241022",
        api_key="sk-ant-headless-key-1234567890abcdef",
        allowed_users="4242",
        language="id",
        timezone="Asia/Jakarta",
    )

    contexts = _patch_network()
    with patch.object(wizard, "_prompt", side_effect=AssertionError("headless mode must not prompt")), \
         patch.object(wizard, "_prompt_secret", side_effect=AssertionError("headless mode must not prompt")), \
         patch.object(wizard, "_prompt_choice", side_effect=AssertionError("headless mode must not prompt")), \
         patch.object(wizard, "_prompt_bool", side_effect=AssertionError("headless mode must not prompt")), \
         contexts[0], contexts[1], contexts[2], contexts[3], contexts[4], contexts[5]:

        assert await wizard.run(options) is True

    with open(env_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert "TELEGRAM_BOT_TOKEN=1234567890:HeadlessToken1234567890123456" in content
    assert "TELEGRAM_ALLOWED_USERS=4242" in content
    assert "AI_PROVIDER=anthropic" in content
    assert "AI_MODEL=claude-3-5-sonnet-20241022" in content
    assert "UI_LANG=id" in content
    assert "TIMEZONE=Asia/Jakarta" in content


@pytest.mark.asyncio
async def test_headless_setup_rejects_unknown_provider(tmp_path):
    """An unusable provider id fails loudly instead of writing a broken .env."""
    env_file = str(tmp_path / ".env.headless_bad")
    wizard = SetupWizard(env_path=env_file)
    options = SetupOptions(
        non_interactive=True,
        bot_token="1234567890:HeadlessToken1234567890123456",
        provider="not-a-provider",
    )

    with patch.object(TelegramAdapter, "get_me", return_value=TelegramUser(id=1, username="t", is_bot=True)), \
         patch.object(TelegramAdapter, "close", new=AsyncMock(return_value=None)), \
         pytest.raises(SetupError):
        await wizard.run(options)

    assert not os.path.exists(env_file)


@pytest.mark.asyncio
async def test_rerunning_setup_preserves_hand_edited_keys(tmp_path):
    """Re-running setup must not delete keys the wizard does not ask about."""
    env_file = str(tmp_path / ".env.merge")
    with open(env_file, "w", encoding="utf-8") as f:
        f.write("# my notes\nGITHUB_TOKEN=ghp_handwritten\nAI_TEMPERATURE=0.9\n")

    wizard = SetupWizard(env_path=env_file)
    options = SetupOptions(
        non_interactive=True,
        bot_token="1234567890:HeadlessToken1234567890123456",
        provider="anthropic",
        model="claude-3-5-sonnet-20241022",
        api_key="sk-ant-headless-key-1234567890abcdef",
        timezone="UTC",
    )

    contexts = _patch_network()
    with contexts[0], contexts[1], contexts[2], contexts[3], contexts[4], contexts[5]:
        assert await wizard.run(options) is True

    with open(env_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert "GITHUB_TOKEN=ghp_handwritten" in content
    assert "AI_TEMPERATURE=0.9" in content
    assert "# my notes" in content
    assert "AI_PROVIDER=anthropic" in content
