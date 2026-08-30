"""Unit tests for Orchestrator v2: Multimodal (photo, doc, voice), commands (/schedule, /remind, /chart), and proactive execution."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import pytest
from src.application.orchestrator import AgentOrchestrator
from src.domain.user import AuthPolicy
from src.infrastructure.scheduler.job_scheduler import JobScheduler, JobStatus
from src.infrastructure.security.rate_limiter import UserRateLimiter
from src.infrastructure.telegram.adapter import TelegramAdapter
from src.infrastructure.telegram.auth import TelegramAuthManager
from src.infrastructure.tools.registry import ToolRegistry
from tests.conftest import MockAIProvider


class MockTelegramAdapterV2(TelegramAdapter):
    """Mock TelegramAdapter capturing messages, photos, and file downloads."""

    def __init__(self):
        super().__init__(bot_token="1234567890:MockToken")
        self.sent_messages = []
        self.chat_actions = []
        self.file_downloads = {}

    async def send_message(self, chat_id, text, reply_markup=None, reply_to_message_id=None, parse_mode=None):
        self.sent_messages.append({
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode
        })
        return [len(self.sent_messages)]

    async def send_chat_action(self, chat_id, action="typing"):
        self.chat_actions.append({"chat_id": chat_id, "action": action})
        return True

    async def download_file_by_id(self, file_id: str):
        content = self.file_downloads.get(file_id, b"sample file binary content")
        return content, {"file_path": f"files/{file_id}", "file_id": file_id}


@pytest.fixture
def orchestrator_setup(temp_db, mock_config):
    mock_tg = MockTelegramAdapterV2()
    mock_ai = MockAIProvider(fixed_response="AI Assistant Response")
    tools = ToolRegistry()
    auth_policy = AuthPolicy(allowlist_enabled=False)
    auth_mgr = TelegramAuthManager(policy=auth_policy)
    limiter = UserRateLimiter()
    scheduler = JobScheduler(db=temp_db)

    orchestrator = AgentOrchestrator(
        config=mock_config,
        telegram_adapter=mock_tg,
        ai_provider=mock_ai,
        db=temp_db,
        tool_registry=tools,
        auth_manager=auth_mgr,
        rate_limiter=limiter,
        scheduler=scheduler,
    )
    return orchestrator, mock_tg, mock_ai, scheduler


@pytest.mark.asyncio
async def test_orchestrator_photo_multimodal(orchestrator_setup):
    """Test receiving and processing photo message attachments."""
    orchestrator, mock_tg, mock_ai, _ = orchestrator_setup
    mock_tg.file_downloads["photo_123"] = b"\xff\xd8\xff\xe0\x00\x10JFIF"

    msg = {
        "chat": {"id": 111, "type": "private"},
        "from": {"id": 111, "username": "user1"},
        "photo": [
            {"file_id": "photo_small", "width": 100, "height": 100, "file_size": 500},
            {"file_id": "photo_123", "width": 800, "height": 600, "file_size": 15000},
        ],
        "caption": "What is depicted in this photo?"
    }

    await orchestrator.handle_message(msg)

    assert len(mock_tg.sent_messages) == 1
    assert "AI Assistant Response" in mock_tg.sent_messages[0]["text"]
    assert len(mock_ai.recorded_requests) == 1
    last_req = mock_ai.recorded_requests[0]
    user_msg = [m for m in last_req.messages if m.role.value == "user"][-1]
    assert "[Photo Attached: 800x600" in user_msg.content
    assert "What is depicted in this photo?" in user_msg.content
    assert "image_base64" in user_msg.metadata


@pytest.mark.asyncio
async def test_orchestrator_document_multimodal(orchestrator_setup):
    """Test receiving and parsing document message attachments."""
    orchestrator, mock_tg, mock_ai, _ = orchestrator_setup
    csv_bytes = b"id,name,revenue\n1,ProjectA,5000\n2,ProjectB,8500\n"
    mock_tg.file_downloads["doc_456"] = csv_bytes

    msg = {
        "chat": {"id": 111, "type": "private"},
        "from": {"id": 111, "username": "user1"},
        "document": {
            "file_id": "doc_456",
            "file_name": "sales.csv",
            "mime_type": "text/csv",
            "file_size": len(csv_bytes),
        },
        "caption": "Summarize the total revenue"
    }

    await orchestrator.handle_message(msg)

    assert len(mock_tg.sent_messages) == 1
    assert len(mock_ai.recorded_requests) == 1
    last_req = mock_ai.recorded_requests[0]
    user_msg = [m for m in last_req.messages if m.role.value == "user"][-1]
    assert "Document Attached: sales.csv" in user_msg.content
    assert "ProjectA" in user_msg.content
    assert "Summarize the total revenue" in user_msg.content


@pytest.mark.asyncio
async def test_orchestrator_voice_transcription(orchestrator_setup, monkeypatch):
    """Test receiving voice notes with speech-to-text transcription."""
    orchestrator, mock_tg, mock_ai, _ = orchestrator_setup
    mock_tg.file_downloads["voice_789"] = b"OggS\x00\x02fake_audio_bytes"

    async def mock_transcribe(audio_bytes, filename="voice.ogg"):
        return "Check the current weather in London"

    monkeypatch.setattr(orchestrator, "_transcribe_audio", mock_transcribe)

    msg = {
        "chat": {"id": 111, "type": "private"},
        "from": {"id": 111, "username": "user1"},
        "voice": {
            "file_id": "voice_789",
            "duration": 5,
            "file_size": 2048,
        }
    }

    await orchestrator.handle_message(msg)

    # Verify transcription notice + AI response sent
    assert len(mock_tg.sent_messages) == 2
    assert "Transcribed voice note" in mock_tg.sent_messages[0]["text"]
    assert "AI Assistant Response" in mock_tg.sent_messages[1]["text"]


@pytest.mark.asyncio
async def test_orchestrator_schedule_and_remind_commands(orchestrator_setup):
    """Test /schedule and /remind slash command handling."""
    orchestrator, mock_tg, _, scheduler = orchestrator_setup

    # 1. Schedule a task
    sched_msg = {
        "chat": {"id": 111, "type": "private"},
        "from": {"id": 111, "username": "user1"},
        "text": "/schedule every 1h Fetch market prices"
    }
    await orchestrator.handle_message(sched_msg)
    assert len(mock_tg.sent_messages) == 1
    assert "Proactive scheduled AI job created" in mock_tg.sent_messages[0]["text"]

    # 2. Schedule a reminder
    remind_msg = {
        "chat": {"id": 111, "type": "private"},
        "from": {"id": 111, "username": "user1"},
        "text": "/remind 10m Stand up and stretch"
    }
    await orchestrator.handle_message(remind_msg)
    assert len(mock_tg.sent_messages) == 2
    assert "Reminder set" in mock_tg.sent_messages[1]["text"]

    # 3. List scheduled jobs
    list_msg = {
        "chat": {"id": 111, "type": "private"},
        "from": {"id": 111, "username": "user1"},
        "text": "/schedule list"
    }
    await orchestrator.handle_message(list_msg)
    assert len(mock_tg.sent_messages) == 3
    assert "Active Scheduled Jobs" in mock_tg.sent_messages[2]["text"]
    assert "Fetch market prices" in mock_tg.sent_messages[2]["text"]

    # 4. Cancel a job
    jobs = await scheduler.list_jobs(user_id=111, active_only=True)
    assert len(jobs) == 2
    target_id = jobs[0].job_id

    cancel_msg = {
        "chat": {"id": 111, "type": "private"},
        "from": {"id": 111, "username": "user1"},
        "text": f"/schedule cancel {target_id}"
    }
    await orchestrator.handle_message(cancel_msg)
    assert "cancelled" in mock_tg.sent_messages[3]["text"]


@pytest.mark.asyncio
async def test_orchestrator_chart_command(orchestrator_setup):
    """Test /chart command with QuickChart and ASCII output."""
    orchestrator, mock_tg, _, _ = orchestrator_setup

    chart_msg = {
        "chat": {"id": 111, "type": "private"},
        "from": {"id": 111, "username": "user1"},
        "text": "/chart bar Q1,Q2,Q3,Q4 100,200,150,300"
    }
    await orchestrator.handle_message(chart_msg)

    assert len(mock_tg.sent_messages) == 1
    content = mock_tg.sent_messages[0]["text"]
    assert "quickchart.io/chart" in content
    assert "Q1" in content
    assert "Q4" in content
    assert "█" in content


@pytest.mark.asyncio
async def test_orchestrator_run_scheduled_job(orchestrator_setup):
    """Test proactive job execution pushing notification to Telegram."""
    orchestrator, mock_tg, _, scheduler = orchestrator_setup

    # 1. AI Task Job
    ai_job = await scheduler.schedule_cron(
        user_id=111,
        chat_id=222,
        schedule_expr="every 30m",
        prompt="Generate morning summary",
        is_ai_prompt=True,
    )

    await orchestrator.run_scheduled_job(ai_job)

    assert len(mock_tg.sent_messages) == 1
    assert "Scheduled AI Task Update" in mock_tg.sent_messages[0]["text"]
    assert mock_tg.sent_messages[0]["chat_id"] == 222

    # 2. Reminder Job
    remind_job = await scheduler.schedule_reminder(
        user_id=111,
        chat_id=333,
        time_expr="10m",
        text="Drink 500ml water",
    )

    await orchestrator.run_scheduled_job(remind_job)

    assert len(mock_tg.sent_messages) == 2
    assert "Reminder:" in mock_tg.sent_messages[1]["text"]
    assert "Drink 500ml water" in mock_tg.sent_messages[1]["text"]
    assert mock_tg.sent_messages[1]["chat_id"] == 333
