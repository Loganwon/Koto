"""Domain module - DOCX conversion tools."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

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

from ._internal_fs import _resolve_path, _result_path, _safe_resolve
from ._internal_results import _blocked_write_result, _success_result


def _resolve_output_path(
    source_path: str,
    source_resolved: str,
    target_path: str,
    suffix: str,
) -> Optional[str]:
    requested = str(target_path or "").strip()
    if requested:
        if os.path.isabs(requested):
            return os.path.normpath(requested)
        resolved = _safe_resolve(requested)
        if not resolved:
            return None
        return resolved
    base = Path(source_resolved or source_path).with_suffix(suffix)
    return str(base)


def _convert_docx_to_pdf_with_docx2pdf(source: str, target: str) -> str:
    return _conversion_docx2pdf(source, target)


def _convert_docx_to_pdf_with_word(source: str, target: str) -> str:
    return _conversion_word(source, target)


def _convert_docx_to_pdf_with_libreoffice(source: str, target: str) -> str:
    return _conversion_libreoffice(source, target)


def convert_docx_to_pdf(path: str, target_path: str = "") -> str:
    return _conversion_convert_docx_to_pdf(
        path,
        target_path,
        resolve_path=_resolve_path,
        resolve_output_path=_resolve_output_path,
        result_path=_result_path,
        success_result=_success_result,
        blocked_write_result=_blocked_write_result,
        converters=(
            _convert_docx_to_pdf_with_docx2pdf,
            _convert_docx_to_pdf_with_word,
            _convert_docx_to_pdf_with_libreoffice,
        ),
    )
