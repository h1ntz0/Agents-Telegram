"""Unit tests for OpenCodeMirror engine and event rendering."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Dict, List, Optional
import pytest

from src.infrastructure.opencode.mirror import (
    OpenCodeMirror,
    RenderedUpdate,
    render_event,
)


# ---------------------------------------------------------------------------
# Fake Bridge & Fake Telegram Adapter for Testing (No Network)
# ---------------------------------------------------------------------------


class FakeBridge:
    """In-memory simulated OpenCodeBridge."""

    def __init__(
        self,
        events: Optional[List[Dict[str, Any]]] = None,
        agent: Optional[str] = "coder",
    ) -> None:
        self.events: List[Dict[str, Any]] = events or []
        self.agent = agent
        self.prompt_calls: List[tuple[str, str]] = []
        self.interrupted: List[str] = []
        self.stream_delay: float = 0.0
        self.permission_requests: List[Dict[str, Any]] = []

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return {"id": session_id, "agent": self.agent} if self.agent else None

    async def prompt_async(self, session_id: str, text: str) -> Dict[str, Any]:
        self.prompt_calls.append((session_id, text))
        return {"id": "msg_001", "sessionID": session_id}

    async def stream_events(self, session_id: str) -> AsyncIterator[Dict[str, Any]]:
        for evt in self.events:
            if self.stream_delay > 0:
                await asyncio.sleep(self.stream_delay)
            yield evt

    async def interrupt(self, session_id: str) -> bool:
        self.interrupted.append(session_id)
        return True

    async def list_permission_requests(self, session_id: str) -> List[Dict[str, Any]]:
        return list(self.permission_requests)


class FakeTelegram:
    """In-memory simulated TelegramAdapter."""

    def __init__(self) -> None:
        self.sent_messages: List[Dict[str, Any]] = []
        self.edits: List[Dict[str, Any]] = []
        self.chat_actions: List[Dict[str, Any]] = []
        self._next_msg_id = 100

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> List[int]:
        msg_id = self._next_msg_id
        self._next_msg_id += 1
        self.sent_messages.append({
            "chat_id": chat_id,
            "message_id": msg_id,
            "text": text,
            "reply_markup": reply_markup,
        })
        return [msg_id]

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> bool:
        self.edits.append({
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "reply_markup": reply_markup,
        })
        return True

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> bool:
        self.chat_actions.append({"chat_id": chat_id, "action": action})
        return True

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False,
    ) -> bool:
        return True


# ---------------------------------------------------------------------------
# Pure Unit Tests: render_event (Kept intact)
# ---------------------------------------------------------------------------


def test_render_event_prompt_admitted():
    evt = {"type": "session.next.prompt.admitted", "data": {"sessionID": "s1"}}
    upd = render_event(evt)
    assert upd == RenderedUpdate(kind="status", text="⏳ Prompt diterima…")


def test_render_event_step_started():
    evt = {"type": "session.next.step.started", "data": {"sessionID": "s1"}}
    upd = render_event(evt)
    assert upd == RenderedUpdate(kind="status", text="🧠 Berpikir…")


def test_render_event_text_ended():
    evt = {
        "type": "session.next.text.ended",
        "data": {"text": "Halo! Sesi OpenCode siap membantu."},
    }
    upd = render_event(evt)
    assert upd == RenderedUpdate(
        kind="text",
        text="Halo! Sesi OpenCode siap membantu.",
    )


def test_render_event_text_started_ignored():
    evt = {"type": "session.next.text.started", "data": {"sessionID": "s1"}}
    assert render_event(evt) is None


def test_render_event_tool_called_with_title():
    evt = {
        "type": "session.next.tool.called",
        "data": {"tool": "read", "title": "src/config.py"},
    }
    upd = render_event(evt)
    assert upd == RenderedUpdate(kind="tool", text="🔧 read: src/config.py")


def test_render_event_tool_called_without_title():
    evt = {"type": "session.next.tool.called", "data": {"tool": "web_search"}}
    upd = render_event(evt)
    assert upd == RenderedUpdate(kind="tool", text="🔧 web_search")


def test_render_event_tool_called_defensive_fields():
    evt = {
        "type": "session.next.tool.called",
        "data": {
            "state": {
                "tool": "bash",
                "input": {"command": "pytest -v"},
            }
        },
    }
    upd = render_event(evt)
    assert upd == RenderedUpdate(kind="tool", text="🔧 bash: pytest -v")


def test_render_event_tool_called_filePath():
    evt = {
        "type": "session.next.tool.called",
        "data": {
            "toolName": "file_read",
            "input": {"filePath": "README.md"},
        },
    }
    upd = render_event(evt)
    assert upd == RenderedUpdate(kind="tool", text="🔧 file_read: README.md")


def test_render_event_tool_progress_with_title_or_progress():
    evt_with_title = {
        "type": "session.next.tool.progress",
        "data": {"tool": "bash", "title": "compiling assets"},
    }
    upd = render_event(evt_with_title)
    assert upd == RenderedUpdate(kind="tool", text="⏳ bash…")

    evt_with_progress = {
        "type": "session.next.tool.progress",
        "data": {"tool": "docker", "state": {"progress": "pulling image"}},
    }
    upd2 = render_event(evt_with_progress)
    assert upd2 == RenderedUpdate(kind="tool", text="⏳ docker…")


def test_render_event_tool_progress_ignored_without_title_or_progress():
    evt_no_progress = {
        "type": "session.next.tool.progress",
        "data": {"tool": "bash"},
    }
    assert render_event(evt_no_progress) is None


def test_render_event_tool_success():
    evt = {"type": "session.next.tool.success", "data": {"tool": "git_commit"}}
    upd = render_event(evt)
    assert upd == RenderedUpdate(kind="tool", text="✅ git_commit")


def test_render_event_tool_failed():
    evt = {
        "type": "session.next.tool.failed",
        "data": {"tool": "shell", "error": "Command returned code 1"},
    }
    upd = render_event(evt)
    assert upd == RenderedUpdate(
        kind="error",
        text="❌ shell: Command returned code 1",
    )


def test_render_event_tool_failed_nested_state_error():
    evt = {
        "type": "session.next.tool.failed",
        "data": {
            "name": "python_sandbox",
            "state": {"error": "ZeroDivisionError"},
        },
    }
    upd = render_event(evt)
    assert upd == RenderedUpdate(
        kind="error",
        text="❌ python_sandbox: ZeroDivisionError",
    )


def test_render_event_shell_started():
    evt = {
        "type": "session.next.shell.started",
        "data": {"command": "git checkout -b feature"},
    }
    upd = render_event(evt)
    assert upd == RenderedUpdate(kind="tool", text="💻 shell: git checkout -b feature")


def test_render_event_shell_ended_ignored():
    evt = {"type": "session.next.shell.ended", "data": {"code": 0}}
    assert render_event(evt) is None


def test_render_event_step_failed():
    evt = {
        "type": "session.next.step.failed",
        "data": {"error": "Context window exceeded"},
    }
    upd = render_event(evt)
    assert upd == RenderedUpdate(kind="error", text="❌ Context window exceeded")


def test_render_event_step_ended_with_finish():
    evt = {
        "type": "session.next.step.ended",
        "data": {"finish": "stop", "tokens": {"input": 100, "output": 20}},
    }
    upd = render_event(evt)
    assert upd == RenderedUpdate(kind="done", text="stop")


def test_render_event_step_ended_missing_finish():
    evt = {
        "type": "session.next.step.ended",
        "data": {"cost": 0},
    }
    assert render_event(evt) is None


def test_render_event_ignored_events():
    assert render_event({"type": "session.next.prompted", "data": {}}) is None
    assert render_event({"type": "session.next.synthetic", "data": {}}) is None
    assert render_event({"type": "session.next.random_unknown", "data": {}}) is None


def test_render_event_malformed_guards():
    assert render_event(None) is None  # type: ignore[arg-type]
    assert render_event({}) is None
    assert render_event({"type": None, "data": {}}) is None
    assert render_event({"type": "session.next.text.ended", "data": None}) is None
    assert render_event({"type": "session.next.text.ended"}) is None
    assert render_event("not a dict") is None  # type: ignore[arg-type]
    assert render_event({"type": "session.next.text.ended", "data": "string"}) is None


# ---------------------------------------------------------------------------
# OpenCodeMirror Tests: Status Card Architecture
# ---------------------------------------------------------------------------


def test_mirror_initialization():
    bridge = FakeBridge()
    tg = FakeTelegram()
    mirror = OpenCodeMirror(bridge, tg, "ses_test_123", 4242)

    assert mirror.session_id == "ses_test_123"
    assert mirror.chat_id == 4242
    assert mirror.is_running is False
    assert mirror.edit_interval == 1.5
    assert mirror.permission_poll_interval == 3.0
    assert mirror.max_card_lines == 6


def test_mirror_status_card_render_only_status_and_tools():
    bridge = FakeBridge(agent="coder")
    tg = FakeTelegram()
    mirror = OpenCodeMirror(bridge, tg, "ses_1", 100, max_card_lines=3)
    mirror._header = "⏳ OpenCode [coder]"

    # Initial empty state
    initial = mirror._render_status_card()
    assert "⏳ OpenCode [coder]" in initial
    assert "⏳ Memproses…" in initial

    # Add status, tools, and text
    mirror._status_lines.append("🧠 Berpikir…")
    mirror._status_lines.append("🔧 read: foo.py")
    mirror._status_lines.append("✅ read")
    mirror._status_lines.append("🔧 bash: pytest")
    mirror._assistant_texts.append("Here is 500 lines of generated code...")

    card = mirror._render_status_card()

    # Status card must NEVER contain assistant text!
    assert "Here is 500 lines of generated code..." not in card
    # Keeps only LAST N (max_card_lines = 3)
    assert "🧠 Berpikir…" not in card
    assert "🔧 read: foo.py" in card
    assert "✅ read" in card
    assert "🔧 bash: pytest" in card


@pytest.mark.asyncio
async def test_mirror_run_prompt_full_flow_status_card_and_separate_text():
    events = [
        {"type": "session.next.prompt.admitted", "data": {}},
        {"type": "session.next.step.started", "data": {}},
        {"type": "session.next.tool.called", "data": {"tool": "read", "title": "main.py"}},
        {"type": "session.next.tool.success", "data": {"tool": "read"}},
        {"type": "session.next.text.ended", "data": {"text": "Analisis kode selesai. Berfungsi normal."}},
        {"type": "session.next.step.ended", "data": {"finish": "stop"}},
    ]

    bridge = FakeBridge(events=events, agent="coder")
    tg = FakeTelegram()
    mirror = OpenCodeMirror(bridge, tg, "ses_abc", 9999, edit_interval=1.5)

    await mirror.run_prompt("Tolong review main.py")

    # 1. bridge.prompt_async called with text
    assert len(bridge.prompt_calls) == 1
    assert bridge.prompt_calls[0] == ("ses_abc", "Tolong review main.py")

    # 2. telegram typing chat action sent
    assert len(tg.chat_actions) == 1
    assert tg.chat_actions[0] == {"chat_id": 9999, "action": "typing"}

    # 3. Exactly TWO messages sent via send_message:
    #    [0] Status Card message with Stop button inline keyboard
    #    [1] SEPARATE assistant text message
    assert len(tg.sent_messages) == 2

    status_card_msg = tg.sent_messages[0]
    assert status_card_msg["chat_id"] == 9999
    assert "⏳ OpenCode" in status_card_msg["text"]
    assert status_card_msg["reply_markup"] == {
        "inline_keyboard": [[{"text": "⏹️ Stop", "callback_data": "ocstop:ses_abc"}]]
    }

    text_msg = tg.sent_messages[1]
    assert text_msg["chat_id"] == 9999
    assert text_msg["text"] == "Analisis kode selesai. Berfungsi normal."

    # 4. Status card had edits, and final edit has keyboard removed & compact finish summary
    assert len(tg.edits) >= 1
    final_edit = tg.edits[-1]
    assert "✅ OpenCode selesai (stop)" in final_edit["text"]
    assert "Analisis kode selesai. Berfungsi normal." not in final_edit["text"]
    # Stop keyboard REMOVED
    assert final_edit["reply_markup"] == {"inline_keyboard": []}

    # 5. Mirror is no longer running
    assert mirror.is_running is False


@pytest.mark.asyncio
async def test_mirror_run_prompt_long_assistant_text_not_truncated():
    """Verify long assistant text (9000 chars) is sent in full, never truncated."""
    long_code = "def code():\n    pass\n" * 450  # ~9000 chars
    events = [
        {"type": "session.next.step.started", "data": {}},
        {"type": "session.next.text.ended", "data": {"text": long_code}},
        {"type": "session.next.step.ended", "data": {"finish": "stop"}},
    ]

    bridge = FakeBridge(events=events)
    tg = FakeTelegram()
    mirror = OpenCodeMirror(bridge, tg, "ses_long", 5555)

    await mirror.run_prompt("Generate 9000 chars of code")

    # Separate text message must contain the complete 9000-char text without truncation
    assert len(tg.sent_messages) == 2
    sent_text_msg = tg.sent_messages[1]["text"]
    assert len(sent_text_msg) == len(long_code)
    assert sent_text_msg == long_code
    assert not sent_text_msg.startswith("…\n")

    # Status card must not contain the generated code
    final_card = tg.edits[-1]["text"]
    assert "def code():" not in final_card
    assert "✅ OpenCode selesai (stop)" in final_card


@pytest.mark.asyncio
async def test_mirror_permission_relay():
    """Verify pending permission requests produce an inline keyboard with ocperm:."""
    bridge = FakeBridge(
        events=[
            {"type": "session.next.step.started", "data": {}},
            {"type": "session.next.step.ended", "data": {"finish": "stop"}},
        ]
    )
    bridge.permission_requests = [
        {
            "id": "req_xyz_1",
            "permission": "bash",
            "pattern": "rm -rf /tmp/test",
        }
    ]

    tg = FakeTelegram()
    # Fast poll interval for test
    mirror = OpenCodeMirror(bridge, tg, "ses_perm", 7777, permission_poll_interval=0.01)

    await mirror.run_prompt("Execute rm command")

    # Should have sent:
    # 1) status card
    # 2) permission request message
    perm_messages = [
        m for m in tg.sent_messages
        if m.get("reply_markup") and any(
            "ocperm:" in btn.get("callback_data", "")
            for row in m["reply_markup"].get("inline_keyboard", [])
            for btn in row
        )
    ]
    assert len(perm_messages) == 1
    perm_msg = perm_messages[0]
    # Callback data must stay short (Telegram hard limit is 64 bytes) and resolve back.
    assert "req_xyz_1" not in str(perm_msg["reply_markup"])
    assert "bash" in perm_msg["text"] or "rm -rf /tmp/test" in perm_msg["text"]

    buttons = perm_msg["reply_markup"]["inline_keyboard"][0]
    callback_datas = [b["callback_data"] for b in buttons]
    for data in callback_datas:
        assert data.startswith("ocperm:")
        assert len(data.encode("utf-8")) <= 64
    assert any(d.endswith(":once") for d in callback_datas)
    assert any(d.endswith(":always") for d in callback_datas)
    assert any(d.endswith(":reject") for d in callback_datas)
    token = callback_datas[0].split(":")[1]
    assert mirror.resolve_permission_token(token) == "req_xyz_1"


@pytest.mark.asyncio
async def test_mirror_run_prompt_stops_on_error_event():
    events = [
        {"type": "session.next.step.started", "data": {}},
        {"type": "session.next.tool.failed", "data": {"tool": "bash", "error": "file not found"}},
        {"type": "session.next.text.ended", "data": {"text": "Should not appear"}},
    ]

    bridge = FakeBridge(events=events)
    tg = FakeTelegram()
    mirror = OpenCodeMirror(bridge, tg, "ses_err", 1001)

    await mirror.run_prompt("Run bash")

    assert len(tg.sent_messages) == 1  # Only status card, no text sent on error
    assert len(tg.edits) >= 1
    final_edit = tg.edits[-1]
    assert "❌ OpenCode error:" in final_edit["text"]
    assert "file not found" in final_edit["text"]
    assert final_edit["reply_markup"] == {"inline_keyboard": []}
    assert mirror.is_running is False


@pytest.mark.asyncio
async def test_mirror_stop():
    bridge = FakeBridge()
    tg = FakeTelegram()
    mirror = OpenCodeMirror(bridge, tg, "ses_stop_me", 2002)

    mirror._running = True
    assert mirror.is_running is True

    await mirror.stop()

    assert mirror.is_running is False
    assert bridge.interrupted == ["ses_stop_me"]


@pytest.mark.asyncio
async def test_mirror_handles_bridge_exception_gracefully():
    class FailingBridge(FakeBridge):
        async def prompt_async(self, session_id: str, text: str) -> Dict[str, Any]:
            raise RuntimeError("Connection to OpenCode lost")

    bridge = FailingBridge()
    tg = FakeTelegram()
    mirror = OpenCodeMirror(bridge, tg, "ses_fail", 3003)

    await mirror.run_prompt("Hello")

    assert mirror.is_running is False
    assert len(tg.sent_messages) >= 1
    assert "Connection to OpenCode lost" in tg.sent_messages[-1]["text"]
