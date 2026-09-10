"""Shell command execution tool with sandboxing and safety filters (cross-platform)."""

import asyncio
import platform
import re
import shutil
from typing import Any, Dict
from src.domain.tool import BaseTool, PermissionLevel, RiskLevel, ToolDefinition, ToolResult
from src.infrastructure.security.prompt_guard import wrap_untrusted_content

DANGEROUS_COMMAND_PATTERNS = [
    re.compile(r"\brm\s+-[a-zA-Z]*r", re.IGNORECASE),
    re.compile(r"\bmkfs\b", re.IGNORECASE),
    re.compile(r"\bdd\s+if=", re.IGNORECASE),
    re.compile(r"\bshutdown\b", re.IGNORECASE),
    re.compile(r"\breboot\b", re.IGNORECASE),
    re.compile(r"\bformat\b", re.IGNORECASE),
    re.compile(r"\bgit\s+push\s+.*--force", re.IGNORECASE),
    re.compile(r"\bdrop\s+database\b", re.IGNORECASE),
]


class ShellTool(BaseTool):
    """Executes system terminal commands with execution controls."""

    def __init__(self, enabled: bool = False, allow_destructive: bool = False, timeout: float = 30.0):
        self.enabled = enabled
        self.allow_destructive = allow_destructive
        self.timeout = timeout

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="shell_execute",
            description="Execute shell commands on the local machine (cross-platform, requires explicit enabling).",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to run."
                    }
                },
                "required": ["command"]
            },
            permission=PermissionLevel.EXECUTE,
            risk_level=RiskLevel.HIGH,
            requires_confirmation=True
        )

    @staticmethod
    def _build_argv(command: str) -> list:
        """Build a cross-platform argv without using shell=True."""
        system = platform.system().lower()
        if system == "windows":
            pwsh = shutil.which("pwsh")
            if pwsh:
                return [pwsh, "-NoProfile", "-Command", command]
            powershell = shutil.which("powershell")
            if powershell:
                return [powershell, "-NoProfile", "-Command", command]
            cmd_exe = shutil.which("cmd") or "cmd.exe"
            return [cmd_exe, "/c", command]
        bash = shutil.which("bash")
        if bash:
            return [bash, "-c", command]
        sh = shutil.which("sh") or "sh"
        return [sh, "-c", command]

    async def execute(self, arguments: Dict[str, Any], user_id: int) -> ToolResult:
        if not self.enabled:
            return ToolResult(
                content="Shell execution is disabled by configuration (ALLOW_SHELL=false).",
                is_error=True
            )

        command = arguments.get("command", "").strip()
        if not command:
            return ToolResult(content="Command cannot be empty.", is_error=True)

        if not self.allow_destructive:
            for pat in DANGEROUS_COMMAND_PATTERNS:
                if pat.search(command):
                    return ToolResult(
                        content=f"Destructive command pattern detected in '{command}'. Execution rejected.",
                        is_error=True
                    )

        argv = self._build_argv(command)
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout_b, stderr_b = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
            stdout = stdout_b.decode("utf-8", errors="replace")[:10000]
            stderr = stderr_b.decode("utf-8", errors="replace")[:10000]

            output = f"Exit code: {process.returncode}\n"
            if stdout:
                output += f"STDOUT:\n{stdout}\n"
            if stderr:
                output += f"STDERR:\n{stderr}\n"

            safe_output = wrap_untrusted_content(output, source=f"Command: {command}")
            return ToolResult(
                content=safe_output,
                is_error=(process.returncode != 0)
            )
        except asyncio.TimeoutError:
            return ToolResult(content=f"Command execution timed out after {self.timeout}s.", is_error=True)
        except Exception as e:
            return ToolResult(content=f"Error executing shell command: {str(e)}", is_error=True)
