<#
    Install the Bambu Status widget for the current user.

    No admin rights, nothing outside the user profile:
      %LOCALAPPDATA%\Programs\BambuStatus   the widget and the monitor
      %APPDATA%\BambuStatus\config.json     printer host, serial, access code
      HKCU\...\CurrentVersion\Run           start it at logon

    Run it with:  powershell -ExecutionPolicy Bypass -File .\windows\install.ps1
#>
[CmdletBinding()]
param(
    [switch]$NoAutostart,   # skip the logon entry
    [switch]$NoStart        # install but do not launch it now
)

$ErrorActionPreference = "Stop"

$src     = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo    = Split-Path -Parent $src
$dest    = Join-Path $env:LOCALAPPDATA "Programs\BambuStatus"
$confDir = Join-Path $env:APPDATA "BambuStatus"
$conf    = Join-Path $confDir "config.json"

$common = Join-Path $src "common.ps1"
if (-not (Test-Path $common)) {
    Write-Host "Missing $common - this clone is incomplete." -ForegroundColor Red
    Write-Host "Run 'git pull' in the repository and try again."
    exit 1
}
. $common

$python = Find-Python
if (-not $python) {
    Write-Host ""
    Write-Host "No usable Python found." -ForegroundColor Red
    Write-Host "Install Python 3.9 or newer from https://www.python.org/downloads/"
    Write-Host "and keep the 'tcl/tk and IDLE' option ticked - the widget is drawn with tkinter."
    exit 1
}
$pythonw = Join-Path (Split-Path -Parent $python) "pythonw.exe"
if (-not (Test-Path $pythonw)) { $pythonw = $python }   # no windowless build: live with a console
Write-Host "==> python: $python"

Write-Host "==> installing to $dest"
New-Item -ItemType Directory -Force -Path $dest, $confDir | Out-Null
Copy-Item (Join-Path $src "bambu_widget.pyw") $dest -Force
Copy-Item (Join-Path $src "winui.py")         $dest -Force
# the monitor is the same file the Linux daemon uses; it only gains an
# extension here so the widget can import it
Copy-Item (Join-Path $repo "bin\bambu-monitor") (Join-Path $dest "bambu_monitor.py") -Force

$widget = Join-Path $dest "bambu_widget.pyw"

if (-not (Test-Path $conf)) {
    Write-Host "==> writing config template to $conf"
    $template = @"
{
  "host": "192.168.0.000",
  "serial": "PUT-YOUR-SERIAL-HERE",
  "accessCode": "00000000"
}
"@
    # no BOM: the monitor reads this as UTF-8
    [System.IO.File]::WriteAllText($conf, $template, (New-Object System.Text.UTF8Encoding($false)))
} else {
    Write-Host "==> keeping existing config at $conf"
}

# Start menu entry
$programs = [Environment]::GetFolderPath("Programs")
$lnk = Join-Path $programs "Bambu Status.lnk"
try {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($lnk)
    $shortcut.TargetPath = $pythonw
    $shortcut.Arguments = "`"$widget`""
    $shortcut.WorkingDirectory = $dest
    $shortcut.Description = "Bambu Lab print progress on the taskbar"
    $shortcut.Save()
    Write-Host "==> start menu shortcut created"
} catch {
    Write-Host "    (could not create the start menu shortcut: $($_.Exception.Message))"
}

if (-not $NoAutostart) {
    $run = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    Set-ItemProperty -Path $run -Name "BambuStatus" -Value "`"$pythonw`" `"$widget`""
    Write-Host "==> will start at logon (right click the widget to turn that off)"
}

if (-not $NoStart) {
    Stop-Widget
    Start-Process -FilePath $pythonw -ArgumentList "`"$widget`"" -WorkingDirectory $dest
    Write-Host "==> started"
}

Write-Host ""
Write-Host "Done. The widget takes the printer's address, serial, access code and"
Write-Host "name from Bambu Studio or OrcaSlicer by itself, so if either has ever"
Write-Host "talked to your printer there is nothing left to do."
Write-Host ""
Write-Host "If it says it is still looking, set it straight by hand:"
Write-Host "  right click the widget -> Find my printer...   (or edit $conf)"
Write-Host "  the printer screen shows all three under Settings -> WLAN,"
Write-Host "  and LAN mode has to be on."
Write-Host ""
Write-Host "Drag the widget to move it, right click it for the menu."
