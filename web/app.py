# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary

# Bypass system/VPN proxy for all localhost services (Ollama, etc.)
# Must be set before any requests/urllib imports.
import os as _os
_os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost,::1")
_os.environ.setdefault("no_proxy", "127.0.0.1,localhost,::1")

import asyncio
import importlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

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
from flask import (
    Response,
    jsonify,
    request,
    send_file,
    stream_with_context,
)

from web.app_blueprints import register_blueprints_deferred
from web.app_factory import create_flask_app
from web.app_http import configure_http_wiring
from web.app_observability import configure_observability
from web.app_proxy import configure_proxy, extract_system_proxy_candidates
from web.app_realtime import init_notification_socket, init_socketio
from web.app_runtime import start_background_runtime
from web.app_storage import resolve_app_storage_paths
from web.chat_file_handlers import (
    handle_multi_file_chat_request,
    handle_single_file_chat_request,
)
from web.utils.filenames import secure_filename as _secure_filename


from app.core.routing import SmartDispatcher
from app.core.llm.model_mode import normalize_model_mode
from app.core.llm.model_capabilities import (
    DEFAULT_INTERACTIONS_ONLY_MODELS as _DEFAULT_INTERACTIONS_ONLY_MODELS,
    get_interactions_only_model_set as _get_interactions_only_model_set,
    normalize_model_id as _normalize_model_id,
)
from app.core.security.output_validator import sanitize_user_visible_text

from web.services.chat_stream.generate.system_handler import handle_system
from web.services.chat_stream.generate.web_search_handler import handle_web_search
from web.services.chat_stream.generate.regular_handler import handle_regular
from web.services.chat_stream.agent_handler import handle_agent_task
from web.services.chat_stream.langgraph_bridge import handle_langgraph_workflow
from web.services.chat_stream.orchestrator import setup_chat_stream_context
from web.services.chat_stream.generate.tot_handler import handle_tree_of_thought
from web.services.chat_stream.generate.research_handler import handle_research
from web.services.chat_stream.generate.painter_handler import handle_painter
from web.llm_runtime_helpers import (
    FakeGenerateContentResponse as _FakeGenerateContentResponse,
    extract_prompt_text as _extract_prompt_text,
    is_interactions_only as _is_interactions_only_helper,
    normalize_proxy_url as _normalize_proxy_url,
)

agent_bp = None

try:
    # The HTTP surface is registered by ``web.blueprints.parallel_api``.
    # The application module owns only the dispatcher lifecycle.
    from web.task_dispatcher import start_dispatcher, stop_dispatcher

    PARALLEL_SYSTEM_ENABLED = True
except ImportError as e:
    _app_logger.warning(f"[WARNING] Failed to import parallel execution system: {e}")
    PARALLEL_SYSTEM_ENABLED = False

# Diagnostic import probes must not create schedulers or worker queues.  The
# app still exports every route and service needed to validate startup.
if os.environ.get("KOTO_SKIP_BACKGROUND_RUNTIME", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}:
    PARALLEL_SYSTEM_ENABLED = False

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

# Also load OpenAI / Anthropic config files if present (user-configured via settings)
for _env_file, _env_var in [
    ("openai_config.env", "OPENAI_API_KEY"),
    ("anthropic_config.env", "ANTHROPIC_API_KEY"),
]:
    _cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", _env_file)
    if os.path.isfile(_cfg_path):
        try:
            load_dotenv(_cfg_path, override=False)
            if os.getenv(_env_var):
                _app_logger.info("Loaded %s from %s", _env_var, _env_file)
        except Exception as exc:
            _app_logger.debug("Optional provider config load failed for %s: %s", _env_file, exc)

API_KEY = get_deepseek_api_key(ensure_loaded=False)
GEMINI_API_BASE = ""
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

from web.config import (
    _load_user_settings,
    get_default_wechat_files_dir,
    get_organize_root,
    get_workspace_root,
    invalidate_settings_cache,
)


if not API_KEY:
    _app_logger.warning("⚠️ Warning: No cloud API key found in deepseek_config.env or gemini_config.env")
    _app_logger.info("   请在 config/deepseek_config.env 中配置 DeepSeek API 密钥")
    _app_logger.info("   应用将继续启动，但云端 AI 功能不可用")

if GEMINI_API_BASE:
    _app_logger.info(f"📡 使用自定义 API 端点: {GEMINI_API_BASE}")

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


threading.Thread(target=_warmup_proxy, daemon=True).start()


# Preload TaskClassifier in background to avoid first-request latency
# NOTE: Disabled due to memory constraints - model loads on first classify() call instead
# def _warmup_classifier():
#     try:
#         from app.core.routing.task_classifier import TaskClassifier
#         _ = TaskClassifier.classify("warmup")
#     except Exception:
#         pass
# threading.Thread(target=_warmup_classifier, daemon=True).start()


# Legacy ``client.models`` compatibility for text-only web features.
# Gemini remains archived; the adapter delegates to the active LLMProvider.
# -- Client cache --
_client = None
_client_mode_key = (None, None)


def get_client():
    global _client, _client_mode_key
    model_mode, local_model = _get_local_model_config()
    current_key = (model_mode, local_model)
    if _client is not None and _client_mode_key != current_key:
        _client = None
    if _client is None:
        if model_mode == "local":
            try:
                from app.core.llm.ollama_provider import create_ollama_client
                _client = create_ollama_client(model_tag=local_model or None)
            except Exception as _e:
                raise RuntimeError("本地模式已启用，但 Ollama 初始化失败") from _e
        else:
            _client = create_client()
        _client_mode_key = current_key
    return _client


def create_client():
    from app.core.llm.llm_client_compat import create_cloud_client_compat

    return create_cloud_client_compat()


# ── 本地模型配置读取 ──────────────────────────────────────────────────────
def _get_local_model_config() -> tuple:
    """Read model_mode and local_model_tag via provider_factory."""
    try:
        from app.core.llm.provider_factory import is_local_mode, get_local_model_tag
        if not is_local_mode():
            return "cloud", None
        return "local", get_local_model_tag() or None
    except Exception:
        return "cloud", None
# ?? Token ???????????????? Google??????????????????????????
try:
    from app.core.analytics.token_tracker import record_usage as _record_token_usage

    _TOKEN_TRACKER_ENABLED = True
except ImportError:
    _TOKEN_TRACKER_ENABLED = False

    def _record_token_usage(*_a, **_kw):
        pass


def _is_interactions_only(model_id: str) -> bool:
    """
    ?? model_id ????? Interactions API ?? generate_content?
    ????? _INTERACTIONS_ONLY_MODELS????????????????
    """
    try:
        iom = _INTERACTIONS_ONLY_MODELS  # noqa: F821 ? ????????????
    except NameError:
        iom = _DEFAULT_INTERACTIONS_ONLY_MODELS
    return _is_interactions_only_helper(model_id, iom)


_logger_tracked = logging.getLogger(__name__)


class _TrackedModels:
    """
    ?? client.models ? generate_content / generate_content_stream????
      1. Token ??????
      2. Interactions-only ??????????? + ???????
         - ??? generate_content ???????? interactions-only
         - ???????? _call_interactions_api_sync()
         - ???????? catch "Interactions API" 400 ??? retry
    """

    def __init__(self, real_models):
        object.__setattr__(self, "_real", real_models)

    # ?? ???? ?????????????????????????????????????????????????????????????

    @staticmethod
    def _call_ia(model_id: str, contents, config) -> "_FakeGenerateContentResponse":
        """Fail closed: archived models must never revive the legacy API."""
        del contents, config
        raise RuntimeError(
            f"Interactions API 已归档（model={model_id}）。请改用 DeepSeek 或当前已配置的模型。"
        )

    # ?? generate_content ????????????????????????????????????????????????????

    def generate_content(self, model=None, *args, **kwargs):
        # ????????
        if model is None and args:
            model, args = args[0], args[1:]

        model_str = str(model or "")
        real = object.__getattribute__(self, "_real")

        # ? ?????interactions-only ????? Interactions API
        if _is_interactions_only(model_str):
            _logger_tracked.debug(
                "[TrackedModels] rejecting archived Interactions model %s", model_str
            )
            return self._call_ia(
                model_str, kwargs.get("contents"), kwargs.get("config")
            )

        # ? ???? + ????
        try:
            response = real.generate_content(model=model, **kwargs)
        except Exception as _gc_err:
            _err_str = str(_gc_err)
            if "Interactions API" in _err_str or (
                "only supports" in _err_str and "Interactions" in _err_str
            ):
                _logger_tracked.warning(
                    "[TrackedModels] 400 Interactions-API error for model=%s ? retrying via Interactions API",
                    model_str,
                )
                try:
                    return self._call_ia(
                        model_str, kwargs.get("contents"), kwargs.get("config")
                    )
                except Exception as _ia_retry_err:
                    _logger_tracked.error(
                        "[TrackedModels] Interactions API retry also failed for %s: %s",
                        model_str,
                        _ia_retry_err,
                    )
            raise  # ? Interactions ???? retry ?????????????

        # ? Token ??
        if _TOKEN_TRACKER_ENABLED:
            try:
                usage = getattr(response, "usage_metadata", None)
                if usage:
                    _record_token_usage(
                        model=model_str,
                        prompt_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
                        completion_tokens=int(
                            getattr(usage, "candidates_token_count", 0) or 0
                        ),
                    )
            except Exception:
                import logging; logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)
        return response

    # ?? generate_content_stream ?????????????????????????????????????????????

    def generate_content_stream(self, model=None, *args, **kwargs):
        """
        ???????
        interactions-only ?????????????????????
        Interactions API???????????? chunk yield ???
        ????? for chunk in stream ??????
        """
        if model is None and args:
            model, args = args[0], args[1:]

        model_str = str(model or "")
        real = object.__getattribute__(self, "_real")

        # ? ?????interactions-only ?? ? ?????? chunk ??
        if _is_interactions_only(model_str):
            _logger_tracked.debug(
                "[TrackedModels] rejecting archived Interactions model %s",
                model_str,
            )
            self._call_ia(model_str, kwargs.get("contents"), kwargs.get("config"))
            return

        # ? ?????? + ??????? chunk ????
        try:
            stream = real.generate_content_stream(model=model, **kwargs)
            first_chunk = True
            for chunk in stream:
                yield chunk
                if first_chunk:
                    first_chunk = False
                if _TOKEN_TRACKER_ENABLED:
                    try:
                        usage = getattr(chunk, "usage_metadata", None)
                        if usage and (getattr(usage, "prompt_token_count", 0) or 0) > 0:
                            _record_token_usage(
                                model=model_str,
                                prompt_tokens=int(
                                    getattr(usage, "prompt_token_count", 0) or 0
                                ),
                                completion_tokens=int(
                                    getattr(usage, "candidates_token_count", 0) or 0
                                ),
                            )
                    except Exception:
                        import logging; logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)
        except Exception as _stream_err:
            _err_str = str(_stream_err)
            if "Interactions API" in _err_str or (
                "only supports" in _err_str and "Interactions" in _err_str
            ):
                _logger_tracked.warning(
                    "[TrackedModels] 400 Interactions-API error in stream for model=%s ? retrying via Interactions API",
                    model_str,
                )
                fake_resp = self._call_ia(
                    model_str, kwargs.get("contents"), kwargs.get("config")
                )
                yield fake_resp
                return
            raise

    def generate_images(self, model=None, *args, **kwargs):
        """?? generate_images?Imagen??????????? token ??"""
        del model, args, kwargs
        raise RuntimeError("图片生成提供商未配置，请使用当前可用的图片生成服务。")

    def embed_content(self, model=None, *args, **kwargs):
        """?? embed_content??? embedding token ??"""
        del model, args, kwargs
        raise RuntimeError("云端 embedding 未配置，请使用当前可用的检索服务。")

    def __getattr__(self, name):
        real = object.__getattribute__(self, "_real")
        return getattr(real, name)


# ??????? client ???????????????
class _ClientProxy:
    """?????????"""

    def __getattr__(self, name):
        obj = getattr(get_client(), name)
        if name == "models":
            return _TrackedModels(obj)
        return obj


client = _ClientProxy()


def create_research_client():
    """Compatibility entrypoint that deliberately blocks archived research APIs."""
    raise RuntimeError("Interactions API 已归档，请使用当前配置的 DeepSeek 研究模型。")


from web.utils.threading_utils import run_with_heartbeat, run_with_timeout, stream_with_keepalive


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


# ================= ????????? =================
if PARALLEL_SYSTEM_ENABLED:
    _app_logger.debug("[PARALLEL] ?? Initializing parallel execution system...")
    try:
        start_dispatcher()
        _app_logger.info(
            "[PARALLEL] ? Parallel execution system initialized successfully"
        )
    except Exception as e:
        _app_logger.error(
            f"[PARALLEL] ? Failed to initialize parallel execution system: {e}"
        )
        PARALLEL_SYSTEM_ENABLED = False

# ================= WebSocket ?????? =================
sock = init_notification_socket(
    app,
    _app_logger,
    Sock,
    lambda: get_notification_manager(),
)


# ???????????? app.run() ??????? Flask 3.x ????????????
agent_bp = register_blueprints_deferred(app, _app_logger)
start_background_runtime(_app_logger, get_workspace_root)

WORKSPACE_DIR = get_workspace_root()
_storage_paths = resolve_app_storage_paths(
    PROJECT_ROOT,
    WORKSPACE_DIR,
    settings_manager.chats_dir,
)
CHAT_DIR = _storage_paths.chat_dir
UPLOAD_DIR = _storage_paths.upload_dir

# ================= ??????? =================
# ??? API ????????????????????????????
# ???????????TTL ??? 6 ???????

try:
    from app.core.services.model_manager import KNOWN_MODEL_REGISTRY as _MODEL_REGISTRY
    from app.core.services.model_manager import ModelManager
    from app.core.services.model_manager import TASK_REQUIREMENTS as _MODEL_TASK_REQUIREMENTS
    from app.core.services.model_manager import score_model_for_task as _score_model_for_task

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
# ??????? client.models.generate_content()???? Interactions API
# ???gemini-2.5-flash ? gemini-2.5-pro ????????? generate_content???????
_INTERACTIONS_ONLY_MODELS = {
    mid for mid in _DEFAULT_INTERACTIONS_ONLY_MODELS
}
# ????????????????
_model_manager = None

# ?? ??????????? web/models/resolver.py?????????????????????????
from web.models.resolver import (
    resolve_model_alias as _resolve_model_alias,
    resolve_model_lock_task as _resolve_model_lock_task,
    model_supports_locked_task as _model_supports_locked_task,
    pick_available_fallback_model as _pick_available_fallback_model,
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

from web.sse.sanitizer import sanitize_sse_text_field as _sanitize_sse_text_field
from web.sse.sanitizer import safe_sse as _safe_sse


def _sync_model_routes_from_manager(force_refresh: bool = False) -> bool:
    """? ModelManager ????????????fallback ???????"""
    global MODEL_MAP, _model_manager, _INTERACTIONS_ONLY_MODELS, _INTERACTIONS_FALLBACK_MODEL

    if _model_manager is None:
        return False

    dynamic_map = _model_manager.refresh() if force_refresh else _model_manager.get_model_map()
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

    # ???? SmartDispatcher ? MODEL_MAP ??
    try:
        SmartDispatcher._dependencies["MODEL_MAP"] = MODEL_MAP
    except Exception:
        import logging

        logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)

    # ???? ModelFallbackExecutor ????
    try:
        from app.core.llm.model_fallback import get_fallback_executor

        get_fallback_executor().update_model_map(MODEL_MAP)
    except Exception as _fe:
        _app_logger.warning(
            f"[ModelManager] ?? ModelFallbackExecutor ?????????: {_fe}"
        )

    # ???? AIRouter ???????
    try:
        from app.core.routing.ai_router import AIRouter

        _available_caps = _model_manager._cached_caps
        _fast_candidates = [
            (mid, caps)
            for mid, caps in _available_caps.items()
            if not _is_interactions_only(mid)
            and not caps.get("image_gen", False)
            and mid != "local-executor"
        ]
        if _fast_candidates:
            _router_candidate = max(
                _fast_candidates,
                key=lambda x: x[1].get("speed", 0) + x[1].get("tier", 0) * 0.1,
            )[0]
            AIRouter.set_router_model(_router_candidate)
    except Exception as _are:
        _app_logger.warning(
            f"[ModelManager] ?? AIRouter ?????????????: {_are}"
        )
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
        _model_manager = ModelManager(client)
        _sync_model_routes_from_manager(force_refresh=True)
        _app_logger.info("[ModelManager] ? ??????????????")
    except Exception as _me:
        import traceback as _tb

        _app_logger.warning(
            f"[ModelManager] ?? ?????????????????: {_me}"
        )
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
            _app_logger.warning(
                f"[ModelManager] ?? ???????????: {_refresh_err}"
            )


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
    """??????????????????????????????"""
    info = MODEL_INFO.get(model_id)
    if info:
        return f"{info['name']} {info['speed']}"
    # ?????? ModelManager ??????
    if _model_manager:
        caps = _model_manager._cached_caps.get(model_id)
        if caps and caps.get("display"):
            return caps["display"]
    # ????????? ID
    return model_id


# ================= ??????? (???? web/local_executor.py) =================
try:
    from web.local_executor import LocalExecutor
except ImportError:
    from local_executor import LocalExecutor


# ================= Web search capability (migrated to web/web_searcher.py) =================
from web.web_searcher import WebSearcher

# === System Instruction ===
# ??????? - ??CHAT/RESEARCH????????
# ???? system prompt ?????? chat_stream ?? task_type ????
from web.prompts.task_addendums import TASK_SYSTEM_ADDENDUMS as _TASK_SYSTEM_ADDENDUMS
from web.chat_system_instruction import (
    get_chat_system_instruction as _get_chat_system_instruction,
    get_default_chat_system_instruction as _get_DEFAULT_CHAT_SYSTEM_INSTRUCTION,
)


def _get_writing_style_instruction(user_input: str) -> str:
    """?????????????????????????"""
    text = (user_input or "").lower()
    writing_keywords = [
        "?",
        "??",
        "??",
        "??",
        "??",
        "??",
        "??",
        "??",
        "??",
        "??",
        "??",
        "??",
        "write",
        "rewrite",
        "polish",
        "email",
        "report",
        "summary",
    ]
    if not any(k in text for k in writing_keywords):
        return ""

    try:
        mm = get_memory_manager()
        if not mm or not hasattr(mm, "user_profile"):
            return ""
        profile = mm.user_profile.profile or {}
        style = (profile.get("communication_style") or {}).get(
            "writing_style_profile"
        ) or {}
        if not style:
            return ""

        detail = style.get("preferred_detail_level", "moderate")
        formality = style.get("formality", "neutral")
        structure_pref = style.get("structure_preference", "paragraph_first")
        tone_tags = style.get("tone_tags", [])

        return (
            "\n\n## ?? ??????????????\n"
            f"- ???{formality}\n"
            f"- ????{detail}\n"
            f"- ?????{structure_pref}\n"
            f"- ?????{', '.join(tone_tags) if tone_tags else '?'}\n"
            "- ??????????????????????????????????????"
        )
    except Exception as exc:
        _app_logger.debug(f"[StyleProfile] ????: {exc}")
        return ""


def _get_system_instruction():
    """????????????????????? Skills ???"""
    from datetime import datetime

    now = datetime.now()
    date_str = now.strftime("%Y?%m?%d?")
    weekday = ["??", "??", "??", "??", "??", "??", "??"][now.weekday()]

    _base_filegen = f"""?? Koto ??????????????????????

## ???????
?? **????**: {date_str} {weekday}

## ????????????
- ??????????????????????/??/??/1????????
- ??????X????????????**????**?????? 2026 ????1??????? 2026 ? 1 ???
- ??????????????????????2024?1??????

## ????
1. **????????** - ?????????????????????JSON
2. **????** - ???????????????
3. **????** - ????????????????

## ??????

### ???????????????
- **??????????**???????
- ??Markdown??????# ## ### ???- ??????
- ?????????????Word/PDF
- ???????????

????????????????
```
# ????

## ???
????...

## ???
- ??1
- ??2
```

### ?????????????????
- ???? ---BEGIN_FILE: filename.py--- ? ---END_FILE--- ??
- ????? 80 ???
- **????????**: `import os; OUTPUT_DIR = os.environ.get('KOTO_OUTPUT_DIR', os.getcwd())`???????????? `OUTPUT_DIR`
- ??????????????PDF???
- ?? try/except ??????
- **???????????????????**

## ?????
- ? ??JSON???"????"
- ? ?????????????
- ? ?? BEGIN_FILE/END_FILE ?????????Python???
- ? ???????????????

## ???
1. **??????** > ???? > JSON??
2. ????????? > ??????
3. ?????? > ????
"""
    # ?? FILE_GEN ??? Skills
    try:
        from app.core.skills.skill_manager import SkillManager

        return SkillManager.inject_into_prompt(_base_filegen, task_type="FILE_GEN")
    except Exception:
        return _base_filegen


# SYSTEM_INSTRUCTION ????????????????? _get_system_instruction()
# SYSTEM_INSTRUCTION = _get_system_instruction()


from web.filegen_time_context import (
    build_filegen_time_context as _build_filegen_time_context,
    parse_time_info_for_filegen as _parse_time_info_for_filegen,
)


def _get_filegen_brief_instruction() -> str:
    """FILE_GEN ???????????????????"""
    now = datetime.now()
    return (
        "??Koto????????????????????????\n"
        f"??????: {now.strftime('%Y-%m-%d')}?{now.strftime('%Y?%m?%d?')}??\n"
        "???????????????????1????????????????"
    )






# ===== ????????? =====
TASK_PROMPTS = {
    "CHAT": """?????????
- ?????????????
- ????????
- ????????""",
    "CODER": """??????
- ????????????
- ??Python/JavaScript????
- ?????????????
- ???????????
- ???????80???""",
    "FILE_GEN": """??????
- ??????????????
- ??????????????
- ??Word/PDF/Excel??
- ???????????
- ????????????""",
    "PAINTER": """???????
- ???????????
- ?????????
- ?????????????
- ????????""",
    "RESEARCH": """??????
- ????????????
- ???????????
- ?????????
- ???????????
- ??????""",
    "SYSTEM": """???????
- ???????????
- ??????????????
- ?????????
- ?????????""",
}

# ===== Windows???????? =====
WINDOWS_SHORTCUTS = {
    # ????????
    "??": "Ctrl+C",
    "??": "Ctrl+V",
    "??": "Ctrl+X",
    "??": "Ctrl+Z",
    "??": "Ctrl+Y",
    "??": "Ctrl+A",
    "??": "Ctrl+S",
    "??": "Ctrl+O",
    "??": "Ctrl+N",
    # ?????
    "????": "Ctrl+T",
    "?????": "Ctrl+W",
    "????": "Ctrl+H",
    "??": "Ctrl+B",
    "??": "Ctrl+R",
    "??": "Ctrl+??",
    "??": "Ctrl+??",
    # ????
    "?????": "Ctrl+Shift+Esc",
    "??": "Win+Shift+S",
    "????": "Win",
    "??": "Win+L",
    "??": "Alt+F4",
    "????": "Win+Tab",
    "????": "Win+D",
    # ????
    "????": "Alt+Tab",
    "????": "Alt+F4",
}


# ================= Context analyzer (migrated to web/context_analyzer.py) =================
from web.context_analyzer import ContextAnalyzer

try:
    _app_logger.debug("[INIT] Configuring SmartDispatcher with local dependencies...")
    SmartDispatcher.configure(
        local_executor=LocalExecutor,
        context_analyzer=ContextAnalyzer,
        web_searcher=WebSearcher,
        model_map=MODEL_MAP,
        client=client,
    )
    _app_logger.debug("[INIT] SmartDispatcher configured successfully.")
except Exception as e:
    _app_logger.error(f"[ERROR] Failed to configure SmartDispatcher: {e}")

# ??? ??????????? ????????????????????????????????????????????????????
# ?????????????????????????? SmartDispatcher ??
import threading as _threading

_threading.Thread(
    target=_init_model_manager, name="ModelManagerInit", daemon=True
).start()
_threading.Thread(
    target=_model_manager_refresh_loop, name="ModelManagerRefresh", daemon=True
).start()

# ================= Local dispatcher (migrated to web/local_dispatcher.py) =================
from app.core.routing.local_dispatcher import (
    LOCAL_ROUTER_MODEL,
    OLLAMA_API_URL,
    LocalDispatcher,
)


# ================= Utilities (migrated to web/utils/assistant_utils.py) =================
from web.utils.assistant_utils import Utils
# ================= Session Manager (migrated to web/session_manager.py) =================
from web.session_manager import SessionManager
from web.session_manager import configure_session_storage, get_session_manager

configure_session_storage(lambda: CHAT_DIR)
session_manager = get_session_manager()

# ================= Memory runtime (migrated to web/memory_runtime.py) =================
from web.memory_runtime import (
    _inject_memory_adapters,
    _start_memory_extraction,
    get_knowledge_base,
    get_memory_manager,
)
# ?????????????
memory_manager = None  # ??? get_memory_manager() ????
kb = None  # ??? get_knowledge_base() ????

# ================= Koto Brain =================
from app.core.brain import BrainRuntimeServices, configure_default_brain_runtime
from app.core.brain import KotoBrain
from web.chat_runtime_services import (
    ChatRuntimeServices,
    configure_chat_runtime_services,
)
from web.settings_runtime_bootstrap import configure_settings_runtime_services_from_app_globals
configure_default_brain_runtime(
    BrainRuntimeServices(
        get_smart_dispatcher=lambda: SmartDispatcher,
        get_utils=lambda: Utils,
        get_local_executor=lambda: LocalExecutor,
        get_client=lambda: client,
        get_workspace_dir=lambda: WORKSPACE_DIR,
        get_settings_manager=lambda: settings_manager,
        get_model_map=lambda: MODEL_MAP,
    )
)
brain = KotoBrain()
configure_chat_runtime_services(
    ChatRuntimeServices(
        get_brain=lambda: brain,
        get_session_manager=lambda: session_manager,
        get_model_map=lambda: MODEL_MAP,
        get_interrupt_manager=lambda: _interrupt_manager,
        get_interrupt_flags=lambda: _interrupt_flags,
        get_smart_dispatcher=lambda: SmartDispatcher,
        get_web_searcher=lambda: WebSearcher,
        get_local_executor=lambda: LocalExecutor,
        get_default_chat_system_instruction=lambda: default_chat_system_instruction,
        get_create_client=lambda: create_client,
        get_utils=lambda: Utils,
        get_chat_stream_handler=lambda: chat_stream,
    )
)


configure_settings_runtime_services_from_app_globals(globals())

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
    # ?? Orchestrator: pre-checks + context setup ??????????????????????????
    _ctx_result = setup_chat_stream_context(
        request=request, session_manager=session_manager,
        settings_manager=settings_manager, client=client,
        _app_logger=_app_logger, _interrupt_manager=_interrupt_manager,
        Utils=Utils, SmartDispatcher=SmartDispatcher,
        LMRv2=None, CONFIG=None,
        get_memory_manager=get_memory_manager, WebSearcher=WebSearcher,
        _get_chat_system_instruction=_get_chat_system_instruction,
        _get_DEFAULT_CHAT_SYSTEM_INSTRUCTION=_get_DEFAULT_CHAT_SYSTEM_INSTRUCTION,
        _get_writing_style_instruction=_get_writing_style_instruction,
        _TASK_SYSTEM_ADDENDUMS=_TASK_SYSTEM_ADDENDUMS, MODEL_MAP=MODEL_MAP,
        _resolve_requested_model_id=_resolve_requested_model_id,
        get_model_display_name=get_model_display_name,
        API_KEY=API_KEY,
    )
    if _ctx_result["early_response"]:
        return _ctx_result["early_response"]
    _ctx = _ctx_result["context"]
    session_name = _ctx["session_name"]
    user_input = _ctx["user_input"]
    locked_task = _ctx["locked_task"]
    locked_model = _ctx["locked_model"]
    shadow_context = _ctx["shadow_context"]
    doc_edit = _ctx["doc_edit"]
    doc_file_type = _ctx["doc_file_type"]
    doc_has_sel = _ctx["doc_has_sel"]
    system_instruction = _ctx["system_instruction"]
    use_instruction = system_instruction
    history = _ctx["history"]
    full_history = _ctx["full_history"]
    _cw_paged_context = _ctx["_cw_paged_context"]
    has_recent_upload = _ctx["has_recent_upload"]
    recent_file_type = _ctx["recent_file_type"]
    recent_file_path = _ctx["recent_file_path"]
    task_type = _ctx["task_type"]
    route_method = _ctx["route_method"]
    context_info = _ctx["context_info"]
    _router_decision = _ctx["_router_decision"]
    _local_chat_override = _ctx["_local_chat_override"]
    _LMRv2 = None
    _workflow_route = _ctx["_workflow_route"]
    _uses_standard_workflow_route = _ctx["_uses_standard_workflow_route"]
    _complexity = _ctx["_complexity"]
    _routed_model_id = _ctx["_routed_model_id"]
    model_id = _ctx["model_id"]
    _rag_context_block = _ctx["_rag_context_block"]
    _show_thinking = _ctx["_show_thinking"]
    _llm_user_input = _ctx["_llm_user_input"]

    _response = handle_langgraph_workflow(
        _workflow_route, session_name, user_input,
        session_manager, _app_logger, _safe_sse,
    )
    if _response:
        return _response

    # ?? AGENT handler ? delegated ??????????????????????????????????????????
    _response = handle_agent_task(
        task_type, session_name, user_input, history,
        locked_model, route_method, _router_decision,
        SmartDispatcher, session_manager, _app_logger,
        _start_memory_extraction, _safe_sse,
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
            if any(k in msg for k in ["gemini", "deep-research", "??", "cloud"]):
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

        routing_list = None
        # ??? routing_list ?????????????
        if context_info and context_info.get("routing_list"):
            routing_list = context_info.get("routing_list")

        yield f"data: {json.dumps({'type': 'classification', 'task_type': task_type, 'task_display': task_display, 'model': model_id, 'model_display': model_display, 'route_method': route_method, 'routing_list': routing_list, 'message': classification_msg})}\n\n"

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
        if routing_list:
            steps_str = (
                " ? ".join(
                    [
                        (
                            f"{r.get('task','?')}({r.get('score', 0):.2f})"
                            if isinstance(r.get("score"), (int, float))
                            else f"{r.get('task','?')}({r.get('score','?')})"
                        )
                        for r in routing_list[:5]
                    ]
                )
                if isinstance(routing_list, list)
                else str(routing_list)
            )
            t = yield_thinking(f"?????: {steps_str}", "routing", "hybrid")
            if t:
                yield t

        # ????????????
        if context_info and context_info.get("complexity"):
            complexity_msg = f"?? ?????: {context_info['complexity']}"
            yield f"data: {json.dumps({'type': 'info', 'message': complexity_msg})}\n\n"
            t = yield_thinking(
                f"???????: {context_info['complexity']}", "analyzing", "hybrid"
            )
            if t:
                yield t

        # ???????????????
        # _llm_user_input ??????????????????????
        effective_input = _llm_user_input
        if (
            context_info
            and context_info.get("is_continuation")
            and context_info.get("enhanced_input")
        ):
            effective_input = context_info["enhanced_input"]
            _app_logger.debug(
                f"[STREAM] Using enhanced input (length: {len(effective_input)})"
            )
            yield f"data: {json.dumps({'type': 'info', 'message': '?? ???????????????'})}\n\n"
            t = yield_thinking(
                f"????????????? ({len(effective_input)} ??)",
                "context",
                "hybrid",
            )
            if t:
                yield t

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
        interrupt_event = _interrupt_manager.get_event(session_name)

        def interrupted():
            return _interrupt_manager.is_interrupted(session_name)

        # ????: ????
        from web.smart_feedback import SmartFeedback

        _task_labels = SmartFeedback.TASK_LABELS
        _tl = _task_labels.get(task_type, task_type)
        yield f"data: {json.dumps({'type': 'progress', 'message': f'????{_tl}??', 'detail': get_model_display_name(model_id)})}\n\n"

        try:
            # ?????????????????
            used_model = "unknown"

            # SYSTEM handler ? delegated
            if task_type == "SYSTEM":
                for chunk in handle_system(
                    yield_thinking, user_input, session_name,
                    start_time, client, model_id, system_instruction,
                    session_manager, _app_logger,
                ):
                    yield chunk
                    if interrupted():
                        return
                return

            # === FILE TASKS ? workspace task-stream only ===
            _file_task_types = ("FILE_OP", "FILE_EDIT", "FILE_SEARCH", "FILE_GEN",
                               "DOC_ANNOTATE", "MEETING_EXTRACT")
            _is_file_task = task_type in _file_task_types
            _is_file_direct = (
                not _is_file_task
                and has_recent_upload
                and recent_file_path
                and os.path.isfile(recent_file_path)
                and task_type in ("RESEARCH", "CHAT")
                and _uses_standard_workflow_route()
            )
            if _is_file_task or _is_file_direct:
                message = (
                    "???????????????????????????????"
                    "???????????????????????????"
                )
                _app_logger.warning(
                    "[CHAT] blocked legacy file-task execution via /api/chat/stream "
                    "(task_type=%s, session=%s)",
                    task_type,
                    session_name,
                )
                yield _safe_sse({
                    "type": "error",
                    "message": message,
                    "_message_as_error": True,
                })
                yield _safe_sse({
                    "type": "done",
                    "images": [],
                    "saved_files": [],
                    "total_time": round(time.time() - start_time, 1),
                    "had_error": True,
                    "legacy_file_task_blocked": True,
                })
                return

            # === WEB_SEARCH handler ? delegated ===
            if task_type == "WEB_SEARCH":
                for chunk in handle_web_search(
                    yield_thinking, context_info, client,
                    session_manager, user_input, session_name,
                    start_time, _app_logger, MODEL_MAP,
                ):
                    yield chunk
                    if interrupted():
                        return
                return

            # === ?? Tree of Thought ? RESEARCH/CHAT only ===
            _tot_result = {"handled": False}
            for chunk in handle_tree_of_thought(
                task_type, effective_input, user_input,
                session_name, start_time, model_id,
                system_instruction, _uses_standard_workflow_route,
                settings_manager, session_manager, MODEL_MAP, _app_logger,
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
                    yield_thinking, task_type, user_input,
                    effective_input, session_name, start_time,
                    model_id, system_instruction, context_info,
                    _rag_context_block, client, session_manager,
                    MODEL_MAP, WebSearcher, _app_logger,
                    stream_with_keepalive, interrupted,
                ):
                    yield chunk
                    if interrupted():
                        return
                return

            # === PAINTER handler ===
            if task_type == "PAINTER":
                for chunk in handle_painter(
                    task_type, user_input, effective_input,
                    session_name, start_time, context_info,
                    client, session_manager, settings_manager,
                    Utils, WORKSPACE_DIR, _app_logger, interrupted,
                ):
                    yield chunk
                    if interrupted():
                        return
                return

            # === Regular Mode (????) ===
            # Regular mode handler ? delegated
            for chunk in handle_regular(
                yield_thinking, task_type, user_input,
                session_name, start_time, client, _app_logger,
                session_manager, settings_manager, request, _safe_sse,
                MODEL_MAP, locked_model, use_instruction, history,
                context_info, _interrupt_manager, _rag_context_block,
                SmartDispatcher, _LMRv2,
            ):
                yield chunk
                if interrupted():
                    return
            return

        except Exception as e:
            error_str = str(e)
            _app_logger.debug(f"[CHAT] Exception: {error_str}")

            from app.core.shared.llm_helpers import is_online_failure as _iof2, is_ollama_alive as _ioav2
            from app.core.routing import LocalModelRouter as _LMR_fb2
            _OLLAMA_TEXT_TASKS2 = {"CHAT", "CODER", "RESEARCH", "FILE_GEN", "MULTI_STEP", "AGENT"}

            # ????? ? ???????????????/Key??/503/??????????????
            if _iof2(e) and task_type in _OLLAMA_TEXT_TASKS2 and _ioav2():
                _app_logger.warning(f"[CHAT] outer: cloud failure ({error_str[:60]}), trying Ollama")
                yield f"data: {json.dumps({'type': 'progress', 'message': '?? ?? AI ???????????? (Ollama)...', 'detail': ''}, ensure_ascii=False)}\n\n"
                _ollama_ok = False
                try:
                    _fb2_stream = _LMR_fb2.generate_stream(
                        user_input, history=history,
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
                                f"{session_name}.json", user_input, _fb2_full,
                                task=task_type, model_name=f"ollama/local",
                            )
                            total_time = time.time() - start_time
                            yield f"data: {json.dumps({'type': 'done', 'images': [], 'saved_files': [], 'total_time': total_time})}\n\n"
                            return
                except Exception as _fb2_err:
                    _app_logger.error(f"[CHAT] outer Ollama fallback failed: {_fb2_err}")

                if not _ollama_ok:
                    # Ollama???????????
                    error_response = f"? ?? AI ??????????????\n\n????: {error_str[:150]}"
                    session_manager.append_and_save(
                        f"{session_name}.json", user_input, error_response,
                        task=task_type, model_name=model_id,
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
                    _app_logger.warning(
                        f"[CHAT] ??????? {model_id} ????? 120s???????"
                    )
                except Exception:
                    import logging; logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)
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
        parallel_system_enabled=PARALLEL_SYSTEM_ENABLED,
        stop_dispatcher=stop_dispatcher,
        chat_dir=CHAT_DIR,
        workspace_dir=WORKSPACE_DIR,
    )
