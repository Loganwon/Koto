# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
HTML page-rendering blueprint.

Routes:
  GET /            - index
  GET /favicon.ico - favicon
  GET /app         - app_main
  GET /addons      - addon center
  GET /addon-center - addon center (compat)
  GET /mini        - mini page
"""

import os

from flask import Blueprint, Response, make_response, render_template, send_from_directory
from web.runtime_context import service_registry

pages_bp = Blueprint("pages", __name__)


def _get_initial_theme() -> str:
    """从已保存的用户设置读取初始主题，默认 light。"""
    try:
        settings_manager = service_registry.settings_manager
        if settings_manager is None:
            return "light"
        theme = settings_manager.get("appearance", "theme")
        return theme if theme else "light"
    except Exception:
        return "light"


@pages_bp.route("/")
def index() -> Response:
    # 云模式：未认证用户看到落地页
    deploy_mode = os.environ.get("KOTO_DEPLOY_MODE", "local")
    auth_enabled = os.environ.get("KOTO_AUTH_ENABLED", "false").lower() == "true"
    if deploy_mode == "cloud" and auth_enabled:
        return make_response(render_template("landing.html"))
    resp = make_response(render_template("index.html", initial_theme=_get_initial_theme()))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp

@pages_bp.route("/favicon.ico")
def favicon() -> Response:
    """Serve the Koto icon as favicon."""
    import os as _os
    static_dir = _os.path.join(_os.path.dirname(__file__), "..", "static", "assets")
    return send_from_directory(static_dir, "koto_icon.png", mimetype="image/png")


@pages_bp.route("/app")
def app_main() -> Response:
    """主应用页面（SaaS 模式下需认证后访问）"""
    resp = make_response(render_template("index.html", initial_theme=_get_initial_theme()))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


@pages_bp.route("/addons")
@pages_bp.route("/addon-center")
def addon_center() -> str:
    """Independent Add-on protocol, admission and runtime surface."""
    return render_template("addon_center.html")


@pages_bp.route("/mini")
def mini_page() -> str:
    """迷你模式页面（浏览器访问用）"""
    return render_template("mini_koto.html")
