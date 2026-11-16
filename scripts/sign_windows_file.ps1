#Requires -Version 5.1
<#
.SYNOPSIS
    Authenticode-sign one Koto Windows executable with a certificate from the
    current user's Personal certificate store.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$FilePath,
    [Parameter(Mandatory = $true)][string]$Thumbprint,
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$resolvedPath = (Resolve-Path -LiteralPath $FilePath -ErrorAction Stop).Path
$normalizedThumbprint = ($Thumbprint -replace '[^0-9A-Fa-f]', '').ToUpperInvariant()
if ($normalizedThumbprint -notmatch '^[0-9A-F]{40,128}$') {
    throw "The code-signing certificate thumbprint is invalid."
}

$certificatePath = "Cert:\CurrentUser\My\$normalizedThumbprint"
$certificate = Get-Item -Path $certificatePath -ErrorAction Stop
if (-not $certificate.HasPrivateKey) {
    throw "The code-signing certificate has no accessible private key."
}
$now = Get-Date
if ($certificate.NotBefore -gt $now -or $certificate.NotAfter -le $now) {
    throw "The code-signing certificate is not currently valid."
}
$codeSigningEku = @(
    $certificate.EnhancedKeyUsageList |
        Where-Object { $_.ObjectId.Value -eq '1.3.6.1.5.5.7.3.3' }
)
if ($codeSigningEku.Count -eq 0) {
    throw "The selected certificate is not valid for code signing."
}

$timestampUri = $null
if (-not [Uri]::TryCreate($TimestampUrl, [UriKind]::Absolute, [ref]$timestampUri) -or
    $timestampUri.Scheme -notin @('http', 'https')) {
    throw "TimestampUrl must be an absolute HTTP or HTTPS URL."
}

$resolver = Join-Path $PSScriptRoot "resolve_signtool.ps1"
$signTool = (& $resolver -Quiet) | Select-Object -First 1
if (-not $signTool -or -not (Test-Path -LiteralPath $signTool -PathType Leaf)) {
    throw "Windows SDK SignTool is required for RFC 3161 Authenticode signing."
}

& $signTool sign `
    /sha1 $normalizedThumbprint `
    /s My `
    /fd SHA256 `
    /tr $timestampUri.AbsoluteUri `
    /td SHA256 `
    /d Koto `
    /du "https://github.com/Loganwon/Koto" `
    $resolvedPath
if ($LASTEXITCODE -ne 0) {
    throw "SignTool failed with exit code $LASTEXITCODE for '$resolvedPath'."
}

$signature = Get-AuthenticodeSignature -LiteralPath $resolvedPath

if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
    throw "Authenticode signing failed for '$resolvedPath': $($signature.StatusMessage)"
}
if (-not $signature.TimeStamperCertificate) {
    throw "Authenticode signing did not attach an RFC 3161 timestamp: $resolvedPath"
}
if ($signature.SignerCertificate.Thumbprint.ToUpperInvariant() -ne $normalizedThumbprint) {
    throw "Authenticode signer mismatch after signing: $resolvedPath"
}

Write-Host "[sign] Valid SHA-256 Authenticode signature: $resolvedPath"
