<#
    Run the monitor's own diagnostics and say where the chain breaks.

    The widget runs under pythonw.exe, which has no console, so --doctor has
    nowhere to print to. This finds the installed copy (or this clone), runs
    --doctor and --dump-slicer, shows them and writes them to a file that is
    safe to paste into a bug report: the monitor masks the access code and the
    account token itself.

    Run it with:  powershell -ExecutionPolicy Bypass -File .\windows\doctor.ps1
#>
[CmdletBinding()]
param(
    [switch]$Offline,   # skip the network half: no LAN listen, no account
    [switch]$NoOpen     # write the report but do not open it
)

$ErrorActionPreference = "Stop"

$src      = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo     = Split-Path -Parent $src
$installed = Join-Path $env:LOCALAPPDATA "Programs\BambuStatus\bambu_monitor.py"
$clone     = Join-Path $repo "bin\bambu-monitor"

# the installed copy first: it is the one that is actually failing
$monitor = if (Test-Path $installed) { $installed } elseif (Test-Path $clone) { $clone } else { $null }
if (-not $monitor) {
    Write-Host "No bambu-monitor found." -ForegroundColor Red
    Write-Host "Install it first:  powershell -ExecutionPolicy Bypass -File .\windows\install.ps1"
    exit 1
}

function Find-Python {
    $candidates = New-Object System.Collections.Generic.List[string]
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $exe = & py -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) { $candidates.Add($exe.Trim()) }
    }
    foreach ($name in @("python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -notlike "*\WindowsApps\*") { $candidates.Add($cmd.Source) }
    }
    foreach ($exe in $candidates) {
        & $exe -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { return $exe }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host "No usable Python found - install 3.9 or newer from python.org." -ForegroundColor Red
    exit 1
}

# bin\bambu-monitor deliberately has no extension, and python will not import
# or run a file it cannot name; a byte-exact copy under .py fixes that without
# touching the original
$run = $monitor
$temp = $null
if ([System.IO.Path]::GetExtension($monitor) -ne ".py") {
    $temp = Join-Path ([System.IO.Path]::GetTempPath()) "bambu_monitor_doctor.py"
    Copy-Item -LiteralPath $monitor -Destination $temp -Force
    $run = $temp
}

$flags = @()
if ($Offline) { $flags += "--offline" }

# the report is written in UTF-8 and the console codepage is usually not: left
# alone, python raises UnicodeEncodeError halfway through and the half that
# explains the failure is the half that is lost
$env:PYTHONIOENCODING = "utf-8"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$report = New-Object System.Text.StringBuilder
try {
    foreach ($mode in @("--doctor", "--dump-slicer")) {
        $out = & $python $run $mode @flags 2>&1 | Out-String
        [void]$report.AppendLine($out)
    }
} finally {
    if ($temp -and (Test-Path $temp)) { Remove-Item -LiteralPath $temp -Force }
}

$text = $report.ToString()
Write-Host $text

$dir  = Join-Path $env:LOCALAPPDATA "BambuStatus"
$file = Join-Path $dir "diagnostics.txt"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
[System.IO.File]::WriteAllText($file, $text, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "==> written to $file" -ForegroundColor Green
Write-Host "    Access codes and the account token are masked, so it is safe to paste."
if (-not $NoOpen) { Start-Process notepad.exe $file }
