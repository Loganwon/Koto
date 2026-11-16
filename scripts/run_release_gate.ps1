#Requires -Version 5.1
<#
.SYNOPSIS
    Run the complete local Koto Windows release gate from a clean commit.
.DESCRIPTION
    Executes source regressions, the AI release lane, the canonical Windows
    build, exact candidate verification, installer E2E, and portable E2E.
    Any failure stops the gate and no release-ready conclusion is printed.
#>

param(
    [string]$Version = "",
    [int]$HealthTimeoutSec = 120
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$BuildRelease = Join-Path $RepoRoot "Build_Release.ps1"
$CandidateVerifier = Join-Path $RepoRoot "scripts\verify_release_candidate.py"
$VersionValidator = Join-Path $RepoRoot "scripts\validate_release_version.py"
$InstallerE2E = Join-Path $RepoRoot "tests\installer\test_installer_e2e.ps1"
$PortableE2E = Join-Path $RepoRoot "tests\installer\test_portable_e2e.ps1"
$SourceStartupMatrix = Join-Path $RepoRoot "tests\windows\test_source_startup_matrix.ps1"
$StartupEventSummary = Join-Path $RepoRoot "scripts\summarize_startup_events.py"
$SignatureVerifier = Join-Path $RepoRoot "scripts\verify_windows_signatures.ps1"
$ReadinessChecker = Join-Path $RepoRoot "scripts\check_release_readiness.ps1"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    exit 1
}

function Invoke-Checked([string]$Label, [scriptblock]$Action) {
    Write-Host "`n[release-gate] $Label" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) {
        Fail "$Label failed with exit code $LASTEXITCODE"
    }
}

function Get-AvailableLoopbackPort {
    $listener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback,
        0
    )
    try {
        $listener.Start()
        return ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    } finally {
        $listener.Stop()
    }
}

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    Fail "Virtualenv Python not found: $Python"
}
if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = (Get-Content (Join-Path $RepoRoot "VERSION") -Raw).Trim()
}
if ($Version -notmatch '^[0-9A-Za-z][0-9A-Za-z._+\-]*$') {
    Fail "Unsafe release version: $Version"
}
if ($HealthTimeoutSec -lt 10) {
    Fail "HealthTimeoutSec must be at least 10 seconds"
}
$signerThumbprint = (([string]$env:KOTO_CODE_SIGNING_THUMBPRINT) -replace '[^0-9A-Fa-f]', '').ToUpperInvariant()
Write-Host "`n[release-gate] Aggregated release-readiness preflight" -ForegroundColor Cyan
& $ReadinessChecker `
    -RepoRoot $RepoRoot `
    -CodeSigningThumbprint $signerThumbprint `
    -JsonOutput (Join-Path $RepoRoot "logs\release_readiness.json") `
    -MarkdownOutput (Join-Path $RepoRoot "logs\release_readiness.md") `
    -RequireFormal `
    -SkipArtifactInspection
if ($LASTEXITCODE -ne 0) {
    Fail "Release-readiness preflight found blocking issues; review logs\release_readiness.md"
}
$expectedRevision = (& git -C $RepoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($expectedRevision)) {
    Fail "Could not resolve the exact Git revision for this release gate"
}

Push-Location $RepoRoot
try {
    Invoke-Checked "Release version metadata contract" {
        & $Python $VersionValidator --expected-version $Version
    }
    Invoke-Checked "Frontend typecheck" {
        & npm --prefix web run typecheck
    }
    Invoke-Checked "Frontend unit regressions" {
        & npm --prefix web test
    }
    Invoke-Checked "Frontend production build" {
        & npm --prefix web run build
    }
    Invoke-Checked "Release source regressions" {
        & $Python -m pytest `
            tests/unit/test_release_packaging_guards.py `
            tests/unit/test_release_startup_runtime.py `
            tests/unit/test_release_version_contract.py `
            tests/unit/test_release_manifest.py `
            tests/unit/test_verify_release_candidate.py `
            tests/unit/test_model_install_compatibility.py `
            tests/unit/test_architecture_guardrails.py `
            tests/unit/test_audit_code_baseline.py `
            tests/unit/test_frontend_quality_config.py `
            tests/unit/test_runtime_capabilities.py `
            tests/unit/test_startup_reliability_contract.py `
            tests/unit/test_source_snapshot_plan.py `
            tests/unit/test_health_endpoint.py `
            -q --tb=short
    }
    Invoke-Checked "AI assistant release lane" {
        & $Python scripts/run_ai_assistant_flow_tests.py release -q --tb=short
    }
    Invoke-Checked "Source desktop startup lifecycle matrix" {
        & $SourceStartupMatrix -RepoRoot $RepoRoot -TimeoutSec $HealthTimeoutSec
    }
    Invoke-Checked "Structured startup event validation" {
        & $Python $StartupEventSummary `
            --budget (Join-Path $RepoRoot "config\startup_performance_budget.json") `
            --report (Join-Path $RepoRoot "logs\startup_performance_report.json") `
            --markdown (Join-Path $RepoRoot "logs\startup_performance_summary.md") `
            --history (Join-Path $RepoRoot "logs\startup_performance_history.jsonl") `
            --revision $expectedRevision `
            --run-id "local-$expectedRevision" `
            (Join-Path $RepoRoot "logs\startup_matrix\normal.jsonl") `
            (Join-Path $RepoRoot "logs\startup_matrix\slow.jsonl") `
            (Join-Path $RepoRoot "logs\startup_matrix\port_conflict.jsonl")
    }
    Invoke-Checked "Canonical Windows release build" {
        & $BuildRelease -Version $Version
    }
    Invoke-Checked "Windows Authenticode signature gate" {
        & $SignatureVerifier `
            -FilePath @(
                (Join-Path $RepoRoot "dist\Koto_Portable\Koto.exe"),
                (Join-Path $RepoRoot "dist\Koto_Portable\LocalModelInstaller.exe"),
                (Join-Path $RepoRoot "dist\Koto_v${Version}_Setup.exe")
            ) `
            -ExpectedThumbprint $signerThumbprint `
            -RequireTimestamp
    }
    Invoke-Checked "Exact release candidate verification" {
        & $Python $CandidateVerifier --version $Version --dist-dir (Join-Path $RepoRoot "dist") --expected-git-revision $expectedRevision --source-root $RepoRoot
    }

    $setupPath = Join-Path $RepoRoot "dist\Koto_v${Version}_Setup.exe"
    $zipPath = Join-Path $RepoRoot "dist\Koto_v${Version}_Windows.zip"
    $packagedStartupDir = Join-Path $RepoRoot "logs\packaged_startup_matrix"
    New-Item -ItemType Directory -Path $packagedStartupDir -Force | Out-Null
    Remove-Item -LiteralPath (Join-Path $packagedStartupDir "installer.jsonl") -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $packagedStartupDir "portable.jsonl") -Force -ErrorAction SilentlyContinue
    $installerPort = Get-AvailableLoopbackPort
    Invoke-Checked "Installer E2E" {
        & $InstallerE2E `
            -SetupExe $setupPath `
            -TestInstallDir (Join-Path $env:LOCALAPPDATA "KotoReleaseGate") `
            -Port $installerPort `
            -HealthTimeoutSec $HealthTimeoutSec `
            -StartupEvidenceDir $packagedStartupDir `
            -RequireAuthenticodeSignatures `
            -ExpectedSignerThumbprint $signerThumbprint
    }
    $portablePort = Get-AvailableLoopbackPort
    Invoke-Checked "Portable E2E" {
        & $PortableE2E `
            -ZipFile $zipPath `
            -Port $portablePort `
            -HealthTimeoutSec $HealthTimeoutSec `
            -StartupEvidenceDir $packagedStartupDir `
            -RequireAuthenticodeSignatures `
            -ExpectedSignerThumbprint $signerThumbprint
    }
    Invoke-Checked "Packaged desktop startup performance budget" {
        & $Python $StartupEventSummary `
            --budget (Join-Path $RepoRoot "config\packaged_startup_performance_budget.json") `
            --report (Join-Path $RepoRoot "logs\packaged_startup_performance_report.json") `
            --markdown (Join-Path $RepoRoot "logs\packaged_startup_performance_summary.md") `
            --history (Join-Path $RepoRoot "logs\packaged_startup_performance_history.jsonl") `
            --revision $expectedRevision `
            --run-id "local-packaged-$expectedRevision" `
            (Join-Path $packagedStartupDir "installer.jsonl") `
            (Join-Path $packagedStartupDir "portable.jsonl")
    }
    Invoke-Checked "Post-E2E candidate re-verification" {
        & $Python $CandidateVerifier --version $Version --dist-dir (Join-Path $RepoRoot "dist") --expected-git-revision $expectedRevision --source-root $RepoRoot
    }

    Write-Host "`n[PASS] Koto v$Version passed the complete local release gate." -ForegroundColor Green
    Write-Host "       Installer, portable ZIP, manifest, and SHA256SUMS are exact and release-eligible." -ForegroundColor Green
} finally {
    Pop-Location
}
