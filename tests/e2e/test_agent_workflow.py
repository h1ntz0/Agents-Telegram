"""E2E test of complete agent conversation and tool execution loop."""

import pytest
from src.application.orchestrator import AgentOrchestrator
from src.domain.agent import ToolCall
from src.domain.provider import CompletionResponse, TokenUsage
from src.domain.user import AuthPolicy
from src.infrastructure.security.rate_limiter import UserRateLimiter
from src.infrastructure.telegram.auth import TelegramAuthManager
from src.infrastructure.tools.filesystem_tool import FileReadTool, FileWriteTool
from src.infrastructure.tools.registry import ToolRegistry
from tests.conftest import MockAIProvider
from tests.unit.test_orchestrator import MockTelegramAdapter


class MultiStepMockAI(MockAIProvider):
    """Simulates a multi-step ReAct agent: first step tool call, second step final answer."""

    def __init__(self):
        super().__init__()
        self.call_count = 0

    async def generate_response(self, request):
        self.request_history.append(request)
        self.call_count += 1
        if self.call_count == 1:
            return CompletionResponse(
                content=None,
                tool_calls=[ToolCall(id="tc_1", name="file_write", arguments={"file_path": "report.txt", "content": "Autonomous report ready."})],
                usage=TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30)
            )
        else:
            return CompletionResponse(
                content="I have written the report to report.txt successfully.",
                tool_calls=[],
                usage=TokenUsage(prompt_tokens=40, completion_tokens=15, total_tokens=55)
            )


@pytest.mark.asyncio
async def test_full_agent_react_workflow(temp_db, mock_config, tmp_path):
    mock_tg = MockTelegramAdapter()
    multi_ai = MultiStepMockAI()

    sandbox_dir = str(tmp_path / "sandbox")
    tools = ToolRegistry()
    tools.register(FileWriteTool(root_dir=sandbox_dir, read_only=False))
    tools.register(FileReadTool(root_dir=sandbox_dir))

    auth_policy = AuthPolicy(allowlist_enabled=False)
    auth_mgr = TelegramAuthManager(policy=auth_policy)
    limiter = UserRateLimiter()

    orchestrator = AgentOrchestrator(
        config=mock_config,
        telegram_adapter=mock_tg,
        ai_provider=multi_ai,
        db=temp_db,
        tool_registry=tools,
        auth_manager=auth_mgr,
        rate_limiter=limiter,
    )

    user_msg = {
        "text": "Write a report file",
        "chat": {"id": 888, "type": "private"},
        "from": {"id": 888, "username": "boss"}
    }
    await orchestrator.handle_message(user_msg)

    # Validate output
    assert len(mock_tg.sent_messages) == 1
    final_reply = mock_tg.sent_messages[0]["text"]
    assert "written the report" in final_reply

    # Validate session state in DB
    session = await temp_db.get_or_create_session(888, 888)
    assert len(session.messages) >= 3  # USER, ASSISTANT (tool_calls), TOOL (response), ASSISTANT (final)
