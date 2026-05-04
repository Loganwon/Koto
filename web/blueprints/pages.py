# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
HTML page-rendering blueprint.

Routes:
  GET /                        — index
  GET /app                     — app_main
  GET /file-network            — file_network
  GET /knowledge-graph         — knowledge_graph_page
  GET /test_upload             — test_upload
  GET /skills                  — skill_marketplace
  GET /skill-marketplace       — skill_marketplace
  GET /monitoring-dashboard    — monitoring_dashboard
  GET /edit-ppt/<session_id>   — edit_ppt
  GET /mini                    — mini_page
  GET /m                       — mobile_page
  GET /mobile                  — mobile_page
  GET /notebook                — notebook_ui
    GET /workspace-assistant     — workspace_assistant_page
"""

import os

from flask import Blueprint, Response, make_response, render_template, send_from_directory

pages_bp = Blueprint("pages", __name__)


def _get_initial_theme() -> str:
    """从已保存的用户设置读取初始主题，默认 light。"""
    try:
        from web.app import settings_manager
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


@pages_bp.route("/app")
def app_main() -> Response:
    """主应用页面（SaaS 模式下需认证后访问）"""
    resp = make_response(render_template("index.html", initial_theme=_get_initial_theme()))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


@pages_bp.route("/file-network")
def file_network() -> str:
    """文件网络界面"""
    return render_template("file_network.html")


@pages_bp.route("/knowledge-graph")
def knowledge_graph_page() -> str:
    """知识图谱可视化界面"""
    return render_template("knowledge_graph.html")


@pages_bp.route("/test_upload")
def test_upload() -> str:
    return render_template("test_upload.html")


@pages_bp.route("/edit-ppt/<session_id>")
def edit_ppt(session_id: str) -> str:
    """PPT 生成后编辑页面（P1 功能）"""
    return render_template("edit_ppt.html")


@pages_bp.route("/pptx-editor/<file_id>")
def pptx_editor(file_id: str) -> str:
    """PPTX 文件编辑器 — 上传并编辑现有 PPTX 文件"""
    return render_template("pptx_editor.html")


@pages_bp.route("/skills")
@pages_bp.route("/skill-marketplace")
def skill_marketplace() -> str:
    """Koto Skill 库 — GitHub Extension Marketplace 风格管理界面"""
    return render_template("skill_marketplace.html")


@pages_bp.route("/skill-community")
def skill_community() -> str:
    """Koto Skill 社区 — 精选社区 Skills，一键安装"""
    return render_template("skill_community.html")


@pages_bp.route("/monitoring-dashboard")
def monitoring_dashboard() -> Response:
    """Phase 4 System Monitoring Dashboard"""
    return send_from_directory(
        os.path.join(os.path.dirname(__file__), os.pardir, "static"),
        "monitoring_dashboard.html",
    )


@pages_bp.route("/mini")
def mini_page() -> str:
    """迷你模式页面（浏览器访问用）"""
    return render_template("mini_koto.html")


@pages_bp.route("/m")
@pages_bp.route("/mobile")
def mobile_page() -> str:
    """移动端优化页面"""
    return render_template("mobile.html")


@pages_bp.route("/notebook")
def notebook_ui() -> str:
    """NotebookLM 风格界面"""
    return render_template("notebook_lm.html")


@pages_bp.route("/workspace-assistant")
def workspace_assistant_page() -> Response:
    """全格式 AI 原生工作区"""
    resp = make_response(render_template("workspace_assistant.html"))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


@pages_bp.route("/doc-compare")
def doc_compare_ui() -> str:
    """多文档对比界面"""
    return render_template("doc_compare.html")

