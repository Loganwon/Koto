from __future__ import annotations

import json

import pytest

from app.core.agent.file_task_runtime_utils import _is_error_result


def test_is_error_result_rejects_structured_python_traceback() -> None:
    result = {
        "stdout": "",
        "stderr": (
            "Traceback (most recent call last):\n"
            '  File "<string>", line 2, in <module>\n'
            "IndexError: list index out of range\n"
        ),
        "error": "",
    }

    assert _is_error_result(result) is True


def test_is_error_result_allows_nonfatal_stderr_warning() -> None:
    result = {
        "stdout": "saved",
        "stderr": "UserWarning: workbook has no default style",
        "error": "",
    }

    assert _is_error_result(result) is False


def test_is_error_result_rejects_structured_exception_line() -> None:
    result = {"stdout": "", "stderr": "ValueError: invalid value", "error": ""}

    assert _is_error_result(result) is True


@pytest.mark.parametrize(
    "result",
    [
        "Error parsing file: invalid DOCX archive",
        {"ok": False, "content": "partial data"},
        {"success": False, "result": "partial data"},
        {"failure": {"code": "read_failed"}},
    ],
)
def test_is_error_result_rejects_parser_error_and_typed_failure(result):
    assert _is_error_result(result)


@pytest.mark.parametrize("serialize", [False, True])
def test_typed_success_preserves_content_with_a_legacy_error_prefix(serialize):
    result = {"ok": True, "value": "Error parsing file: is a sentence in this document"}
    assert not _is_error_result(json.dumps(result) if serialize else result)
    result["error"] = {"code": "read_failed"}
    assert _is_error_result(result)
