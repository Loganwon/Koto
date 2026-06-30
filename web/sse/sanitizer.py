# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

import json

from app.core.security.output_validator import sanitize_user_visible_text


def sanitize_sse_text_field(
    payload: dict,
    field_name: str,
    *,
    fallback: str,
    treat_as_error: bool = False,
    skip_empty: bool = False,
) -> None:
    if field_name not in payload:
        return

    raw_value = payload.get(field_name, "")
    if skip_empty:
        raw_value = str(raw_value or "").strip()
        if not raw_value:
            return

    payload[field_name] = sanitize_user_visible_text(
        raw_value,
        fallback=fallback,
        treat_as_error=treat_as_error,
    )


def safe_sse(payload: dict) -> str:
    safe_payload = dict(payload or {})
    event_type = str(safe_payload.get("type") or "").strip().lower()
    message_as_error = bool(
        safe_payload.pop("_message_as_error", event_type == "error")
    )
    detail_as_error = bool(safe_payload.pop("_detail_as_error", False))
    message_fallback = safe_payload.pop("_message_fallback", None)
    detail_fallback = safe_payload.pop("_detail_fallback", None)

    if "message" in safe_payload:
        if message_fallback is None:
            message_fallback = (
                "AI 处理失败，请稍后重试。" if message_as_error else "处理中…"
            )
        sanitize_sse_text_field(
            safe_payload,
            "message",
            fallback=message_fallback,
            treat_as_error=message_as_error,
        )

    if "detail" in safe_payload:
        if detail_fallback is None:
            detail_fallback = "处理失败，请稍后重试。" if detail_as_error else ""
        sanitize_sse_text_field(
            safe_payload,
            "detail",
            fallback=detail_fallback,
            treat_as_error=detail_as_error,
            skip_empty=True,
        )

    return f"data: {json.dumps(safe_payload, ensure_ascii=False)}\n\n"
