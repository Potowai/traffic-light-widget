# Build artifacts: PNG snapshot for README + multi-size ICO for tray icon.
#   ./build.ps1                         default
#   ./build.ps1 -Out docs/snap.png      custom snapshot output path
param(
    [string]$Out = "traffic-light-widget.png",
    [string]$Icon = "traffic-light-icon.ico"
)
$ErrorActionPreference = "Stop"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $dir "TrafficLightWidget.py"

& python $py --snapshot $Out
if (-not (Test-Path $Out)) { Write-Error "snapshot failed" }

& python $py --icon $Icon
if (-not (Test-Path $Icon)) { Write-Error "icon failed" }

$iconPng = $Icon -replace "\.ico$", ".png"
if (-not (Test-Path $iconPng)) { Write-Error "icon png failed" }

Write-Output "OK all artifacts built"
