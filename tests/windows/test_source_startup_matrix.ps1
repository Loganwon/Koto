#Requires -Version 5.1
<#
.SYNOPSIS
    Exercise Koto's real source desktop startup lifecycle on Windows.
.DESCRIPTION
    Covers normal startup, duplicate launch, forced status-page startup, and a
    non-Koto preferred-port conflict. Assertions use startup_events.jsonl plus
    the structured startup-health endpoint.
#>

param(
    [string]$RepoRoot = "",
    [int]$TimeoutSec = 90,
    [switch]$AllowStopExisting,
    [switch]$LeaveRunning
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
} else {
    $RepoRoot = (Resolve-Path $RepoRoot).Path
}

$Launcher = Join-Path $RepoRoot "Koto_Start.ps1"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$LockFile = Join-Path $RepoRoot ".koto.lock"
$EventFile = Join-Path $RepoRoot "logs\startup_events.jsonl"
$MatrixEventDir = Join-Path $RepoRoot "logs\startup_matrix"
$savedEnvironment = @{}
$environmentNames = @(
    "KOTO_PORT",
    "KOTO_STARTUP_FAST_READY_SEC",
    "KOTO_STARTUP_TIMEOUT_SEC",
    "KOTO_STARTUP_PARENT_SESSION_ID",
    "KOTO_PYTHON_RUNTIME_READY_MONOTONIC"
)
$dummyRootPid = $null

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Get-FreePort {
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

function Get-ProcessTreeIds([int]$RootPid) {
    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $result = [System.Collections.Generic.List[int]]::new()
    $queue = [System.Collections.Generic.Queue[int]]::new()
    $queue.Enqueue($RootPid)
    while ($queue.Count -gt 0) {
        $current = $queue.Dequeue()
        if ($result.Contains($current)) { continue }
        $result.Add($current)
        foreach ($child in $all | Where-Object { [int]$_.ParentProcessId -eq $current }) {
            $queue.Enqueue([int]$child.ProcessId)
        }
    }
    return @($result)
}

function Stop-ProcessTree([int]$RootPid) {
    $ids = @(Get-ProcessTreeIds -RootPid $RootPid)
    for ($index = $ids.Count - 1; $index -ge 0; $index--) {
        Stop-Process -Id $ids[$index] -Force -ErrorAction SilentlyContinue
    }
}

function Get-OwnedDesktopProcesses {
    $rootPattern = [regex]::Escape($RepoRoot)
    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and
        $_.CommandLine -match $rootPattern -and
        $_.CommandLine -match "src[/\\]koto_(setup|app)\.py"
    })
}

function Stop-KotoDesktop {
    if (Test-Path -LiteralPath $LockFile) {
        $text = (Get-Content -LiteralPath $LockFile -Raw -ErrorAction SilentlyContinue).Trim()
        if ($text -match '^\d+$') { Stop-ProcessTree -RootPid ([int]$text) }
    }
    foreach ($process in Get-OwnedDesktopProcesses) {
        Stop-Process -Id ([int]$process.ProcessId) -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 500
    Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
}

function Read-StartupEvents {
    if (-not (Test-Path -LiteralPath $EventFile)) { return @() }
    return @(Get-Content -LiteralPath $EventFile -ErrorAction SilentlyContinue |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        ForEach-Object { $_ | ConvertFrom-Json })
}

function Save-ScenarioEvents([string]$Scenario) {
    New-Item -ItemType Directory -Path $MatrixEventDir -Force | Out-Null
    $destination = Join-Path $MatrixEventDir "$Scenario.jsonl"
    Copy-Item -LiteralPath $EventFile -Destination $destination -Force
}

function Wait-StartupEvent([string]$EventName) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $match = @(Read-StartupEvents | Where-Object { $_.event -eq $EventName } | Select-Object -Last 1)
        if ($match.Count -gt 0) { return $match[0] }
        Start-Sleep -Milliseconds 250
    }
    throw "Timed out waiting for startup event '$EventName'"
}

function Invoke-Launcher([int]$Port, [bool]$ForceStatusPage = $false) {
    $env:KOTO_PORT = [string]$Port
    $env:KOTO_STARTUP_TIMEOUT_SEC = [string]$TimeoutSec
    if ($ForceStatusPage) {
        $env:KOTO_STARTUP_FAST_READY_SEC = "0"
    } else {
        Remove-Item Env:KOTO_STARTUP_FAST_READY_SEC -ErrorAction SilentlyContinue
    }
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
        -File $Launcher -Mode desktop -NoAutoRestart
    if ($LASTEXITCODE -ne 0) { throw "Koto launcher exited with $LASTEXITCODE" }
}

function Assert-HealthyPort([int]$Port) {
    $response = Invoke-RestMethod `
        -Uri "http://127.0.0.1:$Port/api/startup-health" `
        -TimeoutSec 3 -ErrorAction Stop
    Assert-True ([string]$response.status -eq "healthy") "Port $Port did not return healthy startup status"
}

foreach ($name in $environmentNames) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

try {
    Assert-True (Test-Path -LiteralPath $Launcher -PathType Leaf) "Launcher not found: $Launcher"
    Assert-True (Test-Path -LiteralPath $Python -PathType Leaf) "Venv Python not found: $Python"

    $existing = @(Get-OwnedDesktopProcesses)
    if ($existing.Count -gt 0 -and -not $AllowStopExisting) {
        throw "A Koto desktop instance is already running. Re-run with -AllowStopExisting only when it is safe to stop it."
    }
    Stop-KotoDesktop

    Write-Host "[matrix] normal startup + duplicate launch" -ForegroundColor Cyan
    Remove-Item -LiteralPath $EventFile -Force -ErrorAction SilentlyContinue
    $normalPort = Get-FreePort
    Invoke-Launcher -Port $normalPort
    Wait-StartupEvent -EventName "window_shown" | Out-Null
    Wait-StartupEvent -EventName "frontend_ready" | Out-Null
    Assert-HealthyPort -Port $normalPort
    $lockBefore = (Get-Content -LiteralPath $LockFile -Raw).Trim()
    $sessionsBefore = @(Read-StartupEvents | Where-Object { $_.event -eq "desktop_start" }).Count
    Invoke-Launcher -Port $normalPort
    $lockAfter = (Get-Content -LiteralPath $LockFile -Raw).Trim()
    $sessionsAfter = @(Read-StartupEvents | Where-Object { $_.event -eq "desktop_start" }).Count
    Assert-True ($lockBefore -eq $lockAfter) "Duplicate launch replaced the running desktop PID"
    Assert-True ($sessionsBefore -eq $sessionsAfter) "Duplicate launch created another desktop session"
    Save-ScenarioEvents -Scenario "normal"
    Stop-KotoDesktop

    Write-Host "[matrix] forced slow/status-page startup" -ForegroundColor Cyan
    Remove-Item -LiteralPath $EventFile -Force -ErrorAction SilentlyContinue
    $slowPort = Get-FreePort
    Invoke-Launcher -Port $slowPort -ForceStatusPage $true
    $slowWindow = Wait-StartupEvent -EventName "window_shown"
    Wait-StartupEvent -EventName "frontend_ready" | Out-Null
    $statusStopped = Wait-StartupEvent -EventName "status_server_stopped"
    Assert-HealthyPort -Port $slowPort
    Assert-True ([bool]$slowWindow.via_status_page) "Slow startup did not exercise the status page"
    $statusListener = Get-NetTCPConnection -State Listen -LocalPort ([int]$statusStopped.port) -ErrorAction SilentlyContinue
    Assert-True ($null -eq $statusListener) "Startup status server did not release port $($statusStopped.port)"
    Save-ScenarioEvents -Scenario "slow"
    Stop-KotoDesktop

    Write-Host "[matrix] non-Koto preferred-port conflict" -ForegroundColor Cyan
    Remove-Item -LiteralPath $EventFile -Force -ErrorAction SilentlyContinue
    $conflictPort = Get-FreePort
    $dummy = Start-Process -FilePath $Python `
        -ArgumentList @("-m", "http.server", [string]$conflictPort, "--bind", "127.0.0.1") `
        -WorkingDirectory $RepoRoot -WindowStyle Hidden -PassThru
    $dummyRootPid = $dummy.Id
    $deadline = (Get-Date).AddSeconds(10)
    do {
        $dummyListener = Get-NetTCPConnection -State Listen -LocalPort $conflictPort -ErrorAction SilentlyContinue
        if ($dummyListener) { break }
        Start-Sleep -Milliseconds 100
    } while ((Get-Date) -lt $deadline)
    Assert-True ($null -ne $dummyListener) "Conflict fixture did not bind port $conflictPort"

    Invoke-Launcher -Port $conflictPort
    $selection = Wait-StartupEvent -EventName "backend_port_selected"
    Wait-StartupEvent -EventName "window_shown" | Out-Null
    Wait-StartupEvent -EventName "frontend_ready" | Out-Null
    Assert-True ([bool]$selection.used_fallback) "Koto did not report fallback-port selection"
    Assert-True ([int]$selection.port -ne $conflictPort) "Koto reused the occupied preferred port"
    Assert-HealthyPort -Port ([int]$selection.port)
    $dummyStillListening = Get-NetTCPConnection -State Listen -LocalPort $conflictPort -ErrorAction SilentlyContinue
    Assert-True ($null -ne $dummyStillListening) "Koto terminated the non-Koto conflict fixture"
    Save-ScenarioEvents -Scenario "port_conflict"
    Stop-KotoDesktop
    Stop-ProcessTree -RootPid $dummyRootPid
    $dummyRootPid = $null

    Write-Host "[PASS] Source desktop startup lifecycle matrix passed." -ForegroundColor Green
} finally {
    Stop-KotoDesktop
    if ($null -ne $dummyRootPid) { Stop-ProcessTree -RootPid $dummyRootPid }
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], "Process")
    }
    if ($LeaveRunning) {
        Remove-Item Env:KOTO_STARTUP_FAST_READY_SEC -ErrorAction SilentlyContinue
        & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File $Launcher -Mode desktop -NoAutoRestart
    }
}
