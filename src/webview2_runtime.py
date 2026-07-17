"""WebView2 Runtime detection and offline bootstrap for Windows releases.

Koto bundles the WebView2 loader assemblies through pywebview, but the loader is
not the browser runtime itself.  Fresh Windows 10 installations may not have the
Evergreen Runtime, so release builds ship Microsoft's signed x64 standalone
installer and invoke it only when the documented registry keys are absent.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

WEBVIEW2_CLIENT_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_INSTALLER_NAME = "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"

_MACHINE_KEY = (
    rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_ID}"
)
_USER_KEY = rf"Software\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_ID}"


def _usable_version(value: object) -> str | None:
    version = str(value or "").strip()
    if not version or version == "0.0.0.0":
        return None
    return version


def get_webview2_version() -> str | None:
    """Return the installed Evergreen Runtime version from Microsoft's keys."""
    if sys.platform != "win32":
        return "not-required"

    try:
        import winreg
    except ImportError:
        return None

    locations = (
        (winreg.HKEY_LOCAL_MACHINE, _MACHINE_KEY),
        (winreg.HKEY_CURRENT_USER, _USER_KEY),
    )
    for root, key_path in locations:
        try:
            with winreg.OpenKey(root, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "pv")
        except OSError:
            continue
        version = _usable_version(value)
        if version:
            return version
    return None


def find_bundled_installer(app_root: Path | str) -> Path | None:
    root = Path(app_root).resolve()
    candidates = (
        root / WEBVIEW2_INSTALLER_NAME,
        root / "prerequisites" / WEBVIEW2_INSTALLER_NAME,
    )
    return next((path for path in candidates if path.is_file()), None)


def ensure_webview2_runtime(
    app_root: Path | str,
    *,
    log: Callable[[str], None] | None = None,
    install_timeout: float = 300.0,
    detection_timeout: float = 20.0,
) -> tuple[bool, str]:
    """Ensure the desktop runtime exists, installing the bundled copy if needed."""
    emit = log or (lambda _message: None)

    if os.environ.get("KOTO_SERVER_ONLY") == "1":
        return True, "server-only mode does not require WebView2"
    if os.environ.get("KOTO_SKIP_WEBVIEW2_CHECK") == "1":
        return True, "WebView2 preflight explicitly skipped"

    version = get_webview2_version()
    if version:
        emit(f"WebView2 Runtime ready: {version}")
        return True, version

    installer = find_bundled_installer(app_root)
    if installer is None:
        return (
            False,
            f"WebView2 Runtime is missing and {WEBVIEW2_INSTALLER_NAME} was not packaged",
        )

    emit(f"WebView2 Runtime missing; installing bundled prerequisite: {installer.name}")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            [str(installer), "/silent", "/install"],
            cwd=str(installer.parent),
            check=False,
            timeout=max(float(install_timeout), 1.0),
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired:
        return False, "WebView2 Runtime installation timed out"
    except OSError as exc:
        return False, f"WebView2 Runtime installer could not start: {exc}"

    deadline = time.monotonic() + max(float(detection_timeout), 0.0)
    while True:
        version = get_webview2_version()
        if version:
            emit(f"WebView2 Runtime installed: {version}")
            return True, version
        if time.monotonic() >= deadline:
            break
        time.sleep(0.25)

    return (
        False,
        "WebView2 Runtime installer exited with code "
        f"{completed.returncode}, but the Runtime is still unavailable",
    )
