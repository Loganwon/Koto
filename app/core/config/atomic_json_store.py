"""Crash-safe, cross-process JSON persistence for non-settings state."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from .settings_store import SettingsStoreError, settings_file_lock


class AtomicJsonStoreError(SettingsStoreError):
    pass


def _decode(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def load_json_document(
    path: str | os.PathLike[str],
    *,
    default: Any,
) -> Any:
    """Load JSON under a process lock and recover only from a valid backup."""
    target = Path(path)
    with settings_file_lock(target):
        if not target.exists():
            return copy.deepcopy(default)
        try:
            return _decode(target)
        except (OSError, ValueError, TypeError):
            backup = target.with_name(f"{target.name}.bak")
            try:
                recovered = _decode(backup)
            except (OSError, ValueError, TypeError) as backup_error:
                timestamp = time.strftime("%Y%m%d-%H%M%S")
                corrupt = target.with_name(f"{target.name}.corrupt-{timestamp}")
                try:
                    os.replace(target, corrupt)
                except OSError:
                    pass
                raise AtomicJsonStoreError(
                    f"JSON state is corrupt and has no valid backup: {target}"
                ) from backup_error
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            corrupt = target.with_name(f"{target.name}.corrupt-{timestamp}")
            try:
                os.replace(target, corrupt)
            except OSError:
                pass
            _atomic_write(target, recovered)
            return recovered


def save_json_document(path: str | os.PathLike[str], payload: Any) -> None:
    target = Path(path)
    with settings_file_lock(target):
        _atomic_write(target, payload)
        _atomic_write(target.with_name(f"{target.name}.bak"), payload)


def update_json_document(
    path: str | os.PathLike[str],
    updater: Callable[[Any], Any],
    *,
    default: Any,
) -> Any:
    """Run a locked read-modify-write transaction."""
    target = Path(path)
    with settings_file_lock(target):
        if target.exists():
            try:
                current = _decode(target)
            except (OSError, ValueError, TypeError) as exc:
                raise AtomicJsonStoreError(
                    f"cannot update corrupt JSON: {target}"
                ) from exc
        else:
            current = copy.deepcopy(default)
        updated = updater(copy.deepcopy(current))
        _atomic_write(target, updated)
        _atomic_write(target.with_name(f"{target.name}.bak"), updated)
        return copy.deepcopy(updated)


__all__ = [
    "AtomicJsonStoreError",
    "load_json_document",
    "save_json_document",
    "update_json_document",
]
