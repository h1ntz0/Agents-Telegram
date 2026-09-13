"""OpenRouter API Provider implementation (OpenAI-compatible wrapper)."""

from typing import Optional
from src.domain.provider import ProviderType
from src.infrastructure.ai.openai_provider import OpenAIProvider


class OpenRouterProvider(OpenAIProvider):
    """OpenRouter provider leveraging standardized OpenAI Chat format."""

    def __init__(
        self,
        api_key: str,
        model: str = "anthropic/claude-3.5-sonnet",
        base_url: Optional[str] = None,
        timeout: float = 60.0,
    ):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url or "https://openrouter.ai/api/v1",
            timeout=timeout,
        )

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.OPENROUTER
