"""Unit tests for OpenCode HTTP Bridge v2 API additions and loopback security."""

import asyncio
import json
import httpx
import pytest
from src.infrastructure.opencode.bridge import OpenCodeBridge, OpenCodeError


# ---------------------------------------------------------------------------
# 1. Loopback URL Detection & Security Guard Tests
# ---------------------------------------------------------------------------

def test_is_loopback_url_valid():
    """Valid loopback addresses must return True."""
    valid_urls = [
        "http://127.0.0.1:4096",
        "http://127.0.0.1",
        "https://127.0.0.1:8080",
        "http://localhost:4096",
        "http://localhost",
        "http://LOCALHOST:4096",
        "http://[::1]:4096",
        "http://[::1]",
        "http://::1",
        "http://::1:4096",
        "127.0.0.1:4096",
        "localhost:4096",
    ]
    for url in valid_urls:
        assert OpenCodeBridge.is_loopback_url(url) is True, f"Failed for valid URL: {url}"


def test_is_loopback_url_invalid():
    """Non-loopback addresses, 0.0.0.0, and empty inputs must return False."""
    invalid_urls = [
        "http://0.0.0.0:4096",
        "http://0.0.0.0",
        "http://192.168.1.1:4096",
        "http://10.0.0.1",
        "http://example.com",
        "http://example.com:4096",
        "http://8.8.8.8:4096",
        "",
        None,
        "   ",
        "ftp://127.0.0.1",  # non-http(s) could be handled or accepted if host is loopback, but let's test host
    ]
    for url in invalid_urls:
        if url == "ftp://127.0.0.1":
            continue  # Host is still 127.0.0.1
        assert OpenCodeBridge.is_loopback_url(url) is False, f"Failed for invalid URL: {url}"


def test_assert_loopback_success():
    """Bridge with loopback URL passes assertion."""
    bridge = OpenCodeBridge(base_url="http://127.0.0.1:4096")
    bridge._assert_loopback()

    bridge_lh = OpenCodeBridge(base_url="http://localhost:4096")
    bridge_lh._assert_loopback()


def test_assert_loopback_rejection():
    """Bridge with non-loopback URL raises OpenCodeError with clear message."""
    bridge = OpenCodeBridge(base_url="http://192.168.1.50:4096")
    with pytest.raises(OpenCodeError) as exc_info:
        bridge._assert_loopback()
    assert "loopback" in str(exc_info.value).lower()

    bridge_zero = OpenCodeBridge(base_url="http://0.0.0.0:4096")
    with pytest.raises(OpenCodeError):
        bridge_zero._assert_loopback()


@pytest.mark.asyncio
async def test_new_methods_reject_non_loopback():
    """All v2 network methods must call _assert_loopback and reject non-loopback URLs."""
    bridge = OpenCodeBridge(base_url="http://192.168.1.100:4096")

    with pytest.raises(OpenCodeError):
        await bridge.health()

    with pytest.raises(OpenCodeError):
        async for _ in bridge.stream_events("ses_123"):
            pass

    with pytest.raises(OpenCodeError):
        await bridge.prompt_async("ses_123", "hello")

    with pytest.raises(OpenCodeError):
        await bridge.interrupt("ses_123")

    with pytest.raises(OpenCodeError):
        await bridge.set_model("ses_123", "model1", "prov1")

    with pytest.raises(OpenCodeError):
        await bridge.set_agent("ses_123", "coder")

    with pytest.raises(OpenCodeError):
        await bridge.list_agents()

    with pytest.raises(OpenCodeError):
        await bridge.list_models()

    with pytest.raises(OpenCodeError):
        await bridge.list_commands()

    with pytest.raises(OpenCodeError):
        await bridge.list_skills()

    with pytest.raises(OpenCodeError):
        await bridge.list_permission_requests("ses_123")

    with pytest.raises(OpenCodeError):
        await bridge.reply_permission("ses_123", "req_1", "once")

    with pytest.raises(OpenCodeError):
        await bridge.get_session_messages_v2("ses_123")


# ---------------------------------------------------------------------------
# 2. Mock Transport Helper
# ---------------------------------------------------------------------------

def make_bridge(handler) -> OpenCodeBridge:
    """Create OpenCodeBridge configured with a MockTransport."""
    transport = httpx.MockTransport(handler)
    return OpenCodeBridge(base_url="http://127.0.0.1:4096", transport=transport)


# ---------------------------------------------------------------------------
# 3. Health Endpoint Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/health"
        return httpx.Response(200, json={"status": "healthy", "version": "2.0.0"})

    bridge = make_bridge(handler)
    res = await bridge.health()
    assert res == {"status": "healthy", "version": "2.0.0"}


@pytest.mark.asyncio
async def test_health_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    bridge = make_bridge(handler)
    res = await bridge.health()
    assert res is None


# ---------------------------------------------------------------------------
# 4. SSE Stream Events Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_events_success():
    sse_body = (
        b": heartbeat\n\n"
        b"data: {\"id\":\"evt_1\",\"type\":\"session.next.text.delta\",\"data\":{\"text\":\"Hel\"}}\n\n"
        b": heartbeat\n"
        b"data: {\"id\":\"evt_2\",\"type\":\"session.next.text.ended\",\n"
        b"data: \"data\":{\"text\":\"Hello\"}}\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/session/ses_abc/event"
        return httpx.Response(200, content=sse_body)

    bridge = make_bridge(handler)
    events = []
    async for event in bridge.stream_events("ses_abc"):
        events.append(event)

    assert len(events) == 2
    assert events[0]["id"] == "evt_1"
    assert events[0]["data"]["text"] == "Hel"
    assert events[1]["id"] == "evt_2"
    assert events[1]["data"]["text"] == "Hello"


@pytest.mark.asyncio
async def test_stream_events_non_200():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Session not found")

    bridge = make_bridge(handler)
    with pytest.raises(OpenCodeError) as exc_info:
        async for _ in bridge.stream_events("ses_missing"):
            pass
    assert "404" in str(exc_info.value)


@pytest.mark.asyncio
async def test_stream_events_cancellation():
    async def infinite_lines():
        while True:
            yield b": heartbeat\n\n"
            await asyncio.sleep(0.01)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=infinite_lines())

    bridge = make_bridge(handler)

    async def consume():
        async for _ in bridge.stream_events("ses_infinite"):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ---------------------------------------------------------------------------
# 5. Prompt Async Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prompt_async_success():
    expected_data = {
        "admittedSeq": 1,
        "id": "msg_001",
        "sessionID": "ses_xyz",
        "prompt": {"text": "write tests"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/session/ses_xyz/prompt"
        payload = json.loads(request.content)
        assert payload == {"prompt": {"text": "write tests"}}
        return httpx.Response(200, json={"data": expected_data})

    bridge = make_bridge(handler)
    res = await bridge.prompt_async("ses_xyz", "write tests")
    assert res == expected_data


@pytest.mark.asyncio
async def test_prompt_async_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    bridge = make_bridge(handler)
    with pytest.raises(OpenCodeError) as exc_info:
        await bridge.prompt_async("ses_xyz", "test")
    assert "500" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 6. Session Control: Interrupt, Set Model, Set Agent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_interrupt_success_and_failure():
    status = 204

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/session/ses_1/interrupt"
        return httpx.Response(status)

    bridge = make_bridge(handler)
    assert await bridge.interrupt("ses_1") is True

    status = 500
    assert await bridge.interrupt("ses_1") is False


@pytest.mark.asyncio
async def test_set_model():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/session/ses_1/model"
        payload = json.loads(request.content)
        assert payload == {"model": {"id": "claude-3-7-sonnet", "providerID": "anthropic"}}
        return httpx.Response(200, json={"ok": True})

    bridge = make_bridge(handler)
    ok = await bridge.set_model("ses_1", "claude-3-7-sonnet", "anthropic")
    assert ok is True


@pytest.mark.asyncio
async def test_set_agent():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/session/ses_1/agent"
        payload = json.loads(request.content)
        assert payload == {"agent": "sisyphus"}
        return httpx.Response(200, json={"ok": True})

    bridge = make_bridge(handler)
    ok = await bridge.set_agent("ses_1", "sisyphus")
    assert ok is True


# ---------------------------------------------------------------------------
# 7. List Methods (Agents, Models, Commands, Skills)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_agents():
    agents_list = [{"id": "build", "name": "Build Agent"}, {"id": "oracle", "name": "Oracle"}]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/agent"
        return httpx.Response(200, json={"data": agents_list})

    bridge = make_bridge(handler)
    res = await bridge.list_agents()
    assert res == agents_list


@pytest.mark.asyncio
async def test_list_models_raw_list_fallback():
    models_list = [{"id": "gpt-4o", "providerID": "openai"}]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/model"
        # Test fallback when API returns raw list instead of {"data": [...]}
        return httpx.Response(200, json=models_list)

    bridge = make_bridge(handler)
    res = await bridge.list_models()
    assert res == models_list


@pytest.mark.asyncio
async def test_list_commands_malformed_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "structure"})

    bridge = make_bridge(handler)
    res = await bridge.list_commands()
    assert res == []


@pytest.mark.asyncio
async def test_list_skills_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Crash")

    bridge = make_bridge(handler)
    res = await bridge.list_skills()
    assert res == []


# ---------------------------------------------------------------------------
# 8. Permissions Tests (List & Reply)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_permission_requests_with_and_without_session():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/session/ses_100/permission":
            return httpx.Response(200, json={"data": [{"id": "p1", "action": "bash"}]})
        elif request.url.path == "/api/permission/request":
            return httpx.Response(200, json={"data": [{"id": "p2", "action": "file_write"}]})
        return httpx.Response(404)

    bridge = make_bridge(handler)
    res_session = await bridge.list_permission_requests("ses_100")
    assert len(res_session) == 1
    assert res_session[0]["id"] == "p1"

    res_global = await bridge.list_permission_requests(None)
    assert len(res_global) == 1
    assert res_global[0]["id"] == "p2"


@pytest.mark.asyncio
async def test_reply_permission_validation_and_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/session/ses_100/permission/req_99/reply"
        payload = json.loads(request.content)
        assert payload["reply"] == "once"
        assert payload["message"] == "authorized by user"
        return httpx.Response(204)

    bridge = make_bridge(handler)

    # Invalid reply value raises ValueError
    with pytest.raises(ValueError):
        await bridge.reply_permission("ses_100", "req_99", "invalid_choice")

    # Valid reply with message
    ok = await bridge.reply_permission("ses_100", "req_99", "once", message="authorized by user")
    assert ok is True


# ---------------------------------------------------------------------------
# 9. Get Session Messages v2
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_session_messages_v2():
    msg_data = [
        {"id": "msg_1", "type": "user", "content": [{"type": "text", "text": "hello"}]},
        {"id": "msg_2", "type": "assistant", "content": [{"type": "text", "text": "hi"}]},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/session/ses_msg/message"
        assert request.url.params.get("limit") == "50"
        return httpx.Response(200, json={"data": msg_data, "cursor": {}})

    bridge = make_bridge(handler)
    res = await bridge.get_session_messages_v2("ses_msg", limit=50)
    assert res == msg_data
