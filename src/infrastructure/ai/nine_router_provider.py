"""9router Model Aggregator Provider implementation."""

from typing import Optional
from src.domain.provider import ProviderType
from src.infrastructure.ai.openai_provider import OpenAIProvider


class NineRouterProvider(OpenAIProvider):
    """Handles communication with local or remote 9router unified AI gateway."""

    def __init__(
        self,
        api_key: str = "",
        model: str = "claude-3-5-sonnet-20241022",
        base_url: Optional[str] = None,
        timeout: float = 60.0
    ):
        target_url = (base_url or "http://localhost:20128/v1").rstrip("/")
        super().__init__(
            api_key=api_key or "9router-local-key",
            model=model,
            base_url=target_url,
            timeout=timeout
        )

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.NINE_ROUTER
