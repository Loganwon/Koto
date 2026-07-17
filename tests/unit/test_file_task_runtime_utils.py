from __future__ import annotations

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
