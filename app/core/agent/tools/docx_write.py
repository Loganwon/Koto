"""Domain module - DOCX write tools."""

from __future__ import annotations

import json
import os
from typing import Any, List

from app.core.agent.toolkits.foundation.docx_minimal import (
    _coerce_docx_paragraphs_for_write,
    _minimal_docx_package_bytes,
    _normalize_docx_paragraphs,
)
from app.core.agent.toolkits.foundation.docx_style import (
    apply_docx_style as _apply_docx_style,
)

from ._internal_backup import (
    _best_effort_backup,
    _ensure_existing_file_writable,
    _nonwritable_target_message,
    _nonwritable_target_next_step,
)
from ._internal_fs import _resolve_path, _result_path
from ._internal_results import _blocked_write_result, _file_task_diff, _success_result
from ._internal_tempfile import _save_docx_via_temp_file, _write_bytes_via_temp_file
from ._internal_warnings import _merge_warnings


def _write_docx_content_without_python_docx(
    path: str, resolved: str, para_list: Any
) -> str:
    paragraphs = _normalize_docx_paragraphs(para_list)
    if not paragraphs:
        paragraphs = [{"text": "", "style": "Normal"}]
    file_exists = os.path.exists(resolved)
    backup_warning = _best_effort_backup(resolved) if file_exists else ""
    write_warning = _ensure_existing_file_writable(resolved) if file_exists else ""
    os.makedirs(os.path.dirname(resolved), exist_ok=True)
    docx_bytes = _minimal_docx_package_bytes(
        paragraphs, existing_path=resolved if file_exists else ""
    )
    _write_bytes_via_temp_file(docx_bytes, resolved, suffix=".docx")
    preview = "\n".join(str(p.get("text", "")) for p in paragraphs[:3])
    diff_items = [
        {
            "paragraph_index": index,
            "before": "",
            "after": str(item.get("text") or ""),
            "style": str(item.get("style") or ""),
        }
        for index, item in enumerate(paragraphs, start=1)
    ]
    return _success_result(
        _result_path(path, resolved),
        operation="write_docx_content",
        summary=f"已写入 {len(paragraphs)} 个段落到 Word 文档",
        file_type="docx",
        change_type="modify" if file_exists else "create",
        preview=preview,
        focus=True,
        summary_code="WRITE_OK" if file_exists else "CREATE_OK",
        diff=_file_task_diff("docx_paragraphs", diff_items),
        paragraphs_written=len(paragraphs),
        warning=_merge_warnings(
            backup_warning,
            write_warning,
            "python-docx 未安装，已使用基础 DOCX 写入兜底。",
        ),
    )


def write_docx_content(path: str, paragraphs: str = "[]") -> str:
    """Create a DOCX or append paragraphs to an existing DOCX.

    This function never replaces existing paragraphs. Use a targeted editor or
    a single precise python-docx operation for localized replacements.

    Args:
        path: Path to the DOCX file (will be created if not exists).
        paragraphs: JSON array of paragraph objects:
            [{"text": "...", "style": "Heading 1"}, {"text": "..."}]

    Returns: JSON with operation result.
    """
    resolved = _resolve_path(path, must_exist=False)
    if not resolved:
        return json.dumps({"error": f"无效路径: {path}"}, ensure_ascii=False)

    para_list = _coerce_docx_paragraphs_for_write(paragraphs)

    try:
        from docx import Document

        # Create or load document
        file_exists = os.path.exists(resolved)
        backup_warning = ""
        write_warning = ""
        if file_exists:
            doc = Document(resolved)
            original_paragraph_count = len(doc.paragraphs)
            # Backup
            backup_warning = _best_effort_backup(resolved)
            write_warning = _ensure_existing_file_writable(resolved)
        else:
            doc = Document()
            original_paragraph_count = 0
            os.makedirs(os.path.dirname(resolved), exist_ok=True)

        if not para_list:
            para_list = [{"text": "", "style": "Normal"}]

        style_warnings: List[str] = []
        for p in para_list:
            text = p.get("text", "")
            style = p.get("style")
            para = doc.add_paragraph(text)
            if style:
                style_warnings.append(_apply_docx_style(para, style))

        _save_docx_via_temp_file(doc, resolved)
        preview = "\n".join(str(p.get("text", "")) for p in para_list[:3])
        diff_items = [
            {
                "paragraph_index": original_paragraph_count + index,
                "before": "",
                "after": str(item.get("text", "")),
                "style": str(item.get("style") or ""),
            }
            for index, item in enumerate(para_list, start=1)
        ]
        return _success_result(
            _result_path(path, resolved),
            operation="write_docx_content",
            summary=f"已写入 {len(para_list)} 个段落到 Word 文档",
            file_type="docx",
            change_type="modify" if file_exists else "create",
            preview=preview,
            focus=True,
            summary_code="WRITE_OK" if file_exists else "CREATE_OK",
            diff=_file_task_diff("docx_paragraphs", diff_items),
            paragraphs_written=len(para_list),
            warning=_merge_warnings(backup_warning, write_warning, *style_warnings),
        )
    except ImportError:
        try:
            return _write_docx_content_without_python_docx(path, resolved, para_list)
        except PermissionError as exc:
            preview = "\n".join(
                str(p.get("text", ""))
                for p in _normalize_docx_paragraphs(para_list)[:3]
            )
            return _blocked_write_result(
                _result_path(path, resolved),
                summary=str(exc).strip() or _nonwritable_target_message(resolved),
                suggested_next_step=_nonwritable_target_next_step(resolved),
                operation="write_docx_content",
                file_type="docx",
                preview=preview,
                paragraphs_written=len(_normalize_docx_paragraphs(para_list)),
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
    except PermissionError as exc:
        preview = "\n".join(str(p.get("text", "")) for p in para_list[:3])
        return _blocked_write_result(
            _result_path(path, resolved),
            summary=str(exc).strip() or _nonwritable_target_message(resolved),
            suggested_next_step=_nonwritable_target_next_step(resolved),
            operation="write_docx_content",
            file_type="docx",
            preview=preview,
            paragraphs_written=len(para_list),
        )
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
