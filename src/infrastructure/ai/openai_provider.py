"""OpenAI and OpenAI-compatible API Provider implementation."""

import json
from typing import Any, Dict, List, Optional
import httpx
from src.domain.agent import Message, Role, ToolCall
from src.domain.provider import AIProvider, CompletionRequest, CompletionResponse, ProviderType, TokenUsage


class OpenAIProvider(AIProvider):
    """Handles communication with OpenAI API and compatible endpoints (OpenRouter, vLLM, Ollama-compat, etc.)."""

    def __init__(self, api_key: str, model: str = "gpt-4o", base_url: Optional[str] = None, timeout: float = 60.0):
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.timeout = timeout

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.OPENAI

    async def validate_credentials(self) -> bool:
        """Check API key validity by querying available models."""
        url = f"{self.base_url}/models"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url, headers=headers)
                return res.status_code == 200
        except Exception:
            return False

    async def generate_response(self, request: CompletionRequest) -> CompletionResponse:
        """Execute chat completion with tool calling support."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        openai_messages: List[Dict[str, Any]] = []
        if request.system_prompt:
            openai_messages.append({"role": "system", "content": request.system_prompt})

        for msg in request.messages:
            if msg.role == Role.USER:
                openai_messages.append({"role": "user", "content": msg.content})
            elif msg.role == Role.ASSISTANT:
                msg_dict: Dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
                if msg.tool_calls:
                    msg_dict["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments) if isinstance(tc.arguments, dict) else str(tc.arguments)
                            }
                        }
                        for tc in msg.tool_calls
                    ]
                openai_messages.append(msg_dict)
            elif msg.role == Role.TOOL:
                for tr in msg.tool_responses:
                    openai_messages.append({
                        "role": "tool",
                        "tool_call_id": tr.tool_call_id,
                        "content": tr.content
                    })

        payload: Dict[str, Any] = {
            "model": request.model or self.model,
            "messages": openai_messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
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
            payload["tool_choice"] = "auto"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            res = await client.post(url, headers=headers, json=payload)
            if res.status_code != 200:
                error_detail = res.text
                try:
                    error_json = res.json()
                    error_detail = error_json.get("error", {}).get("message", res.text)
                except Exception:
                    pass
                raise RuntimeError(f"OpenAI API Error [{res.status_code}]: {error_detail}")

            data = res.json()
            choice = data["choices"][0]
            message_data = choice["message"]
            content = message_data.get("content")

            tool_calls: List[ToolCall] = []
            if "tool_calls" in message_data and message_data["tool_calls"]:
                for tc in message_data["tool_calls"]:
                    fn = tc["function"]
                    args = {}
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except Exception:
                        args = {"raw": fn.get("arguments", "")}
                    tool_calls.append(ToolCall(id=tc["id"], name=fn["name"], arguments=args))

            usage_data = data.get("usage", {})
            usage = TokenUsage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0)
            )

            return CompletionResponse(content=content, tool_calls=tool_calls, usage=usage, raw_response=data)
