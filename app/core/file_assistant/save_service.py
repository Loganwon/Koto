# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

logger = logging.getLogger(__name__)

PathGuard = Callable[[Path], bool]


class AutoSavePermissionError(PermissionError):
    """Raised when an auto-save target fails path-safety checks."""


@dataclass(frozen=True)
class AutoSaveResult:
    saved_at: str
    src_written: bool
    tmp_path: Path
    src_path: Path | None = None


class AutoSavePersistenceService:
    """Persist auto-save bytes to session tmp storage and optional source files."""

    def persist(
        self,
        *,
        tmp_dir: str | Path,
        file_id: str,
        raw_bytes: bytes,
        suffix: str,
        explicit: bool,
        ws_source_path: str,
        workspace_dir: str | Path,
        allowed_extensions: Iterable[str],
        fs_guard: PathGuard,
    ) -> AutoSaveResult:
        tmp_root = Path(tmp_dir)
        tmp_path = tmp_root / f"{file_id}{suffix}"
        tmp_path.write_bytes(raw_bytes)
        logger.info(
            "[WorkspaceAssistant] auto_save tmp -> %s (%d bytes)",
            tmp_path,
            len(raw_bytes),
        )

        src_written = False
        src_path: Path | None = None
        allowed = {str(ext).lower() for ext in allowed_extensions}

        if explicit and ws_source_path:
            src_path, src_is_workspace_file = self._resolve_source_path(
                raw_path=ws_source_path,
                workspace_dir=workspace_dir,
                fs_guard=fs_guard,
            )

            if src_path and src_path.suffix.lower() in allowed:
                if src_is_workspace_file:
                    src_path.parent.mkdir(parents=True, exist_ok=True)
                elif not src_path.parent.exists():
                    logger.info(
                        "[WorkspaceAssistant] auto_save external parent missing, skip src write: %s",
                        src_path,
                    )
                    src_path = None

                if src_path is not None:
                    src_path.write_bytes(raw_bytes)
                    src_written = True
                    logger.info(
                        "[WorkspaceAssistant] auto_save src -> %s (%d bytes)",
                        src_path,
                        len(raw_bytes),
                    )
                    if src_is_workspace_file:
                        self._sync_registry(src_path)
                        self._write_version_snapshot(src_path, raw_bytes, suffix)

        return AutoSaveResult(
            saved_at=datetime.datetime.now().strftime("%H:%M"),
            src_written=src_written,
            tmp_path=tmp_path,
            src_path=src_path if src_written else None,
        )

    def _resolve_source_path(
        self,
        *,
        raw_path: str,
        workspace_dir: str | Path,
        fs_guard: PathGuard,
    ) -> tuple[Path | None, bool]:
        ws_root = Path(workspace_dir).resolve()
        requested_path = Path(str(raw_path).strip())

        if requested_path.is_absolute():
            src_path = requested_path.resolve()
            if not fs_guard(src_path):
                raise AutoSavePermissionError("路径不合法")
            try:
                src_path.relative_to(ws_root)
                return src_path, True
            except ValueError:
                return src_path, False

        src_path = ws_root.joinpath(requested_path).resolve()
        try:
            src_path.relative_to(ws_root)
        except ValueError as exc:
            raise AutoSavePermissionError("路径不合法") from exc
        return src_path, True

    @staticmethod
    def _sync_registry(src_path: Path) -> None:
        try:
            from app.core.file.file_registry import get_file_registry

            registry = get_file_registry()
            registry.batch_register([str(src_path)], source="editor", extract_content=False)
            logger.debug("[WorkspaceAssistant] auto_save registry synced: %s", src_path.name)
        except Exception as exc:
            logger.debug("[WorkspaceAssistant] auto_save registry sync skipped: %s", exc)

    @staticmethod
    def _write_version_snapshot(src_path: Path, raw_bytes: bytes, suffix: str) -> None:
        try:
            snap_dir = src_path.parent / ".koto_versions" / src_path.stem
            snap_dir.mkdir(parents=True, exist_ok=True)
            ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            snap_path = snap_dir / f"{ts_str}{suffix}"
            snap_path.write_bytes(raw_bytes)
            snaps = sorted(snap_dir.glob(f"*{suffix}"))
            for old_snap in snaps[:-10]:
                old_snap.unlink(missing_ok=True)
            logger.debug("[WorkspaceAssistant] version snapshot: %s", snap_path.name)
        except Exception as exc:
            logger.debug("[WorkspaceAssistant] version snapshot failed: %s", exc)
