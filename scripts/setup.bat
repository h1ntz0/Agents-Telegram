@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0\.."
title Telegram Agent Setup

echo =========================================
echo   Telegram Agent - Windows Setup Wizard
echo =========================================
echo.

REM ---- 1. Locate a working Python 3.12+ -------------------------------
set "PYTHON_CMD="
call :try_python "py -3.14"
call :try_python "py -3.13"
call :try_python "py -3.12"
call :try_python "py -3"
call :try_python "python"
call :try_python "python3"

if not defined PYTHON_CMD goto :no_python

:have_python
echo [OK] Using Python: %PYTHON_CMD%
echo.

REM ---- 2. Virtual environment -----------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Creating virtual environment in .venv ...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create the virtual environment.
        echo         Do not run this from C:\Windows\system32 - use your home folder.
        goto :fail
    )
)

set "VENV_PY=.venv\Scripts\python.exe"

REM ---- 3. Ensure pip exists -------------------------------------------
"%VENV_PY%" -m pip --version >nul 2>nul
if errorlevel 1 (
    echo [INFO] Bootstrapping pip ...
    "%VENV_PY%" -m ensurepip --upgrade >nul 2>nul
)

REM ---- 4. Install dependencies ----------------------------------------
"%VENV_PY%" -c "import httpx, pydantic, yaml, aiosqlite" >nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing project dependencies ^(this may take a minute^) ...
    "%VENV_PY%" -m pip install --upgrade pip
    "%VENV_PY%" -m pip install -e .
    if errorlevel 1 (
        echo [WARN] Editable install failed. Installing runtime packages directly ...
        "%VENV_PY%" -m pip install "pydantic>=2.7.0" "pyyaml>=6.0.1" "python-dotenv>=1.0.1" "httpx>=0.27.0" "aiosqlite>=0.20.0"
    )
    "%VENV_PY%" -c "import httpx, pydantic, yaml, aiosqlite" >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed.
        echo         Check your internet connection and try again.
        goto :fail
    )
)

REM ---- 5. Launch the interactive setup wizard -------------------------
echo.
echo [INFO] Launching Setup Wizard ...
echo.
"%VENV_PY%" -m src setup
if errorlevel 1 (
    echo.
    echo [ERROR] The setup wizard did not finish successfully.
    goto :fail
)

echo.
echo =========================================
echo   Setup complete.
echo   Start the agent with:  scripts\start.bat
echo =========================================
pause
exit /b 0

REM ======================= helpers =====================================
:try_python
if defined PYTHON_CMD exit /b 0
%~1 -c "import sys; sys.exit(0 if sys.version_info>=(3,12) else 1)" >nul 2>nul
if errorlevel 1 exit /b 0
set "PYTHON_CMD=%~1"
exit /b 0

:no_python
echo [ERROR] Python 3.12 or newer was not found on this computer.
echo.

REM Preferred: the "py" launcher can install a runtime directly
where py >nul 2>nul
if errorlevel 1 goto :no_python_winget
echo [INFO] Installing Python 3.12 via the "py" launcher ...
py install 3.12
call :try_python "py -3.12"
if defined PYTHON_CMD goto :have_python

:no_python_winget
where winget >nul 2>nul
if errorlevel 1 goto :no_python_manual
echo [INFO] Installing Python 3.12 via winget ...
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
call :try_python "py -3.12"
if defined PYTHON_CMD goto :have_python

echo.
echo [INFO] If Python was installed, CLOSE this window, open a NEW one,
echo        then run:  scripts\setup.bat
goto :fail

:no_python_manual
echo Please install Python 3.12+ manually:
echo    1. Open https://www.python.org/downloads/
echo    2. During install, TICK "Add python.exe to PATH"
echo    3. Close this window, open a NEW one, then run: scripts\setup.bat
goto :fail

:fail
echo.
echo Setup did not finish. Fix the problem above, then run setup again.
pause
exit /b 1
