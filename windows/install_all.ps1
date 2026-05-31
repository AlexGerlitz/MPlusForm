param(
  [string]$WoWPath = "",
  [string]$ServerUrl = "http://127.0.0.1:8015",
  [string]$SshAlias = "mplus-moscow",
  [switch]$SkipTunnelTask,
  [switch]$NoStart
)

$ErrorActionPreference = "Stop"

& (Join-Path $PSScriptRoot "install_addon.ps1") -WoWPath $WoWPath

$argsForSync = @{
  ServerUrl = $ServerUrl
  SshAlias = $SshAlias
  WoWPath = $WoWPath
}
if ($SkipTunnelTask) { $argsForSync.NoTunnelTask = $true }
if ($NoStart) { $argsForSync.NoStart = $true }

& (Join-Path $PSScriptRoot "install_sync_task.ps1") @argsForSync

Write-Host ""
Write-Host "Install complete."
Write-Host "Next in WoW: /reload, then /mpf status."
Write-Host "After key: when you see queued run, type /mpf syncnow in WoW."
Write-Host "Alternative: type /reload, then run .\sync_now.ps1. No 30-60 sec manual wait."
