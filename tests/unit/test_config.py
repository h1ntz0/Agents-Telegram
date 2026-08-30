"""Unit tests for configuration manager, parsing, and masking."""

import os
from src.application.config_manager import ConfigManager, RootConfig, parse_int_list


def test_parse_int_list():
    assert parse_int_list("123, 456, 789") == [123, 456, 789]
    assert parse_int_list("abc, 12, def") == [12]
    assert parse_int_list("") == []
    assert parse_int_list(None) == []


def test_config_defaults(tmp_path):
    env_file = str(tmp_path / ".env.test")
    cfg_mgr = ConfigManager(env_path=env_file)
    cfg = cfg_mgr.load_config()

    assert cfg.app.env == "production"
    assert cfg.telegram.mode == "polling"
    assert cfg.ai.provider == "openai"
    assert cfg.storage.memory_enabled is True
    assert cfg.tools.web_search.enabled is True
    assert cfg.tools.shell.enabled is False


def test_save_and_load_env(tmp_path):
    env_file = str(tmp_path / ".env.custom")
    cfg_mgr = ConfigManager(env_path=env_file)

    vars_to_save = {
        "TELEGRAM_BOT_TOKEN": "9876543210:TestTokenABC",
        "TELEGRAM_ALLOWED_USERS": "1001, 1002",
        "AI_PROVIDER": "anthropic",
        "AI_API_KEY": "sk-ant-testkey123456",
        "AI_MODEL": "claude-3-5-sonnet",
        "AGENT_NAME": "CyberAssistant",
        "ALLOW_SHELL": True,
    }

    cfg_mgr.save_env_file(vars_to_save)
    assert os.path.exists(env_file)

    loaded = cfg_mgr.load_config()
    assert loaded.telegram.bot_token == "9876543210:TestTokenABC"
    assert loaded.telegram.allowed_users == [1001, 1002]
    assert loaded.ai.provider == "anthropic"
    assert loaded.agent.name == "CyberAssistant"
    assert loaded.tools.shell.enabled is True


def test_masked_view_redacts_secrets(tmp_path):
    env_file = str(tmp_path / ".env.view")
    cfg_mgr = ConfigManager(env_path=env_file)
    cfg = RootConfig()
    cfg.telegram.bot_token = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz12345"
    cfg.ai.api_key = "sk-1234567890abcdef1234567890"

    view = cfg_mgr.get_masked_view(cfg)
    tg_token_view = view["Telegram"]["Bot Token"]
    ai_key_view = view["AI Provider"]["API Key"]

    assert "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz12345" not in tg_token_view
    assert "..." in tg_token_view
    assert "sk-1234567890abcdef1234567890" not in ai_key_view
    assert "..." in ai_key_view
