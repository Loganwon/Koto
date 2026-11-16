from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_desktop_launcher_stops_server_lock_instead_of_opening_browser():
    src = (_repo_root() / "Koto_Start.ps1").read_text(encoding="utf-8-sig")

    assert "function Invoke-LockCheck" in src
    assert "param([string]$RunMode)" in src
    assert 'if ($RunMode -eq "desktop")' in src
    assert '$isDesktopProcess = $runningCmd -match "koto_(app|setup)\\.py"' in src
    assert "Stop-Process -Id ([int]$lockedPid)" in src
    assert "desktop 启动将先停止它" in src
    assert "Invoke-LockCheck -RunMode $Mode" in src


def test_desktop_launcher_requires_json_health_contract():
    src = (_repo_root() / "Koto_Start.ps1").read_text(encoding="utf-8-sig")

    assert "Invoke-RestMethod" in src
    assert '$status -notin @("healthy", "degraded")' in src
    assert "$response -is [string]" in src


def test_desktop_launcher_tracks_effective_port_and_owning_instance():
    src = (_repo_root() / "Koto_Start.ps1").read_text(encoding="utf-8-sig")

    assert "$env:KOTO_LAUNCH_TOKEN = $launchToken" in src
    assert "$env:KOTO_STARTUP_PORT_FILE = $startupPortFile" in src
    assert '"X-Koto-Launch-Token" = $LaunchToken' in src
    assert "Test-KotoHealth -Port $probePort -LaunchToken $launchToken" in src
    assert "$Port = $reportedPort" in src


def test_desktop_launcher_uses_fast_probe_and_allows_slow_imports():
    src = (_repo_root() / "Koto_Start.ps1").read_text(encoding="utf-8-sig")

    assert 'Uri = "http://127.0.0.1:$Port/api/startup-health"' in src
    assert "$STARTUP_HEALTH_TIMEOUT_SEC = 120" in src
    assert "$env:KOTO_STARTUP_TIMEOUT_SEC" in src
    assert "AddSeconds($STARTUP_HEALTH_TIMEOUT_SEC)" in src


def test_desktop_launcher_never_kills_a_live_process_on_probe_timeout():
    src = (_repo_root() / "Koto_Start.ps1").read_text(encoding="utf-8-sig")

    timeout_branch = src.split(
        "if (-not $backendHealthy -and -not $proc.HasExited)", 1
    )[1].split("if ($backendHealthy)", 1)[0]
    assert "Stop-KotoProcessTree" not in timeout_branch
    assert "保留桌面进程" in timeout_branch
    assert "exit 0" in timeout_branch


def test_desktop_launcher_uses_cim_command_lines_and_delegates_port_choice():
    src = (_repo_root() / "Koto_Start.ps1").read_text(encoding="utf-8-sig")

    assert "Get-CimInstance Win32_Process" in src
    assert "$procInfo.CommandLine" in src
    port_step = src.split("# Step 6: 端口检查", 1)[1].split("# Step 7:", 1)[0]
    assert 'if ($Mode -eq "desktop")' in port_step
    assert "$KOTO_PORT" in port_step
