from __future__ import annotations

import os
from collections.abc import Mapping
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
    return any(
        normalized.startswith(prefix) for prefix in ARCHIVED_CLOUD_MODEL_PREFIXES
    )


def get_configured_cloud_provider(default: str = DEFAULT_CLOUD_PROVIDER) -> str:
    env_provider = os.getenv("KOTO_CLOUD_PROVIDER") or os.getenv("KOTO_LLM_PROVIDER")
    if env_provider:
        return normalize_cloud_provider(env_provider, default=default)
    try:
        from app.core.config.user_settings import SettingsManager

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
        from app.core.config.user_settings import SettingsManager

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


def select_task_model(
    task_type: str,
    *,
    model_map: Mapping[str, str] | None = None,
    has_image: bool = False,
    complexity: str = "normal",
) -> str:
    """Select a configured model without classifying the user's text.

    Task type is an explicit transport/runtime contract supplied by the caller.
    This function deliberately contains no keywords, corpora, similarity model,
    history continuation, or free-form intent inference.
    """
    task = str(task_type or "CHAT").strip().upper() or "CHAT"
    mapping = dict(model_map or {})
    lookup_task = "VISION" if has_image and task != "PAINTER" else task
    if str(complexity or "normal").strip().lower() == "complex":
        preferred = mapping.get("COMPLEX") or mapping.get(lookup_task)
    else:
        preferred = mapping.get(lookup_task)
    preferred = preferred or mapping.get("CHAT") or "deepseek-chat"
    configured = get_configured_cloud_model(
        task_type=lookup_task,
        fallback_model=preferred,
    )
    selected = configured or preferred

    try:
        from app.core.llm.model_fallback import get_fallback_executor

        fallback = get_fallback_executor()
        if fallback and not fallback.is_available(selected):
            alternative = fallback.get_best_available(
                task_type=lookup_task,
                preferred=selected,
            )
            if alternative:
                selected = alternative
    except Exception:
        pass
    return selected


def is_deepseek_model(model_id: str) -> bool:
    return str(model_id or "").strip().lower().startswith("deepseek")


def resolve_requested_model_id(
    requested_model: str,
    fallback_model: str = "",
    task_type: str = "CHAT",
) -> str:
    """Resolve a public model choice against current provider policy."""

    normalized = str(requested_model or "").strip().lower()
    if not normalized or normalized in {"auto", "cloud"}:
        configured = get_configured_cloud_model(
            task_type=task_type,
            fallback_model=fallback_model,
        )
        return configured or fallback_model or "deepseek-chat"

    from app.core.llm.provider_boundary import normalize_public_model

    return normalize_public_model(
        str(requested_model or "").strip() or fallback_model or "deepseek-chat"
    )
