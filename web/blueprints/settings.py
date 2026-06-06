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

from flask import Blueprint, Response, current_app, jsonify, request

from web.auth import require_auth
from web.runtime_context import (
    get_app_attr,
    get_app_module,
    get_client,
    get_project_root,
    get_settings_manager,
    get_types,
    get_workspace_dir,
)

_logger = logging.getLogger("koto.app")

settings_bp = Blueprint("settings_routes", __name__)

# ---------------------------------------------------------------------------
# Lazy accessors for runtime services still owned by web.app.
# ---------------------------------------------------------------------------


def _app():
    """Return the web.app module (for mutable globals)."""
    return get_app_module()


def _get_settings_manager():
    return get_settings_manager()


def _get_client():
    return get_client()


def _get_types():
    return get_types()


def _get_create_client():
    return get_app_attr("create_client")


def _get_detected_proxy():
    detector = get_app_attr("get_detected_proxy")
    if callable(detector):
        return detector()
    return None


def _augment_models_for_cloud_provider(payload: dict) -> dict:
    try:
        from app.core.llm.deepseek_config import DEEPSEEK_DEFAULT_MODEL, has_deepseek_api_key
        from app.core.llm.model_selection import get_configured_cloud_provider

        provider = get_configured_cloud_provider()
        if provider != "deepseek":
            return payload

        model_id = DEEPSEEK_DEFAULT_MODEL
        sm = _get_settings_manager()
        try:
            model_id = str(sm.get("ai", "deepseek_model") or model_id).strip() or model_id
        except Exception:
            pass
        model_entry = {
            "id": model_id,
            "display": "DeepSeek V4 Pro",
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
            for task in text_tasks:
                current = raw_map.get(task)
                if isinstance(current, dict):
                    current.update(
                        {
                            "model_id": model_id,
                            "display": "DeepSeek V4 Pro",
                            "provider": "deepseek",
                            "tier": 10,
                        }
                    )
                else:
                    raw_map[task] = model_id
        available = payload.setdefault("available", [])
        if isinstance(available, list) and not any(
            item.get("id") == model_id for item in available if isinstance(item, dict)
        ):
            available.insert(0, model_entry)
        payload["cloud_provider"] = "deepseek"
        payload["cloud_provider_ready"] = has_deepseek_api_key()
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
            "version": get_app_attr("APP_VERSION", ""),
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
            if info.get("mode") == "cloud":
                info["mode"] = provider
        return jsonify({"success": True, **info})
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
              default: cloud
              description: AI inference mode
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
        mod = _app()
        data = request.json or {}
        raw_mode = str(data.get("mode") or "cloud").strip().lower()
        mode = raw_mode if raw_mode in {"local", "cloud", "gemini", "deepseek"} else "cloud"
        model_tag = data.get("model_tag")  # 本地模式时可指定模型

        sm = _get_settings_manager()

        # model_mode / local_model are top-level keys, not category.key – use
        # the lock + _save_settings directly to ensure atomic write.
        with sm._lock:
            sm._settings["model_mode"] = mode
            ai_settings = sm._settings.setdefault("ai", {})
            if isinstance(ai_settings, dict):
                if mode in {"gemini", "deepseek"}:
                    ai_settings["cloud_provider"] = mode
                elif mode == "cloud":
                    ai_settings.setdefault("cloud_provider", "gemini")
            if model_tag:
                sm._settings["local_model"] = model_tag
            save_ok = sm._save_settings()
        if not save_ok:
            return jsonify({"success": False, "error": "保存设置到磁盘失败"}), 500

        # 清除缓存，下次 get_client() 调用时重建
        mod._user_settings_cache.clear()
        mod._client = None
        mod._client_mode_key = (None, None)

        return jsonify(
            {
                "success": True,
                "mode": mode,
                "model": model_tag or sm.get_all().get("local_model"),
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
            mod = _app()
            mod._user_settings_cache.clear()
            mod._client = None
            mod._client_mode_key = (None, None)
        except Exception as e:
            _logger.debug(f"[LocalModel] 安装向导失败: {e}")

    import threading as _threading

    _threading.Thread(target=_run_gui, daemon=True).start()
    return jsonify({"success": True, "message": "安装向导已启动"})


# ---------------------------------------------------------------------------
# /api/skills  (list)  and  /api/skills/<skill_id>/*
# ---------------------------------------------------------------------------


@settings_bp.route("/api/skills", methods=["GET"])
@require_auth
def list_skills() -> Response:
    """Return all skills with their metadata and enabled state."""
    try:
        from app.core.skills.skill_manager import SkillManager

        return jsonify(SkillManager.list_skills())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@settings_bp.route("/api/skills/<skill_id>/toggle", methods=["POST"])
@require_auth
def toggle_skill(skill_id: str) -> Response:
    """Enable or disable a skill.
    ---
    tags:
      - Skills
    parameters:
      - in: path
        name: skill_id
        type: string
        required: true
        description: Unique identifier of the skill
      - in: body
        name: body
        required: true
        schema:
          type: object
          properties:
            enabled:
              type: boolean
              description: Whether to enable or disable the skill
    responses:
      200:
        description: Toggle result
        schema:
          type: object
          properties:
            success:
              type: boolean
      500:
        description: Server error
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
        from app.core.skills.skill_manager import SkillManager

        data = request.json or {}
        enabled = bool(data.get("enabled", False))
        success = SkillManager.set_enabled(skill_id, enabled)
        return jsonify({"success": success})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@settings_bp.route("/api/skills/<skill_id>/prompt", methods=["POST"])
@require_auth
def update_skill_prompt(skill_id: str) -> Response:
    """更新某个技能的自定义 Prompt"""
    try:
        from app.core.skills.skill_manager import SkillManager

        data = request.json or {}
        prompt = data.get("prompt", "")
        if not prompt.strip():
            SkillManager.reset_prompt(skill_id)
            return jsonify({"success": True, "reset": True})
        success = SkillManager.update_prompt(skill_id, prompt)
        return jsonify({"success": success})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@settings_bp.route("/api/skills/<skill_id>/reset", methods=["POST"])
@require_auth
def reset_skill_prompt(skill_id: str) -> Response:
    """将技能 Prompt 恢复为默认值"""
    try:
        from app.core.skills.skill_manager import SkillManager

        success = SkillManager.reset_prompt(skill_id)
        return jsonify({"success": success})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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
    return jsonify(_get_settings_manager().get_all())


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
    mod = _app()
    sm = _get_settings_manager()
    data = request.json
    category = data.get("category")
    key = data.get("key")
    value = data.get("value")

    if category and key:
        sm.ensure_directories()
        success = sm.set(category, key, value)
        if not success:
            return jsonify({"success": False, "error": "保存设置到磁盘失败"}), 500
        # 使 _load_user_settings 缓存失效，确保后续读取获得最新值
        mod._user_settings_cache.clear()
        # 存储路径变更时立即更新模块级全局变量，让运行时路径即时生效
        if category == "storage" and key in ("workspace_dir", "chats_dir", "documents_dir", "images_dir"):
            _app_mod = _app()
            if key == "workspace_dir":
                _app_mod.WORKSPACE_DIR = sm.workspace_dir
                import os as _os
                _os.makedirs(_app_mod.WORKSPACE_DIR, exist_ok=True)
            elif key == "chats_dir":
                _app_mod.CHAT_DIR = sm.chats_dir
                import os as _os
                _os.makedirs(_app_mod.CHAT_DIR, exist_ok=True)
        # 代理设置变更时立即重新检测
        if category == "proxy":
            mod._proxy_checked = False
            mod._detected_proxy = None
            threading.Thread(
                target=lambda: mod.get_detected_proxy(), daemon=True
            ).start()
        return jsonify({"success": success})
    return jsonify({"success": False, "error": "Missing category or key"})


@settings_bp.route("/api/settings/reset", methods=["POST"])
@require_auth
def reset_settings() -> Response:
    mod = _app()
    sm = _get_settings_manager()
    success = sm.reset()
    # 同样清除缓存
    mod._user_settings_cache.clear()
    mod._proxy_checked = False
    mod._detected_proxy = None
    return jsonify({"success": success})


# ---------------------------------------------------------------------------
# /api/switch-to-mini, /api/switch-to-main
# ---------------------------------------------------------------------------


@settings_bp.route("/api/switch-to-mini", methods=["POST"])
@require_auth
def switch_to_mini() -> Response:
    """切换到迷你模式"""
    import subprocess
    import sys

    # 打包版无法以脚本方式启动 mini_koto.py
    if getattr(sys, "frozen", False):
        return jsonify(
            {"success": False, "error": "打包版暂不支持迷你模式，请使用窗口顶栏按钮"}
        )

    try:
        PROJECT_ROOT = get_project_root()

        # 启动迷你窗口
        mini_koto_path = os.path.join(PROJECT_ROOT, "web", "mini_koto.py")
        if os.path.exists(mini_koto_path):
            # 在新进程中启动迷你窗口
            subprocess.Popen(
                [sys.executable, mini_koto_path],
                creationflags=(
                    subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                ),
                cwd=PROJECT_ROOT,
            )
            return jsonify({"success": True, "message": "迷你模式已启动"})
        else:
            return jsonify({"success": False, "error": "找不到迷你模式程序"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@settings_bp.route("/api/switch-to-main", methods=["POST"])
@require_auth
def switch_to_main() -> Response:
    """切换到主程序"""
    import subprocess
    import sys

    # 打包版已在主程序窗口中运行，直接返回成功
    if getattr(sys, "frozen", False):
        return jsonify({"success": True, "message": "已在主程序中运行"})

    try:
        PROJECT_ROOT = get_project_root()

        # 启动主窗口
        main_app_path = os.path.join(PROJECT_ROOT, "koto_app.py")
        if os.path.exists(main_app_path):
            subprocess.Popen(
                [sys.executable, main_app_path],
                creationflags=(
                    subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                ),
                cwd=PROJECT_ROOT,
            )
            return jsonify({"success": True, "message": "主程序已启动"})
        else:
            return jsonify({"success": False, "error": "找不到主程序"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


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
    from app.core.llm.model_selection import get_configured_cloud_provider

    provider = get_configured_cloud_provider()
    API_KEY = get_app_attr("API_KEY", "")
    PROJECT_ROOT = get_project_root()
    WORKSPACE_DIR = get_workspace_dir()
    config_path = os.path.join(PROJECT_ROOT, "config", "gemini_config.env")
    _placeholders = {"your_api_key_here", "YOUR_API_KEY_HERE", ""}
    if provider == "deepseek":
        ds_path = find_deepseek_config_path()
        config_path = str(ds_path or os.path.join(PROJECT_ROOT, "config", "deepseek_config.env"))
        has_api_key = has_deepseek_api_key()
    else:
        has_api_key = bool(API_KEY and len(API_KEY) > 10 and API_KEY not in _placeholders)
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
    """设置 API Key"""
    mod = _app()
    data = request.json
    api_key = data.get("api_key", "").strip()
    provider = str(data.get("provider") or "").strip().lower() or "gemini"

    if not api_key or len(api_key) < 10:
        return jsonify({"success": False, "error": "Invalid API key"})

    try:
        if provider == "deepseek":
            from app.core.llm.deepseek_config import (
                set_runtime_deepseek_api_key,
                write_deepseek_config_file,
            )

            write_deepseek_config_file(api_key)
            set_runtime_deepseek_api_key(api_key)
            sm = _get_settings_manager()
            sm.set("ai", "cloud_provider", "deepseek")
            sm.set("ai", "deepseek_model", "deepseek-v4-pro")
        else:
            from app.core.llm.gemini_config import (
                set_runtime_gemini_api_key,
                write_gemini_config_file,
            )

            write_gemini_config_file(api_key)
            mod.API_KEY = set_runtime_gemini_api_key(api_key)
            # Reset cached client so get_client() rebuilds with the new key
            mod._client = None
            mod.client = mod.create_client()

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


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
        if provider_name == "deepseek":
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

        c = _get_client()
        start = time.time()
        response = c.models.generate_content(
            model="gemini-2.5-flash",
            contents="Say 'Koto is ready!' in one short sentence.",
        )
        latency = time.time() - start
        return jsonify(
            {"success": True, "message": response.text, "latency": round(latency, 2)}
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
    c = _get_client()
    t = _get_types()

    results = {
        "proxy": {
            "detected": _get_detected_proxy(),
            "force": _app().FORCE_PROXY or None,
            "custom_endpoint": _app().GEMINI_API_BASE or None,
        },
        "models": {},
    }

    # 测试模型列表
    test_models = [
        ("gemini-2.5-flash-lite", "路由分类"),
        ("gemini-2.5-flash", "日常对话"),
        ("gemini-2.5-pro", "代码生成"),
        ("gemini-2.5-flash", "联网搜索"),
        ("gemini-3.1-flash-image-preview", "图像生成"),
    ]

    def test_model(model_id, purpose):
        try:
            start = time.time()
            if "image-generation" in model_id or "imagen" in model_id:
                # 图像模型只测试连通性
                response = c.models.generate_content(
                    model=model_id,
                    contents="test",
                    config=t.GenerateContentConfig(max_output_tokens=10),
                )
            else:
                response = c.models.generate_content(
                    model=model_id,
                    contents="Reply with only: OK",
                    config=t.GenerateContentConfig(max_output_tokens=10),
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
            "所有模型均不可用。建议：\n1. 检查代理配置是否正确\n2. 考虑使用 API 中转服务\n3. 在 gemini_config.env 中配置 GEMINI_API_BASE"
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
    from app.core.llm.gemini_config import (
        set_runtime_gemini_api_key,
        write_gemini_config_file,
    )

    config_path = os.path.join(PROJECT_ROOT, "config", "gemini_config.env")
    try:
        config_path = str(write_gemini_config_file(key))
        _mod = _app()
        _mod.API_KEY = set_runtime_gemini_api_key(key)
        _mod.client = _mod.create_client()
        _logger.info("[Activate] 激活码验证成功，系统 API Key 已写入配置")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@settings_bp.route("/api/v1/models", methods=["GET"])
@require_auth
def api_list_models() -> Response:
    """动态模型列表 API — 返回当前可用模型及各任务的路由结果"""
    _a = _app()
    if _a._model_manager:
        return jsonify(
            _augment_models_for_cloud_provider({
                "ready": True,
                "model_map": _a._model_manager.get_model_map_with_scores(),
                "available": _a._model_manager.get_available_models(),
                "fallback": _a._INTERACTIONS_FALLBACK_MODEL,
                "interactions_only": list(_a._INTERACTIONS_ONLY_MODELS),
            })
        )
    return jsonify(
        _augment_models_for_cloud_provider({
            "ready": False,
            "model_map": {
                task: {
                    "model_id": mid,
                    "display": _a.get_model_display_name(mid),
                    "provider": "gemini" if mid != "local-executor" else "local",
                    "tier": _a.MODEL_INFO.get(mid, {}).get("tier", 5),
                    "score": None,
                    "_inferred": False,
                }
                for task, mid in _a.MODEL_MAP.items()
            },
            "available": [
                {
                    "id": mid,
                    "display": _a.get_model_display_name(mid),
                    "tier": _a.MODEL_INFO.get(mid, {}).get("tier", 5),
                    "provider": "gemini" if mid != "local-executor" else "local",
                    "strengths": _a.MODEL_INFO.get(mid, {}).get("strengths", []),
                    "capabilities": {},
                }
                for mid in dict.fromkeys(_a.MODEL_MAP.values())
            ],
            "fallback": _a._INTERACTIONS_FALLBACK_MODEL,
            "interactions_only": list(_a._INTERACTIONS_ONLY_MODELS),
        })
    )


@settings_bp.route("/api/v1/models/refresh", methods=["POST"])
@require_auth
def api_refresh_models() -> Response:
    """手动触发模型列表刷新，重新查询 API 并更新路由表"""
    _a = _app()
    if not _a._model_manager_available or _a._model_manager is None:
        import threading as _t

        _t.Thread(
            target=_a._init_model_manager, name="ModelManagerReinit", daemon=True
        ).start()
        return jsonify(
            {"status": "initializing", "message": "模型管理器正在后台初始化"}
        )
    try:
        new_map = _a._model_manager.refresh()
        _a.MODEL_MAP.update(new_map)
        try:
            from app.core.llm.model_fallback import get_fallback_executor

            get_fallback_executor().update_model_map(_a.MODEL_MAP)
        except Exception as _fe:
            _logger.warning("[ModelRefresh] FallbackExecutor sync failed: %s", _fe)
        try:
            from app.core.routing.ai_router import AIRouter

            _caps = _a._model_manager._cached_caps
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
                "model_map": _a._model_manager.get_model_map_with_scores(),
                "count": len(_a._model_manager.get_available_models()),
            }
        )
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@settings_bp.route("/api/analyze", methods=["POST"])
@require_auth
def analyze_task() -> Response:
    """预分析任务类型和模型选择 — 让前端立即显示路由结果"""
    from app.core.routing import SmartDispatcher

    _a = _app()
    data = request.json or {}
    message: str = data.get("message", "")
    locked_task: str | None = data.get("locked_task")
    locked_model: str = data.get("locked_model", "auto")
    has_file: bool = data.get("has_file", False)
    file_type: str = data.get("file_type", "")

    if not message:
        return jsonify(
            {"task": "CHAT", "model": _a.MODEL_MAP["CHAT"], "route_method": "Empty"}
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
    model_info = _a.MODEL_INFO.get(model, {"name": model, "speed": ""})
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
