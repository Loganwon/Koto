from __future__ import annotations

import io
import json
import re
import shutil
import socket
import subprocess
import threading
import urllib.request
import zipfile
from pathlib import Path
from types import SimpleNamespace

from src import startup_recovery, webview2_runtime


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


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

    ok, detail = webview2_runtime.ensure_webview2_runtime(tmp_path, detection_timeout=1)

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


def test_startup_status_server_redirect_contract(tmp_path):
    port = _free_port()
    restart_called = threading.Event()
    log_messages: list[str] = []
    events: list[tuple[str, dict]] = []
    backend_url = "http://127.0.0.1:59991"
    thread = threading.Thread(
        target=startup_recovery.serve_startup_status,
        args=("127.0.0.1", port),
        kwargs={
            "app_root": tmp_path,
            "bundle_dir": tmp_path,
            "backend_url": backend_url,
            "status_provider": lambda: {"status": "ready", "phase": "ready"},
            "restart": restart_called.set,
            "log": log_messages.append,
            "event": lambda name, **details: events.append((name, details)),
        },
        daemon=True,
    )
    thread.start()

    status_url = f"http://127.0.0.1:{port}/api/status"
    for _ in range(40):
        try:
            with urllib.request.urlopen(status_url, timeout=0.25) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except OSError:
            threading.Event().wait(0.025)
    else:
        raise AssertionError("startup status server did not listen")

    assert payload["status"] == "ready"
    assert payload["target_url"] == backend_url
    assert "✔ 启动状态页已检测到后端就绪，正在切换主界面" in log_messages

    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/api/support-bundle", timeout=1
    ) as response:
        support_payload = response.read()
        assert response.headers.get_content_type() == "application/zip"
        assert "Koto_Support_" in response.headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(support_payload)) as archive:
        assert {"diagnostics.json", "system.json", "manifest.json"} <= set(
            archive.namelist()
        )

    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/retry", method="POST"
    )
    with urllib.request.urlopen(request, timeout=1) as response:
        assert json.loads(response.read().decode("utf-8"))["success"] is True
    assert restart_called.wait(1)
    thread.join(timeout=3)
    assert not thread.is_alive(), "startup status port must be released after redirect"
    assert "✔ 启动状态服务已完成使命并释放端口" in log_messages
    assert [name for name, _details in events] == [
        "status_server_listening",
        "status_backend_ready",
        "status_support_bundle_exported",
        "status_restart_requested",
        "status_server_stopped",
    ]


def test_recovery_page_never_recommends_source_environment_repairs():
    page = startup_recovery._page(r"C:\Koto\logs\startup.log")

    assert "不需要运行 pip" in page
    assert "requirements.txt" not in page
    assert "RunSource.bat" not in page
    assert "Failed to fetch" not in page
    assert "导出支持包" in page
    assert "/api/support-bundle" in page


def test_recovery_page_polling_script_has_no_literal_newline_in_js_string():
    page = startup_recovery._page(r"C:\Koto\logs\startup.log")

    assert "const NL=String.fromCharCode(10);" in page
    assert ".join(NL)" in page
    assert "+NL+" in page
    assert "+'\n'+" not in page


def test_recovery_page_embedded_javascript_is_syntactically_valid():
    page = startup_recovery._page(r"C:\Koto\logs\startup.log")
    script = re.search(r"<script>([\s\S]*?)</script>", page)
    node = shutil.which("node")

    assert script is not None
    assert node is not None, "Node.js is required by the frontend release toolchain"
    checked = subprocess.run(
        [node, "--check", "-"],
        input=script.group(1),
        text=True,
        capture_output=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr
