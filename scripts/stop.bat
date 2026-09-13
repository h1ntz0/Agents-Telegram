@echo off
REM Telegram Agent Platform -- stop the background runtime (Windows cmd).
REM
REM   scripts\stop.bat
REM
REM This is a thin forwarder: "python -m src stop" owns the PID file and the
REM process shutdown, so the CLI stays the single source of truth. The child's
REM exit code is propagated (0 when stopped or when nothing was running).

setlocal
cd /d "%~dp0\.."

set "PYTHON_EXEC="
if exist ".venv\Scripts\python.exe" set "PYTHON_EXEC=.venv\Scripts\python.exe"
if not defined PYTHON_EXEC if exist ".venv\bin\python" set "PYTHON_EXEC=.venv\bin\python"
if not defined PYTHON_EXEC where python3 >nul 2>nul
if not defined PYTHON_EXEC if not errorlevel 1 set "PYTHON_EXEC=python3"
if not defined PYTHON_EXEC where python >nul 2>nul
if not defined PYTHON_EXEC if not errorlevel 1 set "PYTHON_EXEC=python"
if not defined PYTHON_EXEC goto :no_python

"%PYTHON_EXEC%" -m src stop %*
set "STOP_CODE=%ERRORLEVEL%"
if not "%STOP_CODE%"=="0" goto :stop_failed
exit /b 0

:stop_failed
echo.
echo [ERROR] The agent could not be stopped (exit code %STOP_CODE%).
echo         Check the messages above, then run scripts\doctor.bat.
pause
exit /b %STOP_CODE%

:no_python
echo [ERROR] No Python interpreter was found.
echo         Run scripts\setup.bat first.
pause
exit /b 1
