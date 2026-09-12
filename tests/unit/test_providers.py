"""Unit tests for AI provider factory and credential validation abstractions."""

import pytest
from src.infrastructure.ai.factory import create_ai_provider
from src.infrastructure.ai.openai_provider import OpenAIProvider
from src.infrastructure.ai.anthropic_provider import AnthropicProvider
from src.infrastructure.ai.google_provider import GoogleProvider
from src.infrastructure.ai.ollama_provider import OllamaProvider


def test_create_ai_provider_factory():
    openai_prov = create_ai_provider("openai", api_key="sk-test", model="gpt-4o")
    assert isinstance(openai_prov, OpenAIProvider)

    anthropic_prov = create_ai_provider("anthropic", api_key="sk-ant-test", model="claude-3-5-sonnet")
    assert isinstance(anthropic_prov, AnthropicProvider)

    google_prov = create_ai_provider("google", api_key="AIzaSyTest", model="gemini-2.0-flash")
    assert isinstance(google_prov, GoogleProvider)

    ollama_prov = create_ai_provider("ollama", model="llama3.2")
    assert isinstance(ollama_prov, OllamaProvider)


def test_unsupported_provider_raises_error():
    with pytest.raises(ValueError) as exc:
        create_ai_provider("unknown_provider")
    assert "Unsupported AI Provider" in str(exc.value)


@pytest.mark.asyncio
async def test_providers_use_exact_requested_model():
    from src.domain.agent import Message, Role
    from src.domain.provider import CompletionRequest
    from unittest.mock import patch, AsyncMock
    import httpx

    req = CompletionRequest(
        messages=[Message(role=Role.USER, content="ping")],
        model="ag/gemini-3.7-flash-high"
    )

    # 1. 9router Provider
    nine_router = create_ai_provider("9router", model="claude-3-5-sonnet-20241022")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}
        })
        await nine_router.generate_response(req)
        sent_payload = mock_post.call_args[1]["json"]
        assert sent_payload["model"] == "ag/gemini-3.7-flash-high"

    # 2. DeepSeek Provider
    deepseek = create_ai_provider("deepseek", api_key="sk-test", model="deepseek-chat")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}
        })
        await deepseek.generate_response(CompletionRequest(
            messages=[Message(role=Role.USER, content="ping")],
            model="deepseek-reasoner"
        ))
        sent_payload = mock_post.call_args[1]["json"]
        assert sent_payload["model"] == "deepseek-reasoner"


@pytest.mark.asyncio
async def test_html_404_error_explains_missing_v1_suffix():
    """Regression: a web-UI HTML 404 must give an actionable error, not a raw HTML dump."""
    import httpx as _httpx
    from unittest.mock import AsyncMock, patch
    from src.domain.agent import Message, Role
    from src.domain.provider import CompletionRequest

    provider = OpenAIProvider(api_key="k", model="m", base_url="http://localhost:20128")
    html = "<!DOCTYPE html><html><head><title>404</title></head></html>"
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _httpx.Response(404, text=html)
        with pytest.raises(RuntimeError) as exc:
            await provider.generate_response(CompletionRequest(
                messages=[Message(role=Role.USER, content="hi")], model="m"
            ))
    msg = str(exc.value)
    assert "404" in msg
    assert "HTML" in msg
    assert "/v1" in msg
    assert "<!DOCTYPE" not in msg  # never dump the raw page into chat
    assert "404" in msg
    assert "HTML" in msg
    assert "/v1" in msg


@pytest.mark.asyncio
async def test_validate_credentials_records_actionable_error():
    import httpx as _httpx
    from unittest.mock import AsyncMock, patch

    provider = OpenAIProvider(api_key="k", model="m", base_url="http://localhost:20128")
    html = "<!DOCTYPE html><html></html>"
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_get.return_value = _httpx.Response(404, text=html)
        mock_post.return_value = _httpx.Response(404, text=html)
        ok = await provider.validate_credentials()
    assert ok is False
    assert provider.last_error
    assert "/v1" in provider.last_error
