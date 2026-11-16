"""Create privacy-safe failure records that map to allowlisted replay tests."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

REPLAY_KEYS = frozenset(
    {
        "startup.local_model_missing",
        "startup.runtime_incompatible",
        "startup.legacy_upgrade",
        "docx.large_review",
        "pdf.text_position",
        "pdf.watermark_cleanup",
        "health.ping_liveness",
        "office.corrupt_pptx",
    }
)

_SENSITIVE_KEY_RE = re.compile(
    r"password|passwd|pwd|token|secret|api[_-]?key|authorization|credential|cookie|session|user(name)?",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_WINDOWS_PATH_RE = re.compile(r"(?i)(?:[A-Z]:\\|\\\\)[^\r\n\t\"'<>|]+")
_UNIX_HOME_RE = re.compile(r"/(?:home|Users)/[^/\s]+(?:/[^\s\"']*)?")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_API_TOKEN_RE = re.compile(r"(?i)\b(?:sk|key|token)[-_][A-Za-z0-9_-]{8,}\b")
_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:api[_-]?key|token|secret|password)=)[^&#\s]+"
)
_PUBLIC_IP_RE = re.compile(
    r"\b(?!127\.0\.0\.1\b)(?!0\.0\.0\.0\b)(?:\d{1,3}\.){3}\d{1,3}\b"
)


def sanitize_replay_value(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if depth > 8:
        return "[truncated]"
    if _SENSITIVE_KEY_RE.search(key):
        return None if value is None else "[redacted]"
    if isinstance(value, Mapping):
        return {
            str(item_key)[:80]: sanitize_replay_value(
                item_value, key=str(item_key), depth=depth + 1
            )
            for item_key, item_value in list(value.items())[:50]
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_replay_value(item, depth=depth + 1) for item in value[:50]]
    if not isinstance(value, str):
        return value

    text = value[:4000]
    text = _BEARER_RE.sub("Bearer [redacted]", text)
    text = _API_TOKEN_RE.sub("[redacted]", text)
    text = _QUERY_SECRET_RE.sub(r"\1[redacted]", text)
    text = _EMAIL_RE.sub("[email]", text)
    text = _WINDOWS_PATH_RE.sub("[path]", text)
    text = _UNIX_HOME_RE.sub("[path]", text)
    text = _PUBLIC_IP_RE.sub("[ip]", text)
    return text


def build_failure_replay_case(
    event: Mapping[str, Any],
    *,
    replay_key: str,
    surface: str,
    operation: str,
) -> dict[str, Any]:
    if replay_key not in REPLAY_KEYS:
        raise ValueError(f"unsupported replay key: {replay_key}")
    sanitized = sanitize_replay_value(dict(event))
    identity = json.dumps(
        {
            "replay_key": replay_key,
            "surface": surface,
            "operation": operation,
            "type": sanitized.get("type") or sanitized.get("event_type"),
            "level": sanitized.get("level"),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return {
        "schema_version": 1,
        "case_id": f"failure-{fingerprint}",
        "replay_key": replay_key,
        "surface": str(surface)[:40],
        "operation": str(operation)[:60],
        "symptom_code": str(
            event.get("symptom_code") or event.get("type") or "unknown_failure"
        )[:80],
        "observed": sanitized,
    }


def validate_failure_replay_case(case: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "case_id",
        "replay_key",
        "surface",
        "operation",
        "symptom_code",
        "observed",
    }
    missing = required - set(case)
    if missing:
        raise ValueError(f"missing replay fields: {sorted(missing)}")
    if case.get("schema_version") != 1:
        raise ValueError("unsupported replay schema")
    if case.get("replay_key") not in REPLAY_KEYS:
        raise ValueError(f"unsupported replay key: {case.get('replay_key')}")
    serialized = json.dumps(case, ensure_ascii=False)
    if _EMAIL_RE.search(serialized) or _WINDOWS_PATH_RE.search(serialized):
        raise ValueError("replay case contains identifiable user data")
