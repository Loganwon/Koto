# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

# Bypass system/VPN proxy for all localhost services (Ollama, etc.)
# Must be set before any requests/urllib imports.
import os as _os

_os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost,::1")
_os.environ.setdefault("no_proxy", "127.0.0.1,localhost,::1")

import json
import logging
import os
import sys
import time
_sys = sys
_app_logger = logging.getLogger("koto.app")

# 确保 web/ 目录在模块搜索路径中（通过 koto_app.py 启动时需要）
_web_dir = os.path.dirname(os.path.abspath(__file__))
if _web_dir not in sys.path:
    sys.path.append(_web_dir)

# 确保 Koto 根目录（web/ 的父目录）在 sys.path 最前面，
# 避免 web/app.py 文件名与 app/ 包名冲突（'app' is not a package 错误）
_koto_root = os.path.dirname(_web_dir)
if _koto_root in sys.path:
    sys.path.remove(_koto_root)
sys.path.insert(0, _koto_root)

from dotenv import load_dotenv
from flask import Response, request, stream_with_context

from web.app_blueprints import register_blueprints_deferred
from web.app_factory import create_flask_app
from web.app_http import configure_http_wiring
from web.app_observability import configure_observability
from web.app_proxy import configure_proxy, extract_system_proxy_candidates
from web.app_realtime import init_notification_socket, init_socketio
from web.app_runtime import (
    start_background_runtime,
    start_model_runtime,
    start_proxy_warmup,
)
from web.app_storage import resolve_app_storage_paths
from app.core.services.notification_manager import get_notification_manager
from app.core.llm.model_selection import select_task_model
from app.core.llm.model_capabilities import (
    DEFAULT_INTERACTIONS_ONLY_MODELS as _DEFAULT_INTERACTIONS_ONLY_MODELS,
    get_interactions_only_model_set as _get_interactions_only_model_set,
)

from web.services.chat_stream.generate.system_handler import handle_system
from web.services.chat_stream.generate.web_search_handler import handle_web_search
from web.services.chat_stream.generate.regular_handler import handle_regular
from web.services.chat_stream.agent_handler import agent_request_options, handle_agent_task
from web.services.chat_stream.orchestrator import setup_chat_stream_context
from web.services.chat_stream.generate.tot_handler import handle_tree_of_thought
from web.services.chat_stream.generate.research_handler import handle_research
from web.services.chat_stream.generate.painter_handler import handle_painter
from web.llm_runtime_helpers import (
    get_local_model_config as _get_local_model_config,
    is_interactions_only as _is_interactions_only_helper,
    normalize_proxy_url as _normalize_proxy_url,
)
from web.chat_writing_style import build_writing_style_instruction

try:
    from flask_sock import Sock
except ImportError:
    Sock = None

try:
    from flask_socketio import SocketIO

    _has_socketio = True
except ImportError:
    SocketIO = None
    _has_socketio = False
    _app_logger.warning("[WebSocket] flask-socketio 未安装，文件助手 AI 面板不可用")


from web.sse.interrupt_manager import StreamInterruptManager

_interrupt_manager = StreamInterruptManager()
_interrupt_flags = {}  # 仅用于向后兼容

if getattr(_sys, "frozen", False):
    PROJECT_ROOT = os.path.dirname(_sys.executable)
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

from app.core.llm.deepseek_config import get_deepseek_api_key, load_deepseek_config_env

_loaded_deepseek_config = load_deepseek_config_env(override=False)

# Also load additional config files if present (user-configured via settings)
for _env_file, _env_var in [
    ("openai_config.env", "OPENAI_API_KEY"),
]:
    _cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", _env_file)
    if os.path.isfile(_cfg_path):
        try:
            load_dotenv(_cfg_path, override=False)
            if os.getenv(_env_var):
                _app_logger.info("Loaded %s from %s", _env_var, _env_file)
        except Exception as exc:
            _app_logger.debug(
                "Optional provider config load failed for %s: %s", _env_file, exc
            )

API_KEY = get_deepseek_api_key(ensure_loaded=False)
FORCE_PROXY = os.getenv("FORCE_PROXY", "").strip()

# ── Startup config validation ───────────────────────────────────────────
try:
    from app.core.llm.deepseek_config import has_deepseek_api_key

    _config_warnings = (
        []
        if has_deepseek_api_key(ensure_loaded=False)
        else ["DeepSeek API key is not configured; cloud features are unavailable."]
    )
    for _cw in _config_warnings:
        _app_logger.warning("[CONFIG] %s", _cw)
except Exception as _cfg_val_err:
    _app_logger.debug("Config validation skipped: %s", _cfg_val_err)

from web.shared import (
    get_workspace_root,
)

PROXY_OPTIONS = [
    "http://127.0.0.1:7890",
    "http://127.0.0.1:10809",
    "http://127.0.0.1:1080",
]


def _extract_system_proxy_candidates() -> list:
    """Collect proxy candidates from system settings (Windows) and env."""
    return extract_system_proxy_candidates(
        settings_manager=settings_manager,
        normalize_proxy_url=_normalize_proxy_url,
        proxy_options=PROXY_OPTIONS,
    )


def setup_proxy():
    return configure_proxy(
        force_proxy=FORCE_PROXY,
        settings_manager=settings_manager,
        normalize_proxy_url=_normalize_proxy_url,
        proxy_options=PROXY_OPTIONS,
        logger=_app_logger,
    )


# 延迟代理检测到首次需要时（启动加速）
_detected_proxy = None
_proxy_checked = False


def get_detected_proxy():
    """懒加载代理检测（首次调用时执行）"""
    global _detected_proxy, _proxy_checked
    if not _proxy_checked:
        _detected_proxy = setup_proxy()
        _proxy_checked = True
    return _detected_proxy


# 向后兼容：detected_proxy 现在通过函数访问
detected_proxy = None  # 占位符，实际通过 get_detected_proxy() 获取

# ── Settings Manager（在代理检测线程之前创建，以便读取用户代理配置）──
from app.core.config.user_settings import SettingsManager as _SettingsManager

settings_manager = _SettingsManager()


# 在后台线程预热代理检测（不阻塞启动）
def _warmup_proxy():
    global detected_proxy
    detected_proxy = get_detected_proxy()


start_proxy_warmup(_app_logger, _warmup_proxy)


# Provider-neutral application gateway.  It is invalidated only when the user
# changes model mode or the configured local model.
from web.runtime_context import service_registry


# ?? Token ???????????????? Google??????????????????????????
def _is_interactions_only(model_id: str) -> bool:
    return _is_interactions_only_helper(model_id, _INTERACTIONS_ONLY_MODELS)


from web.utils.threading_utils import stream_with_keepalive

app, APP_VERSION, _cors_origins = create_flask_app(__name__)

# ?? Flask-SocketIO ????????????????
socketio = init_socketio(
    app,
    _app_logger,
    _cors_origins,
    has_socketio=_has_socketio,
    socketio_cls=SocketIO,
)


error_response = configure_http_wiring(app, _app_logger)


configure_observability(
    app,
    _app_logger,
    APP_VERSION,
    unauthorized_response=lambda: error_response("Unauthorized", 401),
)


# ================= WebSocket ?????? =================
sock = init_notification_socket(
    app,
    _app_logger,
    Sock,
    lambda: get_notification_manager(),
)


# ???????????? app.run() ??????? Flask 3.x ????????????
register_blueprints_deferred(app, _app_logger)
try:
    from app.core.agent.addons import initialize_addon_system

    _addon_bootstrap = initialize_addon_system()
    _app_logger.info(
        "[Addon] runtime bootstrap admitted=%s disabled=%s blocked=%s",
        len(_addon_bootstrap.admitted),
        len(_addon_bootstrap.disabled),
        len(_addon_bootstrap.blocked),
    )
except Exception as _addon_bootstrap_error:
    _app_logger.warning(
        "[Addon] runtime bootstrap failed safely: %s", _addon_bootstrap_error
    )
start_background_runtime(_app_logger, get_workspace_root)

_startup_workspace_dir = get_workspace_root()
_storage_paths = resolve_app_storage_paths(
    PROJECT_ROOT,
    _startup_workspace_dir,
    settings_manager.chats_dir,
)
_startup_chat_dir = _storage_paths.chat_dir
UPLOAD_DIR = _storage_paths.upload_dir

# ================= ??????? =================
# ??? API ????????????????????????????
# ???????????TTL ??? 6 ???????

try:
    from app.core.services.model_manager import KNOWN_MODEL_REGISTRY as _MODEL_REGISTRY
    from app.core.services.model_manager import ModelManager
    from app.core.services.model_manager import (
        TASK_REQUIREMENTS as _MODEL_TASK_REQUIREMENTS,
    )
    from app.core.services.model_manager import (
        score_model_for_task as _score_model_for_task,
    )

    _model_manager_available = True
except ImportError:
    try:
        from model_manager import KNOWN_MODEL_REGISTRY as _MODEL_REGISTRY
        from model_manager import ModelManager
        from model_manager import TASK_REQUIREMENTS as _MODEL_TASK_REQUIREMENTS
        from model_manager import score_model_for_task as _score_model_for_task

        _model_manager_available = True
    except ImportError:
        _model_manager_available = False
        ModelManager = None
        _MODEL_REGISTRY = {}
        _MODEL_TASK_REQUIREMENTS = {}

        def _score_model_for_task(caps, task):
            return 0.0


# ??????API ??????????????????
# ????? deep-research-pro-preview-* ? Interactions API agent??????? generate_content
MODEL_MAP = {
    "CHAT": "deepseek-chat",
    "CODER": "deepseek-chat",
    "WEB_SEARCH": "deepseek-chat",
    "VISION": "deepseek-chat",
    "RESEARCH": "deepseek-chat",
    "FILE_GEN": "deepseek-chat",
    "FILE_TASK": "deepseek-chat",
    "PAINTER": "deepseek-chat",
    "SYSTEM": "local-executor",
    "FILE_OP": "local-executor",
    "AGENT": "deepseek-chat",
    "FILE_SEARCH": "deepseek-chat",
    "DOC_ANNOTATE": "deepseek-chat",
    "MEETING_EXTRACT": "deepseek-chat",
    "COMPLEX": "deepseek-chat",
}

# ??? Interactions-API-only ?????????????????????????????????????
# Archived interactions-only model detection is retained for fail-closed routing.
# Model compatibility note for generate_content support
_INTERACTIONS_ONLY_MODELS = {mid for mid in _DEFAULT_INTERACTIONS_ONLY_MODELS}
# ????????????????
_model_manager = None

# ?? ??????????? web/models/resolver.py?????????????????????????
from web.models.resolver import (
    format_model_display_name as _format_model_display_name,
    resolve_requested_model_id as _resolve_requested_model_id,
    init_resolver as _init_model_resolver,
)

# ?????????????????????????
try:
    _init_model_resolver(
        model_map=MODEL_MAP,
        model_task_requirements=_MODEL_TASK_REQUIREMENTS,
        score_model_for_task=_score_model_for_task,
    )
except Exception:
    logging.getLogger(__name__).warning(
        "Model resolver initialization failed; using fallback routing.", exc_info=True
    )

from web.sse.sanitizer import safe_sse as _safe_sse


def _sync_model_routes_from_manager(force_refresh: bool = False) -> bool:
    """? ModelManager ????????????fallback ???????"""
    global _INTERACTIONS_ONLY_MODELS, _INTERACTIONS_FALLBACK_MODEL

    if _model_manager is None:
        return False

    dynamic_map = (
        _model_manager.refresh() if force_refresh else _model_manager.get_model_map()
    )
    if not dynamic_map:
        return False

    MODEL_MAP.update(dynamic_map)
    # ?????????
    _init_model_resolver(
        model_manager=_model_manager,
        model_map=MODEL_MAP,
        model_task_requirements=_MODEL_TASK_REQUIREMENTS,
        score_model_for_task=_score_model_for_task,
    )
    _INTERACTIONS_ONLY_MODELS = _get_interactions_only_model_set(
        _model_manager.get_interactions_only_models()
    )
    _INTERACTIONS_FALLBACK_MODEL = _model_manager.get_fallback_model()

    # ???? ModelFallbackExecutor ????
    try:
        from app.core.llm.model_fallback import get_fallback_executor

        get_fallback_executor().update_model_map(MODEL_MAP)
    except Exception as _fe:
        _app_logger.warning(f"[ModelManager] ?? ModelFallbackExecutor ?????????: {_fe}")

    return True


def _init_model_manager():
    """
    ?????????????????????????
    ?????????????????????????
    """
    global _model_manager
    if not _model_manager_available or ModelManager is None:
        _app_logger.debug("[ModelManager] ??????????????")
        return
    try:
        _app_logger.debug("[ModelManager] ?? ????????...")
        _model_manager = ModelManager(service_registry.llm_gateway)
        _sync_model_routes_from_manager(force_refresh=True)
        _app_logger.info("[ModelManager] ? ??????????????")
    except Exception as _me:
        import traceback as _tb

        _app_logger.warning(f"[ModelManager] ?? ?????????????????: {_me}")
        _tb.print_exc()


def _model_manager_refresh_loop():
    """????????????????????????"""
    interval = max(60, int(os.getenv("KOTO_MODEL_MANAGER_REFRESH_INTERVAL", "900")))
    while True:
        time.sleep(interval)
        if _model_manager is None:
            continue
        try:
            synced = _sync_model_routes_from_manager(force_refresh=True)
            if synced:
                _app_logger.debug("[ModelManager] ? ??????")
        except Exception as _refresh_err:
            _app_logger.warning(f"[ModelManager] ?? ???????????: {_refresh_err}")


# ?????????????????????
MODEL_INFO = {
    "deepseek-chat": {
        "name": "DeepSeek Chat",
        "speed": "??",
        "tier": 8,
        "strengths": ["??", "??", "??", "????", "??"],
    },
    "local-executor": {
        "name": "?????",
        "speed": "???",
        "tier": 0,
        "strengths": ["????", "????", "????"],
    },
}


def get_model_display_name(model_id):
    return _format_model_display_name(model_id, MODEL_INFO, _model_manager)


# ================= Local deterministic system actions =================
from web.tasks.local_executor import LocalExecutor

# ================= Web search capability =================
from web.knowledge.web_searcher import WebSearcher
from web.knowledge.knowledge_graph import KnowledgeGraph
from app.core.services.graph_rag_service import configure_knowledge_graph_factory
from app.core.services.web_search_gateway import configure_web_search_handler

configure_knowledge_graph_factory(KnowledgeGraph)
configure_web_search_handler(WebSearcher.search_with_grounding)

# === System Instruction ===
# ??????? - ??CHAT/RESEARCH????????
# ???? system prompt ?????? chat_stream ?? task_type ????
from web.prompts.task_addendums import TASK_SYSTEM_ADDENDUMS as _TASK_SYSTEM_ADDENDUMS
from app.core.services.chat_system_instruction import (
    get_chat_system_instruction as _get_chat_system_instruction,
    get_default_chat_system_instruction as _get_DEFAULT_CHAT_SYSTEM_INSTRUCTION,
)


start_model_runtime(_app_logger, _init_model_manager, _model_manager_refresh_loop)

# ================= Local dispatcher (migrated to web/local_dispatcher.py) =================
from app.core.routing.local_dispatcher import LocalDispatcher

# ================= Utilities (migrated to web/utils/assistant_utils.py) =================
from web.utils.assistant_utils import Utils

# ================= Session Manager (migrated to web/session_manager.py) =================
from web.session_manager import (
    configure_session_storage,
    get_chat_dir,
    get_session_manager,
)

configure_session_storage(_startup_chat_dir)
session_manager = get_session_manager()

# ================= Memory runtime (migrated to web/memory_runtime.py) =================
from web.memory_runtime import (
    _start_memory_extraction,
    get_memory_manager,
)

_get_writing_style_instruction = build_writing_style_instruction(
    get_memory_manager, _app_logger
)

# ?????????????
memory_manager = None  # ??? get_memory_manager() ????
kb = None  # ??? get_knowledge_base() ????

# ================= Koto Brain =================
from app.core.brain import BrainRuntimeServices, configure_default_brain_runtime
from app.core.brain import KotoBrain

configure_default_brain_runtime(
    BrainRuntimeServices(
        select_model_for_task=lambda task_type, **kwargs: select_task_model(
            task_type,
            model_map=MODEL_MAP,
            **kwargs,
        ),
        get_utils=lambda: Utils,
        get_local_executor=lambda: LocalExecutor,
        get_workspace_dir=get_workspace_root,
        get_settings_manager=lambda: settings_manager,
        get_model_map=lambda: MODEL_MAP,
        get_llm_gateway=lambda: service_registry.llm_gateway,
    )
)
brain = KotoBrain()

# ================= Routes =================


def chat():
    """Send a chat message and get a response (non-streaming).
    ---
    tags: [Chat]
    security:
      - Bearer: []
    parameters:
      - in: body
        name: body
        schema:
          required: [session, message]
          properties:
            session: {type: string, description: Session/conversation name}
            message: {type: string, description: User message}
            locked_model: {type: string, default: cloud}
            locked_task: {type: string}
    responses:
      200:
        description: AI response
        schema:
          properties:
            response: {type: string}
            model: {type: string}
      400:
        description: Missing session or message
      500:
        description: Internal error
    """
    from web.blueprints.chat import chat as _chat_handler

    return _chat_handler()


def chat_stream():
    """Stream a chat response via Server-Sent Events.
    ---
    tags:
      - Chat
    parameters:
      - in: body
        name: body
        schema:
          required: [session, message]
          properties:
            session:
              type: string
            message:
              type: string
            locked_model:
              type: string
              default: cloud
            locked_task:
              type: string
    responses:
      200:
        description: SSE stream of chat tokens
    """
    llm_gateway = service_registry.llm_gateway
    # ?? Orchestrator: pre-checks + context setup ??????????????????????????
    _ctx_result = setup_chat_stream_context(
        request=request,
        session_manager=session_manager,
        settings_manager=settings_manager,
        _app_logger=_app_logger,
        _interrupt_manager=_interrupt_manager,
        Utils=Utils,
        get_memory_manager=get_memory_manager,
        WebSearcher=WebSearcher,
        _get_chat_system_instruction=_get_chat_system_instruction,
        _get_DEFAULT_CHAT_SYSTEM_INSTRUCTION=_get_DEFAULT_CHAT_SYSTEM_INSTRUCTION,
        _get_writing_style_instruction=_get_writing_style_instruction,
        _TASK_SYSTEM_ADDENDUMS=_TASK_SYSTEM_ADDENDUMS,
        MODEL_MAP=MODEL_MAP,
        _resolve_requested_model_id=_resolve_requested_model_id,
        get_model_display_name=get_model_display_name,
        API_KEY=API_KEY,
    )
    if _ctx_result["early_response"]:
        return _ctx_result["early_response"]
    _ctx = _ctx_result["context"]
    session_name = _ctx["session_name"]
    user_input = _ctx["user_input"]
    locked_model = _ctx["locked_model"]
    system_instruction = _ctx["system_instruction"]
    history = _ctx["history"]
    task_type = _ctx["task_type"]
    route_method = _ctx["route_method"]
    _addon_runtime_plan = _ctx["_addon_runtime_plan"]
    model_id = _ctx["model_id"]
    _rag_context_block = _ctx["_rag_context_block"]
    _show_thinking = _ctx["_show_thinking"]
    _llm_user_input = _ctx["_llm_user_input"]

    # ?? AGENT handler ? delegated ??????????????????????????????????????????
    _response = handle_agent_task(
        task_type,
        session_name,
        user_input,
        history,
        locked_model,
        route_method,
        _addon_runtime_plan,
        session_manager,
        _app_logger,
        _start_memory_extraction,
        _safe_sse,
        **agent_request_options(_ctx),
    )
    if _response:
        return _response

    def generate():
        start_time = time.time()

        def _infer_analysis_source(message: str, phase: str = "thinking") -> str:
            """???????local / cloud / hybrid / system"""
            msg = (message or "").lower()
            phase_l = (phase or "").lower()

            if any(k in msg for k in ["ollama", "????", "qwen", "local"]):
                return "local"
            if any(k in msg for k in ["deep-research", "?", "cloud"]):
                return "cloud"
            if any(
                k in phase_l for k in ["routing", "context", "planning", "analyzing"]
            ):
                return "hybrid"
            return "system"

        def yield_thinking(message: str, phase: str = "thinking", source: str = None):
            """??????????????? show_thinking ?????????"""
            if not _show_thinking:
                return ""

            resolved_source = source or _infer_analysis_source(message, phase)
            source_tag = {
                "local": "[????]",
                "cloud": "[?????]",
                "hybrid": "[????]",
                "system": "[????]",
            }.get(resolved_source, "[????]")

            elapsed = round(time.time() - start_time, 1)
            display_message = f"{source_tag} {message}"
            return f"data: {json.dumps({'type': 'thinking', 'message': display_message, 'phase': phase, 'elapsed': elapsed, 'analysis_source': resolved_source}, ensure_ascii=False)}\n\n"

        # === ?????????? ===
        task_display_names = {
            "PAINTER": "?? ????",
            "FILE_GEN": "?? ????",
            "CODER": "?? ????",
            "RESEARCH": "?? ????",
            "WEB_SEARCH": "?? ????",
            "CHAT": "?? ??",
            "SYSTEM": "??? ????",
            "FILE_OP": "?? ????",
            "FILE_EDIT": "?? ????",
            "FILE_SEARCH": "?? ????",
            "VISION": "??? ????",
            "MULTI_STEP": "?? ????",
            "AGENT": "?? ????",
        }

        model_display = get_model_display_name(model_id)
        task_display = task_display_names.get(task_type, task_type)

        # ???????????????????
        classification_msg = f"?? ????: {task_display}"
        if route_method:
            classification_msg += f" (??: {route_method})"

        yield f"data: {json.dumps({'type': 'classification', 'task_type': task_type, 'task_display': task_display, 'model': model_id, 'model_display': model_display, 'route_method': route_method, 'message': classification_msg})}\n\n"

        # ???????????
        t = yield_thinking(f"?????? ? ??? {task_display}", "routing", "hybrid")
        if t:
            yield t
        model_source = (
            "local"
            if any(k in (model_id or "").lower() for k in ["qwen", "llama", "ollama"])
            else "cloud"
        )
        t = yield_thinking(
            f"????: {route_method}?????: {model_display}",
            "model",
            model_source,
        )
        if t:
            yield t
        effective_input = _llm_user_input

        # ??????????????? Markdown???????????
        if task_type not in ["SYSTEM", "FILE_OP", "PAINTER", "VISION"]:
            adapted_input = Utils.adapt_prompt_to_markdown(
                task_type, effective_input, history=history
            )
            if adapted_input != effective_input:
                effective_input = adapted_input
                yield f"data: {json.dumps({'type': 'info', 'message': '?? ????????Markdown??'})}\n\n"
                t = yield_thinking(
                    "????????? Markdown ?????????",
                    "planning",
                    "hybrid",
                )
                if t:
                    yield t

        # ????????????????
        _interrupt_manager.reset(session_name)

        def interrupted():
            return _interrupt_manager.is_interrupted(session_name)

        # ????: ????
        from web.proactive.smart_feedback import SmartFeedback

        _task_labels = SmartFeedback.TASK_LABELS
        _tl = _task_labels.get(task_type, task_type)
        yield f"data: {json.dumps({'type': 'progress', 'message': f'????{_tl}??', 'detail': get_model_display_name(model_id)})}\n\n"

        try:
            # SYSTEM handler ? delegated
            if task_type == "SYSTEM":
                for chunk in handle_system(
                    yield_thinking,
                    user_input,
                    session_name,
                    start_time,
                    llm_gateway,
                    model_id,
                    system_instruction,
                    session_manager,
                    _app_logger,
                ):
                    yield chunk
                    if interrupted():
                        return
                return

            # === FILE TASKS ? workspace task-stream only ===
            _file_task_types = (
                "FILE_OP",
                "FILE_EDIT",
                "FILE_SEARCH",
                "FILE_GEN",
                "DOC_ANNOTATE",
                "MEETING_EXTRACT",
            )
            _is_file_task = task_type in _file_task_types
            if _is_file_task:
                message = (
                    "???????????????????????????????" "???????????????????????????"
                )
                _app_logger.warning(
                    "[CHAT] blocked legacy file-task execution via /api/chat/stream "
                    "(task_type=%s, session=%s)",
                    task_type,
                    session_name,
                )
                yield _safe_sse(
                    {
                        "type": "error",
                        "message": message,
                        "_message_as_error": True,
                    }
                )
                yield _safe_sse(
                    {
                        "type": "done",
                        "images": [],
                        "saved_files": [],
                        "total_time": round(time.time() - start_time, 1),
                        "had_error": True,
                        "legacy_file_task_blocked": True,
                    }
                )
                return

            # === WEB_SEARCH handler ? delegated ===
            if task_type == "WEB_SEARCH":
                for chunk in handle_web_search(
                    yield_thinking,
                    llm_gateway,
                    session_manager,
                    user_input,
                    session_name,
                    start_time,
                    _app_logger,
                    MODEL_MAP,
                ):
                    yield chunk
                    if interrupted():
                        return
                return

            # === ?? Tree of Thought ? RESEARCH/CHAT only ===
            _tot_result = {"handled": False}
            for chunk in handle_tree_of_thought(
                task_type,
                effective_input,
                user_input,
                session_name,
                start_time,
                model_id,
                system_instruction,
                None,  # _uses_standard_workflow_route removed
                settings_manager,
                session_manager,
                MODEL_MAP,
                _app_logger,
                _result=_tot_result,
            ):
                yield chunk
                if interrupted():
                    return
            if _tot_result["handled"]:
                return

            # === RESEARCH handler ===
            if task_type == "RESEARCH":
                for chunk in handle_research(
                    yield_thinking,
                    task_type,
                    user_input,
                    effective_input,
                    session_name,
                    start_time,
                    model_id,
                    system_instruction,
                    _rag_context_block,
                    llm_gateway,
                    session_manager,
                    MODEL_MAP,
                    WebSearcher,
                    _app_logger,
                    stream_with_keepalive,
                    interrupted,
                ):
                    yield chunk
                    if interrupted():
                        return
                return

            # === PAINTER handler ===
            if task_type == "PAINTER":
                for chunk in handle_painter(
                    task_type,
                    user_input,
                    effective_input,
                    session_name,
                    start_time,
                    llm_gateway,
                    session_manager,
                    settings_manager,
                    Utils,
                    _app_logger,
                    interrupted,
                ):
                    yield chunk
                    if interrupted():
                        return
                return

            # === Regular Mode (????) ===
            # Regular mode handler ? delegated
            for chunk in handle_regular(
                yield_thinking,
                task_type,
                user_input,
                session_name,
                start_time,
                llm_gateway,
                _app_logger,
                session_manager,
                settings_manager,
                request,
                _safe_sse,
                MODEL_MAP,
                locked_model,
                system_instruction,
                history,
                _interrupt_manager,
                _rag_context_block,
            ):
                yield chunk
                if interrupted():
                    return
            return

        except Exception as e:
            error_str = str(e)
            _app_logger.debug(f"[CHAT] Exception: {error_str}")

            from app.core.shared.llm_helpers import (
                is_online_failure as _iof2,
                is_ollama_alive as _ioav2,
            )
            from app.core.llm.local_model_runtime import OllamaRuntime

            _OLLAMA_TEXT_TASKS2 = {
                "CHAT",
                "CODER",
                "RESEARCH",
                "FILE_GEN",
                "MULTI_STEP",
                "AGENT",
            }

            # ????? ? ???????????????/Key??/503/??????????????
            if _iof2(e) and task_type in _OLLAMA_TEXT_TASKS2 and _ioav2():
                _app_logger.warning(
                    f"[CHAT] outer: cloud failure ({error_str[:60]}), trying Ollama"
                )
                yield f"data: {json.dumps({'type': 'progress', 'message': '?? ?? AI ???????????? (Ollama)...', 'detail': ''}, ensure_ascii=False)}\n\n"
                _ollama_ok = False
                try:
                    _fb2_stream = OllamaRuntime.generate_stream(
                        user_input,
                        history=history,
                        system_instruction=system_instruction,  # carries doc_edit proposals format if set
                    )
                    if _fb2_stream:
                        _fb2_full = ""
                        for _fc2 in _fb2_stream:
                            if _fc2:
                                _fb2_full += _fc2
                                yield f"data: {json.dumps({'type': 'token', 'content': _fc2})}\n\n"
                        if _fb2_full:
                            _ollama_ok = True
                            session_manager.append_and_save(
                                f"{session_name}.json",
                                user_input,
                                _fb2_full,
                                task=task_type,
                                model_name="ollama/local",
                            )
                            total_time = time.time() - start_time
                            yield f"data: {json.dumps({'type': 'done', 'images': [], 'saved_files': [], 'total_time': total_time})}\n\n"
                            return
                except Exception as _fb2_err:
                    _app_logger.error(
                        f"[CHAT] outer Ollama fallback failed: {_fb2_err}"
                    )

                if not _ollama_ok:
                    # Ollama???????????
                    error_response = (
                        f"? ?? AI ??????????????\n\n????: {error_str[:150]}"
                    )
                    session_manager.append_and_save(
                        f"{session_name}.json",
                        user_input,
                        error_response,
                        task=task_type,
                        model_name=model_id,
                    )
                    yield f"data: {json.dumps({'type': 'token', 'content': error_response})}\n\n"
                    total_time = time.time() - start_time
                    yield f"data: {json.dumps({'type': 'done', 'images': [], 'saved_files': [], 'total_time': total_time})}\n\n"
                    return

            # ???????Ollama??????????
            if (
                "location is not supported" in error_str.lower()
                or "failed_precondition" in error_str.lower()
            ):
                error_response = (
                    "⚠️ 云端模型当前不可用\n\n"
                    "请检查网络或当前云端模型配置。\n\n"
                    "可尝试：\n"
                    "1. 在设置中确认 DeepSeek API 密钥与模型配置\n"
                    "2. 稍后重试，或切换到其他可用云端模型\n"
                    "3. 使用本地 Ollama 模型继续任务"
                )
            elif "API key not valid" in error_str or (
                "INVALID_ARGUMENT" in error_str and "api key" in error_str.lower()
            ):
                error_response = (
                    "⚠️ **云端 API 密钥无效**\n\n"
                    "请在 Koto 设置中检查 DeepSeek API 密钥是否正确且仍然有效。\n"
                    "更新后重试；也可以切换到本地 Ollama 模型。\n\n"
                    f"错误详情：`{error_str[:150]}`"
                )
            elif (
                "server disconnected" in error_str.lower()
                or "disconnected without" in error_str.lower()
                or "connection reset" in error_str.lower()
                or "connection aborted" in error_str.lower()
            ):
                # ?????????????????2 ????????????? Flash
                try:
                    from app.core.llm.model_fallback import get_fallback_executor

                    get_fallback_executor().mark_unavailable(model_id, ttl=120)
                    _app_logger.warning(f"[CHAT] ??????? {model_id} ????? 120s???????")
                except Exception:
                    import logging

                    logging.getLogger(__name__).warning(
                        "Silenced exception caught", exc_info=True
                    )
                error_response = (
                    "⚠️ **云端连接中断**\n\n"
                    "已暂时避开当前不可用模型。请检查网络后重试，"
                    "或在设置中切换到其他可用模型/本地 Ollama。"
                )
            elif (
                "resource_exhausted" in error_str.lower()
                or "quota" in error_str.lower()
                or "rate limit" in error_str.lower()
                or "429" in error_str
            ):
                error_response = (
                    "⚠️ **云端 API 请求过于频繁**\n\n"
                    "请稍候 1–2 分钟后重试，或在设置中切换到其他可用模型。"
                )
            elif (
                "unavailable" in error_str.lower()
                or "503" in error_str
                or "service unavailable" in error_str.lower()
            ):
                error_response = (
                    "⚠️ **云端模型服务暂不可用**\n\n"
                    "请稍后重试，或切换到其他已配置的云端模型/本地 Ollama。"
                )
            elif (
                "deadline_exceeded" in error_str.lower()
                or "timed out" in error_str.lower()
            ):
                error_response = (
                    "⚠️ **请求超时**\n\n"
                    "请检查网络后重试；若任务较复杂，可缩小任务范围，"
                    "或切换到响应更快的可用模型。"
                )
            else:
                error_response = f"? ????: {error_str[:200]}"

            # ?????????????
            session_manager.append_and_save(
                f"{session_name}.json",
                user_input,
                error_response,
                task=task_type,
                model_name=model_id,
            )

            yield f"data: {json.dumps({'type': 'token', 'content': error_response})}\n\n"
            total_time = time.time() - start_time
            yield f"data: {json.dumps({'type': 'done', 'images': [], 'saved_files': [], 'total_time': total_time})}\n\n"

    def _safe_generate():
        """
        generate() ????????
        ???? generate() ???????????????? 'done' ???
        ?????????/???????????????
        """
        _sent_done = False
        try:
            for _chunk in generate():
                if isinstance(_chunk, (str, bytes)):
                    _chunk_str = (
                        _chunk
                        if isinstance(_chunk, str)
                        else _chunk.decode("utf-8", errors="replace")
                    )
                    if '"type": "done"' in _chunk_str or "'type': 'done'" in _chunk_str:
                        _sent_done = True
                yield _chunk
        except Exception as _sg_err:
            _app_logger.warning(
                f"[STREAM] ?? _safe_generate caught exception: {_sg_err}"
            )
            import traceback

            traceback.print_exc()
            if not _sent_done:
                _err_msg = f"? ????????: {str(_sg_err)[:200]}"
                yield f"data: {json.dumps({'type': 'token', 'content': _err_msg})}\n\n"
        finally:
            if not _sent_done:
                _app_logger.warning(
                    f"[STREAM] ?? generate() ??? done ??????? done (task_type={task_type})"
                )
                yield f"data: {json.dumps({'type': 'done', 'images': [], 'saved_files': [], 'total_time': 0, 'fallback_done': True})}\n\n"

    response = Response(
        stream_with_context(_safe_generate()), mimetype="text/event-stream"
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"  # ?? nginx ??
    response.headers["Connection"] = "keep-alive"
    return response


if __name__ == "__main__":
    from web.app_entrypoint import run_web_server

    run_web_server(
        app=app,
        socketio=socketio,
        local_dispatcher=LocalDispatcher,
        chat_dir=get_chat_dir(),
        workspace_dir=get_workspace_root(),
    )
