"""Factory for creating AI Provider instances from application configuration."""

from src.domain.provider import AIProvider, ProviderType
from src.infrastructure.ai.anthropic_provider import AnthropicProvider
from src.infrastructure.ai.deepseek_provider import DeepSeekProvider
from src.infrastructure.ai.google_provider import GoogleProvider
from src.infrastructure.ai.nine_router_provider import NineRouterProvider
from src.infrastructure.ai.ollama_provider import OllamaProvider
from src.infrastructure.ai.opencode_go_provider import OpenCodeGoProvider
from src.infrastructure.ai.opencode_zen_provider import OpenCodeZenProvider
from src.infrastructure.ai.openai_provider import OpenAIProvider
from src.infrastructure.ai.openrouter_provider import OpenRouterProvider


def create_ai_provider(
    provider_name: str,
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    timeout: float = 60.0,
) -> AIProvider:
    """Instantiate appropriate AI Provider implementation based on provider_name."""
    name = (provider_name or "").lower().strip()

    if name in (ProviderType.NINE_ROUTER.value, "9_router"):
        return NineRouterProvider(
            api_key=api_key or "9router-local",
            model=model or "claude-3-5-sonnet-20241022",
            base_url=base_url if base_url else "http://localhost:20128/v1",
            timeout=timeout
        )
    elif name == ProviderType.DEEPSEEK.value:
        return DeepSeekProvider(
            api_key=api_key,
            model=model or "deepseek-chat",
            base_url=base_url if base_url else "https://api.deepseek.com/v1",
            timeout=timeout
        )
    elif name in (ProviderType.ANTHROPIC.value, "claude", "claude_code"):
        return AnthropicProvider(
            api_key=api_key,
            model=model or "claude-3-5-sonnet-20241022",
            timeout=timeout
        )
    elif name == ProviderType.GOOGLE.value:
        return GoogleProvider(
            api_key=api_key,
            model=model or "gemini-2.0-flash",
            timeout=timeout
        )
    elif name == ProviderType.OPENROUTER.value:
        return OpenRouterProvider(
            api_key=api_key,
            model=model or "anthropic/claude-3.5-sonnet",
            timeout=timeout
        )
    elif name == ProviderType.OLLAMA.value:
        return OllamaProvider(
            model=model or "llama3.2",
            base_url=base_url if base_url else "http://localhost:11434",
            timeout=timeout
        )
    elif name in (ProviderType.OPENCODE_ZEN.value, "opencode_zen", "opencode zen", "zen", "opencode"):
        return OpenCodeZenProvider(
            api_key=api_key or "opencode-local-key",
            model=model or "muse-spark-1.2-contributor-free",
            base_url=base_url,
            timeout=timeout
        )
    elif name in (ProviderType.OPENCODE_GO.value, "opencode_go", "opencode go", "go"):
        return OpenCodeGoProvider(
            api_key=api_key or "opencode-local-key",
            model=model or "go-code-fast",
            base_url=base_url,
            timeout=timeout
        )
    elif name in (ProviderType.OPENAI.value, "custom"):
        return OpenAIProvider(
            api_key=api_key,
            model=model or "gpt-4o",
            base_url=base_url if base_url else None,
            timeout=timeout
        )
    else:
        raise ValueError(
            f"Unsupported AI Provider '{provider_name}'. "
            f"Supported providers: {', '.join([p.value for p in ProviderType])}"
        )
