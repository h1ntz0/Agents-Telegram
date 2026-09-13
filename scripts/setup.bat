@echo off
REM Telegram Agent Platform -- environment bootstrap + setup wizard launcher (Windows cmd).
REM
REM   scripts\setup.bat                    interactive wizard
REM   scripts\setup.bat --advanced
REM   scripts\setup.bat -y --bot-token 123:ABC --provider openai --model gpt-4o-mini --api-key sk-...
REM
REM Every argument is forwarded verbatim to "python -m src setup" and the wizard's
REM exit code becomes this script's exit code.

setlocal
cd /d "%~dp0\.."
title Telegram Agent Setup

echo =========================================
echo   Telegram Agent - Windows Setup Wizard
echo =========================================
echo.

REM ---- 1. Reuse a working .venv, whichever shell created it ------------
if exist ".venv\Scripts\python.exe" goto :venv_check
if exist ".venv\bin\python" goto :venv_foreign

REM ---- 2. Locate a Python 3.12+ to build the virtual environment with --
set "PYTHON_CMD="
call :try_python "py -3.14"
call :try_python "py -3.13"
call :try_python "py -3.12"
call :try_python "py -3"
call :try_python "python"
call :try_python "python3"
if not defined PYTHON_CMD goto :no_python

:create_venv
echo [INFO] Creating virtual environment in .venv with "%PYTHON_CMD%" ...
%PYTHON_CMD% -m venv .venv
if errorlevel 1 goto :venv_failed
if not exist ".venv\Scripts\python.exe" goto :venv_failed

REM ---- 3. Validate the interpreter inside the virtual environment -----
:venv_check
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info>=(3,12) else 1)" >nul 2>nul
if errorlevel 1 goto :venv_old

:venv_ready
set "VENV_PY=.venv\Scripts\python.exe"
echo [OK] Using Python: %VENV_PY%
echo.

REM ---- 4. Ensure pip exists -------------------------------------------
"%VENV_PY%" -m pip --version >nul 2>nul
if not errorlevel 1 goto :pip_ready
echo [INFO] Bootstrapping pip with ensurepip ...
"%VENV_PY%" -m ensurepip --upgrade >nul 2>nul
:pip_ready

REM ---- 5. Install dependencies ----------------------------------------
"%VENV_PY%" -c "import httpx, pydantic, yaml, aiosqlite" >nul 2>nul
if not errorlevel 1 goto :deps_ready

echo [INFO] Installing project dependencies ^(this may take a minute^) ...
"%VENV_PY%" -m pip install --quiet --upgrade pip
"%VENV_PY%" -m pip install --quiet -e .
if not errorlevel 1 goto :verify_deps
echo [WARN] Editable install failed. Installing the runtime packages directly ...
"%VENV_PY%" -m pip install --quiet "pydantic>=2.7.0" "pyyaml>=6.0.1" "python-dotenv>=1.0.1" "httpx>=0.27.0" "aiosqlite>=0.20.0"

:verify_deps
"%VENV_PY%" -c "import httpx, pydantic, yaml, aiosqlite" >nul 2>nul
if errorlevel 1 goto :deps_failed

:deps_ready

REM ---- 6. Launch the wizard, forwarding every argument ----------------
echo.
echo [INFO] Launching Setup Wizard ...
echo.
"%VENV_PY%" -m src setup %*
set "WIZARD_CODE=%ERRORLEVEL%"
if not "%WIZARD_CODE%"=="0" goto :wizard_failed

echo.
echo =========================================
echo   Setup complete.
echo   Start the agent with:  scripts\start.bat
echo =========================================
pause
exit /b 0

REM ======================= failure paths ===============================
:wizard_failed
echo.
echo [ERROR] The setup wizard exited with code %WIZARD_CODE%.
echo         Fix the problem above, then run scripts\setup.bat again.
pause
exit /b %WIZARD_CODE%

:venv_old
echo [ERROR] The interpreter inside .venv is older than Python 3.12.
echo         Delete the .venv folder and run scripts\setup.bat again.
goto :fail

:venv_foreign
echo [ERROR] The .venv folder was created by a Linux/macOS Python interpreter.
echo         Windows cannot use it. Delete the .venv folder and run this script again.
goto :fail

:venv_failed
echo [ERROR] Could not create the virtual environment.
echo         Do not run this from C:\Windows\system32 - use your home folder.
goto :fail

:deps_failed
echo [ERROR] Dependency installation failed.
echo         Check your internet connection and run scripts\setup.bat again.
goto :fail

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
if defined PYTHON_CMD goto :create_venv

:no_python_winget
where winget >nul 2>nul
if errorlevel 1 goto :no_python_manual
echo [INFO] Installing Python 3.12 via winget ...
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
call :try_python "py -3.12"
if defined PYTHON_CMD goto :create_venv

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
echo Setup did not finish. Fix the problem above, then run scripts\setup.bat again.
pause
exit /b 1
