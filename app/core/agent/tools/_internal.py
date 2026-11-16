"""Internal helpers facade -- re-exports from domain-organized sub-modules.

This module is the stable public API.  Implementations live in
``_internal_*.py`` domain modules.
"""

from __future__ import annotations

# -- backup and permissions ---------------------------------------------------
from app.core.agent.tools._internal_backup import (  # noqa: F401
    _best_effort_backup,
    _clear_readonly_attribute,
    _create_alternate_backup,
    _ensure_existing_file_writable,
    _nonwritable_target_message,
    _nonwritable_target_next_step,
)

# -- format-specific helpers --------------------------------------------------
from app.core.agent.tools._internal_formats import (  # noqa: F401
    _build_workbook_structure_payload,
    _detect_financial_series_gap_findings,
    _next_available_docx_copy_path,
    _pptx_operation_context,
    _read_pdf_excerpt,
    _read_pdf_letter_window,
    _severity_for_financial_label,
)

# -- filesystem paths ---------------------------------------------------------
from app.core.agent.tools._internal_fs import (  # noqa: F401
    _file_service,
    _get_project_root,
    _get_workspace_root,
    _resolve_path,
    _result_path,
    _safe_resolve,
)

# -- number normalization -----------------------------------------------------
from app.core.agent.tools._internal_normalize import (  # noqa: F401
    _normalize_positive_float,
    _normalize_positive_int,
    _normalize_text_limit,
)

# -- result construction ------------------------------------------------------
from app.core.agent.tools._internal_results import (  # noqa: F401
    _blocked_write_result,
    _file_task_diff,
    _resolve_task_file_entries,
    _success_result,
)

# -- sandbox operations -------------------------------------------------------
from app.core.agent.tools._internal_sandbox import (  # noqa: F401
    _copy_sandbox_workspace_file_to_workspace,
    _fingerprint_changed,
    _fingerprint_file,
    _mark_direct_target_mutation,
    _normalize_workspace_relative_path,
    _prepare_sandbox_target_paths,
    _prepend_task_file_context,
    _stage_task_files_for_sandbox,
    _sync_target_outputs_from_sandbox,
    _target_output_candidates,
    _unique_staged_name,
    _workspace_target_path,
)

# -- temporary file saving ----------------------------------------------------
from app.core.agent.tools._internal_tempfile import (  # noqa: F401
    _save_docx_via_temp_file,
    _save_pptx_via_temp_file,
    _save_via_temp_file,
    _save_workbook_via_temp_file,
    _write_bytes_via_temp_file,
)

# -- warnings -----------------------------------------------------------------
from app.core.agent.tools._internal_warnings import _merge_warnings  # noqa: F401
