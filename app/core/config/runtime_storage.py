"""Canonical locations and one-time migration helpers for mutable runtime data."""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
from contextlib import closing
from pathlib import Path
from typing import Callable, Iterable

logger = logging.getLogger(__name__)

_migration_lock = threading.RLock()


def project_root() -> Path:
    """Return the writable application root in source and frozen builds."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def runtime_data_dir() -> Path:
    configured = os.environ.get("KOTO_RUNTIME_DATA_DIR", "").strip()
    return Path(configured).expanduser() if configured else project_root() / "data"


def runtime_data_path(*parts: str, env_var: str | None = None) -> Path:
    if env_var:
        configured = os.environ.get(env_var, "").strip()
        if configured:
            return Path(configured).expanduser()
    return runtime_data_dir().joinpath(*parts)


def runtime_database_path(filename: str) -> Path:
    configured = os.environ.get("KOTO_DB_DIR", "").strip()
    base = Path(configured).expanduser() if configured else runtime_data_dir() / "db"
    return base / filename


def runtime_secret_path(filename: str, *, env_var: str | None = None) -> Path:
    target = runtime_data_path("secrets", filename, env_var=env_var)
    if env_var and os.environ.get(env_var, "").strip():
        return target
    return migrate_legacy_file(
        target,
        legacy_paths=(legacy_config_path(filename),),
    )


def load_or_create_secret(
    path: str | os.PathLike[str], factory: Callable[[], str]
) -> str:
    """Return one stable local secret and persist new files with owner-only mode."""
    target = Path(path).expanduser()
    with _migration_lock:
        try:
            stored = target.read_text(encoding="utf-8").strip()
        except OSError:
            stored = ""
        if stored:
            return stored

        generated = str(factory()).strip()
        if not generated:
            raise ValueError("secret factory returned an empty value")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
        )
        temp = Path(temp_name)
        try:
            try:
                os.chmod(temp, 0o600)
            except OSError:
                pass
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = -1
                handle.write(generated)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)
            return generated
        except BaseException:
            if fd >= 0:
                os.close(fd)
            temp.unlink(missing_ok=True)
            raise


def legacy_config_path(*parts: str) -> Path:
    return project_root().joinpath("config", *parts)


def prepare_runtime_database(
    target: str | os.PathLike[str],
    *,
    legacy_paths: Iterable[str | os.PathLike[str]] = (),
) -> Path:
    """Copy a legacy SQLite database once, using SQLite's consistent backup API.

    The source is never modified. A temporary database is atomically promoted only
    after backup succeeds, so an interrupted upgrade cannot replace valid data.
    """
    destination = Path(target).expanduser()
    if destination.exists():
        return destination

    with _migration_lock:
        if destination.exists():
            return destination
        source = next(
            (
                Path(candidate).expanduser()
                for candidate in legacy_paths
                if Path(candidate).expanduser().is_file()
            ),
            None,
        )
        if source is None:
            return destination

        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            dir=str(destination.parent),
            prefix=f".{destination.name}.",
            suffix=".migrating",
        )
        os.close(fd)
        temp = Path(temp_name)
        try:
            with closing(sqlite3.connect(str(source))) as source_conn:
                with closing(sqlite3.connect(str(temp))) as destination_conn:
                    source_conn.backup(destination_conn)
            os.replace(temp, destination)
            logger.info("Migrated runtime database %s -> %s", source, destination)
        except Exception:
            temp.unlink(missing_ok=True)
            logger.warning(
                "Could not migrate runtime database %s -> %s; legacy data was left intact",
                source,
                destination,
                exc_info=True,
            )
    return destination


def migrate_legacy_file(
    target: str | os.PathLike[str],
    *,
    legacy_paths: Iterable[str | os.PathLike[str]] = (),
) -> Path:
    """Copy a legacy state file once without ever mutating the old copy."""
    destination = Path(target).expanduser()
    if destination.exists():
        return destination
    with _migration_lock:
        if destination.exists():
            return destination
        source = next(
            (
                Path(candidate).expanduser()
                for candidate in legacy_paths
                if Path(candidate).expanduser().is_file()
            ),
            None,
        )
        if source is None:
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            dir=str(destination.parent),
            prefix=f".{destination.name}.",
            suffix=".migrating",
        )
        os.close(fd)
        temp = Path(temp_name)
        try:
            shutil.copyfile(source, temp)
            os.replace(temp, destination)
            logger.info("Migrated runtime file %s -> %s", source, destination)
        except Exception:
            temp.unlink(missing_ok=True)
            logger.warning(
                "Could not migrate runtime file %s -> %s; legacy data was left intact",
                source,
                destination,
                exc_info=True,
            )
    return destination


def migrate_legacy_directory(
    target: str | os.PathLike[str],
    *,
    legacy_paths: Iterable[str | os.PathLike[str]] = (),
) -> Path:
    """Copy a legacy runtime directory once and atomically publish the copy."""
    destination = Path(target).expanduser()
    if destination.exists():
        return destination
    with _migration_lock:
        if destination.exists():
            return destination
        source = next(
            (
                Path(candidate).expanduser()
                for candidate in legacy_paths
                if Path(candidate).expanduser().is_dir()
            ),
            None,
        )
        if source is None:
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = Path(
            tempfile.mkdtemp(
                dir=str(destination.parent),
                prefix=f".{destination.name}.",
                suffix=".migrating",
            )
        )
        try:
            shutil.copytree(source, temp, dirs_exist_ok=True)
            os.replace(temp, destination)
            logger.info("Migrated runtime directory %s -> %s", source, destination)
        except Exception:
            shutil.rmtree(temp, ignore_errors=True)
            logger.warning(
                "Could not migrate runtime directory %s -> %s; legacy data was left intact",
                source,
                destination,
                exc_info=True,
            )
    return destination


__all__ = [
    "legacy_config_path",
    "load_or_create_secret",
    "migrate_legacy_directory",
    "migrate_legacy_file",
    "prepare_runtime_database",
    "project_root",
    "runtime_data_dir",
    "runtime_data_path",
    "runtime_database_path",
    "runtime_secret_path",
]
