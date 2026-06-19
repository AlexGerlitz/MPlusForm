param(
  [string]$ServerUrl = "http://127.0.0.1:8015",
  [string]$SshAlias = "mplus-api-host",
  [string]$WoWPath = "",
  [switch]$NoTunnelTask,
  [switch]$NoStart
)

$ErrorActionPreference = "Stop"
Set-ExecutionPolicy -Scope Process Bypass -Force

$argsForSync = @{
  ServerUrl = $ServerUrl
  SshAlias = $SshAlias
  WoWPath = $WoWPath
}
if ($NoTunnelTask) { $argsForSync.NoTunnelTask = $true }
if ($NoStart) { $argsForSync.NoStart = $true }

Write-Host "== MPlusForm Sync Setup =="
Write-Host "This installs only the optional desktop sync."
Write-Host "The CurseForge addon files are not modified, except Data\\Snapshot.lua."
Write-Host ""

& (Join-Path $PSScriptRoot "windows\install_sync_task.ps1") @argsForSync

Write-Host ""
Write-Host "== MPlusForm Sync Status =="
& (Join-Path $PSScriptRoot "windows\status.ps1")

Write-Host ""
Write-Host "Setup complete. In WoW, reload UI and hover a player tooltip after the first approved sync."

