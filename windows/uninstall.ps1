param(
  [switch]$RemoveFiles,
  [switch]$RemoveAddon,
  [string]$WoWPath = ""
)

$ErrorActionPreference = "SilentlyContinue"
$SyncTaskName = "MPlusForm Sync"
$TunnelTaskName = "MPlusForm SSH Tunnel"

Stop-ScheduledTask -TaskName $SyncTaskName
Unregister-ScheduledTask -TaskName $SyncTaskName -Confirm:$false
Stop-ScheduledTask -TaskName $TunnelTaskName
Unregister-ScheduledTask -TaskName $TunnelTaskName -Confirm:$false
Write-Host "Scheduled tasks removed."

if ($RemoveFiles) {
  Remove-Item -Recurse -Force (Join-Path $env:LOCALAPPDATA "MPlusFormSync")
  Remove-Item -Recurse -Force (Join-Path $env:APPDATA "MPlusFormSync")
  Write-Host "Sync files/config removed."
}

if ($RemoveAddon) {
  $candidates = @()
  if ($WoWPath -ne "") { $candidates += $WoWPath }
  $candidates += @(
    "G:\World of Warcraft",
    "C:\Program Files (x86)\World of Warcraft",
    "C:\Program Files\World of Warcraft",
    "$env:ProgramFiles\World of Warcraft",
    "${env:ProgramFiles(x86)}\World of Warcraft"
  )
  foreach ($c in $candidates) {
    $addon = Join-Path $c "_retail_\Interface\AddOns\MPlusForm"
    if (Test-Path $addon) {
      Remove-Item -Recurse -Force $addon
      Write-Host "Addon removed: $addon"
      break
    }
  }
}
