"""OpenCode Go AI Provider implementation using OpenAI-compatible interface."""

from src.domain.provider import ProviderType
from src.infrastructure.ai.openai_provider import OpenAIProvider


class OpenCodeGoProvider(OpenAIProvider):
    """AI Provider for OpenCode Go models."""

    def __init__(
        self,
        api_key: str,
        model: str = "go-code-fast",
        base_url: str = "https://go.opencode.ai/v1",
        timeout: float = 60.0
    ):
        super().__init__(
            api_key=api_key or "opencode-go-key",
            model=model or "go-code-fast",
            base_url=base_url or "https://go.opencode.ai/v1",
            timeout=timeout
        )

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.OPENCODE_GO
