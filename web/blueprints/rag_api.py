# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
RAG API Blueprint — 文件知识库检索与索引管理
============================================

Routes:
  POST /api/rag/search          — 混合检索（向量 + BM25）
  GET  /api/rag/index-status    — 索引状态查询
  POST /api/rag/reindex         — 全量重建索引
  POST /api/rag/index-file      — 索引单个文件
  POST /api/rag/index-directory — 索引目录下所有文件
  GET  /api/rag/indexed-files   — 已索引文件列表
  POST /api/rag/start-watcher   — 启动文件监控
  POST /api/rag/stop-watcher    — 停止文件监控
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Blueprint, Response, jsonify, request

logger = logging.getLogger("koto.routes.rag")

rag_bp = Blueprint("rag", __name__)

def _get_indexer():
    from app.core.services.file_rag_indexer import get_file_rag_indexer

    return get_file_rag_indexer()


def _get_rag():
    from app.core.services.rag_service import get_rag_service
    return get_rag_service()


def _get_workspace_dir():
    from web.runtime_context import service_registry
    return service_registry.workspace_dir


# ── 搜索 ────────────────────────────────────────────────────────────────────

@rag_bp.route("/api/rag/search", methods=["POST"])
def rag_search() -> Response:
    """
    混合检索知识库。

    请求体:
        {
            "query": "查询文本",
            "k": 5,                    // 返回数量，默认 5
            "score_threshold": 0.3,    // 最低分数阈值，默认 0.3
            "bm25_weight": 0.3         // BM25 权重 0-1，默认 0.3
        }

    返回:
        {
            "success": true,
            "results": [
                {
                    "content": "文本片段",
                    "source": "文件路径",
                    "score": 0.85,
                    "chunk_index": 0
                }
            ],
            "count": 5,
            "index_stats": {...}
        }
    """
    try:
        data = request.get_json(silent=True) or {}
        query = str(data.get("query", "")).strip()
        if not query:
            return jsonify({"success": False, "error": "缺少 query 参数"}), 400

        k = max(1, min(int(data.get("k", 5)), 50))
        score_threshold = float(data.get("score_threshold", 0.3))
        bm25_weight = float(data.get("bm25_weight", 0.3))

        rag = _get_rag()
        results = rag.hybrid_retrieve(
            query, k=k, score_threshold=score_threshold, bm25_weight=bm25_weight
        )

        return jsonify({
            "success": True,
            "results": results,
            "count": len(results),
            "index_stats": rag.stats(),
        })

    except Exception as exc:
        logger.error(f"[RAG API] 搜索失败: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


# ── 索引状态 ────────────────────────────────────────────────────────────────

@rag_bp.route("/api/rag/index-status", methods=["GET"])
def rag_index_status() -> Response:
    """获取 RAG 索引状态。"""
    try:
        rag = _get_rag()
        indexer = _get_indexer()
        return jsonify({
            "success": True,
            "rag": rag.stats(),
            "indexer": indexer.get_status(),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


# ── 全量重建索引 ────────────────────────────────────────────────────────────

@rag_bp.route("/api/rag/reindex", methods=["POST"])
def rag_reindex() -> Response:
    """全量重建索引（清空 + 重新扫描）。"""
    try:
        indexer = _get_indexer()
        result = indexer.reindex_all()
        return jsonify({
            "success": True,
            **result,
        })
    except Exception as exc:
        logger.error(f"[RAG API] 重建索引失败: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


# ── 索引单个文件 ────────────────────────────────────────────────────────────

@rag_bp.route("/api/rag/index-file", methods=["POST"])
def rag_index_file() -> Response:
    """
    索引单个文件。

    请求体:
        {
            "file_path": "路径"        // 绝对路径或相对于 workspace/documents 的路径
        }
    """
    try:
        data = request.get_json(silent=True) or {}
        file_path = str(data.get("file_path", "")).strip()
        if not file_path:
            return jsonify({"success": False, "error": "缺少 file_path 参数"}), 400

        # 解析相对路径
        if not os.path.isabs(file_path):
            workspace_dir = _get_workspace_dir()
            file_path = os.path.join(workspace_dir, "documents", file_path)

        if not os.path.exists(file_path):
            return jsonify({"success": False, "error": f"文件不存在: {file_path}"}), 404

        count = _get_indexer().index_file(file_path)
        return jsonify({
            "success": count >= 0,
            "file_path": file_path,
            "chunks": count,
        })

    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


# ── 索引目录 ────────────────────────────────────────────────────────────────

@rag_bp.route("/api/rag/index-directory", methods=["POST"])
def rag_index_directory() -> Response:
    """
    索引目录下所有支持的文件。

    请求体:
        {
            "dir_path": "目录路径",
            "extensions": [".pdf", ".docx"]  // 可选，限制扩展名
        }
    """
    try:
        data = request.get_json(silent=True) or {}
        dir_path = str(data.get("dir_path", "")).strip()
        if not dir_path:
            return jsonify({"success": False, "error": "缺少 dir_path 参数"}), 400

        if not os.path.isdir(dir_path):
            return jsonify({"success": False, "error": f"目录不存在: {dir_path}"}), 404

        rag = _get_rag()
        extensions = data.get("extensions")
        result = rag.index_directory(dir_path, extensions=extensions)

        return jsonify({
            "success": True,
            "results": result,
            "total_files": len(result),
            "total_chunks": sum(c for c in result.values() if c > 0),
        })

    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


# ── 已索引文件列表 ───────────────────────────────────────────────────────────

@rag_bp.route("/api/rag/indexed-files", methods=["GET"])
def rag_indexed_files() -> Response:
    """获取已索引文件列表。"""
    try:
        indexer = _get_indexer()
        return jsonify({
            "success": True,
            "files": indexer.get_indexed_files(),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500






# ── Model Config ─────────────────────────────────────────────────────────

@rag_bp.route("/api/rag/model-config", methods=["GET"])
def rag_model_config() -> Response:
    try:
        from app.core.llm.model_config import (
            get_chat_model, get_embed_model, get_model_mode, is_local_mode,
        )
        return jsonify({
            "success": True,
            "mode": get_model_mode(),
            "is_local": is_local_mode(),
            "chat_model": get_chat_model(),
            "embed_model": get_embed_model(),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@rag_bp.route("/api/rag/model-config", methods=["PUT"])
def rag_model_config_update() -> Response:
    try:
        data = request.get_json(silent=True) or {}
        from app.core.config.user_settings import SettingsManager
        sm = SettingsManager()
        current = sm.get_all()

        if "embed_model" in data:
            current["local_embed_model"] = str(data["embed_model"]).strip()
            if "ai" not in current:
                current["ai"] = {}
            current["ai"]["local_embed_model"] = current["local_embed_model"]

        if "chat_model" in data:
            current["local_model"] = str(data["chat_model"]).strip()
            if "ai" in current:
                current["ai"]["local_model"] = current["local_model"]

        if "model_mode" in data:
            new_mode = str(data["model_mode"]).strip()
            current["model_mode"] = new_mode
            # Keep ai.use_local_only in sync with the canonical model_mode
            if "ai" not in current:
                current["ai"] = {}
            current["ai"]["use_local_only"] = new_mode == "local"

        sm.patch(current)

        # Reset RAG embeddings so the new embed model takes effect
        from app.core.services.rag_service import reset_rag_service
        reset_rag_service()

        from app.core.llm.model_config import (
            get_chat_model, get_embed_model, get_model_mode,
        )
        return jsonify({
            "success": True,
            "mode": get_model_mode(),
            "chat_model": get_chat_model(),
            "embed_model": get_embed_model(),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500

# ── KB Config ────────────────────────────────────────────────────────────

@rag_bp.route("/api/rag/kb-status", methods=["GET"])
def rag_kb_status() -> Response:
    try:
        from app.core.services.kb_config import KBConfig
        kb = KBConfig()
        return jsonify({"success": True, **kb.get_status()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@rag_bp.route("/api/rag/kb-set-root", methods=["POST"])
def rag_kb_set_root() -> Response:
    try:
        data = request.get_json(silent=True) or {}
        root_dir = str(data.get("root_dir", "")).strip()
        if not root_dir:
            return jsonify({"success": False, "error": "missing root_dir"}), 400

        from app.core.services.kb_config import KBConfig
        kb = KBConfig()
        ok = kb.set_root(root_dir)
        if not ok:
            return jsonify({"success": False, "error": f"invalid dir: {root_dir}"}), 400

        from app.core.services.file_rag_indexer import get_file_rag_indexer

        indexer = get_file_rag_indexer(watch_dir=root_dir)
        result = indexer.scan_and_index()
        return jsonify({
            "success": True,
            "root_dir": root_dir,
            "index_result": result,
            "message": "KB ready. You can now search or start auto-watcher.",
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@rag_bp.route("/api/rag/ollama-check", methods=["GET"])
def rag_ollama_check() -> Response:
    try:
        from app.core.services.kb_config import _check_ollama
        result = _check_ollama()
        return jsonify({"success": True, **result})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500

# ── 文件监控控制 ────────────────────────────────────────────────────────────

@rag_bp.route("/api/rag/start-watcher", methods=["POST"])
def rag_start_watcher() -> Response:
    """启动文件变更监控。"""
    try:
        data = request.get_json(silent=True) or {}
        interval = max(5, int(data.get("interval", 30)))
        indexer = _get_indexer()
        indexer.start_watching(interval=interval)
        return jsonify({
            "success": True,
            "message": f"文件监控已启动 (间隔={interval}s)",
            "status": indexer.get_status(),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@rag_bp.route("/api/rag/stop-watcher", methods=["POST"])
def rag_stop_watcher() -> Response:
    """停止文件变更监控。"""
    try:
        indexer = _get_indexer()
        indexer.stop_watching()
        return jsonify({
            "success": True,
            "message": "文件监控已停止",
            "status": indexer.get_status(),
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500
