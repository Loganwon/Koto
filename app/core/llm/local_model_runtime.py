# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Canonical read-only access to the configured local-model runtime state."""

from __future__ import annotations


def get_configured_local_model_tag() -> str:
    """Return the user-selected Ollama model tag, or an empty string."""
    try:
        from app.core.config.user_settings import SettingsManager

        settings = SettingsManager().get_all()
        return str(
            settings.get("local_model")
            or (settings.get("ai") or {}).get("local_model")
            or ""
        ).strip()
    except Exception:
        return ""


def get_configured_model_mode() -> str:
    """Return the persisted inference mode without any UI-specific aliases."""
    try:
        from app.core.config.user_settings import SettingsManager

        return (
            str(SettingsManager().get_all().get("model_mode") or "cloud")
            .strip()
            .lower()
        )
    except Exception:
        return "cloud"
