# Telegram Agent Platform -- start the agent runtime (Windows).
#
#   .\scripts\start.ps1            # foreground; Ctrl+C stops it
#   .\scripts\start.ps1 --detach   # background
#   .\scripts\start.ps1 --force    # take over a stale or live PID file
#
# A missing virtual environment or missing dependencies are bootstrapped through
# .\scripts\setup.ps1. Every argument is forwarded to `python -m src start`
# unchanged and the child's exit code is propagated to the caller.

$ErrorActionPreference = "Continue"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$venvPython  = Join-Path $projectRoot ".venv\Scripts\python.exe"
$posixPython = Join-Path $projectRoot ".venv\bin\python"
$depImports  = "import httpx, pydantic, yaml, aiosqlite"

function Test-ConsoleInput {
    # True only when a real console is attached (double-click, open terminal).
    try { $null = [Console]::KeyAvailable; return $true } catch { return $false }
}

function Exit-With-Pause([int]$code) {
    if ($code -ne 0 -and $env:AGENT_LAUNCHER_NO_PAUSE -ne "1" -and (Test-ConsoleInput)) {
        Write-Host ""
        Write-Host "Press any key to close..." -ForegroundColor Gray
        try { $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown") } catch {}
    }
    exit $code
}

function Test-Dependencies {
    if (-not (Test-Path $venvPython)) { return $false }
    & $venvPython -c $depImports 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Invoke-Setup {
    Write-Host "[INFO] Running .\scripts\setup.ps1 first ..." -ForegroundColor Yellow
    Write-Host ""
    $env:AGENT_LAUNCHER_NO_PAUSE = "1"
    & (Join-Path $PSScriptRoot "setup.ps1")
    $setupCode = $LASTEXITCODE
    Remove-Item Env:\AGENT_LAUNCHER_NO_PAUSE -ErrorAction SilentlyContinue
    if ($setupCode -ne 0) {
        Write-Host ""
        Write-Host "[ERROR] Setup did not complete (exit code $setupCode)." -ForegroundColor Red
        Write-Host "        Run .\scripts\setup.ps1 manually, then retry .\scripts\start.ps1." -ForegroundColor Yellow
        Exit-With-Pause $setupCode
    }
    if (-not (Test-Path $venvPython)) {
        Write-Host "[ERROR] Setup finished but .venv is still missing." -ForegroundColor Red
        Exit-With-Pause 1
    }
}

if (-not (Test-Path $venvPython)) {
    if (Test-Path $posixPython) {
        Write-Host "[ERROR] The .venv folder was created by a Linux/macOS Python interpreter." -ForegroundColor Red
        Write-Host "        Windows cannot use it. Delete the .venv folder and run .\scripts\setup.ps1 again." -ForegroundColor Yellow
        Exit-With-Pause 1
    }
    Invoke-Setup
}

if (-not (Test-Dependencies)) {
    Invoke-Setup
}

Write-Host "[INFO] Starting the Telegram Agent ..." -ForegroundColor Cyan
& $venvPython -m src start @args
$agentCode = $LASTEXITCODE

if ($agentCode -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] The agent exited with code $agentCode." -ForegroundColor Red
    Write-Host "        Run .\scripts\doctor.ps1 for a full diagnosis." -ForegroundColor Yellow
    Exit-With-Pause $agentCode
}

exit 0
