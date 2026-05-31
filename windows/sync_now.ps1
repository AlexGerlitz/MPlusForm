$ErrorActionPreference = "Stop"
$AppDir = Join-Path $env:LOCALAPPDATA "MPlusFormSync"
$Config = Join-Path $env:APPDATA "MPlusFormSync\config.json"
$Py = Join-Path $AppDir "runtime\python\python.exe"
$Script = Join-Path $AppDir "mplusform_sync_service.py"

if (-not (Test-Path $Config)) { throw "Config not found: $Config. Run install_all.ps1 first." }
if (-not (Test-Path $Py)) { throw "Portable python not found: $Py" }
if (-not (Test-Path $Script)) { throw "Sync script not found: $Script" }

$cfg = Get-Content -Raw $Config | ConvertFrom-Json
Write-Host "== MPlusForm sync now =="
Write-Host "SavedVariables: $($cfg.saved_variables)"
Write-Host "CombatLog:      $($cfg.combat_log_path)"
if (Test-Path $cfg.saved_variables) {
  $sv = Get-Item $cfg.saved_variables
  Write-Host "SV modified:    $($sv.LastWriteTime) size=$($sv.Length)"
} else {
  Write-Host "SV missing"
}
if (Test-Path $cfg.combat_log_path) {
  $cl = Get-Item $cfg.combat_log_path
  Write-Host "Log modified:   $($cl.LastWriteTime) size=$($cl.Length)"
} else {
  Write-Host "Combat log missing. In WoW run /combatlog or start a key with the rc10.7 addon enabled."
}

& $Py $Script --once --config $Config

Write-Host ""
Write-Host "== API stats =="
try {
  Invoke-RestMethod -Uri "http://127.0.0.1:8015/api/v1/stats" -TimeoutSec 8 | ConvertTo-Json -Depth 8
} catch {
  Write-Host "stats failed: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "== Last sync log lines =="
$Log = Join-Path $AppDir "logs\sync.log"
if (Test-Path $Log) { Get-Content $Log -Tail 60 } else { Write-Host "no sync.log yet" }
