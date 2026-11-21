$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$databasePath = Join-Path $repoRoot 'backend\data\udaya_library.db'
$backupDir = Join-Path $repoRoot 'backend\data\backups'
$sqlite = Get-Command sqlite3.exe -ErrorAction SilentlyContinue

if (-not (Test-Path $databasePath)) { throw "Database not found at $databasePath" }
if (-not $sqlite) { throw 'sqlite3.exe was not found on PATH. Install the SQLite command-line tools, then retry.' }
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupPath = Join-Path $backupDir "udaya_library-$stamp.db"

& $sqlite.Source $databasePath ".backup '$backupPath'"
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $backupPath)) { throw 'SQLite online backup failed.' }
$integrity = (& $sqlite.Source $backupPath 'PRAGMA integrity_check;') -join ''
if ($integrity -ne 'ok') { throw "Backup integrity check failed: $integrity" }

$backups = Get-ChildItem $backupDir -Filter 'udaya_library-*.db' -File | Sort-Object LastWriteTime -Descending
if ($backups.Count -gt 30) { $backups | Select-Object -Skip 30 | Remove-Item -Force }
Write-Host "Created verified backup: $backupPath"
