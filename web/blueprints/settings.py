# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Settings, setup, diagnose, info, local-model, and mode-switch routes.

Extracted from web/app.py into a standalone Flask Blueprint so that the
monolithic module becomes easier to maintain.
"""

import json
import logging
import os
import threading
import time
from math import isfinite

from flask import Blueprint, Response, current_app, jsonify, request

from web.blueprints.auth import require_auth
from web.shared import invalidate_settings_cache
from web.settings_runtime_services import (
    get_api_key,
    get_app_version,
    get_detected_proxy,
    get_force_proxy,
    get_model_runtime,
    get_project_root,
    get_settings_manager,
    get_workspace_dir,
    reset_client_cache,
    reset_proxy_detection,
    update_chat_dir,
    update_workspace_dir,
)

_logger = logging.getLogger("koto.app")

settings_bp = Blueprint("settings_routes", __name__)

_BOOLEAN_SETTING_KEYS = {
    ("ai", "auto_save_files"),
    ("ai", "show_thinking"),
    ("ai", "show_task_type"),
    ("ai", "enable_mini_game"),
    ("ai", "use_local_only"),
    ("proxy", "enabled"),
}


def _normalize_setting_value(category: str, key: str, value):
    """Reject malformed values for settings exposed by the current UI."""
    if (category, key) in _BOOLEAN_SETTING_KEYS:
        if not isinstance(value, bool):
            return None, "该设置必须是布尔值"
        return value, None
    if (category, key) == ("appearance", "theme"):
        if value not in {"light", "dark", "ocean", "forest", "sunset", "lavender", "midnight", "auto"}:
            return None, "不支持的主题"
        return value, None
    if (category, key) == ("appearance", "ui_zoom"):
        try:
            zoom = float(value)
        except (TypeError, ValueError):
            return None, "界面缩放必须是数字"
        if not isfinite(zoom) or not 0.7 <= zoom <= 1.5:
            return None, "界面缩放必须在 70% 到 150% 之间"
        return float(f"{zoom:.2f}"), None
    if category == "storage" and key in {"workspace_dir", "documents_dir", "images_dir", "chats_dir"}:
        if not isinstance(value, str):
            return None, "存储路径必须是文本"
    if (category, key) == ("ai", "cloud_provider") and value != "deepseek":
        return None, "当前版本仅支持 DeepSeek 云端供应商"
    return value, None

def _get_settings_manager():
    return get_settings_manager()


def _save_model_runtime(sm, *, mode: str, model_tag=None) -> tuple[bool, str]:
    """Persist the one shared model-mode/model-tag runtime contract."""
    canonical_mode = "local" if str(mode or "").strip().lower() in {"local", "ollama"} else "cloud"
    # model_mode is the canonical global inference mode. Keep the older
    # compatibility fields derived from it, but persist everything through one
    # cross-process transaction instead of mutating SettingsManager internals.
    ai_patch = {
        "use_local_only": canonical_mode == "local",
        "cloud_provider": "deepseek",
    }
    settings_patch = {
        "model_mode": canonical_mode,
        "ai": ai_patch,
    }
    normalized_model_tag = str(model_tag or "").strip()
    if normalized_model_tag:
        settings_patch["local_model"] = normalized_model_tag
        ai_patch["local_model"] = normalized_model_tag
    saved = sm.patch(settings_patch)
    active_model = str(sm.get_all().get("local_model") or "").strip()
    if saved:
        # LocalModelRouter has a separate response cache for legacy fast
        # paths.  Clear it here so it cannot keep answering with the model
        # selected before this atomic settings update.
        try:
            from app.core.routing.local_model_router import LocalModelRouter

            LocalModelRouter.reset_response_model()
        except Exception:
            pass
        try:
            from app.core.llm.local_model_capabilities import clear_ollama_capability_cache

            clear_ollama_capability_cache()
        except Exception:
            pass
    return saved, active_model


def _model_runtime_payload(sm) -> dict:
    """Expose the only supported model-selection contract to every UI entry."""
    from app.core.llm.local_model_runtime import (
        get_configured_local_model_tag,
        get_configured_model_mode,
    )
    from app.core.llm.model_selection import (
        get_configured_cloud_model,
        get_configured_cloud_provider,
    )

    mode = get_configured_model_mode()
    cloud_provider = get_configured_cloud_provider()
    cloud_model = get_configured_cloud_model(provider=cloud_provider)
    local_model = get_configured_local_model_tag()
    active_model = local_model if mode == "local" else cloud_model
    return {
        "mode": mode,
        "cloud_provider": cloud_provider,
        "cloud_model": cloud_model,
        "local_model": local_model,
        "active_model": {
            "mode": mode,
            "provider": "ollama" if mode == "local" else cloud_provider,
            "id": active_model,
        },
    }


def _augment_models_for_cloud_provider(payload: dict) -> dict:
    try:
        from app.core.llm.deepseek_config import DEEPSEEK_DEFAULT_MODEL, has_deepseek_api_key
        from app.core.llm.model_selection import get_configured_cloud_provider
        from app.core.llm.provider_boundary import (
            is_legacy_public_model,
            normalize_public_model,
        )

        provider = get_configured_cloud_provider()
        if provider != "deepseek":
            return payload

        model_id = DEEPSEEK_DEFAULT_MODEL
        try:
            sm = _get_settings_manager()
            model_id = str(sm.get("ai", "deepseek_model") or model_id).strip() or model_id
        except Exception:
            pass
        model_entry = {
            "id": model_id,
            "display": "DeepSeek Chat",
            "tier": 10,
            "provider": "deepseek",
            "strengths": ["reasoning", "coding", "tool_calling", "file_task"],
            "capabilities": {"tool_calling": True, "streaming": True},
        }
        text_tasks = [
            "CHAT",
            "CODER",
            "WEB_SEARCH",
            "RESEARCH",
            "FILE_GEN",
            "FILE_TASK",
            "AGENT",
            "FILE_SEARCH",
            "DOC_ANNOTATE",
            "MEETING_EXTRACT",
            "COMPLEX",
        ]
        raw_map = payload.get("model_map")
        if isinstance(raw_map, dict):
            for task, current in list(raw_map.items()):
                if isinstance(current, dict):
                    current_id = str(current.get("model_id") or "").lower()
                    current_provider = str(current.get("provider") or "").lower()
                else:
                    current_id = str(current or "").lower()
                    current_provider = ""
                if is_legacy_public_model(current_id) or current_provider == "gemini":
                    raw_map.pop(task, None)
            for task in text_tasks:
                current = raw_map.get(task)
                if isinstance(current, dict):
                    current.update(
                        {
                            "model_id": model_id,
                            "display": "DeepSeek Chat",
                            "provider": "deepseek",
                            "tier": 10,
                        }
                    )
                else:
                    raw_map[task] = model_id
        available = payload.setdefault("available", [])
        if isinstance(available, list):
            available[:] = [
                item
                for item in available
                if not (
                    isinstance(item, dict)
                    and (
                        is_legacy_public_model(item.get("id"))
                        or str(item.get("provider") or "").lower() == "gemini"
                    )
                )
            ]
            if not any(
                item.get("id") == model_id
                for item in available
                if isinstance(item, dict)
            ):
                available.insert(0, model_entry)
        payload["cloud_provider"] = "deepseek"
        payload["cloud_provider_ready"] = has_deepseek_api_key()
        payload["fallback"] = normalize_public_model(payload.get("fallback"))
        interactions_only = payload.get("interactions_only")
        if isinstance(interactions_only, list):
            payload["interactions_only"] = [
                model_id
                for model_id in interactions_only
                if not is_legacy_public_model(model_id)
            ]
    except Exception as exc:
        _logger.debug("[Models] cloud provider augmentation skipped: %s", exc)
    return payload


# ---------------------------------------------------------------------------
# /api/info
# ---------------------------------------------------------------------------


@settings_bp.route("/api/info", methods=["GET"])
def api_info() -> Response:
    """Application metadata and configuration info.
    ---
    tags: [Health]
    responses:
      200:
        description: App metadata
        schema:
          properties:
            version: {type: string}
            deploy_mode: {type: string, enum: [local, cloud]}
            auth_enabled: {type: boolean}
    """
    return jsonify(
        {
            "version": get_app_version(""),
            "deploy_mode": os.environ.get("KOTO_DEPLOY_MODE", "local"),
            "auth_enabled": os.environ.get("KOTO_AUTH_ENABLED", "false").lower()
            == "true",
        }
    )


# ---------------------------------------------------------------------------
# /api/local-model/*
# ---------------------------------------------------------------------------


@settings_bp.route("/api/local-model/status", methods=["GET"])
@require_auth
def local_model_status() -> Response:
    """Get local model configuration and runtime status.
    ---
    tags:
      - Models
    responses:
      200:
        description: Local model info
        schema:
          type: object
          properties:
            success:
              type: boolean
            model_name:
              type: string
              description: Currently configured local model name
            status:
              type: string
              description: Runtime status of the local model
      500:
        description: Failed to retrieve model info
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            error:
              type: string
    """
    try:
        from app.core.llm.ollama_provider import get_local_model_info
        from app.core.llm.model_selection import get_configured_cloud_provider

        info = get_local_model_info()
        if info.get("mode") in {"cloud", "gemini", "deepseek"}:
            provider = get_configured_cloud_provider()
            info["cloud_provider"] = provider
            info["mode"] = "cloud"
        return jsonify({"success": True, **info, **_model_runtime_payload(_get_settings_manager())})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@settings_bp.route("/api/local-model/switch", methods=["POST"])
@require_auth
def local_model_switch() -> Response:
    """Switch AI mode between local and cloud, hot-reloading client cache.
    ---
    tags:
      - Models
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            mode:
              type: string
              enum: [local, cloud]
              description: AI inference mode; omit this field to update only the local model tag
            model_tag:
              type: string
              description: Specific local model tag to use (only relevant when mode is local)
    responses:
      200:
        description: Mode switched successfully
        schema:
          type: object
          properties:
            success:
              type: boolean
            mode:
              type: string
              enum: [local, cloud]
            model:
              type: string
              description: Active model tag after switching
      500:
        description: Switch failed
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: false
            error:
              type: string
    """
    try:
        data = request.json or {}
        # A settings-panel model selection is not a request to change between
        # local and cloud modes.  Preserve the current mode when the caller
        # only submits model_tag; defaulting to cloud here used to make the
        # workspace toggle race the setting back to its previous model.
        requested_mode = data.get("mode")
        sm = _get_settings_manager()
        with sm._lock:
            current_mode = sm._settings.get("model_mode") or "cloud"
        raw_mode = str(requested_mode if requested_mode is not None else current_mode).strip().lower()
        if raw_mode == "gemini":
            return jsonify(
                {
                    "success": False,
                    "error": "Gemini provider is archived and cannot be selected.",
                    "code": "provider_archived",
                }
            ), 410
        mode = "local" if raw_mode in {"local", "ollama"} else "cloud"
        model_tag = data.get("model_tag")  # 本地模式时可指定模型

        save_ok, active_model = _save_model_runtime(sm, mode=mode, model_tag=model_tag)
        if not save_ok:
            return jsonify({"success": False, "error": "保存设置到磁盘失败"}), 500

        # 清除缓存，下次 get_client() 调用时重建
        invalidate_settings_cache()
        reset_client_cache()

        return jsonify(
            {
                "success": True,
                **_model_runtime_payload(sm),
                "model": active_model,
                "use_local_only": mode == "local",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@settings_bp.route("/api/local-model/setup", methods=["POST"])
@require_auth
def local_model_setup() -> Response:
    """触发本地模型安装向导（异步，不阻塞 API 响应）"""
    try:
        import subprocess as _subprocess
        import sys as _sys
        from pathlib import Path as _Path

        app_root = _Path(_sys.executable).parent if getattr(_sys, "frozen", False) else _Path(get_project_root())
        installer = app_root / "LocalModelInstaller.exe"
        if installer.exists():
            _subprocess.Popen([str(installer)], cwd=str(app_root))
            return jsonify({"success": True, "message": "独立本地模型安装器已启动"})
    except Exception as e:
        _logger.debug("[LocalModel] 独立安装器启动失败，回退内置向导: %s", e)

    def _run_gui():
        try:
            from model_downloader import run_downloader_gui

            run_downloader_gui()
            # 安装完成后清除缓存
            invalidate_settings_cache()
            reset_client_cache()
        except Exception as e:
            _logger.debug(f"[LocalModel] 安装向导失败: {e}")

    import threading as _threading

    _threading.Thread(target=_run_gui, daemon=True).start()
    return jsonify({"success": True, "message": "安装向导已启动"})


# ---------------------------------------------------------------------------
# /api/settings
# ---------------------------------------------------------------------------


@settings_bp.route("/api/settings", methods=["GET"])
@require_auth
def get_settings() -> Response:
    """Get all application settings.
    ---
    tags:
      - Settings
    responses:
      200:
        description: All settings grouped by category
        schema:
          type: object
    """
    # 合并 appearance 主题（如有 cookie/参数可在此合并）
    from app.core.llm.provider_boundary import sanitize_public_settings

    response = jsonify(sanitize_public_settings(_get_settings_manager().get_all()))
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@settings_bp.route("/api/settings", methods=["POST"])
@require_auth
def update_settings() -> Response:
    """Update an application setting.
    ---
    tags:
      - Settings
    parameters:
      - in: body
        name: body
        required: true
        schema:
          required: [category, key, value]
          properties:
            category:
              type: string
              description: Settings category
            key:
              type: string
              description: Setting key
            value:
              description: New value
    responses:
      200:
        description: Update result
        schema:
          type: object
          properties:
            success:
              type: boolean
    """
    sm = _get_settings_manager()
    data = request.get_json(silent=True) or {}
    category = data.get("category")
    key = data.get("key")
    value = data.get("value")

    if category and key:
        value, validation_error = _normalize_setting_value(category, key, value)
        if validation_error:
            return jsonify({"success": False, "error": validation_error}), 400
        if category == "ai" and key in {"local_model", "use_local_only"}:
            # Legacy callers of /api/settings use the exact same atomic
            # model-runtime writer as the settings picker and workspace mode
            # control.  There is no longer a competing persistence path.
            current_mode = str(sm.get_all().get("model_mode") or "cloud").strip().lower()
            target_mode = (
                "local" if bool(value) else "cloud"
            ) if key == "use_local_only" else current_mode
            success, _ = _save_model_runtime(
                sm,
                mode=target_mode,
                model_tag=value if key == "local_model" else None,
            )
        else:
            success = sm.set(category, key, value)
        if not success:
            return jsonify({"success": False, "error": "保存设置到磁盘失败"}), 500
        # Storage settings must create the newly selected paths, not only the
        # old paths that existed before the update.
        sm.ensure_directories()
        # 使 _load_user_settings 缓存失效，确保后续读取获得最新值
        invalidate_settings_cache()
        if category == "ai" and key in {"local_model", "use_local_only"}:
            reset_client_cache()
        # 存储路径变更时立即更新模块级全局变量，让运行时路径即时生效
        if category == "storage" and key in ("workspace_dir", "chats_dir", "documents_dir", "images_dir"):
            if key == "workspace_dir":
                update_workspace_dir(sm.workspace_dir)
            elif key == "chats_dir":
                update_chat_dir(sm.chats_dir)
        # 代理设置变更时立即重新检测
        if category == "proxy":
            reset_proxy_detection()
            # The old client may already hold a transport created with the
            # previous proxy.  Rebuild it lazily for the next request so this
            # setting takes effect now rather than after an application restart.
            reset_client_cache()
        return jsonify({"success": success})
    return jsonify({"success": False, "error": "Missing category or key"})


@settings_bp.route("/api/settings/reset", methods=["POST"])
@require_auth
def reset_settings() -> Response:
    sm = _get_settings_manager()
    success = sm.reset()
    # 同样清除缓存
    invalidate_settings_cache()
    reset_proxy_detection()
    reset_client_cache()
    return jsonify({"success": success})


# ---------------------------------------------------------------------------
# /api/setup/*
# ---------------------------------------------------------------------------


@settings_bp.route("/api/setup/status", methods=["GET"])
def get_setup_status() -> Response:
    """Check initial setup status (API key, workspace).
    ---
    tags:
      - Setup
    responses:
      200:
        description: Current setup status
        schema:
          type: object
          properties:
            initialized:
              type: boolean
              description: True when both API key and workspace are configured
            has_api_key:
              type: boolean
              description: Whether a valid API key is present
            has_workspace:
              type: boolean
              description: Whether the workspace directory exists
            workspace_path:
              type: string
              description: Absolute path to the workspace directory
            config_path:
              type: string
              description: Absolute path to the configuration file
    """
    from app.core.llm.deepseek_config import find_deepseek_config_path, has_deepseek_api_key
    PROJECT_ROOT = get_project_root()
    WORKSPACE_DIR = get_workspace_dir()
    provider = "deepseek"
    ds_path = find_deepseek_config_path()
    config_path = str(ds_path or os.path.join(PROJECT_ROOT, "config", "deepseek_config.env"))
    has_api_key = has_deepseek_api_key()
    has_workspace = os.path.exists(WORKSPACE_DIR)

    return jsonify(
        {
            "initialized": has_api_key and has_workspace,
            "has_api_key": has_api_key,
            "has_workspace": has_workspace,
            "workspace_path": os.path.abspath(WORKSPACE_DIR),
            "config_path": os.path.abspath(config_path),
            "cloud_provider": provider,
        }
    )


@settings_bp.route("/api/setup/apikey", methods=["POST"])
def setup_api_key() -> Response:
    """Persist the API key for the active DeepSeek cloud provider."""
    data = request.json or {}
    api_key = data.get("api_key", "").strip()
    provider = str(data.get("provider") or "").strip().lower() or "deepseek"

    if provider != "deepseek":
        archived = provider == "gemini"
        return jsonify(
            {
                "success": False,
                "error": (
                    "Gemini provider is archived and cannot accept new API keys."
                    if archived
                    else f"Unsupported cloud provider: {provider}"
                ),
                "code": "provider_archived" if archived else "provider_unsupported",
            }
        ), 410 if archived else 400

    if not api_key or len(api_key) < 10:
        return jsonify({"success": False, "error": "Invalid API key"})

    try:
        from app.core.llm.deepseek_config import (
            set_runtime_deepseek_api_key,
            write_deepseek_config_file,
        )
        write_deepseek_config_file(api_key)
        set_runtime_deepseek_api_key(api_key)
        sm = _get_settings_manager()
        sm.set("ai", "cloud_provider", "deepseek")
        sm.set("ai", "deepseek_model", "deepseek-chat")

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


def _write_provider_env(filename: str, key_name: str, api_key: str) -> str:
    """Write a simple .env file for OpenAI / Anthropic style providers."""
    from pathlib import Path as _Path
    config_path = _Path(get_project_root()) / "config" / filename
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(f"{key_name}={api_key}\n", encoding="utf-8")
    # Also load into current environment
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(str(config_path), override=True)
    return str(config_path)


@settings_bp.route("/api/setup/workspace", methods=["POST"])
def setup_workspace() -> Response:
    """设置工作区目录"""
    PROJECT_ROOT = get_project_root()
    sm = _get_settings_manager()
    data = request.json
    workspace_path = data.get("path", "").strip()

    if not workspace_path:
        workspace_path = os.path.join(PROJECT_ROOT, "workspace")

    try:
        os.makedirs(workspace_path, exist_ok=True)
        os.makedirs(os.path.join(workspace_path, "documents"), exist_ok=True)
        os.makedirs(os.path.join(workspace_path, "images"), exist_ok=True)
        os.makedirs(os.path.join(workspace_path, "code"), exist_ok=True)

        # 更新设置
        sm.set("storage", "workspace_dir", workspace_path)

        return jsonify({"success": True, "path": workspace_path})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@settings_bp.route("/api/setup/test", methods=["GET"])
def test_api_connection() -> Response:
    """测试 API 连接"""
    try:
        from app.core.llm.model_selection import get_configured_cloud_model, get_configured_cloud_provider
        from app.core.llm.provider_factory import get_llm_provider

        provider_name = get_configured_cloud_provider()
        model = get_configured_cloud_model(provider="deepseek")
        provider = get_llm_provider(provider="deepseek", model=model)
        start = time.time()
        result = provider.generate_content(
            prompt="Say 'Koto is ready!' in one short sentence.",
            model=model,
            max_tokens=64,
            stream=False,
        )
        latency = time.time() - start
        message = result.get("content", "") if isinstance(result, dict) else str(result)
        return jsonify(
            {"success": True, "message": message, "latency": round(latency, 2)}
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ---------------------------------------------------------------------------
# /api/diagnose
# ---------------------------------------------------------------------------


@settings_bp.route("/api/diagnose", methods=["GET"])
@require_auth
def diagnose_models() -> Response:
    """诊断所有模型的可用性"""
    from app.core.llm.provider_factory import get_llm_provider

    provider = get_llm_provider(provider="deepseek", allow_local_fallback=False)

    results = {
        "proxy": {
            "detected": get_detected_proxy(),
            "force": get_force_proxy() or None,
            "cloud_provider": "deepseek",
        },
        "models": {},
    }

    # 测试模型列表
    test_models = [("deepseek-chat", "云端对话与任务规划")]

    def test_model(model_id, purpose):
        try:
            start = time.time()
            provider.generate_content(
                prompt="Reply with only: OK",
                model=model_id,
                max_tokens=10,
            )
            latency = time.time() - start
            return {
                "status": "✅ 可用",
                "latency": round(latency, 2),
                "purpose": purpose,
            }
        except Exception as e:
            error_msg = str(e)
            if "location is not supported" in error_msg:
                status = "❌ 地区限制"
            elif "not found" in error_msg.lower():
                status = "❌ 模型不存在"
            elif "quota" in error_msg.lower():
                status = "⚠️ 配额耗尽"
            elif "timeout" in error_msg.lower():
                status = "⚠️ 超时"
            else:
                status = "❌ 错误"
            return {"status": status, "error": error_msg[:150], "purpose": purpose}

    # 并行测试（带超时）
    threads = []
    for model_id, purpose in test_models:

        def run_test(m=model_id, p=purpose):
            results["models"][m] = test_model(m, p)

        thr = threading.Thread(target=run_test, daemon=True)
        threads.append(thr)
        thr.start()

    # 等待所有线程完成（最多 15 秒）
    for thr in threads:
        thr.join(timeout=15)

    # 检查是否所有模型都不可用
    all_failed = all(
        "❌" in results["models"].get(m, {}).get("status", "") for m, _ in test_models
    )

    if all_failed:
        results["recommendation"] = (
            "DeepSeek 不可用。建议：\n1. 检查代理配置是否正确\n2. 检查 DeepSeek API Key\n3. 检查服务商网络状态"
        )

    return jsonify(results)


# ---------------------------------------------------------------------------
# Additional routes: local-model list, window API, setup activate,
# model listing / refresh, task analysis
# ---------------------------------------------------------------------------


@settings_bp.route("/api/local-model/list", methods=["GET"])
@require_auth
def local_model_list() -> Response:
    """列出 Ollama 已安装的所有本地模型"""
    import socket as _socket

    ollama_url = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")

    # 先做快速端口探测，区分"未安装"与"正在启动"
    def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
        try:
            s = _socket.create_connection((host, port), timeout=timeout)
            s.close()
            return True
        except OSError:
            return False

    host_part = ollama_url.split("://", 1)[-1].rsplit(":", 1)
    try:
        _host, _port = host_part[0], int(host_part[1]) if len(host_part) > 1 else 11434
    except (ValueError, IndexError):
        _host, _port = "127.0.0.1", 11434

    # 重试一次：Ollama 可能正在启动
    port_ok = _port_open(_host, _port, timeout=1.5) or _port_open(_host, _port, timeout=2.0)
    if not port_ok:
        import shutil
        installed = shutil.which("ollama") is not None
        hint = "Ollama 正在启动，请稍候重试" if installed else "Ollama 未安装，请访问 ollama.com 下载"
        return jsonify({"success": False, "models": [], "error": hint}), 200

    try:
        import requests as _requests
        r = _requests.get(
            f"{ollama_url}/api/tags",
            headers={"Accept": "application/json"},
            timeout=8,
            proxies={"http": None, "https": None},  # 强制绕过系统代理，避免 VPN/代理导致 502
        )
        r.raise_for_status()
        data = r.json()
        models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        return jsonify({"success": True, "models": models})
    except Exception as e:
        err_str = str(e)
        if "502" in err_str:
            hint = "Ollama 服务异常 (502)，请在命令行运行 ollama serve 后重试"
        else:
            hint = err_str
        return jsonify({"success": False, "models": [], "error": hint}), 200


@settings_bp.route("/api/window/switch-to-full", methods=["POST"])
@require_auth
def api_window_switch_to_full() -> Response:
    """通过 HTTP 降级调用 WindowAPI.switch_to_full（pywebview JS bridge 不可用时使用）"""
    window_api = current_app.config.get("WINDOW_API")
    if window_api is None:
        return jsonify({"success": False, "error": "not_in_pywebview"})
    return jsonify(window_api.switch_to_full())


@settings_bp.route("/api/window/switch-to-mini", methods=["POST"])
@require_auth
def api_window_switch_to_mini() -> Response:
    """通过 HTTP 降级调用 WindowAPI.switch_to_mini"""
    window_api = current_app.config.get("WINDOW_API")
    if window_api is None:
        return jsonify({"success": False, "error": "not_in_pywebview"})
    return jsonify(window_api.switch_to_mini())


@settings_bp.route("/api/setup/activate", methods=["POST"])
def setup_activate() -> Response:
    """使用激活码启用系统内置 API Key"""
    data = request.json or {}
    code = (data.get("code") or "").strip()
    if not code:
        return jsonify({"success": False, "error": "请输入激活码"})
    try:
        from app.core.llm._license import get_system_key

        key = get_system_key(code)
    except Exception as e:
        _logger.warning("[Activate] 无法加载 _license 模块: %s", e)
        return jsonify({"success": False, "error": "激活服务暂不可用"})
    if not key:
        return jsonify({"success": False, "error": "激活码无效"})
    PROJECT_ROOT = get_project_root()
    from app.core.llm.deepseek_config import (
        set_runtime_deepseek_api_key,
        write_deepseek_config_file,
    )

    config_path = os.path.join(PROJECT_ROOT, "config", "deepseek_config.env")
    try:
        config_path = str(write_deepseek_config_file(key))
        set_runtime_deepseek_api_key(key)
        reset_client_cache()
        sm = _get_settings_manager()
        sm.set("ai", "cloud_provider", "deepseek")
        sm.set("ai", "deepseek_model", "deepseek-chat")
        _logger.info("[Activate] 激活码验证成功，系统 API Key 已写入配置")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@settings_bp.route("/api/v1/models", methods=["GET"])
@require_auth
def api_list_models() -> Response:
    """动态模型列表 API — 返回当前可用模型及各任务的路由结果"""
    runtime = get_model_runtime()
    if runtime.model_manager:
        return jsonify(
            _augment_models_for_cloud_provider({
                "ready": True,
                "model_map": runtime.model_manager.get_model_map_with_scores(),
                "available": runtime.model_manager.get_available_models(),
                "fallback": runtime.fallback_model,
                "interactions_only": list(runtime.interactions_only_models),
            })
        )
    return jsonify(
        _augment_models_for_cloud_provider({
            "ready": False,
            "model_map": {
                task: {
                    "model_id": mid,
                    "display": runtime.get_display_name(mid),
                    "provider": "deepseek" if mid != "local-executor" else "local",
                    "tier": runtime.model_info.get(mid, {}).get("tier", 5),
                    "score": None,
                    "_inferred": False,
                }
                for task, mid in runtime.model_map.items()
            },
            "available": [
                {
                    "id": mid,
                    "display": runtime.get_display_name(mid),
                    "tier": runtime.model_info.get(mid, {}).get("tier", 5),
                    "provider": "deepseek" if mid != "local-executor" else "local",
                    "strengths": runtime.model_info.get(mid, {}).get("strengths", []),
                    "capabilities": {},
                }
                for mid in dict.fromkeys(runtime.model_map.values())
            ],
            "fallback": runtime.fallback_model,
            "interactions_only": list(runtime.interactions_only_models),
        })
    )


@settings_bp.route("/api/v1/models/refresh", methods=["POST"])
@require_auth
def api_refresh_models() -> Response:
    """手动触发模型列表刷新，重新查询 API 并更新路由表"""
    runtime = get_model_runtime()
    if not runtime.model_manager_available or runtime.model_manager is None:
        import threading as _t

        _t.Thread(
            target=runtime.initialize_model_manager, name="ModelManagerReinit", daemon=True
        ).start()
        return jsonify(
            {"status": "initializing", "message": "模型管理器正在后台初始化"}
        )
    try:
        new_map = runtime.model_manager.refresh()
        runtime.model_map.update(new_map)
        try:
            from app.core.llm.model_fallback import get_fallback_executor

            get_fallback_executor().update_model_map(runtime.model_map)
        except Exception as _fe:
            _logger.warning("[ModelRefresh] FallbackExecutor sync failed: %s", _fe)
        try:
            from app.core.routing.ai_router import AIRouter

            _caps = runtime.model_manager._cached_caps
            _candidates = [
                (mid, caps)
                for mid, caps in _caps.items()
                if not caps.get("interactions_only", False)
                and not caps.get("image_gen", False)
                and mid != "local-executor"
            ]
            if _candidates:
                _best = max(
                    _candidates,
                    key=lambda x: x[1].get("speed", 0) + x[1].get("tier", 0) * 0.1,
                )[0]
                AIRouter.set_router_model(_best)
        except Exception as _are:
            _logger.warning("[ModelRefresh] AIRouter update failed: %s", _are)
        return jsonify(
            {
                "status": "ok",
                "model_map": runtime.model_manager.get_model_map_with_scores(),
                "count": len(runtime.model_manager.get_available_models()),
            }
        )
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@settings_bp.route("/api/analyze", methods=["POST"])
@require_auth
def analyze_task() -> Response:
    """预分析任务类型和模型选择 — 让前端立即显示路由结果"""
    from app.core.routing import SmartDispatcher

    runtime = get_model_runtime()
    data = request.json or {}
    message: str = data.get("message", "")
    locked_task: str | None = data.get("locked_task")
    locked_model: str = data.get("locked_model", "auto")
    has_file: bool = data.get("has_file", False)
    file_type: str = data.get("file_type", "")

    if not message:
        return jsonify(
            {"task": "CHAT", "model": runtime.model_map["CHAT"], "route_method": "Empty"}
        )

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

    if locked_task:
        task = locked_task
        route_method = "🔒 Manual"
    elif has_file and file_type and file_type.startswith("image"):
        is_edit = any(kw in message.lower() for kw in IMAGE_EDIT_KEYWORDS)
        task = "PAINTER" if is_edit else "VISION"
        route_method = "🖼️ Image Edit" if is_edit else "👁️ Image Analysis"
    else:
        task, route_method, _ = SmartDispatcher.analyze(message)

    model = (
        locked_model
        if (locked_model and locked_model != "auto")
        else SmartDispatcher.get_model_for_task(task, has_image=has_file)
    )
    try:
        from app.core.llm.model_selection import get_configured_cloud_model

        if str(model or "").strip().lower() in {"", "auto", "cloud"} or not str(model or "").strip().lower().startswith("local"):
            model = get_configured_cloud_model(task_type=task, fallback_model=model) or model
    except Exception:
        pass
    model_info = runtime.model_info.get(model, {"name": model, "speed": ""})
    return jsonify(
        {
            "task": task,
            "model": model,
            "model_name": model_info.get("name", model),
            "model_speed": model_info.get("speed", ""),
            "route_method": route_method,
            "strengths": model_info.get("strengths", []),
        }
    )
