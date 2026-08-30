"""E2E tests for Setup Wizard interactive simulation."""

import os
from unittest.mock import patch
import pytest
from src.application.setup_wizard import SetupWizard
from src.domain.user import TelegramUser
from src.infrastructure.telegram.adapter import TelegramAdapter


@pytest.mark.asyncio
async def test_setup_wizard_e2e(tmp_path):
    env_file = str(tmp_path / ".env.wizard_test")
    wizard = SetupWizard(env_path=env_file)

    inputs = [
        "1001, 1002",         # Allowed Telegram users
        "3",                  # Provider choice (3 = anthropic)
        "1",                  # Model choice menu (1 = claude-3-5-sonnet-20241022)
        "My Bot",             # Agent Name
        "Direct & Helpful",   # Personality
        "Helpful prompt",     # System Prompt
        "n",                  # Configure advanced? (n)
        "y"                   # Save configuration? (y)
    ]

    secrets = [
        "1234567890:ValidMockToken1234567890123456",  # Bot Token
        "sk-ant-test-key-mock12345678901234567890",   # Anthropic API Key
    ]

    with patch.object(wizard, "_prompt", side_effect=inputs), \
         patch.object(wizard, "_prompt_secret", side_effect=secrets), \
         patch.object(TelegramAdapter, "get_me", return_value=TelegramUser(id=1, username="test_bot", is_bot=True)), \
         patch("src.infrastructure.ai.anthropic_provider.AnthropicProvider.validate_credentials", return_value=True):

        success = await wizard.run(advanced=False, non_interactive=False)
        assert success is True
        assert os.path.exists(env_file)

        # Verify contents
        with open(env_file, "r") as f:
            content = f.read()

        assert "AI_PROVIDER=anthropic" in content
        assert "AGENT_NAME=My Bot" in content
        assert "AI_MODEL=" in content and "claude" in content
        assert "TELEGRAM_BOT_TOKEN=1234567890:ValidMockToken1234567890123456" in content
