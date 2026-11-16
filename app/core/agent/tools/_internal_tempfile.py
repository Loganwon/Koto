"""Internal helpers: temporary file saving."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from ._internal_backup import (  # noqa: F401
    _clear_readonly_attribute,
    _nonwritable_target_message,
)


def _save_via_temp_file(save_func: Any, target_path: str, *, suffix: str) -> None:
    target = str(target_path or "").strip()
    if not target:
        raise ValueError("target_path is required")

    directory = os.path.dirname(target) or os.getcwd()
    temp_handle = tempfile.NamedTemporaryFile(
        delete=False, suffix=suffix or ".tmp", dir=directory
    )
    temp_path = temp_handle.name
    temp_handle.close()
    try:
        save_func(temp_path)
        if os.path.exists(target):
            _clear_readonly_attribute(target)
        try:
            os.replace(temp_path, target)
        except PermissionError as exc:
            raise PermissionError(_nonwritable_target_message(target)) from exc
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _save_docx_via_temp_file(document: Any, target_path: str) -> None:
    _save_via_temp_file(document.save, target_path, suffix=".docx")


def _write_bytes_via_temp_file(data: bytes, target_path: str, *, suffix: str) -> None:
    def _write_temp(temp_path: str) -> None:
        with open(temp_path, "wb") as handle:
            handle.write(data)

    _save_via_temp_file(_write_temp, target_path, suffix=suffix)


def _save_workbook_via_temp_file(workbook: Any, target_path: str) -> None:
    suffix = Path(str(target_path or "")).suffix or ".xlsx"
    _save_via_temp_file(workbook.save, target_path, suffix=suffix)


def _save_pptx_via_temp_file(presentation: Any, target_path: str) -> None:
    suffix = Path(str(target_path or "")).suffix or ".pptx"
    _save_via_temp_file(presentation.save, target_path, suffix=suffix)
