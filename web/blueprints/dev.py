# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Dev / debug and RAG blueprint.

Routes:
  GET    /workflow-dag                                   — Workflow DAG visualization page
  GET    /api/dev/graph-mermaid                          — Mermaid DAG markup for a workflow/agent
  GET    /api/dev/checkpoint-info                        — Checkpoint DB info
  GET    /api/dev/checkpoints/<thread_id>                — List checkpoints for a thread
  DELETE /api/dev/checkpoints/<thread_id>                — Delete all checkpoints for a thread
  POST   /api/rag/ingest                                 — Index file or text into vector store
  POST   /api/rag/query                                  — Retrieve relevant chunks (optionally with LLM answer)
  GET    /api/rag/stats                                  — RAG index statistics
  DELETE /api/rag/clear                                  — Clear the entire RAG vector store
  GET    /api/auto-catalog/status                        — Auto-catalog scheduler status
  POST   /api/auto-catalog/enable                        — Enable auto-catalog
  POST   /api/auto-catalog/disable                       — Disable auto-catalog
  POST   /api/auto-catalog/run-now                       — Trigger a manual catalog run
  GET    /api/auto-catalog/backup-manifest/<filename>    — Download a backup manifest file
"""

import logging
import os

from flask import Blueprint, Response, jsonify, request, send_file, send_from_directory

from web.auth import require_auth

_logger = logging.getLogger("koto.routes.dev")

dev_bp = Blueprint("dev", __name__)


# ── Auto-catalog routes ───────────────────────────────────────────────────────


@dev_bp.route("/api/auto-catalog/status", methods=["GET"])
@require_auth
def auto_catalog_status() -> Response:
    """获取自动归纳状态"""
    try:
        from web.auto_catalog_scheduler import get_auto_catalog_scheduler

        scheduler = get_auto_catalog_scheduler()

        return jsonify(
            {
                "success": True,
                "enabled": scheduler.is_auto_catalog_enabled(),
                "schedule_time": scheduler.get_catalog_schedule(),
                "source_directories": scheduler.get_source_directories(),
                "backup_directory": scheduler.get_backup_directory(),
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@dev_bp.route("/api/auto-catalog/enable", methods=["POST"])
@require_auth
def auto_catalog_enable() -> Response:
    """启用自动归纳"""
    try:
        from web.auto_catalog_scheduler import get_auto_catalog_scheduler

        scheduler = get_auto_catalog_scheduler()

        data = request.json or {}
        schedule_time = data.get("schedule_time", "02:00")
        source_dirs = data.get("source_directories")

        scheduler.enable_auto_catalog(schedule_time, source_dirs)

        return jsonify(
            {
                "success": True,
                "message": f"自动归纳已启用，每日 {schedule_time} 执行",
                "schedule_time": schedule_time,
                "source_directories": scheduler.get_source_directories(),
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@dev_bp.route("/api/auto-catalog/disable", methods=["POST"])
@require_auth
def auto_catalog_disable() -> Response:
    """禁用自动归纳"""
    try:
        from web.auto_catalog_scheduler import get_auto_catalog_scheduler

        scheduler = get_auto_catalog_scheduler()

        scheduler.disable_auto_catalog()

        return jsonify({"success": True, "message": "自动归纳已禁用"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dev_bp.route("/api/auto-catalog/run-now", methods=["POST"])
@require_auth
def auto_catalog_run_now() -> Response:
    """立即执行一次归纳（手动触发）"""
    try:
        from web.auto_catalog_scheduler import get_auto_catalog_scheduler

        scheduler = get_auto_catalog_scheduler()

        result = scheduler.manual_catalog_now()

        return jsonify(
            {
                "success": result.get("success", False),
                "total_files": result.get("total_files", 0),
                "organized_count": result.get("organized_count", 0),
                "backed_up_count": result.get("backed_up_count", 0),
                "errors": result.get("errors", []),
                "report_path": result.get("report_path", ""),
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dev_bp.route("/api/auto-catalog/backup-manifest/<path:filename>", methods=["GET"])
@require_auth
def get_backup_manifest(filename: str) -> Response:
    """下载备份清单文件"""
    try:
        from web.auto_catalog_scheduler import get_auto_catalog_scheduler

        scheduler = get_auto_catalog_scheduler()

        backup_dir = scheduler.get_backup_directory()
        return send_from_directory(backup_dir, filename, as_attachment=False)
    except Exception as e:
        return jsonify({"error": str(e)}), 404


# ── LangGraph workflow visualization & dev tools ──────────────────────────────


@dev_bp.route("/workflow-dag")
@require_auth
def workflow_dag_page() -> Response:
    """工作流 DAG 可视化页面"""
    html_path = os.path.join(
        os.path.dirname(__file__), os.pardir, "static", "workflow_dag.html"
    )
    try:
        return send_file(html_path)
    except Exception as e:
        return f"<h3>Error: {e}</h3>", 500


@dev_bp.route("/api/dev/graph-mermaid", methods=["GET"])
@require_auth
def api_dev_graph_mermaid() -> Response:
    """
    返回指定工作流 / Agent 的 Mermaid DAG 图标记。

    参数:
        workflow : 工作流名称  (research_and_document | multi_agent_ppt | react_agent)
        type     : 类型        (workflow | agent)
    """
    wf = request.args.get("workflow", "react_agent")
    wf_type = request.args.get("type", "agent")
    try:
        if wf_type == "agent" or wf == "react_agent":
            from app.core.agent.factory import create_langgraph_agent

            agent = create_langgraph_agent()
            mermaid_code = agent.get_graph_mermaid()
            node_count = mermaid_code.count("\n    ") if mermaid_code else 0
            edge_count = (
                mermaid_code.count("-->") + mermaid_code.count("-.->")
                if mermaid_code
                else 0
            )
        else:
            from app.core.workflow.langgraph_workflow import WorkflowEngine

            engine = WorkflowEngine()
            mermaid_code = engine.get_graph_mermaid(wf)
            node_count = mermaid_code.count("\n    ") if mermaid_code else 0
            edge_count = (
                mermaid_code.count("-->") + mermaid_code.count("-.->")
                if mermaid_code
                else 0
            )

        return jsonify(
            {
                "success": True,
                "workflow": wf,
                "type": wf_type,
                "mermaid": mermaid_code,
                "node_count": max(node_count, 0),
                "edge_count": max(edge_count, 0),
            }
        )
    except Exception as e:
        import traceback

        return (
            jsonify(
                {"success": False, "error": str(e), "traceback": traceback.format_exc()}
            ),
            500,
        )


@dev_bp.route("/api/dev/checkpoint-info", methods=["GET"])
@require_auth
def api_dev_checkpoint_info() -> Response:
    """返回检查点数据库信息（类型 / 会话数 / 快照总数）。"""
    try:
        from app.core.agent.checkpoint_manager import CheckpointManager

        return jsonify(CheckpointManager.get_db_info())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dev_bp.route("/api/dev/checkpoints/<thread_id>", methods=["GET"])
@require_auth
def api_dev_list_checkpoints(thread_id: str) -> Response:
    """列出某会话的检查点快照列表。"""
    try:
        from app.core.agent.checkpoint_manager import CheckpointManager

        snapshots = CheckpointManager.list_checkpoints(thread_id)
        return jsonify(
            {"thread_id": thread_id, "snapshots": snapshots, "count": len(snapshots)}
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dev_bp.route("/api/dev/checkpoints/<thread_id>", methods=["DELETE"])
@require_auth
def api_dev_delete_checkpoints(thread_id: str) -> Response:
    """删除某会话的全部检查点（用于清除对话历史）。"""
    try:
        from app.core.agent.checkpoint_manager import CheckpointManager

        ok = CheckpointManager.delete_thread(thread_id)
        return jsonify({"success": ok, "thread_id": thread_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── RAG vector retrieval API ─────────────────────────────────────────────────


@dev_bp.route("/api/rag/ingest", methods=["POST"])
@require_auth
def api_rag_ingest() -> Response:
    """
    索引文件或文本到向量库。

    请求体 (JSON):
        { "file_path": "/abs/path/to/doc.pdf" }
        或
        { "text": "要索引的文本内容...", "source": "my_doc" }

    返回:
        { "success": true, "chunks_added": 42, "stats": {...} }
    """
    try:
        from app.core.services.rag_service import get_rag_service

        data = request.get_json(force=True) or {}
        rag = get_rag_service()

        if "file_path" in data:
            fp = data["file_path"]
            if not os.path.isabs(fp):
                fp = os.path.join(os.getcwd(), fp)
            if not os.path.exists(fp):
                return jsonify({"error": f"文件不存在: {fp}"}), 400
            count = rag.index_file(fp)
        elif "text" in data:
            count = rag.index_text(data["text"], source=data.get("source", "api_input"))
        else:
            return jsonify({"error": "请提供 file_path 或 text 字段"}), 400

        return jsonify({"success": True, "chunks_added": count, "stats": rag.stats()})
    except Exception as e:
        _logger.exception("[RAG /ingest] error")
        return jsonify({"error": str(e)}), 500


@dev_bp.route("/api/rag/query", methods=["POST"])
@require_auth
def api_rag_query() -> Response:
    """
    检索向量库，返回相关文本片段。

    请求体 (JSON):
        {
          "question": "Koto 支持哪些文件格式？",
          "k": 5,
          "answer": true        // 可选：true = 同时生成 LLM 答案
        }

    返回（仅检索）:
        { "chunks": [...], "count": 3 }

    返回（含答案）:
        { "answer": "...", "sources": [...], "chunks": [...], "context_used": true }
    """
    try:
        from app.core.services.rag_service import get_rag_service

        data = request.get_json(force=True) or {}
        question = data.get("question", "").strip()
        if not question:
            return jsonify({"error": "question 字段不能为空"}), 400

        k = int(data.get("k", 5))
        want_answer = data.get("answer", False)
        rag = get_rag_service()

        if want_answer:
            result = rag.rag_answer(question, k=k)
            return jsonify(result)
        else:
            chunks = rag.retrieve(question, k=k)
            return jsonify({"chunks": chunks, "count": len(chunks)})
    except Exception as e:
        _logger.exception("[RAG /query] error")
        return jsonify({"error": str(e)}), 500


@dev_bp.route("/api/rag/stats", methods=["GET"])
@require_auth
def api_rag_stats() -> Response:
    """
    返回 RAG 索引统计信息。

    返回:
        {
          "initialized": true,
          "doc_count": 312,
          "index_dir": "config/rag_index",
          "index_size_mb": 2.4,
          "embedding_model": "GoogleGenerativeAIEmbeddings"
        }
    """
    try:
        from app.core.services.rag_service import get_rag_service

        rag = get_rag_service()
        return jsonify(rag.stats())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dev_bp.route("/api/rag/clear", methods=["DELETE"])
@require_auth
def api_rag_clear() -> Response:
    """清空 RAG 向量库（删除所有索引数据）。"""
    try:
        import app.core.services.rag_service as _rag_mod
        from app.core.services.rag_service import get_rag_service

        rag = get_rag_service()
        ok = rag.clear()
        # 重置单例，下次 get_rag_service() 将重建
        _rag_mod._rag_instance = None
        return jsonify({"success": ok, "message": "向量库已清空"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
