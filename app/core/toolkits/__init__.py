# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Namespaced tool projection used by the Koto MCP server.

Package structure:
  unified_tool_registry.py — outward-facing projection of canonical Kernel tools
  bootstrap.py             — deterministic projection bootstrap

Agent execution remains owned by ``app.core.agent.kernel.ToolCatalog`` and
``app.core.agent.tool_registry.ToolRegistry``. This package must not grow a
second executor or LLM-facing Agent registry.
"""

from app.core.toolkits.unified_tool_registry import (
    ToolRecord,
    ToolSource,
    UnifiedToolRegistry,
    get_unified_tool_registry,
    reset_unified_tool_registry,
)

__all__ = [
    "ToolSource",
    "ToolRecord",
    "UnifiedToolRegistry",
    "get_unified_tool_registry",
    "reset_unified_tool_registry",
]
