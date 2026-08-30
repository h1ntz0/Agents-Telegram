"""Domain interface, contracts, and model catalog for AI Providers."""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from src.domain.agent import Message, ToolCall
from src.domain.tool import ToolDefinition


class ProviderType(str, Enum):
    NINE_ROUTER = "9router"
    DEEPSEEK = "deepseek"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    OPENAI = "openai"
    OPENROUTER = "openrouter"
    OLLAMA = "ollama"
    CUSTOM = "custom"


PROVIDER_MODELS_CATALOG: Dict[str, List[str]] = {
    "9router": [
        "ag/gemini-3.7-flash-high",
        "ds/deepseek-v4-flash",
        "ds/deepseek-chat",
        "ds/deepseek-reasoner",
        "ag/claude-sonnet-4-6",
        "cx/gpt-5.6-sol",
        "cx/gpt-5.4",
        "ag/gpt-oss-120b-medium",
    ],
    "deepseek": [
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-coder",
    ],
    "anthropic": [
        "claude-3-7-sonnet-20250219",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
    ],
    "google": [
        "gemini-2.0-flash",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
    ],
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
        "o1",
        "o3-mini",
    ],
    "openrouter": [
        "anthropic/claude-3.5-sonnet",
        "deepseek/deepseek-r1",
        "deepseek/deepseek-chat",
        "openai/gpt-4o",
        "google/gemini-2.0-flash-001",
        "meta-llama/llama-3.3-70b-instruct",
    ],
    "ollama": [
        "llama3.2",
        "deepseek-r1",
        "qwen2.5-coder",
        "mistral",
    ],
    "custom": []
}


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
        """Generate response from LLM given conversation context, tools, and exact requested model."""
        pass

    @abstractmethod
    async def validate_credentials(self) -> bool:
        """Test if the configured API key and endpoint are operational."""
        pass
