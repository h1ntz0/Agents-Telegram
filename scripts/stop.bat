@echo off
cd /d "%~dp0\.."

set "PYTHON_EXEC=.venv\Scripts\python.exe"
if not exist "%PYTHON_EXEC%" (
    set "PYTHON_EXEC=python"
)

"%PYTHON_EXEC%" -m src.interfaces.cli.main stop %*
