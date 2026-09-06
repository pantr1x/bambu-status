<#
    Remove the Bambu Status widget. Leaves the printer config behind unless
    -Purge is given.

    Run it with:  powershell -ExecutionPolicy Bypass -File .\windows\uninstall.ps1
#>
[CmdletBinding()]
param([switch]$Purge)

$ErrorActionPreference = "Stop"

$dest    = Join-Path $env:LOCALAPPDATA "Programs\BambuStatus"
$confDir = Join-Path $env:APPDATA "BambuStatus"
$cache   = Join-Path $env:LOCALAPPDATA "BambuStatus"
$lnk     = Join-Path ([Environment]::GetFolderPath("Programs")) "Bambu Status.lnk"

Write-Host "==> stopping the widget"
Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like "*bambu_widget.pyw*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Write-Host "==> removing the logon entry"
Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" `
    -Name "BambuStatus" -ErrorAction SilentlyContinue

foreach ($path in @($lnk, $dest, $cache)) {
    if (Test-Path $path) {
        Write-Host "==> removing $path"
        Remove-Item $path -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if ($Purge) {
    if (Test-Path $confDir) {
        Write-Host "==> removing $confDir"
        Remove-Item $confDir -Recurse -Force
    }
} else {
    Write-Host ""
    Write-Host "Printer config kept at $confDir (run with -Purge to delete it)."
}
