# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Crash-safe, cross-process storage primitives for Koto user settings."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Mapping


class SettingsStoreError(RuntimeError):
    """Raised when the settings file cannot be locked or persisted safely."""


def deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deep copy where ``overlay`` wins over ``base``."""
    result = copy.deepcopy(dict(base))
    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent),
        suffix=".tmp",
        prefix=f".{path.name}.",
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(5):
            try:
                os.replace(tmp_path, path)
                break
            except OSError as exc:
                transient = isinstance(exc, PermissionError) or getattr(
                    exc, "winerror", None
                ) in {5, 32}
                if not transient or attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    except BaseException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


@contextmanager
def settings_file_lock(
    settings_path: str | os.PathLike[str],
    *,
    timeout: float = 12.0,
    stale_after: float = 10.0,
):
    """Serialize read-modify-write transactions across Koto processes.

    ``O_EXCL`` provides the cross-platform atomic claim. A token prevents one
    process from deleting a lock that was replaced by another process.
    """
    path = Path(settings_path)
    lock_path = path.with_name(f"{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    token = f"{os.getpid()}:{time.time_ns()}:{uuid.uuid4().hex}"
    deadline = time.monotonic() + timeout

    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="ascii") as handle:
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
            break
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
                if age > stale_after:
                    lock_path.unlink(missing_ok=True)
                    continue
            except OSError:
                continue
            if time.monotonic() >= deadline:
                raise SettingsStoreError(
                    f"Timed out waiting for settings lock: {lock_path}"
                )
            time.sleep(0.05)

    try:
        yield
    finally:
        try:
            if lock_path.read_text(encoding="ascii") == token:
                lock_path.unlink(missing_ok=True)
        except OSError:
            pass


def _load_recoverable_document_locked(path: Path) -> tuple[dict[str, Any], bool]:
    """Load the primary file, falling back to its last-known-good backup."""
    if not path.exists():
        return {}, False

    current = _read_json_dict(path)
    if current is not None:
        return current, False

    backup_path = path.with_name(f"{path.name}.bak")
    backup = _read_json_dict(backup_path)
    if backup is not None:
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        corrupt_path = path.with_name(f"{path.name}.corrupt-{timestamp}")
        try:
            os.replace(path, corrupt_path)
        except OSError:
            pass
        _atomic_write_json(path, backup)
        return backup, True

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    corrupt_path = path.with_name(f"{path.name}.corrupt-{timestamp}")
    try:
        os.replace(path, corrupt_path)
    except OSError:
        pass
    return {}, True


def _refresh_backup_best_effort(path: Path, payload: Mapping[str, Any]) -> None:
    try:
        _atomic_write_json(path.with_name(f"{path.name}.bak"), payload)
    except OSError:
        # The primary file is already durable. A backup failure must not make
        # the UI report that the user's setting was lost.
        pass


def load_settings_document(
    settings_path: str | os.PathLike[str],
    *,
    defaults: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Load settings under the inter-process lock and repair when necessary."""
    path = Path(settings_path)
    with settings_file_lock(path):
        current, recovered = _load_recoverable_document_locked(path)
        merged = deep_merge(defaults or {}, current)
        if recovered or not path.exists() or merged != current:
            _atomic_write_json(path, merged)
            _refresh_backup_best_effort(path, merged)
        return merged


def atomic_update_settings(
    settings_path: str | os.PathLike[str],
    patch: Mapping[str, Any],
    *,
    defaults: Mapping[str, Any] | None = None,
    replace_top_level: Iterable[str] = (),
) -> dict[str, Any]:
    """Atomically merge a settings patch without overwriting unrelated keys."""
    path = Path(settings_path)
    replace_keys = set(replace_top_level)
    with settings_file_lock(path):
        current, _recovered = _load_recoverable_document_locked(path)
        merged = deep_merge(defaults or {}, current)
        for key, value in patch.items():
            if key in replace_keys or not isinstance(value, Mapping):
                merged[key] = copy.deepcopy(value)
            else:
                existing = merged.get(key)
                merged[key] = deep_merge(
                    existing if isinstance(existing, Mapping) else {},
                    value,
                )
        _atomic_write_json(path, merged)
        _refresh_backup_best_effort(path, merged)
        return merged
