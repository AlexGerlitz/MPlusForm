param(
  [string]$ServerUrl = "http://127.0.0.1:8015",
  [string]$SshAlias = "mplus-moscow",
  [string]$WoWPath = "",
  [string]$UploaderId = "",
  [int]$PollIntervalSec = 10,
  [switch]$NoTunnelTask,
  [switch]$NoStart
)

$ErrorActionPreference = "Stop"
$SyncTaskName = "MPlusForm Sync"
$TunnelTaskName = "MPlusForm SSH Tunnel"

function Find-WoWPath {
  param([string]$Given)
  $candidates = @()
  if ($Given -ne "") { $candidates += $Given }
  $candidates += @(
    "G:\World of Warcraft",
    "C:\Program Files (x86)\World of Warcraft",
    "C:\Program Files\World of Warcraft",
    "$env:ProgramFiles\World of Warcraft",
    "${env:ProgramFiles(x86)}\World of Warcraft"
  )
  foreach ($c in $candidates) {
    if ($c -and (Test-Path (Join-Path $c "_retail_\Interface\AddOns"))) { return $c }
  }
  throw "World of Warcraft retail folder not found. Pass -WoWPath 'G:\World of Warcraft'."
}

$PackageRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$RuntimeSource = Join-Path $PackageRoot "sync\runtime\python"
$PySource = Join-Path $PackageRoot "sync\mplusform_sync_service.py"
if (-not (Test-Path (Join-Path $RuntimeSource "pythonw.exe"))) { throw "Portable Python runtime missing: $RuntimeSource" }
if (-not (Test-Path $PySource)) { throw "Sync script missing: $PySource" }

$AppDir = Join-Path $env:LOCALAPPDATA "MPlusFormSync"
$ConfigDir = Join-Path $env:APPDATA "MPlusFormSync"
$LogDir = Join-Path $AppDir "logs"
$RuntimeDest = Join-Path $AppDir "runtime\python"
$PyDest = Join-Path $AppDir "mplusform_sync_service.py"
$ConfigPath = Join-Path $ConfigDir "config.json"

$Wow = Find-WoWPath -Given $WoWPath
$Retail = Join-Path $Wow "_retail_"
$SavedRoot = Join-Path $Retail "WTF\Account"
$SavedFile = Get-ChildItem -Path $SavedRoot -Recurse -Filter "MPlusForm.lua" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $SavedFile) {
  $AccountDir = Get-ChildItem -Path $SavedRoot -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($null -eq $AccountDir) { throw "No WTF Account folder found. Start WoW once with MPlusForm enabled, then run installer again." }
  $SavedVariablesDir = Join-Path $AccountDir.FullName "SavedVariables"
  New-Item -ItemType Directory -Force -Path $SavedVariablesDir | Out-Null
  $SavedVariablesPath = Join-Path $SavedVariablesDir "MPlusForm.lua"
  "MPlusFormDB = { [""uploadQueue""] = {}, [""localRuns""] = {}, [""settings""] = { [""tooltip""] = true } }" | Set-Content -Encoding UTF8 $SavedVariablesPath
} else {
  $SavedVariablesPath = $SavedFile.FullName
}

$AddonDataDir = Join-Path $Retail "Interface\AddOns\MPlusForm\Data"
$CombatLogPath = Join-Path $Retail "Logs\WoWCombatLog.txt"
New-Item -ItemType Directory -Force -Path $AppDir,$ConfigDir,$LogDir,$AddonDataDir,(Split-Path -Parent $CombatLogPath) | Out-Null
if (Test-Path $RuntimeDest) { Remove-Item -Recurse -Force $RuntimeDest }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $RuntimeDest) | Out-Null
Copy-Item -Recurse -Force $RuntimeSource $RuntimeDest
Copy-Item -Force $PySource $PyDest

if ($UploaderId -eq "") { $UploaderId = "$env:COMPUTERNAME-$env:USERNAME" }
$config = [ordered]@{
  server_url = $ServerUrl
  wow_path = $Wow.Replace('\','/')
  saved_variables = $SavedVariablesPath.Replace('\','/')
  addon_data_dir = $AddonDataDir.Replace('\','/')
  combat_log_path = $CombatLogPath.Replace('\','/')
  uploader_id = $UploaderId
  poll_interval_sec = [Math]::Max(10, $PollIntervalSec)
  silent = $true
  combat_log_tolerance_before_sec = 180
  combat_log_tolerance_after_sec = 360
  min_selected_log_events_for_upload = 1
  upload_metadata_without_combatlog = $false
  enable_combatlog_evidence = $true
  combatlog_evidence_grace_sec = 120
  upload_recovered_completed_runs = $true
  upload_recovered_incomplete_runs = $false
  live_heartbeat_enabled = $true
  live_heartbeat_jitter_enabled = $true
  live_heartbeat_interval_sec = 10
  live_heartbeat_min_sec = 5
  live_heartbeat_max_sec = 15
  wow_process_check_enabled = $false
}
$config | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $ConfigPath

$Pythonw = Join-Path $RuntimeDest "pythonw.exe"
$Python = Join-Path $RuntimeDest "python.exe"
$SyncArgs = "`"$PyDest`" --watch --config `"$ConfigPath`""
$SyncAction = New-ScheduledTaskAction -Execute $Pythonw -Argument $SyncArgs -WorkingDirectory $AppDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Hours 0)
Register-ScheduledTask -TaskName $SyncTaskName -Action $SyncAction -Trigger $Trigger -Settings $Settings -Description "Silent MPlusForm background sync, no-token, Retail 12 logfile parser" -RunLevel Limited -Force | Out-Null

if (-not $NoTunnelTask) {
  $SshExe = Join-Path $env:WINDIR "System32\OpenSSH\ssh.exe"
  if (-not (Test-Path $SshExe)) { $SshExe = "ssh.exe" }
  $TunnelForward = "8015:127.0.0.1:8015"
  $TunnelCommand = ('"{0}" -N -L {1} {2}' -f $SshExe, $TunnelForward, $SshAlias)
  $TunnelLauncher = Join-Path $AppDir "start_tunnel_hidden.vbs"
  $TunnelCommandForVbs = $TunnelCommand.Replace('"', '""')
  @"
Set shell = CreateObject("WScript.Shell")
cmd = "$TunnelCommandForVbs"
shell.Run cmd, 0, True
"@ | Set-Content -Encoding ASCII $TunnelLauncher
  $TunnelAction = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$TunnelLauncher`""
  Register-ScheduledTask -TaskName $TunnelTaskName -Action $TunnelAction -Trigger $Trigger -Settings $Settings -Description "MPlusForm local SSH tunnel to VPS API" -RunLevel Limited -Force | Out-Null
}

if (-not $NoStart) {
  if (-not $NoTunnelTask) { Start-ScheduledTask -TaskName $TunnelTaskName }
  Start-Sleep -Seconds 2
  Start-ScheduledTask -TaskName $SyncTaskName
}

Write-Host "MPlusForm Sync installed."
Write-Host "Mode: silent Task Scheduler, no tray icon, no user token."
Write-Host "Sync task: $SyncTaskName"
if (-not $NoTunnelTask) { Write-Host "Tunnel task: $TunnelTaskName" }
Write-Host "Runtime: $Pythonw"
Write-Host "Config: $ConfigPath"
Write-Host "Log: $(Join-Path $LogDir 'sync.log')"
Write-Host "SavedVariables: $SavedVariablesPath"
Write-Host "CombatLog: $CombatLogPath"
Write-Host "Addon Data: $AddonDataDir"
