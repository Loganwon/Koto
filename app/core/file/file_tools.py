# -*- coding: utf-8 -*-
"""File tools facade - moved to app.core.agent.toolkits.builtin.file_tools_plugin."""

from __future__ import annotations

from app.core.agent.toolkits.builtin.file_tools_plugin import (
    FileToolsPlugin,
    register_file_tools,
)

__all__ = ["FileToolsPlugin", "register_file_tools"]
