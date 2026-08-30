"""DeepSeek API Provider implementation (OpenAI-compatible protocol)."""

from typing import Optional
from src.domain.provider import ProviderType
from src.infrastructure.ai.openai_provider import OpenAIProvider


class DeepSeekProvider(OpenAIProvider):
    """Handles communication with official DeepSeek API (deepseek-chat, deepseek-reasoner)."""

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        base_url: Optional[str] = None,
        timeout: float = 60.0
    ):
        target_url = (base_url or "https://api.deepseek.com/v1").rstrip("/")
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=target_url,
            timeout=timeout
        )

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.DEEPSEEK
