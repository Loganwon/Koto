# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import datetime
import hashlib
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from app.core.file_assistant.docx_preservation import (
    DocxStructureLossError,
    assert_docx_structure_preserved,
)

logger = logging.getLogger(__name__)

PathGuard = Callable[[Path], bool]


class AutoSavePermissionError(PermissionError):
    """Raised when an auto-save target fails path-safety checks."""


class AutoSaveConflictError(RuntimeError):
    """The source changed since the editor read its expected version."""

    def __init__(self, current_sha256: str) -> None:
        super().__init__("原文件已被其他操作修改，请保留当前编辑稿并重新核对后保存。")
        self.current_sha256 = current_sha256


@dataclass(frozen=True)
class AutoSaveResult:
    saved_at: str
    src_written: bool
    tmp_path: Path
    src_path: Path | None = None
    source_sha256: str = ""
    previous_source_sha256: str = ""
    tmp_sha256: str = ""
    verified: bool = False


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
        expected_source_sha256: str | None = None,
    ) -> AutoSaveResult:
        tmp_root = Path(tmp_dir)
        tmp_path = tmp_root / f"{file_id}{suffix}"
        expected = None
        if expected_source_sha256 is not None:
            expected = str(expected_source_sha256).strip().lower()
            if expected and not re.fullmatch(r"[0-9a-f]{64}", expected):
                raise ValueError("expected_source_sha256 必须是原文件的 SHA-256。")
        tmp_root.mkdir(parents=True, exist_ok=True)
        from app.core.config.settings_store import settings_file_lock

        # Uploaded files can use the session copy itself as their workspace
        # source. Stage the draft separately so writing the cache cannot change
        # that source before its optimistic-version check.
        candidate = Path(str(ws_source_path)) if ws_source_path else None
        if candidate is not None and not candidate.is_absolute():
            candidate = Path(workspace_dir) / candidate
        same_target = (
            candidate is not None and candidate.resolve() == tmp_path.resolve()
        )
        cache_source = (
            tmp_path.read_bytes()
            if candidate is None and suffix.lower() == ".docx" and tmp_path.is_file()
            else None
        )
        draft_path = (
            tmp_root / f"{file_id}.koto-editor-draft{suffix}"
            if same_target or cache_source is not None
            else tmp_path
        )
        with settings_file_lock(draft_path, timeout=30.0):
            self._atomic_write(draft_path, raw_bytes)
        digest = hashlib.sha256(raw_bytes).hexdigest()
        if cache_source is not None:
            assert_docx_structure_preserved(cache_source, raw_bytes)
            with settings_file_lock(tmp_path, timeout=30.0):
                self._atomic_write(tmp_path, raw_bytes)
            draft_path.unlink(missing_ok=True)
        logger.info(
            "[WorkspaceAssistant] auto_save tmp -> %s (%d bytes)",
            tmp_path,
            len(raw_bytes),
        )

        src_written = False
        src_path: Path | None = None
        previous_sha256 = ""
        source_verified = False
        allowed = {str(ext).lower() for ext in allowed_extensions}

        if (explicit or same_target) and ws_source_path:
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
                    from app.core.agent.file_mutation_transaction import (
                        FileMutationTransaction,
                    )

                    transaction = FileMutationTransaction(
                        str(src_path), run_id="editor-save"
                    )
                    transaction.begin()
                    try:
                        previous = src_path.read_bytes() if src_path.is_file() else None
                        previous_sha256 = (
                            hashlib.sha256(previous).hexdigest()
                            if previous is not None
                            else ""
                        )
                        if expected is not None and previous_sha256 != expected:
                            # No source mutation took place: release without rewriting it.
                            transaction.commit()
                            raise AutoSaveConflictError(previous_sha256)
                        if previous is not None and src_path.suffix.lower() == ".docx":
                            try:
                                assert_docx_structure_preserved(previous, raw_bytes)
                            except DocxStructureLossError:
                                transaction.commit()  # No source mutation occurred.
                                raise
                        if previous is not None and src_is_workspace_file and explicit:
                            self._write_version_snapshot(src_path, previous, suffix)
                        self._atomic_write(src_path, raw_bytes)
                        if hashlib.sha256(src_path.read_bytes()).hexdigest() != digest:
                            raise OSError("保存后读回内容与待保存内容不一致。")
                        transaction.commit()
                        src_written = bool(explicit)
                        source_verified = True
                    except BaseException:
                        transaction.rollback()
                        raise
                    logger.info(
                        "[WorkspaceAssistant] auto_save src -> %s (%d bytes)",
                        src_path,
                        len(raw_bytes),
                    )
                    if src_is_workspace_file and explicit:
                        self._sync_registry(src_path)
                        self._write_version_snapshot(src_path, raw_bytes, suffix)
                    if same_target:
                        draft_path.unlink(missing_ok=True)

        return AutoSaveResult(
            saved_at=datetime.datetime.now().strftime("%H:%M"),
            src_written=src_written,
            tmp_path=tmp_path,
            src_path=src_path if src_written else None,
            source_sha256=digest if source_verified else "",
            previous_source_sha256=previous_sha256,
            tmp_sha256=digest,
            verified=src_written,
        )

    @staticmethod
    def _atomic_write(target: Path, raw_bytes: bytes) -> None:
        """Publish fully flushed bytes from a temporary sibling on one volume."""
        staged: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{target.stem}.",
                suffix=".koto-save",
                dir=target.parent,
                delete=False,
            ) as stream:
                staged = Path(stream.name)
                stream.write(raw_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(staged, target)
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)

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
            registry.batch_register(
                [str(src_path)], source="editor", extract_content=False
            )
            logger.debug(
                "[WorkspaceAssistant] auto_save registry synced: %s", src_path.name
            )
        except Exception as exc:
            logger.debug(
                "[WorkspaceAssistant] auto_save registry sync skipped: %s", exc
            )

    @staticmethod
    def _write_version_snapshot(src_path: Path, raw_bytes: bytes, suffix: str) -> None:
        try:
            snap_dir = src_path.parent / ".koto_versions" / src_path.stem
            snap_dir.mkdir(parents=True, exist_ok=True)
            ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            snap_path = snap_dir / f"{ts_str}{suffix}"
            snap_path.write_bytes(raw_bytes)
            snaps = sorted(snap_dir.glob(f"*{suffix}"))
            for old_snap in snaps[:-10]:
                old_snap.unlink(missing_ok=True)
            logger.debug("[WorkspaceAssistant] version snapshot: %s", snap_path.name)
        except Exception as exc:
            logger.debug("[WorkspaceAssistant] version snapshot failed: %s", exc)
