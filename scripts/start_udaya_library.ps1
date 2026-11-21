$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot 'backend'
$pythonExe = Join-Path $backendDir '.venv\Scripts\python.exe'
$logsDir = Join-Path $backendDir 'logs'
$logPath = Join-Path $logsDir 'server.log'
$errorLogPath = Join-Path $logsDir 'server-error.log'
$pidPath = Join-Path $logsDir 'server.pid'

New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
$existing = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $existing) {
    if (-not (Test-Path $pythonExe)) {
        throw "Backend Python environment not found at $pythonExe"
    }
    $server = Start-Process -FilePath $pythonExe `
        -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '8000' `
        -WorkingDirectory $backendDir `
        -RedirectStandardOutput $logPath `
        -RedirectStandardError $errorLogPath `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -Path $pidPath -Value $server.Id
    Start-Sleep -Seconds 2
} else {
    Write-Host "Udaya Library is already listening on port 8000 (PID $($existing.OwningProcess))."
}

$lanIp = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
        $_.IPAddress -match '^(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})$' -and
        $_.IPAddress -ne '127.0.0.1'
    } |
    Select-Object -First 1 -ExpandProperty IPAddress
if (-not $lanIp) { $lanIp = '127.0.0.1' }
$mobileUrl = "http://$lanIp`:8000"
Write-Host "Desktop URL: http://127.0.0.1:8000"
Write-Host "Mobile Wi-Fi URL: $mobileUrl"

try {
    & $pythonExe -c 'import sys; import qrcode; qr=qrcode.QRCode(border=1); qr.add_data(sys.argv[1]); qr.make(fit=True); qr.print_ascii(invert=True)' $mobileUrl
} catch {
    Write-Host 'QR code unavailable: install the optional Python qrcode package to enable terminal QR output.'
}

$edge = Get-Command msedge.exe -ErrorAction SilentlyContinue
$chrome = Get-Command chrome.exe -ErrorAction SilentlyContinue
if ($edge) {
    Start-Process $edge.Source '--app=http://127.0.0.1:8000'
} elseif ($chrome) {
    Start-Process $chrome.Source '--app=http://127.0.0.1:8000'
} else {
    Start-Process 'http://127.0.0.1:8000'
}
