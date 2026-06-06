# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Lightweight accessors for runtime globals still owned by ``web.app``.

This module is intentionally small. It lets blueprints and lower-level helpers
avoid importing symbols directly from the monolithic app module while the
remaining globals are migrated into narrower services.
"""

from __future__ import annotations

import importlib
import json
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


def call_app_factory(name: str, *args: Any, **kwargs: Any) -> Any:
    factory = get_app_attr(name)
    if not callable(factory):
        raise RuntimeError(f"web.app factory is unavailable: {name}")
    return factory(*args, **kwargs)


def safe_editor_sse(payload: dict) -> str:
    safe_sse = getattr(_app_module(), "_editor_ai_safe_sse", None)
    if callable(safe_sse):
        return safe_sse(payload)
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def normalize_model_mode(value: Any, default: str = "cloud") -> str:
    normalizer = getattr(_app_module(), "normalize_model_mode", None)
    if callable(normalizer):
        return str(normalizer(value, default=default))
    candidate = str(value or default or "cloud").strip().lower()
    return candidate if candidate in {"cloud", "local", "auto"} else str(default or "cloud")


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


def stream_file_task_request(data: dict) -> Iterable[str]:
    streamer = getattr(_app_module(), "_stream_file_task_request", None)
    if not callable(streamer):
        yield safe_editor_sse({"type": "error", "text": "文件任务运行时不可用"})
        return
    yield from streamer(data)
