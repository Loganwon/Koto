from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_desktop_launcher_stops_server_lock_instead_of_opening_browser():
    src = (_repo_root() / "Koto_Start.ps1").read_text(encoding="utf-8-sig")

    assert "function Invoke-LockCheck" in src
    assert "param([string]$RunMode)" in src
    assert 'if ($RunMode -eq "desktop")' in src
    assert "Stop-Process -Id ([int]$lockedPid)" in src
    assert "desktop 启动将先停止它" in src
    assert "Invoke-LockCheck -RunMode $Mode" in src


def test_desktop_launcher_requires_json_health_contract():
    src = (_repo_root() / "Koto_Start.ps1").read_text(encoding="utf-8-sig")

    assert "Invoke-RestMethod" in src
    assert '$status -in @("healthy", "degraded")' in src
    assert "$response -is [string]" in src
