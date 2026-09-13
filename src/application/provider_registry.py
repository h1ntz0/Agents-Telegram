"""Runtime provider resolution: per-provider credentials -> concrete AIProvider instances.

This is what lets the bot switch between providers (9router, OpenAI, Anthropic, Google,
DeepSeek, OpenRouter, Ollama, OpenCode, custom) at runtime without editing ``.env`` and
restarting the process.
"""

from typing import List

from src.application.config_manager import ProviderCredential, RootConfig
from src.domain.provider import (
    CANONICAL_PROVIDERS,
    KEYLESS_PROVIDERS,
    PROVIDER_MODELS_CATALOG,
    AIProvider,
    normalize_provider_name,
)
from src.infrastructure.ai.factory import create_ai_provider


class ProviderCredentialsMissing(ValueError):
    """Raised when a provider is selected but no usable credentials are configured."""

    def __init__(self, provider_name: str):
        self.provider_name = provider_name
        env_prefix = provider_name.upper().replace("-", "_")
        super().__init__(
            f"No credentials configured for provider '{provider_name}'. "
            f"Set {env_prefix}_API_KEY (and {env_prefix}_BASE_URL if needed) in your .env, "
            f"then restart the agent."
        )


def resolve_provider_credentials(provider_name: str, config: RootConfig) -> ProviderCredential:
    """Return the credentials to use for ``provider_name``.

    Precedence: explicit per-provider credentials -> generic ``AI_*`` values (only when the
    provider is the configured default) -> provider defaults (keyless providers such as Ollama).
    """
    canonical = normalize_provider_name(provider_name)

    cred = config.providers.get(canonical)
    if cred is not None and (cred.api_key or canonical in KEYLESS_PROVIDERS):
        return cred

    if canonical == normalize_provider_name(config.ai.provider):
        return ProviderCredential(
            api_key=config.ai.api_key,
            base_url=config.ai.base_url,
            model=config.ai.model,
        )

    if canonical in KEYLESS_PROVIDERS:
        return ProviderCredential()

    raise ProviderCredentialsMissing(canonical)


def provider_is_configured(provider_name: str, config: RootConfig) -> bool:
    """True when ``provider_name`` has usable credentials and can be switched to."""
    try:
        resolve_provider_credentials(provider_name, config)
        return True
    except ProviderCredentialsMissing:
        return False


def list_provider_names() -> List[str]:
    """Canonical provider ids in display order."""
    return list(CANONICAL_PROVIDERS)


def build_provider(provider_name: str, config: RootConfig) -> AIProvider:
    """Construct a ready-to-use AIProvider for ``provider_name`` using resolved credentials."""
    canonical = normalize_provider_name(provider_name)
    cred = resolve_provider_credentials(canonical, config)

    catalog = PROVIDER_MODELS_CATALOG.get(canonical) or []
    model = cred.model or (catalog[0] if catalog else "") or config.ai.model

    return create_ai_provider(
        provider_name=canonical,
        api_key=cred.api_key,
        model=model,
        base_url=cred.base_url,
        timeout=getattr(config.ai, "timeout_seconds", 60.0),
    )
