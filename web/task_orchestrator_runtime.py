# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

from typing import Any


def get_interactions_fallback_model() -> str:
    from web.runtime_context import get_interactions_fallback_model as _get_model

    return _get_model()


def call_interactions_api_sync(*args: Any, **kwargs: Any) -> Any:
    from web.runtime_context import call_interactions_api_sync as _call_api

    return _call_api(*args, **kwargs)


def get_filegen_brief_instruction() -> str:
    from web.runtime_context import get_filegen_brief_instruction as _get_instruction

    return _get_instruction()


class ClientProxy:
    def __getattr__(self, name: str) -> Any:
        from web.runtime_context import get_client_proxy

        return getattr(get_client_proxy(), name)


class SettingsManagerProxy:
    def __getattr__(self, name: str) -> Any:
        from web.runtime_context import get_settings_manager

        return getattr(get_settings_manager(), name)

    def get(self, *args: Any, **kwargs: Any) -> Any:
        from web.runtime_context import get_settings_manager

        return get_settings_manager().get(*args, **kwargs)


class ModelMapProxy:
    def get(self, key: str, default: Any = None) -> Any:
        from web.runtime_context import get_model_map

        return get_model_map().get(key, default)


class SmartDispatcherProxy:
    def __getattr__(self, name: str) -> Any:
        from web.runtime_context import get_smart_dispatcher

        return getattr(get_smart_dispatcher(), name)


class WorkspaceDirProxy:
    def __fspath__(self) -> str:
        from web.runtime_context import get_workspace_dir

        return get_workspace_dir()

    def __str__(self) -> str:
        return self.__fspath__()


client = ClientProxy()
settings_manager = SettingsManagerProxy()
MODEL_MAP = ModelMapProxy()
SmartDispatcher = SmartDispatcherProxy()
WORKSPACE_DIR = WorkspaceDirProxy()
