@echo off
if exist "data\agent.pid" (
    set /p AGENT_PID=<data\agent.pid
    taskkill /F /PID !AGENT_PID! 2>nul
    del data\agent.pid 2>nul
    echo [INFO] Agent stopped.
) else (
    echo [INFO] No active agent PID file found.
)
