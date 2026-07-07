# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Service registry with lifecycle management.

Provides lazy access to runtime services while decoupling consumers from
the monolithic ``web.app`` module.  New code should use
:func:`service_registry` instead of calling individual ``get_*`` helpers.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
import logging
import sys
from typing import Any

_logger = logging.getLogger(__name__)

# ?? Internal module resolution ??????????????????????????????

def _app_module() -> Any:
    """Resolve the runtime application module (``web.app`` or ``__main__``)."""

    def _is_app(candidate: Any) -> bool:
        return candidate is not None and (
            hasattr(candidate, "settings_manager") or hasattr(candidate, "app")
        )

    for name in ("web.app", "__main__", "app"):
        module = sys.modules.get(name)
        if _is_app(module):
            return module
    return importlib.import_module("web.app")


# ?? Service registry ????????????????????????????????????????

class ServiceRegistry:
    """Lazy service container with lifecycle hooks.

    Usage::

        from web.runtime_context import service_registry
        session_mgr = service_registry.session_manager
        brain      = service_registry.brain
    """

    def __init__(self) -> None:
        self._module: Any = None
        self._cache: dict[str, Any] = {}
        self._shutdown_hooks: list[Callable[[], None]] = []
        self._factories: dict[str, Callable[[], Any]] = {}

    # -- module access --

    @property
    def module(self) -> Any:
        if self._module is None:
            self._module = _app_module()
        return self._module

    def _get(self, attr: str, required: bool = True) -> Any:
        if attr in self._cache:
            return self._cache[attr]
        value = getattr(self.module, attr, None)
        if value is None and required:
            raise RuntimeError(f"Runtime service unavailable: {attr}")
        self._cache[attr] = value
        return value

    def invalidate(self, *attrs: str) -> None:
        """Clear cached service references (useful after hot-reload)."""
        for attr in attrs:
            self._cache.pop(attr, None)
        if not attrs:
            self._cache.clear()

    def on_shutdown(self, hook: Callable[[], None]) -> None:
        """Register a function to call on application shutdown."""
        self._shutdown_hooks.append(hook)

    def shutdown(self) -> None:
        """Call all registered shutdown hooks."""
        for hook in self._shutdown_hooks:
            try:
                hook()
            except Exception:
                _logger.exception("Shutdown hook failed: %s", hook)

    # -- typed service accessors --

    @property
    def settings_manager(self) -> Any:
        return self._get("settings_manager")

    @property
    def session_manager(self) -> Any:
        return self._get("session_manager")

    @property
    def brain(self) -> Any:
        return self._get("brain")

    @property
    def client(self) -> Any:
        return self._get("client")

    @property
    def model_map(self) -> dict:
        model_map = self._get("MODEL_MAP", required=False)
        return model_map if isinstance(model_map, dict) else {}

    @property
    def interrupt_manager(self) -> Any:
        return self._get("_interrupt_manager", required=False)

    @property
    def workspace_dir(self) -> str:
        return str(getattr(self.module, "WORKSPACE_DIR", "") or "")

    @property
    def project_root(self) -> str:
        return str(getattr(self.module, "PROJECT_ROOT", "") or "")


# Singleton
service_registry = ServiceRegistry()


# ?? Backward-compatible getters ?????????????????????????????
# These remain for existing blueprint code.  New imports should use
# ``service_registry.<property>`` directly.

def get_app_module() -> Any:
    return service_registry.module

def get_client() -> Any:
    return service_registry.client

def get_client_proxy() -> Any:
    return service_registry.client

def get_types() -> Any:
    return service_registry._get("types", required=False)

def get_model_map() -> dict:
    return service_registry.model_map

def get_workspace_dir() -> str:
    return service_registry.workspace_dir

def get_project_root() -> str:
    return service_registry.project_root

def get_settings_manager() -> Any:
    return service_registry.settings_manager

def get_app_attr(name: str, default: Any = None) -> Any:
    return getattr(service_registry.module, name, default)

def get_utils() -> Any:
    from web.utils.assistant_utils import Utils
    return Utils

def get_session_manager() -> Any:
    return service_registry.session_manager

def get_brain() -> Any:
    return service_registry.brain

def get_interrupt_manager() -> Any:
    return service_registry.interrupt_manager

def get_memory_manager() -> Any:
    return service_registry._get("memory_manager", required=False)


# ?? Domain-specific helpers (kept for convenience) ??????????

def get_model_id(task_type: str = "CHAT", default: str = "") -> str:
    """Return the best model id for a task type.

    Uses the configured cloud model when available, falling back to
    the MODEL_MAP entry or the explicit ``default``.
    """
    fallback = str(service_registry.model_map.get(task_type, default) or default)
    try:
        from app.core.llm.model_selection import get_configured_cloud_model
        return get_configured_cloud_model(task_type=task_type, fallback_model=fallback) or fallback
    except Exception:
        return fallback or "deepseek-chat"

def get_smart_dispatcher() -> Any:
    return service_registry._get("SmartDispatcher")

def get_web_searcher() -> Any:
    return service_registry._get("WebSearcher")

def get_local_executor() -> Any:
    return service_registry._get("LocalExecutor")

def get_interrupt_flags() -> dict:
    return getattr(service_registry.module, "_interrupt_flags", {})

def get_default_chat_system_instruction() -> str:
    return str(getattr(service_registry.module, "default_chat_system_instruction", "") or "")

def get_chat_stream_handler() -> Any:
    return service_registry._get("ChatStreamHandler", required=False)

def get_operation_history() -> Any:
    return service_registry._get("operation_history", required=False)

def get_create_client() -> Any:
    return service_registry._get("create_client", required=False)

def get_app_version(default: str = "") -> str:
    return str(getattr(service_registry.module, "APP_VERSION", default) or default)

def get_api_key(default: str = "") -> str:
    return str(getattr(service_registry.module, "API_KEY", default) or default)

def get_detected_proxy() -> Any:
    return service_registry._get("detected_proxy", required=False)
def resolve_requested_model_id(
    requested_model: str,
    fallback_model: str = "",
    task_type: str = "CHAT",
) -> str:
    """解析用户请求的模型 ID 为实际可用模型。

    - "auto" / "cloud" / 空 → 使用配置的云端模型
    - 其他 → 直接返回请求的模型 ID
    """
    normalized = str(requested_model or "").strip().lower()
    if not normalized or normalized in {"auto", "cloud"}:
        try:
            from app.core.llm.model_selection import get_configured_cloud_model
            configured = get_configured_cloud_model(
                task_type=task_type,
                fallback_model=fallback_model,
            )
            if configured:
                return configured
        except Exception:
            pass
        return fallback_model or "deepseek-chat"
    return str(requested_model or "").strip() or fallback_model or "deepseek-chat"
# ── Editor AI / Compat stubs (delegated to app module) ────────────────────

def get_configured_local_model_id(default: str = "") -> str:
    """Return configured local model id from settings."""
    try:
        from web.config import _load_user_settings
        settings = _load_user_settings()
        return str(settings.get("local_model", "") or default).strip() or default
    except Exception:
        return default

def safe_editor_sse(data: str, event: str = "message") -> str:
    """Format data as SSE event string."""
    return f"event: {event}\ndata: {data}\n\n"

def normalize_model_mode(raw: str) -> str:
    """Normalize model mode string."""
    mode = str(raw or "").strip().lower()
    valid = {"local", "cloud", "deepseek", "gemini"}
    return mode if mode in valid else "cloud"

def stream_file_task_request(*args, **kwargs):
    """Delegate to web.file_task_stream.stream_file_task_request (the real implementation)."""
    import sys as _s_mod
    _fts_mod = _s_mod.modules.get("web.file_task_stream")
    if _fts_mod is None:
        import web.file_task_stream as _fts_mod
    if _fts_mod and hasattr(_fts_mod, "stream_file_task_request") and callable(_fts_mod.stream_file_task_request):
        return _fts_mod.stream_file_task_request(*args, **kwargs)
    raise RuntimeError("stream_file_task_request not available in web.file_task_stream")
