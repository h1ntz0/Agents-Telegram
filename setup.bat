@echo off
setlocal enabledelayedexpansion

echo =========================================
echo   Telegram Agent - Windows Setup Wizard
echo =========================================

REM 1. Check Python
where py >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set PYTHON_CMD=py -3.12
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% equ 0 (
        set PYTHON_CMD=python
    ) else (
        echo [ERROR] Python 3.12+ is not installed or not found in PATH.
        echo Please install Python 3.12 from https://www.python.org/downloads/
        exit /b 1
    )
)

REM 2. Virtual Environment
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Creating virtual environment in .venv...
    %PYTHON_CMD% -m venv .venv
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        exit /b 1
    )
)

REM 3. Install & Verify Dependencies
.venv\Scripts\python.exe -c "import httpx, pydantic, yaml, aiosqlite" >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [INFO] Installing project dependencies automatically...
    .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
    .venv\Scripts\python.exe -m pip install --quiet -e .
)

REM 4. Run Setup
echo [INFO] Launching Setup Wizard...
.venv\Scripts\python.exe -m src setup
