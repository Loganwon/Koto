<#
.SYNOPSIS
    End-to-end test for the Koto Windows installer (Koto_v*_Setup.exe).

    Steps:
      1. Silent install to $TestInstallDir
      2. Verify critical files + file size + Start Menu shortcut
      3. Verify Windows registry key written by Inno Setup
      4. Seed config (bypass first-run wizard) + launch the real desktop path
      5. Poll /api/health + verify that the WebView window was shown
      6. Stop Koto process
      7. Perform an in-place upgrade over stale managed runtime files
      8. Verify stale runtime removal + user data preservation
      9. Silent uninstall
     10. Verify cleanup (files + registry key removed)

    Exit 0 on success, 1 on any failure.

.PARAMETER SetupExe
    Path to Koto_v*_Setup.exe.  Defaults to searching dist\ then the script dir.

.PARAMETER TestInstallDir
    Where to install for testing.  Defaults to $env:LOCALAPPDATA\KotoE2ETest.

.PARAMETER Port
    Port for the test server.  Default 5099.

.PARAMETER HealthTimeoutSec
    Seconds to wait for /api/health before failing.  Default 45.

.EXAMPLE
    .\test_installer_e2e.ps1 -SetupExe "C:\downloads\Koto_v1.0.3_Setup.exe"
#>
param(
    [string]$SetupExe       = "",
    [string]$TestInstallDir = "$env:LOCALAPPDATA\KotoE2ETest",
    [int]$Port              = 5099,
    [int]$HealthTimeoutSec  = 45,
    [bool]$RequireHealth    = $true,
    [bool]$RequireDesktopWindow = $true,
    [string]$EvidenceDir = "",
    [int]$DesktopHoldSec = 0
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Resolve-Path (Join-Path $ScriptDir "..\..")
. (Join-Path $ScriptDir "release_e2e_helpers.ps1")
$regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{A3F8E291-7C44-4B2A-9D6E-8C5F1A347B90}_is1"

# ── Locate installer ────────────────────────────────────────────────────
if (-not $SetupExe) {
    $candidates = @(
        (Join-Path $RepoRoot "dist\Koto_v*_Setup.exe"),
        (Join-Path $ScriptDir "Koto_v*_Setup.exe")
    )
    foreach ($c in $candidates) {
        $found = Get-Item $c -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { $SetupExe = $found.FullName; break }
    }
}
if (-not $SetupExe -or -not (Test-Path $SetupExe)) {
    Write-Error "ERROR: Setup EXE not found. Pass -SetupExe <path>."
    exit 1
}
Write-Host "[E2E] Installer: $SetupExe"
Write-Host "[E2E] Install dir: $TestInstallDir"
Write-Host "[E2E] Port: $Port"

# The production AppId is intentionally stable. Refuse to overwrite another
# real Koto registration when this test runs outside a disposable machine.
$existingRegistration = Get-ItemProperty -Path $regPath -ErrorAction SilentlyContinue
if ($existingRegistration) {
    $existingInstallDir = [string]$existingRegistration.InstallLocation
    $expectedInstallDir = [System.IO.Path]::GetFullPath($TestInstallDir).TrimEnd('\')
    if ([string]::IsNullOrWhiteSpace($existingInstallDir) -or
        [System.IO.Path]::GetFullPath($existingInstallDir).TrimEnd('\') -ne $expectedInstallDir) {
        Write-Error "Refusing to replace an existing Koto registration at: $existingInstallDir"
        exit 1
    }
}

# ── Helper ──────────────────────────────────────────────────────────────
$failures = [System.Collections.Generic.List[string]]::new()
function Fail([string]$msg) { $script:failures.Add($msg); Write-Host "::error:: FAIL: $msg" }
function Pass([string]$msg) { Write-Host "  PASS: $msg" }
function Save-KotoWindowEvidence([string]$OutputDirectory, [System.Diagnostics.Process]$Process) {
    if ([string]::IsNullOrWhiteSpace($OutputDirectory)) { return }
    try {
        Add-Type -AssemblyName System.Drawing
        if (-not ("KotoWindowCaptureNative" -as [type])) {
            Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class KotoWindowCaptureNative {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int command);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr insertAfter, int x, int y, int width, int height, uint flags);

    public static IntPtr FindVisibleWindow(uint processId) {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr hWnd, IntPtr _) {
            uint owner;
            GetWindowThreadProcessId(hWnd, out owner);
            if (owner == processId && IsWindowVisible(hWnd)) {
                found = hWnd;
                return false;
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }
}
"@
        }
        New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
        $Process.Refresh()
        $handle = $Process.MainWindowHandle
        if ($handle -eq [IntPtr]::Zero) {
            $handle = [KotoWindowCaptureNative]::FindVisibleWindow([uint32]$Process.Id)
        }
        if ($handle -eq [IntPtr]::Zero) { throw "No visible window belongs to Koto PID $($Process.Id)" }
        $rect = New-Object KotoWindowCaptureNative+RECT
        if (-not [KotoWindowCaptureNative]::GetWindowRect($handle, [ref]$rect)) {
            throw "GetWindowRect failed for Koto PID $($Process.Id)"
        }
        $width = $rect.Right - $rect.Left
        $height = $rect.Bottom - $rect.Top
        if ($width -le 0 -or $height -le 0) { throw "Koto window has invalid bounds ${width}x${height}" }
        $bitmap = New-Object System.Drawing.Bitmap $width, $height
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        try {
            # WebView2's GPU surface commonly renders blank through PrintWindow.
            # Briefly raise the test window and capture its exact screen bounds.
            [KotoWindowCaptureNative]::ShowWindow($handle, 9) | Out-Null
            [KotoWindowCaptureNative]::SetWindowPos($handle, [IntPtr](-1), 0, 0, 0, 0, 0x43) | Out-Null
            [KotoWindowCaptureNative]::SetForegroundWindow($handle) | Out-Null
            Start-Sleep -Milliseconds 1500
            if ([KotoWindowCaptureNative]::GetForegroundWindow() -ne $handle) {
                throw "Koto could not become the foreground window; screenshot would capture another application"
            }
            $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)
            [KotoWindowCaptureNative]::SetWindowPos($handle, [IntPtr](-2), 0, 0, 0, 0, 0x43) | Out-Null
            $path = Join-Path $OutputDirectory "koto-installed-desktop.png"
            $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
            Pass "Koto window evidence saved: $path"
        }
        finally {
            $graphics.Dispose()
            $bitmap.Dispose()
        }
    }
    catch {
        Fail "Could not capture desktop evidence: $($_.Exception.Message)"
    }
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

function Test-RemovedFeatureAssets([string]$WebRoot) {
    $removedFeatureMarkers = @(
        "学习包",
        "有声概览",
        "audio_overview",
        "notebook_guide",
        "openNotebookGuide",
        "openAudioOverview"
    )
    $hits = @(Get-ChildItem -LiteralPath $WebRoot -File -Recurse |
        Select-String -Pattern $removedFeatureMarkers -SimpleMatch -List)
    if ($hits.Count -gt 0) {
        $firstHit = $hits[0]
        Fail "Removed feature marker still installed: $($firstHit.Path):$($firstHit.LineNumber)"
    }
    else {
        Pass "Removed learning/audio features are absent from installed Web payload"
    }
}

# ── Cleanup any leftover from previous run ───────────────────────────────
if (Test-Path $TestInstallDir) {
    Write-Host "[E2E] Removing leftover install dir..."
    Remove-Item $TestInstallDir -Recurse -Force -ErrorAction SilentlyContinue
}

# ══════════════════════════════════════════════════════════════════════════
# STEP 1 — Silent install
# ══════════════════════════════════════════════════════════════════════════
Write-Host "`n[Step 1] Silent install..."
$p = Start-Process -FilePath $SetupExe `
    -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/DIR=`"$TestInstallDir`"" `
    -Wait -PassThru
if ($p.ExitCode -ne 0) { Fail "Installer exited with code $($p.ExitCode)"; exit 1 }
Pass "Installer exited 0"

# ══════════════════════════════════════════════════════════════════════════
# STEP 2 — Verify critical files
# ══════════════════════════════════════════════════════════════════════════
Write-Host "`n[Step 2] Verifying installed files..."
$exePath = Join-Path $TestInstallDir "Koto.exe"
$internalDir = Join-Path $TestInstallDir "_internal"
$staticRoot = Join-Path $internalDir "web\static"
$configRoot = Join-Path $internalDir "config"

$requiredPaths = @(
    $exePath,
    $internalDir,
    (Join-Path $internalDir "psutil"),
    (Join-Path $internalDir "app"),
    (Join-Path $internalDir "web"),
    (Join-Path $internalDir "config"),
    (Join-Path $staticRoot "js\build\workspace-bundle.js"),
    (Join-Path $staticRoot "jszip.min.js"),
    (Join-Path $staticRoot "univer-dist\assets\sheets-main.js"),
    (Join-Path $staticRoot "univer-dist\assets\sheets-main.css"),
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
    (Join-Path $TestInstallDir "Start_Koto.bat"),
    (Join-Path $TestInstallDir "Install_WebView2_Runtime.bat"),
    (Join-Path $TestInstallDir "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"),
    (Join-Path $internalDir "python311.dll"),
    (Join-Path $internalDir "VCRUNTIME140.dll"),
    (Join-Path $internalDir "webview\lib\runtimes\win-x64\native\WebView2Loader.dll"),
    (Join-Path $TestInstallDir "LocalModelInstaller.exe"),
    (Join-Path $TestInstallDir "unins000.exe")
)
foreach ($path in $requiredPaths) {
    if (Test-Path $path) { Pass "Exists: $(Split-Path -Leaf $path)" }
    else                 { Fail "Missing: $path" }
}

$unexpectedRuntimePaths = @(
    (Join-Path $TestInstallDir ".webview2_profile"),
    (Join-Path $TestInstallDir "config"),
    (Join-Path $TestInstallDir "chats"),
    (Join-Path $TestInstallDir "logs"),
    (Join-Path $TestInstallDir "workspace")
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
Test-RemovedFeatureAssets -WebRoot (Join-Path $internalDir "web")

# Start Menu shortcut check
$startMenu = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Koto"
if (Test-Path "$startMenu\Koto.lnk") { Pass "Start Menu shortcut exists" }
else { Fail "Start Menu shortcut missing: $startMenu\Koto.lnk" }

# ══════════════════════════════════════════════════════════════════════════
# STEP 3 — Verify registry key (Inno Setup writes under HKCU)
# ══════════════════════════════════════════════════════════════════════════
Write-Host "`n[Step 3] Checking registry..."
if (Test-Path $regPath) { Pass "Uninstall registry key exists" }
else                     { Fail "Uninstall registry key missing at $regPath" }

# ══════════════════════════════════════════════════════════════════════════
# STEP 4 — Seed config + launch Koto.exe
# ══════════════════════════════════════════════════════════════════════════
Write-Host "`n[Step 4] Seeding config and launching Koto.exe..."
& (Join-Path $ScriptDir "seed_config.ps1") -InstallDir $TestInstallDir

$env:KOTO_PORT = $Port
Remove-Item Env:KOTO_SERVER_ONLY -ErrorAction SilentlyContinue
Write-Host "  Desktop mode (WebView2 path enabled)"
$kotoProc = Start-KotoWithoutDeveloperEnvironment `
    -ExePath $exePath `
    -WorkingDirectory $TestInstallDir
Write-Host "  Developer runtimes removed from child PATH/environment"

Write-Host "  Koto.exe PID: $($kotoProc.Id)"

# ══════════════════════════════════════════════════════════════════════════
# STEP 5 — Poll /api/health
# ══════════════════════════════════════════════════════════════════════════
Write-Host "`n[Step 5] Waiting for http://127.0.0.1:$Port/api/health (up to ${HealthTimeoutSec}s)..."
$healthUrl = "http://127.0.0.1:$Port/api/health"
$deadline  = (Get-Date).AddSeconds($HealthTimeoutSec)
$healthy   = $false

while ((Get-Date) -lt $deadline) {
    if ($kotoProc.HasExited) {
        Fail "Koto.exe exited unexpectedly (code $($kotoProc.ExitCode)) before health check"
        break
    }
    try {
        $resp = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3 -ErrorAction Stop
        if ($resp.success -eq $true -or $resp.status -eq "ok" -or $resp.status -eq "healthy") {
            $healthy = $true
            Pass "/api/health returned success"
            break
        }
    } catch {
        # Not up yet — keep polling
    }
    Start-Sleep -Milliseconds 1000
}

if (-not $healthy -and -not $kotoProc.HasExited) {
    # Try raw status code as a fallback (health endpoint may return 200 without 'success' key)
    try {
        $raw = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        if ($raw.StatusCode -eq 200) {
            $healthy = $true
            Pass "/api/health returned HTTP 200 (raw)"
        }
    } catch {}
}

if (-not $healthy) {
    Show-KotoStartupDiagnostics -InstallDir $TestInstallDir -HealthPort $Port
    if ($RequireHealth) {
        Fail "Health endpoint did not respond within ${HealthTimeoutSec}s"
    } else {
        Write-Host "::warning::Health endpoint did not respond within ${HealthTimeoutSec}s (best-effort in CI — pywebview may not init headless)"
    }
}

# A backend-only check used to hide desktop failures. Require the callback
# emitted only after pywebview has created and shown the real native window.
$desktopReady = $false
$desktopDeadline = (Get-Date).AddSeconds($HealthTimeoutSec)
$startupLog = Join-Path $TestInstallDir "logs\startup.log"
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
    Show-KotoStartupDiagnostics -InstallDir $TestInstallDir -HealthPort $Port
    if ($RequireDesktopWindow) { Fail "Desktop window was not shown within ${HealthTimeoutSec}s" }
    else { Write-Host "::warning::Desktop window callback was not observed" }
}
else {
    Start-Sleep -Seconds 3
    Save-KotoWindowEvidence -OutputDirectory $EvidenceDir -Process $kotoProc
    if ($DesktopHoldSec -gt 0) {
        Write-Host "  Holding the installed desktop open for ${DesktopHoldSec}s..."
        Start-Sleep -Seconds $DesktopHoldSec
    }
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

# The setup and application share an exact AppMutex. An upgrade must never
# replace Python/DLL files while the installed desktop is still running.
Write-Host "`n[Step 5b] Verifying running-app upgrade protection..."
$blockedUpgrade = Start-Process -FilePath $SetupExe `
    -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/DIR=`"$TestInstallDir`"" `
    -Wait -PassThru
if ($blockedUpgrade.ExitCode -ne 0) {
    Pass "Installer refused to overwrite a running Koto instance"
}
else {
    Fail "Installer accepted an upgrade while Koto was still running"
}
if (-not $kotoProc.HasExited) { Pass "Running Koto instance remained alive" }
else                          { Fail "Koto exited during the blocked upgrade check" }

# ══════════════════════════════════════════════════════════════════════════
# STEP 6 — Stop Koto
# ══════════════════════════════════════════════════════════════════════════
Write-Host "`n[Step 6] Stopping Koto.exe..."
if (-not $kotoProc.HasExited) {
    Stop-Process -Id $kotoProc.Id -Force -ErrorAction SilentlyContinue
    $kotoProc.WaitForExit(5000) | Out-Null
    Pass "Process stopped"
}

# ══════════════════════════════════════════════════════════════════════════
# STEP 7 — True in-place upgrade with a stale runtime marker
# ══════════════════════════════════════════════════════════════════════════
Write-Host "`n[Step 7] Running a true in-place upgrade..."
$staleRuntimeMarker = Join-Path $internalDir "e2e-obsolete-runtime-marker.txt"
$userDataSentinel = Join-Path $TestInstallDir "config\e2e-user-data-sentinel.txt"
Set-Content -LiteralPath $staleRuntimeMarker -Value "must be removed by InstallDelete" -Encoding UTF8
Set-Content -LiteralPath $userDataSentinel -Value "must survive an in-place upgrade" -Encoding UTF8
$upgrade = Start-Process -FilePath $SetupExe `
    -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/DIR=`"$TestInstallDir`"" `
    -Wait -PassThru
if ($upgrade.ExitCode -eq 0) { Pass "In-place upgrade exited 0" }
else                         { Fail "In-place upgrade exited $($upgrade.ExitCode)" }

# ══════════════════════════════════════════════════════════════════════════
# STEP 8 — Verify managed-runtime cleanup and user-data preservation
# ══════════════════════════════════════════════════════════════════════════
Write-Host "`n[Step 8] Verifying in-place upgrade boundaries..."
if (Test-Path $staleRuntimeMarker) { Fail "Stale _internal marker survived upgrade" }
else                               { Pass "Stale _internal runtime removed before upgrade" }
if (Test-Path $userDataSentinel) { Pass "User config survived in-place upgrade" }
else                              { Fail "User config was deleted during in-place upgrade" }
if (Test-Path $exePath) { Pass "Koto.exe present after in-place upgrade" }
else                    { Fail "Koto.exe missing after in-place upgrade" }

# ══════════════════════════════════════════════════════════════════════════
# STEP 9 — Silent uninstall
# ══════════════════════════════════════════════════════════════════════════
Write-Host "`n[Step 9] Silent uninstall..."
$uninsExe = Join-Path $TestInstallDir "unins000.exe"
if (Test-Path $uninsExe) {
    $u = Start-Process -FilePath $uninsExe `
        -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART" `
        -Wait -PassThru
    if ($u.ExitCode -eq 0) { Pass "Uninstaller exited 0" }
    else                   { Fail "Uninstaller exited $($u.ExitCode)" }
} else {
    Fail "unins000.exe not found - cannot uninstall"
}

# ══════════════════════════════════════════════════════════════════════════
# STEP 10 — Verify cleanup
# ══════════════════════════════════════════════════════════════════════════
Write-Host "`n[Step 10] Verifying uninstall cleanup..."
Start-Sleep -Seconds 2
if (Test-Path $exePath) { Fail "Koto.exe still present after uninstall" }
else                    { Pass "Koto.exe removed" }
if (-not (Test-Path $regPath)) { Pass "Registry key removed after uninstall" }
else                           { Fail "Registry key still present after uninstall" }

# ══════════════════════════════════════════════════════════════════════════
# RESULT
# ══════════════════════════════════════════════════════════════════════════
Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "✅ Installer E2E: ALL CHECKS PASSED" -ForegroundColor Green
    exit 0
} else {
    Write-Host "❌ Installer E2E: $($failures.Count) CHECK(S) FAILED:" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "   - $_" -ForegroundColor Red }
    exit 1
}
