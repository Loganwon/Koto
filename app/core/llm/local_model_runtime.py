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
    """Return the persisted inference mode in the shared ``cloud``/``local`` form.

    Older releases persisted provider names such as ``deepseek`` and ``ollama``.
    They describe the same two user-visible choices, but exposing them to each
    caller made the chat panel, file tasks, and settings disagree about which
    model was active.  Keep the compatibility read here and give every runtime
    consumer one canonical value.
    """
    try:
        from app.core.config.user_settings import SettingsManager

        stored = (
            str(SettingsManager().get_all().get("model_mode") or "cloud")
            .strip()
            .lower()
        )
        return "local" if stored in {"local", "ollama"} else "cloud"
    except Exception:
        return "cloud"
