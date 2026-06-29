# Remove the Traffic Light Widget. Per-user, no admin.
$ErrorActionPreference = "Stop"

# Kill running widget processes launched from our install location.
$exe = Join-Path $env:LOCALAPPDATA "TrafficLightWidget" "TrafficLightWidget.py"
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*TrafficLightWidget.py*" } |
    ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }

# Remove startup shortcut.
$startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$shortcutPath = Join-Path $startup "Traffic Light Widget.lnk"
if (Test-Path $shortcutPath) { Remove-Item $shortcutPath -Force }
Write-Output "OK removed startup shortcut"

# Remove installed widget.
$dest = Join-Path $env:LOCALAPPDATA "TrafficLightWidget"
if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
Write-Output "OK removed $dest"

# Leave opencode and copilot state untouched.
Write-Output "Done. (Your opencode sessions and Copilot session state are untouched.)"
