@echo off
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Virtual environment not found. Running setup first...
    call "%~dp0setup.bat"
)

REM Verify dependencies
.venv\Scripts\python.exe -c "import httpx, pydantic, yaml, aiosqlite" >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [INFO] Installing missing dependencies...
    .venv\Scripts\python.exe -m pip install --quiet -e .
)

echo [INFO] Starting Telegram Agent Runtime on Windows...
.venv\Scripts\python.exe -m src start
