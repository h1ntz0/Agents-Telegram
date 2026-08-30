"""Ollama Local Model Provider implementation."""

import json
from typing import Any, Dict, List, Optional
import httpx
from src.domain.agent import Message, Role, ToolCall
from src.domain.provider import AIProvider, CompletionRequest, CompletionResponse, ProviderType, TokenUsage


class OllamaProvider(AIProvider):
    """Handles communication with local Ollama API instance."""

    def __init__(self, model: str = "llama3.2", base_url: Optional[str] = None, timeout: float = 60.0):
        self.model = model
        self.base_url = (base_url or "http://localhost:11434").rstrip("/")
        self.timeout = timeout

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.OLLAMA

    async def validate_credentials(self) -> bool:
        """Check if local Ollama daemon is reachable and responding."""
        url = f"{self.base_url}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(url)
                return res.status_code == 200
        except Exception:
            return False

    async def generate_response(self, request: CompletionRequest) -> CompletionResponse:
        """Execute chat completion with Ollama API."""
        url = f"{self.base_url}/api/chat"

        ollama_messages: List[Dict[str, Any]] = []
        if request.system_prompt:
            ollama_messages.append({"role": "system", "content": request.system_prompt})

        for msg in request.messages:
            role = "user" if msg.role == Role.USER else ("assistant" if msg.role == Role.ASSISTANT else "tool")
            ollama_messages.append({"role": role, "content": msg.content or ""})

        payload: Dict[str, Any] = {
            "model": request.model or self.model,
            "messages": ollama_messages,
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            }
        }

        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters
                    }
                }
                for tool in request.tools
            ]

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            res = await client.post(url, json=payload)
            if res.status_code != 200:
                raise RuntimeError(f"Ollama API Error [{res.status_code}]: {res.text}")

            data = res.json()
            message_data = data.get("message", {})
            content = message_data.get("content")

            tool_calls: List[ToolCall] = []
            if "tool_calls" in message_data and message_data["tool_calls"]:
                for tc in message_data["tool_calls"]:
                    fn = tc.get("function", {})
                    tool_calls.append(ToolCall(
                        id=fn.get("name", "call"),
                        name=fn.get("name", ""),
                        arguments=fn.get("arguments", {})
                    ))

            prompt_tokens = data.get("prompt_eval_count", 0)
            completion_tokens = data.get("eval_count", 0)

            return CompletionResponse(
                content=content if content else None,
                tool_calls=tool_calls,
                usage=TokenUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens
                ),
                raw_response=data
            )
