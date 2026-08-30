"""Unit tests for 9router and DeepSeek providers."""

from src.infrastructure.ai.factory import create_ai_provider
from src.infrastructure.ai.nine_router_provider import NineRouterProvider
from src.infrastructure.ai.deepseek_provider import DeepSeekProvider


def test_nine_router_provider_defaults():
    prov = create_ai_provider("9router")
    assert isinstance(prov, NineRouterProvider)
    assert "20128" in prov.base_url
    assert prov.model == "claude-3-5-sonnet-20241022"


def test_deepseek_provider_defaults():
    prov = create_ai_provider("deepseek", api_key="sk-deepseek-test")
    assert isinstance(prov, DeepSeekProvider)
    assert "api.deepseek.com" in prov.base_url
    assert prov.model == "deepseek-chat"
