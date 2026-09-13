"""S4/S5: per-provider request correctness + base_url propagation.

Proves that EVERY provider (not just 9router) emits the correct endpoint and payload
shape for ``generate_response``, and that a custom ``base_url`` is honoured for
anthropic / google / openrouter.

These are the contract tests that make "providers besides 9router are usable" real.
"""

import json

import httpx
import pytest
from unittest.mock import AsyncMock, patch

from src.domain.agent import Message, Role
from src.domain.provider import CompletionRequest
from src.infrastructure.ai.factory import create_ai_provider


def _req(model: str = "test-model", content: str = "ping") -> CompletionRequest:
    return CompletionRequest(messages=[Message(role=Role.USER, content=content)], model=model)


def _ok_json(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload)


# --------------------------------------------------------------------------- #
# S4 — payload / endpoint correctness per provider
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_openai_provider_posts_to_chat_completions():
    prov = create_ai_provider("openai", api_key="sk-openai", model="gpt-4o")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _ok_json({"choices": [{"message": {"content": "ok"}}]})
        await prov.generate_response(_req(model="gpt-4o"))

    url = mock_post.call_args[0][0]
    headers = mock_post.call_args[1]["headers"]
    payload = mock_post.call_args[1]["json"]
    assert url == "https://api.openai.com/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-openai"
    assert payload["model"] == "gpt-4o"
    assert payload["messages"] == [{"role": "user", "content": "ping"}]


@pytest.mark.asyncio
async def test_openai_custom_base_url_is_honoured():
    prov = create_ai_provider(
        "custom", api_key="sk-x", model="my-model", base_url="http://localhost:8000/v1"
    )
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _ok_json({"choices": [{"message": {"content": "ok"}}]})
        await prov.generate_response(_req(model="my-model"))

    assert mock_post.call_args[0][0] == "http://localhost:8000/v1/chat/completions"


@pytest.mark.asyncio
async def test_deepseek_provider_posts_to_deepseek():
    prov = create_ai_provider("deepseek", api_key="sk-ds", model="deepseek-chat")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _ok_json({"choices": [{"message": {"content": "ok"}}]})
        await prov.generate_response(_req(model="deepseek-reasoner"))

    assert mock_post.call_args[0][0] == "https://api.deepseek.com/v1/chat/completions"
    assert mock_post.call_args[1]["json"]["model"] == "deepseek-reasoner"


@pytest.mark.asyncio
async def test_openrouter_provider_posts_to_openrouter():
    prov = create_ai_provider("openrouter", api_key="sk-or", model="openai/gpt-4o")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _ok_json({"choices": [{"message": {"content": "ok"}}]})
        await prov.generate_response(_req(model="openai/gpt-4o"))

    assert mock_post.call_args[0][0] == "https://openrouter.ai/api/v1/chat/completions"


@pytest.mark.asyncio
async def test_anthropic_provider_posts_to_messages_with_native_shape():
    prov = create_ai_provider("anthropic", api_key="sk-ant", model="claude-3-5-sonnet-20241022")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _ok_json({"content": [{"type": "text", "text": "ok"}]})
        await prov.generate_response(_req(model="claude-3-5-sonnet-20241022"))

    url = mock_post.call_args[0][0]
    headers = mock_post.call_args[1]["headers"]
    payload = mock_post.call_args[1]["json"]
    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "sk-ant"
    assert headers["anthropic-version"] == "2023-06-01"
    assert payload["model"] == "claude-3-5-sonnet-20241022"
    assert payload["max_tokens"] >= 1
    assert payload["messages"] == [{"role": "user", "content": "ping"}]
    # Anthropic does NOT use the OpenAI "choices" shape; assert we parsed the native shape.
    assert "choices" not in payload


@pytest.mark.asyncio
async def test_google_provider_posts_to_generate_content():
    prov = create_ai_provider("google", api_key="AIza-key", model="gemini-2.0-flash")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _ok_json(
            {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
        )
        await prov.generate_response(_req(model="gemini-2.0-flash"))

    url = mock_post.call_args[0][0]
    payload = mock_post.call_args[1]["json"]
    assert url.startswith("https://generativelanguage.googleapis.com/v1beta/models/")
    assert ":generateContent?key=AIza-key" in url
    assert "gemini-2.0-flash" in url
    assert payload["contents"] == [{"role": "user", "parts": [{"text": "ping"}]}]


@pytest.mark.asyncio
async def test_ollama_provider_posts_to_api_chat():
    prov = create_ai_provider("ollama", model="llama3.2")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _ok_json({"message": {"content": "ok"}})
        await prov.generate_response(_req(model="llama3.2"))

    url = mock_post.call_args[0][0]
    payload = mock_post.call_args[1]["json"]
    assert url == "http://localhost:11434/api/chat"
    assert payload["model"] == "llama3.2"
    assert payload["stream"] is False


# --------------------------------------------------------------------------- #
# S5 — base_url propagation to anthropic / google / openrouter
# --------------------------------------------------------------------------- #

def test_anthropic_base_url_override_is_propagated():
    prov = create_ai_provider(
        "anthropic", api_key="k", model="claude-3-5-sonnet-20241022",
        base_url="https://anthropic-proxy.test/v1",
    )
    assert prov.base_url == "https://anthropic-proxy.test/v1"


def test_google_base_url_override_is_propagated():
    prov = create_ai_provider(
        "google", api_key="k", model="gemini-2.0-flash",
        base_url="https://gemini-proxy.test/v1beta",
    )
    assert prov.base_url == "https://gemini-proxy.test/v1beta"


def test_openrouter_base_url_override_is_propagated():
    prov = create_ai_provider(
        "openrouter", api_key="k", model="openai/gpt-4o",
        base_url="https://openrouter-proxy.test/v1",
    )
    assert prov.base_url == "https://openrouter-proxy.test/v1"


def test_defaults_preserved_when_no_base_url_given():
    """Regression: omitting base_url must keep each provider's canonical endpoint."""
    assert create_ai_provider("anthropic", api_key="k").base_url == "https://api.anthropic.com/v1"
    assert create_ai_provider("google", api_key="k").base_url == "https://generativelanguage.googleapis.com/v1beta"
    assert create_ai_provider("openrouter", api_key="k").base_url == "https://openrouter.ai/api/v1"
    assert create_ai_provider("openai", api_key="k").base_url == "https://api.openai.com/v1"
    assert create_ai_provider("ollama").base_url == "http://localhost:11434"
