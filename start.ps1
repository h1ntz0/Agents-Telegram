# PowerShell Start Daemon Script for Windows
$ErrorActionPreference = "Stop"

$venvPath = Join-Path $PSScriptRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Virtual environment not found. Running setup first..." -ForegroundColor Yellow
    & (Join-Path $PSScriptRoot "setup.ps1")
}

Write-Host "Starting Telegram Agent Runtime on Windows..." -ForegroundColor Cyan
& $venvPython -m src start
