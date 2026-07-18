<#
Runs inside Windows Sandbox. The host maps the release payload and tests as
read-only folders and maps the result folder as writable.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SetupExe,
    [string]$ResultsDir = "C:\KotoResults",
    [int]$Port = 5099,
    [int]$DesktopHoldSec = 12,
    [switch]$RequireCodeSigning
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Path $ResultsDir -Force | Out-Null
$transcript = Join-Path $ResultsDir "windows-sandbox-installer-e2e.log"
$resultPath = Join-Path $ResultsDir "windows-sandbox-result.json"
$exitCode = 1

Start-Transcript -Path $transcript -Force | Out-Null
try {
    $e2eArguments = @(
        '-NoLogo',
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', 'C:\KotoTests\test_installer_e2e.ps1',
        '-SetupExe', $SetupExe,
        '-TestInstallDir', 'C:\KotoE2E',
        '-Port', [string]$Port,
        '-EvidenceDir', $ResultsDir,
        '-DesktopHoldSec', [string]$DesktopHoldSec
    )
    if ($RequireCodeSigning) {
        $e2eArguments += '-RequireCodeSigning'
    }
    & powershell.exe @e2eArguments
    $exitCode = $LASTEXITCODE
}
catch {
    Write-Error $_
    $exitCode = 1
}
finally {
    [ordered]@{
        completed_at = (Get-Date).ToString("o")
        setup_exe = $SetupExe
        require_code_signing = [bool]$RequireCodeSigning
        exit_code = $exitCode
        passed = ($exitCode -eq 0)
    } | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    Stop-Transcript | Out-Null
}

exit $exitCode
