# Shared process helpers for installer and portable release validation.

function Assert-KotoAuthenticodeSignature {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string]$ExpectedThumbprint
    )

    $normalizedExpected = ($ExpectedThumbprint -replace '[^0-9A-Fa-f]', '').ToUpperInvariant()
    if ($normalizedExpected -notmatch '^[0-9A-F]{40,128}$') {
        throw "Expected signer thumbprint is invalid."
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $FilePath
    if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        throw "Invalid Authenticode signature for '$FilePath': $($signature.Status)"
    }
    if (-not $signature.SignerCertificate -or
        $signature.SignerCertificate.Thumbprint.ToUpperInvariant() -ne $normalizedExpected) {
        throw "Unexpected Authenticode signer for '$FilePath'."
    }
    if (-not $signature.TimeStamperCertificate) {
        throw "Trusted timestamp is missing for '$FilePath'."
    }
}

function Test-KotoHealthResponse {
    param([Parameter(Mandatory = $true)]$Response)

    if ($Response.success -eq $true) { return $true }
    $status = [string]$Response.status
    return $status.Trim().ToLowerInvariant() -in @("ok", "healthy", "degraded")
}

function Start-KotoWithoutDeveloperEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$ExePath,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    $names = @(
        "PATH",
        "PYTHONHOME",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "NODE_PATH",
        "JAVA_HOME"
    )
    $saved = @{}
    foreach ($name in $names) {
        $saved[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }

    try {
        [Environment]::SetEnvironmentVariable(
            "PATH",
            "$env:SystemRoot\System32;$env:SystemRoot",
            "Process"
        )
        foreach ($name in $names | Where-Object { $_ -ne "PATH" }) {
            [Environment]::SetEnvironmentVariable($name, $null, "Process")
        }
        return Start-Process `
            -FilePath $ExePath `
            -WorkingDirectory $WorkingDirectory `
            -PassThru
    }
    finally {
        foreach ($name in $names) {
            [Environment]::SetEnvironmentVariable($name, $saved[$name], "Process")
        }
    }
}

function Export-KotoDesktopStartupEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$OutputDirectory,
        [Parameter(Mandatory = $true)][string]$Scenario
    )

    if ([string]::IsNullOrWhiteSpace($OutputDirectory)) { return $null }
    if ($Scenario -notmatch '^[A-Za-z0-9_-]+$') {
        throw "Unsafe startup evidence scenario name: $Scenario"
    }

    $source = Join-Path $InstallDir "logs\startup_events.jsonl"
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Structured startup event log was not created: $source"
    }

    $deadline = (Get-Date).AddSeconds(10)
    do {
        $rawLines = @(
            Get-Content -LiteralPath $source -Encoding UTF8 |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        )
        $events = @($rawLines | ForEach-Object { $_ | ConvertFrom-Json })
        $windowSessions = @(
            $events |
                Where-Object { [string]$_.event -eq "window_shown" } |
                Select-Object -ExpandProperty session_id -Unique
        )
        $frontendSessions = @(
            $events |
                Where-Object { [string]$_.event -eq "frontend_ready" } |
                Select-Object -ExpandProperty session_id -Unique
        )
        $completedSessions = @(
            $windowSessions | Where-Object { $frontendSessions -contains $_ }
        )
        if ($completedSessions.Count -eq 1) { break }
        Start-Sleep -Milliseconds 100
    } while ((Get-Date) -lt $deadline)
    if ($completedSessions.Count -ne 1) {
        throw "Expected exactly one interactive desktop startup session, found $($completedSessions.Count)"
    }

    $sessionId = [string]$completedSessions[0]
    $sessionLines = [System.Collections.Generic.List[string]]::new()
    $eventNames = [System.Collections.Generic.HashSet[string]]::new()
    for ($index = 0; $index -lt $events.Count; $index += 1) {
        if ([string]$events[$index].session_id -eq $sessionId) {
            $sessionLines.Add($rawLines[$index])
            [void]$eventNames.Add([string]$events[$index].event)
        }
    }
    foreach ($required in @("desktop_start", "backend_port_selected", "window_shown", "frontend_ready")) {
        if (-not $eventNames.Contains($required)) {
            throw "Desktop startup session $sessionId is missing event '$required'"
        }
    }

    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    $destination = Join-Path $OutputDirectory "$Scenario.jsonl"
    $utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllLines($destination, $sessionLines, $utf8WithoutBom)
    Write-Host "  Frozen desktop startup evidence: $destination"
    return $destination
}

function Get-KotoStartupScenarios {
    return @(
        [pscustomobject]@{ Name = "blank"; ExpectedMode = "cloud"; ExpectedStatus = "misconfigured" },
        [pscustomobject]@{ Name = "cloud_invalid"; ExpectedMode = "cloud"; ExpectedStatus = "available" },
        [pscustomobject]@{ Name = "cloud_offline"; ExpectedMode = "cloud"; ExpectedStatus = "available" },
        [pscustomobject]@{ Name = "local_unselected"; ExpectedMode = "local"; ExpectedStatus = "misconfigured" },
        [pscustomobject]@{ Name = "local_service_down"; ExpectedMode = "local"; ExpectedStatus = "checking" },
        [pscustomobject]@{ Name = "local_model_missing"; ExpectedMode = "local"; ExpectedStatus = "checking" },
        [pscustomobject]@{ Name = "local_runtime_incompatible"; ExpectedMode = "local"; ExpectedStatus = "checking" },
        [pscustomobject]@{ Name = "legacy_upgrade"; ExpectedMode = "local"; ExpectedStatus = "checking" }
    )
}

function Invoke-KotoStartupMatrix {
    param(
        [Parameter(Mandatory = $true)][string]$ExePath,
        [Parameter(Mandatory = $true)][string]$InstallDir,
        [Parameter(Mandatory = $true)][string]$ScriptDir,
        [Parameter(Mandatory = $true)][int]$BasePort,
        [int]$TimeoutSec = 45,
        [string[]]$ScenarioNames = @()
    )

    $savedEnvironment = @{}
    $environmentNames = @(
        "KOTO_PORT", "KOTO_SERVER_ONLY",
        "DEEPSEEK_API_KEY", "DEEPSEEK_KEY", "DS_API_KEY", "DS_KEY",
        "DEEPSEEK_BASE_URL", "DEEPSEEK_API_BASE", "OLLAMA_BASE_URL", "OLLAMA_HOST",
        "KOTO_DEEPSEEK_CONFIG_PATH", "KOTO_USER_SETTINGS_PATH"
    )
    foreach ($name in $environmentNames) {
        $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }

    $matrixFailures = [System.Collections.Generic.List[string]]::new()
    try {
        foreach ($name in $environmentNames) {
            [Environment]::SetEnvironmentVariable($name, $null, "Process")
        }
        $env:KOTO_SERVER_ONLY = "1"
        $env:KOTO_DEEPSEEK_CONFIG_PATH = Join-Path $InstallDir "config\deepseek_config.env"
        $env:KOTO_USER_SETTINGS_PATH = Join-Path $InstallDir "config\user_settings.json"
        $index = 0
        $scenarios = @(Get-KotoStartupScenarios)
        if ($ScenarioNames.Count -gt 0) {
            $knownNames = @($scenarios | ForEach-Object { $_.Name })
            $unknownNames = @($ScenarioNames | Where-Object { $_ -notin $knownNames })
            if ($unknownNames.Count -gt 0) {
                throw "Unknown startup scenarios: $($unknownNames -join ', ')"
            }
            $scenarios = @($scenarios | Where-Object { $_.Name -in $ScenarioNames })
        }
        foreach ($scenario in $scenarios) {
            $port = $BasePort + $index
            $index += 1
            $env:KOTO_PORT = [string]$port
            if ($scenario.ExpectedMode -eq "local") {
                $env:OLLAMA_BASE_URL = "http://127.0.0.1:1"
            } else {
                Remove-Item Env:OLLAMA_BASE_URL -ErrorAction SilentlyContinue
            }

            & (Join-Path $ScriptDir "seed_config.ps1") `
                -InstallDir $InstallDir -Scenario $scenario.Name
            $process = $null
            try {
                $process = Start-KotoWithoutDeveloperEnvironment `
                    -ExePath $ExePath -WorkingDirectory $InstallDir
                $deadline = (Get-Date).AddSeconds($TimeoutSec)
                $ready = $false
                while ((Get-Date) -lt $deadline) {
                    if ($process.HasExited) { break }
                    try {
                        $startup = Invoke-RestMethod `
                            -Uri "http://127.0.0.1:$port/api/startup-health" `
                            -TimeoutSec 2 -ErrorAction Stop
                        if ([string]$startup.status -eq "healthy") {
                            $ready = $true
                            break
                        }
                    } catch {}
                    Start-Sleep -Milliseconds 250
                }
                if (-not $ready) {
                    $matrixFailures.Add("$($scenario.Name): startup-health unavailable")
                    continue
                }

                $capabilities = Invoke-RestMethod `
                    -Uri "http://127.0.0.1:$port/api/capabilities" `
                    -TimeoutSec 5 -ErrorAction Stop
                $active = $capabilities.capabilities.active_model
                if ([string]$capabilities.mode -ne $scenario.ExpectedMode) {
                    $matrixFailures.Add(
                        "$($scenario.Name): mode '$($capabilities.mode)', expected '$($scenario.ExpectedMode)'"
                    )
                }
                if ([string]$active.status -ne $scenario.ExpectedStatus) {
                    $matrixFailures.Add(
                        "$($scenario.Name): status '$($active.status)', expected '$($scenario.ExpectedStatus)'"
                    )
                }
                if (-not $process.HasExited) {
                    Write-Host "  PASS: startup scenario '$($scenario.Name)'"
                }
            } catch {
                $matrixFailures.Add("$($scenario.Name): $($_.Exception.Message)")
            } finally {
                if ($null -ne $process -and -not $process.HasExited) {
                    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
                    $process.WaitForExit(5000) | Out-Null
                }
            }
        }
    } finally {
        foreach ($name in $environmentNames) {
            [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], "Process")
        }
    }

    if ($matrixFailures.Count -gt 0) {
        throw "Startup matrix failed: $($matrixFailures -join '; ')"
    }
    return $true
}
