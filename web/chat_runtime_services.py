# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Explicit runtime services for chat, session, and chat-stream handlers.

The web application configures this small container during startup.  Consumers
resolve the callbacks at request time, so runtime replacements remain visible
without importing the application module or using the legacy reflection bridge.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChatRuntimeServices:
    get_brain: Callable[[], Any]
    get_session_manager: Callable[[], Any]
    get_model_map: Callable[[], dict]
    get_interrupt_manager: Callable[[], Any]
    get_interrupt_flags: Callable[[], dict]
    get_smart_dispatcher: Callable[[], Any]
    get_web_searcher: Callable[[], Any]
    get_local_executor: Callable[[], Any]
    get_default_chat_system_instruction: Callable[[], str]
    get_create_client: Callable[[], Any]
    get_utils: Callable[[], Any]
    get_chat_stream_handler: Callable[[], Callable[..., Any]]


_services: ChatRuntimeServices | None = None


def configure_chat_runtime_services(services: ChatRuntimeServices) -> None:
    global _services
    _services = services


def _require_services() -> ChatRuntimeServices:
    if _services is None:
        raise RuntimeError("Chat runtime services are not configured")
    return _services


def get_brain() -> Any:
    return _require_services().get_brain()


def get_session_manager() -> Any:
    return _require_services().get_session_manager()


def get_model_map() -> dict:
    return _require_services().get_model_map() or {}


def get_interrupt_manager() -> Any:
    return _require_services().get_interrupt_manager()


def get_interrupt_flags() -> dict:
    return _require_services().get_interrupt_flags()


def get_smart_dispatcher() -> Any:
    return _require_services().get_smart_dispatcher()


def get_web_searcher() -> Any:
    return _require_services().get_web_searcher()


def get_local_executor() -> Any:
    return _require_services().get_local_executor()


def get_default_chat_system_instruction() -> str:
    return str(_require_services().get_default_chat_system_instruction() or "")


def get_create_client() -> Any:
    return _require_services().get_create_client()


def get_utils() -> Any:
    return _require_services().get_utils()


def get_chat_stream_handler() -> Callable[..., Any]:
    return _require_services().get_chat_stream_handler()


def resolve_requested_model_id(
    requested_model: str,
    fallback_model: str = "",
    task_type: str = "CHAT",
) -> str:
    """Resolve a public model selection without consulting the app bridge."""
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

    from app.core.llm.provider_boundary import normalize_public_model

    return normalize_public_model(
        str(requested_model or "").strip() or fallback_model or "deepseek-chat"
    )
