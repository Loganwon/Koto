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

_logger = logging.getLogger("koto.app")

settings_bp = Blueprint("settings_routes", __name__)

# ---------------------------------------------------------------------------
# Lazy accessors – avoid circular imports by pulling from web.app at runtime
# ---------------------------------------------------------------------------


def _app():
    """Return the web.app module (for mutable globals)."""
    import web.app as _mod

    return _mod


def _get_settings_manager():
    from web.app import settings_manager

    return settings_manager


def _get_client():
    from web.app import client

    return client


def _get_types():
    from web.app import types

    return types


def _get_create_client():
    from web.app import create_client

    return create_client


def _get_detected_proxy():
    from web.app import get_detected_proxy

    return get_detected_proxy()


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
    from web.app import APP_VERSION

    return jsonify(
        {
            "version": APP_VERSION,
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

        info = get_local_model_info()
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
        mode = data.get("mode", "cloud")  # "local" 或 "cloud"
        model_tag = data.get("model_tag")  # 本地模式时可指定模型

        settings_path = os.path.join(mod.PROJECT_ROOT, "config", "user_settings.json")
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except Exception:
            settings = {}

        settings["model_mode"] = mode
        if model_tag:
            settings["local_model"] = model_tag

        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)

        # 清除缓存，下次 get_client() 调用时重建
        mod._user_settings_cache.clear()
        mod._client = None
        mod._client_mode_key = (None, None)

        return jsonify(
            {
                "success": True,
                "mode": mode,
                "model": model_tag or settings.get("local_model"),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@settings_bp.route("/api/local-model/setup", methods=["POST"])
@require_auth
def local_model_setup() -> Response:
    """触发本地模型安装向导（异步，不阻塞 API 响应）"""

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
# /api/skills/<skill_id>/*
# ---------------------------------------------------------------------------


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
        success = sm.set(category, key, value)
        sm.ensure_directories()
        # 使 _load_user_settings 缓存失效，确保后续读取获得最新值
        mod._user_settings_cache.clear()
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
        from web.app import PROJECT_ROOT

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
        from web.app import PROJECT_ROOT

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
    from web.app import API_KEY, PROJECT_ROOT, WORKSPACE_DIR

    config_path = os.path.join(PROJECT_ROOT, "config", "gemini_config.env")
    _placeholders = {"your_api_key_here", "YOUR_API_KEY_HERE", ""}
    has_api_key = bool(API_KEY and len(API_KEY) > 10 and API_KEY not in _placeholders)
    has_workspace = os.path.exists(WORKSPACE_DIR)

    return jsonify(
        {
            "initialized": has_api_key and has_workspace,
            "has_api_key": has_api_key,
            "has_workspace": has_workspace,
            "workspace_path": os.path.abspath(WORKSPACE_DIR),
            "config_path": os.path.abspath(config_path),
        }
    )


@settings_bp.route("/api/setup/apikey", methods=["POST"])
def setup_api_key() -> Response:
    """设置 API Key"""
    mod = _app()
    data = request.json
    api_key = data.get("api_key", "").strip()

    if not api_key or len(api_key) < 10:
        return jsonify({"success": False, "error": "Invalid API key"})

    config_path = os.path.join(mod.PROJECT_ROOT, "config", "gemini_config.env")
    os.makedirs(os.path.dirname(config_path), exist_ok=True)

    try:
        # 写入配置文件（同时写入两个变量名，避免优先级错乱）
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(
                f"# Koto Configuration\nGEMINI_API_KEY={api_key}\nAPI_KEY={api_key}\n"
            )

        # 更新环境变量
        os.environ["GEMINI_API_KEY"] = api_key
        os.environ["API_KEY"] = api_key
        mod.API_KEY = api_key
        # Reset cached client so get_client() rebuilds with the new key
        mod._client = None
        mod.client = mod.create_client()

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@settings_bp.route("/api/setup/workspace", methods=["POST"])
def setup_workspace() -> Response:
    """设置工作区目录"""
    from web.app import PROJECT_ROOT

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
        c = _get_client()
        start = time.time()
        response = c.models.generate_content(
            model="gemini-3-flash-preview",
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
        ("gemini-2.0-flash-lite", "路由分类"),
        ("gemini-3-flash-preview", "日常对话"),
        ("gemini-3-pro-preview", "代码生成"),
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
    try:
        import json as _json
        import urllib.request as _urlreq

        ollama_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        req = _urlreq.Request(
            f"{ollama_url}/api/tags", headers={"Accept": "application/json"}
        )
        with _urlreq.urlopen(req, timeout=4) as resp:
            data = _json.loads(resp.read().decode())
        models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        return jsonify({"success": True, "models": models})
    except Exception as e:
        return jsonify({"success": False, "models": [], "error": str(e)}), 200


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
    from web.app import PROJECT_ROOT

    config_path = os.path.join(PROJECT_ROOT, "config", "gemini_config.env")
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(f"# Koto Configuration\nGEMINI_API_KEY={key}\nAPI_KEY={key}\n")
        os.environ["GEMINI_API_KEY"] = key
        os.environ["API_KEY"] = key
        _mod = _app()
        _mod.API_KEY = key
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
            {
                "ready": True,
                "model_map": _a._model_manager.get_model_map_with_scores(),
                "available": _a._model_manager.get_available_models(),
                "fallback": _a._INTERACTIONS_FALLBACK_MODEL,
                "interactions_only": list(_a._INTERACTIONS_ONLY_MODELS),
            }
        )
    return jsonify(
        {
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
        }
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
