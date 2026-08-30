"""Hierarchical configuration manager with schema validation, secret masking, and persistence."""

import os
import stat
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, Field


class AppSettings(BaseModel):
    env: str = "production"
    log_level: str = "INFO"
    timezone: str = "Asia/Jakarta"
    port: int = 8080


class TelegramSettings(BaseModel):
    bot_token: str = Field(default="")
    allowed_users: List[int] = Field(default_factory=list)
    admin_users: List[int] = Field(default_factory=list)
    mode: str = "polling"
    webhook_url: str = ""
    enable_private_chat: bool = True
    enable_group_chat: bool = False


class AISettings(BaseModel):
    provider: str = "openai"
    api_key: str = Field(default="")
    model: str = "gpt-4o"
    base_url: str = ""
    temperature: float = 0.2
    max_tokens: int = 2048


class AgentSettings(BaseModel):
    name: str = "Assistant"
    personality: str = "Professional"
    system_prompt: str = "You are a helpful and accurate AI assistant. You answer queries concisely and use tools when needed."


class WebSearchToolSettings(BaseModel):
    enabled: bool = True


class GitHubToolSettings(BaseModel):
    enabled: bool = False
    token: str = ""
    default_repo: str = ""
    allow_write: bool = False


class FilesystemToolSettings(BaseModel):
    enabled: bool = True
    root_dir: str = "./data"
    read_only: bool = True


class ShellToolSettings(BaseModel):
    enabled: bool = False
    allow_destructive: bool = False


class ToolsSettings(BaseModel):
    web_search: WebSearchToolSettings = Field(default_factory=WebSearchToolSettings)
    github: GitHubToolSettings = Field(default_factory=GitHubToolSettings)
    filesystem: FilesystemToolSettings = Field(default_factory=FilesystemToolSettings)
    shell: ShellToolSettings = Field(default_factory=ShellToolSettings)
    require_confirmation_for_destructive: bool = True


class StorageSettings(BaseModel):
    memory_enabled: bool = True
    provider: str = "sqlite"
    database_path: str = "data/agent.db"
    retention_days: int = 0


class SecuritySettings(BaseModel):
    rate_limit_per_minute: int = 15
    daily_budget_usd: float = 5.0


class RootConfig(BaseModel):
    app: AppSettings = Field(default_factory=AppSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    ai: AISettings = Field(default_factory=AISettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    tools: ToolsSettings = Field(default_factory=ToolsSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)


def parse_int_list(value: Optional[str]) -> List[int]:
    """Parse comma-separated integer string into a list of integers."""
    if not value:
        return []
    res = []
    for item in str(value).split(","):
        cleaned = item.strip()
        if cleaned.isdigit():
            res.append(int(cleaned))
    return res


class ConfigManager:
    """Loads and manages application configuration across YAML defaults, .env, and environment variables."""

    def __init__(self, env_path: str = ".env", default_yaml_path: str = "config/defaults/default.yaml"):
        self.env_path = env_path
        self.default_yaml_path = default_yaml_path

    def load_config(self) -> RootConfig:
        """Resolve and validate configuration by hierarchy."""
        data: Dict[str, Any] = {}

        # 1. Load from default.yaml if exists
        if os.path.exists(self.default_yaml_path):
            try:
                with open(self.default_yaml_path, "r", encoding="utf-8") as f:
                    yaml_data = yaml.safe_load(f)
                    if isinstance(yaml_data, dict):
                        data.update(yaml_data)
            except Exception:
                pass

        # 2. Load from .env file
        env_file_data: Dict[str, str] = {}
        if os.path.exists(self.env_path):
            env_file_data = dotenv_values(self.env_path)

        # Helper to get variable from OS environ > .env file
        def get_val(key: str, default: Any = None) -> Any:
            return os.environ.get(key, env_file_data.get(key, default))

        # Build resolved dictionary
        app_dict = data.get("app", {})
        telegram_dict = data.get("telegram", {})
        ai_dict = data.get("ai", {})
        agent_dict = data.get("agent", {})
        tools_dict = data.get("tools", {})
        storage_dict = data.get("storage", {})
        security_dict = data.get("security", {})

        app_cfg = AppSettings(
            env=get_val("APP_ENV", app_dict.get("env", "production")),
            log_level=get_val("LOG_LEVEL", app_dict.get("log_level", "INFO")),
            timezone=get_val("TIMEZONE", app_dict.get("timezone", "Asia/Jakarta")),
            port=int(get_val("PORT", app_dict.get("port", 8080))),
        )

        allowed_raw = get_val("TELEGRAM_ALLOWED_USERS")
        admin_raw = get_val("ADMIN_TELEGRAM_USERS")

        telegram_cfg = TelegramSettings(
            bot_token=get_val("TELEGRAM_BOT_TOKEN", telegram_dict.get("bot_token", "")),
            allowed_users=parse_int_list(allowed_raw) if allowed_raw is not None else telegram_dict.get("allowed_users", []),
            admin_users=parse_int_list(admin_raw) if admin_raw is not None else telegram_dict.get("admin_users", []),
            mode=get_val("TELEGRAM_MODE", telegram_dict.get("mode", "polling")),
            webhook_url=get_val("TELEGRAM_WEBHOOK_URL", telegram_dict.get("webhook_url", "")),
            enable_private_chat=str(get_val("ENABLE_PRIVATE_CHAT", telegram_dict.get("enable_private_chat", True))).lower() in ("true", "1", "yes"),
            enable_group_chat=str(get_val("ENABLE_GROUP_CHAT", telegram_dict.get("enable_group_chat", False))).lower() in ("true", "1", "yes"),
        )

        ai_cfg = AISettings(
            provider=get_val("AI_PROVIDER", ai_dict.get("provider", "openai")),
            api_key=get_val("AI_API_KEY", ai_dict.get("api_key", "")),
            model=get_val("AI_MODEL", ai_dict.get("model", "gpt-4o")),
            base_url=get_val("AI_BASE_URL", ai_dict.get("base_url", "")),
            temperature=float(get_val("AI_TEMPERATURE", ai_dict.get("temperature", 0.2))),
            max_tokens=int(get_val("AI_MAX_TOKENS", ai_dict.get("max_tokens", 2048))),
        )

        agent_cfg = AgentSettings(
            name=get_val("AGENT_NAME", agent_dict.get("name", "Assistant")),
            personality=get_val("AGENT_PERSONALITY", agent_dict.get("personality", "Professional")),
            system_prompt=get_val("AGENT_SYSTEM_PROMPT", agent_dict.get("system_prompt", "You are a helpful and accurate AI assistant. You answer queries concisely and use tools when needed.")),
        )

        web_cfg = WebSearchToolSettings(
            enabled=str(get_val("ENABLE_WEB_SEARCH", tools_dict.get("web_search", {}).get("enabled", True))).lower() in ("true", "1", "yes")
        )
        github_cfg = GitHubToolSettings(
            enabled=str(get_val("ENABLE_GITHUB", tools_dict.get("github", {}).get("enabled", False))).lower() in ("true", "1", "yes"),
            token=get_val("GITHUB_TOKEN", tools_dict.get("github", {}).get("token", "")),
            default_repo=get_val("GITHUB_DEFAULT_REPO", tools_dict.get("github", {}).get("default_repo", "")),
            allow_write=str(get_val("GITHUB_ALLOW_WRITE", tools_dict.get("github", {}).get("allow_write", False))).lower() in ("true", "1", "yes"),
        )
        fs_cfg = FilesystemToolSettings(
            enabled=str(get_val("ENABLE_FILESYSTEM", tools_dict.get("filesystem", {}).get("enabled", True))).lower() in ("true", "1", "yes"),
            root_dir=get_val("FILESYSTEM_ROOT_DIR", tools_dict.get("filesystem", {}).get("root_dir", "./data")),
            read_only=str(get_val("FILESYSTEM_READ_ONLY", tools_dict.get("filesystem", {}).get("read_only", True))).lower() in ("true", "1", "yes"),
        )
        shell_cfg = ShellToolSettings(
            enabled=str(get_val("ALLOW_SHELL", tools_dict.get("shell", {}).get("enabled", False))).lower() in ("true", "1", "yes"),
            allow_destructive=str(get_val("ALLOW_DESTRUCTIVE_SHELL", tools_dict.get("shell", {}).get("allow_destructive", False))).lower() in ("true", "1", "yes"),
        )

        tools_cfg = ToolsSettings(
            web_search=web_cfg,
            github=github_cfg,
            filesystem=fs_cfg,
            shell=shell_cfg,
            require_confirmation_for_destructive=str(get_val("REQUIRE_CONFIRMATION_FOR_DESTRUCTIVE", tools_dict.get("require_confirmation_for_destructive", True))).lower() in ("true", "1", "yes"),
        )

        storage_cfg = StorageSettings(
            memory_enabled=str(get_val("MEMORY_ENABLED", storage_dict.get("memory_enabled", True))).lower() in ("true", "1", "yes"),
            provider=get_val("MEMORY_PROVIDER", storage_dict.get("provider", "sqlite")),
            database_path=get_val("DATABASE_PATH", storage_dict.get("database_path", "data/agent.db")),
            retention_days=int(get_val("MEMORY_RETENTION_DAYS", storage_dict.get("retention_days", 0))),
        )

        security_cfg = SecuritySettings(
            rate_limit_per_minute=int(get_val("RATE_LIMIT_REQUESTS_PER_MINUTE", security_dict.get("rate_limit_per_minute", 15))),
            daily_budget_usd=float(get_val("DAILY_BUDGET_USD", security_dict.get("daily_budget_usd", 5.0))),
        )

        return RootConfig(
            app=app_cfg,
            telegram=telegram_cfg,
            ai=ai_cfg,
            agent=agent_cfg,
            tools=tools_cfg,
            storage=storage_cfg,
            security=security_cfg,
        )

    def save_env_file(self, env_vars: Dict[str, Any]) -> None:
        """Write key-value dictionary to .env file with secure file permissions (0600)."""
        lines = [
            "# Auto-generated by Telegram Agent Setup Wizard",
            f"APP_ENV={env_vars.get('APP_ENV', 'production')}",
            f"LOG_LEVEL={env_vars.get('LOG_LEVEL', 'INFO')}",
            f"TIMEZONE={env_vars.get('TIMEZONE', 'Asia/Jakarta')}",
            "",
            "# Telegram",
            f"TELEGRAM_BOT_TOKEN={env_vars.get('TELEGRAM_BOT_TOKEN', '')}",
            f"TELEGRAM_ALLOWED_USERS={env_vars.get('TELEGRAM_ALLOWED_USERS', '')}",
            f"ADMIN_TELEGRAM_USERS={env_vars.get('ADMIN_TELEGRAM_USERS', '')}",
            f"TELEGRAM_MODE={env_vars.get('TELEGRAM_MODE', 'polling')}",
            f"ENABLE_PRIVATE_CHAT={str(env_vars.get('ENABLE_PRIVATE_CHAT', True)).lower()}",
            f"ENABLE_GROUP_CHAT={str(env_vars.get('ENABLE_GROUP_CHAT', False)).lower()}",
            "",
            "# AI Provider",
            f"AI_PROVIDER={env_vars.get('AI_PROVIDER', 'openai')}",
            f"AI_API_KEY={env_vars.get('AI_API_KEY', '')}",
            f"AI_MODEL={env_vars.get('AI_MODEL', 'gpt-4o')}",
            f"AI_BASE_URL={env_vars.get('AI_BASE_URL', '')}",
            f"AI_TEMPERATURE={env_vars.get('AI_TEMPERATURE', 0.2)}",
            f"AI_MAX_TOKENS={env_vars.get('AI_MAX_TOKENS', 2048)}",
            "",
            "# Agent",
            f"AGENT_NAME={env_vars.get('AGENT_NAME', 'Assistant')}",
            f"AGENT_PERSONALITY={env_vars.get('AGENT_PERSONALITY', 'Professional')}",
            f"AGENT_SYSTEM_PROMPT={env_vars.get('AGENT_SYSTEM_PROMPT', 'You are a helpful and accurate AI assistant.')}",
            "",
            "# Tools",
            f"ENABLE_WEB_SEARCH={str(env_vars.get('ENABLE_WEB_SEARCH', True)).lower()}",
            f"ENABLE_GITHUB={str(env_vars.get('ENABLE_GITHUB', False)).lower()}",
            f"GITHUB_TOKEN={env_vars.get('GITHUB_TOKEN', '')}",
            f"GITHUB_DEFAULT_REPO={env_vars.get('GITHUB_DEFAULT_REPO', '')}",
            f"GITHUB_ALLOW_WRITE={str(env_vars.get('GITHUB_ALLOW_WRITE', False)).lower()}",
            f"ENABLE_FILESYSTEM={str(env_vars.get('ENABLE_FILESYSTEM', True)).lower()}",
            f"FILESYSTEM_ROOT_DIR={env_vars.get('FILESYSTEM_ROOT_DIR', './data')}",
            f"FILESYSTEM_READ_ONLY={str(env_vars.get('FILESYSTEM_READ_ONLY', True)).lower()}",
            f"ALLOW_SHELL={str(env_vars.get('ALLOW_SHELL', False)).lower()}",
            f"REQUIRE_CONFIRMATION_FOR_DESTRUCTIVE={str(env_vars.get('REQUIRE_CONFIRMATION_FOR_DESTRUCTIVE', True)).lower()}",
            "",
            "# Storage & Security",
            f"MEMORY_ENABLED={str(env_vars.get('MEMORY_ENABLED', True)).lower()}",
            f"MEMORY_PROVIDER={env_vars.get('MEMORY_PROVIDER', 'sqlite')}",
            f"DATABASE_PATH={env_vars.get('DATABASE_PATH', 'data/agent.db')}",
            f"MEMORY_RETENTION_DAYS={env_vars.get('MEMORY_RETENTION_DAYS', 0)}",
            f"RATE_LIMIT_REQUESTS_PER_MINUTE={env_vars.get('RATE_LIMIT_REQUESTS_PER_MINUTE', 15)}",
            f"DAILY_BUDGET_USD={env_vars.get('DAILY_BUDGET_USD', 5.0)}",
            ""
        ]

        content = "\n".join(lines)
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Apply strict file permissions: chmod 600 (owner read/write only)
        try:
            os.chmod(self.env_path, stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            pass

    def get_masked_view(self, config: RootConfig) -> Dict[str, Any]:
        """Produce safe configuration representation with masked secrets for inspection."""
        def mask_str(s: str) -> str:
            if not s:
                return "(not configured)"
            if len(s) <= 8:
                return "********"
            return s[:4] + "..." + s[-4:]

        return {
            "App": {
                "Environment": config.app.env,
                "Log Level": config.app.log_level,
                "Timezone": config.app.timezone,
            },
            "Telegram": {
                "Bot Token": mask_str(config.telegram.bot_token),
                "Allowed Users": config.telegram.allowed_users if config.telegram.allowed_users else "Allowlist disabled (Open access)",
                "Admin Users": config.telegram.admin_users,
                "Mode": config.telegram.mode,
                "Private Chat": "Enabled" if config.telegram.enable_private_chat else "Disabled",
                "Group Chat": "Enabled" if config.telegram.enable_group_chat else "Disabled",
            },
            "AI Provider": {
                "Provider": config.ai.provider,
                "API Key": mask_str(config.ai.api_key),
                "Model": config.ai.model,
                "Base URL": config.ai.base_url or "(default)",
                "Temperature": config.ai.temperature,
            },
            "Agent": {
                "Name": config.agent.name,
                "Personality": config.agent.personality,
            },
            "Tools": {
                "Web Search": "Enabled" if config.tools.web_search.enabled else "Disabled",
                "GitHub": "Enabled" if config.tools.github.enabled else "Disabled",
                "GitHub Token": mask_str(config.tools.github.token) if config.tools.github.enabled else "N/A",
                "Filesystem": "Enabled" if config.tools.filesystem.enabled else "Disabled",
                "Filesystem Read-Only": config.tools.filesystem.read_only,
                "Shell Execution": "Enabled" if config.tools.shell.enabled else "Disabled",
                "Confirmation for Destructive": config.tools.require_confirmation_for_destructive,
            },
            "Storage": {
                "Memory Enabled": config.storage.memory_enabled,
                "Database Path": config.storage.database_path,
                "Retention": f"{config.storage.retention_days} days" if config.storage.retention_days > 0 else "Unlimited",
            },
            "Security": {
                "Rate Limit": f"{config.security.rate_limit_per_minute} req/min",
                "Daily Budget": f"${config.security.daily_budget_usd}",
            }
        }
