$SyncTaskName = "MPlusForm Sync"
$TunnelTaskName = "MPlusForm SSH Tunnel"
$AppDir = Join-Path $env:LOCALAPPDATA "MPlusFormSync"
$Config = Join-Path $env:APPDATA "MPlusFormSync\config.json"
$State = Join-Path $AppDir "state.json"
$Log = Join-Path $AppDir "logs\sync.log"
$Py = Join-Path $AppDir "runtime\python\python.exe"
$Script = Join-Path $AppDir "mplusform_sync_service.py"

Write-Host "== tasks =="
Get-ScheduledTask -TaskName $SyncTaskName -ErrorAction SilentlyContinue | Format-List TaskName,State,TaskPath
Get-ScheduledTask -TaskName $TunnelTaskName -ErrorAction SilentlyContinue | Format-List TaskName,State,TaskPath

Write-Host "== config =="
if (Test-Path $Config) {
  $cfg = Get-Content -Raw $Config | ConvertFrom-Json
  Write-Host "server_url=$($cfg.server_url)"
  Write-Host "wow_path=$($cfg.wow_path)"
  Write-Host "saved_variables=$($cfg.saved_variables)"
  Write-Host "addon_data_dir=$($cfg.addon_data_dir)"
  Write-Host "combat_log_path=$($cfg.combat_log_path)"
  Write-Host "uploader_id=$($cfg.uploader_id)"
  Write-Host "auth=no-user-token"
  if (Test-Path $cfg.combat_log_path) {
    $item = Get-Item $cfg.combat_log_path
    Write-Host "combat_log_exists=true size=$($item.Length) modified=$($item.LastWriteTime)"
  } else {
    Write-Host "combat_log_exists=false"
  }
} else {
  Write-Host "no config: $Config"
}

Write-Host "== sync self-status =="
if ((Test-Path $Py) -and (Test-Path $Script) -and (Test-Path $Config)) {
  & $Py $Script --status --config $Config
} else {
  Write-Host "sync script/runtime not installed yet"
}

Write-Host "== health =="
try {
  Invoke-RestMethod -Uri "http://127.0.0.1:8015/api/health" -TimeoutSec 5 | ConvertTo-Json -Depth 5
} catch {
  Write-Host "health failed: $($_.Exception.Message)"
}

Write-Host "== state =="
if (Test-Path $State) { Get-Content $State } else { Write-Host "no state yet" }

Write-Host "== last log lines =="
if (Test-Path $Log) { Get-Content $Log -Tail 80 } else { Write-Host "no log yet" }
