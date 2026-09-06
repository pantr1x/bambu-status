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

function Find-Python {
    # tkinter ships with the python.org installer but can be left out of some
    # builds, so test for it rather than trusting the first python on PATH
    $candidates = New-Object System.Collections.Generic.List[string]
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $exe = & py -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) { $candidates.Add($exe.Trim()) }
    }
    foreach ($name in @("python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        # the Store stub on PATH is not an interpreter, it is an advert
        if ($cmd -and $cmd.Source -notlike "*\WindowsApps\*") { $candidates.Add($cmd.Source) }
    }
    foreach ($exe in $candidates) {
        & $exe -c "import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { return $exe }
    }
    return $null
}

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
    Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" |
        Where-Object { $_.CommandLine -like "*bambu_widget.pyw*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
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
