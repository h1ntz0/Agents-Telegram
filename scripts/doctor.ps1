# PowerShell Doctor / Diagnostics Script for Windows
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$venvPath = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Error: Virtual environment not found. Please run .\scripts\setup.ps1 first." -ForegroundColor Red
    exit 1
}

& $venvPython -m src doctor $args
