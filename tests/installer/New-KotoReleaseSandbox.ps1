<#
Generates and optionally launches a Windows Sandbox configuration for Koto's
real installer E2E. Requires Windows Sandbox (Windows Pro/Enterprise).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SetupExe,
    [string]$ResultsDir = "",
    [string]$ConfigPath = "",
    [switch]$Launch
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..\..")
$setupPath = (Resolve-Path $SetupExe).Path
$setupDirectory = Split-Path -Parent $setupPath
$setupName = Split-Path -Leaf $setupPath

if ([string]::IsNullOrWhiteSpace($ResultsDir)) {
    $ResultsDir = Join-Path $repoRoot "dist\windows-sandbox-results"
}
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $repoRoot "dist\Koto-release-test.wsb"
}
$resultsPath = [System.IO.Path]::GetFullPath($ResultsDir)
$configFullPath = [System.IO.Path]::GetFullPath($ConfigPath)
New-Item -ItemType Directory -Path $resultsPath -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path -Parent $configFullPath) -Force | Out-Null

function Escape-Xml([string]$Value) {
    return [System.Security.SecurityElement]::Escape($Value)
}

$sandboxExe = Join-Path $env:SystemRoot "System32\WindowsSandbox.exe"
if ($Launch -and -not (Test-Path $sandboxExe)) {
    throw "Windows Sandbox is unavailable. Use Windows Pro/Enterprise and enable the Windows Sandbox optional feature."
}

$hostSetup = Escape-Xml $setupDirectory
$hostTests = Escape-Xml $scriptDir
$hostResults = Escape-Xml $resultsPath
$guestSetup = Escape-Xml ("C:\KotoRelease\" + $setupName)
$command = "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File C:\KotoTests\run_windows_sandbox_release.ps1 -SetupExe `"$guestSetup`""
$commandXml = Escape-Xml $command

$wsb = @"
<Configuration>
  <Networking>Default</Networking>
  <ClipboardRedirection>Disable</ClipboardRedirection>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>$hostSetup</HostFolder>
      <SandboxFolder>C:\KotoRelease</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
    <MappedFolder>
      <HostFolder>$hostTests</HostFolder>
      <SandboxFolder>C:\KotoTests</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
    <MappedFolder>
      <HostFolder>$hostResults</HostFolder>
      <SandboxFolder>C:\KotoResults</SandboxFolder>
      <ReadOnly>false</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>$commandXml</Command>
  </LogonCommand>
</Configuration>
"@

Set-Content -LiteralPath $configFullPath -Value $wsb -Encoding UTF8
Write-Host "Windows Sandbox configuration: $configFullPath"
Write-Host "Result folder: $resultsPath"

if ($Launch) {
    Start-Process -FilePath $sandboxExe -ArgumentList $configFullPath | Out-Null
    Write-Host "Windows Sandbox launched. It will write logs, JSON results, and a desktop screenshot to the result folder."
}
