# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
# 延迟导入蓝图 - 避免启动时加载重型依赖
def __getattr__(name):
    if name == "task_bp":
        from .task_routes import task_bp

        return task_bp
    if name == "job_bp":
        from .job_routes import job_bp

        return job_bp
    if name == "plugin_protocol_bp":
        from .plugin_protocol_routes import plugin_protocol_bp

        return plugin_protocol_bp
    if name == "goal_bp":
        from .goal_routes import goal_bp

        return goal_bp
    if name == "file_hub_bp":
        from .file_hub_routes import file_hub_bp

        return file_hub_bp
    if name == "ops_bp":
        from .ops_routes import ops_bp

        return ops_bp
    if name == "telegram_bot_bp":
        from .telegram_bot_routes import telegram_bot_bp

        return telegram_bot_bp
    if name == "mcp_bp":
        from .mcp_routes import mcp_bp

        return mcp_bp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
