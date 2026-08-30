"""OpenCode Zen AI Provider implementation using OpenAI-compatible interface."""

from src.domain.provider import ProviderType
from src.infrastructure.ai.openai_provider import OpenAIProvider


class OpenCodeZenProvider(OpenAIProvider):
    """AI Provider for OpenCode Zen models."""

    def __init__(
        self,
        api_key: str,
        model: str = "muse-spark-1.2-contributor-free",
        base_url: str = "https://api.opencode.ai/v1",
        timeout: float = 60.0
    ):
        super().__init__(
            api_key=api_key or "opencode-zen-key",
            model=model or "muse-spark-1.2-contributor-free",
            base_url=base_url or "https://api.opencode.ai/v1",
            timeout=timeout
        )

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.OPENCODE_ZEN
