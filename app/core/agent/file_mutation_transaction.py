"""Crash-recoverable transaction boundary for deterministic file mutations."""

from __future__ import annotations

import logging
import os
import re
import shutil

from app.core.agent.file_task_artifact_transaction import resolved_write_path
from app.core.config.settings_store import settings_file_lock

logger = logging.getLogger(__name__)


class FileMutationTransaction:
    """Rollback one file target and recover an interrupted previous mutation."""

    def __init__(self, target_path: str, *, run_id: str = "") -> None:
        self.target = resolved_write_path(target_path)
        token = re.sub(r"[^A-Za-z0-9_-]+", "_", run_id or "run")[:48] or "run"
        self.backup = self.target.with_name(
            f".{self.target.stem}.{token}.koto-rollback{self.target.suffix}"
        )
        self.preexisting = self.target.is_file()
        self._active = False
        self._lock_context = None

    def begin(self) -> "FileMutationTransaction":
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self._lock_context = settings_file_lock(self.target, timeout=30.0)
        self._lock_context.__enter__()
        try:
            self._recover_stale_backup()
            self.preexisting = self.target.is_file()
            if self.preexisting:
                shutil.copy2(self.target, self.backup)
            self._active = True
            return self
        except BaseException:
            self._release_lock()
            raise

    def commit(self) -> None:
        if not self._active:
            return
        try:
            self.backup.unlink(missing_ok=True)
        finally:
            self._active = False
            self._release_lock()

    def rollback(self) -> None:
        if not self._active:
            return
        try:
            if self.preexisting and self.backup.is_file():
                os.replace(self.backup, self.target)
            elif not self.preexisting and self.target.is_file():
                self.target.unlink()
        finally:
            self.backup.unlink(missing_ok=True)
            self._active = False
            self._release_lock()

    def _release_lock(self) -> None:
        context = self._lock_context
        self._lock_context = None
        if context is not None:
            context.__exit__(None, None, None)

    def _recover_stale_backup(self) -> None:
        pattern = f".{self.target.stem}.*.koto-rollback{self.target.suffix}"
        stale = sorted(
            self.target.parent.glob(pattern),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if not stale:
            return
        newest, *older = stale
        os.replace(newest, self.target)
        for path in older:
            path.unlink(missing_ok=True)
        logger.warning("recovered interrupted file mutation for %s", self.target)


__all__ = ["FileMutationTransaction"]
