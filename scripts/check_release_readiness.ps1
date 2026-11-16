#Requires -Version 5.1
<#
.SYNOPSIS
    Produce one actionable Koto Windows release-readiness report.
.DESCRIPTION
    Collects all cheap preflight checks before the expensive release gate.
    Blocking issues and optional recommendations are reported separately.
#>

[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$CodeSigningThumbprint = $env:KOTO_CODE_SIGNING_THUMBPRINT,
    [string]$JsonOutput = "",
    [string]$MarkdownOutput = "",
    [switch]$RequireFormal,
    [switch]$SkipArtifactInspection
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)
$checks = [System.Collections.Generic.List[object]]::new()

function Add-ReadinessCheck {
    param(
        [Parameter(Mandatory = $true)][string]$Id,
        [Parameter(Mandatory = $true)][ValidateSet('pass', 'block', 'advisory')][string]$Status,
        [Parameter(Mandatory = $true)][string]$Summary,
        [string]$Remediation = "",
        [hashtable]$Details = @{}
    )

    $script:checks.Add([pscustomobject][ordered]@{
        id = $Id
        status = $Status
        summary = $Summary
        remediation = $Remediation
        details = [pscustomobject]$Details
    })
}

function Resolve-OptionalTool {
    param([Parameter(Mandatory = $true)][string]$Resolver)

    if (-not (Test-Path -LiteralPath $Resolver -PathType Leaf)) { return $null }
    $resolved = (& $Resolver -Quiet 2>$null) | Select-Object -First 1
    if ($LASTEXITCODE -ne 0 -or -not $resolved) { return $null }
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) { return $null }
    return [System.IO.Path]::GetFullPath([string]$resolved)
}

function Get-ChangeArea {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $path = $RelativePath.Replace('\', '/').Trim('"')
    if ($path -match '^([.]codex/designs/|data/README[.]md$)') {
        return 'documentation'
    }
    if ($path -match '^(web/static/js/build/|web/static/js/.*[.]map$|web/_npm_build[.]txt$)') {
        return 'generated_frontend'
    }
    if ($path -match '^(dist/|logs/|data/|_test_screenshots/|[.]pytest_cache|[.]codex/)') {
        return 'local_runtime_or_evidence'
    }
    if ($path -match '^(tests/|test_)') { return 'tests' }
    if ($path -match '^(docs/|README[.]md$|CONTRIBUTING[.]md$|CHANGELOG[.]md$)') {
        return 'documentation'
    }
    if ($path -match '^([.]github/|scripts/|config/|Build_Release[.]ps1$|koto_installer[.]iss$|koto[.]spec$)') {
        return 'release_and_configuration'
    }
    if ($path -match '^(app/|launcher/|src/|web/)') { return 'product_source' }
    return 'other'
}

$gitCommand = Get-Command git -ErrorAction SilentlyContinue
if (-not $gitCommand) {
    Add-ReadinessCheck -Id 'git_available' -Status 'block' `
        -Summary 'Git is not available.' `
        -Remediation 'Install Git and reopen the terminal.'
} else {
    Add-ReadinessCheck -Id 'git_available' -Status 'pass' `
        -Summary 'Git is available.' -Details @{ path = $gitCommand.Source }

    $insideWorktree = (& git -C $RepoRoot rev-parse --is-inside-work-tree 2>$null)
    if ($LASTEXITCODE -ne 0 -or $insideWorktree -ne 'true') {
        Add-ReadinessCheck -Id 'clean_worktree' -Status 'block' `
            -Summary 'The selected directory is not a Git worktree.' `
            -Remediation 'Run the readiness check from the Koto repository.'
    } else {
        $gitStatus = @(& git -C $RepoRoot status --porcelain --untracked-files=all)
        if ($LASTEXITCODE -ne 0) {
            Add-ReadinessCheck -Id 'clean_worktree' -Status 'block' `
                -Summary 'Git worktree status could not be read.' `
                -Remediation 'Resolve Git repository errors and rerun the check.'
        } else {
            $untrackedCount = @($gitStatus | Where-Object { $_.StartsWith('??') }).Count
            $trackedCount = $gitStatus.Count - $untrackedCount
            if ($gitStatus.Count -gt 0) {
                $changeAreas = [ordered]@{}
                foreach ($statusLine in $gitStatus) {
                    $path = if ($statusLine.Length -gt 3) { $statusLine.Substring(3) } else { '' }
                    if ($path.Contains(' -> ')) { $path = ($path -split ' -> ', 2)[1] }
                    $area = Get-ChangeArea -RelativePath $path
                    if (-not $changeAreas.Contains($area)) { $changeAreas[$area] = 0 }
                    $changeAreas[$area] += 1
                }
                Add-ReadinessCheck -Id 'clean_worktree' -Status 'block' `
                    -Summary "The release source snapshot has $($gitStatus.Count) pending paths." `
                    -Remediation 'Review, test, and commit the intended source snapshot; do not discard changes automatically.' `
                    -Details @{
                        pending_paths = $gitStatus.Count
                        tracked_changes = $trackedCount
                        untracked_paths = $untrackedCount
                        change_areas = [pscustomobject]$changeAreas
                    }
            } else {
                $revision = (& git -C $RepoRoot rev-parse HEAD).Trim()
                Add-ReadinessCheck -Id 'clean_worktree' -Status 'pass' `
                    -Summary 'The release source snapshot is clean and committed.' `
                    -Details @{ git_revision = $revision }
            }
        }
    }
}

$python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $python -PathType Leaf) {
    Add-ReadinessCheck -Id 'build_python' -Status 'pass' `
        -Summary 'The pinned Koto virtual-environment Python is available.' `
        -Details @{ path = $python }
} else {
    Add-ReadinessCheck -Id 'build_python' -Status 'block' `
        -Summary 'The Koto build virtual environment is missing.' `
        -Remediation 'Create .venv and install config/build-requirements.lock.'
}

$versionFile = Join-Path $RepoRoot 'VERSION'
$versionValidator = Join-Path $RepoRoot 'scripts\validate_release_version.py'
if ((Test-Path -LiteralPath $python -PathType Leaf) -and
    (Test-Path -LiteralPath $versionFile -PathType Leaf) -and
    (Test-Path -LiteralPath $versionValidator -PathType Leaf)) {
    $releaseVersion = (Get-Content -LiteralPath $versionFile -Raw).Trim()
    $versionValidationOutput = @(
        & $python $versionValidator --expected-version $releaseVersion 2>&1
    )
    if ($LASTEXITCODE -eq 0) {
        Add-ReadinessCheck -Id 'release_version' -Status 'pass' `
            -Summary "Release metadata consistently declares version $releaseVersion."
    } else {
        Add-ReadinessCheck -Id 'release_version' -Status 'block' `
            -Summary 'Release version metadata is inconsistent.' `
            -Remediation 'Synchronize VERSION, Python, frontend lockfiles, and CHANGELOG.' `
            -Details @{ validator_output = @($versionValidationOutput) }
    }
} else {
    Add-ReadinessCheck -Id 'release_version' -Status 'block' `
        -Summary 'Release version validation prerequisites are missing.' `
        -Remediation 'Restore VERSION, the validator, and the repository virtual environment.'
}

$requirementsVerifier = Join-Path $RepoRoot 'scripts\verify_build_requirements.py'
$requirementsLock = Join-Path $RepoRoot 'config\build-requirements.lock'
if ((Test-Path -LiteralPath $python -PathType Leaf) -and
    (Test-Path -LiteralPath $requirementsVerifier -PathType Leaf) -and
    (Test-Path -LiteralPath $requirementsLock -PathType Leaf)) {
    $requirementsOutput = @(& $python $requirementsVerifier $requirementsLock 2>&1)
    if ($LASTEXITCODE -eq 0) {
        Add-ReadinessCheck -Id 'build_tool_lock' -Status 'pass' `
            -Summary 'Windows build-tool versions match the pinned lockfile.'
    } else {
        Add-ReadinessCheck -Id 'build_tool_lock' -Status 'block' `
            -Summary 'Windows build-tool versions do not match the pinned lockfile.' `
            -Remediation 'Reinstall config/build-requirements.lock into .venv.' `
            -Details @{ verifier_output = @($requirementsOutput) }
    }
} else {
    Add-ReadinessCheck -Id 'build_tool_lock' -Status 'block' `
        -Summary 'Build-tool lock verification prerequisites are missing.' `
        -Remediation 'Restore the build requirements lock and repository virtual environment.'
}

$snapshotPlanner = Join-Path $RepoRoot 'scripts\write_source_snapshot_plan.py'
if ((Test-Path -LiteralPath $python -PathType Leaf) -and
    (Test-Path -LiteralPath $snapshotPlanner -PathType Leaf)) {
    $snapshotJson = Join-Path $RepoRoot 'logs\source_snapshot_plan.json'
    $snapshotMarkdown = Join-Path $RepoRoot 'logs\source_snapshot_plan.md'
    $snapshotOutput = @(
        & $python $snapshotPlanner `
            --source-root $RepoRoot `
            --json-output $snapshotJson `
            --markdown-output $snapshotMarkdown `
            --fail-on-unclassified `
            --fail-on-risk 2>&1
    )
    $snapshotReport = if (Test-Path -LiteralPath $snapshotJson -PathType Leaf) {
        Get-Content -LiteralPath $snapshotJson -Raw | ConvertFrom-Json
    } else { $null }
    if ($LASTEXITCODE -eq 0 -and $snapshotReport) {
        Add-ReadinessCheck -Id 'source_snapshot_policy' -Status 'pass' `
            -Summary "All $($snapshotReport.pending_count) pending paths are classified with no risk-flagged untracked files." `
            -Details @{
                pending_paths = $snapshotReport.pending_count
                untracked_paths = $snapshotReport.untracked_count
                plan = $snapshotMarkdown
            }
    } else {
        Add-ReadinessCheck -Id 'source_snapshot_policy' -Status 'block' `
            -Summary 'The source snapshot contains unclassified or risk-flagged untracked files.' `
            -Remediation 'Review logs/source_snapshot_plan.md and update only narrow source/runtime policies.' `
            -Details @{ planner_output = @($snapshotOutput) }
    }
} else {
    Add-ReadinessCheck -Id 'source_snapshot_policy' -Status 'block' `
        -Summary 'The source snapshot planner is unavailable.' `
        -Remediation 'Restore scripts/write_source_snapshot_plan.py and the repository virtual environment.'
}

$npm = Get-Command npm -ErrorAction SilentlyContinue
if ($npm) {
    Add-ReadinessCheck -Id 'node_toolchain' -Status 'pass' `
        -Summary 'npm is available for reproducible frontend builds.' `
        -Details @{ path = $npm.Source }
} else {
    Add-ReadinessCheck -Id 'node_toolchain' -Status 'block' `
        -Summary 'npm is missing.' `
        -Remediation 'Install the supported Node.js release and rerun the check.'
}

$inno = Resolve-OptionalTool -Resolver (Join-Path $RepoRoot 'scripts\resolve_inno_setup.ps1')
if ($inno) {
    Add-ReadinessCheck -Id 'inno_setup' -Status 'pass' `
        -Summary 'Inno Setup is available.' -Details @{ path = $inno }
} else {
    Add-ReadinessCheck -Id 'inno_setup' -Status 'block' `
        -Summary 'Inno Setup is missing.' `
        -Remediation 'Install Inno Setup 6 before building the Windows installer.'
}

$signTool = Resolve-OptionalTool -Resolver (Join-Path $RepoRoot 'scripts\resolve_signtool.ps1')
if ($signTool) {
    Add-ReadinessCheck -Id 'windows_signtool' -Status 'pass' `
        -Summary 'The x64 Windows SDK SignTool is available.' `
        -Details @{ path = $signTool }
} else {
    Add-ReadinessCheck -Id 'windows_signtool' -Status 'block' `
        -Summary 'The x64 Windows SDK SignTool is missing.' `
        -Remediation 'Install the Windows 10 or Windows 11 SDK.'
}

$normalizedThumbprint = (([string]$CodeSigningThumbprint) -replace '[^0-9A-Fa-f]', '').ToUpperInvariant()
if ($normalizedThumbprint -notmatch '^[0-9A-F]{40,128}$') {
    Add-ReadinessCheck -Id 'code_signing_certificate' -Status 'block' `
        -Summary 'No valid release code-signing certificate thumbprint is configured.' `
        -Remediation 'Import the public-CA code-signing certificate and set KOTO_CODE_SIGNING_THUMBPRINT.'
} else {
    $certificate = Get-Item -Path "Cert:\CurrentUser\My\$normalizedThumbprint" -ErrorAction SilentlyContinue
    $codeSigningEku = if ($certificate) {
        @($certificate.EnhancedKeyUsageList | Where-Object {
            $_.ObjectId.Value -eq '1.3.6.1.5.5.7.3.3'
        })
    } else { @() }
    $now = Get-Date
    if (-not $certificate) {
        Add-ReadinessCheck -Id 'code_signing_certificate' -Status 'block' `
            -Summary 'The configured code-signing certificate is not in Cert:\CurrentUser\My.' `
            -Remediation 'Import the matching certificate into the current user Personal store.'
    } elseif (-not $certificate.HasPrivateKey) {
        Add-ReadinessCheck -Id 'code_signing_certificate' -Status 'block' `
            -Summary 'The configured code-signing certificate has no accessible private key.' `
            -Remediation 'Import the PFX or connect the hardware signing key for this account.'
    } elseif ($certificate.NotBefore -gt $now -or $certificate.NotAfter -le $now) {
        Add-ReadinessCheck -Id 'code_signing_certificate' -Status 'block' `
            -Summary 'The configured code-signing certificate is outside its validity period.' `
            -Remediation 'Renew or replace the release code-signing certificate.'
    } elseif ($codeSigningEku.Count -eq 0) {
        Add-ReadinessCheck -Id 'code_signing_certificate' -Status 'block' `
            -Summary 'The configured certificate does not allow code signing.' `
            -Remediation 'Use a certificate with Code Signing EKU 1.3.6.1.5.5.7.3.3.'
    } else {
        Add-ReadinessCheck -Id 'code_signing_certificate' -Status 'pass' `
            -Summary 'The release code-signing certificate and private key are available.' `
            -Details @{
                thumbprint = $normalizedThumbprint
                expires_at = $certificate.NotAfter.ToUniversalTime().ToString('o')
            }
    }
}

$sandboxExe = Join-Path $env:SystemRoot 'System32\WindowsSandbox.exe'
if (Test-Path -LiteralPath $sandboxExe -PathType Leaf) {
    Add-ReadinessCheck -Id 'windows_sandbox' -Status 'pass' `
        -Summary 'Windows Sandbox is available for clean-image validation.'
} else {
    Add-ReadinessCheck -Id 'windows_sandbox' -Status 'advisory' `
        -Summary 'Windows Sandbox is not enabled on this machine.' `
        -Remediation 'Enable Windows Sandbox on Windows Pro/Enterprise, or rely on the clean windows-latest release job.'
}

if (-not $SkipArtifactInspection) {
    $versionPath = Join-Path $RepoRoot 'VERSION'
    $version = if (Test-Path -LiteralPath $versionPath -PathType Leaf) {
        (Get-Content -LiteralPath $versionPath -Raw).Trim()
    } else { '' }
    $artifactPaths = @(
        (Join-Path $RepoRoot "dist\Koto_v${version}_Setup.exe"),
        (Join-Path $RepoRoot 'dist\Koto_Portable\Koto.exe'),
        (Join-Path $RepoRoot 'dist\Koto_Portable\LocalModelInstaller.exe')
    )
    $existingArtifacts = @($artifactPaths | Where-Object {
        Test-Path -LiteralPath $_ -PathType Leaf
    })
    if ($existingArtifacts.Count -eq 0) {
        Add-ReadinessCheck -Id 'existing_artifacts' -Status 'advisory' `
            -Summary 'No existing Windows candidate was found; signatures will be checked after the build.'
    } else {
        $invalidArtifacts = [System.Collections.Generic.List[string]]::new()
        foreach ($artifact in $existingArtifacts) {
            $signature = Get-AuthenticodeSignature -LiteralPath $artifact
            if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid -or
                -not $signature.TimeStamperCertificate -or
                ($normalizedThumbprint -and $signature.SignerCertificate -and
                    $signature.SignerCertificate.Thumbprint.ToUpperInvariant() -ne $normalizedThumbprint)) {
                $invalidArtifacts.Add((Split-Path -Leaf $artifact))
            }
        }
        if ($invalidArtifacts.Count -gt 0) {
            Add-ReadinessCheck -Id 'existing_artifacts' -Status 'advisory' `
                -Summary "$($invalidArtifacts.Count) existing Windows artifacts are unsigned, stale, or signed by another certificate." `
                -Remediation 'Do not publish existing diagnostic artifacts; rebuild after all blocking checks pass.' `
                -Details @{ affected = @($invalidArtifacts) }
        } else {
            Add-ReadinessCheck -Id 'existing_artifacts' -Status 'pass' `
                -Summary 'Existing Windows artifacts have valid timestamped signatures.'
        }
    }
}

$blockingCount = @($checks | Where-Object { $_.status -eq 'block' }).Count
$advisoryCount = @($checks | Where-Object { $_.status -eq 'advisory' }).Count
$report = [pscustomobject][ordered]@{
    schema_version = 1
    generated_at = (Get-Date).ToUniversalTime().ToString('o')
    repo_root = $RepoRoot
    formal_ready = ($blockingCount -eq 0)
    blocking_count = $blockingCount
    advisory_count = $advisoryCount
    checks = @($checks)
}

foreach ($check in $checks) {
    $label = switch ($check.status) {
        'pass' { 'PASS' }
        'block' { 'BLOCK' }
        default { 'NOTE' }
    }
    $color = switch ($check.status) {
        'pass' { 'Green' }
        'block' { 'Red' }
        default { 'Yellow' }
    }
    Write-Host "[$label] $($check.id): $($check.summary)" -ForegroundColor $color
    if ($check.remediation) {
        Write-Host "        Next: $($check.remediation)" -ForegroundColor DarkGray
    }
}
Write-Host "`nFormalReady=$($report.formal_ready); Blocking=$blockingCount; Advisory=$advisoryCount"

if (-not [string]::IsNullOrWhiteSpace($JsonOutput)) {
    $outputPath = if ([System.IO.Path]::IsPathRooted($JsonOutput)) {
        [System.IO.Path]::GetFullPath($JsonOutput)
    } else {
        [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $JsonOutput))
    }
    $outputParent = Split-Path -Parent $outputPath
    New-Item -ItemType Directory -Path $outputParent -Force | Out-Null
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $outputPath -Encoding UTF8
    Write-Host "Readiness report: $outputPath"
}

if (-not [string]::IsNullOrWhiteSpace($MarkdownOutput)) {
    $markdownPath = if ([System.IO.Path]::IsPathRooted($MarkdownOutput)) {
        [System.IO.Path]::GetFullPath($MarkdownOutput)
    } else {
        [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $MarkdownOutput))
    }
    $markdownParent = Split-Path -Parent $markdownPath
    New-Item -ItemType Directory -Path $markdownParent -Force | Out-Null
    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.Add('# Koto Windows release readiness')
    $lines.Add('')
    $readyLabel = if ($report.formal_ready) { 'YES' } else { 'NO' }
    $lines.Add("- Formal ready: **$readyLabel**")
    $lines.Add("- Blocking issues: **$blockingCount**")
    $lines.Add("- Advisories: **$advisoryCount**")
    $lines.Add("- Generated: $($report.generated_at)")
    $lines.Add('')
    $lines.Add('| Status | Check | Result | Next action |')
    $lines.Add('|---|---|---|---|')
    foreach ($check in $checks) {
        $summary = ([string]$check.summary).Replace('|', '\|').Replace("`r", ' ').Replace("`n", ' ')
        $remediation = ([string]$check.remediation).Replace('|', '\|').Replace("`r", ' ').Replace("`n", ' ')
        $lines.Add("| $($check.status) | $($check.id) | $summary | $remediation |")
    }
    $worktreeCheck = $checks | Where-Object { $_.id -eq 'clean_worktree' } | Select-Object -First 1
    $changeAreasProperty = if ($worktreeCheck) {
        $worktreeCheck.details.PSObject.Properties['change_areas']
    } else { $null }
    if ($changeAreasProperty -and $changeAreasProperty.Value) {
        $lines.Add('')
        $lines.Add('## Pending-path areas')
        $lines.Add('')
        foreach ($property in $changeAreasProperty.Value.PSObject.Properties) {
            $lines.Add("- $($property.Name): $($property.Value)")
        }
    }
    [System.IO.File]::WriteAllLines($markdownPath, $lines, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Readiness summary: $markdownPath"
}

if ($RequireFormal -and $blockingCount -gt 0) { exit 1 }
exit 0
