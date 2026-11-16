# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
# 延迟导入 - 这些类仅在运行时首次使用时加载，减少启动耗时。
def __getattr__(name):
    if name == "ToolRouter":
        from .tool_router import ToolRouter

        return ToolRouter
    elif name == "get_tool_router":
        from .tool_router import get_tool_router

        return get_tool_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
