#Requires -Version 5.1
<#
.SYNOPSIS
    Resolve the local Inno Setup compiler path used by Koto release scripts.
#>

param(
    [switch]$Quiet
)

$candidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)

foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
        if (-not $Quiet) {
            Write-Host "Found Inno Setup: $candidate"
        }
        Write-Output $candidate
        return
    }
}

if (-not $Quiet) {
    Write-Host "Inno Setup 6 compiler not found in known locations."
}
