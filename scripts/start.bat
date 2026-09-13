@echo off
REM Telegram Agent Platform -- start the agent runtime (Windows cmd).
REM
REM   scripts\start.bat            foreground; Ctrl+C stops it
REM   scripts\start.bat --detach   background
REM   scripts\start.bat --force    take over a stale or live PID file
REM
REM A missing virtual environment or missing dependencies are bootstrapped through
REM scripts\setup.bat. Every argument is forwarded to "python -m src start" and
REM the child's exit code is propagated to the caller.

setlocal
cd /d "%~dp0\.."
title Telegram Agent - Start

if exist ".venv\Scripts\python.exe" goto :check_deps
if exist ".venv\bin\python" goto :venv_foreign

echo [INFO] Virtual environment not found. Running setup first ...
set "AGENT_LAUNCHER_NO_PAUSE=1"
call "%~dp0setup.bat"
set "SETUP_CODE=%ERRORLEVEL%"
if not "%SETUP_CODE%"=="0" goto :setup_failed
if not exist ".venv\Scripts\python.exe" goto :setup_failed

:check_deps
set "VENV_PY=.venv\Scripts\python.exe"
"%VENV_PY%" -c "import httpx, pydantic, yaml, aiosqlite" >nul 2>nul
if not errorlevel 1 goto :run

echo [INFO] Dependencies are missing. Running setup first ...
set "AGENT_LAUNCHER_NO_PAUSE=1"
call "%~dp0setup.bat"
set "SETUP_CODE=%ERRORLEVEL%"
if not "%SETUP_CODE%"=="0" goto :setup_failed

:run
echo [INFO] Starting Telegram Agent ...
"%VENV_PY%" -m src start %*
set "AGENT_CODE=%ERRORLEVEL%"
if not "%AGENT_CODE%"=="0" goto :run_failed
exit /b 0

REM ======================= failure paths ===============================
:run_failed
echo.
echo [ERROR] The agent exited with code %AGENT_CODE%.
echo         Run scripts\doctor.bat for a full diagnosis.
pause
exit /b %AGENT_CODE%

:setup_failed
echo.
echo [ERROR] Setup did not complete (exit code %SETUP_CODE%).
echo         Run scripts\setup.bat manually, then retry scripts\start.bat.
pause
exit /b %SETUP_CODE%

:venv_foreign
echo [ERROR] The .venv folder was created by a Linux/macOS Python interpreter.
echo         Windows cannot use it. Delete the .venv folder and run scripts\setup.bat again.
pause
exit /b 1
