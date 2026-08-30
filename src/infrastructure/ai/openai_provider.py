"""OpenAI and OpenAI-compatible API Provider implementation with robust multi-format response handling."""

import json
from typing import Any, Dict, List, Optional
import httpx
from src.domain.agent import Message, Role, ToolCall
from src.domain.provider import AIProvider, CompletionRequest, CompletionResponse, ProviderType, TokenUsage


class OpenAIProvider(AIProvider):
    """Handles communication with OpenAI API and compatible endpoints (9router, DeepSeek, OpenRouter, vLLM, Ollama-compat, etc.)."""

    def __init__(self, api_key: str, model: str = "gpt-4o", base_url: Optional[str] = None, timeout: float = 60.0):
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.timeout = timeout

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.OPENAI

    async def validate_credentials(self) -> bool:
        """Check API key validity by querying available models or a ping completion."""
        url = f"{self.base_url}/models"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url, headers=headers)
                if res.status_code == 200:
                    return True
                # Fallback: test minimal chat completion
                chat_url = f"{self.base_url}/chat/completions"
                c_res = await client.post(
                    chat_url,
                    headers=headers,
                    json={"model": self.model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
                )
                return c_res.status_code == 200
        except Exception:
            return False

    def _extract_response_data(self, response_text: str) -> CompletionResponse:
        """Parse responses across standard JSON, hybrid SSE, and streaming SSE chunks."""
        cleaned_text = response_text.strip()

        # 1. Try direct JSON parsing (stripping any trailing data: [DONE] markers)
        candidate_json = cleaned_text
        if candidate_json.endswith("data: [DONE]"):
            candidate_json = candidate_json[:-len("data: [DONE]")].strip()

        try:
            data = json.loads(candidate_json)
            if isinstance(data, dict) and "choices" in data and len(data["choices"]) > 0:
                choice = data["choices"][0]

                # Format A: standard choices[0].message
                if "message" in choice:
                    msg_obj = choice["message"]
                    content = msg_obj.get("content")
                    # If content is empty or None, fallback to reasoning_content if present
                    if not content and "reasoning_content" in msg_obj:
                        content = msg_obj.get("reasoning_content")

                    tool_calls: List[ToolCall] = []
                    if "tool_calls" in msg_obj and msg_obj["tool_calls"]:
                        for tc in msg_obj["tool_calls"]:
                            fn = tc.get("function", {})
                            args = {}
                            try:
                                args = json.loads(fn.get("arguments", "{}"))
                            except Exception:
                                args = {"raw": fn.get("arguments", "")}
                            tool_calls.append(ToolCall(id=tc.get("id", "call"), name=fn.get("name", ""), arguments=args))

                    usage_data = data.get("usage", {})
                    usage = TokenUsage(
                        prompt_tokens=usage_data.get("prompt_tokens", 0),
                        completion_tokens=usage_data.get("completion_tokens", 0),
                        total_tokens=usage_data.get("total_tokens", 0)
                    )
                    return CompletionResponse(content=content, tool_calls=tool_calls, usage=usage, raw_response=data)

                # Format B: single chunk with choices[0].delta
                elif "delta" in choice:
                    delta_obj = choice["delta"]
                    content = delta_obj.get("content") or delta_obj.get("reasoning_content")
                    return CompletionResponse(content=content, tool_calls=[], raw_response=data)
        except Exception:
            pass

        # 2. Fallback: Parse multi-line Server-Sent Events (SSE) data stream
        accumulated_text = []
        tool_call_chunks: Dict[int, Dict[str, Any]] = {}
        usage = TokenUsage()
        last_raw_chunk = {}

        for raw_line in response_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            data_str = line
            if line.startswith("data:"):
                data_str = line[5:].strip()

            if data_str == "[DONE]":
                break

            try:
                chunk = json.loads(data_str)
                last_raw_chunk = chunk
                choices = chunk.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {}) or choices[0].get("message", {})
                    delta_content = delta.get("content")
                    if not delta_content and "reasoning_content" in delta:
                        delta_content = delta.get("reasoning_content")

                    if delta_content:
                        accumulated_text.append(delta_content)

                    if "tool_calls" in delta and delta["tool_calls"]:
                        for tc_delta in delta["tool_calls"]:
                            idx = tc_delta.get("index", 0)
                            if idx not in tool_call_chunks:
                                tool_call_chunks[idx] = {
                                    "id": tc_delta.get("id", f"call_{idx}"),
                                    "name": tc_delta.get("function", {}).get("name", ""),
                                    "arguments": ""
                                }
                            if "id" in tc_delta and tc_delta["id"]:
                                tool_call_chunks[idx]["id"] = tc_delta["id"]
                            if "function" in tc_delta:
                                fn = tc_delta["function"]
                                if "name" in fn and fn["name"]:
                                    tool_call_chunks[idx]["name"] = fn["name"]
                                if "arguments" in fn and fn["arguments"]:
                                    tool_call_chunks[idx]["arguments"] += fn["arguments"]

                if "usage" in chunk and chunk["usage"]:
                    u = chunk["usage"]
                    usage = TokenUsage(
                        prompt_tokens=u.get("prompt_tokens", 0),
                        completion_tokens=u.get("completion_tokens", 0),
                        total_tokens=u.get("total_tokens", 0)
                    )
            except Exception:
                continue

        final_tool_calls: List[ToolCall] = []
        for tc_data in tool_call_chunks.values():
            args_obj = {}
            if tc_data["arguments"]:
                try:
                    args_obj = json.loads(tc_data["arguments"])
                except Exception:
                    args_obj = {"raw": tc_data["arguments"]}
            final_tool_calls.append(ToolCall(
                id=tc_data["id"],
                name=tc_data["name"],
                arguments=args_obj
            ))

        full_content = "".join(accumulated_text).strip()
        return CompletionResponse(
            content=full_content if full_content else None,
            tool_calls=final_tool_calls,
            usage=usage,
            raw_response=last_raw_chunk
        )

    async def generate_response(self, request: CompletionRequest) -> CompletionResponse:
        """Execute chat completion with tool calling support across standard JSON and SSE streams."""
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
                if msg.metadata and "image_base64" in msg.metadata:
                    mime = msg.metadata.get("mime_type", "image/jpeg")
                    b64 = msg.metadata["image_base64"]
                    openai_messages.append({
                        "role": "user",
                        "content": [
                            {"type": "text", "text": msg.content},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime};base64,{b64}"
                                }
                            }
                        ]
                    })
                else:
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
                raise RuntimeError(f"AI Provider Error [{res.status_code}]: {error_detail}")

            return self._extract_response_data(res.text)
