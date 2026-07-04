from __future__ import annotations

import concurrent.futures
import importlib
import os
import threading
from logging import Logger

from flask import Flask

_blueprints_registered = False
_blueprints_lock = threading.Lock()

_PRELOAD_MODULES = [
    "app.api.task_routes",
    "app.api",
    "app.api.skill_routes",
    "app.api.skill_marketplace_routes",
    "app.api.goal_routes",
    "app.api.file_hub_routes",
    "app.api.job_routes",
    "app.api.mcp_routes",
    "app.api.ops_routes",
    "app.api.shadow_routes",
    "app.api.macro_routes",
    "web.blueprints.workflow_api",
]

_WEB_BLUEPRINT_CONFIGS = [
    ("web.blueprints.pages", "pages_bp", None, "Pages"),
    ("web.blueprints.sessions", "sessions_bp", None, "Sessions"),
    ("web.blueprints.settings", "settings_bp", None, "Settings"),
    ("web.blueprints.workspace", "workspace_bp", None, "Workspace"),
    ("web.blueprints.voice", "voice_bp", None, "VoiceBP"),
    ("web.blueprints.document", "document_bp", None, "Document"),
    ("web.blueprints.knowledge", "knowledge_bp", None, "Knowledge"),
    ("web.blueprints.misc_api", "misc_api_bp", None, "MiscAPI"),
    ("web.blueprints.analytics", "analytics_bp", None, "Analytics"),
    ("web.blueprints.proactive", "proactive_bp", None, "Proactive"),
    ("web.blueprints.execution", "execution_bp", None, "Execution"),
    ("web.blueprints.file_editor", "file_editor_bp", None, "FileEditor"),
    ("web.blueprints.file_organize", "file_organize_bp", None, "FileOrganize"),
    ("web.blueprints.token_stats", "token_stats_bp", None, "TokenStats"),
    ("web.blueprints.dev", "dev_bp", None, "Dev"),
    ("web.blueprints.chat", "chat_bp", None, "Chat"),
    ("web.blueprints.editor_ai", "editor_ai_bp", None, "EditorAI"),
    (
        "web.blueprints.workspace_assistant",
        "workspace_assistant_bp",
        None,
        "WorkspaceAssistant",
    ),
    ("web.blueprints.pptx_editor", "pptx_editor_bp", None, "PptxEditor"),
]


def _safe_preload(mod_name: str) -> None:
    try:
        importlib.import_module(mod_name)
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "Silenced exception caught",
            exc_info=True,
        )


def _exempt_csrf_endpoint(app: Flask, endpoint: str) -> None:
    csrf = getattr(app, "extensions", {}).get("csrf")
    exempt = getattr(csrf, "exempt", None)
    view_func = app.view_functions.get(endpoint)
    if callable(exempt) and view_func is not None:
        exempt(view_func)


def _exempt_csrf_blueprint(app: Flask, blueprint) -> None:
    csrf = getattr(app, "extensions", {}).get("csrf")
    exempt = getattr(csrf, "exempt", None)
    if callable(exempt):
        exempt(blueprint)


def register_blueprints_deferred(app: Flask, logger: Logger):
    """Register API and web blueprints once for the process."""
    global _blueprints_registered

    with _blueprints_lock:
        if _blueprints_registered:
            return None
        _blueprints_registered = True

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(6, len(_PRELOAD_MODULES)),
        thread_name_prefix="BpPreload",
    ) as pool:
        list(pool.map(_safe_preload, _PRELOAD_MODULES))

    agent_blueprint = None

    try:
        from web.app_http import configure_http_wiring

        configure_http_wiring(app, logger)
        logger.info("[HTTP] ✅ HTTP 基础中间件已注册")
    except Exception as exc:
        logger.error(f"[HTTP] ❌ HTTP 基础中间件注册失败: {exc}")

    try:
        from web.auth import register_auth_routes

        register_auth_routes(app)
        logger.info("[Auth] ✅ 认证 API 已注册")
    except ImportError as exc:
        logger.warning(f"[Auth] ⚠️ 未能导入认证 API: {exc}")
    except Exception as exc:
        logger.warning(f"[Auth] ⚠️ 认证 API 注册失败: {exc}")

    try:
        from app.api.task_routes import task_bp as _task_bp

        app.register_blueprint(_task_bp, url_prefix="/api/tasks")
        logger.info("[TaskAPI] ✅ 任务管理 API 已注册: /api/tasks")
    except ImportError as exc:
        logger.warning(f"[TaskAPI] ⚠️ 未能导入任务管理 API 蓝图: {exc}")
    except Exception as exc:
        logger.error(f"[TaskAPI] ❌ 任务管理 API 注册失败: {exc}")

    try:
        from app.api import agent_bp as _agent_bp

        agent_blueprint = _agent_bp
        app.register_blueprint(agent_blueprint, url_prefix="/api/agent")
        logger.info("[UnifiedAgent] ✅ 统一 Agent API 已注册: /api/agent")
    except ImportError as exc:
        logger.warning(f"[UnifiedAgent] ⚠️ 未能导入统一 Agent API 蓝图: {exc}")
    except Exception as exc:
        logger.error(f"[UnifiedAgent] ❌ 注册失败: {exc}")

    try:
        from app.api.skill_routes import skill_bp as _skill_bp

        app.register_blueprint(_skill_bp)
        logger.info("[SkillAPI] ✅ Skill CRUD API 已注册: /api/skills")
    except ImportError as exc:
        logger.warning(f"[SkillAPI] ⚠️ 未能导入 Skill API 蓝图: {exc}")
    except Exception as exc:
        logger.error(f"[SkillAPI] ❌ Skill API 注册失败: {exc}")

    try:
        from app.api.skill_marketplace_routes import marketplace_bp as _marketplace_bp

        app.register_blueprint(_marketplace_bp)
        logger.info("[SkillMarket] ✅ Skill Marketplace API 已注册: /api/skillmarket")
    except ImportError as exc:
        logger.warning(f"[SkillMarket] ⚠️ 未能导入 Skill Marketplace API 蓝图: {exc}")
    except Exception as exc:
        logger.error(f"[SkillMarket] ❌ Skill Marketplace API 注册失败: {exc}")

    if os.environ.get("KOTO_DEV_TRAINING") == "1":
        try:
            from app.api.training_routes import training_bp as _training_bp

            app.register_blueprint(_training_bp)
            logger.info("[TrainingAPI] ✅ 训练数据 API 已注册: /api/training/*")
        except ImportError as exc:
            logger.warning(f"[TrainingAPI] ⚠️ 未能导入训练数据模块: {exc}")
        except Exception as exc:
            logger.error(f"[TrainingAPI] ❌ 训练数据 API 注册失败: {exc}")

        try:
            from app.api.distill_routes import distill_bp as _distill_bp

            app.register_blueprint(_distill_bp, url_prefix="/api/distill")
            logger.info("[DistillAPI] ✅ LoRA 蒸馏训练 API 已注册（开发模式）: /api/distill")
        except ImportError as exc:
            logger.warning(f"[DistillAPI] ⚠️ 未能导入蒸馏训练模块: {exc}")
        except Exception as exc:
            logger.error(f"[DistillAPI] ❌ 蒸馏训练 API 注册失败: {exc}")
    else:
        logger.debug(
            "[DistillAPI] ℹ️ LoRA 训练 API 已封存（公共版），如需启用请设置 KOTO_DEV_TRAINING=1"
        )

    try:
        from web.ppt_api_routes import ppt_api_bp

        app.register_blueprint(ppt_api_bp)
        logger.info("[PPT_API] ✅ PPT 编辑 API 已注册: /api/ppt")
    except ImportError as exc:
        logger.warning(f"[PPT_API] ⚠️ 未能导入 PPT 编辑 API: {exc}")
    except Exception as exc:
        logger.warning(f"[PPT_API] ⚠️ PPT 编辑 API 注册失败: {exc}")

    try:
        from app.api.goal_routes import goal_bp as _goal_bp

        app.register_blueprint(_goal_bp, url_prefix="/api/goals")
        logger.info("[GoalAPI] ✅ 长期目标 API 已注册: /api/goals")
    except ImportError as exc:
        logger.warning(f"[GoalAPI] ⚠️ 未能导入长期目标 API 蓝图: {exc}")
    except Exception as exc:
        logger.error(f"[GoalAPI] ❌ 长期目标 API 注册失败: {exc}")

    try:
        from app.api.file_hub_routes import file_hub_bp as _file_hub_bp

        app.register_blueprint(_file_hub_bp, url_prefix="/api/files")
        logger.info("[FileHubAPI] ✅ 文件 Hub API 已注册: /api/files")
    except ImportError as exc:
        logger.warning(f"[FileHubAPI] ⚠️ 未能导入文件 Hub 蓝图: {exc}")
    except Exception as exc:
        logger.error(f"[FileHubAPI] ❌ 文件 Hub API 注册失败: {exc}")

    try:
        from app.api.job_routes import job_bp as _job_bp

        app.register_blueprint(_job_bp)
        logger.info("[JobAPI] ✅ 后台作业 API 已注册: /api/jobs")
    except ImportError as exc:
        logger.warning(f"[JobAPI] ⚠️ 未能导入作业 API 蓝图: {exc}")
    except Exception as exc:
        logger.error(f"[JobAPI] ❌ 作业 API 注册失败: {exc}")

    try:
        from app.api.bg_agent_routes import bg_agent_bp as _bg_agent_bp

        app.register_blueprint(_bg_agent_bp)
        logger.info("[BgAgentAPI] ✅ Background Agent API 已注册: /api/bg-agent")
    except ImportError as exc:
        logger.warning(f"[BgAgentAPI] ⚠️ 未能导入 Background Agent API 蓝图: {exc}")
    except Exception as exc:
        logger.error(f"[BgAgentAPI] ❌ Background Agent API 注册失败: {exc}")

    try:
        from app.api.mcp_routes import mcp_bp as _mcp_bp

        app.register_blueprint(_mcp_bp)
        _exempt_csrf_blueprint(app, _mcp_bp)
        logger.info("[MCPAPI] ✅ MCP 监管入口已注册: /api/mcp")
    except ImportError as exc:
        logger.warning(f"[MCPAPI] ⚠️ 未能导入 MCP API 蓝图: {exc}")
    except Exception as exc:
        logger.error(f"[MCPAPI] ❌ MCP API 注册失败: {exc}")

    try:
        from app.api.ops_routes import ops_bp as _ops_bp

        app.register_blueprint(_ops_bp)
        logger.info("[OpsAPI] ✅ 运维健康 API 已注册: /api/ops")
    except ImportError as exc:
        logger.warning(f"[OpsAPI] ⚠️ 未能导入运维 API 蓝图: {exc}")
    except Exception as exc:
        logger.error(f"[OpsAPI] ❌ 运维 API 注册失败: {exc}")

    try:
        from app.api.shadow_routes import shadow_bp as _shadow_bp

        app.register_blueprint(_shadow_bp)
        logger.info("[ShadowAPI] ✅ 影子追踪 API 已注册: /api/shadow")
    except ImportError as exc:
        logger.warning(f"[ShadowAPI] ⚠️ 未能导入影子追踪蓝图: {exc}")
    except Exception as exc:
        logger.error(f"[ShadowAPI] ❌ 影子追踪 API 注册失败: {exc}")

    try:
        from app.api.macro_routes import macro_bp as _macro_bp

        app.register_blueprint(_macro_bp)
        logger.info("[MacroAPI] ✅ 宏录制 API 已注册: /api/macro")
    except ImportError as exc:
        logger.warning(f"[MacroAPI] ⚠️ 未能导入宏录制蓝图: {exc}")
    except Exception as exc:
        logger.error(f"[MacroAPI] ❌ 宏录制 API 注册失败: {exc}")

    try:
        from app.api.response_routes import response_bp

        app.register_blueprint(response_bp)
        logger.info("[ResponseAPI] ✅ AI 回复评分 API 已注册: /api/response")
    except ImportError as exc:
        logger.warning(f"[ResponseAPI] ⚠️ 未能导入 AI 回复评分蓝图: {exc}")
    except Exception as exc:
        logger.error(f"[ResponseAPI] ❌ AI 回复评分 API 注册失败: {exc}")

    try:
        from web.routes.health import health_bp as _health_bp

        app.register_blueprint(_health_bp)
        logger.info("[HealthAPI] ✅ 健康检查 API 已注册: /api/health")
    except ImportError as exc:
        logger.warning(f"[HealthAPI] ⚠️ 未能导入健康检查蓝图: {exc}")
    except Exception as exc:
        logger.error(f"[HealthAPI] ❌ 健康检查 API 注册失败: {exc}")

    try:
        from app.api.telegram_bot_routes import telegram_bp as _telegram_bp

        app.register_blueprint(_telegram_bp, url_prefix="/api/telegram")
        logger.info("[TelegramAPI] ✅ Telegram Bot API 已注册: /api/telegram")
    except ImportError as exc:
        logger.warning(f"[TelegramAPI] ⚠️ 未能导入 Telegram Bot API 蓝图: {exc}")
    except Exception as exc:
        logger.error(f"[TelegramAPI] ❌ Telegram Bot API 注册失败: {exc}")

    try:
        from web.blueprints.workflow_api import workflow_bp as _workflow_bp

        app.register_blueprint(_workflow_bp)
        logger.info("[WorkflowAPI] ✅ 工作流 API 已注册: /api/workflow")
    except ImportError as exc:
        logger.warning(f"[WorkflowAPI] ⚠️ 未能导入工作流 API 蓝图: {exc}")
    except Exception as exc:
        logger.error(f"[WorkflowAPI] ❌ 工作流 API 注册失败: {exc}")

    try:
        from web.memory_api_routes import register_memory_routes
        from web.runtime_context import get_memory_manager

        register_memory_routes(app, get_memory_manager)
        logger.info("[MemoryAPI] ✅ 增强记忆系统 API 已注册")
    except ImportError as exc:
        logger.warning(f"[MemoryAPI] ⚠️ 增强记忆系统 API 未找到: {exc}")
    except Exception as exc:
        logger.error(f"[MemoryAPI] ❌ 增强记忆系统 API 注册失败: {exc}")

    for mod_name, attr_name, prefix, tag in _WEB_BLUEPRINT_CONFIGS:
        try:
            module = importlib.import_module(mod_name)
            blueprint = getattr(module, attr_name)
            if prefix:
                app.register_blueprint(blueprint, url_prefix=prefix)
            else:
                app.register_blueprint(blueprint)
            if tag == "Chat":
                _exempt_csrf_endpoint(app, "chat.chat")
            logger.info(f"[{tag}] ✅ 蓝图已注册")
        except ImportError as exc:
            logger.warning(f"[{tag}] ⚠️ 蓝图导入失败: {exc}")
        except Exception as exc:
            logger.error(f"[{tag}] ❌ 蓝图注册失败: {exc}")

    logger.info("[INIT] ✅ 所有蓝图注册完成")
    return agent_blueprint
