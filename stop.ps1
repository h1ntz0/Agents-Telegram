# PowerShell Stop Script for Windows
$pidFile = Join-Path $PSScriptRoot "data\agent.pid"

if (Test-Path $pidFile) {
    $agentPid = Get-Content $pidFile
    try {
        Stop-Process -Id $agentPid -Force -ErrorAction SilentlyContinue
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        Write-Host "Telegram Agent process (PID: $agentPid) stopped." -ForegroundColor Green
    } catch {
        Write-Host "Process $agentPid was not running." -ForegroundColor Yellow
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
} else {
    Write-Host "No active agent PID file found." -ForegroundColor Yellow
}
