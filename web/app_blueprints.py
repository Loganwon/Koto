from __future__ import annotations

import concurrent.futures
import importlib
import os
import threading
from logging import Logger

from flask import Flask

_blueprints_registered = False
_blueprints_lock = threading.Lock()

# These are the route families a released Koto desktop/web build cannot operate
# without.  Keep this list intentionally product-facing: a process which only
# renders the shell but cannot create a session, chat, edit files, or report its
# own health must never advertise itself as healthy.
_REQUIRED_BLUEPRINTS = frozenset(
    {
        "Auth",
        "Pages",
        "Sessions",
        "Settings",
        "Workspace",
        "Chat",
        "EditorAI",
        "WorkspaceAssistant",
        "FileHubAPI",
        "HealthAPI",
    }
)
_BLUEPRINT_HEALTH_EXTENSION = "koto_blueprint_registration"


class RequiredBlueprintRegistrationError(RuntimeError):
    """Raised when a release build cannot register a required capability."""

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


def _is_release_mode(app: Flask) -> bool:
    """Whether a required blueprint failure must abort startup.

    Test, debug, and training runs retain the ability to start in a degraded
    state so contributors can inspect the health payload.  A normal packaged
    or production Flask process is fail-fast.
    """
    return not (
        app.debug
        or app.testing
        or app.config.get("KOTO_ALLOW_DEGRADED_BLUEPRINTS", False)
        or os.environ.get("KOTO_DEV_TRAINING") == "1"
        or os.environ.get("FLASK_ENV", "").lower() == "development"
    )


def _blueprint_registration_state(app: Flask) -> dict:
    """Return the app-local registration ledger consumed by /api/health."""
    return app.extensions.setdefault(
        _BLUEPRINT_HEALTH_EXTENSION,
        {
            "required": sorted(_REQUIRED_BLUEPRINTS),
            "registered": [],
            "missing_required": [],
            "missing_optional": [],
        },
    )


def _record_blueprint_success(app: Flask, name: str) -> None:
    state = _blueprint_registration_state(app)
    if name not in state["registered"]:
        state["registered"].append(name)


def _record_blueprint_failure(app: Flask, name: str, module: str, exc: Exception) -> None:
    """Persist a missing capability and stop a release startup when required."""
    global _blueprints_registered

    state = _blueprint_registration_state(app)
    entry = {"name": name, "module": module, "reason": str(exc)}
    bucket = "missing_required" if name in _REQUIRED_BLUEPRINTS else "missing_optional"
    if entry not in state[bucket]:
        state[bucket].append(entry)

    if name in _REQUIRED_BLUEPRINTS and _is_release_mode(app):
        # A failed release registration must be retryable in the same process
        # (for example in a launcher diagnostic), rather than being masked by
        # the once-per-process guard.
        _blueprints_registered = False
        raise RequiredBlueprintRegistrationError(
            f"Required blueprint '{name}' ({module}) could not be registered: {exc}"
        ) from exc


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
    _blueprint_registration_state(app)

    # Register health before the rest of the product surface.  In a degraded
    # development run this keeps the diagnostic endpoint available to explain
    # which later capability did not load.
    try:
        from web.routes.health import health_bp as _health_bp

        app.register_blueprint(_health_bp)
        _record_blueprint_success(app, "HealthAPI")
        logger.info("[HealthAPI] ✅ 健康检查 API 已注册: /api/health")
    except Exception as exc:
        _record_blueprint_failure(app, "HealthAPI", "web.routes.health", exc)
        logger.error(f"[HealthAPI] ❌ 健康检查 API 注册失败: {exc}")

    try:
        from web.app_http import configure_http_wiring

        configure_http_wiring(app, logger)
        logger.info("[HTTP] ✅ HTTP 基础中间件已注册")
    except Exception as exc:
        logger.error(f"[HTTP] ❌ HTTP 基础中间件注册失败: {exc}")

    try:
        from web.blueprints.auth import register_auth_routes

        register_auth_routes(app)
        _record_blueprint_success(app, "Auth")
        logger.info("[Auth] ✅ 认证 API 已注册")
    except ImportError as exc:
        _record_blueprint_failure(app, "Auth", "web.blueprints.auth", exc)
        logger.warning(f"[Auth] ⚠️ 未能导入认证 API: {exc}")
    except Exception as exc:
        _record_blueprint_failure(app, "Auth", "web.blueprints.auth", exc)
        logger.warning(f"[Auth] ⚠️ 认证 API 注册失败: {exc}")

    try:
        from app.api.task_routes import task_bp as _task_bp

        app.register_blueprint(_task_bp, url_prefix="/api/tasks")
        _exempt_csrf_endpoint(app, "tasks.submit_background_task")
        logger.info("[TaskAPI] ✅ 任务管理 API 已注册: /api/tasks")
    except ImportError as exc:
        _record_blueprint_failure(app, "TaskAPI", "app.api.task_routes", exc)
        logger.warning(f"[TaskAPI] ⚠️ 未能导入任务管理 API 蓝图: {exc}")
    except Exception as exc:
        _record_blueprint_failure(app, "TaskAPI", "app.api.task_routes", exc)
        logger.error(f"[TaskAPI] ❌ 任务管理 API 注册失败: {exc}")

    try:
        from app.api import agent_bp as _agent_bp

        agent_blueprint = _agent_bp
        app.register_blueprint(agent_blueprint, url_prefix="/api/agent")
        logger.info("[UnifiedAgent] ✅ 统一 Agent API 已注册: /api/agent")
    except ImportError as exc:
        _record_blueprint_failure(app, "UnifiedAgent", "app.api", exc)
        logger.warning(f"[UnifiedAgent] ⚠️ 未能导入统一 Agent API 蓝图: {exc}")
    except Exception as exc:
        _record_blueprint_failure(app, "UnifiedAgent", "app.api", exc)
        logger.error(f"[UnifiedAgent] ❌ 注册失败: {exc}")

    try:
        from app.api.skill_routes import skill_bp as _skill_bp

        app.register_blueprint(_skill_bp)
        logger.info("[SkillAPI] ✅ Skill CRUD API 已注册: /api/skills")
    except ImportError as exc:
        _record_blueprint_failure(app, "SkillAPI", "app.api.skill_routes", exc)
        logger.warning(f"[SkillAPI] ⚠️ 未能导入 Skill API 蓝图: {exc}")
    except Exception as exc:
        _record_blueprint_failure(app, "SkillAPI", "app.api.skill_routes", exc)
        logger.error(f"[SkillAPI] ❌ Skill API 注册失败: {exc}")

    try:
        from app.api.skill_marketplace_routes import marketplace_bp as _marketplace_bp

        app.register_blueprint(_marketplace_bp)
        logger.info("[SkillMarket] ✅ Skill Marketplace API 已注册: /api/skillmarket")
    except ImportError as exc:
        _record_blueprint_failure(app, "SkillMarket", "app.api.skill_marketplace_routes", exc)
        logger.warning(f"[SkillMarket] ⚠️ 未能导入 Skill Marketplace API 蓝图: {exc}")
    except Exception as exc:
        _record_blueprint_failure(app, "SkillMarket", "app.api.skill_marketplace_routes", exc)
        logger.error(f"[SkillMarket] ❌ Skill Marketplace API 注册失败: {exc}")

    if os.environ.get("KOTO_DEV_TRAINING") == "1":
        try:
            from app.api.training_routes import training_bp as _training_bp

            app.register_blueprint(_training_bp)
            logger.info("[TrainingAPI] ✅ 训练数据 API 已注册: /api/training/*")
        except ImportError as exc:
            _record_blueprint_failure(app, "TrainingAPI", "app.api.training_routes", exc)
            logger.warning(f"[TrainingAPI] ⚠️ 未能导入训练数据模块: {exc}")
        except Exception as exc:
            _record_blueprint_failure(app, "TrainingAPI", "app.api.training_routes", exc)
            logger.error(f"[TrainingAPI] ❌ 训练数据 API 注册失败: {exc}")

        try:
            from app.api.distill_routes import distill_bp as _distill_bp

            app.register_blueprint(_distill_bp, url_prefix="/api/distill")
            logger.info(
                "[DistillAPI] ✅ LoRA 蒸馏训练 API 已注册（开发模式）: /api/distill"
            )
        except ImportError as exc:
            _record_blueprint_failure(app, "DistillAPI", "app.api.distill_routes", exc)
            logger.warning(f"[DistillAPI] ⚠️ 未能导入蒸馏训练模块: {exc}")
        except Exception as exc:
            _record_blueprint_failure(app, "DistillAPI", "app.api.distill_routes", exc)
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
        _record_blueprint_failure(app, "PPT_API", "web.ppt_api_routes", exc)
        logger.warning(f"[PPT_API] ⚠️ 未能导入 PPT 编辑 API: {exc}")
    except Exception as exc:
        _record_blueprint_failure(app, "PPT_API", "web.ppt_api_routes", exc)
        logger.warning(f"[PPT_API] ⚠️ PPT 编辑 API 注册失败: {exc}")

    try:
        from app.api.goal_routes import goal_bp as _goal_bp

        app.register_blueprint(_goal_bp, url_prefix="/api/goals")
        logger.info("[GoalAPI] ✅ 长期目标 API 已注册: /api/goals")
    except ImportError as exc:
        _record_blueprint_failure(app, "GoalAPI", "app.api.goal_routes", exc)
        logger.warning(f"[GoalAPI] ⚠️ 未能导入长期目标 API 蓝图: {exc}")
    except Exception as exc:
        _record_blueprint_failure(app, "GoalAPI", "app.api.goal_routes", exc)
        logger.error(f"[GoalAPI] ❌ 长期目标 API 注册失败: {exc}")

    try:
        from app.api.file_hub_routes import file_hub_bp as _file_hub_bp

        app.register_blueprint(_file_hub_bp, url_prefix="/api/files")
        _record_blueprint_success(app, "FileHubAPI")
        logger.info("[FileHubAPI] ✅ 文件 Hub API 已注册: /api/files")
    except ImportError as exc:
        _record_blueprint_failure(app, "FileHubAPI", "app.api.file_hub_routes", exc)
        logger.warning(f"[FileHubAPI] ⚠️ 未能导入文件 Hub 蓝图: {exc}")
    except Exception as exc:
        _record_blueprint_failure(app, "FileHubAPI", "app.api.file_hub_routes", exc)
        logger.error(f"[FileHubAPI] ❌ 文件 Hub API 注册失败: {exc}")

    try:
        from app.api.job_routes import job_bp as _job_bp

        app.register_blueprint(_job_bp)
        logger.info("[JobAPI] ✅ 后台作业 API 已注册: /api/jobs")
    except ImportError as exc:
        _record_blueprint_failure(app, "JobAPI", "app.api.job_routes", exc)
        logger.warning(f"[JobAPI] ⚠️ 未能导入作业 API 蓝图: {exc}")
    except Exception as exc:
        _record_blueprint_failure(app, "JobAPI", "app.api.job_routes", exc)
        logger.error(f"[JobAPI] ❌ 作业 API 注册失败: {exc}")

    try:
        from app.api.bg_agent_routes import bg_agent_bp as _bg_agent_bp

        app.register_blueprint(_bg_agent_bp)
        logger.info("[BgAgentAPI] ✅ Background Agent API 已注册: /api/bg-agent")
    except ImportError as exc:
        _record_blueprint_failure(app, "BgAgentAPI", "app.api.bg_agent_routes", exc)
        logger.warning(f"[BgAgentAPI] ⚠️ 未能导入 Background Agent API 蓝图: {exc}")
    except Exception as exc:
        _record_blueprint_failure(app, "BgAgentAPI", "app.api.bg_agent_routes", exc)
        logger.error(f"[BgAgentAPI] ❌ Background Agent API 注册失败: {exc}")

    try:
        from app.api.mcp_routes import mcp_bp as _mcp_bp

        app.register_blueprint(_mcp_bp)
        _exempt_csrf_blueprint(app, _mcp_bp)
        logger.info("[MCPAPI] ✅ MCP 监管入口已注册: /api/mcp")
    except ImportError as exc:
        _record_blueprint_failure(app, "MCPAPI", "app.api.mcp_routes", exc)
        logger.warning(f"[MCPAPI] ⚠️ 未能导入 MCP API 蓝图: {exc}")
    except Exception as exc:
        _record_blueprint_failure(app, "MCPAPI", "app.api.mcp_routes", exc)
        logger.error(f"[MCPAPI] ❌ MCP API 注册失败: {exc}")

    try:
        from app.api.ops_routes import ops_bp as _ops_bp

        app.register_blueprint(_ops_bp)
        logger.info("[OpsAPI] ✅ 运维健康 API 已注册: /api/ops")
    except ImportError as exc:
        _record_blueprint_failure(app, "OpsAPI", "app.api.ops_routes", exc)
        logger.warning(f"[OpsAPI] ⚠️ 未能导入运维 API 蓝图: {exc}")
    except Exception as exc:
        _record_blueprint_failure(app, "OpsAPI", "app.api.ops_routes", exc)
        logger.error(f"[OpsAPI] ❌ 运维 API 注册失败: {exc}")

    try:
        from app.api.macro_routes import macro_bp as _macro_bp

        app.register_blueprint(_macro_bp)
        logger.info("[MacroAPI] ✅ 宏录制 API 已注册: /api/macro")
    except ImportError as exc:
        _record_blueprint_failure(app, "MacroAPI", "app.api.macro_routes", exc)
        logger.warning(f"[MacroAPI] ⚠️ 未能导入宏录制蓝图: {exc}")
    except Exception as exc:
        _record_blueprint_failure(app, "MacroAPI", "app.api.macro_routes", exc)
        logger.error(f"[MacroAPI] ❌ 宏录制 API 注册失败: {exc}")

    try:
        from app.api.response_routes import response_bp

        app.register_blueprint(response_bp)
        logger.info("[ResponseAPI] ✅ AI 回复评分 API 已注册: /api/response")
    except ImportError as exc:
        _record_blueprint_failure(app, "ResponseAPI", "app.api.response_routes", exc)
        logger.warning(f"[ResponseAPI] ⚠️ 未能导入 AI 回复评分蓝图: {exc}")
    except Exception as exc:
        _record_blueprint_failure(app, "ResponseAPI", "app.api.response_routes", exc)
        logger.error(f"[ResponseAPI] ❌ AI 回复评分 API 注册失败: {exc}")

    try:
        from app.api.telegram_bot_routes import telegram_bp as _telegram_bp

        app.register_blueprint(_telegram_bp, url_prefix="/api/telegram")
        logger.info("[TelegramAPI] ✅ Telegram Bot API 已注册: /api/telegram")
    except ImportError as exc:
        _record_blueprint_failure(app, "TelegramAPI", "app.api.telegram_bot_routes", exc)
        logger.warning(f"[TelegramAPI] ⚠️ 未能导入 Telegram Bot API 蓝图: {exc}")
    except Exception as exc:
        _record_blueprint_failure(app, "TelegramAPI", "app.api.telegram_bot_routes", exc)
        logger.error(f"[TelegramAPI] ❌ Telegram Bot API 注册失败: {exc}")

    try:
        from web.blueprints.workflow_api import workflow_bp as _workflow_bp

        app.register_blueprint(_workflow_bp)
        logger.info("[WorkflowAPI] ✅ 工作流 API 已注册: /api/workflow")
    except ImportError as exc:
        _record_blueprint_failure(app, "WorkflowAPI", "web.blueprints.workflow_api", exc)
        logger.warning(f"[WorkflowAPI] ⚠️ 未能导入工作流 API 蓝图: {exc}")
    except Exception as exc:
        _record_blueprint_failure(app, "WorkflowAPI", "web.blueprints.workflow_api", exc)
        logger.error(f"[WorkflowAPI] ❌ 工作流 API 注册失败: {exc}")

    try:
        from web.blueprints.memory_api import register_memory_routes
        from web.memory_runtime import get_memory_manager

        register_memory_routes(app, get_memory_manager)
        logger.info("[Memory] ✅ 记忆 API 已注册")
    except ImportError as exc:
        _record_blueprint_failure(app, "Memory", "web.blueprints.memory_api", exc)
        logger.warning(f"[Memory] ⚠️ 未能导入记忆 API: {exc}")
    except Exception as exc:
        _record_blueprint_failure(app, "Memory", "web.blueprints.memory_api", exc)
        logger.warning(f"[Memory] ⚠️ 记忆 API 注册失败: {exc}")

    try:
        from web.blueprints.parallel_api import register_parallel_api
        register_parallel_api(app)
        logger.info("[Parallel] ✅ 并行任务 API 已注册")
    except ImportError as exc:
        _record_blueprint_failure(app, "Parallel", "web.blueprints.parallel_api", exc)
        logger.warning(f"[Parallel] ⚠️ 未能导入并行任务 API: {exc}")
    except Exception as exc:
        _record_blueprint_failure(app, "Parallel", "web.blueprints.parallel_api", exc)
        logger.warning(f"[Parallel] ⚠️ 并行任务 API 注册失败: {exc}")

    for mod_name, attr_name, prefix, tag in _WEB_BLUEPRINT_CONFIGS:
        try:
            module = importlib.import_module(mod_name)
            blueprint = getattr(module, attr_name)
            if prefix:
                app.register_blueprint(blueprint, url_prefix=prefix)
            else:
                app.register_blueprint(blueprint)
            _record_blueprint_success(app, tag)
            if tag == "Chat":
                _exempt_csrf_endpoint(app, "chat.chat")
                _exempt_csrf_endpoint(app, "chat.chat_stream")
                _exempt_csrf_endpoint(app, "chat.mini_chat")
            elif tag == "EditorAI":
                _exempt_csrf_endpoint(app, "editor_ai.editor_ai_task_stream")
                _exempt_csrf_endpoint(app, "editor_ai.editor_ai_task_stream_cancel")
                _exempt_csrf_endpoint(app, "editor_ai.editor_ai_chart")
            logger.info(f"[{tag}] ✅ 蓝图已注册")
        except ImportError as exc:
            _record_blueprint_failure(app, tag, mod_name, exc)
            logger.warning(f"[{tag}] ⚠️ 蓝图导入失败: {exc}")
        except Exception as exc:
            _record_blueprint_failure(app, tag, mod_name, exc)
            logger.error(f"[{tag}] ❌ 蓝图注册失败: {exc}")

    # Conditionally register dev blueprint only in debug mode
    if app.debug:
        try:
            from web.blueprints.dev import dev_bp as _dev_bp
            app.register_blueprint(_dev_bp)
            logger.info("[Dev] ✅ 开发蓝图已注册 (debug 模式)")
        except ImportError as exc:
            _record_blueprint_failure(app, "Dev", "web.blueprints.dev", exc)
            logger.warning(f"[Dev] ⚠️ 开发蓝图导入失败: {exc}")
        except Exception as exc:
            _record_blueprint_failure(app, "Dev", "web.blueprints.dev", exc)
            logger.error(f"[Dev] ❌ 开发蓝图注册失败: {exc}")

    logger.info("[INIT] ✅ 所有蓝图注册完成")
    return agent_blueprint
