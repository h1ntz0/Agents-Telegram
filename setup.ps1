# PowerShell Setup Script for Windows
$ErrorActionPreference = "Stop"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  Telegram Agent - Windows Setup Wizard  " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# 1. Locate Python 3.12+
$pythonCmd = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCmd = "py -3.12"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $pythonCmd = "python3"
} else {
    Write-Host "Error: Python 3.12+ is not installed or not in PATH." -ForegroundColor Red
    Write-Host "Please install Python 3.12 from https://www.python.org/downloads/ and check 'Add to PATH'." -ForegroundColor Yellow
    exit 1
}

# 2. Virtual Environment Setup
$venvPath = Join-Path $PSScriptRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment in .venv..." -ForegroundColor Yellow
    Invoke-Expression "$pythonCmd -m venv `"$venvPath`""
}

# 3. Install Dependencies
Write-Host "Installing dependencies..." -ForegroundColor Yellow
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -e .

# 4. Launch Setup Wizard
Write-Host "Launching Setup Wizard..." -ForegroundColor Green
& $venvPython -m src setup
