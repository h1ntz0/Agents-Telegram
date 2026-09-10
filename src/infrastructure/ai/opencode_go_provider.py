"""OpenCode Go AI Provider. Uses local gateway (9router) at http://127.0.0.1:20128/v1 by default."""

from src.domain.provider import ProviderType
from src.infrastructure.ai.openai_provider import OpenAIProvider

DEFAULT_OPENCODE_GATEWAY = "http://127.0.0.1:20128/v1"


class OpenCodeGoProvider(OpenAIProvider):
    """AI Provider for OpenCode Go models."""

    def __init__(
        self,
        api_key: str,
        model: str = "go-code-fast",
        base_url: str = "",
        timeout: float = 60.0
    ):
        effective_base = base_url.strip() if base_url.strip() else DEFAULT_OPENCODE_GATEWAY
        super().__init__(
            api_key=api_key or "opencode-go-key",
            model=model or "go-code-fast",
            base_url=effective_base,
            timeout=timeout
        )

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.OPENCODE_GO
