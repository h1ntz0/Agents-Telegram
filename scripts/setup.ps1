# Telegram Agent Platform -- environment bootstrap + setup wizard launcher (Windows).
#
#   .\scripts\setup.ps1                  # interactive wizard
#   .\scripts\setup.ps1 --advanced
#   .\scripts\setup.ps1 -y --bot-token 123:ABC --provider openai --model gpt-4o-mini --api-key sk-...
#
# Every argument is forwarded verbatim to `python -m src setup`, and the wizard's
# exit code becomes this script's exit code.

$ErrorActionPreference = "Continue"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$Host.UI.RawUI.WindowTitle = "Telegram Agent Setup"

$venvPath    = Join-Path $projectRoot ".venv"
$venvPython  = Join-Path $venvPath "Scripts\python.exe"
$posixPython = Join-Path $venvPath "bin\python"
$depImports  = "import httpx, pydantic, yaml, aiosqlite"

function Test-ConsoleInput {
    # True only when a real console is attached (double-click, open terminal).
    # Redirected or absent stdin (CI, containers, automation) returns false, so a
    # launcher can never block forever waiting for a keypress.
    try { $null = [Console]::KeyAvailable; return $true } catch { return $false }
}

function Exit-With-Pause([int]$code) {
    # Keeps the window open when the script was started by a double-click.
    # start.ps1/doctor.ps1 set AGENT_LAUNCHER_NO_PAUSE=1 for the nested bootstrap
    # so an automated run never blocks on a keypress.
    if ($env:AGENT_LAUNCHER_NO_PAUSE -ne "1" -and (Test-ConsoleInput)) {
        Write-Host ""
        Write-Host "Press any key to close..." -ForegroundColor Gray
        try { $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown") } catch {}
    }
    exit $code
}

function Write-Step([string]$message) { Write-Host "[INFO] $message" -ForegroundColor Yellow }
function Write-Ok([string]$message)   { Write-Host "[ OK ] $message" -ForegroundColor Green }
function Write-Warn([string]$message) { Write-Host "[WARN] $message" -ForegroundColor Yellow }

function Test-Python312([string]$exe) {
    if (-not (Test-Path $exe)) { return $false }
    & $exe -c "import sys; sys.exit(0 if sys.version_info>=(3,12) else 1)" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

# 1. Locate a genuine Python 3.12+ runtime (Windows Store stubs are filtered out).
function Test-PythonCandidate([string]$command) {
    if (-not $command) { return $false }
    $parts = $command -split " "
    $exe = $parts[0]
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { return $false }
    $probeArgs = @()
    if ($parts.Count -gt 1) { $probeArgs += $parts[1..($parts.Count - 1)] }
    $probeArgs += @("-c", "import sys; sys.exit(0 if sys.version_info>=(3,12) else 1)")
    & $exe @probeArgs 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

# 2. Virtual environment -- reuse a working one, whichever shell created it.
if (Test-Path $venvPython) {
    if (-not (Test-Python312 $venvPython)) {
        Write-Host "[ERROR] The interpreter inside .venv is older than Python 3.12." -ForegroundColor Red
        Write-Host "        Delete the .venv folder and run .\scripts\setup.ps1 again." -ForegroundColor Yellow
        Exit-With-Pause 1
    }
    Write-Ok "Using the existing virtual environment ($venvPython)"
} elseif (Test-Path $posixPython) {
    Write-Host "[ERROR] The .venv folder was created by a Linux/macOS Python interpreter." -ForegroundColor Red
    Write-Host "        Windows cannot use it. Delete the .venv folder and run this script again." -ForegroundColor Yellow
    Exit-With-Pause 1
} else {
    $candidates = @("py -3.14", "py -3.13", "py -3.12", "py -3", "python", "python3")
    $pythonCmd = $null

    foreach ($candidate in $candidates) {
        if (Test-PythonCandidate $candidate) {
            $pythonCmd = $candidate
            break
        }
    }

    if (-not $pythonCmd) {
        Write-Host "[ERROR] Python 3.12+ was not detected or is incompatible." -ForegroundColor Red
        Write-Host ""

        $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
        if ($pyLauncher) {
            Write-Step "Installing Python 3.12 via the 'py' launcher ..."
            py install 3.12
            if (Test-PythonCandidate "py -3.12") { $pythonCmd = "py -3.12" }
        }
        if ((-not $pythonCmd) -and (Get-Command winget -ErrorAction SilentlyContinue)) {
            Write-Step "Installing Python 3.12 via winget ..."
            winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
            if (Test-PythonCandidate "py -3.12") { $pythonCmd = "py -3.12" }
        }
        if (-not $pythonCmd) {
            if ($pyLauncher -or (Get-Command winget -ErrorAction SilentlyContinue)) {
                Write-Host ""
                Write-Host "[INFO] If the installation completed, CLOSE this window, open a NEW one," -ForegroundColor Cyan
                Write-Host "       then run .\scripts\setup.ps1 again." -ForegroundColor Cyan
            } else {
                Write-Host "Please install Python 3.12+ manually:" -ForegroundColor Yellow
                Write-Host "  1. Download from https://www.python.org/downloads/" -ForegroundColor White
                Write-Host "  2. Crucially: tick 'Add python.exe to PATH' during the installation." -ForegroundColor Yellow
                Write-Host "  3. CLOSE this window, open a NEW one, then run .\scripts\setup.ps1" -ForegroundColor White
            }
            Exit-With-Pause 1
        }
    }

    Write-Step "Creating the virtual environment in .venv with '$pythonCmd' ..."
    $parts = $pythonCmd -split " "
    $venvArgs = @()
    if ($parts.Count -gt 1) { $venvArgs += $parts[1..($parts.Count - 1)] }
    $venvArgs += @("-m", "venv", $venvPath)
    & $parts[0] @venvArgs

    if ($LASTEXITCODE -ne 0 -or -not (Test-Python312 $venvPython)) {
        Write-Host "[ERROR] Failed to create a usable virtual environment." -ForegroundColor Red
        Write-Host "        Run this from a folder you own (not C:\Windows\system32)." -ForegroundColor Yellow
        Exit-With-Pause 1
    }
    Write-Ok "Virtual environment created ($venvPython)"
}

# 3. pip has to exist before anything can be installed.
& $venvPython -m pip --version 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Step "Bootstrapping pip with ensurepip ..."
    & $venvPython -m ensurepip --upgrade 2>$null | Out-Null
}

# 4. Dependencies.
function Test-Dependencies {
    & $venvPython -c $depImports 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

if (-not (Test-Dependencies)) {
    Write-Step "Installing project dependencies (this may take a minute) ..."
    & $venvPython -m pip install --quiet --upgrade pip
    & $venvPython -m pip install --quiet -e .
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Editable install failed. Installing the runtime packages directly ..."
        & $venvPython -m pip install --quiet "pydantic>=2.7.0" "pyyaml>=6.0.1" "python-dotenv>=1.0.1" "httpx>=0.27.0" "aiosqlite>=0.20.0"
    }
    if (-not (Test-Dependencies)) {
        Write-Host "[ERROR] The required dependencies could not be installed." -ForegroundColor Red
        Write-Host "        Check your internet connection and run .\scripts\setup.ps1 again." -ForegroundColor Yellow
        Exit-With-Pause 1
    }
}

# 5. Hand over to the wizard with the caller's arguments untouched.
Write-Host ""
Write-Step "Launching the setup wizard ..."
Write-Host ""
& $venvPython -m src setup @args
$wizardCode = $LASTEXITCODE

if ($wizardCode -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] The setup wizard exited with code $wizardCode." -ForegroundColor Red
    Write-Host "        Fix the problem above, then run .\scripts\setup.ps1 again." -ForegroundColor Yellow
    Exit-With-Pause $wizardCode
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "  Setup complete.                        " -ForegroundColor Green
Write-Host "  Start the agent with: .\scripts\start.ps1" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Green
Exit-With-Pause 0
