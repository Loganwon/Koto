# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Temporary file storage helpers for workflow inputs and outputs."""

from __future__ import annotations

import logging
import re
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

logger = logging.getLogger(__name__)

WORKFLOW_TEMP_PREFIX = "koto_wf_"


class WorkflowUploadFile(Protocol):
    filename: str

    def save(self, dst: str) -> None:
        ...


@dataclass(frozen=True)
class WorkflowUploadResult:
    session_id: str
    paths: list[str]


class WorkflowFileAccessError(ValueError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def workflow_temp_root() -> Path:
    return Path(tempfile.gettempdir()).resolve()


def workflow_upload_dir(session_id: str | None = None, *, temp_root: Path | None = None) -> Path:
    safe_session_id = _safe_session_id(session_id)
    return (temp_root or workflow_temp_root()) / f"{WORKFLOW_TEMP_PREFIX}{safe_session_id}"


def save_workflow_uploads(
    uploaded_files: Iterable[WorkflowUploadFile],
    *,
    session_id: str | None = None,
    temp_root: Path | None = None,
) -> WorkflowUploadResult:
    safe_session_id = _safe_session_id(session_id)
    target_dir = workflow_upload_dir(safe_session_id, temp_root=temp_root)
    target_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[str] = []
    for upload in uploaded_files:
        raw_filename = str(getattr(upload, "filename", "") or "")
        safe_name = Path(raw_filename).name
        if not safe_name:
            continue
        destination = target_dir / safe_name
        try:
            upload.save(str(destination))
            saved_paths.append(str(destination))
        except Exception as exc:
            logger.warning("[WorkflowFileStore] Failed to save upload %s: %s", safe_name, exc)

    return WorkflowUploadResult(session_id=safe_session_id, paths=saved_paths)


def validate_workflow_download_path(path: str, *, temp_root: Path | None = None) -> Path:
    raw_path = str(path or "").strip()
    if not raw_path:
        raise WorkflowFileAccessError("缺少 path 参数", 400)

    candidate = Path(raw_path)
    if not candidate.exists():
        raise WorkflowFileAccessError("文件不存在", 404)

    try:
        resolved = candidate.resolve()
        root = (temp_root or workflow_temp_root()).resolve()
    except Exception as exc:
        raise WorkflowFileAccessError("路径校验失败", 403) from exc

    if not _is_relative_to(resolved, root):
        raise WorkflowFileAccessError("无权访问该路径", 403)
    if len(resolved.parts) < 2 or not resolved.parent.name.startswith(WORKFLOW_TEMP_PREFIX):
        raise WorkflowFileAccessError("无权访问该路径", 403)
    if not resolved.is_file():
        raise WorkflowFileAccessError("文件不存在", 404)
    return resolved


def _safe_session_id(session_id: str | None) -> str:
    raw = str(session_id or "").strip()
    if not raw:
        return uuid.uuid4().hex[:8]
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("._-")
    return safe[:64] or uuid.uuid4().hex[:8]


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
