# PowerShell Start Daemon Script for Windows
$ErrorActionPreference = "Stop"

$venvPath = Join-Path $PSScriptRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Virtual environment not found. Running setup first..." -ForegroundColor Yellow
    & (Join-Path $PSScriptRoot "setup.ps1")
}

# Check if dependencies are missing and auto-install
try {
    & $venvPython -c "import httpx, pydantic, yaml, aiosqlite" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Missing dependencies detected. Auto-installing..." -ForegroundColor Yellow
        & $venvPython -m pip install --quiet --upgrade pip
        & $venvPython -m pip install --quiet -e .
    }
} catch {
    Write-Host "Installing dependencies..." -ForegroundColor Yellow
    & $venvPython -m pip install --quiet -e .
}

Write-Host "Starting Telegram Agent Runtime on Windows..." -ForegroundColor Cyan
& $venvPython -m src start
