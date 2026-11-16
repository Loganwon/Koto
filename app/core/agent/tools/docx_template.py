"""Domain module - DOCX template tools."""

from __future__ import annotations

import json
import os
import shutil
from typing import Any, Dict, List

from app.core.agent.toolkits.foundation.docx_template import (
    replace_docx_placeholders_in_paragraph as _replace_docx_placeholders_in_paragraph,
)

from ._internal_backup import (
    _best_effort_backup,
    _ensure_existing_file_writable,
    _nonwritable_target_message,
    _nonwritable_target_next_step,
)
from ._internal_fs import _resolve_path, _result_path
from ._internal_results import _blocked_write_result, _file_task_diff, _success_result
from ._internal_tempfile import _save_docx_via_temp_file
from ._internal_warnings import _merge_warnings
from .docx_convert import _resolve_output_path  # noqa: F401


def fill_docx_template(
    path: str,
    data: str = "{}",
    target_path: str = "",
    placeholder_style: str = "braces",
) -> str:
    """Fill simple placeholders in a DOCX template.

    `data` is a JSON object. With placeholder_style=braces, field `name`
    replaces both `{{name}}` and `{name}`.
    """
    resolved = _resolve_path(path)
    if not resolved:
        return json.dumps({"error": f"File not found: {path}"}, ensure_ascii=False)
    try:
        values = json.loads(data) if isinstance(data, str) else data
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"Invalid data JSON: {exc}"}, ensure_ascii=False)
    if not isinstance(values, dict):
        return json.dumps(
            {"error": "Template data must be a JSON object"}, ensure_ascii=False
        )

    try:
        from docx import Document

        target = _resolve_output_path(path, resolved, target_path, ".docx")
        if not target:
            return json.dumps(
                {"error": f"Invalid target path: {target_path}"}, ensure_ascii=False
            )
        file_exists = os.path.exists(target)
        if target != resolved:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(resolved, target)

        backup_warning = _best_effort_backup(target) if file_exists else ""
        write_warning = _ensure_existing_file_writable(target) if file_exists else ""
        doc = Document(target)
        replacements: Dict[str, str] = {}
        for raw_key, raw_value in values.items():
            key = str(raw_key)
            value = "" if raw_value is None else str(raw_value)
            replacements[f"{{{{{key}}}}}"] = value
            if str(placeholder_style or "").strip().lower() in {"braces", "single"}:
                replacements[f"{{{key}}}"] = value

        diff_items: List[Dict[str, Any]] = []
        fields_seen: set[str] = set()
        for index, paragraph in enumerate(doc.paragraphs, start=1):
            changed, before, after = _replace_docx_placeholders_in_paragraph(
                paragraph, replacements
            )
            if changed:
                diff_items.append(
                    {
                        "location": "paragraph",
                        "paragraph_index": index,
                        "before": before,
                        "after": after,
                    }
                )
        for table_index, table in enumerate(doc.tables, start=1):
            for row_index, row in enumerate(table.rows, start=1):
                for col_index, cell in enumerate(row.cells, start=1):
                    for paragraph_index, paragraph in enumerate(
                        cell.paragraphs, start=1
                    ):
                        changed, before, after = (
                            _replace_docx_placeholders_in_paragraph(
                                paragraph, replacements
                            )
                        )
                        if changed:
                            diff_items.append(
                                {
                                    "location": "table_cell",
                                    "table_index": table_index,
                                    "row": row_index,
                                    "col": col_index,
                                    "paragraph_index": paragraph_index,
                                    "before": before,
                                    "after": after,
                                }
                            )
        for item in diff_items:
            before = str(item.get("before") or "")
            for raw_key in values:
                key = str(raw_key)
                if f"{{{{{key}}}}}" in before or f"{{{key}}}" in before:
                    fields_seen.add(key)

        _save_docx_via_temp_file(doc, target)
        return _success_result(
            _result_path(target_path or path, target),
            operation="fill_docx_template",
            summary=f"已填充 Word 模板中的 {len(fields_seen)} 个字段",
            file_type="docx",
            change_type="modify" if file_exists else "create",
            summary_code="WRITE_OK",
            diff=_file_task_diff("docx_template_fields", diff_items),
            source_path=_result_path(path, resolved),
            fields_filled=sorted(fields_seen),
            placeholders_replaced=len(diff_items),
            warning=_merge_warnings(backup_warning, write_warning),
            focus=True,
        )
    except ImportError:
        return json.dumps({"error": "python-docx not installed"}, ensure_ascii=False)
    except PermissionError as exc:
        target = _resolve_output_path(path, resolved, target_path, ".docx") or resolved
        return _blocked_write_result(
            _result_path(target_path or path, target),
            summary=str(exc).strip() or _nonwritable_target_message(target),
            suggested_next_step=_nonwritable_target_next_step(target),
            operation="fill_docx_template",
            file_type="docx",
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
