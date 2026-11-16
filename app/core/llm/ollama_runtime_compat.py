# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Inspect whether an installed Ollama runtime can load a selected model."""

from __future__ import annotations

import re
from typing import Any

import requests


def _response_error_text(response: Any) -> str:
    try:
        payload = response.json() or {}
        if isinstance(payload, dict):
            return str(payload.get("error") or payload.get("message") or "").strip()
    except (TypeError, ValueError, requests.exceptions.JSONDecodeError):
        pass
    return str(getattr(response, "text", "") or "").strip()


def _classify_show_failure(response: Any) -> tuple[str, str]:
    """Classify an Ollama ``/api/show`` failure without loading model weights."""
    detail = _response_error_text(response)
    normalized = detail.casefold()
    required = ""
    match = re.search(
        r"(?:requires?|need(?:s|ed)?)(?:\s+(?:ollama|version))*\s+v?([0-9]+(?:\.[0-9]+){1,2})",
        normalized,
    )
    if match:
        required = match.group(1)
    if any(
        token in normalized
        for token in (
            "newer version of ollama",
            "upgrade ollama",
            "requires ollama",
            "not supported by this version",
            "unsupported model architecture",
        )
    ):
        return "runtime_outdated", required
    if any(
        token in normalized
        for token in ("unable to load model", "failed to load model", "invalid model")
    ):
        return "model_load_failed", required
    if getattr(response, "status_code", 0) == 404 or "not found" in normalized:
        return "model_not_installed", required
    return "compatibility_probe_failed", required


def _version_tuple(value: Any) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", str(value or ""))
    return tuple(int(part) for part in numbers[:3])


def version_is_at_least(current: str, required: str) -> bool | None:
    """Compare numeric Ollama versions, returning None when either is unknown."""
    current_parts = _version_tuple(current)
    required_parts = _version_tuple(required)
    if not current_parts or not required_parts:
        return None
    width = max(len(current_parts), len(required_parts))
    return current_parts + (0,) * (width - len(current_parts)) >= required_parts + (
        0,
    ) * (width - len(required_parts))


def inspect_ollama_model_compatibility(
    model_tag: str,
    *,
    base_url: str = "http://127.0.0.1:11434",
    timeout: float = 3.0,
) -> dict[str, Any]:
    """Return runtime/model version compatibility without loading model weights."""
    model_tag = str(model_tag or "").strip()
    result: dict[str, Any] = {
        "model_id": model_tag,
        "current_version": "",
        "required_version": "",
        "compatible": None,
    }
    if not model_tag:
        return result

    endpoint = base_url.rstrip("/")
    try:
        version_response = requests.get(
            f"{endpoint}/api/version",
            timeout=timeout,
            proxies={"http": None, "https": None},
        )
        version_response.raise_for_status()
        result["current_version"] = str(
            (version_response.json() or {}).get("version") or ""
        ).strip()

        show_response = requests.post(
            f"{endpoint}/api/show",
            json={"model": model_tag},
            timeout=timeout,
            proxies={"http": None, "https": None},
        )
        try:
            show_response.raise_for_status()
        except requests.RequestException as exc:
            reason, required = _classify_show_failure(show_response)
            result["reason"] = reason
            result["inspection_error"] = type(exc).__name__
            result["required_version"] = required
            if reason == "runtime_outdated":
                result["compatible"] = False
            return result
        result["required_version"] = str(
            (show_response.json() or {}).get("requires") or ""
        ).strip()
        result["compatible"] = version_is_at_least(
            result["current_version"], result["required_version"]
        )
    except (requests.RequestException, TypeError, ValueError) as exc:
        result["inspection_error"] = type(exc).__name__
        result["reason"] = "ollama_unreachable"
    return result


__all__ = ["inspect_ollama_model_compatibility", "version_is_at_least"]
