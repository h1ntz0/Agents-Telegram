@echo off
REM Telegram Agent Platform -- environment diagnosis (Windows cmd).
REM
REM   scripts\doctor.bat            run every check
REM
REM A missing virtual environment or missing dependencies are bootstrapped through
REM scripts\setup.bat. Arguments are forwarded to "python -m src doctor" and the
REM child's exit code is propagated: 0 when every check passes, 1 on any FAIL.

setlocal
cd /d "%~dp0\.."
title Telegram Agent - Doctor

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
echo [INFO] Running diagnostics ...
"%VENV_PY%" -m src doctor %*
set "DOCTOR_CODE=%ERRORLEVEL%"
if not "%DOCTOR_CODE%"=="0" goto :run_failed
exit /b 0

REM ======================= failure paths ===============================
:run_failed
echo.
echo [ERROR] At least one diagnostic check failed (exit code %DOCTOR_CODE%).
echo         Fix the failing checks above, then run scripts\doctor.bat again.
pause
exit /b %DOCTOR_CODE%

:setup_failed
echo.
echo [ERROR] Setup did not complete (exit code %SETUP_CODE%).
echo         Run scripts\setup.bat manually, then retry scripts\doctor.bat.
pause
exit /b %SETUP_CODE%

:venv_foreign
echo [ERROR] The .venv folder was created by a Linux/macOS Python interpreter.
echo         Windows cannot use it. Delete the .venv folder and run scripts\setup.bat again.
pause
exit /b 1
