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
    try:
        from parallel_api import register_parallel_api
        from parallel_executor import (
            Priority,
            Task,
            TaskStatus,
            TaskType,
            cancel_task,
            get_next_task,
            get_queue_manager,
            get_resource_manager,
            get_task_monitor,
            submit_task,
        )
        from task_dispatcher import get_scheduler, start_dispatcher, stop_dispatcher
    except ImportError:
        from web.parallel_api import register_parallel_api
        from web.parallel_executor import (
            Priority,
            Task,
            TaskStatus,
            TaskType,
            cancel_task,
            get_next_task,
            get_queue_manager,
            get_resource_manager,
            get_task_monitor,
            submit_task,
        )
        from web.task_dispatcher import (
            get_scheduler,
            start_dispatcher,
            stop_dispatcher,
        )

    PARALLEL_SYSTEM_ENABLED = True
except ImportError as e:
    _app_logger.warning(f"[WARNING] Failed to import parallel execution system: {e}")
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

from app.core.llm.gemini_config import (
    get_gemini_api_key,
    load_gemini_config_env,
    set_runtime_gemini_api_key,
    write_gemini_config_file,
)

try:
    from google import genai
    from google.genai import types
except Exception:  # pragma: no cover - surfaced when cloud features are used
    genai = None
    types = None

_loaded_gemini_config = load_gemini_config_env(override=False)
API_KEY = get_gemini_api_key(ensure_loaded=False)
GEMINI_API_BASE = os.getenv("GEMINI_API_BASE", "").strip()
FORCE_PROXY = os.getenv("FORCE_PROXY", "").strip()

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
    candidates = []

    # 0) User-configured manual proxy (highest priority after FORCE_PROXY)
    try:
        _us = settings_manager.get("proxy", "enabled")
        _um = settings_manager.get("proxy", "manual_proxy") or ""
        if _us is not False and _um.strip():
            candidates.append(_normalize_proxy_url(_um.strip()))
    except Exception:
            import logging; logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)

    # 1) Environment variables first (if user/system already configured)
    env_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if env_proxy:
        candidates.append(_normalize_proxy_url(env_proxy))

    # 2) Windows Internet Settings proxy (for "Use a proxy server")
    if sys.platform.startswith("win"):
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                proxy_enabled = winreg.QueryValueEx(key, "ProxyEnable")[0]
                if proxy_enabled:
                    proxy_server = str(
                        winreg.QueryValueEx(key, "ProxyServer")[0]
                    ).strip()
                    if proxy_server:
                        # Formats:
                        #   127.0.0.1:7890
                        #   http=127.0.0.1:7890;https=127.0.0.1:7890
                        if "=" in proxy_server and ";" in proxy_server:
                            pairs = [
                                p.strip() for p in proxy_server.split(";") if p.strip()
                            ]
                            parsed_map = {}
                            for pair in pairs:
                                if "=" in pair:
                                    k, v = pair.split("=", 1)
                                    parsed_map[k.strip().lower()] = v.strip()
                            for proto in ["https", "http", "socks", "socks5"]:
                                if parsed_map.get(proto):
                                    candidates.append(
                                        _normalize_proxy_url(parsed_map.get(proto))
                                    )
                        else:
                            candidates.append(_normalize_proxy_url(proxy_server))
        except Exception:
            import logging; logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)

    # 3) Built-in localhost fallback options
    candidates.extend(PROXY_OPTIONS)

    # De-duplicate while preserving order
    deduped = []
    seen = set()
    for item in candidates:
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def setup_proxy():
    # 优先使用强制代理（不需要测试）
    if FORCE_PROXY and FORCE_PROXY.lower() not in ("auto", "system"):
        os.environ["HTTPS_PROXY"] = FORCE_PROXY
        os.environ["HTTP_PROXY"] = FORCE_PROXY
        _app_logger.info(f"🔧 使用强制代理: {FORCE_PROXY}")
        return FORCE_PROXY

    # 用户明确禁用代理时，清除环境变量并退出
    try:
        if settings_manager.get("proxy", "enabled") is False:
            os.environ.pop("HTTPS_PROXY", None)
            os.environ.pop("HTTP_PROXY", None)
            _app_logger.info("🔧 用户已禁用代理")
            return None
    except Exception:
            import logging; logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)

    # 自动匹配系统代理与本地常见端口
    import socket
    from urllib.parse import urlparse

    proxy_candidates = _extract_system_proxy_candidates()

    for proxy in proxy_candidates:
        try:
            # 从 URL 提取 host:port
            parsed = urlparse(proxy)
            host = parsed.hostname
            port = parsed.port
            if not host or not port:
                continue

            # 快速端口检测（0.1秒超时）
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.1)
            result = sock.connect_ex((host, port))
            sock.close()

            if result == 0:
                os.environ["HTTPS_PROXY"] = proxy
                os.environ["HTTP_PROXY"] = proxy
                _app_logger.info(f"✅ 自动匹配系统代理: {proxy}")
                return proxy
        except Exception:
            continue

    return None


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
try:
    from settings import SettingsManager as _SettingsManager
except ImportError:
    from web.settings import SettingsManager as _SettingsManager
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


# 创建 GenAI 客户端 (配置代理和自定义端点)
def create_client():
    import httpx

    proxy = get_detected_proxy()
    # 超时时间: 连接30秒, 读取180秒 (图像生成和长文本生成需要更长时间)
    timeout_config = httpx.Timeout(180.0, connect=30.0)

    # 构建 http_options
    http_options = {}

    # 注意：最新的 Gemini 模型（如 gemini-2.5-flash-lite）需要 v1beta API
    # v1 API 只支持旧的模型。这里使用 v1beta。
    http_options["api_version"] = "v1beta"

    # 自定义 API 端点（用于中转服务）
    if GEMINI_API_BASE:
        http_options["base_url"] = GEMINI_API_BASE
        _app_logger.info(f"📡 API 端点: {GEMINI_API_BASE}")

    # 配置代理 - 通过环境变量确保被使用
    if proxy:
        os.environ["HTTP_PROXY"] = proxy
        os.environ["HTTPS_PROXY"] = proxy
        _app_logger.info(f"🔌 设置代理: {proxy}")

    # 使用 httpx with explicit proxy for genai
    # 注意：HttpOptions 字段名为 httpx_client (snake_case)，不是 httpxClient
    # 但实测显示：通过 env vars 设置代理比显式传入 httpx_client 更稳定（无 SSL 问题），
    # 因此这里直接使用 timeout-only 的 httpx 客户端，代理由 env vars 自动接管
    from google.genai._api_client import HttpOptions as _HttpOptions

    try:
        http_client = httpx.Client(timeout=timeout_config, verify=True)
    except Exception as e:
        _app_logger.warning(f"⚠️ 创建 HTTP 客户端出错: {e}")
        http_client = httpx.Client(timeout=timeout_config)

    # 构建 HttpOptions 对象
    opts_kwargs = dict(
        api_version=http_options.get("api_version", "v1beta"),
        httpx_client=http_client,
    )
    if http_options.get("base_url"):
        opts_kwargs["base_url"] = http_options["base_url"]

    return genai.Client(api_key=API_KEY, http_options=_HttpOptions(**opts_kwargs))


# ── 本地模型配置读取 ──────────────────────────────────────────────────────
def _get_local_model_config() -> tuple:
    """
    读取 user_settings.json，返回 (model_mode, local_model_tag)。
    model_mode: "local" / "cloud" / "deepseek" / "gemini"（默认 cloud）
    local_model_tag: 如 "qwen2.5:7b" 或 None
    """
    try:
        settings_path = os.path.join(PROJECT_ROOT, "config", "user_settings.json")
        with open(settings_path, "r", encoding="utf-8") as _f:
            _data = json.load(_f)
        mode = _data.get("model_mode", "cloud")
        ai_settings = _data.get("ai")
        if not isinstance(ai_settings, dict):
            ai_settings = {}
        tag = ai_settings.get("local_model") or _data.get("local_model")
        return mode, tag or None
    except Exception:
        return "cloud", None


# 懒加载客户端（mode+tag 作为缓存 key，切换模式后自动重建）
_client = None
_client_mode_key: tuple = (None, None)  # (model_mode, local_model_tag)


def get_client():
    """
    获取 AI 客户端（懒加载）。
    - 若 user_settings.json 中 model_mode == "local"，仅返回 OllamaClientProxy
    - 否则返回 Gemini genai.Client（原有行为）
    """
    global _client, _client_mode_key
    model_mode, local_model = _get_local_model_config()
    current_key = (model_mode, local_model)

    # 模式或模型发生变化时，重置缓存
    if _client is not None and _client_mode_key != current_key:
        _client = None

    if _client is None:
        if model_mode == "local":
            try:
                from app.core.llm.ollama_provider import create_ollama_client

                _client = create_ollama_client(model_tag=local_model or None)
                _app_logger.debug(
                    f"[Koto] 🦙 使用本地模型: {getattr(_client, '_model_tag', None) or local_model or 'auto-select'}"
                )
            except Exception as _e:
                _app_logger.error(f"[Koto] ❌ 本地模式下 Ollama 初始化失败: {_e}")
                raise RuntimeError("本地模式已启用，但 Ollama 初始化失败") from _e
        else:
            _client = create_client()
        _client_mode_key = current_key

    return _client


# ── Token 监测模块（本地统计，无需额外连接 Google）─────────────────────────
try:
    from web.token_tracker import record_usage as _record_token_usage

    _TOKEN_TRACKER_ENABLED = True
except ImportError:
    _TOKEN_TRACKER_ENABLED = False

    def _record_token_usage(*_a, **_kw):
        pass


def _is_interactions_only(model_id: str) -> bool:
    """
    检查 model_id 是否需要走 Interactions API 而非 generate_content。
    使用模块级 _INTERACTIONS_ONLY_MODELS（运行时查找，定义后一定可用）。
    """
    try:
        iom = _INTERACTIONS_ONLY_MODELS  # noqa: F821 — 模块级全局，运行时已定义
    except NameError:
        iom = _DEFAULT_INTERACTIONS_ONLY_MODELS
    return _is_interactions_only_helper(model_id, iom)


def _is_interactions_agent(model_id: str) -> bool:
    """True for genuine agent models that require agent=; False for model= variants.
    deep-research-* models use agent=; gemini-3-*-preview use model=.
    """
    return str(model_id or "").startswith("deep-research")


_logger_tracked = logging.getLogger(__name__)


class _TrackedModels:
    """
    拦截 client.models 的 generate_content / generate_content_stream，实现：
      1. Token 用量自动记录
      2. Interactions-only 模型防御路由（前置检查 + 异常捕获兜底）
         - 在调用 generate_content 前先判断模型是否 interactions-only
         - 若是，直接转发到 _call_interactions_api_sync()
         - 若否，正常调用后 catch "Interactions API" 400 错误并 retry
    """

    def __init__(self, real_models):
        object.__setattr__(self, "_real", real_models)

    # ── 内部工具 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _call_ia(model_id: str, contents, config) -> "_FakeGenerateContentResponse":
        """提取文本并转发到 _call_interactions_api_sync，返回包装后的响应对象。"""
        prompt, sys_instr = _extract_prompt_text(contents, config)
        text = _call_interactions_api_sync(  # noqa: F821
            model_id=model_id,
            user_prompt=prompt,
            sys_instruction=sys_instr,
        )
        return _FakeGenerateContentResponse(text or "")

    # ── generate_content ────────────────────────────────────────────────────

    def generate_content(self, model=None, *args, **kwargs):
        # 兼容旧式位置调用
        if model is None and args:
            model, args = args[0], args[1:]

        model_str = str(model or "")
        real = object.__getattribute__(self, "_real")

        # ① 前置路由：interactions-only 模型直接走 Interactions API
        if _is_interactions_only(model_str):
            _logger_tracked.debug(
                "[TrackedModels] %s → Interactions API (pre-check)", model_str
            )
            try:
                return self._call_ia(
                    model_str, kwargs.get("contents"), kwargs.get("config")
                )
            except Exception as _ia_err:
                _logger_tracked.warning(
                    "[TrackedModels] Interactions API failed for %s: %s — retrying generate_content as last resort",
                    model_str,
                    _ia_err,
                )
                # 强行尝试 generate_content（极少数情况模型实际支持）

        # ② 标准调用 + 异常兜底
        try:
            response = real.generate_content(model=model, **kwargs)
        except Exception as _gc_err:
            _err_str = str(_gc_err)
            if "Interactions API" in _err_str or (
                "only supports" in _err_str and "Interactions" in _err_str
            ):
                _logger_tracked.warning(
                    "[TrackedModels] 400 Interactions-API error for model=%s — retrying via Interactions API",
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
            raise  # 非 Interactions 错误，或 retry 也失败后，重新抛出原始异常

        # ③ Token 记录
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

    # ── generate_content_stream ─────────────────────────────────────────────

    def generate_content_stream(self, model=None, *args, **kwargs):
        """
        拦截流式调用。
        interactions-only 模型不支持流式接口；遇到此类模型时同步调用
        Interactions API，再将完整结果包装成单个 chunk yield 出去，
        保证调用方 for chunk in stream 的用法不变。
        """
        if model is None and args:
            model, args = args[0], args[1:]

        model_str = str(model or "")
        real = object.__getattribute__(self, "_real")

        # ① 前置路由：interactions-only 模型 → 同步调用后单 chunk 输出
        if _is_interactions_only(model_str):
            _logger_tracked.debug(
                "[TrackedModels] %s → Interactions API stream-adapter (pre-check)",
                model_str,
            )
            try:
                fake_resp = self._call_ia(
                    model_str, kwargs.get("contents"), kwargs.get("config")
                )
                yield fake_resp  # 调用方 for chunk in stream: chunk.text 仍能工作
                return
            except Exception as _ia_err:
                _logger_tracked.warning(
                    "[TrackedModels] Interactions API stream-adapter failed for %s: %s — raising",
                    model_str,
                    _ia_err,
                )
                raise

        # ② 标准流式调用 + 异常兜底（首个 chunk 前触发）
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
                    "[TrackedModels] 400 Interactions-API error in stream for model=%s — retrying via Interactions API",
                    model_str,
                )
                fake_resp = self._call_ia(
                    model_str, kwargs.get("contents"), kwargs.get("config")
                )
                yield fake_resp
                return
            raise

    def generate_images(self, model=None, *args, **kwargs):
        """拦截 generate_images（Imagen），按图片数量记录合成 token 用量"""
        if model is None and args:
            model, args = args[0], args[1:]
        real = object.__getattribute__(self, "_real")
        response = real.generate_images(model=model, **kwargs)
        if _TOKEN_TRACKER_ENABLED:
            try:
                # Imagen 按张计费，用合成 token 数换算（1000 tokens/张，配合定价表得出正确费用）
                num_images = max(
                    1, len(getattr(response, "generated_images", []) or [])
                )
                _record_token_usage(
                    model=str(model or "unknown"),
                    prompt_tokens=1000 * num_images,
                    completion_tokens=0,
                )
            except Exception:
                import logging; logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)
        return response

    def embed_content(self, model=None, *args, **kwargs):
        """拦截 embed_content，记录 embedding token 用量"""
        if model is None and args:
            model, args = args[0], args[1:]
        if not model or str(model).endswith("text-embedding-004"):
            from app.core.llm.embedding_model_selector import (
                resolve_gemini_embedding_model,
            )

            model = resolve_gemini_embedding_model()
        real = object.__getattribute__(self, "_real")
        response = real.embed_content(model=model, **kwargs)
        if _TOKEN_TRACKER_ENABLED:
            try:
                usage = getattr(response, "usage_metadata", None)
                if usage:
                    prompt_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
                else:
                    # embed_content 并不总是返回 usage_metadata，按输入内容字符数估算
                    contents = kwargs.get("contents", "") or ""
                    if isinstance(contents, list):
                        contents = " ".join(str(c) for c in contents)
                    prompt_tokens = max(
                        1, len(str(contents)) // 4
                    )  # 粗略估算 1 token ≈ 4 字符
                _record_token_usage(
                    model=str(model or "unknown"),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=0,
                )
            except Exception:
                import logging; logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)
        return response

    def __getattr__(self, name):
        real = object.__getattribute__(self, "_real")
        return getattr(real, name)


# 保持向后兼容的 client 变量（通过属性访问触发懒加载）
class _ClientProxy:
    """代理类，实现懒加载"""

    def __getattr__(self, name):
        obj = getattr(get_client(), name)
        if name == "models":
            return _TrackedModels(obj)
        return obj


client = _ClientProxy()


def create_research_client():
    """创建专用于 Deep Research 的长超时客户端 (5分钟 read timeout)"""
    import httpx
    from google.genai._api_client import HttpOptions as _HttpOptions

    proxy = get_detected_proxy()
    # 深度研究需要更长的超时时间：连接30秒，读取5分钟
    timeout_config = httpx.Timeout(300.0, connect=30.0)

    # 配置代理 - 通过环境变量确保被使用（同 create_client）
    if proxy:
        os.environ["HTTP_PROXY"] = proxy
        os.environ["HTTPS_PROXY"] = proxy

    # 自定义 httpx 客户端（仅用于扩展超时；代理由 env vars 接管）
    http_client = httpx.Client(timeout=timeout_config, verify=True)

    opts_kwargs = dict(
        api_version="v1beta",
        httpx_client=http_client,
    )
    if GEMINI_API_BASE:
        opts_kwargs["base_url"] = GEMINI_API_BASE

    return genai.Client(api_key=API_KEY, http_options=_HttpOptions(**opts_kwargs))


def _poll_interaction(
    ia_client,
    interaction_id: str,
    *,
    timeout: float = 900.0,
    initial_sleep: float = 2.0,
    backoff_multiplier: float = 1.5,
    max_sleep: float = 30.0,
    label: str = "",
) -> object:
    """
    生产级 Interactions API 轮询器。

    实现指数退避 + 抖动 + 最大超时，避免轮询风暴：
      - every successful poll: sleep *= backoff_multiplier（上限 max_sleep）
      - ±25% 随机抖动，分散并发请求峰值
      - 超时后自动请求取消，再抛出 TimeoutError

    状态机：
      ─ RUNNING   (active / running / queued / …)  →  继续等待
      ─ COMPLETED (completed)                       →  返回最终 interaction 对象
      ─ FAILED    (failed / cancelled / error)      →  抛出 RuntimeError

    Args:
        ia_client:          已初始化的 Gemini client（含 .interactions 接口）
        interaction_id:     rc.interactions.create() 返回的 job ID
        timeout:            最大等待秒数（默认 15 分钟）
        initial_sleep:      首次轮询前等待秒数
        backoff_multiplier: 退避倍率（每轮自动乘以此值）
        max_sleep:          单次等待上限（秒）
        label:              日志前缀标签（便于区分调用方）

    Returns:
        status == "completed" 的 interaction 对象

    Raises:
        RuntimeError: interaction_id 为空
        TimeoutError: 超出 timeout 仍未完成（已请求取消）
        RuntimeError: job 返回 failed / cancelled / error 状态
    """
    import random as _random

    if not interaction_id:
        raise RuntimeError(f"[{label or 'poll'}] interaction_id 为空，无法轮询")

    _log = logging.getLogger(__name__)
    tag = f"[Interactions{':' + label if label else ''}]"

    start = time.monotonic()
    sleep_interval = initial_sleep
    last_status = ""
    poll_count = 0

    _log.info("%s ⏳ job=%s  开始轮询 (timeout=%.0fs)", tag, interaction_id, timeout)

    while True:
        elapsed = time.monotonic() - start

        # ── 超时检查 ──────────────────────────────────────────────────────────
        if elapsed >= timeout:
            _log.warning(
                "%s ⌛ job=%s  轮询超时 (%.0fs elapsed)", tag, interaction_id, elapsed
            )
            try:
                ia_client.interactions.cancel(interaction_id)
                _log.info("%s 🛑 job=%s  已请求取消", tag, interaction_id)
            except Exception as _ce:
                _log.debug("%s 取消请求失败: %s", tag, _ce)
            raise TimeoutError(
                f"Interactions API 超时 ({timeout:.0f}s) job={interaction_id}"
            )

        # ── 轮询请求（网络抖动时短暂等待后重试，不立即放弃）──────────────────
        try:
            interaction = ia_client.interactions.get(interaction_id)
        except Exception as _poll_err:
            _log.warning(
                "%s job=%s  轮询请求失败 (#%d): %s",
                tag,
                interaction_id,
                poll_count,
                _poll_err,
            )
            time.sleep(min(sleep_interval, 10.0))
            continue

        status = str(getattr(interaction, "status", "") or "").lower().strip()
        poll_count += 1

        # ── 仅在状态变化时输出日志，避免日志洪水 ─────────────────────────────
        if status != last_status:
            msg = _INTERACTION_STATUS_MSGS.get(status, f"状态: {status!r}")
            _log.info(
                "%s 🔄 job=%s  [poll#%d | %.0fs] %s",
                tag,
                interaction_id,
                poll_count,
                elapsed,
                msg,
            )
            last_status = status

        # ── 终止状态判断 ───────────────────────────────────────────────────────
        if status in _INTERACTION_TERMINAL_STATES:
            if status in _INTERACTION_SUCCESS_STATES:
                _log.info(
                    "%s ✅ job=%s  完成 (total=%.1fs, polls=%d)",
                    tag,
                    interaction_id,
                    elapsed,
                    poll_count,
                )
                return interaction
            # failed / cancelled / error
            err_detail = getattr(interaction, "error", None) or status
            _log.error(
                "%s ❌ job=%s  失败 status=%s  detail=%s",
                tag,
                interaction_id,
                status,
                err_detail,
            )
            raise RuntimeError(
                f"Interactions API job 失败 (status={status}, detail={err_detail})"
            )

        # ── 计算下一轮等待时间：指数退避 + ±25% 随机抖动 ─────────────────────
        jitter = sleep_interval * 0.25 * (_random.random() * 2 - 1)
        actual_sleep = max(1.0, min(sleep_interval + jitter, max_sleep))
        remaining = timeout - elapsed
        actual_sleep = min(actual_sleep, max(0.5, remaining - 0.1))  # 不超过剩余时间

        _log.debug(
            "%s job=%s  等待 %.1fs 后再次轮询…", tag, interaction_id, actual_sleep
        )
        time.sleep(actual_sleep)

        # 逐步延长轮询间隔，直到 max_sleep 上限
        sleep_interval = min(sleep_interval * backoff_multiplier, max_sleep)


def _extract_interaction_text_global(interaction) -> str:
    """
    从 interaction 对象递归提取输出文本。
    兼容多种 SDK 返回格式：outputs 列表、text 属性、parts、Pydantic model_dump、dict 等。
    """

    def _walk(obj) -> list:
        if obj is None:
            return []
        if isinstance(obj, str):
            s = obj.strip()
            return [s] if s else []
        if isinstance(obj, dict):
            results = []
            for key in ("output_text", "text", "content"):
                val = obj.get(key)
                if isinstance(val, str) and val.strip():
                    results.append(val.strip())
                    return results  # 优先返回语义最强的字段
            for val in obj.values():
                results.extend(_walk(val))
            return results
        if isinstance(obj, (list, tuple)):
            results = []
            for item in obj:
                results.extend(_walk(item))
            return results
        # Pydantic / SDK 对象：先尝试 model_dump()
        if hasattr(obj, "model_dump"):
            try:
                return _walk(obj.model_dump())
            except Exception:
                import logging; logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)
        if hasattr(obj, "text") and obj.text:
            return [str(obj.text).strip()]
        if hasattr(obj, "parts"):
            results = []
            for p in obj.parts or []:
                results.extend(_walk(p))
            return results
        if hasattr(obj, "outputs"):
            results = []
            for o in obj.outputs or []:
                results.extend(_walk(o))
            return results
        return []

    parts = _walk(getattr(interaction, "outputs", None))
    if not parts:
        parts = _walk(interaction)

    # 去重，保持原始顺序
    seen: set = set()
    deduped = []
    for p in parts:
        if p not in seen:
            deduped.append(p)
            seen.add(p)
    return "\n".join(deduped).strip()


def _call_interactions_api_sync(
    model_id: str,
    user_prompt: str,
    sys_instruction: str = None,
    timeout: float = 900.0,
) -> str:
    """
    通过 Interactions API 调用 gemini-3-*-preview / deep-research 等异步模型。
    这些模型不支持 client.models.generate_content()，必须使用此端点。

    工作流程：
      1. 本地模型模式 → 直接用 Ollama，跳过 Interactions API
      2. 云端模式     → rc.interactions.create() 提交异步 job，捕获 interaction_id
      3.              → _poll_interaction() 轮询（指数退避，最大 timeout 秒）
      4.              → 提取并返回最终文本

    Args:
        model_id:        目标模型 ID
        user_prompt:     用户输入（已格式化）
        sys_instruction: 系统指令（可选）
        timeout:         最大等待秒数（默认 15 分钟）

    Returns:
        模型响应文本

    Raises:
        TimeoutError:   超时（已自动请求取消）
        RuntimeError:   job 失败或本地降级失败
    """
    _log = logging.getLogger(__name__)

    # ── 本地模型模式：用 Ollama 直接回答，无需 Interactions API ──────────────
    model_mode, _ = _get_local_model_config()
    if model_mode == "local":
        try:
            full_prompt = user_prompt
            if sys_instruction:
                full_prompt = (
                    f"[系统指令]\n{sys_instruction}\n\n[用户输入]\n{user_prompt}"
                )
            resp = get_client().models.generate_content(
                model=model_id,
                contents=full_prompt,
            )
            return getattr(resp, "text", "") or ""
        except Exception as _e:
            raise RuntimeError(f"本地模型 Interactions 降级失败: {_e}") from _e

    # ── 云端：提交异步 Interactions 任务 ─────────────────────────────────────
    full_input = user_prompt
    if sys_instruction:
        full_input = f"[系统指令]\n{sys_instruction}\n\n[用户输入]\n{user_prompt}"

    _rc = create_research_client()
    # Interactions API 区分两种调用方式：
    #   agent=  → deep-research 等真正的 Agent
    #   model=  → gemini-3-pro/flash-preview 等普通模型（用 agent= 会报 400）
    _create_kwargs: dict = {
        "input": full_input[:80000],
        "background": True,
        "stream": False,
    }
    if _is_interactions_agent(model_id):
        _create_kwargs["agent"] = model_id
    else:
        _create_kwargs["model"] = model_id

    interaction = _rc.interactions.create(**_create_kwargs)

    interaction_id = getattr(interaction, "id", None)
    init_status = str(getattr(interaction, "status", "") or "").lower()

    # 快速路径：极少数情况下 create() 即刻返回已完成
    if init_status in _INTERACTION_SUCCESS_STATES:
        _log.info(
            "[Interactions] ⚡ job=%s 即时完成 (status=%s)", interaction_id, init_status
        )
        return _extract_interaction_text_global(interaction)

    if init_status in _INTERACTION_FAIL_STATES:
        err = getattr(interaction, "error", init_status)
        raise RuntimeError(
            f"Interactions API job 立即失败 (status={init_status}): {err}"
        )

    if not interaction_id:
        raise RuntimeError(
            f"Interactions API 未返回有效的 interaction_id (model={model_id})"
        )

    # 慢速路径：轮询等待（指数退避，含自动超时取消）
    final_interaction = _poll_interaction(
        _rc,
        interaction_id,
        timeout=timeout,
        initial_sleep=2.0,
        backoff_multiplier=1.5,
        max_sleep=30.0,
        label=model_id,
    )

    text = _extract_interaction_text_global(final_interaction)
    _log.info("[Interactions] 📄 提取文本 %d 字符 (model=%s)", len(text), model_id)
    return text


from web.utils.threading_utils import run_with_heartbeat, run_with_timeout, stream_with_keepalive


app, APP_VERSION, _cors_origins = create_flask_app(__name__)

# ── Flask-SocketIO 初始化（文件助手全双工通信）──
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


# ================= 并行执行系统初始化 =================
if PARALLEL_SYSTEM_ENABLED:
    _app_logger.debug("[PARALLEL] 🚀 Initializing parallel execution system...")
    try:
        register_parallel_api(app)
        start_dispatcher()
        _app_logger.info(
            "[PARALLEL] ✅ Parallel execution system initialized successfully"
        )
    except Exception as e:
        _app_logger.error(
            f"[PARALLEL] ❌ Failed to initialize parallel execution system: {e}"
        )
        PARALLEL_SYSTEM_ENABLED = False

# ================= WebSocket 支持（可选） =================
sock = init_notification_socket(
    app,
    _app_logger,
    Sock,
    lambda: get_notification_manager(),
)


# 同步注册所有蓝图（必须在 app.run() 之前完成，否则 Flask 3.x 会在首次请求后拒绝注册）
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

# ================= 动态模型管理器 =================
# 自动从 API 发现可用模型并按任务类型智能匹配，无需手动维护模型列表。
# 新模型上线后自动感知，TTL 缓存每 6 小时刷新一次。

try:
    from web.model_manager import KNOWN_MODEL_REGISTRY as _MODEL_REGISTRY
    from web.model_manager import ModelManager
    from web.model_manager import TASK_REQUIREMENTS as _MODEL_TASK_REQUIREMENTS
    from web.model_manager import score_model_for_task as _score_model_for_task

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

# 静态默认值（API 不可用时的兜底，也是启动时的初始值）
# 注意：只有 deep-research-pro-preview-* 是 Interactions API agent，其他模型均用 generate_content
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

# ─── Interactions-API-only 模型（动态更新，静态默认兜底）──────────────────────
# 这些模型不支持 client.models.generate_content()，必须走 Interactions API
# 注意：gemini-2.5-flash 和 gemini-2.5-pro 是普通模型，直接用 generate_content，不在此列表中
_INTERACTIONS_ONLY_MODELS = {
    mid for mid in _DEFAULT_INTERACTIONS_ONLY_MODELS
}
# 当前 Interactions API 模型均支持 background=True
_NO_BACKGROUND_MODELS: set = set()
# 当 Interactions API 也失败时的最终降级模型
_INTERACTIONS_FALLBACK_MODEL = "deepseek-chat"

# ── Interactions API 轮询状态常量 ────────────────────────────────────────────
_INTERACTION_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "error"})
_INTERACTION_SUCCESS_STATES = frozenset({"completed"})
_INTERACTION_FAIL_STATES = frozenset({"failed", "cancelled", "error"})

# 中间状态 → 人类可读日志（仅当状态变化时输出，避免日志洪水）
_INTERACTION_STATUS_MSGS: dict = {
    "active": "Agent 工作中…",
    "running": "Agent 工作中…",
    "queued": "等待队列中，即将开始…",
    "in_progress": "Agent 处理中…",
    "thinking": "Agent 深度思考中…",
    "searching": "Agent 正在检索互联网…",
    "reading": "Agent 正在阅读资料…",
    "generating": "Agent 正在生成回复…",
}

# 全局模型管理器实例（后台初始化）
_model_manager = None

# ── 模型解析函数（已提取至 web/models/resolver.py）────────────────────────
from web.models.resolver import (
    resolve_model_alias as _resolve_model_alias,
    resolve_model_lock_task as _resolve_model_lock_task,
    model_supports_locked_task as _model_supports_locked_task,
    pick_available_fallback_model as _pick_available_fallback_model,
    resolve_requested_model_id as _resolve_requested_model_id,
    init_resolver as _init_model_resolver,
)

# 静态种子：确保模型解析器在动态管理器就绪前也能工作
try:
    _init_model_resolver(
        model_map=MODEL_MAP,
        model_task_requirements=_MODEL_TASK_REQUIREMENTS,
        score_model_for_task=_score_model_for_task,
    )
except Exception:
    pass

from web.sse.sanitizer import sanitize_sse_text_field as _sanitize_sse_text_field
from web.sse.sanitizer import safe_sse as _safe_sse


def _sync_model_routes_from_manager(force_refresh: bool = False) -> bool:
    """将 ModelManager 最新结果同步到全局路由、fallback 和路由器组件。"""
    global MODEL_MAP, _model_manager, _INTERACTIONS_ONLY_MODELS, _INTERACTIONS_FALLBACK_MODEL

    if _model_manager is None:
        return False

    dynamic_map = _model_manager.refresh() if force_refresh else _model_manager.get_model_map()
    if not dynamic_map:
        return False

    MODEL_MAP.update(dynamic_map)
    # 同步模型解析器状态
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

    # 同步更新 SmartDispatcher 的 MODEL_MAP 引用
    try:
        SmartDispatcher._dependencies["MODEL_MAP"] = MODEL_MAP
    except Exception:
        import logging

        logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)

    # 同步更新 ModelFallbackExecutor 的路由表
    try:
        from app.core.llm.model_fallback import get_fallback_executor

        get_fallback_executor().update_model_map(MODEL_MAP)
    except Exception as _fe:
        _app_logger.warning(
            f"[ModelManager] ⚠️ ModelFallbackExecutor 同步失败（非致命）: {_fe}"
        )

    # 同步更新 AIRouter 的轻量路由模型
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
            f"[ModelManager] ⚠️ AIRouter 路由模型更新失败（非致命）: {_are}"
        )
    return True


def _init_model_manager():
    """
    在后台线程中初始化动态模型管理器并更新全局路由表。
    不阻塞主线程启动；路由表更新期间仍使用静态默认值。
    """
    global _model_manager
    if not _model_manager_available or ModelManager is None:
        _app_logger.debug("[ModelManager] 模块不可用，使用静态默认路由")
        return
    try:
        _app_logger.debug("[ModelManager] 🔍 正在发现可用模型...")
        _model_manager = ModelManager(client)
        _sync_model_routes_from_manager(force_refresh=True)
        _app_logger.info("[ModelManager] ✅ 动态路由已加载并完成组件同步")
    except Exception as _me:
        import traceback as _tb

        _app_logger.warning(
            f"[ModelManager] ⚠️ 动态路由初始化失败，使用静态默认值: {_me}"
        )
        _tb.print_exc()


def _model_manager_refresh_loop():
    """周期性刷新模型路由，避免进程长跑时路由映射过期。"""
    interval = max(60, int(os.getenv("KOTO_MODEL_MANAGER_REFRESH_INTERVAL", "900")))
    while True:
        time.sleep(interval)
        if _model_manager is None:
            continue
        try:
            synced = _sync_model_routes_from_manager(force_refresh=True)
            if synced:
                _app_logger.debug("[ModelManager] ✅ 周期刷新完成")
        except Exception as _refresh_err:
            _app_logger.warning(
                f"[ModelManager] ⚠️ 周期刷新失败（非致命）: {_refresh_err}"
            )


# 模型能力矩阵（用于显示，动态模型自动补充）
MODEL_INFO = {
    "deepseek-chat": {
        "name": "DeepSeek Chat",
        "speed": "🚀",
        "tier": 8,
        "strengths": ["推理", "分析", "代码", "复杂任务", "对话"],
    },
    "local-executor": {
        "name": "本地执行器",
        "speed": "🖥️",
        "tier": 0,
        "strengths": ["系统操作", "打开应用", "文件管理"],
    },
}



def get_model_display_name(model_id):
    """获取模型友好显示名称；动态发现的新模型自动从能力注册表补充。"""
    info = MODEL_INFO.get(model_id)
    if info:
        return f"{info['name']} {info['speed']}"
    # 动态模型：从 ModelManager 能力缓存获取
    if _model_manager:
        caps = _model_manager._cached_caps.get(model_id)
        if caps and caps.get("display"):
            return caps["display"]
    # 未知模型：直接展示 ID
    return model_id


# ================= 本地系统执行器 (已迁移到 web/local_executor.py) =================
try:
    from web.local_executor import LocalExecutor
except ImportError:
    from local_executor import LocalExecutor


# ================= Web search capability (migrated to web/web_searcher.py) =================
from web.web_searcher import WebSearcher

# === System Instruction ===
# 简化版系统指令 - 用于CHAT/RESEARCH等非文件生成任务
# 任务专属 system prompt 补充片段（在 chat_stream 确定 task_type 后追加）
from web.prompts.task_addendums import TASK_SYSTEM_ADDENDUMS as _TASK_SYSTEM_ADDENDUMS
from web.chat_system_instruction import (
    get_chat_system_instruction as _get_chat_system_instruction,
    get_default_chat_system_instruction as _get_DEFAULT_CHAT_SYSTEM_INSTRUCTION,
)


def _get_writing_style_instruction(user_input: str) -> str:
    """若命中写作任务，返回从用户画像提取的写作风格约束。"""
    text = (user_input or "").lower()
    writing_keywords = [
        "写",
        "润色",
        "改写",
        "总结",
        "汇报",
        "报告",
        "邮件",
        "文案",
        "周报",
        "日报",
        "计划",
        "说明",
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
            "\n\n## ✍️ 用户写作风格约束（自动学习）\n"
            f"- 语气：{formality}\n"
            f"- 详细度：{detail}\n"
            f"- 结构偏好：{structure_pref}\n"
            f"- 风格标签：{', '.join(tone_tags) if tone_tags else '无'}\n"
            "- 生成文本时优先匹配以上风格；若用户本轮明确要求其他风格，以用户本轮要求为准。"
        )
    except Exception as exc:
        _app_logger.debug(f"[StyleProfile] 注入失败: {exc}")
        return ""


def _get_system_instruction():
    """生成包含当前日期时间的文档生成系统指令（含 Skills 注入）"""
    from datetime import datetime

    now = datetime.now()
    date_str = now.strftime("%Y年%m月%d日")
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]

    _base_filegen = f"""你是 Koto 文档生成专家，专注于生成高质量、可用的文档。

## 当前时间上下文
📅 **生成日期**: {date_str} {weekday}

## 时间理解规则（严格遵守）
- 这是本次请求的唯一时间锚点，请据此理解“今天/本月/今年/1月”等相对时间。
- 当用户只说“X月”未写年份时，默认使用**当前年份**（例如当前是 2026 年，则“1月新番”默认指 2026 年 1 月）。
- 不要默认使用过去年份，除非用户明确指定（如“2024年1月新番”）。

## 核心职责
1. **直接输出文档内容** - 直接输出最终要保存的文档内容，而不是代码或JSON
2. **中文优先** - 使用简体中文，专业术语准确无误
3. **格式规范** - 使用标题、列表、段落进行清晰组织

## 文档生成规则

### 优先策略：直接输出模式（推荐）
- **直接输出最终文档内容**，无需代码包装
- 使用Markdown式格式组织（# ## ### 标题、- 列表、段落）
- 系统会自动将你的输出转换为Word/PDF
- 这是最快、最可靠的方法

示例（只输出内容，不输出代码）：
```
# 文档标题

## 第一节
内容段落...

## 第二节
- 要点1
- 要点2
```

### 代码生成模式（仅当需要特殊格式时）
- 必须使用 ---BEGIN_FILE: filename.py--- 和 ---END_FILE--- 标记
- 代码控制在 80 行以内
- **保存路径必须使用**: `import os; OUTPUT_DIR = os.environ.get('KOTO_OUTPUT_DIR', os.getcwd())`，然后把生成的文件保存到 `OUTPUT_DIR`
- 必须包含中文字体处理（特别是PDF生成）
- 使用 try/except 包装错误处理
- **仅当直接输出无法满足需求时才使用此模式**

## 禁止项清单
- ✗ 输出JSON格式的"虚拟文档"
- ✗ 输出结构化数据而非真实内容
- ✗ 生成 BEGIN_FILE/END_FILE 标记（除非必须生成Python代码）
- ✗ 生成要求用户手动复制粘贴的内容

## 优先级
1. **直接输出内容** > 代码生成 > JSON结构
2. 内容准确、结构清晰 > 输出格式完美
3. 实际可执行性 > 审美程度
"""
    # 注入 FILE_GEN 相关的 Skills
    try:
        from app.core.skills.skill_manager import SkillManager

        return SkillManager.inject_into_prompt(_base_filegen, task_type="FILE_GEN")
    except Exception:
        return _base_filegen


# SYSTEM_INSTRUCTION 不再在模块加载时构建，改为按需调用 _get_system_instruction()
# SYSTEM_INSTRUCTION = _get_system_instruction()


from web.filegen_time_context import (
    build_filegen_time_context as _build_filegen_time_context,
    parse_time_info_for_filegen as _parse_time_info_for_filegen,
)


def _get_filegen_brief_instruction() -> str:
    """FILE_GEN 的简版系统提示（每次调用实时取时间）。"""
    now = datetime.now()
    return (
        "你是Koto文档生成器，输出清晰的结构化内容，不要输出代码。\n"
        f"当前系统日期: {now.strftime('%Y-%m-%d')}（{now.strftime('%Y年%m月%d日')}）。\n"
        "时间规则：若用户仅写月份未写年份（如‘1月新番’），默认按当前年份解释。"
    )






# ===== 任务特定系统提示词 =====
TASK_PROMPTS = {
    "CHAT": """助手模式：普通对话
- 直接回答问题，提供有用信息
- 保持对话自然流畅
- 记住之前的上下文""",
    "CODER": """代码生成专家
- 生成高质量、可运行的代码
- 遵循Python/JavaScript最佳实践
- 添加必要注释，解释复杂逻辑
- 包含错误处理和边界检查
- 代码长度控制在80行以内""",
    "FILE_GEN": """文档生成专家
- 生成结构清晰、格式规范的文档
- 使用标题、列表、段落进行组织
- 适配Word/PDF/Excel导出
- 内容准确、专业、可执行
- 禁止输出代码块和技术细节""",
    "PAINTER": """图像生成艺术家
- 创作独特、高质量的图像
- 理解用户的审美偏好
- 支持风格、颜色、构图的微调
- 输出高分辨率图像""",
    "RESEARCH": """深度研究专家
- 进行全面的信息搜索和分析
- 查找最新、最准确的信息
- 整理多个来源的观点
- 提供有根据的结论和见解
- 标注信息来源""",
    "SYSTEM": """系统操作执行器
- 执行本地系统命令和操作
- 打开应用、管理文件、控制系统
- 提供清晰的执行反馈
- 解释操作结果和错误""",
}

# ===== Windows本地快捷指令映射 =====
WINDOWS_SHORTCUTS = {
    # 文件和剪贴板操作
    "复制": "Ctrl+C",
    "粘贴": "Ctrl+V",
    "剪切": "Ctrl+X",
    "撤销": "Ctrl+Z",
    "重做": "Ctrl+Y",
    "全选": "Ctrl+A",
    "保存": "Ctrl+S",
    "打开": "Ctrl+O",
    "新建": "Ctrl+N",
    # 浏览器操作
    "新标签页": "Ctrl+T",
    "关闭标签页": "Ctrl+W",
    "历史记录": "Ctrl+H",
    "书签": "Ctrl+B",
    "刷新": "Ctrl+R",
    "放大": "Ctrl+加号",
    "缩小": "Ctrl+减号",
    # 系统操作
    "任务管理器": "Ctrl+Shift+Esc",
    "截图": "Win+Shift+S",
    "开始菜单": "Win",
    "锁屏": "Win+L",
    "关机": "Alt+F4",
    "虚拟桌面": "Win+Tab",
    "显示桌面": "Win+D",
    # 应用切换
    "切换应用": "Alt+Tab",
    "关闭应用": "Alt+F4",
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

# ─── 后台启动动态模型路由器 ────────────────────────────────────────────────────
# 不阻塞主线程启动；路由表更新后会自动覆盖静态默认值及 SmartDispatcher 配置
import threading as _threading

_threading.Thread(
    target=_init_model_manager, name="ModelManagerInit", daemon=True
).start()
_threading.Thread(
    target=_model_manager_refresh_loop, name="ModelManagerRefresh", daemon=True
).start()

# ================= Local dispatcher (migrated to web/local_dispatcher.py) =================
from web.local_dispatcher import LOCAL_ROUTER_MODEL, OLLAMA_API_URL, LocalDispatcher


# ================= Utilities (migrated to web/utils/assistant_utils.py) =================
from web.utils.assistant_utils import Utils


# ================= Session Manager (migrated to web/session_manager.py) =================
from web.session_manager import SessionManager

session_manager = SessionManager()

# ================= Memory runtime (migrated to web/memory_runtime.py) =================
from web.memory_runtime import (
    _inject_memory_adapters,
    _start_memory_extraction,
    get_knowledge_base,
    get_memory_manager,
)


# 为了向后兼容，导出全局变量
memory_manager = None  # 将通过 get_memory_manager() 动态获取
kb = None  # 将通过 get_knowledge_base() 动态获取

# ================= Koto Brain =================


class KotoBrain:
    # 图像编辑关键词
    IMAGE_EDIT_KEYWORDS = [
        "修改",
        "换",
        "改成",
        "变成",
        "底色",
        "背景",
        "颜色",
        "抠图",
        "去背景",
        "P图",
        "美化",
        "滤镜",
        "调色",
        "编辑",
        "change",
        "modify",
        "edit",
        "background",
        "color",
    ]

    def chat(
        self,
        history,
        user_input,
        file_data=None,
        model=None,
        auto_model=True,
        task_type: str = None,
    ):
        start_time = time.time()
        original_input = user_input
        # 支持模型选择和自动选择
        _model_id_locked = (
            False  # 如果已在路由中强制设置 model_id，跳过后续 SmartDispatcher 覆盖
        )
        if model and not auto_model:
            model_id = model
            route_method = "Manual select"
            # 优先使用调用方传入的 task_type，避免重复路由
            target_key = task_type or "CHAT"
        else:
            target_key = "CHAT"
            route_method = "Auto"
            model_id = None  # 先置空，下面按路由决定

            if file_data:
                _fd_mime = (
                    file_data.get("mime_type") or "application/octet-stream"
                ).lower()
                _is_image_file = _fd_mime.startswith("image/")
                if _is_image_file:
                    # 图片文件：判断编辑 vs 分析
                    user_lower = user_input.lower()
                    is_edit = any(kw in user_lower for kw in self.IMAGE_EDIT_KEYWORDS)
                    if is_edit:
                        target_key = "PAINTER"
                        route_method = "Image Edit"
                    else:
                        target_key = "VISION"
                        route_method = "Image Analysis"
                else:
                    # 非图片二进制文件（PDF/Word等）：路由为 CHAT，使用降级模型直接读取
                    target_key = "CHAT"
                    route_method = "📄 Binary-Doc-Read"
                    # 强制使用支持 generate_content + 文件字节的降级模型（Interactions API 不支持文件附件）
                    model_id = _INTERACTIONS_FALLBACK_MODEL
                    _model_id_locked = True
            else:
                # 使用智能路由器
                target_key, route_method, _ = SmartDispatcher.analyze(user_input)

            if not _model_id_locked:
                model_id = SmartDispatcher.get_model_for_task(
                    target_key, has_image=bool(file_data)
                )
                try:
                    from app.core.llm.model_selection import get_configured_cloud_model

                    model_id = get_configured_cloud_model(
                        task_type=target_key,
                        fallback_model=model_id,
                    ) or model_id
                except Exception as model_select_err:
                    _app_logger.debug(
                        "[ModelSelect] configured cloud model lookup skipped: %s",
                        model_select_err,
                    )

        # 使用小模型将请求转换为结构化 Markdown（仅在大模型处理时启用）
        # ⚠️ 跳过条件：有文件附件时（file_data）、或输入很大（含嵌入文件内容）
        _has_embedded_file_content = (
            "=== 文件内容 ===" in user_input or len(user_input) > 3000
        )
        model_input = user_input
        if (
            auto_model
            and not file_data
            and not _has_embedded_file_content
            and target_key not in ["SYSTEM", "FILE_OP", "PAINTER", "VISION"]
        ):
            # 仅使用本地模板重整（不传 model_generate，避免额外的 flash-lite API 调用）
            model_input = Utils.adapt_prompt_to_markdown(
                target_key, user_input, history=history
            )
            if model_input != user_input:
                _app_logger.debug("[PROMPT_ADAPTER] Applied local Markdown template")
        result = {
            "task": target_key,
            "model": model_id,
            "route_method": route_method,  # 路由方法信息
            "response": "",
            "images": [],
            "saved_files": [],
            "latency": 0,
            "total_time": 0,
        }

        try:
            # === SYSTEM Mode (本地执行) ===
            if target_key == "SYSTEM":
                exec_result = LocalExecutor.execute(user_input)
                result["response"] = exec_result["message"]
                if exec_result.get("details"):
                    result["response"] += f"\n\n{exec_result['details']}"
                result["total_time"] = time.time() - start_time
                return result

            # === PAINTER Mode (图像生成/编辑) ===
            if target_key == "PAINTER":
                # 如果有输入图片（图像编辑模式）- 使用代码方式处理
                if file_data:
                    # 保存上传的图片到 workspace
                    import subprocess
                    import tempfile

                    temp_img_path = os.path.join(
                        WORKSPACE_DIR, "images", f"input_{int(time.time())}.jpg"
                    )
                    os.makedirs(os.path.dirname(temp_img_path), exist_ok=True)
                    with open(temp_img_path, "wb") as f:
                        f.write(file_data["data"])

                    # 构建图像编辑的系统指令
                    edit_instruction = f"""你是一个图像处理专家。用户上传了一张图片，需要你生成 Python 代码来处理它。

图片路径: {temp_img_path}
用户请求: {user_input}

请生成完整的 Python 代码来完成用户的图像编辑请求。

要求:
1. 使用 OpenCV (cv2) 或 PIL 处理图片
2. 处理后的图片保存到: {settings_manager.images_dir}
3. 文件名格式: edited_{{timestamp}}.jpg 或 .png
4. 代码必须完整可执行
5. 对于换背景色，使用颜色阈值或边缘检测来识别背景区域

常用的背景色处理方法:
- 证件照换底色: 检测接近原背景色的像素，替换为目标颜色
- 蓝色背景 RGB: (67, 142, 219) 或 (0, 191, 255)
- 红色背景 RGB: (255, 0, 0) 或 (220, 0, 0)
- 白色背景 RGB: (255, 255, 255)

代码格式（必须使用这个格式）:
---BEGIN_FILE: image_edit.py---
# 你的代码
---END_FILE---"""

                    # 调用 Gemini 生成代码（带回退）
                    edit_models = [
                        "deepseek-chat",
                        "deepseek-chat",
                        "deepseek-chat",
                    ]
                    code_response = None
                    last_error = None

                    def _process_code_response(code_response_text: str):
                        # 提取代码 - 支持多种格式
                        import re

                        patterns = [
                            r"---BEGIN_FILE:\s*([a-zA-Z0-9_.-]+)\s*---\s*(.*?)---\s*END_FILE\s*---",
                            r"```python\s*(.*?)```",  # 标准 markdown 代码块
                            r"```\s*(.*?)```",  # 无语言标记的代码块
                        ]

                        code_content = None
                        for pattern in patterns:
                            matches = re.findall(
                                pattern, code_response_text, re.DOTALL | re.IGNORECASE
                            )
                            if matches:
                                if isinstance(matches[0], tuple):
                                    code_content = matches[0][1].strip()
                                else:
                                    code_content = matches[0].strip()
                                _app_logger.debug(
                                    f"[IMAGE_EDIT] Extracted code, length: {len(code_content)}"
                                )
                                break

                        if not code_content:
                            return {
                                "images": [],
                                "response": f"❌ 无法从模型响应中提取代码\n\n模型返回内容:\n```\n{code_response_text[:500]}\n```",
                                "error": "no_code",
                            }

                        # 保存并执行代码
                        temp_script = os.path.join(
                            tempfile.gettempdir(), f"koto_edit_{int(time.time())}.py"
                        )
                        with open(temp_script, "w", encoding="utf-8") as f:
                            f.write(code_content)

                        _app_logger.debug(
                            f"[IMAGE_EDIT] Executing script: {temp_script}"
                        )
                        if getattr(sys, "frozen", False):
                            # 打包模式：sys.executable 是 Koto.exe，不能用来运行脚本，改为进程内 exec()
                            import contextlib as _ctx
                            import io as _io

                            _out, _err, _rc = _io.StringIO(), _io.StringIO(), 0
                            try:
                                _prev = os.getcwd()
                                os.chdir(WORKSPACE_DIR)
                                with _ctx.redirect_stdout(_out), _ctx.redirect_stderr(
                                    _err
                                ):
                                    exec(
                                        open(temp_script, "r", encoding="utf-8").read(),
                                        {"__file__": temp_script},
                                    )
                                os.chdir(_prev)
                            except Exception as _ex:
                                _err.write(str(_ex))
                                _rc = 1

                            class _ImgR:
                                returncode = _rc
                                stdout = _out.getvalue()
                                stderr = _err.getvalue()

                            exec_result = _ImgR()
                        else:
                            exec_result = subprocess.run(
                                [sys.executable, temp_script],
                                capture_output=True,
                                text=True,
                                timeout=60,
                                cwd=WORKSPACE_DIR,
                            )

                        _app_logger.debug(
                            f"[IMAGE_EDIT] Script result: returncode={exec_result.returncode}"
                        )
                        if exec_result.stdout:
                            _app_logger.debug(
                                f"[IMAGE_EDIT] stdout: {exec_result.stdout[:200]}"
                            )
                        if exec_result.stderr:
                            _app_logger.debug(
                                f"[IMAGE_EDIT] stderr: {exec_result.stderr[:200]}"
                            )

                        # 清理临时脚本
                        try:
                            os.remove(temp_script)
                        except OSError:
                            pass

                        if exec_result.returncode == 0:
                            images = []
                            images_dir = settings_manager.images_dir
                            for f in os.listdir(images_dir):
                                if f.startswith("edited_") and f.endswith(
                                    (".jpg", ".png", ".jpeg")
                                ):
                                    full_path = os.path.join(images_dir, f)
                                    age = time.time() - os.path.getmtime(full_path)
                                    if age < 60:
                                        rel_path = os.path.relpath(
                                            full_path, WORKSPACE_DIR
                                        ).replace("\\", "/")
                                        images.append(rel_path)

                            if images:
                                return {
                                    "images": images,
                                    "response": f"✅ 图片编辑完成!\n🖼️ 保存位置: `{images_dir}`",
                                    "error": "",
                                }
                            return {
                                "images": [],
                                "response": f"⚠️ 脚本执行成功但未检测到新图片\n\n{exec_result.stdout[:500]}",
                                "error": "no_output",
                            }

                        return {
                            "images": [],
                            "response": f"❌ 图片处理失败\n```\n{exec_result.stderr[:500]}\n```",
                            "error": "exec_failed",
                        }

                    for edit_model in edit_models:
                        try:
                            _app_logger.debug(
                                f"[IMAGE_EDIT] Trying model: {edit_model}"
                            )
                            _app_logger.debug(f"[IMAGE_EDIT] Sending request to API...")
                            response = client.models.generate_content(
                                model=edit_model,
                                contents=edit_instruction,
                                config=types.GenerateContentConfig(
                                    max_output_tokens=4096, temperature=0.5
                                ),
                            )
                            _app_logger.debug(f"[IMAGE_EDIT] Got API response")

                            if (
                                response.candidates
                                and response.candidates[0].content.parts
                            ):
                                code_response = (
                                    response.candidates[0].content.parts[0].text
                                )
                                _app_logger.debug(
                                    f"[IMAGE_EDIT] Got response from {edit_model}, length: {len(code_response)}"
                                )
                                break
                        except Exception as model_err:
                            last_error = str(model_err)
                            _app_logger.debug(
                                f"[IMAGE_EDIT] Model {edit_model} failed: {last_error[:100]}"
                            )
                            continue

                    if code_response:
                        run_result = _process_code_response(code_response)
                        result["images"] = run_result["images"]
                        result["response"] = run_result["response"]
                    else:
                        result["response"] = (
                            f"❌ 所有模型都不可用: {last_error[:200] if last_error else '未知错误'}"
                        )

                    # 失败后自动修正并重试一次（避免无编辑结果）
                    if not result["images"] and Utils.is_failure_output(
                        result["response"]
                    ):
                        fix_prompt = (
                            "上次生成失败，请修正并只输出完整可执行的 Python 代码。\n"
                            "必须使用 BEGIN_FILE/END_FILE 格式。\n"
                            f"图片路径: {temp_img_path}\n"
                            f"输出目录: {settings_manager.images_dir}\n"
                            f"用户请求: {user_input}\n\n"
                            f"失败信息/输出: {result['response']}\n"
                        )
                    retry_models = ["deepseek-chat", "deepseek-chat"]
                    for retry_model in retry_models:
                            try:
                                _app_logger.debug(
                                    f"[IMAGE_EDIT] Retry with model: {retry_model}"
                                )
                                retry_resp = client.models.generate_content(
                                    model=retry_model,
                                    contents=fix_prompt,
                                    config=types.GenerateContentConfig(
                                        max_output_tokens=4096
                                    ),
                                )
                                if (
                                    retry_resp.candidates
                                    and retry_resp.candidates[0].content.parts
                                ):
                                    retry_code = (
                                        retry_resp.candidates[0].content.parts[0].text
                                    )
                                    retry_run = _process_code_response(retry_code)
                                    if retry_run["images"]:
                                        result["images"] = retry_run["images"]
                                        result["response"] = retry_run["response"]
                                        break
                                    result["response"] = retry_run["response"]
                            except Exception as retry_err:
                                _app_logger.debug(
                                    f"[IMAGE_EDIT] Retry failed: {retry_err}"
                                )

                    result["total_time"] = time.time() - start_time
                    return result
                else:
                    # 纯图像生成使用 gemini-3.1-flash-image-preview
                    try:
                        _app_logger.info(f"[图像生成] 开始生成: {user_input[:50]}...")
                        response = client.models.generate_content(
                            model="gemini-3.1-flash-image-preview",
                            contents=user_input,
                            config=types.GenerateContentConfig(
                                response_modalities=["TEXT", "IMAGE"]
                            ),
                        )
                        _app_logger.info(
                            f"[图像生成] 响应成功，候选数: {len(response.candidates) if response.candidates else 0}"
                        )

                        # 保存生成的图片
                        if response.candidates and response.candidates[0].content.parts:
                            for part in response.candidates[0].content.parts:
                                if hasattr(part, "inline_data") and part.inline_data:
                                    img_filename = Utils.save_image_part(part)
                                    if img_filename:
                                        result["images"].append(img_filename)
                                        _app_logger.info(
                                            f"[图像生成] 已保存: {img_filename}"
                                        )

                        if result["images"]:
                            save_path = settings_manager.images_dir
                            result["response"] = (
                                f"✨ 图片已生成!\n🖼️ 保存位置: `{save_path}`"
                            )
                        else:
                            result["response"] = (
                                "❌ 图像生成失败: 无输出内容，请检查提示词"
                            )
                        result["total_time"] = time.time() - start_time
                        return result
                    except Exception as img_err:
                        error_msg = str(img_err)
                        _app_logger.info(f"[图像生成] 错误: {error_msg[:200]}")

                        # 提供更详细的错误信息
                        if (
                            "disconnected" in error_msg.lower()
                            or "timeout" in error_msg.lower()
                        ):
                            result["response"] = (
                                f"❌ 连接超时或中断: {error_msg[:100]}\n\n💡 建议: 请稍后重试，或检查网络连接"
                            )
                        elif "safety" in error_msg.lower():
                            result["response"] = "❌ 内容因安全政策被过滤，请修改提示词"
                        elif (
                            "quota" in error_msg.lower() or "rate" in error_msg.lower()
                        ):
                            result["response"] = "❌ API 配额已达限制，请稍后重试"
                        else:
                            result["response"] = f"❌ 图像生成失败: {error_msg[:100]}"

                        result["total_time"] = time.time() - start_time
                        return result

                if not response.candidates:
                    result["response"] = "Generation failed (safety filter or busy)."
                    result["total_time"] = time.time() - start_time
                    return result

                text_response = ""
                if response.candidates and response.candidates[0].content.parts:
                    for part in response.candidates[0].content.parts:
                        if hasattr(part, "text") and part.text:
                            text_response += part.text
                        if hasattr(part, "inline_data") and part.inline_data:
                            img_filename = Utils.save_image_part(part)
                            if img_filename:
                                result["images"].append(img_filename)

                # 添加图片保存位置提示
                if result["images"]:
                    save_path = settings_manager.images_dir
                    text_response += f"\n\n🖼️ 图片已保存到: `{save_path}`"

                result["response"] = (
                    text_response if text_response else "Image generated successfully!"
                )
                result["total_time"] = time.time() - start_time
                return result

            # === RAG: Retrieve Relevant Context (Auto) ===
            try:
                # 获取知识库实例
                kb_inst = get_knowledge_base()

                # 仅在非特定模式且输入有效时检索
                if target_key not in ["PAINTER", "SYSTEM"] and len(original_input) > 3:
                    # 避免对极短的问候语进行检索
                    skip_keywords = ["你好", "hello", "hi", "test", "测试"]
                    if not any(original_input.lower() == k for k in skip_keywords):
                        _app_logger.debug(
                            f"[RAG]正在检索知识库: {original_input[:50]}..."
                        )
                        rag_results = kb_inst.search(original_input, top_k=3)

                        if rag_results:
                            _app_logger.debug(
                                f"[RAG] 检索到 {len(rag_results)} 个相关片段"
                            )
                            context_str = "\n".join(
                                [
                                    f"--- 来源: {r['file_name']} (相似度: {r['similarity']:.2f}) ---\n{r['text']}"
                                    for r in rag_results
                                ]
                            )

                            # 将上下文注入 prompt
                            rag_context = f"\n\n【参考资料】\n以下是从本地知识库检索到的相关内容，供回答参考：\n{context_str}\n\n"

                            # Log retrieval
                            _app_logger.debug(
                                f"[RAG] Injected context length: {len(rag_context)}"
                            )

                            # Update model input
                            # 如果有 file_data，model_input 可能是 None 或不被直接使用，需谨慎
                            if not file_data:
                                model_input = rag_context + model_input
                            else:
                                # 对于有文件的请求，我们将上下文拼接到 original_input (user prompt)
                                # 注意：下面 generate_content 用的是 original_input + image_part
                                original_input = rag_context + original_input

            except Exception as rag_err:
                _app_logger.debug(f"[RAG] Retrieval warning: {rag_err}")

            # === Regular Mode ===
            # 构建历史记录格式（过滤无关历史）
            history_for_model = ContextAnalyzer.filter_history(original_input, history)
            formatted_history = []
            for turn in history_for_model:
                formatted_history.append(
                    types.Content(
                        role=turn["role"],
                        parts=[types.Part.from_text(text=p) for p in turn["parts"]],
                    )
                )

            # 根据任务类型选择系统提示：FILE_GEN 走文档生成提示，其余走通用助手提示
            if target_key == "FILE_GEN":
                _brain_sys_instruction = _get_system_instruction()
            else:
                _brain_sys_instruction = _get_chat_system_instruction(original_input)

            try:
                from app.core.llm.model_selection import is_deepseek_model
            except Exception:
                def is_deepseek_model(_model_id):
                    return False

            if file_data and is_deepseek_model(model_id):
                _doc_model = _INTERACTIONS_FALLBACK_MODEL
                _app_logger.info(
                    "[brain.chat] DeepSeek selected with binary file; using Gemini file-capable fallback %s",
                    _doc_model,
                )
                model_id = _doc_model
                result["model"] = model_id

            if file_data:
                # 构建 Part 格式（适用于图片和 PDF/文档）
                doc_part = types.Part.from_bytes(
                    data=file_data["data"], mime_type=file_data["mime_type"]
                )
                _fd_mime2 = (file_data.get("mime_type") or "").lower()
                _is_image = _fd_mime2.startswith("image/")

                if not _is_image:
                    # PDF / 文档二进制：Interactions API 不支持文件附件
                    # → 直接使用 gemini-2.5-flash（原生支持 generate_content + PDF bytes）
                    _doc_model = _INTERACTIONS_FALLBACK_MODEL
                    if model_id != _doc_model:
                        _app_logger.info(
                            f"[brain.chat] 非图片文件 ({_fd_mime2}): 降级模型 {model_id} → {_doc_model}"
                        )
                        model_id = _doc_model
                        result["model"] = model_id
                    response = client.models.generate_content(
                        model=model_id,
                        contents=[original_input, doc_part],
                        config=types.GenerateContentConfig(
                            system_instruction=_brain_sys_instruction
                        ),
                    )
                    accumulated_text = response.text if response.text else ""
                elif _is_interactions_only(model_id):
                    # 图片文件 + gemini-3-preview 模型：走 Interactions API
                    try:
                        accumulated_text = _call_interactions_api_sync(
                            model_id,
                            original_input,
                            sys_instruction=_brain_sys_instruction,
                        )
                        if not accumulated_text:
                            raise ValueError("Interactions API 返回空响应")
                    except Exception as _ia_err:
                        _app_logger.info(
                            f"[brain.chat] {model_id} Interactions API 失败: {_ia_err} → 降级到 {_INTERACTIONS_FALLBACK_MODEL}"
                        )
                        model_id = _INTERACTIONS_FALLBACK_MODEL
                        result["model"] = model_id
                        _fb_resp = client.models.generate_content(
                            model=model_id,
                            contents=[original_input, doc_part],
                            config=types.GenerateContentConfig(
                                system_instruction=_brain_sys_instruction
                            ),
                        )
                        accumulated_text = _fb_resp.text if _fb_resp.text else ""
                else:
                    # 图片文件 + 普通 generate_content 模型
                    response = client.models.generate_content(
                        model=model_id,
                        contents=[original_input, doc_part],
                        config=types.GenerateContentConfig(
                            system_instruction=_brain_sys_instruction
                        ),
                    )
                    accumulated_text = response.text if response.text else ""
            else:
                if is_deepseek_model(model_id):
                    from app.core.llm.provider_factory import get_llm_provider

                    provider = get_llm_provider(
                        provider="deepseek",
                        model=model_id,
                        allow_local_fallback=False,
                    )
                    messages = []
                    for turn in history_for_model[-6:]:
                        role = "assistant" if turn.get("role") == "model" else turn.get("role", "user")
                        content = "\n".join(str(p) for p in turn.get("parts", []) if str(p or "").strip())
                        if content:
                            messages.append({"role": role, "content": content})
                    messages.append({"role": "user", "content": model_input})
                    response = provider.generate_content(
                        prompt=messages,
                        model=model_id,
                        system_instruction=_brain_sys_instruction,
                        stream=False,
                    )
                    accumulated_text = response.get("content", "") if isinstance(response, dict) else str(response)
                else:
                    # gemini-3-preview 只支持 Interactions API，不支持 generate_content
                    if _is_interactions_only(model_id):
                        try:
                            # 将历史记录折叠进 prompt（Interactions API 不支持多轮历史）
                            history_prefix = ""
                            if formatted_history:
                                history_lines = []
                                for turn in formatted_history[-6:]:  # 最近 3 轮
                                    role_label = "用户" if turn.role == "user" else "助手"
                                    turn_text = " ".join(
                                        p.text
                                        for p in turn.parts
                                        if hasattr(p, "text") and p.text
                                    )
                                    if turn_text:
                                        history_lines.append(f"{role_label}: {turn_text}")
                                if history_lines:
                                    history_prefix = (
                                        "[对话历史]\n" + "\n".join(history_lines) + "\n\n"
                                    )
                            full_prompt = history_prefix + model_input
                            accumulated_text = _call_interactions_api_sync(
                                model_id,
                                full_prompt,
                                sys_instruction=_brain_sys_instruction,
                            )
                            if not accumulated_text:
                                raise ValueError("Interactions API 返回空响应")
                        except Exception as _ia_err:
                            _app_logger.info(
                                f"[brain.chat] {model_id} Interactions API 失败: {_ia_err} → 降级到 {_INTERACTIONS_FALLBACK_MODEL}"
                            )
                            model_id = _INTERACTIONS_FALLBACK_MODEL
                            result["model"] = model_id
                            _fb_resp = client.models.generate_content(
                                model=model_id,
                                contents=formatted_history
                                + [
                                    types.Content(
                                        role="user",
                                        parts=[types.Part.from_text(text=model_input)],
                                    )
                                ],
                                config=types.GenerateContentConfig(
                                    system_instruction=_brain_sys_instruction
                                ),
                            )
                            accumulated_text = _fb_resp.text if _fb_resp.text else ""
                    else:
                        response = client.models.generate_content(
                            model=model_id,
                            contents=formatted_history
                            + [
                                types.Content(
                                    role="user",
                                    parts=[types.Part.from_text(text=model_input)],
                                )
                            ],
                            config=types.GenerateContentConfig(
                                system_instruction=_brain_sys_instruction
                            ),
                        )
                        accumulated_text = response.text if response.text else ""

            first_token_latency = (time.time() - start_time) * 1000
            result["latency"] = first_token_latency

            # Auto-save files
            if settings_manager.get("ai", "auto_save_files") is not False:
                saved_files = Utils.auto_save_files(accumulated_text)
            else:
                saved_files = []
            result["saved_files"] = saved_files

            # 添加文件保存提示
            if saved_files:
                files_list = ", ".join(saved_files)
                accumulated_text += (
                    f"\n\n📁 文件已保存: **{files_list}**\n📂 位置: `{WORKSPACE_DIR}`"
                )

            result["response"] = accumulated_text
            result["total_time"] = time.time() - start_time
            return result

        except Exception as e:
            err_str = str(e)
            # 自动降级：如果模型返回"只支持 Interactions API"错误，用 2.0-flash 重试一次
            if (
                "Interactions API" in err_str
                and not _is_interactions_only(model_id)
                and model_id != _INTERACTIONS_FALLBACK_MODEL
            ):
                _app_logger.info(
                    f"[brain.chat] Interactions API 错误，自动降级 {model_id} → {_INTERACTIONS_FALLBACK_MODEL}"
                )
                try:
                    model_id = _INTERACTIONS_FALLBACK_MODEL
                    _fb = client.models.generate_content(
                        model=model_id,
                        contents=(
                            formatted_history
                            + [
                                types.Content(
                                    role="user",
                                    parts=[types.Part.from_text(text=model_input)],
                                )
                            ]
                        ),
                        config=types.GenerateContentConfig(
                            system_instruction=_brain_sys_instruction
                        ),
                    )
                    result["response"] = _fb.text if _fb.text else ""
                    result["model"] = model_id
                    result["total_time"] = time.time() - start_time
                    return result
                except Exception as _fb_err:
                    result["response"] = f"❌ 分析失败: {_fb_err}"
            elif (
                "API key not valid" in err_str
                or "INVALID_ARGUMENT" in err_str
                and "api key" in err_str.lower()
            ):
                result["response"] = (
                    "❌ **API 密钥无效**\n\n"
                    "请检查您的 云端 API 密钥：\n"
                    "1. 前往 [aistudio.google.com/apikey](https://aistudio.google.com/apikey) 获取有效密钥\n"
                    "2. 在 Koto 设置页面更新 API 密钥\n"
                    "3. 确保密钥所在项目已启用 Generative Language API\n\n"
                    f"原始错误: `{err_str[:200]}`"
                )
            else:
                # ── 模型本身不可用（404 / not-found / Interactions-only 等）──────────
                # 尝试从 ModelFallbackExecutor 获取备选模型并静默重试一次。
                _retried = False
                try:
                    from app.core.llm.model_fallback import (
                        _is_model_unavailable_error as _mue_chk,
                    )
                    from app.core.llm.model_fallback import (
                        get_fallback_executor,
                    )

                    if _mue_chk(e) and model_id not in (
                        None,
                        _INTERACTIONS_FALLBACK_MODEL,
                    ):
                        _fbe = get_fallback_executor()
                        _fbe.mark_unavailable(model_id)
                        _fb_model = _fbe.get_best_available(task_type=target_key)
                        if (
                            _fb_model
                            and _fb_model != model_id
                            and not _is_interactions_only(_fb_model)
                        ):
                            _app_logger.info(
                                f"[brain.chat] 模型不可用 {model_id} → 自动降级 {_fb_model} (task={target_key})"
                            )
                            _fh = locals().get("formatted_history") or []
                            _mi = locals().get("model_input") or original_input
                            _si = locals().get("_brain_sys_instruction") or ""
                            _fb_r = client.models.generate_content(
                                model=_fb_model,
                                contents=_fh
                                + [
                                    types.Content(
                                        role="user",
                                        parts=[types.Part.from_text(text=_mi)],
                                    )
                                ],
                                config=types.GenerateContentConfig(
                                    system_instruction=_si
                                ),
                            )
                            result["response"] = _fb_r.text if _fb_r.text else ""
                            result["model"] = _fb_model
                            _retried = True
                except Exception as _r_err:
                    _app_logger.info(f"[brain.chat] 降级重试失败: {_r_err}")
                if not _retried:
                    result["response"] = f"❌ 发生错误: {err_str}"
            result["total_time"] = time.time() - start_time
            return result


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
    # ── Orchestrator: pre-checks + context setup ──────────────────────────
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

    # ── AGENT handler — delegated ──────────────────────────────────────────
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
            """推断分析来源：local / cloud / hybrid / system"""
            msg = (message or "").lower()
            phase_l = (phase or "").lower()

            if any(k in msg for k in ["ollama", "本地模型", "qwen", "local"]):
                return "local"
            if any(k in msg for k in ["gemini", "deep-research", "云端", "cloud"]):
                return "cloud"
            if any(
                k in phase_l for k in ["routing", "context", "planning", "analyzing"]
            ):
                return "hybrid"
            return "system"

        def yield_thinking(message: str, phase: str = "thinking", source: str = None):
            """发送思考过程事件（仅当用户开启 show_thinking 时），附带分析来源"""
            if not _show_thinking:
                return ""

            resolved_source = source or _infer_analysis_source(message, phase)
            source_tag = {
                "local": "[本地分析]",
                "cloud": "[大模型分析]",
                "hybrid": "[混合决策]",
                "system": "[系统流程]",
            }.get(resolved_source, "[系统流程]")

            elapsed = round(time.time() - start_time, 1)
            display_message = f"{source_tag} {message}"
            return f"data: {json.dumps({'type': 'thinking', 'message': display_message, 'phase': phase, 'elapsed': elapsed, 'analysis_source': resolved_source}, ensure_ascii=False)}\n\n"

        # === 立即反馈任务分类信息 ===
        task_display_names = {
            "PAINTER": "🎨 图像生成",
            "FILE_GEN": "📄 文档生成",
            "CODER": "💻 代码编程",
            "RESEARCH": "📚 深度研究",
            "WEB_SEARCH": "🌐 实时搜索",
            "CHAT": "💬 对话",
            "SYSTEM": "🖥️ 系统操作",
            "FILE_OP": "📂 文件操作",
            "FILE_EDIT": "✏️ 文件编辑",
            "FILE_SEARCH": "🔍 文件搜索",
            "VISION": "👁️ 图像识别",
            "MULTI_STEP": "🔄 多步任务",
            "AGENT": "🤖 智能助手",
        }

        model_display = get_model_display_name(model_id)
        task_display = task_display_names.get(task_type, task_type)

        # 发送任务分类信息（在最开始，立即显示）
        classification_msg = f"🎯 任务分类: {task_display}"
        if route_method:
            classification_msg += f" (方法: {route_method})"

        routing_list = None
        # 仅保留 routing_list 用于内部调试，不显示给用户
        if context_info and context_info.get("routing_list"):
            routing_list = context_info.get("routing_list")

        yield f"data: {json.dumps({'type': 'classification', 'task_type': task_type, 'task_display': task_display, 'model': model_id, 'model_display': model_display, 'route_method': route_method, 'routing_list': routing_list, 'message': classification_msg})}\n\n"

        # 思考过程：任务路由分析
        t = yield_thinking(f"分析用户意图 → 识别为 {task_display}", "routing", "hybrid")
        if t:
            yield t
        model_source = (
            "local"
            if any(k in (model_id or "").lower() for k in ["qwen", "llama", "ollama"])
            else "cloud"
        )
        t = yield_thinking(
            f"路由方法: {route_method}，选择模型: {model_display}",
            "model",
            model_source,
        )
        if t:
            yield t
        if routing_list:
            steps_str = (
                " → ".join(
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
            t = yield_thinking(f"路由决策链: {steps_str}", "routing", "hybrid")
            if t:
                yield t

        # 如果有复杂度信息，也发送
        if context_info and context_info.get("complexity"):
            complexity_msg = f"📊 任务复杂度: {context_info['complexity']}"
            yield f"data: {json.dumps({'type': 'info', 'message': complexity_msg})}\n\n"
            t = yield_thinking(
                f"任务复杂度评估: {context_info['complexity']}", "analyzing", "hybrid"
            )
            if t:
                yield t

        # 如果有上下文，使用增强后的输入
        # _llm_user_input 携带当前时间戳前缀，防止历史记录干扰时间判断
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
            yield f"data: {json.dumps({'type': 'info', 'message': '🔗 检测到延续任务，使用上下文增强'})}\n\n"
            t = yield_thinking(
                f"检测到上下文延续，增强输入 ({len(effective_input)} 字符)",
                "context",
                "hybrid",
            )
            if t:
                yield t

        # 使用快速小模型将请求转为结构化 Markdown（仅对大模型任务启用）
        if task_type not in ["SYSTEM", "FILE_OP", "PAINTER", "VISION"]:
            adapted_input = Utils.adapt_prompt_to_markdown(
                task_type, effective_input, history=history
            )
            if adapted_input != effective_input:
                effective_input = adapted_input
                yield f"data: {json.dumps({'type': 'info', 'message': '🧾 已将请求结构化为Markdown提示'})}\n\n"
                t = yield_thinking(
                    "将用户请求结构化为 Markdown 格式以提升输出质量",
                    "planning",
                    "hybrid",
                )
                if t:
                    yield t

        # 重置中断标志（每次新请求都重置）
        _interrupt_manager.reset(session_name)
        interrupt_event = _interrupt_manager.get_event(session_name)

        def interrupted():
            return _interrupt_manager.is_interrupted(session_name)

        # 发送进度: 开始处理
        from web.smart_feedback import SmartFeedback

        _task_labels = SmartFeedback.TASK_LABELS
        _tl = _task_labels.get(task_type, task_type)
        yield f"data: {json.dumps({'type': 'progress', 'message': f'开始处理{_tl}任务', 'detail': get_model_display_name(model_id)})}\n\n"

        try:
            # 初始化模型追踪变量（用于日志记录）
            used_model = "unknown"

            # SYSTEM handler — delegated
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

            # === FILE TASKS — workspace task-stream only ===
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
                    "文件任务已统一到工作区任务流执行。请从工作区文件任务入口启动，"
                    "旧聊天流不再执行文件任务，以避免产生不完整的完成状态。"
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

            # === WEB_SEARCH handler — delegated ===
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

            # === 🌳 Tree of Thought — RESEARCH/CHAT only ===
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

            # === Regular Mode (流式输出) ===
            # Regular mode handler — delegated
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

            # 云端不可用 → 尝试本地模型兜底（覆盖地区限制/Key无效/503/配额超限等所有在线失败场景）
            if _iof2(e) and task_type in _OLLAMA_TEXT_TASKS2 and _ioav2():
                _app_logger.warning(f"[CHAT] outer: cloud failure ({error_str[:60]}), trying Ollama")
                yield f"data: {json.dumps({'type': 'progress', 'message': '⚠️ 云端 AI 不可用，已切换到本地模型 (Ollama)...', 'detail': ''}, ensure_ascii=False)}\n\n"
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
                    # Ollama也失败了，显示原始错误
                    error_response = f"❌ 云端 AI 不可用，本地模型也响应失败。\n\n原始错误: {error_str[:150]}"
                    session_manager.append_and_save(
                        f"{session_name}.json", user_input, error_response,
                        task=task_type, model_name=model_id,
                    )
                    yield f"data: {json.dumps({'type': 'token', 'content': error_response})}\n\n"
                    total_time = time.time() - start_time
                    yield f"data: {json.dumps({'type': 'done', 'images': [], 'saved_files': [], 'total_time': total_time})}\n\n"
                    return

            # 地区限制错误（Ollama不可用时的降级提示）
            if (
                "location is not supported" in error_str.lower()
                or "failed_precondition" in error_str.lower()
            ):
                error_response = "❌ 地区限制\n\n您所在的地区不支持 Gemini API。\n\n💡 解决方案:\n1. 在 `config/gemini_config.env` 配置中转服务 `GEMINI_API_BASE`\n2. 或使用支持的代理服务\n3. 或启动本地 Ollama 模型作为备用"
            elif "API key not valid" in error_str or (
                "INVALID_ARGUMENT" in error_str and "api key" in error_str.lower()
            ):
                error_response = (
                    "❌ **API 密钥无效**\n\n"
                    "请检查您的 云端 API 密钥：\n"
                    "1. 前往 [aistudio.google.com/apikey](https://aistudio.google.com/apikey) 获取有效密钥\n"
                    "2. 在 Koto 设置页面更新 API 密钥（设置 → API 配置）\n"
                    "3. 确保密钥所在 Google 项目已启用 Generative Language API\n\n"
                    f"原始错误: `{error_str[:150]}`"
                )
            elif (
                "server disconnected" in error_str.lower()
                or "disconnected without" in error_str.lower()
                or "connection reset" in error_str.lower()
                or "connection aborted" in error_str.lower()
            ):
                # 将连接中断的模型标记为短期不可用（2 分钟），下次请求自动降级到 Flash
                try:
                    from app.core.llm.model_fallback import get_fallback_executor

                    get_fallback_executor().mark_unavailable(model_id, ttl=120)
                    _app_logger.warning(
                        f"[CHAT] 连接中断，已将 {model_id} 标记不可用 120s，下次自动降级"
                    )
                except Exception:
                    import logging; logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)
                error_response = (
                    "❌ **服务器连接中断**\n\n"
                    "与 Gemini API 的连接被意外断开，这通常是临时性问题。\n\n"
                    "💡 建议：\n"
                    "1. 稍等片刻后重新发送消息\n"
                    "2. 检查您的网络连接稳定性\n"
                    "3. 如果使用代理，请确认代理连接正常\n"
                    "4. 如问题持续，可尝试切换到其他模型"
                )
            elif (
                "resource_exhausted" in error_str.lower()
                or "quota" in error_str.lower()
                or "rate limit" in error_str.lower()
                or "429" in error_str
            ):
                error_response = (
                    "❌ **API 配额超限**\n\n"
                    "当前 API 密钥的请求频率或配额已达上限。\n\n"
                    "💡 建议：\n"
                    "1. 稍等 1-2 分钟后重试\n"
                    "2. 在设置中切换到其他 API 密钥\n"
                    "3. 或升级您的 Google AI Studio 计划"
                )
            elif (
                "unavailable" in error_str.lower()
                or "503" in error_str
                or "service unavailable" in error_str.lower()
            ):
                error_response = (
                    "❌ **Gemini 服务暂时不可用**\n\n"
                    "Gemini API 服务器当前无法响应，可能正在维护中。\n\n"
                    "💡 建议：稍等片刻后重试，或访问 [status.google.com](https://status.google.com) 查看服务状态"
                )
            elif (
                "deadline_exceeded" in error_str.lower()
                or "timed out" in error_str.lower()
            ):
                error_response = (
                    "❌ **请求超时**\n\n"
                    "模型响应时间过长，请求已超时。\n\n"
                    "💡 建议：\n"
                    "1. 尝试缩短您的问题或分步骤提问\n"
                    "2. 切换到响应更快的模型（如 gemini-2.5-flash）\n"
                    "3. 检查网络连接质量"
                )
            else:
                error_response = f"❌ 发生错误: {error_str[:200]}"

            # 即使出错也要保存用户的问题
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
        generate() 外层安全包装器：
        确保无论 generate() 内部以何种方式结束，前端都能收到 'done' 事件，
        避免因任务识别失败/早期异常导致对话界面永远挂起。
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
                f"[STREAM] ⚠️ _safe_generate caught exception: {_sg_err}"
            )
            import traceback

            traceback.print_exc()
            if not _sent_done:
                _err_msg = f"❌ 流式响应异常终止: {str(_sg_err)[:200]}"
                yield f"data: {json.dumps({'type': 'token', 'content': _err_msg})}\n\n"
        finally:
            if not _sent_done:
                _app_logger.warning(
                    f"[STREAM] ⚠️ generate() 未发送 done 事件，触发兜底 done (task_type={task_type})"
                )
                yield f"data: {json.dumps({'type': 'done', 'images': [], 'saved_files': [], 'total_time': 0, 'fallback_done': True})}\n\n"

    response = Response(
        stream_with_context(_safe_generate()), mimetype="text/event-stream"
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"  # 禁用 nginx 缓冲
    response.headers["Connection"] = "keep-alive"
    return response


def chat_with_file():
    """处理文件上传和聊天请求"""
    session_name = request.form.get("session")
    user_input = request.form.get("message", "")
    files = request.files.getlist("file")

    # 🔍 调试日志
    _app_logger.info(f"[FILE UPLOAD DEBUG] ========== 接收到文件上传请求 ==========")
    _app_logger.info(
        f"[FILE UPLOAD DEBUG] request.files keys: {list(request.files.keys())}"
    )
    _app_logger.info(
        f"[FILE UPLOAD DEBUG] request.files.getlist('file'): {len(files)} 个文件"
    )
    for i, f in enumerate(files):
        _app_logger.info(f"[FILE UPLOAD DEBUG]   {i+1}. {f.filename if f else 'None'}")

    if not files:
        single_file = request.files.get("file")
        if single_file:
            files = [single_file]
            _app_logger.info(
                f"[FILE UPLOAD DEBUG] 使用单文件模式，文件: {single_file.filename}"
            )

    locked_task = request.form.get("locked_task")
    locked_model = request.form.get("locked_model", "cloud")
    if str(locked_model or "").strip().lower() in {"", "auto"}:
        locked_model = "cloud"
    stream_mode = request.form.get("stream", "").lower() in ("1", "true", "yes")

    _app_logger.info(f"[FILE UPLOAD DEBUG] 最终 files 列表: {len(files)} 个文件")
    _app_logger.info(f"[FILE UPLOAD DEBUG] 判断: len(files) > 1 = {len(files) > 1}")

    if not session_name or not files:
        return jsonify({"error": "Missing session or file"}), 400
    if len(files) > 10:
        return jsonify({"error": "最多一次上传 10 个文件"}), 400

    if len(files) > 1:
        return handle_multi_file_chat_request(
            app_module=sys.modules[__name__],
            session_name=session_name,
            user_input=user_input,
            files=files,
            locked_task=locked_task,
            locked_model=locked_model,
            stream_mode=stream_mode,
        )
    return handle_single_file_chat_request(
        app_module=sys.modules[__name__],
        session_name=session_name,
        user_input=user_input,
        file=files[0],
        locked_task=locked_task,
        locked_model=locked_model,
    )


# ==================== 智能文档处理路由 ====================


from web.services.intent import should_use_annotation_system as _should_use_annotation_system
from web.services.intent import is_analysis_request as _is_analysis_request
from web.services.intent import is_explicit_file_gen_request as _is_explicit_file_gen_request

# 临时 file_id → 实际路径映射（进程内缓存，重启后失效属正常）
_compare_file_registry: dict = {}


# ================= 主程序入口 =================

# ================= NotebookLM 功能复刻 API =================


if __name__ == "__main__":
    import sys
    # Allow emoji/unicode in startup prints on Windows (cp1252 terminal)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    debug_mode = os.environ.get("KOTO_DEBUG", "false").lower() == "true"
    port = int(os.environ.get("KOTO_PORT", "5000"))

    print("\n🚀 Koto Web Server Starting...")
    print(f"📁 Chat Directory: {os.path.abspath(CHAT_DIR)}")
    print(f"📁 Workspace: {os.path.abspath(WORKSPACE_DIR)}")

    # 延迟检查 Ollama 状态（不阻塞启动）
    def check_ollama_async():
        time.sleep(2)  # 延迟2秒后检查
        if os.environ.get("KOTO_DEPLOY_MODE") == "cloud":
            print("☁️ Ollama: Disabled (cloud mode - using Gemini API)")
            return
        if LocalDispatcher.is_ollama_running():
            print("🦙 Ollama: Running")
        else:
            print("🦙 Ollama: Not Running")

    threading.Thread(target=check_ollama_async, daemon=True).start()

    print("⚠️ 本地模型任务路由器已禁用，使用远程 AI")

    print(f"\n🌐 Open http://localhost:{port} in your browser\n")

    # 启动后台服务（异步，不阻塞启动）
    def start_background_services():
        time.sleep(1)  # 延迟1秒后启动后台服务
        try:
            from auto_catalog_scheduler import get_auto_catalog_scheduler
            from clipboard_manager import get_clipboard_manager
            from task_scheduler import get_task_scheduler

            # 启动剪贴板监控
            clipboard_manager = get_clipboard_manager()
            clipboard_manager.start_monitoring()
            print("📋 剪贴板监控已启动")

            # 启动任务调度器
            task_scheduler = get_task_scheduler()
            task_scheduler.start()
            print("⏰ 任务调度器已启动")

            # 初始化自动归纳调度器（如果已启用）
            auto_catalog = get_auto_catalog_scheduler()
            if auto_catalog.is_auto_catalog_enabled():
                auto_catalog._register_scheduled_task()
                print(
                    f"🗂️ 自动归纳已启用，每日 {auto_catalog.get_catalog_schedule()} 执行"
                )

        except Exception as e:
            print(f"⚠️ 后台服务启动失败: {e}")

    threading.Thread(target=start_background_services, daemon=True).start()

    try:
        # Must use socketio.run() (not app.run()) so Flask-SocketIO controls the
        # server event loop and WebSocket connections can be established.
        if socketio is not None:
            socketio.run(app, debug=debug_mode, host="0.0.0.0", port=port,
                         allow_unsafe_werkzeug=True)
        else:
            app.run(debug=debug_mode, host="0.0.0.0", port=port, threaded=True)
    finally:
        # 应用关闭时清理并行执行系统
        if PARALLEL_SYSTEM_ENABLED:
            print("[PARALLEL] 🛑 Shutting down parallel execution system...")
            stop_dispatcher()
            print("[PARALLEL] ✅ Parallel execution system shut down")


# ═══ 文件组织系统 API ═══

from web.lazy_loaders import (
    _lazy_cache,
    _lazy_load,
    get_auto_execution,
    get_batch_ops_manager,
    get_behavior_monitor,
    get_concept_extractor,
    get_context_awareness,
    get_file_analyzer,
    get_file_editor,
    get_file_indexer,
    get_file_organizer,
    get_insight_reporter,
    get_knowledge_graph,
    get_notification_manager,
    get_proactive_dialogue,
    get_suggestion_engine,
    get_trigger_system,
)


# ═══════════════════════════════════════════════════
# 文件编辑与搜索 API
# ═══════════════════════════════════════════════════


# ═══════════════════════════════════════════════════
# 全盘文件扫描 API  (FileScanner)
# ═══════════════════════════════════════════════════


# ═══════════════════════════════════════════════════
# 概念提取 API
# ═══════════════════════════════════════════════════


# ═══════════════════════════════════════════════════
# 知识图谱 API
# ═══════════════════════════════════════════════════


# ═══════════════════════════════════════════════════
# 行为监控 API
# ═══════════════════════════════════════════════════


# ═══════════════════════════════════════════════════
# 智能建议 API
# ═══════════════════════════════════════════════════


# ═══════════════════════════════════════════════════
# 洞察报告 API
# ═══════════════════════════════════════════════════


# ==================== 通知管理 API ====================


# ==================== 主动对话 API ====================


# ==================== 情境感知 API ====================


# ==================== 自动执行 API ====================


# ==================== 主动交互触发系统 API ====================
