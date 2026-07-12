from __future__ import annotations

from pathlib import Path


def test_server_launch_overrides_stale_port_environment(monkeypatch):
    import launcher.entry as entry

    monkeypatch.setenv("KOTO_PORT", "5000")
    monkeypatch.setattr(entry.bootstrap, "find_entry_script", lambda mode: "src/server.py")
    monkeypatch.setattr(entry.subprocess, "call", lambda command: 0)
    monkeypatch.setattr(entry.os, "chdir", lambda path: None)

    assert entry.launch_server(Path.cwd(), 5001) == 0
    assert entry.os.environ["KOTO_PORT"] == "5001"
