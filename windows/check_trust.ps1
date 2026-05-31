$ErrorActionPreference = "Stop"
$ConfigPath = Join-Path $env:APPDATA "MPlusFormSync\config.json"
if (!(Test-Path $ConfigPath)) { throw "Config not found: $ConfigPath" }
$cfg = Get-Content $ConfigPath -Raw | ConvertFrom-Json
$server = ($cfg.server_url).TrimEnd('/')
Write-Host "== trust health =="
try { Invoke-RestMethod -Uri "$server/api/v1/health/trust" -TimeoutSec 8 | ConvertTo-Json -Depth 8 } catch { Write-Warning $_ }
Write-Host "== stats =="
try { Invoke-RestMethod -Uri "$server/api/v1/stats" -TimeoutSec 8 | ConvertTo-Json -Depth 8 } catch { Write-Warning $_ }
