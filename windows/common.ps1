<#
    Shared by install.ps1, upgrade.ps1 and doctor.ps1. Dot-source it:

        . (Join-Path $PSScriptRoot "common.ps1")

    Nothing here does anything on its own.
#>

function Find-Python {
    <#
        The interpreter to run the widget and the monitor with.

        tkinter ships with the python.org installer but can be left out of some
        builds, so test for it rather than trusting the first python on PATH.
        Pass -NoTk when only the monitor is being run: --doctor and --verify
        draw nothing, and a python without tkinter is perfectly good for them.
    #>
    [CmdletBinding()]
    param([switch]$NoTk)

    $probe = if ($NoTk) { "import sys" } else { "import sys, tkinter" }
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
        & $exe -c "$probe; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { return $exe }
    }
    return $null
}

function Stop-Widget {
    <# Close the running widget, if there is one. Silent when there is not. #>
    Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" |
        Where-Object { $_.CommandLine -like "*bambu_widget.pyw*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
