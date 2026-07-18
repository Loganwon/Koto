# -*- coding: utf-8 -*-
"""Canonical failure records and failed terminal payloads for file tasks.

All active file-task paths finish with ``run.finished`` (or
``run.cancelled``).  Failure is data carried by the terminal payload, never a
second terminal event type.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable

from app.core.security.output_validator import sanitize_user_visible_text


def _contains(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)


def build_execution_failure(
    *,
    status: str,
    code: str,
    phase: str,
    summary: str,
    detail: str = "",
    remaining: Iterable[str] | None = None,
    recoverable: bool = True,
    **metadata: Any,
) -> Dict[str, Any]:
    """Build the one user-safe failure record used by every file-task path."""

    safe_summary = sanitize_user_visible_text(summary, fallback="文件任务执行失败。")
    safe_detail = sanitize_user_visible_text(
        detail,
        fallback=safe_summary,
        treat_as_error=True,
    )
    failure: Dict[str, Any] = {
        "status": str(status or "failed").strip().lower() or "failed",
        "code": str(code or "FILE_TASK_FAILED").strip() or "FILE_TASK_FAILED",
        "phase": str(phase or "execution").strip() or "execution",
        "summary": safe_summary,
        "detail": safe_detail or safe_summary,
        "remaining": [
            str(item).strip() for item in (remaining or []) if str(item).strip()
        ],
        "recoverable": bool(recoverable),
    }
    for key, value in metadata.items():
        if value not in (None, "", [], {}):
            failure[key] = value
    return failure


def build_failed_run_payload(
    *,
    status: str,
    code: str,
    phase: str,
    summary: str,
    detail: str = "",
    remaining: Iterable[str] | None = None,
    recoverable: bool = True,
    runtime: Dict[str, Any] | None = None,
    **payload_metadata: Any,
) -> Dict[str, Any]:
    """Build a canonical unsuccessful ``run.finished`` payload."""

    failure = build_execution_failure(
        status=status,
        code=code,
        phase=phase,
        summary=summary,
        detail=detail,
        remaining=remaining,
        recoverable=recoverable,
    )
    runtime_payload = dict(runtime or {})
    runtime_payload["terminal_status"] = failure["status"]
    runtime_payload["failure"] = dict(failure)
    payload: Dict[str, Any] = {
        "summary": failure["summary"],
        "text": failure["summary"],
        "status": failure["status"],
        "completed_task": False,
        "failure": failure,
        "runtime": runtime_payload,
    }
    for key, value in payload_metadata.items():
        if value not in (None, "", [], {}):
            payload[key] = value
    return payload


def build_model_execution_failure(
    exc: Exception,
    *,
    round_index: int,
    model_mode: str = "",
    model_id: str = "",
) -> Dict[str, Any]:
    """Classify one failed model turn without leaking provider internals.

    The returned mapping is the single failure object carried through
    verification, persistence, and the frontend task report.
    """

    raw_detail = str(exc or "").strip()
    lowered = raw_detail.lower()
    if _contains(
        lowered,
        "timed out",
        "timeout",
        "deadline_exceeded",
        "deadline exceeded",
    ):
        status = "model_timeout"
        code = "MODEL_CALL_TIMEOUT"
        summary = "模型在文件任务执行阶段超时，尚未完成文件写入。"
        remaining = [
            "确认当前模型连接稳定后重试；若持续超时，请调整文件任务模型或超时配置。"
        ]
    elif _contains(
        lowered,
        "401",
        "403",
        "429",
        "api key",
        "api_key",
        "permission denied",
        "quota",
        "rate limit",
        "circuit breaker",
        "not reachable",
        "model unavailable",
    ):
        status = "model_unavailable"
        code = "MODEL_UNAVAILABLE"
        summary = "文件任务模型当前不可用，执行未进入有效写入阶段。"
        remaining = ["检查当前模型、API 配置或本地模型服务后重试。"]
    else:
        status = "model_error"
        code = "MODEL_CALL_FAILED"
        summary = "文件任务模型调用失败，执行未完成文件写入。"
        remaining = ["查看任务执行详情中的失败阶段，恢复模型后重新执行。"]

    detail = sanitize_user_visible_text(
        raw_detail,
        fallback=summary,
        treat_as_error=True,
    )
    if not detail:
        detail = summary
    return build_execution_failure(
        status=status,
        code=code,
        phase="model_call",
        summary=summary,
        detail=detail,
        remaining=remaining,
        recoverable=True,
        round=max(1, int(round_index or 1)),
        model_mode=str(model_mode or "").strip(),
        model_id=str(model_id or "").strip(),
    )


__all__ = [
    "build_execution_failure",
    "build_failed_run_payload",
    "build_model_execution_failure",
]
