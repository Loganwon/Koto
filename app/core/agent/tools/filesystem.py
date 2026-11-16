"""Domain module - Filesystem tools."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from app.core.agent.toolkits.foundation.docx_minimal import (
    _plain_text_to_docx_paragraphs,
)
from app.core.agent.toolkits.foundation.office_create import (
    create_docx_file as _office_create_docx_file,
)
from app.core.agent.toolkits.foundation.office_create import (
    create_pptx_file as _office_create_pptx_file,
)
from app.core.agent.toolkits.foundation.office_create import (
    create_xlsx_file as _office_create_xlsx_file,
)
from app.core.agent.toolkits.foundation.office_create import (
    plain_text_to_pptx_slides as _office_plain_text_to_pptx_slides,
)
from app.core.agent.toolkits.foundation.pptx_layout import _pptx_text_lines

from ._internal_backup import (
    _ensure_existing_file_writable,
    _nonwritable_target_message,
    _nonwritable_target_next_step,
)
from ._internal_fs import (
    _file_service,
    _get_workspace_root,
    _resolve_path,
    _result_path,
    _safe_resolve,
)
from ._internal_results import _blocked_write_result, _file_task_diff, _success_result
from ._internal_tempfile import (
    _save_docx_via_temp_file,
    _save_pptx_via_temp_file,
    _save_workbook_via_temp_file,
)
from .docx_write import _write_docx_content_without_python_docx  # noqa: F401


def list_workspace_files(path: str = "", recursive: bool = False) -> str:
    """List files in workspace directory. Returns JSON array of file info."""
    root = _get_workspace_root()
    target = _safe_resolve(path) if path else root
    if target is None or not os.path.isdir(target):
        return json.dumps({"error": f"Directory not found: {path}"}, ensure_ascii=False)

    entries = []
    try:
        if recursive:
            for dirpath, dirnames, filenames in os.walk(target):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for fname in filenames:
                    if fname.startswith("."):
                        continue
                    fpath = os.path.join(dirpath, fname)
                    rel = os.path.relpath(fpath, root).replace("\\", "/")
                    try:
                        st = os.stat(fpath)
                        entries.append({"name": rel, "size": st.st_size})
                    except OSError:
                        pass
                    if len(entries) >= 300:
                        break
        else:
            for item in sorted(os.listdir(target)):
                if item.startswith("."):
                    continue
                fpath = os.path.join(target, item)
                rel = os.path.relpath(fpath, root).replace("\\", "/")
                is_dir = os.path.isdir(fpath)
                entries.append(
                    {
                        "name": rel,
                        "type": "dir" if is_dir else "file",
                        "size": 0 if is_dir else os.path.getsize(fpath),
                    }
                )
    except PermissionError:
        return json.dumps({"error": "Permission denied"}, ensure_ascii=False)

    return json.dumps(entries, ensure_ascii=False)


def open_file_in_editor(path: str) -> str:
    """Open a file in the frontend editor so the user can view it.
    Use this when the user wants to open, view, or navigate to a file
    — NOT for reading content. The file will be brought into focus in the UI.
    """
    resolved = _resolve_path(path)
    if not resolved or not os.path.isfile(resolved):
        return json.dumps({"error": f"File not found: {path}"}, ensure_ascii=False)
    fname = os.path.basename(resolved)
    root = _get_workspace_root()
    rel = os.path.relpath(resolved, root).replace("\\", "/") if root else resolved
    return _success_result(
        rel,
        operation="open_file",
        summary=f"已打开 {fname}",
        file_type=Path(resolved).suffix.lstrip(".").lower(),
        change_type="open",
        focus=True,
    )


def copy_file(source: str, destination: str) -> str:
    """Copy a file within the workspace."""
    src = _resolve_path(source)
    if not src:
        return json.dumps({"error": f"Source not found: {source}"}, ensure_ascii=False)
    dst = _safe_resolve(destination)
    if not dst:
        return json.dumps(
            {"error": f"Invalid destination: {destination}"}, ensure_ascii=False
        )
    try:
        write_warning = (
            _ensure_existing_file_writable(dst) if os.path.exists(dst) else ""
        )
        result = _file_service().copy_file(src, dst, overwrite=True)
        if not result.get("success"):
            error_text = str(result.get("error") or "复制失败")
            if (
                any(token in error_text.lower() for token in ("permission", "denied"))
                or "权限" in error_text
            ):
                return _blocked_write_result(
                    _result_path(destination, dst),
                    summary=error_text,
                    suggested_next_step=_nonwritable_target_next_step(dst),
                    operation="copy_file",
                    file_type=Path(dst).suffix.lstrip(".").lower(),
                )
            return json.dumps({"error": error_text}, ensure_ascii=False)
        copied_path = str(result.get("destination") or dst)
        return _success_result(
            _result_path(destination, copied_path),
            operation="copy_file",
            summary=f"已复制文件到 {os.path.basename(copied_path)}",
            change_type="create",
            file_type=Path(copied_path).suffix.lstrip(".").lower(),
            focus=True,
            warning=write_warning,
        )
    except PermissionError as exc:
        return _blocked_write_result(
            _result_path(destination, dst),
            summary=str(exc).strip() or _nonwritable_target_message(dst),
            suggested_next_step=_nonwritable_target_next_step(dst),
            operation="copy_file",
            file_type=Path(dst).suffix.lstrip(".").lower(),
        )
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def _create_docx_file(path: str, resolved: str, content: str) -> str:
    return _office_create_docx_file(
        path,
        resolved,
        content,
        plain_text_to_paragraphs=_plain_text_to_docx_paragraphs,
        save_document=_save_docx_via_temp_file,
        fallback_writer=_write_docx_content_without_python_docx,
        success_result=_success_result,
        result_path=_result_path,
        file_task_diff=_file_task_diff,
    )


def _create_xlsx_file(path: str, resolved: str, content: str) -> str:
    return _office_create_xlsx_file(
        path,
        resolved,
        content,
        save_workbook=_save_workbook_via_temp_file,
        success_result=_success_result,
        result_path=_result_path,
        file_task_diff=_file_task_diff,
    )


def _plain_text_to_pptx_slides(content: str) -> List[Dict[str, Any]]:
    return _office_plain_text_to_pptx_slides(content)


def _create_pptx_file(path: str, resolved: str, content: str) -> str:
    return _office_create_pptx_file(
        path,
        resolved,
        content,
        text_lines=_pptx_text_lines,
        save_presentation=_save_pptx_via_temp_file,
        success_result=_success_result,
        result_path=_result_path,
    )


def create_file(path: str, content: str = "") -> str:
    """Create a new file in the workspace.

    Office targets are created as real package files and emit the same write
    metrics as their specialized tools, so task quality gates can verify them.
    """
    resolved = _safe_resolve(path)
    if not resolved:
        return json.dumps({"error": f"Invalid path: {path}"}, ensure_ascii=False)
    if os.path.exists(resolved):
        return json.dumps({"error": "File already exists"}, ensure_ascii=False)
    try:
        suffix = Path(resolved).suffix.lower()
        if suffix in {".docx", ".doc"}:
            return _create_docx_file(path, resolved, content)
        if suffix in {".xlsx", ".xlsm"}:
            return _create_xlsx_file(path, resolved, content)
        if suffix in {".pptx", ".ppt"}:
            return _create_pptx_file(path, resolved, content)
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)
        return _success_result(
            _result_path(path, resolved),
            operation="create_file",
            summary=f"已创建文件 {os.path.basename(resolved)}",
            change_type="create",
            preview=content,
            focus=True,
        )
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
