$ErrorActionPreference = "Stop"
$AppDir = Join-Path $env:LOCALAPPDATA "MPlusFormSync"
$Config = Join-Path $env:APPDATA "MPlusFormSync\config.json"
$Py = Join-Path $AppDir "runtime\python\python.exe"
$Script = Join-Path $AppDir "mplusform_sync_service.py"
if (-not (Test-Path $Py)) { throw "Portable python not found: $Py" }
if (-not (Test-Path $Script)) { throw "Sync script not found: $Script" }
& $Py $Script --once --config $Config
