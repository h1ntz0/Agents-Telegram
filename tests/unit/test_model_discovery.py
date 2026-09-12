"""Unit tests for live dynamic model discovery across providers."""

import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from src.infrastructure.ai.model_discovery import (
    fetch_available_models,
    fetch_available_models_ex,
    normalize_base_url,
)


@pytest.mark.asyncio
async def test_fetch_openai_compatible_models():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"id": "model-alpha"},
            {"id": "model-beta"},
            {"id": "model-alpha"}  # Duplicate to test deduplication
        ]
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        models = await fetch_available_models(
            provider_name="9router",
            api_key="test-key",
            base_url="http://localhost:20128/v1"
        )
        assert models == ["model-alpha", "model-beta"]


@pytest.mark.asyncio
async def test_fetch_ollama_models():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "models": [
            {"name": "llama3.2:latest"},
            {"name": "deepseek-r1:latest"}
        ]
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        models = await fetch_available_models(
            provider_name="ollama",
            base_url="http://localhost:11434"
        )
        assert models == ["llama3.2:latest", "deepseek-r1:latest"]


@pytest.mark.asyncio
async def test_fetch_google_gemini_models():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "models": [
            {"name": "models/gemini-2.0-flash"},
            {"name": "models/text-embedding-004"},  # Should be filtered out
            {"name": "models/gemini-1.5-pro"}
        ]
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        models = await fetch_available_models(
            provider_name="google",
            api_key="gemini-key"
        )
        assert models == ["gemini-2.0-flash", "gemini-1.5-pro"]


@pytest.mark.asyncio
async def test_fetch_fallback_on_network_error():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=Exception("Connection failed")):
        models = await fetch_available_models(
            provider_name="deepseek",
            api_key="test-key",
            base_url="https://api.deepseek.com/v1"
        )
        assert "deepseek-chat" in models
        assert "deepseek-reasoner" in models


def test_normalize_base_url():
    assert normalize_base_url("http://localhost:20128/v1") == "http://localhost:20128/v1"
    assert normalize_base_url("https://api.deepseek.com/v1/") == "https://api.deepseek.com/v1"
    assert normalize_base_url("localhost:20128/v1") == "http://localhost:20128/v1"
    assert normalize_base_url("127.0.0.1:20128/v1") == "http://127.0.0.1:20128/v1"
    assert normalize_base_url("sk-REVOKED-NINE-ROUTER-KEY-0001") is None
    assert normalize_base_url("") is None
    assert normalize_base_url("not a url") is None
    assert normalize_base_url("ftp://example.com") is None


@pytest.mark.asyncio
async def test_api_key_as_base_url_does_not_break_discovery():
    """Regression: an API key pasted into the URL field must not produce a malformed request."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": [{"id": "ag/gemini-3.8-flash-high"}]}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        models, live_ok = await fetch_available_models_ex(
            provider_name="9router",
            api_key="123456",
            base_url="sk-REVOKED-NINE-ROUTER-KEY-0001",
        )

    called_url = mock_get.call_args[0][0]
    assert called_url == "http://localhost:20128/v1/models"
    assert live_ok is True
    assert models == ["ag/gemini-3.8-flash-high"]


@pytest.mark.asyncio
async def test_live_ok_false_on_network_error():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=Exception("boom")):
        models, live_ok = await fetch_available_models_ex(
            provider_name="9router", api_key="k", base_url="http://localhost:20128/v1"
        )
    assert live_ok is False
    assert models  # fallback catalog is non-empty
