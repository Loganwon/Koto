from __future__ import annotations

import base64
import filecmp
import hashlib
import importlib
import io
import json
import logging
import os
import re
import shutil
import stat
import sys
import tempfile
import time
import types
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.agent.base import AgentPlugin
from app.core.agent.file_task_completion_verifier import verify_task_completion
from app.core.agent.file_task_contract import FileTaskToolStreamResult
from app.core.agent.file_task_result_markers import (
    KOTO_CREATED_FALLBACK_KEY,
    KOTO_CREATED_RESULT_KEY,
    KOTO_CREATED_RESULT_MARKER,
    KOTO_MODIFIED_FALLBACK_KEY,
    KOTO_MODIFIED_RESULT_KEY,
    KOTO_MODIFIED_RESULT_MARKER,
)
from app.core.agent.path_utils import (
    default_search_roots,
    has_parent_path_segment,
    is_within_roots,
    resolve_existing_path,
)
from app.core.agent.task_tool_operation_bindings import build_task_tool_operations
from app.core.agent.toolkits.foundation import (
    FOUNDATION_TOOL_SOURCE,
    FOUNDATION_TOOLKIT_ID,
    FOUNDATION_TOOLKIT_VERSION,
)
from app.core.agent.toolkits.foundation.conversion import (
    convert_docx_to_pdf as _conversion_convert_docx_to_pdf,
)
from app.core.agent.toolkits.foundation.conversion import (
    convert_docx_to_pdf_with_docx2pdf as _conversion_docx2pdf,
)
from app.core.agent.toolkits.foundation.conversion import (
    convert_docx_to_pdf_with_libreoffice as _conversion_libreoffice,
)
from app.core.agent.toolkits.foundation.conversion import (
    convert_docx_to_pdf_with_word as _conversion_word,
)
from app.core.agent.toolkits.foundation.conversion import (
    convert_file as _conversion_convert_file,
)
from app.core.agent.toolkits.foundation.conversion import (
    list_conversions as _conversion_list_conversions,
)
from app.core.agent.toolkits.foundation.conversion import (
    normalize_conversion_extension as _conversion_normalize_extension,
)
from app.core.agent.toolkits.foundation.docx_compare import (
    _build_docx_compare_annotations,
    _contract_risk_summary_from_annotations,
    _docx_compare_annotation_candidates,
    _docx_diff_comment,
    _docx_diff_key,
    _docx_nonempty_paragraph_texts,
    _short_docx_diff_text,
)
from app.core.agent.toolkits.foundation.docx_minimal import (
    _coerce_docx_paragraphs_for_write,
    _minimal_docx_package_bytes,
    _normalize_docx_paragraphs,
    _plain_text_to_docx_paragraphs,
)
from app.core.agent.toolkits.foundation.docx_review_cleanup import (
    DOCX_COMMENT_MARKUP_TAGS as _DOCX_COMMENT_MARKUP_TAGS,
)
from app.core.agent.toolkits.foundation.docx_review_cleanup import (
    DOCX_W_NS as _DOCX_W_NS,
)
from app.core.agent.toolkits.foundation.docx_review_cleanup import _serialize_xml_root
from app.core.agent.toolkits.foundation.docx_review_cleanup import (
    accept_docx_revision_markup as _accept_docx_revision_markup,
)
from app.core.agent.toolkits.foundation.docx_review_cleanup import (
    build_docx_review_clear_summary as _build_docx_review_clear_summary,
)
from app.core.agent.toolkits.foundation.docx_review_cleanup import (
    normalize_docx_review_clear_scope as _review_normalize_docx_review_clear_scope,
)
from app.core.agent.toolkits.foundation.docx_review_cleanup import (
    remove_comments_content_type_override as _remove_comments_content_type_override,
)
from app.core.agent.toolkits.foundation.docx_review_cleanup import (
    remove_comments_relationships_xml as _remove_comments_relationships_xml,
)
from app.core.agent.toolkits.foundation.docx_review_cleanup import (
    remove_docx_comment_markup as _remove_docx_comment_markup,
)
from app.core.agent.toolkits.foundation.docx_style import (
    apply_docx_style as _apply_docx_style,
)
from app.core.agent.toolkits.foundation.docx_table_helpers import (
    _compact_financial_table_rows,
    _match_header_index,
    _normalize_table_columns,
    _style_compact_financial_docx_table,
    _table_sort_value,
)
from app.core.agent.toolkits.foundation.docx_template import (
    replace_docx_placeholders_in_paragraph as _replace_docx_placeholders_in_paragraph,
)
from app.core.agent.toolkits.foundation.multi_file import (
    compare_files as _multi_compare_files,
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
from app.core.agent.toolkits.foundation.pdf_window import (
    int_to_chinese_letter_number as _int_to_chinese_letter_number,
)
from app.core.agent.toolkits.foundation.pdf_window import (
    int_to_pdf_roman as _int_to_pdf_roman,
)
from app.core.agent.toolkits.foundation.pdf_window import (
    pdf_letter_heading_terms as _pdf_letter_heading_terms,
)
from app.core.agent.toolkits.foundation.pdf_window import (
    pdf_page_has_letter_heading as _pdf_page_has_letter_heading,
)
from app.core.agent.toolkits.foundation.pdf_window import (
    read_pdf_excerpt as _pdf_read_excerpt,
)
from app.core.agent.toolkits.foundation.pdf_window import (
    read_pdf_letter_window as _pdf_read_letter_window,
)
from app.core.agent.toolkits.foundation.pptx import PptxOperationContext
from app.core.agent.toolkits.foundation.pptx import add_pptx_slides as _pptx_add_slides
from app.core.agent.toolkits.foundation.pptx import (
    design_pptx_theme_layout as _pptx_design_theme_layout,
)
from app.core.agent.toolkits.foundation.pptx import (
    write_pptx_slides as _pptx_write_slides,
)
from app.core.agent.toolkits.foundation.pptx_layout import _pptx_text_lines
from app.core.agent.toolkits.foundation.registry import build_task_tool_definitions
from app.core.agent.toolkits.foundation.xlsx_sheet_selection import (
    select_workbook_sheet as _select_workbook_sheet,
)
from app.core.agent.toolkits.foundation.xlsx_sheet_selection import (
    sheet_matches_statement as _sheet_matches_statement,
)
from app.core.agent.toolkits.foundation.xlsx_structure import (
    collect_formula_examples as _collect_formula_examples,
)
from app.core.agent.toolkits.foundation.xlsx_structure import (
    detect_year_header as _detect_year_header,
)
from app.core.agent.toolkits.foundation.xlsx_structure import (
    display_series_value as _display_series_value,
)
from app.core.agent.toolkits.foundation.xlsx_structure import (
    extract_external_link_targets as _extract_external_link_targets,
)
from app.core.agent.toolkits.foundation.xlsx_structure import (
    row_label_for_year_series as _row_label_for_year_series,
)
from app.core.agent.toolkits.foundation.xlsx_structure import (
    sample_sheet_rows as _sample_sheet_rows,
)
from app.core.agent.toolkits.foundation.xlsx_structure import (
    severity_for_financial_label as _xlsx_severity_for_financial_label,
)
from app.core.services.file_service import FileService

logger = logging.getLogger(__name__)

_TEXT_LIMIT_MIN = 1_000

_TEXT_LIMIT_DEFAULT = 60_000

_TEXT_LIMIT_DOCX_DEFAULT = 24_000

_TEXT_LIMIT_MAX = 200_000

_TASK_TOOL_LLM_CALL_TIMEOUT = float(os.getenv("KOTO_FILE_TASK_LLM_TIMEOUT", "45"))

_SANDBOX_CLEANUP_RETRIES = int(os.getenv("KOTO_SANDBOX_CLEANUP_RETRIES", "3"))

_SANDBOX_CLEANUP_RETRY_DELAY_SECONDS = float(
    os.getenv("KOTO_SANDBOX_CLEANUP_RETRY_DELAY", "0.1")
)

_WORKSPACE_ROOT: Optional[str] = None  # test/compatibility override only

_GENERIC_SHEET_NAME_GUESSES = {"sheet", "sheet1", "工作表", "工作表1"}

_YEAR_HEADER_RE = re.compile(
    r"(?<!\d)(20\d{2}(?:\s*[A-Za-z]{0,4})?)(?!\d)", re.IGNORECASE
)

_FINANCIAL_STATEMENT_PATTERNS = {
    "profit_and_loss": (
        re.compile(
            r"(?:^|\b)(p\s*&\s*l|profit\s*&?\s*loss|income\s*statement)(?:\b|$)",
            re.IGNORECASE,
        ),
        re.compile(r"利润|损益|收入成本", re.IGNORECASE),
    ),
    "balance_sheet": (
        re.compile(
            r"(?:^|\b)(balance\s*sheet|statement\s*of\s*financial\s*position|bs)(?:\b|$)",
            re.IGNORECASE,
        ),
        re.compile(r"资产负债", re.IGNORECASE),
    ),
    "cash_flow": (
        re.compile(r"(?:^|\b)(cash\s*flow|cashflow|cf)(?:\b|$)", re.IGNORECASE),
        re.compile(r"现金流", re.IGNORECASE),
    ),
}

_HIGH_PRIORITY_FINANCIAL_LABEL_HINTS = (
    "税",
    "所得税",
    "净利润",
    "现金",
    "资产",
    "负债",
    "收入",
    "成本",
    "毛利",
)

_WORKSPACE_CREATED_FILE_EXTS = {
    ".csv",
    ".doc",
    ".docx",
    ".gif",
    ".jpeg",
    ".jpg",
    ".json",
    ".md",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".svg",
    ".txt",
    ".webp",
    ".xls",
    ".xlsm",
    ".xlsx",
}

_DOCX_REVIEW_CLEAR_SCOPE_ALIASES = {
    "": "comments",
    "comment": "comments",
    "comments": "comments",
    "annotation": "comments",
    "annotations": "comments",
    "批注": "comments",
    "标注": "comments",
    "评论": "comments",
    "注释": "comments",
    "review": "all",
    "review_marks": "all",
    "all": "all",
    "全部": "all",
    "所有": "all",
    "修订": "revisions",
    "revision": "revisions",
    "revisions": "revisions",
    "tracked_changes": "revisions",
}

from app.core.agent.toolkits.foundation.xlsx import (  # noqa: E402, F401
    audit_financial_workbook,
    inspect_workbook_structure,
    read_sheet_data,
    write_sheet_data,
)
