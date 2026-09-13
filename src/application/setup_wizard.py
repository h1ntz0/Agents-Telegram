"""Interactive and headless setup wizard with live API verification and flexible model selection."""

import getpass
import os
import platform
import shutil
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from src.application.config_manager import ConfigManager, RootConfig
from src.infrastructure.ai.factory import create_ai_provider
from src.domain.provider import PROVIDER_MODELS_CATALOG, KEYLESS_PROVIDERS, normalize_provider_name
from src.infrastructure.ai.model_discovery import (
    base_url_lacks_api_path,
    fetch_available_models_ex,
    normalize_base_url,
)
from src.infrastructure.i18n import (
    LANGUAGE_NAMES,
    available_languages,
    language_name,
    normalize_language,
    set_language,
    t,
)
from src.infrastructure.telegram.adapter import TelegramAdapter, build_bot_commands

# Provider ids offered by the wizard, in menu order.
PROVIDER_CHOICES: List[str] = [
    "9router",
    "deepseek",
    "anthropic",
    "google",
    "openai",
    "openrouter",
    "ollama",
    "opencode-zen",
    "opencode-go",
    "custom",
]

# Providers whose base URL the wizard asks for (the rest use a built-in default).
PROVIDER_URL_DEFAULTS: Dict[str, str] = {
    "9router": "http://localhost:20128/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "opencode-zen": "https://api.opencode.ai/v1",
    "opencode-go": "https://go.opencode.ai/v1",
}

# Model menus are derived from the shared catalog so the wizard can never drift
# out of sync with the providers' real model list.
PROVIDER_MODEL_MENUS: Dict[str, List[str]] = {
    provider: list(models) + ["Ketik nama model manual (Custom)"]
    for provider, models in PROVIDER_MODELS_CATALOG.items()
}

CUSTOM_MODEL_SENTINEL = "Ketik nama model manual (Custom)"


class SetupError(RuntimeError):
    """Raised when setup cannot complete, carrying a message safe to print to the user."""


@dataclass
class SetupOptions:
    """Everything the wizard can be told up front, enabling a fully headless install."""

    advanced: bool = False
    non_interactive: bool = False
    bot_token: str = ""
    provider: str = ""
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    allowed_users: str = ""
    language: str = ""
    timezone: str = ""
    force: bool = False
    # Values filled in by the wizard during the run.
    extras: Dict[str, Any] = field(default_factory=dict)


def valid_timezone(name: str) -> bool:
    """Whether a string is an IANA timezone this interpreter can resolve."""
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return False


class SetupWizard:
    """Guided terminal wizard to configure and initialize the Telegram Agent."""

    def __init__(self, env_path: str = ".env"):
        self.env_path = env_path
        self.config_manager = ConfigManager(env_path=env_path)

    # -- prompt helpers --------------------------------------------------------

    def _prompt(self, question: str, default: str = "") -> str:
        """Prompt user with optional default fallback."""
        default_str = f" [{default}]" if default else ""
        try:
            val = input(f"? {question}{default_str}: ").strip()
            return val if val else default
        except (KeyboardInterrupt, EOFError):
            print(f"\n{t('wizard.exit.generic')}")
            raise SetupError(t("wizard.exit.generic"))

    def _prompt_int(self, question: str, default: int = 15) -> int:
        """Prompt user for an integer with graceful validation and retry."""
        while True:
            raw = self._prompt(question, str(default))
            try:
                clean = raw.strip()
                if clean.lower() in ("y", "yes", "ok"):
                    return default
                return int(clean)
            except ValueError:
                print(f"  ! Please enter a whole number, for example {default}.")

    def _prompt_float(self, question: str, default: float = 5.0) -> float:
        """Prompt user for a floating-point number with graceful validation."""
        while True:
            raw = self._prompt(question, str(default))
            try:
                clean = raw.strip()
                if clean.lower() in ("y", "yes", "ok"):
                    return default
                return float(clean)
            except ValueError:
                print(f"  ! Please enter a number, for example {default}.")

    def _prompt_secret(self, question: str, default: str = "") -> str:
        """Prompt for sensitive credentials securely."""
        default_str = " [press Enter to keep the current value]" if default else ""
        try:
            val = getpass.getpass(f"? {question}{default_str}: ").strip()
            return val if val else default
        except (KeyboardInterrupt, EOFError):
            print(f"\n{t('wizard.exit.generic')}")
            raise SetupError(t("wizard.exit.generic"))

    def _prompt_url(self, question: str, default: str = "") -> str:
        """Prompt for a base URL, validating and normalizing it with retry."""
        while True:
            raw = self._prompt(question, default)
            if not raw.strip():
                return ""
            normalized = normalize_base_url(raw)
            if normalized:
                if normalized != raw.strip().rstrip("/"):
                    print(f"  -> Using URL: {normalized}")
                if base_url_lacks_api_path(normalized):
                    print(f"  ! {t('wizard.error.url_rejected')}")
                    print("    A gateway normally needs a path, for example http://localhost:20128/v1")
                return normalized
            print(f"  ! {t('wizard.error.url_rejected')}")

    def _prompt_choice(self, question: str, choices: list[str], default_idx: int = 0) -> str:
        """Prompt user to choose from a list of options."""
        print(f"\n? {question}")
        for i, choice in enumerate(choices, 1):
            marker = ">" if (i - 1) == default_idx else " "
            print(f"  {marker} {i}. {choice}")
        while True:
            val = self._prompt(f"Select an option (1-{len(choices)})", str(default_idx + 1))
            if val.isdigit() and 1 <= int(val) <= len(choices):
                return choices[int(val) - 1]
            print(f"  ! Invalid choice. Enter a number between 1 and {len(choices)}.")

    def _prompt_bool(self, question: str, default: bool = True) -> bool:
        """Prompt user for a yes/no boolean response."""
        default_str = "Y/n" if default else "y/N"
        val = self._prompt(f"{question} ({default_str})", "y" if default else "n").lower()
        return val in ("y", "yes", "true", "1")

    # -- run -------------------------------------------------------------------

    async def run(
        self,
        options: Optional[SetupOptions] = None,
        advanced: bool = False,
        non_interactive: bool = False,
    ) -> bool:
        """Execute the setup sequence and persist a configuration.

        Pass a :class:`SetupOptions` to drive the wizard (fully headless when
        ``non_interactive`` is set). ``advanced``/``non_interactive`` remain as direct
        keyword arguments for callers that predate the options object.
        """
        if options is None:
            options = SetupOptions(advanced=advanced, non_interactive=non_interactive)
        else:
            options.advanced = options.advanced or advanced
            options.non_interactive = options.non_interactive or non_interactive

        headless = options.non_interactive
        interactive = not headless

        if not headless:
            print("\n" + "=" * 52)
            print(f"  {t('wizard.title')}")
            print("=" * 52 + "\n")

        # Language is resolved first (the question itself is bilingual) so every later
        # message is already in the language the user chose.
        existing_cfg: Optional[RootConfig] = None
        if os.path.exists(self.env_path):
            try:
                existing_cfg = self.config_manager.load_config()
            except Exception:
                existing_cfg = None

        if options.language and self._is_language(options.language):
            lang = normalize_language(options.language)
        elif interactive:
            lang = normalize_language(self._prompt_choice(
                "Language / Bahasa",
                [f"{code} - {name}" for code, name in LANGUAGE_NAMES.items()],
                0,
            ).split(" ")[0])
        else:
            lang = normalize_language(options.language or (existing_cfg.app.ui_lang if existing_cfg else "en"))
        set_language(lang)

        # Step 0: Environment detection - always fatal, in every mode.
        print(f"\n{t('wizard.step.env')}")
        if sys.version_info < (3, 12):
            py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            message = t("wizard.env.python_bad", version=py_ver)
            print(f"x {message}")
            raise SetupError(message)

        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        print(f"  {t('wizard.env.python_ok', version=py_ver)}")
        print(f"  {t('wizard.env.os', os=f'{platform.system()} ({platform.release()})')}")
        print(f"  {t('wizard.env.project', path=os.getcwd())}")
        git_status = "installed" if shutil.which("git") else "missing"
        docker_status = "installed" if shutil.which("docker") else "missing"
        print(f"  Git: {git_status} | Docker: {docker_status}")
        print(f"  {t('wizard.env.ready')}")

        # Step 1: existing configuration
        merge_into_existing = False
        if os.path.exists(self.env_path):
            if options.force:
                os.remove(self.env_path)
            else:
                merge_into_existing = existing_cfg is not None

                if interactive:
                    print(f"\n  {t('wizard.existing.found', path=self.env_path)}")
                    action = self._prompt_choice(
                        t("wizard.existing.action"),
                        [
                            t("wizard.existing.edit"),
                            t("wizard.existing.keep"),
                            t("wizard.existing.reset"),
                        ],
                        0,
                    )
                    if action == t("wizard.existing.keep"):
                        return await self._validate_and_finish(existing_cfg)
                    if action == t("wizard.existing.reset"):
                        os.remove(self.env_path)
                        existing_cfg = None
                        merge_into_existing = False
                        print(f"  {t('wizard.existing.removed')}")

        env_dict: Dict[str, Any] = {}
        if merge_into_existing and existing_cfg is not None:
            # Carry forward only the keys the wizard manages; everything else in the
            # file is preserved verbatim by ConfigManager.save_env_file(merge=True).
            env_dict["TELEGRAM_BOT_TOKEN"] = existing_cfg.telegram.bot_token
            env_dict["TELEGRAM_ALLOWED_USERS"] = ",".join(str(u) for u in existing_cfg.telegram.allowed_users)

        env_dict["UI_LANG"] = lang

        base_env = dict(env_dict)

        # Step 2: Telegram
        print(f"\n{t('wizard.step.telegram')}")
        if options.bot_token:
            token = options.bot_token
            env_dict["TELEGRAM_BOT_TOKEN"] = token
            # In headless mode an unusable token fails the install instead of leaving a
            # half-configured deployment that dies on its first poll.
            await self._verify_telegram(token, optional_failure=False, quiet=headless)
        elif headless:
            raise SetupError(t("wizard.headless.missing", option="--bot-token"))
        else:
            env_dict["TELEGRAM_BOT_TOKEN"] = await self._prompt_telegram_token(existing_cfg)

        if options.allowed_users:
            env_dict["TELEGRAM_ALLOWED_USERS"] = options.allowed_users
        elif headless:
            env_dict["TELEGRAM_ALLOWED_USERS"] = base_env.get("TELEGRAM_ALLOWED_USERS", "")
        else:
            print(f"  {t('wizard.telegram.allowed_hint')}")
            default_allowed = base_env.get("TELEGRAM_ALLOWED_USERS", "")
            env_dict["TELEGRAM_ALLOWED_USERS"] = self._prompt(t("wizard.telegram.allowed"), default_allowed)

        # Step 3: AI provider + model
        print(f"\n{t('wizard.step.provider')}")
        provider = normalize_provider_name(options.provider) if options.provider else ""
        if provider and provider not in PROVIDER_CHOICES:
            raise SetupError(t(
                "wizard.headless.unknown_provider",
                provider=options.provider,
                options=", ".join(PROVIDER_CHOICES),
            ))
        if not provider:
            if headless:
                raise SetupError(t("wizard.headless.missing", option="--provider"))
            current = existing_cfg.ai.provider if existing_cfg and existing_cfg.ai.provider in PROVIDER_CHOICES else PROVIDER_CHOICES[0]
            provider = self._prompt_choice(t("wizard.provider.choose"), PROVIDER_CHOICES, PROVIDER_CHOICES.index(current))

        env_dict["AI_PROVIDER"] = provider
        base_url = options.base_url or self._prompt_base_url(provider, existing_cfg, interactive)
        if base_url:
            env_dict["AI_BASE_URL"] = base_url

        api_key = options.api_key or self._prompt_api_key(provider, existing_cfg, interactive)
        env_dict["AI_API_KEY"] = api_key

        model = options.model or await self._choose_model(provider, api_key, base_url, existing_cfg, interactive)
        env_dict["AI_MODEL"] = model

        if interactive:
            await self._verify_provider(provider, api_key, model, base_url)
        elif provider not in KEYLESS_PROVIDERS or api_key:
            await self._verify_provider(provider, api_key, model, base_url, strict=True)

        # Step 4: persona and preferences
        print(f"\n{t('wizard.step.persona')}")
        if headless:
            env_dict["AGENT_NAME"] = (existing_cfg.agent.name if existing_cfg else "Assistant")
            env_dict["AGENT_PERSONALITY"] = (existing_cfg.agent.personality if existing_cfg else "Professional")
            env_dict["AGENT_SYSTEM_PROMPT"] = (
                existing_cfg.agent.system_prompt if existing_cfg else
                "You are a helpful and accurate AI assistant. You answer queries concisely and use tools when needed."
            )
        else:
            env_dict["AGENT_NAME"] = self._prompt(t("wizard.persona.name"), existing_cfg.agent.name if existing_cfg else "Personal Assistant")
            env_dict["AGENT_PERSONALITY"] = self._prompt(t("wizard.persona.style"), existing_cfg.agent.personality if existing_cfg else "Direct & Helpful")
            env_dict["AGENT_SYSTEM_PROMPT"] = self._prompt(
                t("wizard.persona.system_prompt"),
                existing_cfg.agent.system_prompt if existing_cfg else
                "You are a helpful and accurate AI assistant. You answer queries concisely and use tools when needed.",
            )

        env_dict["TIMEZONE"] = self._resolve_timezone(options, existing_cfg, interactive)

        # Step 5: advanced settings
        advanced_choice = options.advanced
        if interactive and not advanced_choice:
            advanced_choice = self._prompt_bool(t("wizard.advanced.ask"), default=False)

        if advanced_choice:
            if interactive:
                print(f"\n{t('wizard.step.advanced')}")
            env_dict.update(self._advanced_settings(existing_cfg))
        else:
            env_dict.update(self._default_settings(existing_cfg))

        # Review
        self._print_review(env_dict, headless)

        if interactive and not self._prompt_bool(t("wizard.review.save", path=self.env_path), default=True):
            print(t("wizard.review.aborted"))
            return False

        saved_path = self.config_manager.save_env_file(env_dict, merge=True)
        print(f"\n{t('wizard.saved', path=saved_path)}")

        try:
            adapter = TelegramAdapter(bot_token=str(env_dict.get("TELEGRAM_BOT_TOKEN", "")))
            if await adapter.set_my_commands(build_bot_commands(lang)):
                print(f"  {t('wizard.commands_registered')}")
            await adapter.close()
        except Exception:
            pass

        self._ensure_gitignore()

        print(f"\n{t('wizard.done')}\n")
        print(t("wizard.next.start"))
        if platform.system() == "Windows":
            print("  PowerShell:      .\\scripts\\start.ps1")
            print("  Command prompt:  scripts\\start.bat")
        else:
            print("  Linux / macOS:   ./scripts/start")
            print("    (Windows:      .\\scripts\\start.ps1)")
        print("\n  Docker:  docker compose run --rm setup && docker compose up -d")
        print(f"\n{t('wizard.next.telegram')}\n")
        return True

    # -- run helpers -----------------------------------------------------------

    @staticmethod
    def _is_language(value: str) -> bool:
        from src.infrastructure.i18n import is_supported_language
        return is_supported_language(value)

    async def _verify_telegram(self, token: str, optional_failure: bool, quiet: bool = False) -> bool:
        """Confirm a bot token with Telegram. Returns whether verification succeeded."""
        if not quiet:
            print(f"  {t('wizard.telegram.verifying')}")
        try:
            adapter = TelegramAdapter(bot_token=token)
            bot_user = await adapter.get_me()
            await adapter.close()
            print(f"  {t('wizard.telegram.verified', username=bot_user.username, id=bot_user.id)}")
            return True
        except Exception as e:
            print(f"  x {t('wizard.telegram.failed', error=str(e))}")
            if optional_failure:
                return False
            raise SetupError(t("wizard.telegram.failed", error=str(e)))

    async def _prompt_telegram_token(self, existing_cfg: Optional[RootConfig]) -> str:
        """Ask for a bot token until it verifies, or the user chooses to continue anyway."""
        while True:
            default_token = existing_cfg.telegram.bot_token if existing_cfg else ""
            token = self._prompt_secret(t("wizard.telegram.token"), default_token)
            if not token:
                print(f"  ! {t('wizard.telegram.token_required')}")
                continue
            if await self._verify_telegram(token, optional_failure=True):
                return token
            if not self._prompt_bool(t("wizard.telegram.retry"), default=True):
                print(f"  {t('wizard.telegram.skipped')}")
                return token

    def _prompt_base_url(self, provider: str, existing_cfg: Optional[RootConfig], interactive: bool) -> str:
        """Resolve the provider base URL: asked only where a default is not built in."""
        if not interactive:
            return existing_cfg.ai.base_url if existing_cfg else ""
        if provider in PROVIDER_URL_DEFAULTS:
            default_url = existing_cfg.ai.base_url if (existing_cfg and existing_cfg.ai.base_url) else PROVIDER_URL_DEFAULTS[provider]
            return self._prompt_url(t("wizard.provider.url", provider=provider.upper()), default_url)
        if provider == "custom":
            return self._prompt_url(
                "Custom OpenAI-compatible base URL (e.g. http://localhost:8000/v1)",
                existing_cfg.ai.base_url if existing_cfg else "",
            )
        return existing_cfg.ai.base_url if existing_cfg else ""

    def _prompt_api_key(self, provider: str, existing_cfg: Optional[RootConfig], interactive: bool) -> str:
        """Resolve the provider API key, skipping the prompt for keyless providers."""
        if provider in KEYLESS_PROVIDERS:
            return ""
        if not interactive:
            return existing_cfg.ai.api_key if existing_cfg else ""
        default_key = existing_cfg.ai.api_key if existing_cfg else ""
        if provider == "9router":
            return self._prompt(t("wizard.provider.key_optional", provider=provider.upper()), default_key)
        return self._prompt_secret(t("wizard.provider.key", provider=provider.upper()), default_key)

    async def _choose_model(
        self,
        provider: str,
        api_key: str,
        base_url: str,
        existing_cfg: Optional[RootConfig],
        interactive: bool,
    ) -> str:
        """Pick a model: explicit flag wins, otherwise ask (live list) or take the first available."""
        if not interactive:
            if existing_cfg and existing_cfg.ai.model and normalize_provider_name(existing_cfg.ai.provider) == provider:
                return existing_cfg.ai.model
            discovered, _ = await fetch_available_models_ex(provider, api_key=api_key, base_url=base_url)
            clean = self._clean_models(discovered, provider)
            if clean:
                return clean[0]
            raise SetupError(t("wizard.headless.missing", option="--model"))

        print(f"\n  {t('wizard.provider.discovering', provider=provider.upper())}")
        discovered, live_ok = await fetch_available_models_ex(provider, api_key=api_key, base_url=base_url)
        clean_discovered = self._clean_models(discovered, provider)

        if not live_ok:
            print(f"  ! {t('wizard.provider.discovery_failed', provider=provider.upper())}")
            print(f"    {t('wizard.provider.discovery_fallback')}")
            print(f"    {t('wizard.provider.gateway', url=base_url or '(provider default)')}")

        model_options = clean_discovered + [t("wizard.provider.custom_model")]
        default_model = existing_cfg.ai.model if (existing_cfg and existing_cfg.ai.model in model_options) else model_options[0]
        source = t("wizard.provider.source_live") if live_ok else t("wizard.provider.source_offline")

        print(f"\n? {t('wizard.provider.choose_model', provider=provider.upper(), count=len(clean_discovered), source=source)}")
        for i, opt in enumerate(model_options, 1):
            marker = ">" if opt == default_model else " "
            print(f"  {marker} {i}. {opt}")

        raw_model_input = self._prompt(
            t("wizard.provider.model_prompt", count=len(model_options)),
            str(model_options.index(default_model) + 1),
        )
        if raw_model_input.isdigit() and 1 <= int(raw_model_input) <= len(model_options):
            chosen = model_options[int(raw_model_input) - 1]
            if chosen == t("wizard.provider.custom_model"):
                return self._prompt(t("wizard.provider.type_model"), default_model)
            return chosen
        return raw_model_input.strip()

    @staticmethod
    def _clean_models(discovered: List[str], provider: str) -> List[str]:
        """Strip the manual-entry sentinel and fall back to the bundled catalog."""
        clean = [m for m in discovered if m != CUSTOM_MODEL_SENTINEL and m != t("wizard.provider.custom_model")]
        if not clean:
            clean = [m for m in PROVIDER_MODELS_CATALOG.get(provider, []) if m]
        return clean

    async def _verify_provider(
        self,
        provider: str,
        api_key: str,
        model: str,
        base_url: str,
        strict: bool = False,
    ) -> bool:
        """Validate provider credentials, optionally failing hard."""
        print(f"  {t('wizard.provider.testing', provider=provider.upper(), model=model)}")
        try:
            prov_inst = create_ai_provider(provider_name=provider, api_key=api_key, model=model, base_url=base_url)
            valid = await prov_inst.validate_credentials()
        except Exception as e:
            print(f"  x {t('wizard.provider.invalid', provider=provider.upper())}")
            print(f"    {t('wizard.provider.detail', detail=str(e))}")
            if strict:
                raise SetupError(t("wizard.provider.invalid", provider=provider.upper()))
            return False

        if valid:
            print(f"  {t('wizard.provider.verified', provider=provider.upper(), model=model)}")
            return True

        print(f"  x {t('wizard.provider.invalid', provider=provider.upper())}")
        detail = getattr(prov_inst, "last_error", None)
        if detail:
            print(f"    {t('wizard.provider.detail', detail=detail)}")
        if strict:
            raise SetupError(t("wizard.provider.invalid", provider=provider.upper()))
        if not self._prompt_bool(t("wizard.provider.keep_anyway"), default=True):
            raise SetupError(t("wizard.provider.invalid", provider=provider.upper()))
        return False

    def _resolve_timezone(
        self,
        options: SetupOptions,
        existing_cfg: Optional[RootConfig],
        interactive: bool,
    ) -> str:
        """Resolve the scheduling timezone, validating IANA names."""
        current = (
            options.timezone
            or (existing_cfg.app.timezone if existing_cfg else "")
            or os.environ.get("TZ", "")
            or "UTC"
        )
        if not interactive:
            if options.timezone and not valid_timezone(options.timezone):
                raise SetupError(f"Unknown timezone '{options.timezone}'. Use an IANA name such as Asia/Jakarta.")
            return current

        print(f"  Reminders and schedules are interpreted in this timezone.")
        while True:
            value = self._prompt(t("wizard.prefs.timezone"), current)
            if valid_timezone(value):
                return value
            print(f"  ! Unknown timezone '{value}'. Use an IANA name, e.g. Asia/Jakarta, Europe/Berlin, UTC.")

    def _advanced_settings(self, existing_cfg: Optional[RootConfig]) -> Dict[str, Any]:
        """Collect the advanced integration and safety settings."""
        prior = existing_cfg.tools if existing_cfg else None
        prior_rate = existing_cfg.security.rate_limit_per_minute if existing_cfg else 15
        out: Dict[str, Any] = {}

        out["ENABLE_WEB_SEARCH"] = self._prompt_bool(
            t("wizard.adv.web_search"), default=(prior.web_search.enabled if prior else True)
        )

        enable_gh = self._prompt_bool(t("wizard.adv.github"), default=(prior.github.enabled if prior else True))
        out["ENABLE_GITHUB"] = enable_gh
        if enable_gh:
            out["GITHUB_TOKEN"] = self._prompt_secret(t("wizard.adv.github_token"), prior.github.token if prior else "")
            out["GITHUB_DEFAULT_REPO"] = self._prompt(t("wizard.adv.github_repo"), prior.github.default_repo if prior else "")
            out["GITHUB_ALLOW_WRITE"] = self._prompt_bool(
                t("wizard.adv.github_write"), default=(prior.github.allow_write if prior else False)
            )
        else:
            out["GITHUB_TOKEN"] = prior.github.token if prior else ""
            out["GITHUB_DEFAULT_REPO"] = prior.github.default_repo if prior else ""
            out["GITHUB_ALLOW_WRITE"] = False

        out["ENABLE_FILESYSTEM"] = self._prompt_bool(
            t("wizard.adv.filesystem"), default=(prior.filesystem.enabled if prior else True)
        )
        if out["ENABLE_FILESYSTEM"]:
            out["FILESYSTEM_ROOT_DIR"] = self._prompt(
                t("wizard.adv.filesystem_root"), prior.filesystem.root_dir if prior else "."
            )
            out["FILESYSTEM_READ_ONLY"] = self._prompt_bool(
                t("wizard.adv.filesystem_readonly"), default=False
            )

        out["ALLOW_SHELL"] = self._prompt_bool(t("wizard.adv.shell"), default=(prior.shell.enabled if prior else False))
        out["REQUIRE_CONFIRMATION_FOR_DESTRUCTIVE"] = self._prompt_bool(
            t("wizard.adv.confirm"), default=True
        )
        out["MEMORY_ENABLED"] = self._prompt_bool(
            t("wizard.adv.memory"), default=(existing_cfg.storage.memory_enabled if existing_cfg else True)
        )
        out["RATE_LIMIT_REQUESTS_PER_MINUTE"] = self._prompt_int(
            t("wizard.adv.rate_limit"), prior_rate
        )
        return out

    @staticmethod
    def _default_settings(existing_cfg: Optional[RootConfig]) -> Dict[str, Any]:
        """The safe defaults written when the user declines the advanced questions."""
        prior = existing_cfg.tools if existing_cfg else None
        return {
            "ENABLE_WEB_SEARCH": True,
            "ENABLE_GITHUB": True,
            "GITHUB_TOKEN": prior.github.token if prior else "",
            "GITHUB_DEFAULT_REPO": prior.github.default_repo if prior else "",
            "GITHUB_ALLOW_WRITE": False,
            "ENABLE_FILESYSTEM": True,
            # '.' plus read_only=False gives a usable coding workspace, matching .env.example.
            "FILESYSTEM_ROOT_DIR": prior.filesystem.root_dir if prior else ".",
            "FILESYSTEM_READ_ONLY": False,
            "ALLOW_SHELL": False,
            "REQUIRE_CONFIRMATION_FOR_DESTRUCTIVE": True,
            "MEMORY_ENABLED": True,
            "RATE_LIMIT_REQUESTS_PER_MINUTE": existing_cfg.security.rate_limit_per_minute if existing_cfg else 15,
        }

    @staticmethod
    def _print_review(env_dict: Dict[str, Any], headless: bool) -> None:
        """Print the resolved configuration for a final human check."""
        if headless:
            return
        enabled = t("wizard.review.enabled")
        disabled = t("wizard.review.disabled")
        print(f"\n{t('wizard.review.title')}")
        print("=" * 52)
        print(f"  {t('wizard.review.telegram', value=env_dict.get('TELEGRAM_ALLOWED_USERS') or t('wizard.review.open'))}")
        print(f"  {t('wizard.review.ai', provider=str(env_dict.get('AI_PROVIDER', '')).upper(), model=env_dict.get('AI_MODEL', ''))}")
        print(f"  {t('wizard.review.agent', name=env_dict.get('AGENT_NAME', ''))}")
        print(f"  {t('wizard.review.language', language=language_name(env_dict.get('UI_LANG', 'en')))}")
        print(f"  Timezone:   {env_dict.get('TIMEZONE', 'UTC')}")
        print(f"  {t('wizard.review.workspace', path=env_dict.get('FILESYSTEM_ROOT_DIR', './data'), readonly=env_dict.get('FILESYSTEM_READ_ONLY', True))}")
        print(f"  {t('wizard.review.memory', value=enabled if env_dict.get('MEMORY_ENABLED') else disabled)}")
        print(f"  {t('wizard.review.rate', value=env_dict.get('RATE_LIMIT_REQUESTS_PER_MINUTE', 15))}")
        print("=" * 52 + "\n")

    def _ensure_gitignore(self) -> None:
        """Ensure the generated secrets and runtime data stay out of version control."""
        required = [".env", "data/*.db", ".venv/"]
        if not os.path.exists(".gitignore"):
            with open(".gitignore", "w", encoding="utf-8") as f:
                f.write("\n".join(required) + "\n")
            return

        with open(".gitignore", "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

        missing = [entry for entry in required if entry not in lines]
        if missing:
            with open(".gitignore", "a", encoding="utf-8") as f:
                f.write("\n" + "\n".join(missing) + "\n")

    async def _validate_and_finish(self, config: RootConfig) -> bool:
        """Run quick validation for existing configuration."""
        from src.application.doctor import SystemDoctor
        print(f"\n{t('wizard.doctor.header')}")
        doc = SystemDoctor(env_path=self.env_path)
        passed, results = await doc.run_diagnostics()
        for r in results:
            mark = "OK " if r["status"] == "PASS" else ("-- " if r["status"] == "INFO" else "x  ")
            print(f"{mark} {r['name']}: {r['detail']}")
        return passed
