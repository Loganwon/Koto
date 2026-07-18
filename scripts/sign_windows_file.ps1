#Requires -Version 5.1

<#
.SYNOPSIS
    Sign or verify a Windows executable with the Koto release certificate.
.DESCRIPTION
    Uses a certificate that is already present in Cert:\CurrentUser\My and has
    an accessible private key. The certificate thumbprint is supplied explicitly
    or through KOTO_SIGNING_CERT_THUMBPRINT. RFC 3161/SHA-256 timestamping is
    mandatory for signing and verification.
#>

param(
    [string]$FilePath = "",
    [string]$CertificateThumbprint = $env:KOTO_SIGNING_CERT_THUMBPRINT,
    [string]$TimestampServer = $(
        if ($env:KOTO_SIGNING_TIMESTAMP_SERVER) {
            $env:KOTO_SIGNING_TIMESTAMP_SERVER
        } else {
            "http://timestamp.digicert.com"
        }
    ),
    [switch]$ValidateOnly,
    [switch]$VerifyOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-SignTool {
    $fromPath = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($fromPath) {
        return $fromPath.Source
    }

    $kitRoots = @(
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin",
        "$env:ProgramFiles\Windows Kits\10\bin"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Container) }
    $candidates = foreach ($root in $kitRoots) {
        Get-ChildItem -LiteralPath $root -Filter signtool.exe -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '[\\/]x64[\\/]signtool\.exe$' }
    }
    $selected = $candidates | Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $selected) {
        throw "signtool.exe was not found. Install the Windows SDK signing tools."
    }
    return $selected.FullName
}

function Get-CodeSigningCertificate {
    param([Parameter(Mandatory = $true)][string]$Thumbprint)

    $normalized = ($Thumbprint -replace '[^0-9A-Fa-f]', '').ToUpperInvariant()
    if ($normalized -notmatch '^[0-9A-F]{40}$') {
        throw "The code-signing certificate thumbprint must contain exactly 40 hexadecimal characters."
    }

    $certificate = Get-Item -LiteralPath "Cert:\CurrentUser\My\$normalized" -ErrorAction SilentlyContinue
    if (-not $certificate) {
        throw "Code-signing certificate $normalized was not found in Cert:\CurrentUser\My."
    }
    if (-not $certificate.HasPrivateKey) {
        throw "Code-signing certificate $normalized does not have an accessible private key."
    }

    $now = Get-Date
    if ($certificate.NotBefore -gt $now -or $certificate.NotAfter -le $now) {
        throw "Code-signing certificate $normalized is not currently valid."
    }
    $codeSigningOid = '1.3.6.1.5.5.7.3.3'
    $ekuOids = @($certificate.EnhancedKeyUsageList | ForEach-Object { $_.ObjectId.Value })
    if ($codeSigningOid -notin $ekuOids) {
        throw "Certificate $normalized is not authorized for Code Signing ($codeSigningOid)."
    }
    return $certificate
}

function Assert-AuthenticodeSignature {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedThumbprint,
        [Parameter(Mandatory = $true)][string]$SignTool
    )

    & $SignTool verify /pa /tw $Path | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "SignTool verification failed for $Path (exit $LASTEXITCODE)."
    }

    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        throw "Authenticode verification failed for ${Path}: $($signature.Status)."
    }
    if (-not $signature.SignerCertificate -or
        $signature.SignerCertificate.Thumbprint -ne $ExpectedThumbprint) {
        throw "Authenticode signer mismatch for $Path."
    }
    if (-not $signature.TimeStamperCertificate) {
        throw "The signature on $Path does not carry a trusted timestamp."
    }
}

$certificate = Get-CodeSigningCertificate -Thumbprint $CertificateThumbprint
$normalizedThumbprint = $certificate.Thumbprint.ToUpperInvariant()
$signTool = Resolve-SignTool

if ($ValidateOnly) {
    Write-Host "Code-signing certificate ready: $($certificate.Subject) [$normalizedThumbprint]"
    Write-Host "SignTool: $signTool"
    exit 0
}

if ([string]::IsNullOrWhiteSpace($FilePath)) {
    throw "FilePath is required unless -ValidateOnly is used."
}
$resolvedPath = (Resolve-Path -LiteralPath $FilePath -ErrorAction Stop).Path

if (-not $VerifyOnly) {
    if ([string]::IsNullOrWhiteSpace($TimestampServer) -or
        $TimestampServer -notmatch '^https?://') {
        throw "TimestampServer must be an HTTP(S) RFC 3161 endpoint."
    }
    & $signTool sign `
        /sha1 $normalizedThumbprint `
        /s My `
        /fd SHA256 `
        /tr $TimestampServer `
        /td SHA256 `
        /d "Koto" `
        $resolvedPath | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "SignTool signing failed for $resolvedPath (exit $LASTEXITCODE)."
    }
}

Assert-AuthenticodeSignature `
    -Path $resolvedPath `
    -ExpectedThumbprint $normalizedThumbprint `
    -SignTool $signTool
Write-Host "Authenticode signature verified: $resolvedPath"
