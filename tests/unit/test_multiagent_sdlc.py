"""Unit tests for Multi-Agent SDLC pipeline execution."""

import pytest
from src.application.multiagent_sdlc import MultiAgentSDLC
from src.infrastructure.tools.registry import ToolRegistry
from tests.conftest import MockAIProvider


@pytest.mark.asyncio
async def test_multiagent_sdlc_pipeline_flow():
    mock_ai = MockAIProvider(fixed_response="Generated step output")
    tools = ToolRegistry()
    sdlc = MultiAgentSDLC(ai_provider=mock_ai, tool_registry=tools)

    progress_events = []

    async def callback(msg, pct):
        progress_events.append((msg, pct))

    result = await sdlc.execute_feature_lifecycle(
        feature_description="Build JWT Auth Middleware",
        user_id=1,
        progress_callback=callback
    )

    assert result.success is True
    assert result.feature_name == "Build JWT Auth Middleware"
    assert "Generated step output" in result.plan_output
    assert "Generated step output" in result.code_output
    assert "Generated step output" in result.qa_output
    assert len(progress_events) == 4
