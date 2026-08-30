"""Tool registry and execution coordinator with permission and risk-level controls."""

from typing import Any, Dict, List, Optional
from src.domain.tool import BaseTool, PermissionLevel, RiskLevel, ToolDefinition, ToolResult


class ToolRegistry:
    """Central repository of executable tools with permission evaluation."""

    def __init__(self, require_confirmation_for_destructive: bool = True):
        self._tools: Dict[str, BaseTool] = {}
        self.require_confirmation_for_destructive = require_confirmation_for_destructive

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        self._tools[tool.definition.name] = tool

    def get(self, name: str) -> Optional[BaseTool]:
        """Retrieve tool by name."""
        return self._tools.get(name)

    def list_definitions(self) -> List[ToolDefinition]:
        """Return list of all registered tool definitions."""
        return [tool.definition for tool in self._tools.values()]

    def is_destructive(self, name: str) -> bool:
        """Check if tool has DESTRUCTIVE permission or CRITICAL risk."""
        tool = self.get(name)
        if not tool:
            return False
        defn = tool.definition
        return (
            defn.permission == PermissionLevel.DESTRUCTIVE
            or defn.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
            or defn.requires_confirmation
        )

    async def execute(self, name: str, arguments: Dict[str, Any], user_id: int) -> ToolResult:
        """Execute tool safely with exception capture."""
        tool = self.get(name)
        if not tool:
            return ToolResult(
                content=f"Error: Tool '{name}' not found in registry.",
                is_error=True
            )

        try:
            return await tool.execute(arguments, user_id=user_id)
        except Exception as e:
            return ToolResult(
                content=f"Tool Execution Error ({name}): {str(e)}",
                is_error=True
            )
