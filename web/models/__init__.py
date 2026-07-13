# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Model-related subpackage -- resolver, capabilities, display helpers."""

from web.models.resolver import (
    init_resolver,
    model_supports_locked_task,
    pick_available_fallback_model,
    resolve_model_alias,
    resolve_model_lock_task,
    resolve_requested_model_id,
)

__all__ = [
    "init_resolver",
    "model_supports_locked_task",
    "pick_available_fallback_model",
    "resolve_model_alias",
    "resolve_model_lock_task",
    "resolve_requested_model_id",
]