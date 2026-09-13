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
    OPENCODE_ZEN = "opencode-zen"
    OPENCODE_GO = "opencode-go"
    OPENCODE = "opencode"
    CUSTOM = "custom"


PROVIDER_MODELS_CATALOG: Dict[str, List[str]] = {
    "9router": [
        "ag/gemini-3.8-flash-high",
        "ag/gemini-3.8-flash-medium",
        "ag/gemini-3.8-flash-low",
        "ag/gemini-3.8-flash",
        "ag/gemini-3.7-flash-high",
        "ag/gemini-3.7-flash-medium",
        "ag/gemini-3.7-flash-low",
        "ag/gemini-3.6-flash-high",
        "ag/gemini-3.6-flash-medium",
        "ag/gemini-3.6-flash-low",
        "ag/gemini-3.5-flash-high",
        "ag/gemini-3.5-flash-low",
        "ag/gemini-3.5-flash-extra-low",
        "ag/gemini-3-flash",
        "ag/gemini-3-flash-agent",
        "ag/gemini-pro-agent",
        "ag/gemini-3.1-pro-low",
        "ag/claude-sonnet-4-6",
        "ag/claude-opus-4-6-thinking",
        "ag/gpt-oss-120b-medium",
        "ds/deepseek-v4-pro",
        "ds/deepseek-v4-pro-max",
        "ds/deepseek-v4-pro-none",
        "ds/deepseek-v4-flash",
        "ds/deepseek-v4-flash-vision-exp",
        "ds/deepseek-chat",
        "ds/deepseek-reasoner",
        "ocg/deepseek-v4-pro",
        "ocg/deepseek-v4-flash",
        "ocg/deepseek-v4-flash-vision-exp",
        "ocg/deepseek-flash",
        "ocg/glm-5.3",
        "ocg/glm-5.3-flash",
        "ocg/glm-5.2",
        "ocg/glm-5.1",
        "ocg/kimi-k3",
        "ocg/kimi-k2.7-code",
        "ocg/kimi-k2.6",
        "ocg/minimax-m3",
        "ocg/minimax-m2.7",
        "ocg/minimax-m2.5",
        "ocg/qwen3.8-max",
        "ocg/qwen3.8-flash",
        "ocg/qwen3.7-max",
        "ocg/qwen3.7-plus",
        "ocg/qwen3.6-plus",
        "ocg/grok-4.6",
        "ocg/gpt-5.6-luna",
        "ocg/mimo-v2.5",
        "ocg/mimo-v2.5-pro",
        "ocg/longcat-2.0",
        "ocg/hy4-preview",
        "ocg/hy3",
        "ocg/muse-spark-1.3-contributor",
        "ocg/muse-spark-1.2-contributor",
        "openrouter/thinkingmachines/inkling:free",
        "openrouter/thinkingmachines/inkling-small:free",
        "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
        "openrouter/nvidia/nemotron-3.5-lightning:free",
        "sumo/deepseek-v4-flash-0731:netra",
        "dsm/deepseek-v4-flash-0731:netra",
        "my-combo",
        "aseli-combo",
        "fsd-BP",
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
    "opencode-zen": [
        "muse-spark-1.2-contributor-free",
        "oc/mimo-v2.5-free",
        "oc/big-pickle",
        "oc/hy3-free",
        "zen-code-1",
        "zen-instruct-preview",
    ],
    "opencode-go": [
        "go-code-fast",
        "go-flash",
        "go-sonnet",
        "go-chat",
        "go-coder-preview",
    ],
    "opencode": [
        "muse-spark-1.2-contributor-free",
        "oc/mimo-v2.5-free",
        "oc/big-pickle",
        "oc/hy3-free",
        "go-code-fast",
    ],
    "custom": []
}


# Canonical provider identifiers, in the order used by the /provider listing.
CANONICAL_PROVIDERS: List[str] = [
    "9router",
    "deepseek",
    "anthropic",
    "google",
    "openai",
    "openrouter",
    "ollama",
    "opencode-zen",
    "opencode-go",
    "custom",
]

# Providers that need no API key (local or keyless endpoints).
KEYLESS_PROVIDERS: set = {"ollama"}

# Alias -> canonical provider id.
PROVIDER_ALIASES: Dict[str, str] = {
    "9_router": "9router",
    "nine_router": "9router",
    "nine-router": "9router",
    "claude": "anthropic",
    "claude_code": "anthropic",
    "zen": "opencode-zen",
    "opencode zen": "opencode-zen",
    "opencode_zen": "opencode-zen",
    "go": "opencode-go",
    "opencode go": "opencode-go",
    "opencode_go": "opencode-go",
    "opencode": "opencode-zen",
}


def normalize_provider_name(name: str) -> str:
    """Return the canonical provider id for a user-supplied name (aliases resolved)."""
    cleaned = (name or "").lower().strip()
    return PROVIDER_ALIASES.get(cleaned, cleaned)


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
