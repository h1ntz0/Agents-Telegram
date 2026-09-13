# Telegram Agent Platform -- environment diagnosis (Windows).
#
#   .\scripts\doctor.ps1            # run every check
#
# A missing virtual environment or missing dependencies are bootstrapped through
# .\scripts\setup.ps1. Arguments are forwarded to `python -m src doctor` and the
# child's exit code is propagated: 0 when every check passes, 1 on any FAIL.

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
        Write-Host "        Run .\scripts\setup.ps1 manually, then retry .\scripts\doctor.ps1." -ForegroundColor Yellow
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

Write-Host "[INFO] Running diagnostics ..." -ForegroundColor Cyan
& $venvPython -m src doctor @args
$doctorCode = $LASTEXITCODE

if ($doctorCode -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] At least one diagnostic check failed (exit code $doctorCode)." -ForegroundColor Red
    Write-Host "        Fix the failing checks above, then run .\scripts\doctor.ps1 again." -ForegroundColor Yellow
    Exit-With-Pause $doctorCode
}

exit 0
