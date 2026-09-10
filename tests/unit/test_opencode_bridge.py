"""Unit tests for OpenCode HTTP Bridge, OpenCodeBridgeTool, FileEditTool, and FileDeleteTool."""

import os
import tempfile
import pytest
from src.domain.tool import PermissionLevel, RiskLevel
from src.infrastructure.opencode.bridge import OpenCodeBridge, OpenCodeError
from src.infrastructure.tools.opencode_tool import OpenCodeBridgeTool
from src.infrastructure.tools.filesystem_tool import FileEditTool, FileDeleteTool, FileWriteTool, FileReadTool


# ---------------------------------------------------------------------------
# OpenCode Bridge Tests (Mocked / Simulated HTTP)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_opencode_bridge_initialization():
    bridge = OpenCodeBridge(base_url="http://127.0.0.1:4096")
    assert bridge.base_url == "http://127.0.0.1:4096"
    assert bridge.timeout == 60.0
    assert bridge.prompt_timeout == 180.0


@pytest.mark.asyncio
async def test_opencode_tool_definition():
    bridge = OpenCodeBridge(base_url="http://127.0.0.1:4096")
    tool = OpenCodeBridgeTool(bridge=bridge)
    defn = tool.definition
    assert defn.name == "opencode_session"
    assert defn.permission == PermissionLevel.EXECUTE
    assert defn.risk_level == RiskLevel.MEDIUM
    assert "status" in defn.parameters["properties"]["action"]["enum"]
    assert "send" in defn.parameters["properties"]["action"]["enum"]


@pytest.mark.asyncio
async def test_opencode_tool_missing_params():
    bridge = OpenCodeBridge(base_url="http://127.0.0.1:4096")
    tool = OpenCodeBridgeTool(bridge=bridge)

    # Missing session_id for send
    res = await tool.execute({"action": "send", "prompt": "hi"}, user_id=1)
    assert res.is_error
    assert "session_id is required" in res.content

    # Missing prompt for send
    res = await tool.execute({"action": "send", "session_id": "ses_123"}, user_id=1)
    assert res.is_error
    assert "prompt is required" in res.content


# ---------------------------------------------------------------------------
# FileEditTool Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_file_edit_tool_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = "test.py"
        full_path = os.path.join(tmpdir, test_file)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write("def add(a, b):\n    return a - b\n")

        edit_tool = FileEditTool(root_dir=tmpdir, read_only=False)
        res = await edit_tool.execute({
            "file_path": test_file,
            "old_text": "return a - b",
            "new_text": "return a + b",
        }, user_id=1)

        assert not res.is_error
        assert "replacement(s)" in res.content

        with open(full_path, "r", encoding="utf-8") as f:
            updated = f.read()
        assert "return a + b" in updated


@pytest.mark.asyncio
async def test_file_edit_tool_not_found():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = "test.py"
        full_path = os.path.join(tmpdir, test_file)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write("hello world\n")

        edit_tool = FileEditTool(root_dir=tmpdir, read_only=False)
        res = await edit_tool.execute({
            "file_path": test_file,
            "old_text": "foo bar",
            "new_text": "baz",
        }, user_id=1)

        assert res.is_error
        assert "not found" in res.content


@pytest.mark.asyncio
async def test_file_edit_tool_read_only_rejection():
    with tempfile.TemporaryDirectory() as tmpdir:
        edit_tool = FileEditTool(root_dir=tmpdir, read_only=True)
        res = await edit_tool.execute({
            "file_path": "any.txt",
            "old_text": "a",
            "new_text": "b",
        }, user_id=1)
        assert res.is_error
        assert "read-only" in res.content


@pytest.mark.asyncio
async def test_file_edit_tool_path_traversal():
    with tempfile.TemporaryDirectory() as tmpdir:
        edit_tool = FileEditTool(root_dir=tmpdir, read_only=False)
        res = await edit_tool.execute({
            "file_path": "../outside.txt",
            "old_text": "a",
            "new_text": "b",
        }, user_id=1)
        assert res.is_error
        assert "Security Violation" in res.content


# ---------------------------------------------------------------------------
# FileDeleteTool Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_file_delete_tool_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = "to_delete.txt"
        full_path = os.path.join(tmpdir, test_file)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write("temp data")

        del_tool = FileDeleteTool(root_dir=tmpdir, read_only=False)
        assert del_tool.definition.risk_level == RiskLevel.HIGH
        assert del_tool.definition.permission == PermissionLevel.DESTRUCTIVE

        res = await del_tool.execute({"file_path": test_file}, user_id=1)
        assert not res.is_error
        assert not os.path.exists(full_path)
