# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Bind settings runtime services to the application-owned state at startup."""

from __future__ import annotations

import os
import threading
from collections.abc import MutableMapping
from typing import Any

from web.settings_runtime_services import (
    ModelRuntimeState,
    SettingsRuntimeServices,
    configure_settings_runtime_services,
)


def configure_settings_runtime_services_from_app_globals(
    state: MutableMapping[str, Any],
) -> None:
    """Install explicit settings callbacks over the app's startup state.

    The mapping is supplied by the assembly module; this adapter never imports
    it directly.  Keeping the mutable-key boundary here prevents settings
    routes from reaching into application globals themselves.
    """

    def reset_client_cache() -> None:
        state["_client"] = None
        state["_client_mode_key"] = (None, None)

    def update_storage_dir(kind: str, path: str) -> None:
        if kind == "workspace":
            from web.shared import update_workspace_root

            path = update_workspace_root(path)
            state["WORKSPACE_DIR"] = path
        elif kind == "chat":
            state["CHAT_DIR"] = path
        os.makedirs(path, exist_ok=True)

    def reset_proxy_detection() -> None:
        state["_proxy_checked"] = False
        state["_detected_proxy"] = None
        threading.Thread(target=state["get_detected_proxy"], daemon=True).start()

    def model_runtime() -> ModelRuntimeState:
        return ModelRuntimeState(
            model_manager=state["_model_manager"],
            model_manager_available=state["_model_manager_available"],
            model_map=state["MODEL_MAP"],
            model_info=state["MODEL_INFO"],
            fallback_model=state["_INTERACTIONS_FALLBACK_MODEL"],
            interactions_only_models=state["_INTERACTIONS_ONLY_MODELS"],
            get_display_name=state["get_model_display_name"],
            initialize_model_manager=state["_init_model_manager"],
        )

    configure_settings_runtime_services(
        SettingsRuntimeServices(
            get_app_version=lambda: state["APP_VERSION"],
            get_api_key=lambda: state["API_KEY"],
            get_project_root=lambda: state["PROJECT_ROOT"],
            get_workspace_dir=lambda: state["WORKSPACE_DIR"],
            get_settings_manager=lambda: state["settings_manager"],
            get_detected_proxy=lambda: state["get_detected_proxy"](),
            get_force_proxy=lambda: state["FORCE_PROXY"],
            reset_client_cache=reset_client_cache,
            update_workspace_dir=lambda path: update_storage_dir("workspace", path),
            update_chat_dir=lambda path: update_storage_dir("chat", path),
            reset_proxy_detection=reset_proxy_detection,
            get_model_runtime=model_runtime,
        )
    )
