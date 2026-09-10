# PowerShell Setup Script for Windows
$ErrorActionPreference = "Continue"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$Host.UI.RawUI.WindowTitle = "Telegram Agent Setup"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  Telegram Agent - Windows Setup Wizard  " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# Helper to pause on exit if run via double-click / external window
function Exit-With-Pause([int]$code) {
    Write-Host ""
    Write-Host "Press any key to close..." -ForegroundColor Gray
    try { $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown") } catch {}
    exit $code
}

# 1. Locate a genuine Python 3.12+ runtime (filtering out Windows Store dead stubs)
function Test-PythonCandidate([string]$cmd) {
    try {
        $out = & (Get-Command -Name $cmd.Split(' ')[0] -ErrorAction SilentlyContinue) ($cmd.Split(' ')[1..99] + @("-c", "import sys; sys.exit(0 if sys.version_info>=(3,12) else 1)")) 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

$candidates = @("py -3.12", "py -3", "python", "python3")
$pythonCmd = $null

foreach ($c in $candidates) {
    if (Test-PythonCandidate $c) {
        $pythonCmd = $c
        break
    }
}

if (-not $pythonCmd) {
    Write-Host "[ERROR] Python 3.12+ was not detected or is incompatible." -ForegroundColor Red
    Write-Host ""

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host "[INFO] Attempting to auto-install Python 3.12 via winget..." -ForegroundColor Yellow
        winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
        Write-Host ""
        Write-Host "[INFO] If install completed, CLOSE this PowerShell window, open a NEW one," -ForegroundColor Cyan
        Write-Host "       then re-run .\scripts\setup.ps1" -ForegroundColor Cyan
    } else {
        Write-Host "Please install Python 3.12+ manually:" -ForegroundColor Yellow
        Write-Host "  1. Download from https://www.python.org/downloads/" -ForegroundColor White
        Write-Host "  2. Crucial: Tick 'Add python.exe to PATH' during installation." -ForegroundColor Yellow
        Write-Host "  3. Close and reopen PowerShell, then run .\scripts\setup.ps1" -ForegroundColor White
    }
    Exit-With-Pause 1
}

Write-Host "[OK] Using Python command: $pythonCmd" -ForegroundColor Green
Write-Host ""

# 2. Virtual Environment Setup
$venvPath = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "[INFO] Creating virtual environment in .venv..." -ForegroundColor Yellow
    $parts = $pythonCmd -split " "
    & $parts[0] ($parts[1..99] + @("-m", "venv", $venvPath))
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
        Write-Host "[ERROR] Failed to create virtual environment." -ForegroundColor Red
        Write-Host "        Ensure you are not in a protected folder like C:\Windows\system32." -ForegroundColor Yellow
        Exit-With-Pause 1
    }
}

# 3. Ensure pip is installed
& $venvPython -m pip --version 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[INFO] Bootstrapping pip..." -ForegroundColor Yellow
    & $venvPython -m ensurepip --upgrade 2>$null | Out-Null
}

# 4. Dependency Verification & Installation
$needsInstall = $false
try {
    & $venvPython -c "import httpx, pydantic, yaml, aiosqlite" 2>$null
    if ($LASTEXITCODE -ne 0) { $needsInstall = $true }
} catch {
    $needsInstall = $true
}

if ($needsInstall) {
    Write-Host "[INFO] Installing project dependencies (may take a moment)..." -ForegroundColor Yellow
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -e .
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARN] Editable install failed. Trying direct package installation..." -ForegroundColor Yellow
        & $venvPython -m pip install "pydantic>=2.7.0" "pyyaml>=6.0.1" "python-dotenv>=1.0.1" "httpx>=0.27.0" "aiosqlite>=0.20.0"
    }

    # Final sanity check
    & $venvPython -c "import httpx, pydantic, yaml, aiosqlite" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to install required dependencies." -ForegroundColor Red
        Write-Host "        Check internet connectivity and try again." -ForegroundColor Yellow
        Exit-With-Pause 1
    }
}

# 5. Launch Setup Wizard
Write-Host ""
Write-Host "[INFO] Launching Setup Wizard..." -ForegroundColor Green
Write-Host ""
& $venvPython -m src setup

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] Setup wizard ended with an error." -ForegroundColor Red
    Exit-With-Pause 1
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "  Setup completed successfully!          " -ForegroundColor Green
Write-Host "  Start the agent with: .\scripts\start.ps1" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Green
Exit-With-Pause 0
