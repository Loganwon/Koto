<#
.SYNOPSIS
    Seeds minimal config files so Koto.exe starts without the interactive setup wizard.
    Used by installer and portable E2E tests in CI and local runs.

.PARAMETER InstallDir
    Root directory where Koto is installed/extracted (contains Koto.exe).

.EXAMPLE
    .\seed_config.ps1 -InstallDir "C:\KotoTest"
#>
param(
    [Parameter(Mandatory=$true)]
    [string]$InstallDir
)

$configDir = Join-Path $InstallDir "config"
New-Item -ItemType Directory -Force -Path $configDir | Out-Null

# --- gemini_config.env -------------------------------------------------
# A syntactically valid but dummy API key stops the wizard from showing.
# Koto will warn about an invalid key but will still start the Flask server.
$geminiConfig = Join-Path $configDir "gemini_config.env"
@"
GEMINI_API_KEY=CI_TEST_DUMMY_KEY_NOT_REAL
API_BASE=
"@ | Set-Content -Path $geminiConfig -Encoding UTF8

# --- user_settings.json ------------------------------------------------
# Minimal settings: cloud model mode so no local Ollama needed in CI.
$userSettings = Join-Path $configDir "user_settings.json"
@"
{
  "model_mode": "cloud",
  "local_model_tag": "",
  "theme": "dark",
  "language": "zh",
  "auto_start": false,
  "notifications": false
}
"@ | Set-Content -Path $userSettings -Encoding UTF8

# --- local_model_prompt_shown.flag -------------------------------------
# Prevents the "install local model?" prompt on first boot.
$flagDir = Join-Path $InstallDir "config"
"prompted" | Set-Content -Path (Join-Path $flagDir "local_model_prompt_shown.flag") -Encoding UTF8

Write-Host "[seed_config] Config seeded at: $configDir"
