"""Domain interface and types for Agent Tools and Permissions."""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


class PermissionLevel(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    EXECUTE = "EXECUTE"
    DESTRUCTIVE = "DESTRUCTIVE"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class ToolResult:
    content: str
    is_error: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: Dict[str, Any]
    permission: PermissionLevel = PermissionLevel.READ
    risk_level: RiskLevel = RiskLevel.LOW
    requires_confirmation: bool = False


class BaseTool(ABC):
    @property
    @abstractmethod
    def definition(self) -> ToolDefinition:
        """Return the tool metadata and JSON Schema."""
        pass

    @abstractmethod
    async def execute(self, arguments: Dict[str, Any], user_id: int) -> ToolResult:
        """Execute the tool logic safely."""
        pass
