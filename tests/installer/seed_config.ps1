<#
.SYNOPSIS
    Seeds one provider-startup scenario for source, installer, and portable E2E.
#>
param(
    [Parameter(Mandatory=$true)]
    [string]$InstallDir,

    [ValidateSet(
        "blank",
        "cloud_invalid",
        "cloud_offline",
        "local_unselected",
        "local_service_down",
        "local_model_missing",
        "local_runtime_incompatible",
        "legacy_upgrade"
    )]
    [string]$Scenario = "cloud_invalid"
)

$configDir = Join-Path $InstallDir "config"
New-Item -ItemType Directory -Force -Path $configDir | Out-Null

foreach ($name in @(
    "deepseek_config.env",
    "gemini_config.env",
    "user_settings.json",
    "model_setup_done.json",
    "local_model_prompted.json"
)) {
    Remove-Item -LiteralPath (Join-Path $configDir $name) -Force -ErrorAction SilentlyContinue
}

$settings = [ordered]@{
    model_mode = "cloud"
    local_model = ""
    theme = "dark"
    language = "zh"
    auto_start = $false
    notifications = $false
    startup_test_scenario = $Scenario
}
$deepseekConfig = $null

switch ($Scenario) {
    "cloud_invalid" {
        $deepseekConfig = "DEEPSEEK_API_KEY=CI_INVALID_KEY_NOT_REAL`nDEEPSEEK_BASE_URL=https://api.deepseek.com`n"
    }
    "cloud_offline" {
        $deepseekConfig = "DEEPSEEK_API_KEY=CI_OFFLINE_KEY_NOT_REAL`nDEEPSEEK_BASE_URL=http://127.0.0.1:1`n"
    }
    "local_unselected" {
        $settings.model_mode = "local"
    }
    "local_service_down" {
        $settings.model_mode = "local"
        $settings.local_model = "qwen2.5:7b"
    }
    "local_model_missing" {
        $settings.model_mode = "local"
        $settings.local_model = "koto-e2e-model-does-not-exist:latest"
    }
    "local_runtime_incompatible" {
        $settings.model_mode = "local"
        $settings.local_model = "koto-e2e-requires-newer-ollama:latest"
        $settings.local_runtime_fixture = [ordered]@{
            current_version = "0.1.0"
            required_version = "99.0.0"
        }
    }
    "legacy_upgrade" {
        $settings.Remove("local_model")
        $settings.model_mode = "ollama"
        $settings.local_model_tag = "legacy-user-model:7b"
    }
}

if ($null -ne $deepseekConfig) {
    Set-Content -LiteralPath (Join-Path $configDir "deepseek_config.env") `
        -Value $deepseekConfig -Encoding UTF8
}
$settings | ConvertTo-Json -Depth 5 | Set-Content `
    -LiteralPath (Join-Path $configDir "user_settings.json") -Encoding UTF8

# This flag belongs to the old optional local-model prompt.  Keeping it in E2E
# data prevents legacy builds from stealing focus while upgrade behavior is tested.
@{ prompted = $true; action = "e2e-$Scenario" } | ConvertTo-Json | Set-Content `
    -LiteralPath (Join-Path $configDir "local_model_prompted.json") -Encoding UTF8

Write-Host "[seed_config] Scenario '$Scenario' seeded at: $configDir"
