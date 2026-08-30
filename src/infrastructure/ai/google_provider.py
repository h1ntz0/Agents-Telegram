"""Google Gemini API Provider implementation."""

import json
from typing import Any, Dict, List, Optional
import httpx
from src.domain.agent import Message, Role, ToolCall
from src.domain.provider import AIProvider, CompletionRequest, CompletionResponse, ProviderType, TokenUsage


class GoogleProvider(AIProvider):
    """Handles communication with Google Gemini API."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash", timeout: float = 60.0):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        self.timeout = timeout

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.GOOGLE

    async def validate_credentials(self) -> bool:
        """Validate API key via model listing check."""
        url = f"{self.base_url}/models?key={self.api_key}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url)
                return res.status_code == 200
        except Exception:
            return False

    async def generate_response(self, request: CompletionRequest) -> CompletionResponse:
        """Execute chat completion with Gemini REST API."""
        model_name = request.model or self.model
        if not model_name.startswith("models/"):
            model_name = f"models/{model_name}"

        url = f"{self.base_url}/{model_name}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}

        contents: List[Dict[str, Any]] = []
        for msg in request.messages:
            role = "user" if msg.role in (Role.USER, Role.TOOL) else "model"
            parts = []
            if msg.metadata and "image_base64" in msg.metadata:
                mime = msg.metadata.get("mime_type", "image/jpeg")
                b64 = msg.metadata["image_base64"]
                parts.append({
                    "inline_data": {
                        "mime_type": mime,
                        "data": b64
                    }
                })
            if msg.content:
                parts.append({"text": msg.content})
            for tc in msg.tool_calls:
                parts.append({
                    "functionCall": {
                        "name": tc.name,
                        "args": tc.arguments
                    }
                })
            for tr in msg.tool_responses:
                parts.append({
                    "functionResponse": {
                        "name": tr.name,
                        "response": {"content": tr.content}
                    }
                })
            if parts:
                contents.append({"role": role, "parts": parts})

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens
            }
        }

        if request.system_prompt:
            payload["systemInstruction"] = {
                "parts": [{"text": request.system_prompt}]
            }

        if request.tools:
            function_declarations = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters
                }
                for tool in request.tools
            ]
            payload["tools"] = [{"functionDeclarations": function_declarations}]

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            res = await client.post(url, headers=headers, json=payload)
            if res.status_code != 200:
                raise RuntimeError(f"Google Gemini API Error [{res.status_code}]: {res.text}")

            data = res.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return CompletionResponse(content="", tool_calls=[])

            candidate_content = candidates[0].get("content", {})
            parts = candidate_content.get("parts", [])

            text_content = ""
            tool_calls: List[ToolCall] = []

            for part in parts:
                if "text" in part:
                    text_content += part["text"]
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    tool_calls.append(ToolCall(
                        id=fc.get("name", "call"),
                        name=fc.get("name", ""),
                        arguments=fc.get("args", {})
                    ))

            usage_metadata = data.get("usageMetadata", {})
            usage = TokenUsage(
                prompt_tokens=usage_metadata.get("promptTokenCount", 0),
                completion_tokens=usage_metadata.get("candidatesTokenCount", 0),
                total_tokens=usage_metadata.get("totalTokenCount", 0)
            )

            return CompletionResponse(
                content=text_content if text_content else None,
                tool_calls=tool_calls,
                usage=usage,
                raw_response=data
            )
