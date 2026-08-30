"""Domain entities and value objects for Agent and Session."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class AgentState(str, Enum):
    IDLE = "idle"
    PROCESSING = "processing"
    WAITING_CONFIRMATION = "waiting_confirmation"
    ERROR = "error"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResponse:
    tool_call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    role: Role
    content: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_responses: List[ToolResponse] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PendingConfirmation:
    action_id: str
    tool_name: str
    arguments: Dict[str, Any]
    risk_level: str
    description: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Session:
    session_id: str
    user_id: int
    chat_id: int
    state: AgentState = AgentState.IDLE
    messages: List[Message] = field(default_factory=list)
    pending_confirmation: Optional[PendingConfirmation] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def add_message(self, message: Message) -> None:
        self.messages.append(message)
        self.updated_at = datetime.now(timezone.utc)

    def clear_history(self) -> None:
        self.messages.clear()
        self.pending_confirmation = None
        self.state = AgentState.IDLE
        self.updated_at = datetime.now(timezone.utc)
