param(
  [int]$TimeoutSec = 180
)

$ErrorActionPreference = "Stop"
$AppDir = Join-Path $env:LOCALAPPDATA "MPlusFormSync"
$Config = Join-Path $env:APPDATA "MPlusFormSync\config.json"
if (-not (Test-Path $Config)) { throw "Config not found: $Config. Run install_all.ps1 first." }
$cfg = Get-Content -Raw $Config | ConvertFrom-Json
$SV = $cfg.saved_variables
if (-not (Test-Path $SV)) { throw "SavedVariables not found: $SV" }

$before = Get-Item $SV
$beforeStamp = $before.LastWriteTimeUtc
$beforeLen = $before.Length
Write-Host "Watching SavedVariables for WoW /reload flush:"
Write-Host "  $SV"
Write-Host "Current: $($before.LastWriteTime) size=$beforeLen"
Write-Host ""
Write-Host "Now in WoW type: /mpf syncnow"
Write-Host "Alternative: /reload"
Write-Host "This script will run Sync immediately when MPlusForm.lua changes. Timeout: $TimeoutSec sec."

$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 1
  if (-not (Test-Path $SV)) { continue }
  $cur = Get-Item $SV
  if ($cur.LastWriteTimeUtc -ne $beforeStamp -or $cur.Length -ne $beforeLen) {
    Write-Host "SavedVariables changed: $($cur.LastWriteTime) size=$($cur.Length)"
    Start-Sleep -Seconds 1
    & (Join-Path $PSScriptRoot "sync_now.ps1")
    exit $LASTEXITCODE
  }
}
throw "Timeout: SavedVariables did not change. In WoW you still need /mpf syncnow or /reload."
