from __future__ import annotations

from types import SimpleNamespace

from src import webview2_runtime


def test_webview2_preflight_uses_packaged_offline_installer(tmp_path, monkeypatch):
    installer = tmp_path / webview2_runtime.WEBVIEW2_INSTALLER_NAME
    installer.write_bytes(b"signed payload is verified during the release build")
    versions = iter([None, None, "135.0.0.0"])
    calls: list[tuple[list[str], str]] = []

    monkeypatch.delenv("KOTO_SERVER_ONLY", raising=False)
    monkeypatch.delenv("KOTO_SKIP_WEBVIEW2_CHECK", raising=False)
    monkeypatch.setattr(
        webview2_runtime, "get_webview2_version", lambda: next(versions)
    )

    def fake_run(command, **kwargs):
        calls.append((command, kwargs["cwd"]))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(webview2_runtime.subprocess, "run", fake_run)
    monkeypatch.setattr(webview2_runtime.time, "sleep", lambda _seconds: None)

    ok, detail = webview2_runtime.ensure_webview2_runtime(
        tmp_path, detection_timeout=1
    )

    assert ok is True
    assert detail == "135.0.0.0"
    assert calls == [
        (
            [str(installer), "/silent", "/install"],
            str(tmp_path),
        )
    ]


def test_webview2_preflight_reports_incomplete_release_bundle(tmp_path, monkeypatch):
    monkeypatch.delenv("KOTO_SERVER_ONLY", raising=False)
    monkeypatch.delenv("KOTO_SKIP_WEBVIEW2_CHECK", raising=False)
    monkeypatch.setattr(webview2_runtime, "get_webview2_version", lambda: None)

    ok, detail = webview2_runtime.ensure_webview2_runtime(tmp_path)

    assert ok is False
    assert webview2_runtime.WEBVIEW2_INSTALLER_NAME in detail
