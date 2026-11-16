"""Safe, evidence-based diagnostics for Koto startup failures.

The desktop fallback page and ``python -m launcher --health`` share this
module.  Checks deliberately avoid modifying source files or terminating
processes: a diagnostic result should explain a failure, never make it worse.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import ProxyHandler, Request, build_opener

_SOURCE_CRITICAL_FILES = (
    "web/app.py",
    "src/koto_app.py",
    "src/runtime_bootstrap.py",
    "config/requirements.txt",
)

_FROZEN_CRITICAL_FILES = (
    "web/app.py",
    "web/templates/index.html",
    "web/static/js/build/app-bundle.js",
    "config/deepseek_config.env.example",
    "assets/koto_icon.png",
)

_REQUIRED_MODULES = {
    "flask": "Flask Web server",
    "flask_socketio": "SocketIO realtime transport",
    "webview": "desktop WebView",
}

_COMPATIBILITY_MODULES = (
    "app.core.routing.local_dispatcher",
    "app.core.services.model_manager",
    "app.core.analytics.token_tracker",
    "app.core.services.notification_manager",
    "app.core.config.user_settings",
    "app.core.services.knowledge_base",
)

_OPTIONAL_MODULES = {}

_MAX_SUPPORT_LOG_BYTES = 512 * 1024
_SECRET_VALUE_RE = re.compile(
    r"(?im)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret|authorization|cookie)\b[\"']?\s*[:=]\s*[\"']?)([^\s,;}\"']+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_KEY_LIKE_RE = re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{12,}\b")
_URL_CREDENTIAL_RE = re.compile(r"(https?://)([^/@\s:]+):([^/@\s]+)@", re.I)
_WINDOWS_USER_RE = re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+")


def _check(name: str, level: str, message: str, *, action: str = "") -> dict[str, str]:
    return {"name": name, "level": level, "message": message, "action": action}


def _module_exists(module: str) -> bool:
    # Test runners and embedded launchers may already hold a module object
    # without an import spec.  ``find_spec`` raises ValueError in that case,
    # even though the runtime dependency is available to this process.
    if sys.modules.get(module) is not None:
        return True
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def redact_support_text(text: str, *, app_root: Path | str | None = None) -> str:
    """Remove credentials and user-specific paths from exported diagnostics."""
    redacted = str(text)
    roots: list[tuple[str, str]] = []
    if app_root is not None:
        roots.append((str(Path(app_root).resolve()), "<APP_ROOT>"))
    try:
        roots.append((str(Path.home().resolve()), "<HOME>"))
    except OSError:
        pass
    for value, replacement in sorted(
        roots, key=lambda item: len(item[0]), reverse=True
    ):
        if value:
            redacted = re.sub(re.escape(value), replacement, redacted, flags=re.I)
            redacted = re.sub(
                re.escape(value.replace("\\", "/")), replacement, redacted, flags=re.I
            )
    redacted = _WINDOWS_USER_RE.sub(lambda _match: r"C:\Users\<user>", redacted)
    redacted = _URL_CREDENTIAL_RE.sub(r"\1<redacted>@", redacted)
    redacted = _BEARER_RE.sub("Bearer <redacted>", redacted)
    redacted = _KEY_LIKE_RE.sub("<redacted-key>", redacted)
    redacted = _SECRET_VALUE_RE.sub(r"\1<redacted>", redacted)
    return redacted


def write_crash_report(
    app_root: Path | str,
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: Any,
    *,
    thread_name: str,
) -> Path:
    """Persist a small, redacted JSON report for an otherwise unhandled crash."""
    root = Path(app_root).resolve()
    logs_dir = root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
    report_path = logs_dir / (
        f"crash_{timestamp.strftime('%Y%m%dT%H%M%S_%fZ')}_{os.getpid()}.json"
    )
    rendered_traceback = "".join(
        traceback.format_exception(exc_type, exc_value, exc_traceback)
    )
    payload = {
        "schema_version": 1,
        "generated_at": timestamp.isoformat(),
        "process_id": os.getpid(),
        "thread": thread_name,
        "exception_type": exc_type.__name__,
        "exception_message": redact_support_text(str(exc_value), app_root=root),
        "traceback": redact_support_text(rendered_traceback, app_root=root),
        "python_version": platform.python_version(),
        "frozen": bool(getattr(sys, "frozen", False)),
    }
    temporary_path = report_path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary_path.replace(report_path)
    return report_path


def _read_log_tail(path: Path) -> tuple[str, bool]:
    data = path.read_bytes()
    truncated = len(data) > _MAX_SUPPORT_LOG_BYTES
    if truncated:
        data = data[-_MAX_SUPPORT_LOG_BYTES:]
    return data.decode("utf-8", errors="replace"), truncated


def _support_log_paths(root: Path) -> list[Path]:
    logs_dir = root / "logs"
    if not logs_dir.is_dir():
        return []
    fixed = [
        logs_dir / "startup.log",
        logs_dir / "startup_prerequisites.log",
        logs_dir / "startup_events.jsonl",
    ]
    recent_runtime = sorted(
        logs_dir.glob("runtime_*.log"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:2]
    recent_crashes = sorted(
        logs_dir.glob("crash_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:3]
    seen: set[Path] = set()
    selected: list[Path] = []
    for path in [*fixed, *recent_runtime, *recent_crashes]:
        if path.is_file() and path not in seen:
            seen.add(path)
            selected.append(path)
    return selected


def support_bundle_filename() -> str:
    return f"Koto_Support_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"


def build_startup_support_bundle(
    app_root: Path | str,
    *,
    bundle_dir: Path | str | None = None,
    port: int | None = None,
) -> bytes:
    """Build an in-memory, bounded, redacted startup support archive."""
    root = Path(app_root).resolve()
    diagnostics = run_startup_diagnostics(
        root,
        bundle_dir=bundle_dir,
        port=port,
        include_import_check=not getattr(sys, "frozen", False),
    )
    metadata = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "diagnostic_status": diagnostics.get("status"),
    }
    manifest: dict[str, Any] = {
        "included_logs": [],
        "excluded": ["config", "chats", "workspace"],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "diagnostics.json",
            redact_support_text(
                json.dumps(diagnostics, ensure_ascii=False, indent=2), app_root=root
            ),
        )
        archive.writestr(
            "system.json", json.dumps(metadata, ensure_ascii=False, indent=2)
        )
        for path in _support_log_paths(root):
            content, truncated = _read_log_tail(path)
            archive_name = f"logs/{path.name}"
            archive.writestr(archive_name, redact_support_text(content, app_root=root))
            manifest["included_logs"].append(
                {"name": archive_name, "tail_truncated": truncated}
            )
        archive.writestr(
            "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
        )
    return output.getvalue()


def _source_shadowing_extensions(root: Path) -> list[Path]:
    """Find in-place Cython outputs that override sibling source modules."""
    artifacts: list[Path] = []
    for base in (root / "app", root / "web", root / "src", root / "launcher"):
        if not base.is_dir():
            continue
        for extension in base.rglob("*.pyd"):
            stem = extension.name.split(".cp", 1)[0]
            if stem and (extension.parent / f"{stem}.py").is_file():
                artifacts.append(extension)
    return artifacts


def remove_source_shadowing_extensions(
    root: Path,
) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Remove in-place compiled artifacts and report files that remain locked.

    This is intentionally separate from ``run_startup_diagnostics``: diagnostics
    never mutate the installation, while callers can opt into this cleanup after
    all source-mode Koto processes have stopped.
    """
    removed: list[Path] = []
    blocked: list[tuple[Path, str]] = []
    for artifact in _source_shadowing_extensions(root):
        try:
            artifact.unlink()
            removed.append(artifact)
        except OSError as exc:
            blocked.append((artifact, str(exc)))
    return removed, blocked


def _http_health(port: int) -> bool:
    opener = build_opener(ProxyHandler({"http": None, "https": None}))
    request = Request(f"http://127.0.0.1:{port}/api/health", method="GET")
    try:
        with opener.open(request, timeout=0.8) as response:
            return int(response.status) == 200
    except OSError:
        return False


def _port_state(port: int) -> str:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return "in_use"
    except OSError:
        return "free"


def _check_web_app_import(root: Path) -> tuple[bool, str]:
    """Import the web app in a child process to avoid contaminating recovery."""
    env = os.environ.copy()
    env.setdefault("KOTO_AUTH_ENABLED", "false")
    env.setdefault("KOTO_DEPLOY_MODE", "local")
    env["KOTO_SKIP_BACKGROUND_RUNTIME"] = "1"
    command = (
        "from web.app import app, socketio; "
        "assert app is not None and socketio is not None; "
        "assert any(rule.rule == '/api/health' for rule in app.url_map.iter_rules())"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", command],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=25,
        )
    except subprocess.TimeoutExpired:
        return False, "web app import timed out after 25 seconds"

    if result.returncode == 0:
        return True, "Flask app, SocketIO, and health route imported successfully"

    output = (result.stderr or result.stdout or "unknown import failure").strip()
    return False, output[-800:]


def run_startup_diagnostics(
    app_root: Path | str,
    *,
    bundle_dir: Path | str | None = None,
    port: int | None = None,
    include_import_check: bool = True,
) -> dict[str, Any]:
    """Return structured, non-mutating startup diagnostics.

    ``level`` values are ``ok``, ``warning``, and ``error``.  Only errors
    block a restart attempt; warnings describe optional or degraded features.
    """
    root = Path(app_root).resolve()
    frozen = bool(getattr(sys, "frozen", False))
    resources = Path(bundle_dir).resolve() if bundle_dir is not None else root
    checks: list[dict[str, str]] = []

    critical_files = _FROZEN_CRITICAL_FILES if frozen else _SOURCE_CRITICAL_FILES
    critical_root = resources if frozen else root
    for relative in critical_files:
        path = critical_root / relative
        if path.is_file():
            checks.append(_check(relative, "ok", "found"))
        else:
            checks.append(
                _check(
                    relative,
                    "error",
                    "missing",
                    action=(
                        "reinstall Koto from a verified release package"
                        if frozen
                        else "restore this file from the source checkout"
                    ),
                )
            )

    for directory in ("logs", "chats", "workspace", "config"):
        path = root / directory
        if path.is_dir() and os.access(path, os.W_OK):
            checks.append(
                _check(f"{directory} directory", "ok", "available and writable")
            )
        elif path.exists():
            checks.append(
                _check(
                    f"{directory} directory",
                    "error",
                    "not writable",
                    action="check folder permissions",
                )
            )
        else:
            checks.append(
                _check(
                    f"{directory} directory", "warning", "will be created at startup"
                )
            )

    checks.append(
        _check(
            "Python runtime",
            "ok" if sys.version_info >= (3, 10) else "error",
            f"{sys.executable} ({sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro})",
            action="use Python 3.10 or newer" if sys.version_info < (3, 10) else "",
        )
    )

    for module, label in _REQUIRED_MODULES.items():
        checks.append(
            _check(
                label,
                "ok" if _module_exists(module) else "error",
                (
                    "available"
                    if _module_exists(module)
                    else f"missing Python module: {module}"
                ),
                action=(
                    "reinstall Koto from a verified release package"
                    if frozen
                    else "pip install -r config/requirements.txt"
                ),
            )
        )

    for module in _COMPATIBILITY_MODULES:
        checks.append(
            _check(
                module,
                "ok" if _module_exists(module) else "error",
                (
                    "compatibility bridge available"
                    if _module_exists(module)
                    else "missing compatibility bridge"
                ),
                action="restore the web compatibility shim",
            )
        )

    if not getattr(sys, "frozen", False):
        shadowing_extensions = _source_shadowing_extensions(root)
        if shadowing_extensions:
            checks.append(
                _check(
                    "compiled source shadowing",
                    "error",
                    f"{len(shadowing_extensions)} in-place .pyd files override sibling .py source files",
                    action="stop running source instances, remove stale .pyd artifacts, then restart",
                )
            )

    for module, message in _OPTIONAL_MODULES.items():
        if not _module_exists(module):
            checks.append(_check(module, "warning", message))

    app_file = resources / "web" / "app.py"
    if app_file.is_file():
        try:
            compile(app_file.read_text(encoding="utf-8-sig"), str(app_file), "exec")
            checks.append(_check("web/app.py syntax", "ok", "syntax check passed"))
        except (OSError, SyntaxError, UnicodeError) as exc:
            checks.append(
                _check(
                    "web/app.py syntax",
                    "error",
                    str(exc),
                    action="fix the reported source line",
                )
            )

    if include_import_check and frozen:
        checks.append(
            _check(
                "web application import",
                "warning",
                "separate import probe is skipped inside the packaged executable",
                action="inspect logs/startup.log for the captured packaged import error",
            )
        )
    elif include_import_check and app_file.is_file():
        imported, detail = _check_web_app_import(root)
        checks.append(
            _check(
                "web application import",
                "ok" if imported else "error",
                detail,
                action=(
                    "inspect the first missing module or import error above"
                    if not imported
                    else ""
                ),
            )
        )

    if port is not None:
        state = _port_state(port)
        if state == "free":
            checks.append(_check(f"port {port}", "ok", "available"))
        elif _http_health(port):
            checks.append(
                _check(f"port {port}", "ok", "occupied by a healthy Koto backend")
            )
        else:
            checks.append(
                _check(
                    f"port {port}",
                    "warning",
                    "occupied but no healthy Koto backend responded",
                    action="close the stale process or use a fallback port",
                )
            )

    errors = sum(item["level"] == "error" for item in checks)
    warnings = sum(item["level"] == "warning" for item in checks)
    status = "blocked" if errors else "attention" if warnings else "ready"
    return {
        "status": status,
        "summary": f"{errors} errors, {warnings} warnings, {len(checks) - errors - warnings} checks passed",
        "can_restart": errors == 0,
        "checks": checks,
        "generated_at": int(time.time()),
    }
