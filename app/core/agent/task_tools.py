"""Task tools facade -- re-exports from domain-organized tools/ package.

This module is the stable public API.  Implementations live in
``app.core.agent.tools.*`` domain modules.
"""

from __future__ import annotations

import json
import os  # noqa: E402
import re
from pathlib import Path  # noqa: E402

# -- Plugin imports -----------------------------------------------------------
from typing import Any, Dict, List, Optional  # noqa: E402

from app.core.agent.base import AgentPlugin  # noqa: E402
from app.core.agent.file_task_completion_verifier import (  # noqa: E402, F401
    verify_task_completion,
)
from app.core.agent.task_tool_operation_bindings import (  # noqa: E402
    build_task_tool_operations,
)

# -- all public tools ---------------------------------------------------------
from app.core.agent.tool_registry import ToolRegistry  # noqa: E402, F401
from app.core.agent.toolkits.foundation import (  # noqa: E402
    FOUNDATION_TOOL_SOURCE,
    FOUNDATION_TOOLKIT_ID,
    FOUNDATION_TOOLKIT_VERSION,
)
from app.core.agent.toolkits.foundation.docx_compare import (  # noqa: E402, F401
    _build_docx_compare_annotations,
    _contract_risk_summary_from_annotations,
)
from app.core.agent.toolkits.foundation.registry import (  # noqa: E402
    build_task_tool_definitions,
)
from app.core.agent.toolkits.foundation.xlsx import (  # noqa: E402, F401
    audit_financial_workbook,
    inspect_workbook_structure,
    read_sheet_data,
    write_sheet_data,
)
from app.core.agent.tools import (  # noqa: E402, F401
    SandboxRunResult,
    add_pptx_slides,
    clear_docx_review_marks,
    compare_docx_and_annotate,
    compare_files,
    convert_docx_to_pdf,
    convert_file,
    copy_file,
    create_file,
    design_pptx_theme_layout,
    fill_docx_template,
    insert_docx_paragraph,
    insert_excel_as_docx_table,
    insert_image_into_docx,
    list_conversions,
    list_workspace_files,
    open_file_in_editor,
    parse_file_to_text,
    plan_docx_compare_annotations,
    read_docx_content,
    read_file_range,
    replace_file_selection,
    run_python_in_sandbox,
    write_docx_comments,
    write_docx_content,
    write_pptx_slides,
)

# -- internal helpers ---------------------------------------------------------
from app.core.agent.tools._internal import (  # noqa: E402, F401
    _best_effort_backup,
    _blocked_write_result,
    _build_workbook_structure_payload,
    _clear_readonly_attribute,
    _copy_sandbox_workspace_file_to_workspace,
    _create_alternate_backup,
    _detect_financial_series_gap_findings,
    _ensure_existing_file_writable,
    _file_service,
    _file_task_diff,
    _fingerprint_changed,
    _fingerprint_file,
    _get_workspace_root,
    _mark_direct_target_mutation,
    _merge_warnings,
    _next_available_docx_copy_path,
    _nonwritable_target_message,
    _nonwritable_target_next_step,
    _normalize_positive_float,
    _normalize_positive_int,
    _normalize_text_limit,
    _normalize_workspace_relative_path,
    _pptx_operation_context,
    _prepare_sandbox_target_paths,
    _prepend_task_file_context,
    _read_pdf_excerpt,
    _read_pdf_letter_window,
    _resolve_path,
    _resolve_task_file_entries,
    _result_path,
    _safe_resolve,
    _save_docx_via_temp_file,
    _save_pptx_via_temp_file,
    _save_via_temp_file,
    _save_workbook_via_temp_file,
    _severity_for_financial_label,
    _stage_task_files_for_sandbox,
    _success_result,
    _sync_target_outputs_from_sandbox,
    _target_output_candidates,
    _unique_staged_name,
    _workspace_target_path,
    _write_bytes_via_temp_file,
)
from app.core.agent.tools.conversion import (  # noqa: E402, F401
    _normalize_conversion_extension,
)
from app.core.agent.tools.docx_annotate import (  # noqa: E402, F401
    _normalize_docx_review_clear_scope,
    _parse_annotations_payload,
)
from app.core.agent.tools.docx_convert import (  # noqa: E402, F401
    _convert_docx_to_pdf_with_docx2pdf,
    _convert_docx_to_pdf_with_libreoffice,
    _convert_docx_to_pdf_with_word,
    _resolve_output_path,
)
from app.core.agent.tools.docx_write import (  # noqa: E402, F401
    _write_docx_content_without_python_docx,
)
from app.core.agent.tools.filesystem import (  # noqa: E402, F401
    _create_docx_file,
    _create_pptx_file,
    _create_xlsx_file,
    _plain_text_to_pptx_slides,
)
from app.core.agent.tools.pptx import _read_pptx_slide_window  # noqa: E402, F401
from app.core.agent.tools.sandbox import (  # noqa: E402, F401
    _canonicalize_koto_markers,
    _cleanup_sandbox_tmpdir,
    _format_sandbox_result,
    _load_sandbox_run_python,
    _materialize_sandbox_files,
    _parse_koto_file_markers,
    _relocate_materialized_files_to_output_dir,
    _relocate_root_created_files_to_output_dir,
    _safe_artifact_filename,
    _sync_created_workspace_files_from_sandbox,
    _sync_staged_files_to_source,
    _workspace_output_dir_path,
    _wrap_sandbox_result,
)
from app.core.agent.tools.text import _coerce_read_line_number  # noqa: E402, F401
from app.core.agent.tools.xlsx_read import _read_xlsx_sheet_window  # noqa: E402, F401


class TaskToolsPlugin(AgentPlugin):
    """File-focused tools for the Koto file-task runtime."""

    toolkit_id = FOUNDATION_TOOLKIT_ID
    toolkit_version = FOUNDATION_TOOLKIT_VERSION
    toolkit_source = FOUNDATION_TOOL_SOURCE

    def __init__(
        self,
        socketio=None,
        task_files: Optional[List[Dict[str, str]]] = None,
        workspace_root: str = "",
        request_context: Optional[Dict[str, Any]] = None,
    ):
        self._socketio = socketio
        self._task_files = list(task_files or [])
        self._workspace_root = str(workspace_root or "").strip()
        self._request_context = dict(request_context or {})

    def _run_python_code(self, code: str, timeout: int = 30) -> str:
        return run_python_in_sandbox(
            code,
            timeout=timeout,
            task_files=self._task_files,
            target_path=str(self._request_context.get("target_path") or ""),
            output_dir=self._contextual_output_directory(),
        )

    def _contextual_output_directory(self) -> str:
        target_path = str(self._request_context.get("target_path") or "").strip()
        if target_path:
            normalized_target = target_path.replace("\\", "/").strip("/")
            if "/" in normalized_target:
                parent = str(Path(normalized_target).parent).replace("\\", "/")
                if parent and parent != ".":
                    return parent
        file_dirs: set[str] = set()
        for item in self._task_files:
            if not isinstance(item, dict):
                continue
            path_text = str(item.get("path") or "").strip()
            if not path_text:
                continue
            parent = str(Path(path_text.replace("\\", "/")).parent).replace("\\", "/")
            if parent not in {"", "."}:
                file_dirs.add(parent)
        if len(file_dirs) == 1:
            return next(iter(file_dirs))
        task_text = str(self._request_context.get("task") or "").casefold()
        if not task_text:
            return ""
        task_dir = self._contextual_output_directory_from_task_text(task_text)
        if task_dir:
            return task_dir
        workspace_root = Path(self._workspace_root or _get_workspace_root())
        try:
            matches = [
                child.name
                for child in workspace_root.iterdir()
                if child.is_dir() and child.name.casefold() in task_text
            ]
        except Exception:
            matches = []
        unique_matches = sorted(set(matches))
        if len(unique_matches) == 1:
            return unique_matches[0]
        return ""

    def _contextual_output_directory_from_task_text(self, task_text: str) -> str:
        candidates: set[str] = set()
        for match in re.finditer(
            r"(?P<dir>[A-Za-z0-9_. -]+)/(?:[A-Za-z0-9_. -]+)\\.(?:csv|xlsx|xlsm|docx|md|txt|json|pptx|pdf)",
            task_text,
            re.IGNORECASE,
        ):
            directory = str(match.group("dir") or "").strip().strip("/")
            if directory and not Path(directory).suffix:
                candidates.add(directory)
        workspace_root = Path(self._workspace_root or _get_workspace_root())
        existing = []
        for candidate in candidates:
            try:
                target = (workspace_root / candidate).resolve()
                target.relative_to(workspace_root.resolve())
            except Exception:
                continue
            if target.is_dir():
                existing.append(candidate.replace("\\", "/"))
        unique_existing = sorted(set(existing))
        return unique_existing[0] if len(unique_existing) == 1 else ""

    def _contextual_create_file_path(self, path: str) -> str:
        raw_path = str(path or "").strip()
        if not raw_path:
            return raw_path
        normalized = raw_path.replace("\\", "/").strip()
        if os.path.isabs(raw_path) or "/" in normalized.strip("/"):
            return raw_path
        output_dir = self._contextual_output_directory()
        if not output_dir:
            return raw_path
        return str(Path(output_dir.replace("\\", "/")) / normalized).replace("\\", "/")

    def _create_file(self, path: str, content: str = "") -> str:
        return create_file(self._contextual_create_file_path(path), content)

    @property
    def name(self) -> str:
        return "TaskTools"

    @property
    def description(self) -> str:
        return "Composable file-operation tools for dynamic task execution."

    def get_tools(self) -> List[Dict[str, Any]]:
        return build_task_tool_definitions(self, build_task_tool_operations())

    def _editor_live_update(self, type: str, **kwargs) -> str:
        """Push a change to the live editor via WebSocket."""
        if not self._socketio:
            return "Error: no WebSocket connection"
        payload = {"type": type, **kwargs}
        try:
            self._socketio.emit(
                "agent_execute_command",
                {"action": "editor_apply", "payload": payload},
                namespace="/doc",
            )
            return f"Applied: {type}"
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
