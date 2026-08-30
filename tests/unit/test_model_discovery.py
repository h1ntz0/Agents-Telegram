"""Unit tests for live dynamic model discovery across providers."""

import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from src.infrastructure.ai.model_discovery import fetch_available_models


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
