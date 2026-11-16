"""Small stdlib-only Ollama version checks shared by standalone installers."""

from __future__ import annotations

import json
import re
import urllib.request
from typing import Any, Dict


def _version_tuple(value: Any) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", str(value or ""))[:3])


def _json_request(url: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def inspect_model_compatibility(
    model_tag: str, endpoint: str = "http://127.0.0.1:11434"
) -> Dict[str, Any]:
    """Read Ollama's own model ``requires`` field and compare versions."""
    result: Dict[str, Any] = {
        "current_version": "",
        "required_version": "",
        "compatible": None,
    }
    try:
        result["current_version"] = str(
            _json_request(endpoint.rstrip("/") + "/api/version").get("version") or ""
        ).strip()
        result["required_version"] = str(
            _json_request(endpoint.rstrip("/") + "/api/show", {"model": model_tag}).get(
                "requires"
            )
            or ""
        ).strip()
        current = _version_tuple(result["current_version"])
        required = _version_tuple(result["required_version"])
        if current and required:
            width = max(len(current), len(required))
            result["compatible"] = current + (0,) * (
                width - len(current)
            ) >= required + (0,) * (width - len(required))
    except Exception as exc:
        result["inspection_error"] = type(exc).__name__
    return result


__all__ = ["inspect_model_compatibility"]
