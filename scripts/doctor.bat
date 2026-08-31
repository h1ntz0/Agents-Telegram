@echo off
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Please run scripts\setup.bat first.
    exit /b 1
)

.venv\Scripts\python.exe -m src doctor %*
