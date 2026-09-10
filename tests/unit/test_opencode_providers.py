"""Unit tests for OpenCode Zen and OpenCode Go AI Providers."""

import pytest
from src.domain.agent import Message, Role
from src.domain.provider import CompletionRequest, ProviderType, PROVIDER_MODELS_CATALOG
from src.infrastructure.ai.factory import create_ai_provider
from src.infrastructure.ai.opencode_zen_provider import OpenCodeZenProvider
from src.infrastructure.ai.opencode_go_provider import OpenCodeGoProvider


def test_create_opencode_zen_provider():
    provider = create_ai_provider(
        provider_name="opencode-zen",
        api_key="test-zen-key",
        model="muse-spark-1.2-contributor-free"
    )
    assert isinstance(provider, OpenCodeZenProvider)
    assert provider.provider_type == ProviderType.OPENCODE_ZEN
    assert provider.base_url == "http://127.0.0.1:20128/v1"
    assert provider.model == "muse-spark-1.2-contributor-free"


def test_create_opencode_go_provider():
    provider = create_ai_provider(
        provider_name="opencode-go",
        api_key="test-go-key",
        model="go-code-fast"
    )
    assert isinstance(provider, OpenCodeGoProvider)
    assert provider.provider_type == ProviderType.OPENCODE_GO
    assert provider.base_url == "http://127.0.0.1:20128/v1"
    assert provider.model == "go-code-fast"


def test_opencode_base_url_override():
    zen = create_ai_provider(provider_name="opencode-zen", api_key="k", base_url="http://example.test/v1")
    assert zen.base_url == "http://example.test/v1"

    go = create_ai_provider(provider_name="opencode-go", api_key="k", base_url="http://example.test/v2")
    assert go.base_url == "http://example.test/v2"

def test_opencode_aliases_support():
    p1 = create_ai_provider(provider_name="zen", api_key="k")
    assert isinstance(p1, OpenCodeZenProvider)

    p2 = create_ai_provider(provider_name="go", api_key="k")
    assert isinstance(p2, OpenCodeGoProvider)

    p3 = create_ai_provider(provider_name="opencode", api_key="k")
    assert isinstance(p3, OpenCodeZenProvider)


def test_opencode_catalogs_exist():
    assert "opencode-zen" in PROVIDER_MODELS_CATALOG
    assert "opencode-go" in PROVIDER_MODELS_CATALOG
    assert "muse-spark-1.2-contributor-free" in PROVIDER_MODELS_CATALOG["opencode-zen"]
    assert "go-code-fast" in PROVIDER_MODELS_CATALOG["opencode-go"]
