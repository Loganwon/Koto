# ══════════════════════════════════════════════════════════════
# workflow_api.py — 工作流 Skill 统一 API 端点
#
# 蓝图路由:
#   GET  /api/workflow/list     — 返回所有可用工作流描述
#   POST /api/workflow/execute  — 执行工作流（SSE 流式响应）
#   POST /api/workflow/upload   — 上传工作流输入文件（返回临时路径）
# ══════════════════════════════════════════════════════════════

from __future__ import annotations

from flask import Blueprint, Response, jsonify, request, send_file, stream_with_context

from app.core.workflows.catalog import list_workflow_definitions
from app.core.workflows.execution import (
    WorkflowExecutionError,
    iter_workflow_events,
    prepare_workflow_execution,
)
from app.core.workflows.file_store import (
    WorkflowFileAccessError,
    save_workflow_uploads,
    validate_workflow_download_path,
)

workflow_bp = Blueprint("workflow", __name__)

# Workflow metadata is owned by app.core.workflows.catalog.


@workflow_bp.route("/api/workflow/list", methods=["GET"])
def workflow_list():
    """返回所有可用工作流的描述信息。"""
    return jsonify({
        "success": True,
        "workflows": list_workflow_definitions(),
    })


@workflow_bp.route("/api/workflow/execute", methods=["POST"])
def workflow_execute():
    """
    执行工作流，返回 SSE 流式响应。

    Request JSON:
    {
        "workflow_id": "cross_format_extractor",
        "params": {
            "source_files": ["/tmp/abc/file1.pdf", ...],
            "template_file": "/tmp/abc/template.xlsx",
            ...
        }
    }

    SSE events: status | progress | step_start | step_done | code |
                output | diff | error | done
    """
    data = request.get_json(silent=True) or {}
    workflow_id = (data.get("workflow_id") or "").strip()
    params = data.get("params") or {}

    try:
        execution_plan = prepare_workflow_execution(workflow_id)
    except WorkflowExecutionError as exc:
        return jsonify({"success": False, "error": str(exc)}), exc.status_code

    def generate():
        yield from iter_workflow_events(execution_plan, params)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@workflow_bp.route("/api/workflow/upload", methods=["POST"])
def workflow_upload():
    """
    上传工作流输入文件到临时目录，返回文件路径供后续 execute 调用。

    支持多文件上传（multipart/form-data, 字段名 files[]）。
    返回: {"success": True, "paths": ["/tmp/koto_wf_xxx/file.pdf", ...]}
    """
    uploaded_files = request.files.getlist("files[]") or request.files.getlist("file")
    if not uploaded_files:
        return jsonify({"success": False, "error": "没有收到文件"}), 400

    upload_result = save_workflow_uploads(
        uploaded_files,
        session_id=request.form.get("session_id"),
    )

    return jsonify({
        "success": True,
        "paths": upload_result.paths,
        "session_id": upload_result.session_id,
    })


@workflow_bp.route("/api/workflow/download", methods=["GET"])
def workflow_download():
    """
    下载工作流产出文件（docx/pptx/xlsx 等）。

    Query params:
        path — 临时目录中的文件绝对路径
    """
    try:
        resolved = validate_workflow_download_path(request.args.get("path", ""))
    except WorkflowFileAccessError as exc:
        return jsonify({"error": str(exc)}), exc.status_code

    return send_file(
        str(resolved),
        as_attachment=True,
        download_name=resolved.name,
    )
