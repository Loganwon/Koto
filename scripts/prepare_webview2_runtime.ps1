#Requires -Version 5.1
<#
.SYNOPSIS
    Downloads and verifies Microsoft's x64 Evergreen WebView2 standalone installer.
.DESCRIPTION
    Formal Koto Windows releases carry the offline installer so a clean Windows
    10/11 x64 machine does not need a preinstalled browser runtime.  The payload
    is build output (gitignored), and is accepted only when its Authenticode
    signature is valid and belongs to Microsoft Corporation.
#>
param(
    [string]$OutputDir = "",
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $RepoRoot "build\prerequisites"
}
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
$InstallerName = "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
$InstallerPath = Join-Path $OutputDir $InstallerName
$MetadataPath = Join-Path $OutputDir "webview2-runtime.json"
$DownloadUrl = "https://go.microsoft.com/fwlink/?linkid=2124701"
$MinimumSize = 100MB

function Test-MicrosoftSignedInstaller {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    if ((Get-Item -LiteralPath $Path).Length -lt $MinimumSize) { return $false }

    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        return $false
    }
    if (-not $signature.SignerCertificate -or $signature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') {
        return $false
    }
    return $true
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

if ($Force -or -not (Test-MicrosoftSignedInstaller -Path $InstallerPath)) {
    $DownloadPath = "$InstallerPath.download"
    Remove-Item -LiteralPath $DownloadPath -Force -ErrorAction SilentlyContinue
    Write-Host "Downloading Microsoft WebView2 Evergreen standalone installer..."
    try {
        Invoke-WebRequest -Uri $DownloadUrl -OutFile $DownloadPath -UseBasicParsing
        if (-not (Test-MicrosoftSignedInstaller -Path $DownloadPath)) {
            throw "Downloaded WebView2 installer failed size or Microsoft Authenticode verification."
        }
        Move-Item -LiteralPath $DownloadPath -Destination $InstallerPath -Force
    }
    finally {
        Remove-Item -LiteralPath $DownloadPath -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-MicrosoftSignedInstaller -Path $InstallerPath)) {
    throw "WebView2 prerequisite is missing or not signed by Microsoft: $InstallerPath"
}

$item = Get-Item -LiteralPath $InstallerPath
$hash = (Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash.ToLowerInvariant()
$signature = Get-AuthenticodeSignature -LiteralPath $InstallerPath
$metadata = [ordered]@{
    schema_version = 1
    source_url = $DownloadUrl
    file_name = $InstallerName
    product_version = $item.VersionInfo.ProductVersion
    size_bytes = $item.Length
    sha256 = $hash
    signer = $signature.SignerCertificate.Subject
    prepared_at = (Get-Date).ToUniversalTime().ToString("o")
}
$metadata | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $MetadataPath -Encoding UTF8

Write-Output $InstallerPath
