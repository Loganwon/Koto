# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Explicit runtime facade for settings and model-management routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModelRuntimeState:
    model_manager: Any
    model_manager_available: bool
    model_map: dict
    model_info: dict
    fallback_model: str
    interactions_only_models: set[str]
    get_display_name: Callable[[str], str]
    initialize_model_manager: Callable[[], None]


@dataclass(frozen=True)
class SettingsRuntimeServices:
    get_app_version: Callable[[], str]
    get_api_key: Callable[[], str]
    get_project_root: Callable[[], str]
    get_workspace_dir: Callable[[], str]
    get_settings_manager: Callable[[], Any]
    get_detected_proxy: Callable[[], Any]
    get_force_proxy: Callable[[], str]
    reset_client_cache: Callable[[], None]
    update_workspace_dir: Callable[[str], None]
    update_chat_dir: Callable[[str], None]
    reset_proxy_detection: Callable[[], None]
    get_model_runtime: Callable[[], ModelRuntimeState]


_services: SettingsRuntimeServices | None = None


def configure_settings_runtime_services(services: SettingsRuntimeServices) -> None:
    global _services
    _services = services


def _require_services() -> SettingsRuntimeServices:
    if _services is None:
        raise RuntimeError("Settings runtime services are not configured")
    return _services


def get_app_version(default: str = "") -> str:
    return str(_require_services().get_app_version() or default or "")


def get_api_key() -> str:
    return str(_require_services().get_api_key() or "")


def get_project_root() -> str:
    return str(_require_services().get_project_root() or "")


def get_workspace_dir() -> str:
    return str(_require_services().get_workspace_dir() or "")


def get_settings_manager() -> Any:
    return _require_services().get_settings_manager()


def get_detected_proxy() -> Any:
    return _require_services().get_detected_proxy()


def get_force_proxy() -> str:
    return str(_require_services().get_force_proxy() or "")


def reset_client_cache() -> None:
    _require_services().reset_client_cache()


def update_workspace_dir(path: str) -> None:
    _require_services().update_workspace_dir(path)


def update_chat_dir(path: str) -> None:
    _require_services().update_chat_dir(path)


def reset_proxy_detection() -> None:
    _require_services().reset_proxy_detection()


def get_model_runtime() -> ModelRuntimeState:
    return _require_services().get_model_runtime()
