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
