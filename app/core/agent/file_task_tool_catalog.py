from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class FileTaskToolSpec:
    name: str
    family: str
    file_types: tuple[str, ...]
    read_only: bool
    produces_file_change: bool = False


_ALLOWLIST: tuple[FileTaskToolSpec, ...] = (
    FileTaskToolSpec("parse_file_to_text", "office_read", ("docx", "xlsx", "pptx", "pdf", "txt", "md", "csv", "json"), True),
    FileTaskToolSpec("read_docx_content", "docx", ("docx",), True),
    FileTaskToolSpec("write_docx_content", "docx", ("docx",), False, True),
    FileTaskToolSpec("clear_docx_review_marks", "docx", ("docx",), False, True),
    FileTaskToolSpec("insert_image_into_docx", "docx", ("docx",), False, True),
    FileTaskToolSpec("insert_excel_as_docx_table", "docx_xlsx", ("docx", "xlsx"), False, True),
    FileTaskToolSpec("read_sheet_data", "xlsx", ("xlsx", "xlsm", "csv"), True),
    FileTaskToolSpec("inspect_workbook_structure", "xlsx_audit", ("xlsx", "xlsm"), True),
    FileTaskToolSpec("audit_financial_workbook", "xlsx_audit", ("xlsx", "xlsm"), True),
    FileTaskToolSpec("write_sheet_data", "xlsx", ("xlsx", "xlsm"), False, True),
    FileTaskToolSpec("design_pptx_theme_layout", "pptx", ("pptx",), False, True),
    FileTaskToolSpec("write_pptx_slides", "pptx", ("pptx",), False, True),
    FileTaskToolSpec("add_pptx_slides", "pptx", ("pptx",), False, True),
    FileTaskToolSpec("read_file_range", "text", ("txt", "md", "text", "csv", "json", "py", "js", "html", "css"), True),
    FileTaskToolSpec("create_file", "workspace", ("txt", "md", "csv", "json", "html", "docx", "xlsx", "pptx"), False, True),
    FileTaskToolSpec("copy_file", "workspace", ("docx", "xlsx", "pptx", "pdf", "txt", "md", "csv", "json"), False, True),
    FileTaskToolSpec("list_workspace_files", "workspace", tuple(), True),
    FileTaskToolSpec("open_file_in_editor", "workspace", tuple(), True),
    FileTaskToolSpec("compare_files", "analysis", ("docx", "xlsx", "pptx", "pdf", "txt", "md", "csv", "json"), True),
    FileTaskToolSpec("extract_to_file", "cross_file", ("docx", "xlsx", "pptx", "pdf", "txt", "md", "csv", "json"), False, True),
    FileTaskToolSpec("annotate_file", "review", ("docx", "pdf", "txt", "md"), False, True),
    FileTaskToolSpec("run_python_code", "sandbox", tuple(), False, True),
    FileTaskToolSpec("verify_task_completion", "check", tuple(), True),
)

_SPEC_BY_NAME: Dict[str, FileTaskToolSpec] = {spec.name: spec for spec in _ALLOWLIST}


def supported_file_workflows() -> Dict[str, List[str]]:
    return {
        "docx": ["read paragraphs/tables", "write paragraphs", "clear review comments/tracked changes", "append images/charts as real Word pictures", "append Excel data as a real Word table", "compare/extract/annotate"],
        "xlsx": ["read sheets", "inspect workbook structure/formulas/external links", "audit financial models before drawing conclusions", "write cells", "copy data into DOCX", "sandbox analysis/charts"],
        "pptx": ["extract text", "apply safe theme/layout/font styling", "update existing slide text", "append simple title/content slides"],
        "pdf": ["extract text by page window", "compare/extract", "annotation is best-effort when supported by the tool layer"],
        "text": ["read ranges", "create/update derived TXT/MD/CSV/JSON files", "sandbox processing"],
        "sandbox": ["Python data processing", "chart/image/file creation with KOTO_CREATED/KOTO_MODIFIED markers"],
    }


def file_task_tool_specs() -> List[FileTaskToolSpec]:
    return list(_ALLOWLIST)


def is_file_task_tool(tool_name: str) -> bool:
    return str(tool_name or "").strip() in _SPEC_BY_NAME


def is_write_tool(tool_name: str) -> bool:
    spec = _SPEC_BY_NAME.get(str(tool_name or "").strip())
    return bool(spec and not spec.read_only)


def produces_file_change(tool_name: str) -> bool:
    spec = _SPEC_BY_NAME.get(str(tool_name or "").strip())
    return bool(spec and spec.produces_file_change)


def write_target_for_tool(tool_name: str, tool_args: Dict[str, Any]) -> str:
    args = tool_args or {}
    if tool_name == "copy_file":
        return str(args.get("destination") or "").strip()
    if tool_name in {"insert_excel_as_docx_table", "extract_to_file"}:
        return str(args.get("target_path") or "").strip()
    return str(args.get("path") or args.get("target_path") or args.get("destination") or "").strip()


class FileTaskToolCatalog:
    def __init__(self, *, task_files: Optional[List[Dict[str, str]]] = None):
        from app.core.agent.file_task_tool_gateway import FileTaskToolContext, FileTaskToolGateway

        self._gateway = FileTaskToolGateway(context=FileTaskToolContext(task_files=task_files or []))

    def definitions(self) -> List[Dict[str, Any]]:
        return self._gateway.definitions()

    def allowed_names(self) -> set[str]:
        return self._gateway.allowed_names()

    def execute(self, tool_name: str, tool_args: Dict[str, Any]) -> Any:
        return self._gateway.execute(tool_name, tool_args)


def tool_result_preview(tool_name: str, result: Any, limit: int = 900) -> str:
    result_text = stringify_result(result)
    try:
        payload = json.loads(result_text)
    except Exception:
        payload = None

    if isinstance(payload, dict):
        if payload.get("error"):
            return f"Error: {payload.get('error')}"
        warning = str(payload.get("warning") or "").strip()
        if payload.get("summary"):
            summary = str(payload.get("summary"))
            if warning:
                summary = f"{summary}；警告：{warning}"
            return summary[:limit]
        if tool_name == "read_sheet_data":
            sheet = str(payload.get("sheet") or "").strip()
            summary = f"已读取工作表“{sheet}”的 {payload.get('row_count', 0)} 行表格数据" if sheet else f"已读取 {payload.get('row_count', 0)} 行表格数据"
            if warning:
                summary = f"{summary}；警告：{warning}"
            return summary[:limit]
        if tool_name == "inspect_workbook_structure":
            summary = f"已检查 {payload.get('sheet_count', 0)} 个工作表"
            if payload.get("external_link_count"):
                summary += f"，发现 {payload.get('external_link_count')} 个外部链接"
            if payload.get("total_formula_cells"):
                summary += f"，共 {payload.get('total_formula_cells')} 个公式单元格"
            return summary[:limit]
        if tool_name == "audit_financial_workbook":
            high = sum(1 for item in (payload.get("findings") or []) if isinstance(item, dict) and item.get("severity") == "high")
            medium = sum(1 for item in (payload.get("findings") or []) if isinstance(item, dict) and item.get("severity") == "medium")
            summary = payload.get("summary") or f"已完成财务工作簿审计，高优先级问题 {high} 个，中优先级问题 {medium} 个。"
            return str(summary)[:limit]
        if tool_name == "read_docx_content":
            return f"已读取 {payload.get('total_paragraphs', 0)} 段文本，{payload.get('total_tables', 0)} 个表格"

    if len(result_text) <= limit:
        return result_text
    return result_text[: limit - 1] + "..."


def stringify_result(result: Any) -> str:
    if result is None:
        return "(no output)"
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception:
        return str(result)


def parse_file_change(tool_name: str, tool_args: Dict[str, Any], result: Any) -> Optional[Dict[str, Any]]:
    if not produces_file_change(tool_name):
        return None

    result_text = stringify_result(result)
    try:
        payload = json.loads(result_text)
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None

    if payload.get("changed") is False:
        return None

    blocked_recovery = (
        str(payload.get("status") or "").strip().lower() in {"blocked", "write_blocked"}
        and bool(payload.get("fallback_copy"))
        and bool(payload.get("path") or payload.get("file_path") or write_target_for_tool(tool_name, tool_args))
    )
    if payload.get("error") and not blocked_recovery:
        return None

    change = payload.get("change") if isinstance(payload.get("change"), dict) else {}
    path = (
        payload.get("path")
        or payload.get("file_path")
        or change.get("file_path")
        or write_target_for_tool(tool_name, tool_args)
    )
    if not path:
        return None

    file_type = payload.get("file_type") or Path(str(path)).suffix.lstrip(".").lower()
    change_type = payload.get("change_type") or change.get("change_type") or ("create" if tool_name in {"create_file", "copy_file"} else "modify")
    summary = payload.get("summary") or f"{Path(str(path)).name} 已更新"
    preview = payload.get("preview") or change.get("modified") or ""
    event_payload = {
        "path": str(path),
        "file_type": str(file_type or ""),
        "operation": str(payload.get("operation") or tool_name),
        "summary": str(summary),
        "preview": str(preview),
        "change_type": str(change_type or "modify"),
        "focus": bool(payload.get("focus")),
    }
    for key in (
        "source_path",
        "original_target_path",
        "sheet",
        "requested_sheet",
        "image_path",
        "image_name",
        "images_inserted",
        "title",
        "caption",
        "warning",
        "blocked_target",
        "blocked_reason",
        "fallback_copy",
        "rows_written",
        "columns_written",
        "table_title",
        "table_count",
        "cells_written",
        "paragraphs_written",
        "slides_updated",
        "slides_designed",
        "slides_added",
        "total_slides",
        "theme_name",
        "layout_strategy",
        "font_family",
        "annotations_added",
        "scope",
        "comments_removed",
        "comment_markup_removed",
        "revisions_accepted",
    ):
        if key in payload and payload.get(key) not in (None, ""):
            event_payload[key] = payload.get(key)
    return event_payload


def extract_koto_paths(result: Any, marker: str) -> List[str]:
    if isinstance(result, dict):
        key = "_koto_created" if marker == "__koto_created__:" else "_koto_modified"
        values = result.get(key)
        if isinstance(values, list):
            return [str(item) for item in values if str(item or "").strip()]
    result_text = stringify_result(result)
    idx = result_text.rfind(marker)
    if idx == -1:
        return []
    try:
        parsed = json.loads(result_text[idx + len(marker):])
    except Exception:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def extract_sandbox_artifacts(result: Any) -> List[Dict[str, Any]]:
    payload = result if isinstance(result, dict) else None
    if not payload:
        return []
    files = payload.get("files") or payload.get("images") or {}
    if not isinstance(files, dict):
        return []

    artifacts: List[Dict[str, Any]] = []
    for name, data in files.items():
        filename = str(name or "artifact").strip() or "artifact"
        ext = Path(filename).suffix.lstrip(".").lower()
        mime = "image/svg+xml" if ext == "svg" else f"image/{ext or 'png'}"
        artifacts.append({
            "kind": "image",
            "name": filename,
            "mime_type": mime,
            "data": str(data or ""),
        })
    return artifacts


def file_states_for_changes(changes: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    states: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for change in changes:
        path = str(change.get("path") or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        states.append({
            "path": path,
            "exists": True,
            "modified": True,
            "preview": str(change.get("preview") or change.get("summary") or "")[:1000],
        })
    return states