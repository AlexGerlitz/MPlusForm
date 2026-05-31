param(
  [string]$WoWPath = ""
)

$ErrorActionPreference = "Stop"

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
$AddonSource = Join-Path $PackageRoot "addon\MPlusForm"
if (-not (Test-Path $AddonSource)) { throw "Addon source not found: $AddonSource" }

$Wow = Find-WoWPath -Given $WoWPath
$AddOnsDir = Join-Path $Wow "_retail_\Interface\AddOns"
$AddonDest = Join-Path $AddOnsDir "MPlusForm"

New-Item -ItemType Directory -Force -Path $AddOnsDir | Out-Null
if (Test-Path $AddonDest) { Remove-Item -Recurse -Force $AddonDest }
Copy-Item -Recurse -Force $AddonSource $AddonDest

Write-Host "MPlusForm rc10.7 verified-tooltip addon installed:"
Write-Host $AddonDest
Write-Host "Expected in game: /mpf status -> 1.4.2-rc10.7-retail12-verified-tooltip-safe. After key: /mpf syncnow."
