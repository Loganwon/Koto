# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
File organization, batch processing and utility routes blueprint.

Routes:
  POST   /api/batch/rename              — Batch rename files
  POST   /api/batch/convert             — Batch format conversion
  GET    /api/template/list             — List templates
  POST   /api/template/generate         — Generate document from template
  POST   /api/check/consistency         — Check document consistency
  POST   /api/compare/documents         — Compare two documents
  POST   /api/batch/submit              — Submit batch file processing job
  GET    /api/batch/jobs                — List batch jobs
  GET    /api/batch/jobs/<job_id>       — Get batch job details
  GET    /api/batch/stream/<job_id>     — Stream batch job progress
  POST   /api/organize/scan-file        — Scan and analyze a single file
  POST   /api/organize/auto-organize    — Auto-organize a file
  GET    /api/organize/list-categories  — List all categories and folders
  POST   /api/organize/search           — Search organized files
  GET    /api/organize/stats            — Get organization statistics
  POST   /api/organize/cleanup          — Cleanup duplicate folders
  GET    /api/files/download            — Download file proxy
  POST   /api/ocr/screenshot            — Screenshot and OCR
  POST   /api/ocr/clipboard             — Clipboard image OCR
  GET    /api/history/list              — List operation history
  POST   /api/history/rollback/<op_id>  — Rollback an operation
  GET    /api/history/stats             — Get history statistics
"""

import json
import logging
import os

from flask import Blueprint, Response, jsonify, request, send_file, stream_with_context

from web.runtime_context import service_registry

_logger = logging.getLogger("koto.routes.file_organize")

file_organize_bp = Blueprint("file_organize", __name__)


# ---------------------------------------------------------------------------
# Runtime helper
# ---------------------------------------------------------------------------


def _get_batch_ops_manager():
    return service_registry.batch_ops_manager


# ---------------------------------------------------------------------------
# Batch processing API
# ---------------------------------------------------------------------------


@file_organize_bp.route("/api/template/list", methods=["GET"])
def template_list() -> Response:
    """获取模板列表"""
    try:
        from web.tasks.template_library import TemplateLibrary

        library = TemplateLibrary()
        templates = library.list_templates()

        return jsonify({"success": True, "templates": templates})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# NOTE: /api/template/generate 已迁移至 web/blueprints/template_api.py（RAG 模板生成器），
# 此处移除旧实现避免路由遮蔽。内置模板列表保留在 /api/template/list。


# ---------------------------------------------------------------------------
# Consistency check API
# ---------------------------------------------------------------------------


@file_organize_bp.route("/api/check/consistency", methods=["POST"])
def check_consistency() -> Response:
    """检查文档一致性"""
    try:
        from web.files.consistency_checker import ConsistencyChecker

        data = request.json
        file_path = data.get("file_path")

        checker = ConsistencyChecker()
        result = checker.check_document(file_path)
        report = checker.generate_report(result)

        return jsonify({"success": True, "result": result, "report": report})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Document comparison API
# ---------------------------------------------------------------------------


@file_organize_bp.route("/api/files/download", methods=["GET"])
def download_file_proxy() -> Response:
    """通用的文件下载代理"""
    file_path = request.args.get("path")
    if not file_path or not os.path.isfile(file_path):
        return "File not found", 404
    try:
        return send_file(file_path, as_attachment=True)
    except FileNotFoundError:
        # The file can disappear between the existence check and opening it.
        return "File not found", 404


# ---------------------------------------------------------------------------
# Batch file operations (advanced)
# ---------------------------------------------------------------------------


@file_organize_bp.route("/api/batch/jobs", methods=["GET"])
def batch_list_jobs() -> Response:
    """列出批量任务"""
    manager = _get_batch_ops_manager()
    return jsonify({"success": True, "jobs": manager.list_jobs()})


@file_organize_bp.route("/api/batch/jobs/<job_id>", methods=["GET"])
def batch_get_job(job_id: str) -> Response:
    """获取单个任务详情"""
    manager = _get_batch_ops_manager()
    job = manager.get_job(job_id)
    if not job:
        return jsonify({"success": False, "error": "任务不存在"}), 404
    return jsonify({"success": True, "job": job})
