#Requires -Version 5.1
<#
.SYNOPSIS
    Resolve the newest x64 SignTool shipped by the Windows SDK.
#>

[CmdletBinding()]
param([switch]$Quiet)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$command = Get-Command signtool.exe -ErrorAction SilentlyContinue
if ($command -and (Test-Path -LiteralPath $command.Source -PathType Leaf)) {
    $command.Source
    exit 0
}

$sdkRoots = [System.Collections.Generic.List[string]]::new()
if (${env:ProgramFiles(x86)}) {
    $sdkRoots.Add((Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"))
}
if ($env:ProgramFiles) {
    $sdkRoots.Add((Join-Path $env:ProgramFiles "Windows Kits\10\bin"))
}

foreach ($root in $sdkRoots) {
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { continue }
    $versions = @(
        Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^\d+[.]\d+[.]\d+[.]\d+$' } |
            Sort-Object { [version]$_.Name } -Descending
    )
    foreach ($version in $versions) {
        $candidate = Join-Path $version.FullName "x64\signtool.exe"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $candidate
            exit 0
        }
    }
}

if (-not $Quiet) {
    Write-Error "Windows SDK SignTool was not found. Install the Windows 10/11 SDK."
}
exit 1
