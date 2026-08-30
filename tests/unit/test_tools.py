"""Unit tests for tool implementations, sandboxing, and execution restrictions."""

import os
import pytest
from src.infrastructure.tools.filesystem_tool import DirectoryListTool, FileReadTool, FileWriteTool
from src.infrastructure.tools.registry import ToolRegistry
from src.infrastructure.tools.shell_tool import ShellTool
from src.infrastructure.tools.web_search import WebSearchTool


@pytest.mark.asyncio
async def test_filesystem_read_and_write(tmp_path):
    root_dir = str(tmp_path / "sandbox")
    os.makedirs(root_dir, exist_ok=True)

    writer = FileWriteTool(root_dir=root_dir, read_only=False)
    reader = FileReadTool(root_dir=root_dir)
    lister = DirectoryListTool(root_dir=root_dir)

    # 1. Write file
    write_res = await writer.execute({"file_path": "notes.txt", "content": "Hello Sandboxed World"}, user_id=1)
    assert not write_res.is_error
    assert "Successfully wrote" in write_res.content

    # 2. Read file
    read_res = await reader.execute({"file_path": "notes.txt"}, user_id=1)
    assert not read_res.is_error
    assert "Hello Sandboxed World" in read_res.content

    # 3. List directory
    list_res = await lister.execute({"dir_path": ""}, user_id=1)
    assert not list_res.is_error
    assert "notes.txt" in list_res.content


@pytest.mark.asyncio
async def test_filesystem_path_traversal_blocked(tmp_path):
    root_dir = str(tmp_path / "sandbox")
    os.makedirs(root_dir, exist_ok=True)

    reader = FileReadTool(root_dir=root_dir)
    res = await reader.execute({"file_path": "../../etc/passwd"}, user_id=1)
    assert res.is_error
    assert "Security Violation" in res.content


@pytest.mark.asyncio
async def test_shell_tool_disabled_by_default():
    shell = ShellTool(enabled=False)
    res = await shell.execute({"command": "ls -la"}, user_id=1)
    assert res.is_error
    assert "disabled" in res.content


@pytest.mark.asyncio
async def test_shell_tool_blocks_destructive_commands():
    shell = ShellTool(enabled=True, allow_destructive=False)
    res = await shell.execute({"command": "rm -rf /tmp/data"}, user_id=1)
    assert res.is_error
    assert "Destructive command pattern detected" in res.content


@pytest.mark.asyncio
async def test_tool_registry():
    registry = ToolRegistry(require_confirmation_for_destructive=True)
    shell = ShellTool(enabled=True)
    registry.register(shell)

    assert registry.get("shell_execute") is not None
    assert registry.is_destructive("shell_execute") is True
