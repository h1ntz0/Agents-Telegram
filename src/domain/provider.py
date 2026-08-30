"""Domain interface and contracts for AI Model Providers."""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from src.domain.agent import Message, ToolCall
from src.domain.tool import ToolDefinition


class ProviderType(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    OPENROUTER = "openrouter"
    OLLAMA = "ollama"
    CUSTOM = "custom"


@dataclass
class CompletionRequest:
    messages: List[Message]
    system_prompt: str = ""
    tools: List[ToolDefinition] = field(default_factory=list)
    model: str = ""
    temperature: float = 0.2
    max_tokens: int = 2048


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class CompletionResponse:
    content: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    raw_response: Dict[str, Any] = field(default_factory=dict)


class AIProvider(ABC):
    @property
    @abstractmethod
    def provider_type(self) -> ProviderType:
        """Return the provider identifier."""
        pass

    @abstractmethod
    async def generate_response(self, request: CompletionRequest) -> CompletionResponse:
        """Generate response from LLM given conversation context and tools."""
        pass

    @abstractmethod
    async def validate_credentials(self) -> bool:
        """Test if the configured API key and endpoint are operational."""
        pass
