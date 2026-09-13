"""Hierarchical configuration manager with schema validation, secret masking, and persistence."""

import os
import re
import stat
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set
import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, Field
from src.domain.provider import normalize_provider_name
from src.infrastructure.i18n import DEFAULT_LANGUAGE, normalize_language

DEFAULT_CONFIG_PATH = "config/config.yaml"
DEFAULT_DEFAULTS_PATH = "config/defaults/default.yaml"

# Values accepted as boolean `true` in a .env file.
_TRUTHY = ("true", "1", "yes", "y", "on")


class ConfigurationError(ValueError):
    """Raised when a configuration value cannot be parsed, naming the offending key."""


class AppSettings(BaseModel):
    env: str = "production"
    log_level: str = ""
    timezone: str = "UTC"
    ui_lang: str = DEFAULT_LANGUAGE


class TelegramSettings(BaseModel):
    bot_token: str = Field(default="")
    allowed_users: List[int] = Field(default_factory=list)
    admin_users: List[int] = Field(default_factory=list)
    enable_private_chat: bool = True
    enable_group_chat: bool = False


class AISettings(BaseModel):
    provider: str = "openai"
    api_key: str = Field(default="")
    model: str = "gpt-4o"
    base_url: str = ""
    temperature: float = 0.2
    max_tokens: int = 2048
    timeout_seconds: float = 60.0
    opencode_server_url: str = "http://127.0.0.1:4096"


class AgentSettings(BaseModel):
    name: str = "Assistant"
    personality: str = "Professional"
    system_prompt: str = "You are a helpful and accurate AI assistant. You answer queries concisely and use tools when needed."


class WebSearchToolSettings(BaseModel):
    enabled: bool = True


class GitHubToolSettings(BaseModel):
    enabled: bool = True
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


class ProviderCredential(BaseModel):
    """Per-provider credentials so a user can switch providers at runtime."""

    api_key: str = ""
    base_url: str = ""
    model: str = ""


# Canonical provider id -> env var prefix for per-provider credentials.
# Explicit mapping (not upper()): a canonical id like '9router' starts with a digit.
PROVIDER_ENV_PREFIX: Dict[str, str] = {
    "9router": "NINE_ROUTER",
    "deepseek": "DEEPSEEK",
    "anthropic": "ANTHROPIC",
    "google": "GOOGLE",
    "openai": "OPENAI",
    "openrouter": "OPENROUTER",
    "ollama": "OLLAMA",
    "opencode-zen": "OPENCODE_ZEN",
    "opencode-go": "OPENCODE_GO",
    "custom": "CUSTOM",
}

# Renamed keys that older .env files and the v2 docs still use.
# The canonical name wins when both are present.
ENV_ALIASES: Dict[str, str] = {
    "MEMORY_PROVIDER": "STORAGE_PROVIDER",
    "MEMORY_RETENTION_DAYS": "DATA_RETENTION_DAYS",
}

# Every environment key the application reads. Anything else in .env is inert,
# which `agent doctor` reports so a typo cannot silently do nothing.
KNOWN_ENV_KEYS: Set[str] = {
    "APP_ENV",
    "LOG_LEVEL",
    "TIMEZONE",
    "UI_LANG",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USERS",
    "ADMIN_TELEGRAM_USERS",
    "ENABLE_PRIVATE_CHAT",
    "ENABLE_GROUP_CHAT",
    "AI_PROVIDER",
    "AI_API_KEY",
    "AI_MODEL",
    "AI_BASE_URL",
    "AI_TEMPERATURE",
    "AI_MAX_TOKENS",
    "AI_TIMEOUT_SECONDS",
    "OPENCODE_SERVER_URL",
    "AGENT_NAME",
    "AGENT_PERSONALITY",
    "AGENT_SYSTEM_PROMPT",
    "ENABLE_WEB_SEARCH",
    "ENABLE_HTTP_FETCH",
    "HTTP_FETCH_TIMEOUT_SECONDS",
    "ENABLE_CHART",
    "ENABLE_PYTHON_SANDBOX",
    "PYTHON_SANDBOX_TIMEOUT_SECONDS",
    "ENABLE_WEATHER",
    "WEATHER_TIMEOUT_SECONDS",
    "ENABLE_GITHUB",
    "GITHUB_TOKEN",
    "GITHUB_DEFAULT_REPO",
    "GITHUB_ALLOW_WRITE",
    "ENABLE_FILESYSTEM",
    "FILESYSTEM_ROOT_DIR",
    "FILESYSTEM_READ_ONLY",
    "ALLOW_SHELL",
    "ALLOW_DESTRUCTIVE_SHELL",
    "SHELL_TIMEOUT_SECONDS",
    "REQUIRE_CONFIRMATION_FOR_DESTRUCTIVE",
    "MEMORY_ENABLED",
    "STORAGE_PROVIDER",
    "DATABASE_PATH",
    "DATA_RETENTION_DAYS",
    "RATE_LIMIT_REQUESTS_PER_MINUTE",
}
KNOWN_ENV_KEYS.update(ENV_ALIASES.keys())
for _prefix in PROVIDER_ENV_PREFIX.values():
    KNOWN_ENV_KEYS.update({f"{_prefix}_API_KEY", f"{_prefix}_BASE_URL", f"{_prefix}_MODEL"})


class RootConfig(BaseModel):
    app: AppSettings = Field(default_factory=AppSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    ai: AISettings = Field(default_factory=AISettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    tools: ToolsSettings = Field(default_factory=ToolsSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    providers: Dict[str, ProviderCredential] = Field(default_factory=dict)


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


def parse_bool(value: Any) -> bool:
    """Parse a permissive boolean (`true`/`1`/`yes`/`y`/`on`, case-insensitive)."""
    return str(value).strip().lower() in _TRUTHY


def find_unknown_env_keys(env_path: str) -> List[str]:
    """Return the keys present in an .env file that the application never reads."""
    if not os.path.exists(env_path):
        return []
    loaded = dotenv_values(env_path)
    return sorted(k for k in loaded if k and k not in KNOWN_ENV_KEYS)


def _read_yaml(path: str) -> Dict[str, Any]:
    """Read a YAML mapping from disk, returning an empty dict when absent or empty."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge `override` onto `base` without mutating either input."""
    merged: Dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class ConfigManager:
    """Loads, validates, masks, and persists configuration from YAML, env, and defaults.

    Precedence, highest first: process environment, `.env` file, `config/config.yaml`,
    `config/defaults/default.yaml`, then the pydantic field defaults.
    """

    def __init__(
        self,
        env_path: str = ".env",
        config_path: str = DEFAULT_CONFIG_PATH,
        defaults_path: str = DEFAULT_DEFAULTS_PATH,
    ):
        self.env_path = env_path
        self.config_path = config_path
        self.defaults_path = defaults_path

    # -- loading ---------------------------------------------------------------

    def _load_layers(self) -> Dict[str, Any]:
        """Return the merged YAML layers (shipped defaults under the user override)."""
        return _deep_merge(_read_yaml(self.defaults_path), _read_yaml(self.config_path))

    def load_config(self) -> RootConfig:
        """Load and resolve the hierarchical configuration."""
        yaml_data = self._load_layers()

        env_file_data: Dict[str, str] = {}
        if os.path.exists(self.env_path):
            loaded = dotenv_values(self.env_path)
            env_file_data = {k: v for k, v in loaded.items() if v is not None}

        def raw(env_key: str) -> Any:
            """Resolve one key to its raw string value, or None when unset everywhere."""
            if env_key in os.environ:
                return os.environ[env_key]
            if env_key in env_file_data:
                return env_file_data[env_key]
            alias = ENV_ALIASES.get(env_key)
            if alias:
                if alias in os.environ:
                    return os.environ[alias]
                if alias in env_file_data:
                    return env_file_data[alias]
            return None

        def get_val(env_key: str, default: Any = None) -> Any:
            value = raw(env_key)
            return default if value is None else value

        def as_bool(env_key: str, default: bool) -> bool:
            value = raw(env_key)
            return default if value is None else parse_bool(value)

        def as_int(env_key: str, default: int) -> int:
            value = raw(env_key)
            if value is None:
                return default
            try:
                return int(str(value).strip())
            except (TypeError, ValueError):
                raise ConfigurationError(f"{env_key} must be an integer, got {value!r}")

        def as_float(env_key: str, default: float) -> float:
            value = raw(env_key)
            if value is None:
                return default
            try:
                return float(str(value).strip())
            except (TypeError, ValueError):
                raise ConfigurationError(f"{env_key} must be a number, got {value!r}")

        app_dict = yaml_data.get("app", {})
        telegram_dict = yaml_data.get("telegram", {})
        ai_dict = yaml_data.get("ai", {})
        agent_dict = yaml_data.get("agent", {})
        tools_dict = yaml_data.get("tools", {})
        storage_dict = yaml_data.get("storage", {})
        sec_dict = yaml_data.get("security", {})

        app_env = get_val("APP_ENV", app_dict.get("env", "production"))
        app_cfg = AppSettings(
            env=app_env,
            # An unset LOG_LEVEL defaults to DEBUG outside production so a development
            # run is verbose without anyone having to edit .env.
            log_level=get_val("LOG_LEVEL", app_dict.get("log_level") or ("DEBUG" if app_env != "production" else "INFO")),
            timezone=get_val("TIMEZONE", app_dict.get("timezone", "UTC")),
            ui_lang=normalize_language(get_val("UI_LANG", app_dict.get("ui_lang", DEFAULT_LANGUAGE))),
        )

        allowed_raw = raw("TELEGRAM_ALLOWED_USERS")
        admin_raw = raw("ADMIN_TELEGRAM_USERS")

        telegram_cfg = TelegramSettings(
            bot_token=get_val("TELEGRAM_BOT_TOKEN", telegram_dict.get("bot_token", "")),
            allowed_users=parse_int_list(allowed_raw) if allowed_raw is not None else telegram_dict.get("allowed_users", []),
            admin_users=parse_int_list(admin_raw) if admin_raw is not None else telegram_dict.get("admin_users", []),
            enable_private_chat=as_bool("ENABLE_PRIVATE_CHAT", telegram_dict.get("enable_private_chat", True)),
            enable_group_chat=as_bool("ENABLE_GROUP_CHAT", telegram_dict.get("enable_group_chat", False)),
        )

        ai_cfg = AISettings(
            provider=get_val("AI_PROVIDER", ai_dict.get("provider", "openai")),
            api_key=get_val("AI_API_KEY", ai_dict.get("api_key", "")),
            model=get_val("AI_MODEL", ai_dict.get("model", "gpt-4o")),
            base_url=get_val("AI_BASE_URL", ai_dict.get("base_url", "")),
            temperature=as_float("AI_TEMPERATURE", ai_dict.get("temperature", 0.2)),
            max_tokens=as_int("AI_MAX_TOKENS", ai_dict.get("max_tokens", 2048)),
            timeout_seconds=as_float("AI_TIMEOUT_SECONDS", ai_dict.get("timeout_seconds", 60.0)),
            opencode_server_url=get_val("OPENCODE_SERVER_URL", ai_dict.get("opencode_server_url", "http://127.0.0.1:4096")),
        )

        # Per-provider credentials: {PREFIX}_API_KEY / _BASE_URL / _MODEL, plus the generic
        # AI_* values seeded onto the default provider so runtime /provider switching has a
        # single credential lookup path.
        providers_cfg: Dict[str, ProviderCredential] = {}
        for prov_id, prefix in PROVIDER_ENV_PREFIX.items():
            p_key = get_val(f"{prefix}_API_KEY")
            p_url = get_val(f"{prefix}_BASE_URL")
            p_model = get_val(f"{prefix}_MODEL")
            if p_key or p_url or p_model:
                providers_cfg[prov_id] = ProviderCredential(
                    api_key=p_key or "", base_url=p_url or "", model=p_model or ""
                )

        default_prov = normalize_provider_name(ai_cfg.provider)
        seeded = providers_cfg.get(default_prov, ProviderCredential())
        if ai_cfg.api_key and not seeded.api_key:
            seeded.api_key = ai_cfg.api_key
        if ai_cfg.base_url and not seeded.base_url:
            seeded.base_url = ai_cfg.base_url
        if ai_cfg.model and not seeded.model:
            seeded.model = ai_cfg.model
        providers_cfg[default_prov] = seeded

        agent_cfg = AgentSettings(
            name=get_val("AGENT_NAME", agent_dict.get("name", "Assistant")),
            personality=get_val("AGENT_PERSONALITY", agent_dict.get("personality", "Professional")),
            system_prompt=get_val("AGENT_SYSTEM_PROMPT", agent_dict.get("system_prompt", "You are a helpful and accurate AI assistant. You answer queries concisely and use tools when needed.")),
        )

        web_cfg = WebSearchToolSettings(enabled=as_bool("ENABLE_WEB_SEARCH", tools_dict.get("web_search", {}).get("enabled", True)))
        http_cfg = HttpFetchToolSettings(
            enabled=as_bool("ENABLE_HTTP_FETCH", tools_dict.get("http_fetch", {}).get("enabled", True)),
            timeout_seconds=as_float("HTTP_FETCH_TIMEOUT_SECONDS", tools_dict.get("http_fetch", {}).get("timeout_seconds", 15.0)),
        )
        chart_cfg = ChartToolSettings(enabled=as_bool("ENABLE_CHART", tools_dict.get("chart", {}).get("enabled", True)))
        py_cfg = PythonSandboxToolSettings(
            enabled=as_bool("ENABLE_PYTHON_SANDBOX", tools_dict.get("python_sandbox", {}).get("enabled", True)),
            timeout_seconds=as_float("PYTHON_SANDBOX_TIMEOUT_SECONDS", tools_dict.get("python_sandbox", {}).get("timeout_seconds", 5.0)),
        )
        weather_cfg = WeatherToolSettings(
            enabled=as_bool("ENABLE_WEATHER", tools_dict.get("weather", {}).get("enabled", True)),
            timeout_seconds=as_float("WEATHER_TIMEOUT_SECONDS", tools_dict.get("weather", {}).get("timeout_seconds", 12.0)),
        )
        github_cfg = GitHubToolSettings(
            enabled=as_bool("ENABLE_GITHUB", tools_dict.get("github", {}).get("enabled", True)),
            token=get_val("GITHUB_TOKEN", tools_dict.get("github", {}).get("token", "")),
            default_repo=get_val("GITHUB_DEFAULT_REPO", tools_dict.get("github", {}).get("default_repo", "")),
            allow_write=as_bool("GITHUB_ALLOW_WRITE", tools_dict.get("github", {}).get("allow_write", False)),
        )
        fs_cfg = FilesystemToolSettings(
            enabled=as_bool("ENABLE_FILESYSTEM", tools_dict.get("filesystem", {}).get("enabled", True)),
            root_dir=get_val("FILESYSTEM_ROOT_DIR", tools_dict.get("filesystem", {}).get("root_dir", "./data")),
            read_only=as_bool("FILESYSTEM_READ_ONLY", tools_dict.get("filesystem", {}).get("read_only", True)),
        )
        shell_cfg = ShellToolSettings(
            enabled=as_bool("ALLOW_SHELL", tools_dict.get("shell", {}).get("enabled", False)),
            allow_destructive=as_bool("ALLOW_DESTRUCTIVE_SHELL", tools_dict.get("shell", {}).get("allow_destructive", False)),
            timeout_seconds=as_float("SHELL_TIMEOUT_SECONDS", tools_dict.get("shell", {}).get("timeout_seconds", 30.0)),
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
            require_confirmation_for_destructive=as_bool(
                "REQUIRE_CONFIRMATION_FOR_DESTRUCTIVE",
                tools_dict.get("require_confirmation_for_destructive", True),
            ),
        )

        storage_cfg = StorageSettings(
            memory_enabled=as_bool("MEMORY_ENABLED", storage_dict.get("memory_enabled", True)),
            provider=get_val("STORAGE_PROVIDER", storage_dict.get("provider", "sqlite")),
            database_path=get_val("DATABASE_PATH", storage_dict.get("database_path", "data/agent.db")),
            retention_days=as_int("DATA_RETENTION_DAYS", storage_dict.get("retention_days", 0)),
        )

        sec_cfg = SecuritySettings(
            rate_limit_per_minute=as_int("RATE_LIMIT_REQUESTS_PER_MINUTE", sec_dict.get("rate_limit_per_minute", 15)),
        )

        return RootConfig(
            app=app_cfg,
            telegram=telegram_cfg,
            ai=ai_cfg,
            agent=agent_cfg,
            tools=tools_cfg,
            storage=storage_cfg,
            security=sec_cfg,
            providers=providers_cfg,
        )

    # -- persistence -----------------------------------------------------------

    def save_env_file(self, env_dict: Dict[str, Any], merge: bool = True) -> Path:
        """Write configuration to the env file, preserving anything already there.

        With ``merge=True`` (the default) existing lines - including comments and keys the
        wizard does not manage - are kept, and only the supplied keys are added or updated.
        This is what makes re-running ``agent setup`` safe.
        """
        def render(value: Any) -> str:
            if isinstance(value, bool):
                return "true" if value else "false"
            if value is None:
                return ""
            return str(value)

        pending = {k: render(v) for k, v in env_dict.items()}
        lines: List[str] = []
        path = Path(self.env_path)

        if merge and path.exists():
            existing = path.read_text(encoding="utf-8").splitlines()
            key_pattern = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
            for line in existing:
                match = key_pattern.match(line)
                if match and match.group(1) in pending:
                    key = match.group(1)
                    lines.append(f"{key}={pending.pop(key)}")
                else:
                    lines.append(line)

        if pending:
            if not lines:
                lines = [
                    "# Telegram Agent Configuration",
                    "# Generated by 'agent setup'. Every key is documented in .env.example.",
                    "",
                ]
            elif lines[-1].strip():
                lines.append("")
            lines.append("# --- Updated by 'agent setup' ---")
            for key, value in pending.items():
                lines.append(f"{key}={value}")

        while lines and not lines[-1].strip():
            lines.pop()

        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Restrict permissions to the owner (a no-op on Windows, where ACLs govern instead).
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

        return path.resolve()

    # -- introspection ---------------------------------------------------------

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

        for name, cred in (raw.get("providers") or {}).items():
            if cred.get("api_key"):
                cred["api_key"] = cred["api_key"][:3] + "..." if len(cred["api_key"]) > 7 else "***"

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

    def unknown_env_keys(self) -> List[str]:
        """Return the inert keys present in this instance's env file."""
        return find_unknown_env_keys(self.env_path)

    def current_language(self) -> str:
        """Return the configured UI language code (UI_LANG), defaulting to English."""
        value = os.environ.get("UI_LANG")
        if value is None and os.path.exists(self.env_path):
            value = dotenv_values(self.env_path).get("UI_LANG")
        return normalize_language(value or DEFAULT_LANGUAGE)


def iter_env_lines(env_dict: Dict[str, Any]) -> Iterable[str]:
    """Yield ``KEY=value`` lines for a settings mapping (used by tooling and tests)."""
    for key, value in env_dict.items():
        if isinstance(value, bool):
            yield f"{key}={'true' if value else 'false'}"
        elif value is None:
            yield f"{key}="
        else:
            yield f"{key}={value}"
