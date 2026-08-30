@echo off
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Please run setup.bat first.
    exit /b 1
)
.venv\Scripts\python.exe -m src doctor
