"""Anthropic Claude API Provider implementation."""

import json
from typing import Any, Dict, List, Optional
import httpx
from src.domain.agent import Message, Role, ToolCall
from src.domain.provider import AIProvider, CompletionRequest, CompletionResponse, ProviderType, TokenUsage


class AnthropicProvider(AIProvider):
    """Handles communication with Anthropic Messages API."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-5-sonnet-20241022",
        base_url: Optional[str] = None,
        timeout: float = 60.0,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or "https://api.anthropic.com/v1").rstrip("/")
        self.timeout = timeout

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.ANTHROPIC

    async def validate_credentials(self) -> bool:
        """Validate API key via minimal completion check."""
        url = f"{self.base_url}/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        payload = {
            "model": self.model,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "ping"}]
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, headers=headers, json=payload)
                return res.status_code == 200
        except Exception:
            return False

    async def generate_response(self, request: CompletionRequest) -> CompletionResponse:
        """Execute chat completion with Anthropic API."""
        url = f"{self.base_url}/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        anthropic_messages: List[Dict[str, Any]] = []
        for msg in request.messages:
            if msg.role == Role.USER:
                if msg.metadata and "image_base64" in msg.metadata:
                    mime = msg.metadata.get("mime_type", "image/jpeg")
                    b64 = msg.metadata["image_base64"]
                    anthropic_messages.append({
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": mime,
                                    "data": b64
                                }
                            },
                            {"type": "text", "text": msg.content}
                        ]
                    })
                else:
                    anthropic_messages.append({"role": "user", "content": msg.content})
            elif msg.role == Role.ASSISTANT:
                content_blocks: List[Dict[str, Any]] = []
                if msg.content:
                    content_blocks.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments
                    })
                anthropic_messages.append({"role": "assistant", "content": content_blocks})
            elif msg.role == Role.TOOL:
                content_blocks = []
                for tr in msg.tool_responses:
                    content_blocks.append({
                        "type": "tool_result",
                        "tool_use_id": tr.tool_call_id,
                        "content": tr.content,
                        "is_error": tr.is_error
                    })
                anthropic_messages.append({"role": "user", "content": content_blocks})

        payload: Dict[str, Any] = {
            "model": request.model or self.model,
            "max_tokens": request.max_tokens,
            "messages": anthropic_messages,
            "temperature": request.temperature
        }
        if request.system_prompt:
            payload["system"] = request.system_prompt

        if request.tools:
            payload["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters
                }
                for tool in request.tools
            ]

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            res = await client.post(url, headers=headers, json=payload)
            if res.status_code != 200:
                raise RuntimeError(f"Anthropic API Error [{res.status_code}]: {res.text}")

            data = res.json()
            content_text = ""
            tool_calls: List[ToolCall] = []

            for block in data.get("content", []):
                if block.get("type") == "text":
                    content_text += block.get("text", "")
                elif block.get("type") == "tool_use":
                    tool_calls.append(ToolCall(
                        id=block["id"],
                        name=block["name"],
                        arguments=block.get("input", {})
                    ))

            usage_data = data.get("usage", {})
            usage = TokenUsage(
                prompt_tokens=usage_data.get("input_tokens", 0),
                completion_tokens=usage_data.get("output_tokens", 0),
                total_tokens=usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0)
            )

            return CompletionResponse(
                content=content_text if content_text else None,
                tool_calls=tool_calls,
                usage=usage,
                raw_response=data
            )
