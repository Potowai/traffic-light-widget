# Install the Traffic Light Widget as a per-user startup shortcut on Windows 11.
#
#   ./install.ps1
#
# Everything is per-user — nothing is installed system-wide, no admin needed.
[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$dest = Join-Path $env:LOCALAPPDATA "TrafficLightWidget"
$exe  = Join-Path $dest "TrafficLightWidget.py"

# --- prerequisites ----------------------------------------------------------
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    $pyExe = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
    if (-not $pyExe) { Write-Error "python/pythonw not found on PATH. Install Python 3.10+ first." }
} else {
    $pyExe = $python.Source
}
$pyw = $pyExe -replace "python\.exe$", "pythonw.exe"
if (-not (Test-Path $pyw)) { $pyw = $pyExe }

Write-Output "-> python: $pyExe"
Write-Output "-> pythonw: $pyw"

# --- 1. copy the widget -----------------------------------------------------
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item -Force (Join-Path $dir "TrafficLightWidget.py") $exe
Write-Output "OK widget copied -> $dest"

# --- 2. startup shortcut ----------------------------------------------------
$startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
New-Item -ItemType Directory -Force -Path $startup | Out-Null
$shortcutPath = Join-Path $startup "Traffic Light Widget.lnk"

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($shortcutPath)
$sc.TargetPath = $pyw
$sc.Arguments = "`"$exe`""
$sc.WorkingDirectory = $dest
$sc.WindowStyle = 7
$sc.Description = "Traffic Light Widget"
$sc.IconLocation = "$pyw,0"
$sc.Save()
Write-Output "OK startup shortcut -> $shortcutPath"

# --- 3. launch now ----------------------------------------------------------
Start-Process -FilePath $pyw -ArgumentList "`"$exe`"" -WorkingDirectory $dest -WindowStyle Hidden
Write-Output ""
Write-Output "Done. The widget appears top-right (drag to move, right-click for menu)."
Write-Output "Uninstall any time with ./uninstall.ps1"
