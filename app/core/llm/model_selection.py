from __future__ import annotations

import os
from typing import Any

from .deepseek_config import DEEPSEEK_DEFAULT_MODEL

CLOUD_PROVIDER_NAMES = {"deepseek"}  # Gemini archived
PROVIDER_MODEL_MODES = CLOUD_PROVIDER_NAMES | {"ollama"}
DEFAULT_CLOUD_PROVIDER = "deepseek"
ARCHIVED_CLOUD_MODEL_PREFIXES = (
    "gemini-",
    "nano-banana-",
    "imagen-",
    "deep-research-",
)

_PROVIDER_MODEL_DEFAULTS = {
    "deepseek": DEEPSEEK_DEFAULT_MODEL,
}

_UNSUPPORTED_DEEPSEEK_BINARY_TASKS = {"PAINTER", "VISION"}


def normalize_cloud_provider(value: Any, default: str = DEFAULT_CLOUD_PROVIDER) -> str:
    provider = str(value or "").strip().lower()
    if provider in CLOUD_PROVIDER_NAMES:
        return provider
    default_provider = str(default or DEFAULT_CLOUD_PROVIDER).strip().lower()
    return (
        default_provider
        if default_provider in CLOUD_PROVIDER_NAMES
        else DEFAULT_CLOUD_PROVIDER
    )


def is_archived_cloud_model(model_id: Any) -> bool:
    normalized = str(model_id or "").strip().lower()
    return any(normalized.startswith(prefix) for prefix in ARCHIVED_CLOUD_MODEL_PREFIXES)


def get_configured_cloud_provider(default: str = DEFAULT_CLOUD_PROVIDER) -> str:
    env_provider = os.getenv("KOTO_CLOUD_PROVIDER") or os.getenv("KOTO_LLM_PROVIDER")
    if env_provider:
        return normalize_cloud_provider(env_provider, default=default)
    try:
        from web.settings import SettingsManager

        configured = SettingsManager().get("ai", "cloud_provider")
        return normalize_cloud_provider(configured, default=default)
    except Exception:
        return normalize_cloud_provider(default, default=DEFAULT_CLOUD_PROVIDER)


def get_provider_for_model_mode(
    model_mode: str, default: str = DEFAULT_CLOUD_PROVIDER
) -> str:
    normalized = str(model_mode or "").strip().lower()
    if normalized in CLOUD_PROVIDER_NAMES:
        return normalized
    if normalized == "ollama":
        return "ollama"
    return get_configured_cloud_provider(default=default)


def get_configured_cloud_model(
    task_type: str = "CHAT",
    fallback_model: str = "",
    provider: str | None = None,
) -> str:
    provider_name = normalize_cloud_provider(
        provider or get_configured_cloud_provider(),
        default="deepseek",
    )
    task = str(task_type or "").strip().upper()
    if task in _UNSUPPORTED_DEEPSEEK_BINARY_TASKS:
        return str(fallback_model or "").strip()

    env_model = os.getenv(f"KOTO_{provider_name.upper()}_MODEL")
    if env_model and not is_archived_cloud_model(env_model):
        return env_model.strip()

    try:
        from web.settings import SettingsManager

        settings = SettingsManager()
        configured = settings.get("ai", f"{provider_name}_model") or settings.get(
            "ai", "cloud_model"
        )
        if configured and not is_archived_cloud_model(configured):
            return str(configured).strip()
    except Exception:
        pass

    return _PROVIDER_MODEL_DEFAULTS.get(
        provider_name, str(fallback_model or "").strip()
    )


def is_deepseek_model(model_id: str) -> bool:
    return str(model_id or "").strip().lower().startswith("deepseek")
