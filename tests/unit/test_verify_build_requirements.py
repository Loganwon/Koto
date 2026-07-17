from __future__ import annotations

import importlib.metadata

from scripts.verify_build_requirements import main, read_exact_pins


def test_read_exact_pins_rejects_ranges(tmp_path):
    lockfile = tmp_path / "build.lock"
    lockfile.write_text("PyInstaller>=6\n", encoding="utf-8")

    try:
        read_exact_pins(lockfile)
    except ValueError as exc:
        assert "exact == pin" in str(exc)
    else:
        raise AssertionError("non-exact build dependency was accepted")


def test_verify_build_requirements_accepts_matching_versions(
    tmp_path, monkeypatch, capsys
):
    lockfile = tmp_path / "build.lock"
    lockfile.write_text("Cython==3.2.5\nPyInstaller==6.20.0\n", encoding="utf-8")
    versions = {"Cython": "3.2.5", "PyInstaller": "6.20.0"}
    monkeypatch.setattr(importlib.metadata, "version", versions.__getitem__)
    monkeypatch.setattr("sys.argv", ["verify_build_requirements.py", str(lockfile)])

    assert main() == 0
    assert "Cython==3.2.5" in capsys.readouterr().out
