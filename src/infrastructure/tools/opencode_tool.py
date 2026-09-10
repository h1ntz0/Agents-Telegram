"""Tool wrapper exposing the OpenCode session bridge to the AI model."""

from __future__ import annotations

from typing import Any, Dict
from src.domain.tool import BaseTool, PermissionLevel, RiskLevel, ToolDefinition, ToolResult
from src.infrastructure.opencode.bridge import OpenCodeBridge, OpenCodeError


class OpenCodeBridgeTool(BaseTool):
    """Lets the agent list, inspect, and prompt a locally running OpenCode session."""

    def __init__(self, bridge: OpenCodeBridge):
        self.bridge = bridge

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="opencode_session",
            description=(
                "Interact with a locally running OpenCode coding agent (opencode serve). "
                "Use action='list' to list sessions, 'status' for server health, "
                "'messages' to read recent turns of a session (needs session_id), or "
                "'send' to delegate a coding task to an existing session (needs session_id + prompt). "
                "Use this for real software engineering tasks: editing files, running tests, refactoring."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "list", "messages", "send"],
                        "description": "Operation to perform."
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Target OpenCode session ID (required for messages/send)."
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Coding task/instruction to send (required for action='send')."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of recent messages to fetch (default 10).",
                        "default": 10
                    }
                },
                "required": ["action"]
            },
            permission=PermissionLevel.EXECUTE,
            risk_level=RiskLevel.MEDIUM,
            requires_confirmation=False
        )

    async def execute(self, arguments: Dict[str, Any], user_id: int) -> ToolResult:
        action = (arguments.get("action") or "").strip().lower()
        session_id = (arguments.get("session_id") or "").strip()
        prompt = arguments.get("prompt", "")
        limit = int(arguments.get("limit", 10) or 10)

        try:
            if action == "status":
                url = await self.bridge.auto_discover_server()
                if not url:
                    return ToolResult(
                        content=(
                            "OpenCode server is not running. Start it with "
                            "`opencode serve --port 4096` and retry."
                        ),
                        is_error=True
                    )
                return ToolResult(content=f"OpenCode server is available at {url}.")

            if action == "list":
                await self.bridge.auto_discover_server()
                sessions = await self.bridge.list_sessions()
                if not sessions:
                    return ToolResult(content="No OpenCode sessions found.")
                lines = []
                for s in sessions[:25]:
                    model = s.get("model") or {}
                    model_label = model.get("id") or model.get("modelID") or "?"
                    lines.append(
                        f"- {s.get('id')} | {s.get('title', '(untitled)')} | "
                        f"agent={s.get('agent', '?')} | model={model_label}"
                    )
                return ToolResult(content="OpenCode sessions:\n" + "\n".join(lines))

            if action == "messages":
                if not session_id:
                    return ToolResult(content="session_id is required for action='messages'.", is_error=True)
                messages = await self.bridge.get_messages(session_id, limit=limit)
                if not messages:
                    return ToolResult(content=f"Session {session_id} has no messages.")
                rendered = []
                for m in messages:
                    info = m.get("info", {})
                    role = info.get("role", "?")
                    texts = [
                        p.get("text", "")
                        for p in m.get("parts", [])
                        if isinstance(p, dict) and p.get("type") == "text"
                    ]
                    body = "\n".join(t for t in texts if t).strip()
                    if body:
                        rendered.append(f"[{role}] {body[:1500]}")
                return ToolResult(content="\n\n".join(rendered) if rendered else "No text content.")

            if action == "send":
                if not session_id:
                    return ToolResult(content="session_id is required for action='send'.", is_error=True)
                if not prompt.strip():
                    return ToolResult(content="prompt is required for action='send'.", is_error=True)
                reply = await self.bridge.send_message(session_id, prompt)
                return ToolResult(content=reply)

            return ToolResult(content=f"Unknown action '{action}'.", is_error=True)

        except OpenCodeError as e:
            return ToolResult(content=f"OpenCode error: {str(e)}", is_error=True)
        except Exception as e:
            return ToolResult(content=f"OpenCode tool failure: {str(e)}", is_error=True)
