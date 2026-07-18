# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
File-editor, file-search, scan, and concepts blueprint.

Routes:
  POST /api/file-editor/read          — Read file contents
  POST /api/file-editor/write         — Write file contents
  POST /api/file-editor/replace       — Replace text in file
  POST /api/file-editor/smart-edit    — Smart edit (natural language instruction)
  POST /api/file-search/index         — Index a file or directory
  POST /api/file-search/search        — Search indexed files
  POST /api/file-search/find-by-content — Find files by content similarity
  GET  /api/file-search/list          — List all indexed files
  POST /api/scan/start                — Start full disk scan (background thread)
  GET  /api/scan/status               — Scan progress and statistics
  POST /api/scan/search               — Fuzzy filename search across disk
  GET  /api/scan/stats                — Index statistics
  POST /api/concepts/extract          — Extract key concepts from a file
  POST /api/concepts/related-files    — Find related files by concepts
  GET  /api/concepts/top              — Get global top concepts
  GET  /api/concepts/stats            — Concept extraction statistics
"""

import logging

from flask import Blueprint, Response, jsonify, request

from web.runtime_services import (
    get_concept_extractor,
    get_file_editor,
    get_file_indexer,
)

_logger = logging.getLogger("koto.routes.file_editor")

file_editor_bp = Blueprint("file_editor", __name__)


# ── lazy imports ────────────────────────────────────────────


def _get_file_editor():
    return get_file_editor()


def _get_file_indexer():
    return get_file_indexer()


def _get_concept_extractor():
    return get_concept_extractor()


# ═══════════════════════════════════════════════════
# File editor routes
# ═══════════════════════════════════════════════════


@file_editor_bp.route("/api/file-editor/read", methods=["POST"])
def file_editor_read() -> Response:
    """读取文件内容"""
    try:
        data = request.json or {}
        file_path = data.get("file_path")

        if not file_path:
            return jsonify({"error": "缺少文件路径"}), 400

        editor = _get_file_editor()
        result = editor.read_file(file_path)

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@file_editor_bp.route("/api/file-editor/write", methods=["POST"])
def file_editor_write() -> Response:
    """写入文件内容"""
    try:
        data = request.json or {}
        file_path = data.get("file_path")
        content = data.get("content")

        if not file_path or content is None:
            return jsonify({"error": "缺少必要参数"}), 400

        editor = _get_file_editor()
        result = editor.write_file(file_path, content)

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@file_editor_bp.route("/api/file-editor/replace", methods=["POST"])
def file_editor_replace() -> Response:
    """替换文件内容"""
    try:
        data = request.json or {}
        file_path = data.get("file_path")
        old_text = data.get("old_text")
        new_text = data.get("new_text")
        use_regex = data.get("use_regex", False)

        if not all([file_path, old_text is not None, new_text is not None]):
            return jsonify({"error": "缺少必要参数"}), 400

        editor = _get_file_editor()
        result = editor.replace_text(file_path, old_text, new_text, use_regex=use_regex)

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@file_editor_bp.route("/api/file-editor/smart-edit", methods=["POST"])
def file_editor_smart_edit() -> Response:
    """智能编辑（理解自然语言指令）"""
    try:
        data = request.json or {}
        file_path = data.get("file_path")
        instruction = data.get("instruction")

        if not file_path or not instruction:
            return jsonify({"error": "缺少必要参数"}), 400

        editor = _get_file_editor()
        result = editor.smart_edit(file_path, instruction)

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════
# File search routes
# ═══════════════════════════════════════════════════


@file_editor_bp.route("/api/file-search/index", methods=["POST"])
def file_search_index() -> Response:
    """索引文件或目录"""
    try:
        data = request.json or {}
        path = data.get("path")
        is_directory = data.get("is_directory", False)

        if not path:
            return jsonify({"error": "缺少路径参数"}), 400

        indexer = _get_file_indexer()

        if is_directory:
            result = indexer.index_directory(path, recursive=True)
        else:
            result = indexer.index_file(path)

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@file_editor_bp.route("/api/file-search/search", methods=["POST"])
def file_search_search() -> Response:
    """搜索文件"""
    try:
        data = request.json or {}
        query = data.get("query")
        limit = data.get("limit", 20)
        file_types = data.get("file_types")

        if not query:
            return jsonify({"error": "缺少搜索关键词"}), 400

        indexer = _get_file_indexer()
        results = indexer.search(query, limit=limit, file_types=file_types)

        return jsonify({"success": True, "results": results, "count": len(results)})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@file_editor_bp.route("/api/file-search/find-by-content", methods=["POST"])
def file_search_find_by_content() -> Response:
    """根据内容片段查找文件"""
    try:
        data = request.json or {}
        content_sample = data.get("content")
        min_similarity = data.get("min_similarity", 0.3)

        if not content_sample:
            return jsonify({"error": "缺少内容样本"}), 400

        indexer = _get_file_indexer()
        results = indexer.find_by_content(content_sample, min_similarity=min_similarity)

        return jsonify({"success": True, "results": results, "count": len(results)})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@file_editor_bp.route("/api/file-search/list", methods=["GET"])
def file_search_list() -> Response:
    """列出所有已索引文件"""
    try:
        limit = request.args.get("limit", 100, type=int)
        offset = request.args.get("offset", 0, type=int)

        indexer = _get_file_indexer()
        files = indexer.list_indexed_files(limit=limit, offset=offset)

        return jsonify({"success": True, "files": files, "count": len(files)})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════
# 全盘文件扫描 API  (FileScanner)
# ═══════════════════════════════════════════════════


@file_editor_bp.route("/api/scan/start", methods=["POST"])
def scan_start() -> Response:
    """启动全盘文件扫描（后台线程）"""
    try:
        from web.file_scanner import FileScanner

        data = request.json or {}
        drives = data.get("drives")  # None → 自动枚举所有分区
        already = not FileScanner.start_scan(drives=drives)
        return jsonify(
            {
                "success": True,
                "already_running": already,
                "drives": drives or FileScanner.get_drives(),
                "message": (
                    "扫描已在进行中" if already else "全盘扫描已启动（后台运行）"
                ),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@file_editor_bp.route("/api/scan/status", methods=["GET"])
def scan_status() -> Response:
    """返回扫描进度和统计"""
    try:
        from web.file_scanner import FileScanner

        return jsonify(
            {
                "success": True,
                **FileScanner.get_status(),
                "indexed_count": FileScanner.stats()["total"],
                "by_category": FileScanner.stats()["by_category"],
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@file_editor_bp.route("/api/scan/search", methods=["POST"])
def scan_search() -> Response:
    """全盘文件名模糊搜索"""
    try:
        from web.file_scanner import FileScanner

        data = request.json or {}
        query = (data.get("query") or "").strip()
        limit = int(data.get("limit", 12))
        ext_filter = data.get("ext_filter")  # ['.docx', ...] or None
        category_filter = data.get("category")  # '文档' / '图片' / ... or None
        if not query:
            return jsonify({"success": False, "error": "缺少 query 参数"}), 400
        FileScanner.ensure_loaded()
        results = FileScanner.search(
            query, limit=limit, ext_filter=ext_filter, category_filter=category_filter
        )
        return jsonify({"success": True, "results": results, "count": len(results)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@file_editor_bp.route("/api/scan/stats", methods=["GET"])
def scan_stats() -> Response:
    """索引统计数据"""
    try:
        from web.file_scanner import FileScanner

        return jsonify({"success": True, **FileScanner.stats()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════
# 概念提取 API
# ═══════════════════════════════════════════════════


@file_editor_bp.route("/api/concepts/extract", methods=["POST"])
def concepts_extract() -> Response:
    """从文件中提取关键概念"""
    try:
        data = request.json or {}
        file_path = data.get("file_path")
        content = data.get("content")  # 可选，如果已读取内容
        top_n = data.get("top_n", 10)

        if not file_path:
            return jsonify({"error": "缺少文件路径"}), 400

        extractor = _get_concept_extractor()
        result = extractor.analyze_file(file_path, content=content)

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@file_editor_bp.route("/api/concepts/related-files", methods=["POST"])
def concepts_related_files() -> Response:
    """查找与文件相关的其他文件"""
    try:
        data = request.json or {}
        file_path = data.get("file_path")
        limit = data.get("limit", 5)

        if not file_path:
            return jsonify({"error": "缺少文件路径"}), 400

        extractor = _get_concept_extractor()
        related = extractor.find_related_files(file_path, limit=limit)

        return jsonify(
            {"success": True, "file_path": file_path, "related_files": related}
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@file_editor_bp.route("/api/concepts/top", methods=["GET"])
def concepts_top() -> Response:
    """获取全局热门概念"""
    try:
        limit = request.args.get("limit", 20, type=int)

        extractor = _get_concept_extractor()
        concepts = extractor.get_top_concepts(limit=limit)

        return jsonify({"success": True, "concepts": concepts})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@file_editor_bp.route("/api/concepts/stats", methods=["GET"])
def concepts_stats() -> Response:
    """获取概念提取统计"""
    try:
        extractor = _get_concept_extractor()
        stats = extractor.get_statistics()

        return jsonify(stats)

    except Exception as e:
        return jsonify({"error": str(e)}), 500
