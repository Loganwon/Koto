<#
.SYNOPSIS
    End-to-end test for the Koto portable ZIP bundle (Koto_v*_Windows.zip).

    Steps:
      1. Extract ZIP to temp dir
      2. Verify critical files + file size + Python DLL
      3. Seed config (bypass first-run wizard) + launch the real desktop path
      4. Poll /api/health + verify that the WebView window was shown
      5. Stop process
      6. Remove temp dir

    Exit 0 on success, 1 on any failure.

.PARAMETER ZipFile
    Path to Koto_v*_Windows.zip. Defaults to searching dist\.

.PARAMETER Port
    Port for the test server. Default 5098.

.PARAMETER HealthTimeoutSec
    Seconds to wait for /api/health. Default 45.

.EXAMPLE
    .\test_portable_e2e.ps1 -ZipFile "C:\downloads\Koto_v1.0.3_Windows.zip"
#>
param(
    [string]$ZipFile          = "",
    [int]$Port                = 5098,
    [int]$HealthTimeoutSec    = 45,
    [bool]$RequireHealth      = $true,
    [bool]$RequireDesktopWindow = $true,
    [switch]$RequireCodeSigning
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Resolve-Path (Join-Path $ScriptDir "..\..")
. (Join-Path $ScriptDir "release_e2e_helpers.ps1")
$ExtractDir = Join-Path $env:TEMP "KotoPortableE2E"

# ── Locate ZIP ───────────────────────────────────────────────────────────
if (-not $ZipFile) {
    $found = Get-Item (Join-Path $RepoRoot "dist\Koto_v*_Windows.zip") -ErrorAction SilentlyContinue |
             Select-Object -First 1
    if ($found) { $ZipFile = $found.FullName }
}
if (-not $ZipFile -or -not (Test-Path $ZipFile)) {
    Write-Error "ERROR: ZIP not found. Pass -ZipFile <path>."
    exit 1
}
Write-Host "[E2E-Portable] ZIP: $ZipFile"
Write-Host "[E2E-Portable] Extract dir: $ExtractDir"
Write-Host "[E2E-Portable] Port: $Port"

$failures = [System.Collections.Generic.List[string]]::new()
function Fail([string]$msg) { $script:failures.Add($msg); Write-Host "::error:: FAIL: $msg" }
function Pass([string]$msg) { Write-Host "  PASS: $msg" }
$expectedSignerThumbprint = ""
function Test-RequiredAuthenticodeSignature([string]$Path, [string]$Label) {
    if (-not $RequireCodeSigning) { return }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Fail "Signed executable missing: $Path"
        return
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid -or
        -not $signature.SignerCertificate -or
        -not $signature.TimeStamperCertificate) {
        Fail "$Label must have a valid Authenticode signature and trusted timestamp (status=$($signature.Status))"
        return
    }
    if ([string]::IsNullOrWhiteSpace($script:expectedSignerThumbprint)) {
        $script:expectedSignerThumbprint = $signature.SignerCertificate.Thumbprint
    } elseif ($signature.SignerCertificate.Thumbprint -ne $script:expectedSignerThumbprint) {
        Fail "$Label signer does not match the Koto.exe signer"
        return
    }
    Pass "$Label Authenticode signature and timestamp are valid"
}
function Show-KotoStartupDiagnostics([string]$InstallDir, [int]$HealthPort) {
    Write-Host "::group::Koto startup diagnostics"
    Write-Host "Process PID: $($kotoProc.Id); exited: $($kotoProc.HasExited); expected port: $HealthPort"
    try {
        Get-NetTCPConnection -State Listen -LocalPort $HealthPort -ErrorAction Stop |
            Format-Table -AutoSize | Out-String | Write-Host
    } catch {
        Write-Host "No listener found on port $HealthPort"
    }
    foreach ($logName in @("startup.log", "startup_prerequisites.log", "runtime.log")) {
        $logPath = Join-Path $InstallDir "logs\$logName"
        if (Test-Path $logPath) {
            Write-Host "--- $logPath (last 200 lines) ---"
            Get-Content -LiteralPath $logPath -Tail 200 -ErrorAction Continue
        }
    }
    Write-Host "::endgroup::"
}
function Test-WorkspaceAssetBundle([string]$StaticRoot) {
    $legacyIndexHtml = Join-Path $StaticRoot "univer-dist\index.html"
    if (Test-Path $legacyIndexHtml) {
        Fail "Legacy workspace asset index should not be packaged: $legacyIndexHtml"
    }
    else {
        Pass "Legacy workspace asset index removed"
    }

    $assetPaths = @(
        (Join-Path $StaticRoot "univer-dist\assets\sheets-main.js"),
        (Join-Path $StaticRoot "univer-dist\assets\sheets-main.css")
    )
    foreach ($assetPath in $assetPaths) {
        if (Test-Path $assetPath) { Pass "Workspace asset exists: $(Split-Path -Leaf $assetPath)" }
        else                      { Fail "Missing workspace asset: $assetPath" }
    }
}

# ── Cleanup leftovers ────────────────────────────────────────────────────
if (Test-Path $ExtractDir) {
    Remove-Item $ExtractDir -Recurse -Force -ErrorAction SilentlyContinue
}

# ══════════════════════════════════════════════════════════════════════════
# STEP 1 — Extract ZIP
# ══════════════════════════════════════════════════════════════════════════
Write-Host "`n[Step 1] Extracting ZIP..."
Expand-Archive -Path $ZipFile -DestinationPath $ExtractDir -Force
Pass "ZIP extracted to $ExtractDir"

# ══════════════════════════════════════════════════════════════════════════
# STEP 2 — Verify critical files
# ══════════════════════════════════════════════════════════════════════════
Write-Host "`n[Step 2] Verifying extracted files..."
$exePath = Join-Path $ExtractDir "Koto.exe"
$internalDir = Join-Path $ExtractDir "_internal"
$staticRoot = Join-Path $internalDir "web\static"
$configRoot = Join-Path $internalDir "config"

$requiredPaths = @(
    $exePath,
    $internalDir,
    (Join-Path $internalDir "psutil"),
    (Join-Path $internalDir "app"),
    (Join-Path $internalDir "web"),
    (Join-Path $configRoot ".builtin_key"),
    (Join-Path $configRoot "deepseek_config.env.example"),
    (Join-Path $configRoot "macro_suggestions.json"),
    (Join-Path $configRoot "personality_matrix.json"),
    (Join-Path $configRoot "skill_affinity.json"),
    (Join-Path $configRoot "context"),
    (Join-Path $configRoot "divination_data"),
    (Join-Path $configRoot "skills"),
    (Join-Path $configRoot "skill_packs"),
    (Join-Path $configRoot "tools"),
    (Join-Path $configRoot "workflows"),
    (Join-Path $staticRoot "js\build\workspace-bundle.js"),
    (Join-Path $staticRoot "jszip.min.js"),
    (Join-Path $staticRoot "univer-dist\assets\sheets-main.js"),
    (Join-Path $staticRoot "univer-dist\assets\sheets-main.css"),
    (Join-Path $ExtractDir "Start_Koto.bat"),
    (Join-Path $ExtractDir "Install_WebView2_Runtime.bat"),
    (Join-Path $ExtractDir "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"),
    (Join-Path $ExtractDir "LocalModelInstaller.exe"),
    (Join-Path $internalDir "python311.dll"),
    (Join-Path $internalDir "VCRUNTIME140.dll"),
    (Join-Path $internalDir "webview\lib\runtimes\win-x64\native\WebView2Loader.dll")
)
foreach ($path in $requiredPaths) {
    if (Test-Path $path) { Pass "Exists: $(Split-Path -Leaf $path)" }
    else                 { Fail "Missing: $path" }
}
Test-RequiredAuthenticodeSignature -Path $exePath -Label "portable Koto.exe"
Test-RequiredAuthenticodeSignature `
    -Path (Join-Path $ExtractDir "LocalModelInstaller.exe") `
    -Label "portable LocalModelInstaller.exe"
if ($RequireCodeSigning -and $failures.Count -gt 0) {
    Remove-Item -LiteralPath $ExtractDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "❌ Refusing to launch portable executables that failed the signing gate." -ForegroundColor Red
    exit 1
}

$unexpectedRuntimePaths = @(
    (Join-Path $ExtractDir ".webview2_profile"),
    (Join-Path $ExtractDir "config"),
    (Join-Path $ExtractDir "chats"),
    (Join-Path $ExtractDir "logs"),
    (Join-Path $ExtractDir "workspace")
)
foreach ($path in $unexpectedRuntimePaths) {
    if (Test-Path $path) { Fail "Unexpected runtime state shipped: $path" }
    else                 { Pass "Runtime state excluded: $(Split-Path -Leaf $path)" }
}

# File size validation — catch empty or corrupt builds
$exeSize = (Get-Item $exePath).Length / 1MB
if ($exeSize -lt 40) { Fail "Koto.exe is only $([math]::Round($exeSize,1))MB (expected >= 40MB)" }
else                  { Pass "Koto.exe size is $([math]::Round($exeSize,1))MB" }

Test-WorkspaceAssetBundle -StaticRoot $staticRoot

# Critical DLL check — Python runtime must be present
$pythonDll = Join-Path $internalDir "python311.dll"
if (Test-Path $pythonDll) { Pass "python311.dll exists in _internal" }
else                      { Fail "python311.dll missing from _internal" }

# ══════════════════════════════════════════════════════════════════════════
# STEP 3 — Seed config + launch
# ══════════════════════════════════════════════════════════════════════════
Write-Host "`n[Step 3] Seeding config and launching..."
& (Join-Path $ScriptDir "seed_config.ps1") -InstallDir $ExtractDir

$env:KOTO_PORT = $Port
Remove-Item Env:KOTO_SERVER_ONLY -ErrorAction SilentlyContinue
Write-Host "  Desktop mode (WebView2 path enabled)"
$kotoProc = Start-KotoWithoutDeveloperEnvironment `
    -ExePath $exePath `
    -WorkingDirectory $ExtractDir
Write-Host "  Developer runtimes removed from child PATH/environment"

Write-Host "  Koto.exe PID: $($kotoProc.Id)"

# ══════════════════════════════════════════════════════════════════════════
# STEP 4 — Poll /api/health
# ══════════════════════════════════════════════════════════════════════════
Write-Host "`n[Step 4] Waiting for http://127.0.0.1:$Port/api/health (up to ${HealthTimeoutSec}s)..."
$healthUrl = "http://127.0.0.1:$Port/api/health"
$deadline  = (Get-Date).AddSeconds($HealthTimeoutSec)
$healthy   = $false

while ((Get-Date) -lt $deadline) {
    if ($kotoProc.HasExited) {
        Fail "Koto.exe exited unexpectedly (code $($kotoProc.ExitCode))"
        break
    }
    try {
        $resp = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3 -ErrorAction Stop
        if (Test-KotoHealthResponse -Response $resp) {
            $healthy = $true; Pass "/api/health returned success"; break
        }
    } catch {}
    Start-Sleep -Milliseconds 1000
}
if (-not $healthy) {
    Show-KotoStartupDiagnostics -InstallDir $ExtractDir -HealthPort $Port
    if ($RequireHealth) {
        Fail "Health endpoint did not respond within ${HealthTimeoutSec}s"
    } else {
        Write-Host "::warning::Health endpoint did not respond within ${HealthTimeoutSec}s (best-effort in CI — pywebview may not init headless)"
    }
}

$desktopReady = $false
$desktopDeadline = (Get-Date).AddSeconds($HealthTimeoutSec)
$startupLog = Join-Path $ExtractDir "logs\startup.log"
while ((Get-Date) -lt $desktopDeadline -and -not $kotoProc.HasExited) {
    if (Test-Path $startupLog) {
        $startupText = Get-Content -LiteralPath $startupLog -Raw -ErrorAction SilentlyContinue
        if ($startupText -match "窗口已显示，应用正常运行中") {
            $desktopReady = $true
            Pass "WebView2 desktop window reached the shown callback"
            break
        }
    }
    Start-Sleep -Milliseconds 500
}
if (-not $desktopReady) {
    Show-KotoStartupDiagnostics -InstallDir $ExtractDir -HealthPort $Port
    if ($RequireDesktopWindow) { Fail "Desktop window was not shown within ${HealthTimeoutSec}s" }
    else { Write-Host "::warning::Desktop window callback was not observed" }
}

# /api/ping endpoint check
if ($healthy) {
    try {
        $assetResp = Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/workspace/asset_health" -TimeoutSec 5
        if ($assetResp.ok -eq $true) {
            Pass "/api/v1/workspace/asset_health returned ok"
        } else {
            Fail "/api/v1/workspace/asset_health reported missing assets: $($assetResp.missing -join ', ')"
        }
    } catch {
        Fail "/api/v1/workspace/asset_health request failed: $($_.Exception.Message)"
    }

    try {
        Invoke-RestMethod "http://127.0.0.1:$Port/api/ping" -TimeoutSec 5 | Out-Null
        Pass "/api/ping responded"
    } catch {
        Write-Host "  WARN: /api/ping did not respond"
    }
}

# ══════════════════════════════════════════════════════════════════════════
# STEP 5 — Stop process
# ══════════════════════════════════════════════════════════════════════════
Write-Host "`n[Step 5] Stopping Koto.exe..."
if (-not $kotoProc.HasExited) {
    Stop-Process -Id $kotoProc.Id -Force -ErrorAction SilentlyContinue
    $kotoProc.WaitForExit(5000) | Out-Null
    Pass "Process stopped"
}

# ══════════════════════════════════════════════════════════════════════════
# STEP 6 — Cleanup
# ══════════════════════════════════════════════════════════════════════════
Write-Host "`n[Step 6] Removing temp dir..."
Start-Sleep -Seconds 1
Remove-Item $ExtractDir -Recurse -Force -ErrorAction SilentlyContinue
if (-not (Test-Path $ExtractDir)) { Pass "Temp dir removed" }
else                              { Fail "Temp dir still present after cleanup" }

# ══════════════════════════════════════════════════════════════════════════
# RESULT
# ══════════════════════════════════════════════════════════════════════════
Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "✅ Portable E2E: ALL CHECKS PASSED" -ForegroundColor Green
    exit 0
} else {
    Write-Host "❌ Portable E2E: $($failures.Count) CHECK(S) FAILED:" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "   - $_" -ForegroundColor Red }
    exit 1
}
