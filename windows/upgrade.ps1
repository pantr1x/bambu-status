<#
    Bring an installed Bambu Status up to date, and say whether it worked.

    Pulls the repository, reinstalls, and then waits for the monitor to report
    that it has actually reached the printer. If it has not, it runs the
    diagnostics for you rather than leaving you to guess.

    Run it with:  powershell -ExecutionPolicy Bypass -File .\windows\upgrade.ps1

    Nothing here deletes anything: your config is left alone, and the pull
    refuses to run over uncommitted changes rather than throwing them away.
#>
[CmdletBinding()]
param(
    [string]$Branch = "main",   # the branch to update from
    [int]$Wait = 25,            # seconds to give the monitor to connect
    [switch]$NoVerify           # install only, do not wait or diagnose
)

$ErrorActionPreference = "Stop"

$src  = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $src

$common = Join-Path $src "common.ps1"
if (-not (Test-Path $common)) {
    Write-Host "Missing $common - this clone is incomplete." -ForegroundColor Red
    Write-Host "Run 'git pull' in the repository and try again."
    exit 1
}
. $common

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "git is not on PATH." -ForegroundColor Red
    Write-Host "Install it from https://git-scm.com/download/win, or download the"
    Write-Host "repository as a ZIP and run windows\install.ps1 from it."
    exit 1
}

# ------------------------------------------------------------------ the pull
Push-Location $repo
try {
    # uncommitted work is yours; refuse rather than pull over it
    $dirty = & git status --porcelain
    if ($LASTEXITCODE -ne 0) { Write-Host "Not a git repository: $repo" -ForegroundColor Red; exit 1 }
    if ($dirty) {
        Write-Host "You have uncommitted changes in $repo :" -ForegroundColor Yellow
        $dirty | ForEach-Object { Write-Host "    $_" }
        Write-Host "Commit or stash them first - this script will not overwrite them."
        exit 1
    }

    Write-Host "==> fetching"
    & git fetch origin
    if ($LASTEXITCODE -ne 0) { Write-Host "git fetch failed." -ForegroundColor Red; exit 1 }

    $current = (& git rev-parse --abbrev-ref HEAD).Trim()
    if ($current -ne $Branch) {
        Write-Host "==> switching from $current to $Branch"
        & git checkout $Branch
        if ($LASTEXITCODE -ne 0) { Write-Host "Could not switch to $Branch." -ForegroundColor Red; exit 1 }
    }

    Write-Host "==> updating $Branch"
    & git pull --ff-only origin $Branch
    if ($LASTEXITCODE -ne 0) {
        Write-Host "git pull failed - your branch has commits that $Branch does not." -ForegroundColor Red
        Write-Host "Nothing was changed."
        exit 1
    }
    $head = (& git log -1 --format="%h %s").Trim()
    Write-Host "    now at: $head"
} finally {
    Pop-Location
}

# ------------------------------------------------------------------ install
# install.ps1 stops the running widget and starts the new one itself
Write-Host ""
& (Join-Path $src "install.ps1")
if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
    Write-Host "install.ps1 did not finish." -ForegroundColor Red
    exit 1
}

if ($NoVerify) { exit 0 }

# ------------------------------------------------------------------ verify
# The widget has just started; give the monitor its own word on whether it got
# through, rather than declaring success because files were copied.
$monitor = Join-Path $env:LOCALAPPDATA "Programs\BambuStatus\bambu_monitor.py"
$python  = Find-Python -NoTk
if (-not $python -or -not (Test-Path $monitor)) {
    Write-Host ""
    Write-Host "Installed, but could not run the check." -ForegroundColor Yellow
    Write-Host "Right click the widget -> Diagnostics... to see what it found."
    exit 0
}

Write-Host ""
Write-Host "==> waiting up to $Wait s for the printer"
& $python $monitor --verify $Wait
$connected = ($LASTEXITCODE -eq 0)

if ($connected) {
    Write-Host ""
    Write-Host "Done - the widget is live." -ForegroundColor Green
    exit 0
}

Write-Host ""
Write-Host "==> not connected yet, running the diagnostics" -ForegroundColor Yellow
& (Join-Path $src "doctor.ps1") -NoOpen
Write-Host ""
Write-Host "The report above is also in $env:LOCALAPPDATA\BambuStatus\diagnostics.txt" -ForegroundColor Yellow
Write-Host "Access codes and the account token are masked, so it is safe to paste."
exit 1
