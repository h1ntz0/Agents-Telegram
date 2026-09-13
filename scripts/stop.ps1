# Telegram Agent Platform -- stop the background runtime (Windows).
#
#   .\scripts\stop.ps1
#
# This is a thin forwarder: `python -m src stop` owns the PID file and the
# process shutdown, so the CLI stays the single source of truth. The child's
# exit code is propagated (0 when stopped or when nothing was running).

$ErrorActionPreference = "Continue"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$venvPython  = Join-Path $projectRoot ".venv\Scripts\python.exe"
$posixPython = Join-Path $projectRoot ".venv\bin\python"

function Test-ConsoleInput {
    # True only when a real console is attached (double-click, open terminal).
    try { $null = [Console]::KeyAvailable; return $true } catch { return $false }
}

function Exit-With-Pause([int]$code) {
    if ($code -ne 0 -and (Test-ConsoleInput)) {
        Write-Host ""
        Write-Host "Press any key to close..." -ForegroundColor Gray
        try { $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown") } catch {}
    }
    exit $code
}

if (Test-Path $venvPython) {
    $python = $venvPython
} elseif (Test-Path $posixPython) {
    $python = $posixPython
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $python = "python3"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $python = "python"
} else {
    Write-Host "[ERROR] No Python interpreter was found." -ForegroundColor Red
    Write-Host "        Run .\scripts\setup.ps1 first." -ForegroundColor Yellow
    Exit-With-Pause 1
}

& $python -m src stop @args
Exit-With-Pause $LASTEXITCODE
