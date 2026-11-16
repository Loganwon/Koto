# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Service registry with lifecycle management.

Provides lazy access to runtime services while decoupling consumers from
the monolithic ``web.app`` module.  New code should use
the ``service_registry`` singleton instead of calling individual ``get_*`` helpers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import importlib
import logging
import os
import threading
from typing import Any

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelRuntimeState:
    """Read-only view of the model-selection state owned by ``web.app``."""

    model_manager: Any
    model_manager_available: bool
    model_map: dict
    model_info: dict
    fallback_model: str
    interactions_only_models: set[str]
    get_display_name: Callable[[str], str]
    initialize_model_manager: Callable[[], None]

# ?? Internal module resolution ??????????????????????????????

def _app_module() -> Any:
    """Return the one canonical runtime module.

    Runtime owners must bind it explicitly during application composition.
    Importing through ``__main__`` or an ambiguous top-level ``app`` module
    previously allowed different launchers to expose different service sets.
    """
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
        self._llm_gateway_mode_key: tuple[str, str] | None = None
        self._lock = threading.RLock()

    def bind_module(self, module: Any) -> None:
        """Bind the composed application module as the sole service owner."""
        if module is None:
            raise ValueError("runtime module is required")
        with self._lock:
            if self._module is not None and self._module is not module:
                raise RuntimeError("runtime module is already bound")
            self._module = module

    def register_factory(
        self,
        name: str,
        factory: Callable[[], Any],
        *,
        replace: bool = False,
    ) -> None:
        """Register one explicit service factory without constructing it."""
        key = str(name or "").strip()
        if not key:
            raise ValueError("service name is required")
        if not callable(factory):
            raise TypeError("service factory must be callable")
        with self._lock:
            if key in self._factories and not replace:
                raise RuntimeError(f"Runtime service factory already registered: {key}")
            self._factories[key] = factory
            self._cache.pop(key, None)

    def resolve(self, name: str) -> Any:
        """Resolve a registered service once and cache the constructed instance."""
        key = str(name or "").strip()
        if not key:
            raise ValueError("service name is required")
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            factory = self._factories.get(key)
            if factory is None:
                raise RuntimeError(f"Runtime service factory unavailable: {key}")
            value = factory()
            self._cache[key] = value
            return value

    # -- module access --

    @property
    def module(self) -> Any:
        if self._module is None:
            self._module = _app_module()
        return self._module

    def _get(self, attr: str, required: bool = True) -> Any:
        with self._lock:
            if attr in self._cache:
                return self._cache[attr]
            value = getattr(self.module, attr, None)
            if value is None and required:
                raise RuntimeError(f"Runtime service unavailable: {attr}")
            self._cache[attr] = value
            return value

    def invalidate(self, *attrs: str) -> None:
        """Clear cached service references (useful after hot-reload)."""
        with self._lock:
            for attr in attrs:
                self._cache.pop(attr, None)
            if not attrs:
                self._cache.clear()

    def on_shutdown(self, hook: Callable[[], None]) -> None:
        """Register a function to call on application shutdown."""
        with self._lock:
            self._shutdown_hooks.append(hook)

    def shutdown(self) -> None:
        """Call all registered shutdown hooks."""
        with self._lock:
            hooks = list(reversed(self._shutdown_hooks))
            self._shutdown_hooks.clear()
        for hook in hooks:
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
        # ``brain`` can be replaced during an in-process restart, model reload,
        # or an integration test.  Caching it leaves request handlers pointing
        # at an obsolete instance after the replacement is undone.
        value = getattr(self.module, "brain", None)
        if value is None:
            raise RuntimeError("Runtime service unavailable: brain")
        return value

    @property
    def llm_gateway(self) -> Any:
        from app.core.llm.local_model_runtime import (
            get_configured_local_model_tag,
            get_configured_model_mode,
        )
        from app.core.llm.runtime_gateway import create_runtime_llm_gateway

        mode_key = (
            get_configured_model_mode(),
            get_configured_local_model_tag(),
        )
        if self._llm_gateway_mode_key != mode_key:
            self._cache.pop("llm_gateway", None)
            self._llm_gateway_mode_key = mode_key
        if "llm_gateway" not in self._cache:
            self._cache["llm_gateway"] = create_runtime_llm_gateway()
        return self._cache["llm_gateway"]

    @property
    def model_map(self) -> dict:
        model_map = self._get("MODEL_MAP", required=False)
        return model_map if isinstance(model_map, dict) else {}

    @property
    def interrupt_manager(self) -> Any:
        return self._get("_interrupt_manager", required=False)

    @property
    def interrupt_flags(self) -> dict:
        flags = self._get("_interrupt_flags", required=False)
        return flags if isinstance(flags, dict) else {}

    @property
    def web_searcher(self) -> Any:
        return self._get("WebSearcher")

    @property
    def local_executor(self) -> Any:
        return self._get("LocalExecutor")

    @property
    def utils(self) -> Any:
        return self._get("Utils")

    @property
    def default_chat_system_instruction(self) -> str:
        return str(self._get("default_chat_system_instruction", required=False) or "")

    @property
    def chat_stream_handler(self) -> Callable[..., Any]:
        return self._get("chat_stream")

    @property
    def operation_history(self) -> Any:
        return self._get("operation_history", required=False)

    @property
    def batch_ops_manager(self) -> Any:
        return self.resolve("batch_ops_manager")

    @property
    def workspace_dir(self) -> str:
        # Workspace selection is mutable at runtime. Reading web.app's startup
        # snapshot here made file tasks keep using the previous directory.
        from app.core.config.workspace_runtime import get_workspace_root

        return get_workspace_root()

    @property
    def project_root(self) -> str:
        return str(getattr(self.module, "PROJECT_ROOT", "") or "")

    @property
    def app_version(self) -> str:
        return str(getattr(self.module, "APP_VERSION", "") or "")

    @property
    def detected_proxy(self) -> Any:
        detector = getattr(self.module, "get_detected_proxy", None)
        return detector() if callable(detector) else None

    @property
    def force_proxy(self) -> str:
        return str(getattr(self.module, "FORCE_PROXY", "") or "")

    @property
    def model_runtime(self) -> ModelRuntimeState:
        module = self.module
        model_map = getattr(module, "MODEL_MAP", None)
        if not isinstance(model_map, dict):
            model_map = {}
        get_display_name = getattr(module, "get_model_display_name", None)
        initialize_model_manager = getattr(module, "_init_model_manager", None)
        if not callable(get_display_name) or not callable(initialize_model_manager):
            raise RuntimeError("Model runtime is not available")
        return ModelRuntimeState(
            model_manager=getattr(module, "_model_manager", None),
            model_manager_available=bool(
                getattr(module, "_model_manager_available", False)
            ),
            model_map=model_map,
            model_info=getattr(module, "MODEL_INFO", None) or {},
            fallback_model=str(
                getattr(module, "_INTERACTIONS_FALLBACK_MODEL", "")
                or model_map.get("CHAT")
                or "deepseek-chat"
            ),
            interactions_only_models=set(
                getattr(module, "_INTERACTIONS_ONLY_MODELS", None) or ()
            ),
            get_display_name=get_display_name,
            initialize_model_manager=initialize_model_manager,
        )

    def reset_llm_gateway(self) -> None:
        self.invalidate("llm_gateway")

    def update_workspace_dir(self, path: str) -> str:
        from app.core.config.workspace_runtime import set_workspace_root

        resolved = set_workspace_root(path)
        os.makedirs(resolved, exist_ok=True)
        return resolved

    def update_chat_dir(self, path: str) -> str:
        from web.session_manager import set_chat_dir

        resolved = set_chat_dir(path)
        os.makedirs(resolved, exist_ok=True)
        return resolved

    def reset_proxy_detection(self) -> None:
        module = self.module
        module._proxy_checked = False
        module._detected_proxy = None
        detector = getattr(module, "get_detected_proxy", None)
        if callable(detector):
            threading.Thread(
                target=detector,
                name="ProxyDetectionRefresh",
                daemon=True,
            ).start()


# Singleton
service_registry = ServiceRegistry()


def _make_batch_ops_manager() -> Any:
    from web.files.batch_file_ops import BatchFileOpsManager

    return BatchFileOpsManager()


service_registry.register_factory("batch_ops_manager", _make_batch_ops_manager)
