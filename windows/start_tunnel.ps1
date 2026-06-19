param(
  [string]$SshAlias = "mplus-api-host",
  [int]$LocalPort = 8015
)

$ErrorActionPreference = "Stop"

$existing = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue
if ($existing) {
  Write-Host "Tunnel/listener already exists on 127.0.0.1:$LocalPort"
  exit 0
}

$forward = "${LocalPort}:127.0.0.1:8015"
Start-Process -FilePath "ssh.exe" -ArgumentList @("-N", "-L", $forward, $SshAlias) -WindowStyle Hidden
Start-Sleep -Seconds 2

try {
  $health = Invoke-RestMethod -Uri "http://127.0.0.1:$LocalPort/api/health" -TimeoutSec 5
  Write-Host "Tunnel OK:"
  $health | ConvertTo-Json -Depth 5
} catch {
  Write-Host "Tunnel process started, but health check failed. Check SSH alias/key: $SshAlias"
  throw
}
