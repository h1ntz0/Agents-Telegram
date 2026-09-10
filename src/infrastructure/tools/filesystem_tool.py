"""Filesystem inspection and modification tools with strict directory sandboxing."""

import os
from typing import Any, Dict
from src.domain.tool import BaseTool, PermissionLevel, RiskLevel, ToolDefinition, ToolResult
from src.infrastructure.security.prompt_guard import wrap_untrusted_content


def is_path_safe(base_dir: str, target_path: str) -> bool:
    """Verify that target_path resides within base_dir (prevent path traversal)."""
    abs_base = os.path.abspath(base_dir)
    abs_target = os.path.abspath(os.path.join(base_dir, target_path))
    try:
        common = os.path.commonpath([abs_base, abs_target])
        return common == abs_base
    except Exception:
        return False


class FileReadTool(BaseTool):
    """Safely reads file contents within the allowed workspace sandbox."""

    def __init__(self, root_dir: str = "./data"):
        self.root_dir = root_dir

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="file_read",
            description="Read the text content of a file within the allowed directory.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Relative path to the file."
                    }
                },
                "required": ["file_path"]
            },
            permission=PermissionLevel.READ,
            risk_level=RiskLevel.LOW,
            requires_confirmation=False
        )

    async def execute(self, arguments: Dict[str, Any], user_id: int) -> ToolResult:
        rel_path = arguments.get("file_path", "").strip()
        if not rel_path:
            return ToolResult(content="File path cannot be empty.", is_error=True)

        if not is_path_safe(self.root_dir, rel_path):
            return ToolResult(
                content="Security Violation: Access outside the designated root directory is prohibited.",
                is_error=True
            )

        full_path = os.path.abspath(os.path.join(self.root_dir, rel_path))
        if not os.path.exists(full_path):
            return ToolResult(content=f"File not found: {rel_path}", is_error=True)

        if not os.path.isfile(full_path):
            return ToolResult(content=f"Path is not a regular file: {rel_path}", is_error=True)

        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(50000)  # Max 50KB read limit
            safe_content = wrap_untrusted_content(content, source=f"File: {rel_path}")
            return ToolResult(content=safe_content)
        except Exception as e:
            return ToolResult(content=f"Error reading file: {str(e)}", is_error=True)


class FileWriteTool(BaseTool):
    """Safely writes or updates file contents within the allowed directory."""

    def __init__(self, root_dir: str = "./data", read_only: bool = False):
        self.root_dir = root_dir
        self.read_only = read_only

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="file_write",
            description="Write or overwrite text content to a file in the allowed directory.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Relative path to target file."
                    },
                    "content": {
                        "type": "string",
                        "description": "Text content to write."
                    }
                },
                "required": ["file_path", "content"]
            },
            permission=PermissionLevel.WRITE,
            risk_level=RiskLevel.MEDIUM,
            requires_confirmation=False
        )

    async def execute(self, arguments: Dict[str, Any], user_id: int) -> ToolResult:
        if self.read_only:
            return ToolResult(
                content="Filesystem is currently configured in read-only mode.",
                is_error=True
            )

        rel_path = arguments.get("file_path", "").strip()
        content = arguments.get("content", "")

        if not rel_path:
            return ToolResult(content="File path cannot be empty.", is_error=True)

        if not is_path_safe(self.root_dir, rel_path):
            return ToolResult(
                content="Security Violation: Access outside the designated root directory is prohibited.",
                is_error=True
            )

        full_path = os.path.abspath(os.path.join(self.root_dir, rel_path))
        try:
            parent = os.path.dirname(full_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            return ToolResult(content=f"Successfully wrote {len(content)} characters to {rel_path}.")
        except Exception as e:
            return ToolResult(content=f"Error writing file: {str(e)}", is_error=True)



class DirectoryListTool(BaseTool):
    """Safely lists files and directories within the designated sandbox."""

    def __init__(self, root_dir: str = "./data"):
        self.root_dir = root_dir

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="dir_list",
            description="List contents of a directory in the allowed workspace.",
            parameters={
                "type": "object",
                "properties": {
                    "dir_path": {
                        "type": "string",
                        "description": "Relative directory path. Leave blank for root.",
                        "default": ""
                    }
                }
            },
            permission=PermissionLevel.READ,
            risk_level=RiskLevel.LOW,
            requires_confirmation=False
        )

    async def execute(self, arguments: Dict[str, Any], user_id: int) -> ToolResult:
        rel_path = arguments.get("dir_path", "").strip()
        if not is_path_safe(self.root_dir, rel_path):
            return ToolResult(
                content="Security Violation: Access outside designated root directory is prohibited.",
                is_error=True
            )

        full_path = os.path.abspath(os.path.join(self.root_dir, rel_path))
        if not os.path.exists(full_path):
            return ToolResult(content=f"Directory not found: {rel_path or '.'}", is_error=True)

        if not os.path.isdir(full_path):
            return ToolResult(content=f"Path is not a directory: {rel_path}", is_error=True)

        try:
            entries = sorted(os.listdir(full_path))[:100]
            lines = []
            for e in entries:
                sub = os.path.join(full_path, e)
                kind = "DIR" if os.path.isdir(sub) else "FILE"
                lines.append(f"[{kind}] {e}")
            result_str = "\n".join(lines) if lines else "(empty directory)"
            return ToolResult(content=wrap_untrusted_content(result_str, source=f"Directory: {rel_path or '.'}"))
        except Exception as e:
            return ToolResult(content=f"Error reading directory: {str(e)}", is_error=True)


class FileEditTool(BaseTool):
    """Search-and-replace text edits on a file within the allowed directory."""

    def __init__(self, root_dir: str = "./data", read_only: bool = False):
        self.root_dir = root_dir
        self.read_only = read_only

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="file_edit",
            description="Search for exact text in a file and replace it with new text. Supports single or bulk (all occurrences) replacement.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Relative path to target file."
                    },
                    "old_text": {
                        "type": "string",
                        "description": "Exact text to search for."
                    },
                    "new_text": {
                        "type": "string",
                        "description": "Replacement text."
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace all occurrences. Default: False (replace first only).",
                        "default": False
                    }
                },
                "required": ["file_path", "old_text", "new_text"]
            },
            permission=PermissionLevel.WRITE,
            risk_level=RiskLevel.MEDIUM,
            requires_confirmation=False
        )

    async def execute(self, arguments: Dict[str, Any], user_id: int) -> ToolResult:
        if self.read_only:
            return ToolResult(
                content="Filesystem is currently configured in read-only mode.",
                is_error=True
            )

        rel_path = arguments.get("file_path", "").strip()
        old_text = arguments.get("old_text", "")
        new_text = arguments.get("new_text", "")
        replace_all = arguments.get("replace_all", False)

        if not rel_path:
            return ToolResult(content="File path cannot be empty.", is_error=True)
        if not old_text:
            return ToolResult(content="old_text cannot be empty.", is_error=True)
        if old_text == new_text:
            return ToolResult(content="old_text and new_text are identical. Nothing to replace.", is_error=True)

        if not is_path_safe(self.root_dir, rel_path):
            return ToolResult(
                content="Security Violation: Access outside the designated root directory is prohibited.",
                is_error=True
            )

        full_path = os.path.abspath(os.path.join(self.root_dir, rel_path))
        if not os.path.exists(full_path):
            return ToolResult(content=f"File not found: {rel_path}", is_error=True)
        if not os.path.isfile(full_path):
            return ToolResult(content=f"Path is not a regular file: {rel_path}", is_error=True)

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            return ToolResult(content=f"Error reading file: {str(e)}", is_error=True)

        count = content.count(old_text)
        if count == 0:
            return ToolResult(
                content=f"old_text not found in {rel_path}. Use file_read tool to see current contents first.",
                is_error=True
            )

        if count == 1 or replace_all:
            new_content = content.replace(old_text, new_text)
        else:
            new_content = content.replace(old_text, new_text, 1)

        try:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(new_content)
        except Exception as e:
            return ToolResult(content=f"Error writing file: {str(e)}", is_error=True)

        msg = f"Made {count} replacement(s) in {rel_path}."
        if count > 1 and not replace_all:
            msg += f" Found {count} occurrences; replaced the first one only. Set replace_all=True to replace all."
        return ToolResult(content=msg)


class FileDeleteTool(BaseTool):
    """Delete a single file within the allowed directory."""

    def __init__(self, root_dir: str = "./data", read_only: bool = False):
        self.root_dir = root_dir
        self.read_only = read_only

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="file_delete",
            description="Delete a single file in the workspace.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Relative path to the file to delete."
                    }
                },
                "required": ["file_path"]
            },
            permission=PermissionLevel.DESTRUCTIVE,
            risk_level=RiskLevel.HIGH,
            requires_confirmation=True
        )

    async def execute(self, arguments: Dict[str, Any], user_id: int) -> ToolResult:
        if self.read_only:
            return ToolResult(
                content="Filesystem is currently configured in read-only mode.",
                is_error=True
            )

        rel_path = arguments.get("file_path", "").strip()
        if not rel_path:
            return ToolResult(content="File path cannot be empty.", is_error=True)

        if not is_path_safe(self.root_dir, rel_path):
            return ToolResult(
                content="Security Violation: Access outside the designated root directory is prohibited.",
                is_error=True
            )

        full_path = os.path.abspath(os.path.join(self.root_dir, rel_path))
        if not os.path.exists(full_path):
            return ToolResult(content=f"File not found: {rel_path}", is_error=True)
        if not os.path.isfile(full_path):
            return ToolResult(content=f"Path is not a regular file: {rel_path}", is_error=True)

        try:
            os.remove(full_path)
            return ToolResult(content=f"Successfully deleted {rel_path}.")
        except Exception as e:
            return ToolResult(content=f"Error deleting file: {str(e)}", is_error=True)


