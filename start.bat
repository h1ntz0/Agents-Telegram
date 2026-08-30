@echo off
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Virtual environment not found. Running setup first...
    call setup.bat
)
echo [INFO] Starting Telegram Agent Runtime on Windows...
.venv\Scripts\python.exe -m src start
