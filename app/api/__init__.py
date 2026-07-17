# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
# 延迟导入蓝图 - 避免启动时加载重型依赖
def __getattr__(name):
    if name == "agent_bp":
        from .agent_routes import agent_bp

        return agent_bp
    if name == "task_bp":
        from .task_routes import task_bp

        return task_bp
    if name == "job_bp":
        from .job_routes import job_bp

        return job_bp
    if name == "skill_bp":
        from .skill_routes import skill_bp

        return skill_bp
    if name == "marketplace_bp":
        from .skill_marketplace_routes import marketplace_bp

        return marketplace_bp
    if name == "goal_bp":
        from .goal_routes import goal_bp

        return goal_bp
    if name == "file_hub_bp":
        from .file_hub_routes import file_hub_bp

        return file_hub_bp
    if name == "ops_bp":
        from .ops_routes import ops_bp

        return ops_bp
    if name == "macro_bp":
        from .macro_routes import macro_bp

        return macro_bp
    if name == "telegram_bot_bp":
        from .telegram_bot_routes import telegram_bot_bp

        return telegram_bot_bp
    if name == "distill_bp":
        from .distill_routes import distill_bp

        return distill_bp
    if name == "bg_agent_bp":
        from .bg_agent_routes import bg_agent_bp

        return bg_agent_bp
    if name == "mcp_bp":
        from .mcp_routes import mcp_bp

        return mcp_bp
    if name == "training_bp":
        from .training_routes import training_bp

        return training_bp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
