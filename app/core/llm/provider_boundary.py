from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .deepseek_config import DEEPSEEK_DEFAULT_MODEL

ACTIVE_CLOUD_PROVIDER = "deepseek"
ACTIVE_CLOUD_MODEL = DEEPSEEK_DEFAULT_MODEL
_LEGACY_PROVIDER_NAMES = frozenset({"gemini"})
_LEGACY_MODEL_PREFIXES = ("gemini-", "nano-banana-", "imagen-", "deep-research-")


def normalize_public_provider(value: Any) -> str:
    """Return the only cloud provider exposed by current UI/API surfaces."""
    normalized = str(value or "").strip().lower()
    if normalized in _LEGACY_PROVIDER_NAMES or normalized != ACTIVE_CLOUD_PROVIDER:
        return ACTIVE_CLOUD_PROVIDER
    return normalized


def normalize_public_model(value: Any) -> str:
    """Prevent archived Google model identifiers leaking into active UI state."""
    normalized = str(value or "").strip()
    lowered = normalized.lower()
    if not normalized or lowered.startswith(_LEGACY_MODEL_PREFIXES):
        return ACTIVE_CLOUD_MODEL
    return normalized


def is_legacy_public_model(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized.startswith(_LEGACY_MODEL_PREFIXES)


def sanitize_public_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Copy and normalize persisted settings before they cross the HTTP boundary."""
    payload = deepcopy(dict(settings))
    payload["model_mode"] = (
        "local" if str(payload.get("model_mode") or "").lower() == "local" else "cloud"
    )
    ai = payload.get("ai")
    if not isinstance(ai, dict):
        ai = {}
        payload["ai"] = ai
    ai["cloud_provider"] = ACTIVE_CLOUD_PROVIDER
    ai["deepseek_model"] = normalize_public_model(ai.get("deepseek_model"))
    ai["cloud_model"] = normalize_public_model(ai.get("cloud_model"))
    ai["default_model"] = normalize_public_model(ai.get("default_model"))
    for legacy_key in ("gemini_model", "gemini_api_key", "google_api_key"):
        ai.pop(legacy_key, None)
    return payload
