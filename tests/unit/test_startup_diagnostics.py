from __future__ import annotations

from pathlib import Path


def test_diagnostics_reports_source_readiness_without_importing_app():
    import src.startup_diagnostics as diagnostics

    original = diagnostics._source_shadowing_extensions
    diagnostics._source_shadowing_extensions = lambda _root: []
    try:
        report = diagnostics.run_startup_diagnostics(Path.cwd(), include_import_check=False)
    finally:
        diagnostics._source_shadowing_extensions = original

    assert report["status"] in {"ready", "attention"}
    assert report["can_restart"] is True
    assert any(
        item["name"] == "web/app.py syntax" and item["level"] == "ok"
        for item in report["checks"]
    )


def test_diagnostics_marks_web_import_failure_as_restart_blocker(monkeypatch):
    import src.startup_diagnostics as diagnostics

    monkeypatch.setattr(
        diagnostics,
        "_check_web_app_import",
        lambda root: (False, "cannot import name 'app' from 'web.app'"),
    )
    monkeypatch.setattr(diagnostics, "_source_shadowing_extensions", lambda root: [])
    report = diagnostics.run_startup_diagnostics(Path.cwd(), include_import_check=True)

    assert report["status"] == "blocked"
    assert report["can_restart"] is False
    assert any(
        item["name"] == "web application import" and item["level"] == "error"
        for item in report["checks"]
    )


def test_diagnostics_treats_optional_feature_gaps_as_warnings(monkeypatch):
    import src.startup_diagnostics as diagnostics

    original = diagnostics._module_exists
    monkeypatch.setattr(
        diagnostics,
        "_OPTIONAL_MODULES",
        {"web.optional_feature": "optional feature is unavailable"},
    )
    monkeypatch.setattr(diagnostics, "_source_shadowing_extensions", lambda root: [])
    monkeypatch.setattr(
        diagnostics,
        "_module_exists",
        lambda module: False if module == "web.optional_feature" else original(module),
    )
    report = diagnostics.run_startup_diagnostics(Path.cwd(), include_import_check=False)

    memory_check = next(
        item for item in report["checks"] if item["name"] == "web.optional_feature"
    )
    assert memory_check["level"] == "warning"


def test_diagnostics_blocks_source_shadowing_extensions(monkeypatch):
    import src.startup_diagnostics as diagnostics

    monkeypatch.setattr(
        diagnostics,
        "_source_shadowing_extensions",
        lambda root: [root / "app" / "example.cp311-win_amd64.pyd"],
    )
    report = diagnostics.run_startup_diagnostics(Path.cwd(), include_import_check=False)

    assert report["status"] == "blocked"
    assert any(item["name"] == "compiled source shadowing" for item in report["checks"])


def test_removing_source_shadowing_extensions_reports_locked_files(monkeypatch, tmp_path):
    import src.startup_diagnostics as diagnostics

    artifact = tmp_path / "app" / "example.cp311-win_amd64.pyd"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"compiled")
    monkeypatch.setattr(diagnostics, "_source_shadowing_extensions", lambda root: [artifact])
    monkeypatch.setattr(Path, "unlink", lambda self: (_ for _ in ()).throw(PermissionError("locked")))

    removed, blocked = diagnostics.remove_source_shadowing_extensions(tmp_path)

    assert removed == []
    assert blocked == [(artifact, "locked")]
