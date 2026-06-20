# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Lightweight accessors for runtime globals still owned by ``web.app``.

This module is intentionally small. It lets blueprints and lower-level helpers
avoid importing symbols directly from the monolithic app module while the
remaining globals are migrated into narrower services.
"""

from __future__ import annotations

import importlib
import sys
from typing import Any, Iterable


def _app_module() -> Any:
    def _is_web_app_module(candidate: Any) -> bool:
        return candidate is not None and (
            hasattr(candidate, "settings_manager") or hasattr(candidate, "app")
        )

    module = sys.modules.get("web.app")
    if _is_web_app_module(module):
        return module
    module = sys.modules.get("__main__")
    if _is_web_app_module(module):
        return module
    module = sys.modules.get("app")
    if _is_web_app_module(module):
        return module
    return importlib.import_module("web.app")


def get_app_module() -> Any:
    return _app_module()


def get_client() -> Any:
    getter = getattr(_app_module(), "get_client", None)
    if callable(getter):
        return getter()
    return getattr(_app_module(), "client", None)


def get_client_proxy() -> Any:
    return getattr(_app_module(), "client", None)


def get_types() -> Any:
    return getattr(_app_module(), "types", None)


def get_model_map() -> dict:
    model_map = getattr(_app_module(), "MODEL_MAP", None)
    return model_map if isinstance(model_map, dict) else {}


def get_model_id(task: str, default: str = "") -> str:
    fallback = str(get_model_map().get(task, default) or default)
    try:
        from app.core.llm.model_selection import get_configured_cloud_model

        return get_configured_cloud_model(task_type=task, fallback_model=fallback) or fallback
    except Exception:
        return fallback


def get_workspace_dir() -> str:
    return str(getattr(_app_module(), "WORKSPACE_DIR", "") or "")


def get_project_root() -> str:
    return str(getattr(_app_module(), "PROJECT_ROOT", "") or "")


def get_settings_manager() -> Any:
    return getattr(_app_module(), "settings_manager", None)


def get_app_attr(name: str, default: Any = None) -> Any:
    return getattr(_app_module(), name, default)


def _required_app_attr(name: str) -> Any:
    value = get_app_attr(name)
    if value is None:
        raise RuntimeError(f"runtime service is unavailable: {name}")
    return value


def get_utils() -> Any:
    from web.utils.assistant_utils import Utils

    return Utils


def get_session_manager() -> Any:
    return _required_app_attr("session_manager")


def get_brain() -> Any:
    return _required_app_attr("brain")


def get_smart_dispatcher() -> Any:
    return _required_app_attr("SmartDispatcher")


def get_web_searcher() -> Any:
    return _required_app_attr("WebSearcher")


def get_local_executor() -> Any:
    return _required_app_attr("LocalExecutor")


def get_interrupt_manager() -> Any:
    return _required_app_attr("_interrupt_manager")


def get_interrupt_flags() -> dict:
    flags = _required_app_attr("_interrupt_flags")
    if not isinstance(flags, dict):
        raise RuntimeError("runtime interrupt flags are unavailable")
    return flags


def get_default_chat_system_instruction() -> str:
    getter = get_app_attr("_get_DEFAULT_CHAT_SYSTEM_INSTRUCTION")
    if callable(getter):
        return str(getter() or "")
    return ""


def get_chat_stream_handler() -> Any:
    return get_app_attr("chat_stream")


def get_memory_manager() -> Any:
    getter = get_app_attr("get_memory_manager")
    if callable(getter):
        return getter()
    return None


def get_operation_history() -> Any:
    return get_app_attr("operation_history")


def get_create_client() -> Any:
    return get_app_attr("create_client")


def get_app_version(default: str = "") -> str:
    return str(get_app_attr("APP_VERSION", default) or default)


def get_api_key(default: str = "") -> str:
    return str(get_app_attr("API_KEY", default) or default)


def get_detected_proxy() -> Any:
    detector = get_app_attr("get_detected_proxy")
    if callable(detector):
        return detector()
    return None


def get_behavior_monitor() -> Any:
    from web.lazy_loaders.monitoring_services import get_behavior_monitor as _get_service

    return _get_service()


def get_suggestion_engine() -> Any:
    from web.lazy_loaders.monitoring_services import get_suggestion_engine as _get_service

    return _get_service()


def get_insight_reporter() -> Any:
    from web.lazy_loaders.monitoring_services import get_insight_reporter as _get_service

    return _get_service()


def get_notification_manager() -> Any:
    from web.lazy_loaders.monitoring_services import get_notification_manager as _get_service

    return _get_service()


def get_proactive_dialogue() -> Any:
    from web.lazy_loaders.monitoring_services import get_proactive_dialogue as _get_service

    return _get_service()


def get_context_awareness() -> Any:
    from web.lazy_loaders.monitoring_services import get_context_awareness as _get_service

    return _get_service()


def get_trigger_system() -> Any:
    from web.lazy_loaders.monitoring_services import get_trigger_system as _get_service

    return _get_service()


def get_auto_execution() -> Any:
    from web.lazy_loaders.monitoring_services import get_auto_execution as _get_service

    return _get_service()


def get_knowledge_graph() -> Any:
    from web.lazy_loaders.knowledge_services import get_knowledge_graph as _get_service

    return _get_service()


def get_file_editor() -> Any:
    from web.lazy_loaders.file_services import get_file_editor as _get_service

    return _get_service()


def get_file_indexer() -> Any:
    from web.lazy_loaders.file_services import get_file_indexer as _get_service

    return _get_service()


def get_concept_extractor() -> Any:
    from web.lazy_loaders.knowledge_services import get_concept_extractor as _get_service

    return _get_service()


def get_file_organizer() -> Any:
    from web.lazy_loaders.file_services import get_file_organizer as _get_service

    return _get_service()


def get_file_analyzer() -> Any:
    from web.lazy_loaders.file_services import get_file_analyzer as _get_service

    return _get_service()


def get_batch_ops_manager() -> Any:
    from web.lazy_loaders.file_services import get_batch_ops_manager as _get_service

    return _get_service()


def get_organize_root() -> str:
    from web.config import get_organize_root as _get_service

    return str(_get_service() or "")


def call_app_factory(name: str, *args: Any, **kwargs: Any) -> Any:
    factory = get_app_attr(name)
    if not callable(factory):
        raise RuntimeError(f"web.app factory is unavailable: {name}")
    return factory(*args, **kwargs)


def safe_editor_sse(payload: dict) -> str:
    from web.file_task_stream import safe_editor_sse as _safe_editor_sse

    return _safe_editor_sse(payload)


def normalize_model_mode(value: Any, default: str = "deepseek") -> str:
    normalizer = getattr(_app_module(), "normalize_model_mode", None)
    if callable(normalizer):
        return str(normalizer(value, default=default))
    candidate = str(value or default or "deepseek").strip().lower()
    return candidate if candidate in {"cloud", "local", "auto", "gemini", "deepseek"} else str(default or "deepseek")


def resolve_requested_model_id(
    model_id: str,
    *,
    fallback_model: str = "",
    task_type: str = "CHAT",
) -> str:
    resolver = getattr(_app_module(), "_resolve_requested_model_id", None)
    if callable(resolver):
        return str(
            resolver(
                model_id,
                fallback_model=fallback_model,
                task_type=task_type,
            )
        )
    requested = str(model_id or "").strip()
    if requested and requested.lower() not in {"auto", "cloud", "local"}:
        return requested
    try:
        from app.core.llm.model_selection import get_configured_cloud_model

        resolved = get_configured_cloud_model(
            task_type=task_type,
            fallback_model=fallback_model or get_model_id(task_type, ""),
        )
        if resolved:
            return resolved
    except Exception:
        pass
    return str(fallback_model or get_model_id(task_type, ""))


def get_configured_local_model_id() -> str:
    getter = getattr(_app_module(), "_get_configured_local_model_id", None)
    if callable(getter):
        return str(getter() or "")
    settings = get_settings_manager()
    if settings is None:
        return ""
    try:
        return str(settings.get("ai", "local_model") or "")
    except Exception:
        return ""


def get_interactions_fallback_model(default: str = "gemini-3-flash-preview") -> str:
    return str(getattr(_app_module(), "_INTERACTIONS_FALLBACK_MODEL", default) or default)


def call_interactions_api_sync(*args: Any, **kwargs: Any) -> Any:
    helper = getattr(_app_module(), "_call_interactions_api_sync", None)
    if not callable(helper):
        raise RuntimeError("Interactions API runtime helper is unavailable")
    return helper(*args, **kwargs)


def get_filegen_brief_instruction() -> str:
    helper = getattr(_app_module(), "_get_filegen_brief_instruction", None)
    if callable(helper):
        return str(helper() or "")
    return ""


def stream_file_task_request(data: dict) -> Iterable[str]:
    from web.file_task_stream import stream_file_task_request as _stream_file_task_request

    yield from _stream_file_task_request(data)
