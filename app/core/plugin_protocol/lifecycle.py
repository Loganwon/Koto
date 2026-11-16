# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Plugin lifecycle — host context, health, and the KotoPlugin protocol.

Re-exports the canonical implementation from app.core.agent.plugin_protocol.
"""

from app.core.agent.plugin_protocol.lifecycle import (
    AddonInvocationContext,
    KotoPlugin,
    PluginHealth,
    PluginHealthStatus,
    PluginHostContext,
)

__all__ = [
    "AddonInvocationContext",
    "KotoPlugin",
    "PluginHealth",
    "PluginHealthStatus",
    "PluginHostContext",
]
