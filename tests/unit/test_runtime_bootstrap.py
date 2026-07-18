from __future__ import annotations

import os
import sys
from pathlib import Path

from src import runtime_bootstrap
from src.runtime_bootstrap import RuntimeRoots, configure_frozen_desktop_runtime


def test_frozen_desktop_uses_bundled_python_and_webview_runtime(tmp_path, monkeypatch):
    app_root = tmp_path / "Koto"
    bundle_dir = app_root / "_internal"
    bundle_dir.mkdir(parents=True)
    python_dll = (
        bundle_dir / f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    )
    python_dll.write_bytes(b"test")
    roots = RuntimeRoots(app_root=app_root, bundle_dir=bundle_dir)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("PYWEBVIEW_GUI", "qt")
    monkeypatch.setenv("PYTHONNET_PYDLL", str(tmp_path / "host-python.dll"))

    configure_frozen_desktop_runtime(roots)

    assert os.environ["PYWEBVIEW_GUI"] == "edgechromium"
    assert Path(os.environ["PYTHONNET_PYDLL"]) == python_dll.resolve()


def test_source_runtime_does_not_override_developer_environment(tmp_path, monkeypatch):
    roots = RuntimeRoots(app_root=tmp_path, bundle_dir=tmp_path)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setenv("PYWEBVIEW_GUI", "qt")
    monkeypatch.setenv("PYTHONNET_PYDLL", "developer-python.dll")

    configure_frozen_desktop_runtime(roots)

    assert os.environ["PYWEBVIEW_GUI"] == "qt"
    assert os.environ["PYTHONNET_PYDLL"] == "developer-python.dll"


def test_frozen_runtime_never_inherits_host_python_dll(tmp_path, monkeypatch):
    roots = RuntimeRoots(
        app_root=tmp_path / "Koto",
        bundle_dir=tmp_path / "Koto" / "_internal",
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("PYTHONNET_PYDLL", str(tmp_path / "host-python.dll"))

    configure_frozen_desktop_runtime(roots)

    assert "PYTHONNET_PYDLL" not in os.environ


def test_process_environment_applies_desktop_runtime_once_requested(
    tmp_path, monkeypatch
):
    roots = RuntimeRoots(app_root=tmp_path, bundle_dir=tmp_path / "_internal")
    configured = []
    monkeypatch.setattr(
        runtime_bootstrap,
        "configure_frozen_desktop_runtime",
        configured.append,
    )

    original_cwd = Path.cwd()
    try:
        runtime_bootstrap.configure_process_environment(roots, desktop_runtime=True)
    finally:
        os.chdir(original_cwd)

    assert configured == [roots]
