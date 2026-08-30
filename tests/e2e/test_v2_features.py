"""E2E integration tests for v2.0 features: multimodal input handling and /schedule, /remind, /chart slash commands."""

import pytest
from src.application.orchestrator import AgentOrchestrator
from src.domain.agent import Role
from src.domain.user import AuthPolicy
from src.infrastructure.security.rate_limiter import UserRateLimiter
from src.infrastructure.telegram.adapter import TelegramAdapter
from src.infrastructure.telegram.auth import TelegramAuthManager
from src.infrastructure.tools.chart_tool import ChartTool
from src.infrastructure.tools.registry import ToolRegistry
from tests.conftest import MockAIProvider


class MockV2TelegramAdapter(TelegramAdapter):
    """Extended mock telegram adapter with mock file download support."""

    def __init__(self):
        super().__init__(bot_token="1234567890:MockToken")
        self.sent_messages = []
        self.chat_actions = []

    async def send_message(self, chat_id, text, reply_markup=None, reply_to_message_id=None, parse_mode=None):
        self.sent_messages.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return [1]

    async def send_chat_action(self, chat_id, action="typing"):
        self.chat_actions.append({"chat_id": chat_id, "action": action})
        return True

    async def download_file_by_id(self, file_id: str):
        if "doc" in file_id:
            return b"kind: Deployment\nmetadata:\n  name: web-app\nspec:\n  replicas: 3", {"file_path": f"documents/{file_id}"}
        return b"\xff\xd8\xff\xe0mock_jpeg_binary_data", {"file_path": f"photos/{file_id}"}


@pytest.fixture
def v2_orchestrator_setup(temp_db, mock_config):
    """Factory helper to configure Orchestrator with tools, auth, and mock telegram/AI."""
    mock_tg = MockV2TelegramAdapter()
    mock_ai = MockAIProvider(fixed_response="AI processed your input successfully.")
    tools = ToolRegistry()
    tools.register(ChartTool())

    auth_policy = AuthPolicy(allowlist_enabled=False)
    auth_mgr = TelegramAuthManager(policy=auth_policy)
    limiter = UserRateLimiter()

    orchestrator = AgentOrchestrator(
        config=mock_config,
        telegram_adapter=mock_tg,
        ai_provider=mock_ai,
        db=temp_db,
        tool_registry=tools,
        auth_manager=auth_mgr,
        rate_limiter=limiter,
    )

    return orchestrator, mock_tg, mock_ai, temp_db


# ==========================================
# 1. Multimodal Message Handling Tests
# ==========================================

@pytest.mark.asyncio
async def test_multimodal_photo_with_caption(v2_orchestrator_setup):
    """Test Telegram message with photo attachment and caption."""
    orchestrator, mock_tg, mock_ai, db = v2_orchestrator_setup

    photo_msg = {
        "photo": [{"file_id": "photo_abc123", "width": 1024, "height": 768, "file_size": 51200}],
        "caption": "Analyze this system architecture diagram",
        "chat": {"id": 1001, "type": "private"},
        "from": {"id": 1001, "username": "developer"}
    }

    await orchestrator.handle_message(photo_msg)

    # 1. Check AI request received the photo context + caption
    assert len(mock_ai.request_history) == 1
    last_user_msg = [m for m in mock_ai.request_history[0].messages if m.role == Role.USER][-1]
    assert "image_base64" in last_user_msg.metadata
    assert last_user_msg.metadata["mime_type"] == "image/jpeg"
    assert "Analyze this system architecture diagram" in last_user_msg.content

    # 2. Check outbound Telegram message sent
    assert len(mock_tg.sent_messages) == 1
    assert "AI processed your input" in mock_tg.sent_messages[0]["text"]

    # 3. Check SQLite persistence
    session = await db.get_or_create_session(1001, 1001)
    assert len(session.messages) >= 2


@pytest.mark.asyncio
async def test_multimodal_photo_without_caption(v2_orchestrator_setup):
    """Test Telegram message with photo attachment but no caption."""
    orchestrator, mock_tg, mock_ai, db = v2_orchestrator_setup

    photo_msg = {
        "photo": [{"file_id": "photo_xyz789", "width": 800, "height": 600, "file_size": 20480}],
        "chat": {"id": 1001, "type": "private"},
        "from": {"id": 1001, "username": "developer"}
    }

    await orchestrator.handle_message(photo_msg)

    assert len(mock_ai.request_history) == 1
    last_user_msg = [m for m in mock_ai.request_history[0].messages if m.role == Role.USER][-1]
    assert "image_base64" in last_user_msg.metadata


@pytest.mark.asyncio
async def test_multimodal_document_text_extraction(v2_orchestrator_setup):
    """Test Telegram message with document attachment."""
    orchestrator, mock_tg, mock_ai, db = v2_orchestrator_setup

    doc_msg = {
        "document": {
            "file_id": "doc_file_001",
            "file_name": "k8s_deployment.yaml",
            "mime_type": "text/yaml",
            "file_size": 2048
        },
        "caption": "Verify security context in this manifest",
        "chat": {"id": 1001, "type": "private"},
        "from": {"id": 1001, "username": "devops"}
    }

    await orchestrator.handle_message(doc_msg)

    assert len(mock_ai.request_history) == 1
    last_user_msg = [m for m in mock_ai.request_history[0].messages if m.role == Role.USER][-1]
    assert "[Document Attached: k8s_deployment.yaml" in last_user_msg.content
    assert "Verify security context" in last_user_msg.content


# ==========================================
# 2. Slash Commands Tests: /schedule, /remind, /chart
# ==========================================

@pytest.mark.asyncio
async def test_slash_schedule_command_execution_and_persistence(v2_orchestrator_setup):
    """Test /schedule command adds persistent job into SQLite."""
    orchestrator, mock_tg, _, _ = v2_orchestrator_setup

    cmd_msg = {
        "text": "/schedule in 10m Execute automated database backup",
        "chat": {"id": 1001, "type": "private"},
        "from": {"id": 1001, "username": "admin"}
    }

    await orchestrator.handle_message(cmd_msg)

    # 1. Verify bot confirmation message
    assert len(mock_tg.sent_messages) == 1
    reply = mock_tg.sent_messages[0]["text"]
    assert "scheduled" in reply.lower() or "job" in reply.lower()
    assert "Execute automated database backup" in reply

    # 2. Verify job in JobScheduler
    active_jobs = await orchestrator.scheduler.list_jobs(user_id=1001, active_only=True)
    assert len(active_jobs) == 1
    job = active_jobs[0]
    assert job.prompt == "Execute automated database backup"
    assert job.is_ai_prompt is True


@pytest.mark.asyncio
async def test_slash_schedule_list_and_cancel_lifecycle(v2_orchestrator_setup):
    """Test listing and cancelling scheduled jobs via slash commands."""
    orchestrator, mock_tg, _, _ = v2_orchestrator_setup

    # Schedule a job first
    job = await orchestrator.scheduler.schedule_cron(
        user_id=1001,
        chat_id=1001,
        prompt="Sync git repositories",
        schedule_expr="every 1h"
    )

    # 1. Test /schedule list
    await orchestrator.handle_message({
        "text": "/schedule list",
        "chat": {"id": 1001, "type": "private"},
        "from": {"id": 1001, "username": "admin"}
    })
    list_reply = mock_tg.sent_messages[0]["text"]
    assert "Scheduled Jobs" in list_reply
    assert job.job_id in list_reply

    # 2. Test /schedule cancel <id>
    await orchestrator.handle_message({
        "text": f"/schedule cancel {job.job_id}",
        "chat": {"id": 1001, "type": "private"},
        "from": {"id": 1001, "username": "admin"}
    })
    cancel_reply = mock_tg.sent_messages[1]["text"]
    assert "cancelled" in cancel_reply.lower()

    # 3. Verify cancelled in scheduler
    updated_job = await orchestrator.scheduler.get_job(job.job_id)
    assert updated_job.status == "cancelled"


@pytest.mark.asyncio
async def test_slash_remind_command(v2_orchestrator_setup):
    """Test /remind command creates reminder in scheduler."""
    orchestrator, mock_tg, _, _ = v2_orchestrator_setup

    cmd_msg = {
        "text": "/remind in 15m Take a 5-minute break and stretch",
        "chat": {"id": 1001, "type": "private"},
        "from": {"id": 1001, "username": "coder"}
    }

    await orchestrator.handle_message(cmd_msg)

    # Verify confirmation
    assert len(mock_tg.sent_messages) == 1
    reply = mock_tg.sent_messages[0]["text"]
    assert "Reminder set" in reply
    assert "Take a 5-minute break" in reply

    # Verify reminder job
    jobs = await orchestrator.scheduler.list_jobs(user_id=1001, active_only=True)
    assert len(jobs) == 1
    assert jobs[0].job_type == "reminder"
    assert jobs[0].is_ai_prompt is False


@pytest.mark.asyncio
async def test_slash_chart_command_visualization(v2_orchestrator_setup):
    """Test /chart command generates ASCII chart and QuickChart link."""
    orchestrator, mock_tg, _, _ = v2_orchestrator_setup

    # Test pipe format
    cmd_msg = {
        "text": "/chart bar Monthly Active Users | Jan: 1200, Feb: 1900, Mar: 2800",
        "chat": {"id": 1001, "type": "private"},
        "from": {"id": 1001, "username": "pm"}
    }

    await orchestrator.handle_message(cmd_msg)

    assert len(mock_tg.sent_messages) == 1
    reply = mock_tg.sent_messages[0]["text"]

    # Verify chart output contents
    assert "quickchart.io/chart" in reply
    assert "Jan" in reply
    assert "Feb" in reply
    assert "Mar" in reply
    assert "█" in reply


@pytest.mark.asyncio
async def test_slash_commands_empty_args_show_usage(v2_orchestrator_setup):
    """Test that invoking slash commands without arguments prints clear usage instructions."""
    orchestrator, mock_tg, _, _ = v2_orchestrator_setup

    # /schedule usage
    await orchestrator.handle_message({"text": "/schedule", "chat": {"id": 1, "type": "private"}, "from": {"id": 1}})
    assert "/schedule" in mock_tg.sent_messages[0]["text"]

    # /remind usage
    await orchestrator.handle_message({"text": "/remind", "chat": {"id": 1, "type": "private"}, "from": {"id": 1}})
    assert "/remind" in mock_tg.sent_messages[1]["text"]

    # /chart usage
    await orchestrator.handle_message({"text": "/chart", "chat": {"id": 1, "type": "private"}, "from": {"id": 1}})
    assert "/chart" in mock_tg.sent_messages[2]["text"]
