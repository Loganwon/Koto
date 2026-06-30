# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from .smart_dispatcher import SmartDispatcher


# 延迟导入 - 这些类仅在运行时首次使用时加载，避免启动时加载 google.genai (~4.7s) 和 requests (~0.5s)
def __getattr__(name):
    if name == "LocalModelRouter":
        from .local_model_router import LocalModelRouter

        return LocalModelRouter
    elif name == "RouterDecision":
        from .local_model_router import RouterDecision

        return RouterDecision
    elif name == "AIRouter":
        from .ai_router import AIRouter

        return AIRouter
    elif name == "ToolRouter":
        from .tool_router import ToolRouter

        return ToolRouter
    elif name == "get_tool_router":
        from .tool_router import get_tool_router

        return get_tool_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
