from __future__ import annotations

from pathlib import Path


def test_desktop_launcher_prefers_the_packaged_setup_entry(tmp_path, monkeypatch):
    import launcher.bootstrap as bootstrap

    fake_launcher = tmp_path / "launcher"
    fake_src = tmp_path / "src"
    fake_launcher.mkdir()
    fake_src.mkdir()
    (fake_launcher / "bootstrap.py").write_text("", encoding="utf-8")
    (fake_src / "koto_app.py").write_text("", encoding="utf-8")
    setup = fake_src / "koto_setup.py"
    setup.write_text("", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "__file__", str(fake_launcher / "bootstrap.py"))

    assert bootstrap.find_entry_script("desktop") == str(setup)


def test_server_launch_overrides_stale_port_environment(monkeypatch):
    import launcher.entry as entry

    monkeypatch.setenv("KOTO_PORT", "5000")
    monkeypatch.setattr(
        entry.bootstrap, "find_entry_script", lambda mode: "src/server.py"
    )
    monkeypatch.setattr(entry.subprocess, "call", lambda command: 0)
    monkeypatch.setattr(entry.os, "chdir", lambda path: None)

    assert entry.launch_server(Path.cwd(), 5001) == 0
    assert entry.os.environ["KOTO_PORT"] == "5001"
