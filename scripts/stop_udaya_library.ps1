$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$pidPath = Join-Path $repoRoot 'backend\logs\server.pid'

if (Test-Path $pidPath) {
    $serverPid = [int](Get-Content $pidPath -Raw).Trim()
    $process = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $serverPid -Force
        Write-Host "Stopped Udaya Library server (PID $serverPid)."
    }
    Remove-Item $pidPath -Force -ErrorAction SilentlyContinue
} else {
    $listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        Stop-Process -Id $listener.OwningProcess -Force
        Write-Host "Stopped process listening on port 8000 (PID $($listener.OwningProcess))."
    } else {
        Write-Host 'Udaya Library is not running on port 8000.'
    }
}
