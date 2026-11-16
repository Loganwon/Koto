# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Template RAG API — 基于模板 + RAG 的文档自动生成
================================================

Routes:
  POST /api/template/generate  — 根据模板生成文档
  POST /api/template/preview   — 预览填充内容（不写文件）
  POST /api/template/placeholders — 提取模板占位符列表
"""

from __future__ import annotations

import logging
import os

from flask import Blueprint, Response, jsonify, request

logger = logging.getLogger("koto.routes.template")

template_bp = Blueprint("template", __name__)


def _get_workspace_dir():
    from web.runtime_context import service_registry
    return service_registry.workspace_dir


def _resolve_path(file_path: str) -> str:
    """将相对路径解析到工作区根目录（如 templates/xxx.docx）。"""
    if os.path.isabs(file_path):
        return file_path
    return os.path.join(_get_workspace_dir(), file_path)


# ── 生成文档 ────────────────────────────────────────────────────────────────

@template_bp.route("/api/template/generate", methods=["POST"])
def template_generate() -> Response:
    """
    根据模板 + RAG 知识库生成文档。

    请求体:
        {
            "template_path": "templates/report.docx",  // 模板路径
            "user_query": "生成2024年销售报告",         // 需求描述
            "output_path": "output/report_2024.docx",  // 可选，输出路径
            "rag_k": 8,                                // 可选，RAG 检索数量
            "extra_context": "额外上下文"               // 可选
        }

    返回:
        {
            "success": true,
            "output_path": "生成文件路径",
            "placeholders_filled": {"title": "...", ...},
            "rag_sources": ["file1.pdf", ...],
            "model_used": "qwen2.5:7b"
        }
    """
    try:
        data = request.get_json(silent=True) or {}
        template_path = str(data.get("template_path", "")).strip()
        user_query = str(data.get("user_query", "")).strip()

        if not template_path:
            return jsonify({"success": False, "error": "缺少 template_path 参数"}), 400
        if not user_query:
            return jsonify({"success": False, "error": "缺少 user_query 参数"}), 400

        template_path = _resolve_path(template_path)
        if not os.path.exists(template_path):
            return jsonify({"success": False, "error": f"模板不存在: {template_path}"}), 404

        output_path = str(data.get("output_path", "")).strip() or None
        if output_path:
            output_path = _resolve_path(output_path)

        rag_k = int(data.get("rag_k", 8))
        extra_context = str(data.get("extra_context", "")).strip() or None

        from app.core.services.template_rag_generator import TemplateRAGGenerator
        gen = TemplateRAGGenerator()

        result = gen.generate(
            template_path=template_path,
            user_query=user_query,
            output_path=output_path,
            rag_k=rag_k,
            extra_context=extra_context,
        )

        return jsonify(result)

    except Exception as exc:
        logger.error(f"[Template API] 生成失败: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


# ── 预览填充 ────────────────────────────────────────────────────────────────

@template_bp.route("/api/template/preview", methods=["POST"])
def template_preview() -> Response:
    """
    预览模板填充内容（不写入文件）。

    请求体:
        {
            "template_path": "templates/report.docx",
            "user_query": "生成2024年销售报告",
            "rag_k": 5
        }

    返回:
        {
            "success": true,
            "placeholders": ["title", "date", "content"],
            "filled": {"title": "...", "date": "...", "content": "..."},
            "rag_sources": ["file1.pdf"]
        }
    """
    try:
        data = request.get_json(silent=True) or {}
        template_path = str(data.get("template_path", "")).strip()
        user_query = str(data.get("user_query", "")).strip()

        if not template_path:
            return jsonify({"success": False, "error": "缺少 template_path 参数"}), 400
        if not user_query:
            return jsonify({"success": False, "error": "缺少 user_query 参数"}), 400

        template_path = _resolve_path(template_path)
        if not os.path.exists(template_path):
            return jsonify({"success": False, "error": f"模板不存在: {template_path}"}), 404

        rag_k = int(data.get("rag_k", 5))

        from app.core.services.template_rag_generator import TemplateRAGGenerator
        gen = TemplateRAGGenerator()
        result = gen.preview(
            template_path=template_path,
            user_query=user_query,
            rag_k=rag_k,
        )

        return jsonify(result)

    except Exception as exc:
        logger.error(f"[Template API] 预览失败: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


# ── 提取占位符 ──────────────────────────────────────────────────────────────

@template_bp.route("/api/template/placeholders", methods=["POST"])
def template_placeholders() -> Response:
    """
    提取模板中的所有占位符。

    请求体:
        { "template_path": "templates/report.docx" }

    返回:
        {
            "success": true,
            "template_path": "...",
            "placeholders": ["title", "date", "content"],
            "count": 3
        }
    """
    try:
        data = request.get_json(silent=True) or {}
        template_path = str(data.get("template_path", "")).strip()

        if not template_path:
            return jsonify({"success": False, "error": "缺少 template_path 参数"}), 400

        template_path = _resolve_path(template_path)
        if not os.path.exists(template_path):
            return jsonify({"success": False, "error": f"模板不存在: {template_path}"}), 404

        from pathlib import Path
        from app.core.services.template_rag_generator import TemplateRAGGenerator

        ext = Path(template_path).suffix.lower()
        gen = TemplateRAGGenerator()
        placeholders = gen._extract_placeholders(template_path, ext)

        return jsonify({
            "success": True,
            "template_path": template_path,
            "placeholders": placeholders,
            "count": len(placeholders),
        })

    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500
