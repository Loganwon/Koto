"""Domain module - File conversion tools."""

from __future__ import annotations

from app.core.agent.toolkits.foundation.conversion import (
    convert_file as _conversion_convert_file,
)
from app.core.agent.toolkits.foundation.conversion import (
    list_conversions as _conversion_list_conversions,
)
from app.core.agent.toolkits.foundation.conversion import (
    normalize_conversion_extension as _conversion_normalize_extension,
)

from ._internal_fs import _resolve_path, _result_path
from ._internal_results import _blocked_write_result, _success_result
from .docx_convert import _resolve_output_path  # noqa: F401


def _normalize_conversion_extension(target_format: str) -> str:
    return _conversion_normalize_extension(target_format)


def convert_file(file_path: str, target_format: str, output_path: str = "") -> str:
    return _conversion_convert_file(
        file_path,
        target_format,
        output_path,
        resolve_path=_resolve_path,
        resolve_output_path=_resolve_output_path,
        result_path=_result_path,
        success_result=_success_result,
        blocked_write_result=_blocked_write_result,
    )


def list_conversions(file_ext: str = "") -> str:
    return _conversion_list_conversions(file_ext)
