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
    allow_groups: bool = False


class AISettings(BaseModel):
    provider: str = "openai"
    api_key: str = Field(default="")
    model: str = "gpt-4o"
    base_url: str = ""
    temperature: float = 0.2
    max_tokens: int = 2048
    timeout_seconds: float = 60.0


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
    timeout_seconds: float = 30.0


class HttpFetchToolSettings(BaseModel):
    enabled: bool = True
    timeout_seconds: float = 15.0


class ChartToolSettings(BaseModel):
    enabled: bool = True


class PythonSandboxToolSettings(BaseModel):
    enabled: bool = True
    timeout_seconds: float = 5.0


class WeatherToolSettings(BaseModel):
    enabled: bool = True
    timeout_seconds: float = 12.0


class ToolsSettings(BaseModel):
    web_search: WebSearchToolSettings = Field(default_factory=WebSearchToolSettings)
    http_fetch: HttpFetchToolSettings = Field(default_factory=HttpFetchToolSettings)
    chart: ChartToolSettings = Field(default_factory=ChartToolSettings)
    python_sandbox: PythonSandboxToolSettings = Field(default_factory=PythonSandboxToolSettings)
    weather: WeatherToolSettings = Field(default_factory=WeatherToolSettings)
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
    """Loads, validates, masks, and persists configuration from YAML, env, and defaults."""

    def __init__(self, env_path: str = ".env", config_path: str = "config/config.yaml"):
        self.env_path = env_path
        self.config_path = config_path

    def load_config(self) -> RootConfig:
        """Load and resolve hierarchical configuration with precedence: Env Vars > .env > config.yaml > Defaults."""
        # 1. Load YAML file if exists
        yaml_data: Dict[str, Any] = {}
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f) or {}

        # 2. Load .env file
        env_file_data: Dict[str, str] = {}
        if os.path.exists(self.env_path):
            loaded = dotenv_values(self.env_path)
            env_file_data = {k: v for k, v in loaded.items() if v is not None}

        # Helper to get value in precedence order
        def get_val(env_key: str, default: Any = None) -> Any:
            if env_key in os.environ:
                return os.environ[env_key]
            if env_key in env_file_data:
                return env_file_data[env_key]
            return default

        # Build settings with hierarchical fallbacks
        app_dict = yaml_data.get("app", {})
        telegram_dict = yaml_data.get("telegram", {})
        ai_dict = yaml_data.get("ai", {})
        agent_dict = yaml_data.get("agent", {})
        tools_dict = yaml_data.get("tools", {})
        storage_dict = yaml_data.get("storage", {})
        sec_dict = yaml_data.get("security", {})

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
            timeout_seconds=float(get_val("AI_TIMEOUT_SECONDS", ai_dict.get("timeout_seconds", 60.0))),
        )

        agent_cfg = AgentSettings(
            name=get_val("AGENT_NAME", agent_dict.get("name", "Assistant")),
            personality=get_val("AGENT_PERSONALITY", agent_dict.get("personality", "Professional")),
            system_prompt=get_val("AGENT_SYSTEM_PROMPT", agent_dict.get("system_prompt", "You are a helpful and accurate AI assistant. You answer queries concisely and use tools when needed.")),
        )

        web_cfg = WebSearchToolSettings(
            enabled=str(get_val("ENABLE_WEB_SEARCH", tools_dict.get("web_search", {}).get("enabled", True))).lower() in ("true", "1", "yes")
        )
        http_cfg = HttpFetchToolSettings(
            enabled=str(get_val("ENABLE_HTTP_FETCH", tools_dict.get("http_fetch", {}).get("enabled", True))).lower() in ("true", "1", "yes"),
            timeout_seconds=float(get_val("HTTP_FETCH_TIMEOUT_SECONDS", tools_dict.get("http_fetch", {}).get("timeout_seconds", 15.0))),
        )
        chart_cfg = ChartToolSettings(
            enabled=str(get_val("ENABLE_CHART", tools_dict.get("chart", {}).get("enabled", True))).lower() in ("true", "1", "yes"),
        )
        py_cfg = PythonSandboxToolSettings(
            enabled=str(get_val("ENABLE_PYTHON_SANDBOX", tools_dict.get("python_sandbox", {}).get("enabled", True))).lower() in ("true", "1", "yes"),
            timeout_seconds=float(get_val("PYTHON_SANDBOX_TIMEOUT_SECONDS", tools_dict.get("python_sandbox", {}).get("timeout_seconds", 5.0))),
        )
        weather_cfg = WeatherToolSettings(
            enabled=str(get_val("ENABLE_WEATHER", tools_dict.get("weather", {}).get("enabled", True))).lower() in ("true", "1", "yes"),
            timeout_seconds=float(get_val("WEATHER_TIMEOUT_SECONDS", tools_dict.get("weather", {}).get("timeout_seconds", 12.0))),
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
            timeout_seconds=float(get_val("SHELL_TIMEOUT_SECONDS", tools_dict.get("shell", {}).get("timeout_seconds", 30.0))),
        )

        tools_cfg = ToolsSettings(
            web_search=web_cfg,
            http_fetch=http_cfg,
            chart=chart_cfg,
            python_sandbox=py_cfg,
            weather=weather_cfg,
            github=github_cfg,
            filesystem=fs_cfg,
            shell=shell_cfg,
            require_confirmation_for_destructive=str(get_val("REQUIRE_CONFIRMATION_FOR_DESTRUCTIVE", tools_dict.get("require_confirmation_for_destructive", True))).lower() in ("true", "1", "yes"),
        )

        storage_cfg = StorageSettings(
            memory_enabled=str(get_val("MEMORY_ENABLED", storage_dict.get("memory_enabled", True))).lower() in ("true", "1", "yes"),
            provider=get_val("STORAGE_PROVIDER", storage_dict.get("provider", "sqlite")),
            database_path=get_val("DATABASE_PATH", storage_dict.get("database_path", "data/agent.db")),
            retention_days=int(get_val("DATA_RETENTION_DAYS", storage_dict.get("retention_days", 0))),
        )

        sec_cfg = SecuritySettings(
            rate_limit_per_minute=int(get_val("RATE_LIMIT_REQUESTS_PER_MINUTE", sec_dict.get("rate_limit_per_minute", 15))),
            daily_budget_usd=float(get_val("DAILY_BUDGET_USD", sec_dict.get("daily_budget_usd", 5.0))),
        )

        return RootConfig(
            app=app_cfg,
            telegram=telegram_cfg,
            ai=ai_cfg,
            agent=agent_cfg,
            tools=tools_cfg,
            storage=storage_cfg,
            security=sec_cfg,
        )

    def save_env_file(self, env_dict: Dict[str, Any]) -> None:
        """Write key-value dictionary to .env file and set 0600 file permissions."""
        lines = ["# Telegram Agent Configuration Auto-Generated", "# Permissions: 0600 (Restricted to owner)\n"]
        for k, v in env_dict.items():
            if isinstance(v, bool):
                val_str = "true" if v else "false"
            elif v is None:
                val_str = ""
            else:
                val_str = str(v)
            lines.append(f"{k}={val_str}")

        content = "\n".join(lines) + "\n"

        # Write to file
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Set file permission to 0600 (chmod 600)
        try:
            os.chmod(self.env_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def get_masked_config(self) -> Dict[str, Any]:
        """Return config with secrets masked for safe CLI display."""
        config = self.load_config()
        raw = config.model_dump()

        # Mask secrets
        if raw.get("telegram", {}).get("bot_token"):
            token = raw["telegram"]["bot_token"]
            raw["telegram"]["bot_token"] = token[:6] + "..." + token[-4:] if len(token) > 10 else "***"

        if raw.get("ai", {}).get("api_key"):
            key = raw["ai"]["api_key"]
            raw["ai"]["api_key"] = key[:3] + "..." + key[-4:] if len(key) > 7 else "***"

        if raw.get("tools", {}).get("github", {}).get("token"):
            gh_tok = raw["tools"]["github"]["token"]
            raw["tools"]["github"]["token"] = gh_tok[:4] + "..." if len(gh_tok) > 6 else "***"

        return raw

    def get_masked_view(self, config: Optional[RootConfig] = None) -> Dict[str, Any]:
        """Return human-readable sectioned masked view."""
        if config is None:
            config = self.load_config()

        tg_token = config.telegram.bot_token
        masked_tg = tg_token[:6] + "..." + tg_token[-4:] if len(tg_token) > 10 else "***"

        ai_key = config.ai.api_key
        masked_ai = ai_key[:3] + "..." + ai_key[-4:] if len(ai_key) > 7 else "***"

        return {
            "Telegram": {
                "Bot Token": masked_tg,
                "Allowed Users": config.telegram.allowed_users,
            },
            "AI Provider": {
                "Provider": config.ai.provider,
                "Model": config.ai.model,
                "API Key": masked_ai,
            },
            "Agent": {
                "Name": config.agent.name,
                "Personality": config.agent.personality,
            }
        }
