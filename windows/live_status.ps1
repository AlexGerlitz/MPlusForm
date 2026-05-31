param()
$ErrorActionPreference = "Stop"
$LocalAppData = [Environment]::GetFolderPath("LocalApplicationData")
$Base = Join-Path $LocalAppData "MPlusFormSync"
$State = Join-Path $Base "state.json"
$Evidence = Join-Path $Base "evidence"
Write-Host "=== MPlusForm Live Evidence ==="
Write-Host "State: $State"
Write-Host "Evidence: $Evidence"
if (Test-Path $State) { Get-Content $State -Raw }
if (Test-Path $Evidence) {
  Write-Host "--- latest heartbeat files ---"
  Get-ChildItem $Evidence -Filter "tamper-evident-live-heartbeat-*.jsonl" | Sort-Object LastWriteTime -Descending | Select-Object -First 3 | Format-Table Name,Length,LastWriteTime
  $Latest = Get-ChildItem $Evidence -Filter "tamper-evident-live-heartbeat-*.jsonl" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if ($Latest) {
    Write-Host "--- latest heartbeat line ---"
    Get-Content $Latest.FullName -Tail 1
  }
} else {
  Write-Host "No live evidence spool yet. It appears after a Challenge Mode start marker in WoWCombatLog.txt."
}
