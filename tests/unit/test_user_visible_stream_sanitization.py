from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest


_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault("KOTO_AUTH_ENABLED", "false")
os.environ.setdefault("KOTO_DEPLOY_MODE", "local")
os.environ.setdefault("GEMINI_API_KEY", "test-key-for-unit-tests")


def _parse_sse_payload(frame: str) -> dict:
    prefix = "data: "
    assert frame.startswith(prefix)
    return json.loads(frame[len(prefix):].strip())


@pytest.mark.unit
def test_legacy_safe_sse_hides_sensitive_error_message():
    from web.app import _legacy_safe_sse

    payload = _parse_sse_payload(
        _legacy_safe_sse(
            {
                "type": "error",
                "message": (
                    'Traceback (most recent call last):\n'
                    '  File "app.py", line 1\n'
                    "ConnectError: boom"
                ),
            }
        )
    )

    assert payload["type"] == "error"
    assert payload["message"] == "AI 处理失败，请稍后重试。"


@pytest.mark.unit
def test_legacy_safe_sse_hides_sensitive_detail_when_marked_error_like():
    from web.app import _legacy_safe_sse

    payload = _parse_sse_payload(
        _legacy_safe_sse(
            {
                "type": "progress",
                "message": "正在回退到标准模式",
                "detail": (
                    'Traceback (most recent call last):\n'
                    '  File "app.py", line 1\n'
                    "ConnectError: boom"
                ),
                "_detail_as_error": True,
            }
        )
    )

    assert payload["message"] == "正在回退到标准模式"
    assert payload["detail"] == "处理失败，请稍后重试。"


@pytest.mark.unit
def test_legacy_safe_sse_uses_custom_message_fallback_for_progress_errors():
    from web.app import _legacy_safe_sse

    payload = _parse_sse_payload(
        _legacy_safe_sse(
            {
                "type": "progress",
                "message": "System Prompt:\nYou are a hidden assistant.",
                "_message_as_error": True,
                "_message_fallback": "⚠️ Tree of Thought 遇到问题，切换至标准模式",
            }
        )
    )

    assert payload["message"] == "⚠️ Tree of Thought 遇到问题，切换至标准模式"


@pytest.mark.unit
def test_socket_preview_sanitizer_hides_prompt_leak():
    from app.core.socket_handler import _safe_user_preview_text

    safe = _safe_user_preview_text(
        "System Prompt:\nYou are a hidden assistant.",
        "工具已执行。",
    )

    assert safe == "工具已执行。"