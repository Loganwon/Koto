"""Durable handoff for files opened from Windows Explorer.

Explorer may start Koto while another desktop instance already owns the window.
Small request files let that short-lived second process hand paths to the running
instance without opening a network listener or evaluating JavaScript off-thread.
"""

from __future__ import annotations

import itertools
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Iterable, Sequence

SUPPORTED_EXTERNAL_EXTENSIONS = frozenset({".docx", ".xlsx", ".pptx", ".pdf"})
DEFAULT_APPS_SETTINGS_URI = "ms-settings:defaultapps?registeredAppUser=Koto"
DEFAULT_APPS_SETTINGS_FALLBACK_URI = "ms-settings:defaultapps"
_MAX_PATHS_PER_REQUEST = 16
_MAX_REQUEST_BYTES = 64 * 1024
_MAX_REQUEST_FILES = 32
_STALE_REQUEST_SECONDS = 24 * 60 * 60
_STALE_TEMP_SECONDS = 5 * 60
_ENQUEUED_ENV = "KOTO_EXTERNAL_OPEN_ARGS_ENQUEUED"
_enqueue_lock = threading.Lock()
_consume_lock = threading.Lock()
_request_sequence = itertools.count()


def open_default_apps_settings() -> tuple[bool, str | None]:
    """Open Windows' user-controlled default-app picker for Koto."""
    if sys.platform != "win32":
        return False, "仅 Windows 桌面版支持默认应用设置"

    startfile = getattr(os, "startfile", None)
    if not callable(startfile):
        return False, "当前 Windows 运行环境无法打开系统设置"

    try:
        startfile(DEFAULT_APPS_SETTINGS_URI)
        return True, None
    except Exception:
        try:
            startfile(DEFAULT_APPS_SETTINGS_FALLBACK_URI)
            return True, None
        except Exception as exc:
            return False, str(exc)


def parse_external_open_paths(argv: Sequence[str]) -> list[str]:
    """Return existing, supported file arguments in stable de-duplicated order."""
    selected: list[str] = []
    seen: set[str] = set()
    for raw in argv:
        value = str(raw or "").strip().strip('"')
        if not value or value.startswith("-"):
            continue
        candidate = Path(value).expanduser()
        try:
            candidate = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if (
            not candidate.is_file()
            or candidate.suffix.lower() not in SUPPORTED_EXTERNAL_EXTENSIONS
        ):
            continue
        key = os.path.normcase(str(candidate))
        if key in seen:
            continue
        seen.add(key)
        selected.append(str(candidate))
        if len(selected) >= _MAX_PATHS_PER_REQUEST:
            break
    return selected


def _request_dir(app_root: Path | str) -> Path:
    return Path(app_root).resolve() / ".ipc" / "open_requests"


def enqueue_external_open_requests(app_root: Path | str, paths: Iterable[str]) -> bool:
    """Atomically enqueue validated paths for the owning desktop instance."""
    validated = parse_external_open_paths(list(paths))
    if not validated:
        return False
    request_dir = _request_dir(app_root)
    request_dir.mkdir(parents=True, exist_ok=True)
    # Windows wall-clock timestamps can repeat for roughly 15.6 ms. Without a
    # sequence component, rapid requests sharing a timestamp are ordered by
    # their random UUID and Explorer batch-open order becomes nondeterministic.
    # The v2 prefix also sorts all pre-upgrade numeric request names first, so
    # an already queued legacy request is never overtaken after an update.
    with _enqueue_lock:
        sequence = next(_request_sequence)
    request_name = (
        f"v2_{time.time_ns():020d}_{os.getpid():010d}_"
        f"{sequence:020d}_{uuid.uuid4().hex}.json"
    )
    target = request_dir / request_name
    temporary = target.with_suffix(".tmp")
    payload = {
        "schema_version": 1,
        "created_at": time.time(),
        "process_id": os.getpid(),
        "paths": validated,
    }
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(encoded) > _MAX_REQUEST_BYTES:
        return False
    try:
        temporary.write_bytes(encoded)
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return True


def enqueue_external_open_arguments(app_root: Path | str, argv: Sequence[str]) -> bool:
    """Enqueue process arguments once, before any desktop mutex short-circuit."""

    if os.environ.get(_ENQUEUED_ENV) == "1":
        return False
    paths = parse_external_open_paths(argv)
    if not paths or not enqueue_external_open_requests(app_root, paths):
        return False
    os.environ[_ENQUEUED_ENV] = "1"
    return True


def _validated_payload_paths(payload: object) -> list[str]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return []
    paths = payload.get("paths")
    if not isinstance(paths, list):
        return []
    return parse_external_open_paths(
        [str(path) for path in paths[:_MAX_PATHS_PER_REQUEST]]
    )


def _cleanup_abandoned_temporary_requests(request_dir: Path, now: float) -> None:
    """Remove only old partial writes; a live enqueue may own a recent file."""
    for temporary in request_dir.glob("*.tmp"):
        try:
            if now - temporary.stat().st_mtime > _STALE_TEMP_SECONDS:
                temporary.unlink(missing_ok=True)
        except OSError:
            pass


def consume_external_open_requests(app_root: Path | str) -> list[str]:
    """Consume pending requests once, rejecting stale, large, or malformed input."""
    request_dir = _request_dir(app_root)
    if not request_dir.is_dir():
        return []
    with _consume_lock:
        selected: list[str] = []
        seen: set[str] = set()
        now = time.time()
        _cleanup_abandoned_temporary_requests(request_dir, now)
        for request_path in sorted(request_dir.glob("*.json"))[:_MAX_REQUEST_FILES]:
            try:
                stat = request_path.stat()
                if (
                    stat.st_size > _MAX_REQUEST_BYTES
                    or now - stat.st_mtime > _STALE_REQUEST_SECONDS
                ):
                    continue
                payload = json.loads(request_path.read_text(encoding="utf-8"))
                for path in _validated_payload_paths(payload):
                    key = os.path.normcase(path)
                    if key not in seen:
                        seen.add(key)
                        selected.append(path)
            except (OSError, UnicodeError, json.JSONDecodeError):
                pass
            finally:
                try:
                    request_path.unlink(missing_ok=True)
                except OSError:
                    pass
        return selected
