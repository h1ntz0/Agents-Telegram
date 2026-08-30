# PowerShell Health Doctor Script for Windows
$ErrorActionPreference = "Stop"

$venvPath = Join-Path $PSScriptRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Error: Virtual environment not found. Please run .\setup.ps1 first." -ForegroundColor Red
    exit 1
}

& $venvPython -m src doctor
