#Requires -Version 5.1
<#
.SYNOPSIS
    Verify Koto Authenticode signatures, signer identity, and timestamps.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string[]]$FilePath,
    [string]$ExpectedThumbprint = "",
    [switch]$RequireTimestamp
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$normalizedExpected = ($ExpectedThumbprint -replace '[^0-9A-Fa-f]', '').ToUpperInvariant()
if ($ExpectedThumbprint -and $normalizedExpected -notmatch '^[0-9A-F]{40,128}$') {
    throw "ExpectedThumbprint is invalid."
}

$failures = [System.Collections.Generic.List[string]]::new()
foreach ($candidate in $FilePath) {
    try {
        $resolvedPath = (Resolve-Path -LiteralPath $candidate -ErrorAction Stop).Path
        $signature = Get-AuthenticodeSignature -LiteralPath $resolvedPath
        if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
            throw "signature status is $($signature.Status): $($signature.StatusMessage)"
        }
        if (-not $signature.SignerCertificate) {
            throw "signer certificate is missing"
        }
        $actualThumbprint = $signature.SignerCertificate.Thumbprint.ToUpperInvariant()
        if ($normalizedExpected -and $actualThumbprint -ne $normalizedExpected) {
            throw "signer thumbprint does not match the release certificate"
        }
        if ($RequireTimestamp -and -not $signature.TimeStamperCertificate) {
            throw "trusted timestamp is missing"
        }
        Write-Host "[signature] Valid: $resolvedPath"
    }
    catch {
        $failures.Add("$candidate -- $($_.Exception.Message)")
    }
}

if ($failures.Count -gt 0) {
    throw "Windows signature verification failed:`n$([string]::Join("`n", $failures))"
}
