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

from web.runtime_services import (
    get_batch_ops_manager,
    get_file_analyzer,
    get_file_organizer,
    get_organize_root,
)

_logger = logging.getLogger("koto.routes.file_organize")

file_organize_bp = Blueprint("file_organize", __name__)


# ---------------------------------------------------------------------------
# Lazy helpers – break circular imports with web.app
# ---------------------------------------------------------------------------


def _get_file_organizer():
    return get_file_organizer()


def _get_file_analyzer():
    return get_file_analyzer()


def _get_batch_ops_manager():
    return get_batch_ops_manager()


def _get_organize_root():
    return get_organize_root()


# ---------------------------------------------------------------------------
# Batch processing API
# ---------------------------------------------------------------------------


@file_organize_bp.route("/api/batch/rename", methods=["POST"])
def batch_rename() -> Response:
    """批量重命名文件"""
    try:
        from web.batch_processor import BatchFileProcessor

        data = request.json
        directory = data.get("directory")
        pattern = data.get("pattern")

        processor = BatchFileProcessor()
        result = processor.batch_rename(directory, **pattern)

        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@file_organize_bp.route("/api/batch/convert", methods=["POST"])
def batch_convert() -> Response:
    """批量格式转换"""
    try:
        from web.batch_processor import BatchFileProcessor

        data = request.json
        directory = data.get("directory")
        from_format = data.get("from_format")
        to_format = data.get("to_format")

        processor = BatchFileProcessor()
        result = processor.batch_convert(directory, from_format, to_format)

        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Template API
# ---------------------------------------------------------------------------


@file_organize_bp.route("/api/template/list", methods=["GET"])
def template_list() -> Response:
    """获取模板列表"""
    try:
        from web.template_library import TemplateLibrary

        library = TemplateLibrary()
        templates = library.list_templates()

        return jsonify({"success": True, "templates": templates})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@file_organize_bp.route("/api/template/generate", methods=["POST"])
def template_generate() -> Response:
    """从模板生成文档"""
    try:
        from web.template_library import TemplateLibrary

        data = request.json
        template_name = data.get("template_id") or data.get("template_name")
        variables = data.get("variables", {})
        output_dir = data.get("output_dir")
        output_file = data.get("output_file")
        if output_file and not output_dir:
            if os.path.isdir(output_file):
                output_dir = output_file
            else:
                output_dir = os.path.dirname(output_file) or None

        library = TemplateLibrary()
        result = library.generate_from_template(template_name, variables, output_dir)

        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Consistency check API
# ---------------------------------------------------------------------------


@file_organize_bp.route("/api/check/consistency", methods=["POST"])
def check_consistency() -> Response:
    """检查文档一致性"""
    try:
        from web.consistency_checker import ConsistencyChecker

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


@file_organize_bp.route("/api/compare/documents", methods=["POST"])
def compare_documents() -> Response:
    """对比文档"""
    try:
        from web.document_comparator import DocumentComparator

        data = request.json
        file_a = data.get("file_a")
        file_b = data.get("file_b")
        output_format = data.get("output_format", "markdown")

        comparator = DocumentComparator()
        result = comparator.compare_documents(file_a, file_b, output_format)

        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# OCR assistant API
# ---------------------------------------------------------------------------


@file_organize_bp.route("/api/ocr/screenshot", methods=["POST"])
def ocr_screenshot() -> Response:
    """截图并OCR"""
    try:
        from web.clipboard_ocr_assistant import ClipboardOCRAssistant

        data = request.json
        save_image = data.get("save_image", True)
        auto_index = data.get("auto_index", False)

        assistant = ClipboardOCRAssistant()
        result = assistant.capture_and_ocr(source="screenshot", save_image=save_image)

        if auto_index and result.get("ocr_success"):
            assistant.auto_index_to_knowledge_base(result)

        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@file_organize_bp.route("/api/ocr/clipboard", methods=["POST"])
def ocr_clipboard() -> Response:
    """剪贴板图片OCR"""
    try:
        from web.clipboard_ocr_assistant import ClipboardOCRAssistant

        data = request.json
        save_image = data.get("save_image", True)
        auto_index = data.get("auto_index", False)

        assistant = ClipboardOCRAssistant()
        result = assistant.capture_and_ocr(source="clipboard", save_image=save_image)

        if auto_index and result.get("ocr_success"):
            assistant.auto_index_to_knowledge_base(result)

        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Operation history API
# ---------------------------------------------------------------------------


@file_organize_bp.route("/api/history/list", methods=["GET"])
def history_list() -> Response:
    """获取操作历史"""
    try:
        from web.operation_history import OperationHistory

        limit = request.args.get("limit", 50, type=int)
        file_path = request.args.get("file_path")

        history = OperationHistory()
        operations = history.get_history(limit=limit, file_path=file_path)

        return jsonify({"success": True, "operations": operations})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@file_organize_bp.route("/api/history/rollback/<op_id>", methods=["POST"])
def history_rollback(op_id: str) -> Response:
    """回滚操作"""
    try:
        from web.operation_history import OperationHistory

        history = OperationHistory()
        result = history.rollback(op_id)

        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@file_organize_bp.route("/api/history/stats", methods=["GET"])
def history_stats() -> Response:
    """获取历史统计"""
    try:
        from web.operation_history import OperationHistory

        history = OperationHistory()
        stats = history.get_statistics()

        return jsonify({"success": True, "stats": stats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# File download proxy
# ---------------------------------------------------------------------------


@file_organize_bp.route("/api/files/download", methods=["GET"])
def download_file_proxy() -> Response:
    """通用的文件下载代理"""
    file_path = request.args.get("path")
    if not file_path or not os.path.exists(file_path):
        return "File not found", 404
    return send_file(file_path, as_attachment=True)


# ---------------------------------------------------------------------------
# Batch file operations (advanced)
# ---------------------------------------------------------------------------


@file_organize_bp.route("/api/batch/submit", methods=["POST"])
def batch_submit() -> Response:
    """提交批量文件处理任务"""
    try:
        data = request.json or {}
        command = data.get("command", "")
        manager = _get_batch_ops_manager()

        if command:
            parsed = manager.parse_command(command)
            if not parsed.get("success"):
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": parsed.get("error"),
                            "hint": parsed.get("hint"),
                        }
                    ),
                    400,
                )
            operation = parsed.get("operation")
            input_dir = parsed.get("input_dir")
            output_dir = parsed.get("output_dir")
            options = parsed.get("options", {})
        else:
            operation = data.get("operation")
            input_dir = data.get("input_dir")
            output_dir = data.get("output_dir")
            options = data.get("options", {})

        if not operation or not input_dir or not output_dir:
            return jsonify({"success": False, "error": "缺少必要参数"}), 400

        job = manager.create_job(
            name=f"batch_{operation}",
            operation=operation,
            input_dir=input_dir,
            output_dir=output_dir,
            options=options,
        )
        manager.start_job(job.job_id)
        return jsonify(
            {"success": True, "job_id": job.job_id, "job": manager.get_job(job.job_id)}
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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


@file_organize_bp.route("/api/batch/stream/<job_id>", methods=["GET"])
def batch_stream_job(job_id: str) -> Response:
    """批量任务进度流"""
    manager = _get_batch_ops_manager()
    return Response(manager.stream_job(job_id), mimetype="text/event-stream")


# ---------------------------------------------------------------------------
# File organization API
# ---------------------------------------------------------------------------


@file_organize_bp.route("/api/organize/scan-file", methods=["POST"])
def organize_scan_file() -> Response:
    """扫描和分析单个文件"""
    try:
        data = request.json
        file_path = data.get("file_path")

        if not file_path:
            return jsonify({"error": "缺少 file_path 参数"}), 400

        if not os.path.exists(file_path):
            return jsonify({"error": f"文件不存在: {file_path}"}), 404

        analyzer = _get_file_analyzer()
        analysis_result = analyzer.analyze_file(file_path)

        return jsonify(
            {
                "success": True,
                "file": os.path.basename(file_path),
                "analysis": analysis_result,
            }
        )

    except Exception as e:
        return jsonify({"error": f"分析失败: {str(e)}"}), 500


@file_organize_bp.route("/api/organize/auto-organize", methods=["POST"])
def organize_auto_organize() -> Response:
    """自动组织文件（分析+移动）"""
    try:
        data = request.json
        file_path = data.get("file_path")
        auto_confirm = data.get("auto_confirm", True)

        if not file_path:
            return jsonify({"error": "缺少 file_path 参数"}), 400

        if not os.path.exists(file_path):
            return jsonify({"error": f"文件不存在: {file_path}"}), 404

        # 第一步：分析文件
        analyzer = _get_file_analyzer()
        analysis = analyzer.analyze_file(file_path)
        suggested_folder = analysis.get("suggested_folder")

        if not suggested_folder:
            return jsonify({"error": "无法确定文件分类", "analysis": analysis}), 400

        # 第二步：组织文件
        organizer = _get_file_organizer()
        org_result = organizer.organize_file(
            file_path, suggested_folder, auto_confirm=auto_confirm
        )

        if org_result.get("success"):
            return jsonify(
                {
                    "success": True,
                    "file": os.path.basename(file_path),
                    "analysis": analysis,
                    "organized": org_result,
                }
            )
        else:
            return (
                jsonify(
                    {"error": org_result.get("error", "组织失败"), "analysis": analysis}
                ),
                500,
            )

    except Exception as e:
        return jsonify({"error": f"自动组织失败: {str(e)}"}), 500


@file_organize_bp.route("/api/organize/list-categories", methods=["GET"])
def organize_list_categories() -> Response:
    """列出所有分类和文件夹"""
    try:
        organizer = _get_file_organizer()
        folders = organizer.list_organized_folders()
        stats = organizer.get_categories_stats()

        return jsonify(
            {
                "success": True,
                "folders": folders,
                "stats": stats,
                "total_files": len(organizer.get_index().get("files", [])),
            }
        )

    except Exception as e:
        return jsonify({"error": f"获取分类失败: {str(e)}"}), 500


@file_organize_bp.route("/api/organize/search", methods=["POST"])
def organize_search() -> Response:
    """搜索已组织的文件"""
    try:
        data = request.json
        keyword = data.get("keyword", "")

        if not keyword:
            return jsonify({"error": "缺少搜索关键词"}), 400

        organizer = _get_file_organizer()
        results = organizer.search_files(keyword)

        return jsonify(
            {
                "success": True,
                "keyword": keyword,
                "count": len(results),
                "results": results,
            }
        )

    except Exception as e:
        return jsonify({"error": f"搜索失败: {str(e)}"}), 500


@file_organize_bp.route("/api/organize/stats", methods=["GET"])
def organize_stats() -> Response:
    """获取组织统计信息"""
    try:
        organizer = _get_file_organizer()
        index = organizer.get_index()
        stats = organizer.get_categories_stats()
        folders = organizer.list_organized_folders()

        return jsonify(
            {
                "success": True,
                "total_files": index.get("total_files", 0),
                "total_folders": len(folders),
                "by_industry": stats,
                "last_updated": index.get("last_updated"),
            }
        )

    except Exception as e:
        return jsonify({"error": f"获取统计失败: {str(e)}"}), 500


@file_organize_bp.route("/api/organize/cleanup", methods=["POST"])
def organize_cleanup() -> Response:
    """整合清理 _organize 目录中的重复文件夹"""
    try:
        data = request.get_json(silent=True) or {}
        dry_run = data.get("dry_run", True)
        ai_rename = data.get("ai_rename", False)

        organize_root = _get_organize_root()

        try:
            from web.organize_cleanup import OrganizeCleanup
        except ImportError:
            from organize_cleanup import OrganizeCleanup

        cleanup = OrganizeCleanup(organize_root=organize_root)
        report = cleanup.run(dry_run=dry_run, ai_rename=ai_rename)

        return jsonify(
            {
                "success": True,
                "dry_run": dry_run,
                "total_folders_scanned": report.get("total_folders_scanned", 0),
                "similarity_groups": report.get("similarity_groups", 0),
                "merge_plans": report.get("merge_plans", 0),
                "merged_files": report.get("merged_files", 0),
                "deduped_files": report.get("deduped_files", 0),
                "removed_folders": report.get("removed_folders", 0),
                "empty_cleaned": report.get("empty_cleaned", 0),
                "ai_renames": report.get("ai_renames", 0),
                "log": report.get("log", [])[-50:],  # 最近50条日志
            }
        )

    except Exception as e:
        return jsonify({"error": f"整合清理失败: {str(e)}"}), 500


# ---------------------------------------------------------------------------
# Multi-document compare routes
# ---------------------------------------------------------------------------

_COMPARE_UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "web",
    "uploads",
    "compare",
)
os.makedirs(_COMPARE_UPLOAD_DIR, exist_ok=True)

_ALLOWED_COMPARE_EXTS: set[str] = {
    ".txt",
    ".md",
    ".markdown",
    ".docx",
    ".doc",
    ".pdf",
    ".xlsx",
    ".xls",
    ".pptx",
    ".ppt",
}

# Temporary file_id → path mapping (process-level cache; resets on restart)
_compare_file_registry: dict[str, dict] = {}


@file_organize_bp.route("/api/compare/upload", methods=["POST"])
def compare_upload() -> Response:
    """
    上传一个文件用于多文档对比，返回 file_id。
    前端逐文件调用，收集到 file_ids 后再调用 /api/compare/multi。
    """
    if "file" not in request.files:
        return jsonify({"success": False, "error": "未收到文件字段 'file'"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"success": False, "error": "文件名为空"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in _ALLOWED_COMPARE_EXTS:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"不支持的格式 {ext}，支持: {', '.join(sorted(_ALLOWED_COMPARE_EXTS))}",
                }
            ),
            400,
        )
    import uuid as _uuid

    file_id = _uuid.uuid4().hex
    save_path = os.path.join(_COMPARE_UPLOAD_DIR, f"{file_id}{ext}")
    try:
        f.save(save_path)
    except Exception as e:
        return jsonify({"success": False, "error": f"保存文件失败: {e}"}), 500
    _compare_file_registry[file_id] = {
        "path": save_path,
        "name": f.filename,
        "size": os.path.getsize(save_path),
    }
    return jsonify(
        {
            "success": True,
            "file_id": file_id,
            "filename": f.filename,
            "size": os.path.getsize(save_path),
        }
    )


@file_organize_bp.route("/api/compare/multi", methods=["POST"])
def compare_multi() -> Response:
    """
    文本 diff 对比多个已上传文档。

    Request JSON:
        {"file_ids": ["id1", "id2", ...], "output_format": "inline_json"}
    """
    try:
        from web.document_comparator import DocumentComparator

        data = request.json or {}
        file_ids: list[str] = data.get("file_ids", [])
        output_format: str = data.get("output_format", "inline_json")
        if len(file_ids) < 2:
            return jsonify({"success": False, "error": "至少需要两个文件"}), 400
        file_paths: list[str] = []
        for fid in file_ids:
            info = _compare_file_registry.get(fid)
            if not info:
                return (
                    jsonify(
                        {"success": False, "error": f"file_id 不存在或已过期: {fid}"}
                    ),
                    404,
                )
            file_paths.append(info["path"])
        comparator = DocumentComparator()
        result = comparator.compare_multiple(file_paths, output_format=output_format)
        if result.get("success"):
            for i, fid in enumerate(file_ids):
                info = _compare_file_registry.get(fid, {})
                if i < len(result.get("files", [])):
                    result["files"][i]["display_name"] = info.get("name", "")
        return jsonify(result)
    except Exception as e:
        _logger.exception("[compare_multi] error")
        return jsonify({"success": False, "error": str(e)}), 500


@file_organize_bp.route("/api/compare/ai-stream", methods=["POST"])
def compare_ai_stream() -> Response:
    """
    SSE 流式 AI 语义对比分析。

    Request JSON:
        {"file_ids": ["id1", "id2", ...], "focus": "general"}
    """
    data = request.json or {}
    file_ids: list[str] = data.get("file_ids", [])
    focus: str = data.get("focus", "general")

    if len(file_ids) < 2:

        def _err():
            yield "data: " + json.dumps({"error": "至少需要两个文件"}) + "\n\n"

        return Response(stream_with_context(_err()), mimetype="text/event-stream")

    file_paths = [
        _compare_file_registry[fid]["path"]
        for fid in file_ids
        if fid in _compare_file_registry
    ]
    if len(file_paths) < 2:

        def _err2():
            yield "data: " + json.dumps({"error": "有效文件不足，请重新上传"}) + "\n\n"

        return Response(stream_with_context(_err2()), mimetype="text/event-stream")

    def generate():
        try:
            from web.document_comparator import DocumentComparator
            from web.runtime_context import get_client_proxy

            client = get_client_proxy()
            comparator = DocumentComparator()
            prompt = comparator.build_ai_prompt(file_paths, focus=focus)
            if not prompt:
                yield "data: " + json.dumps({"error": "无法构建分析 prompt"}) + "\n\n"
                return
            model_id = "gemini-2.5-flash"
            try:
                for chunk in client.models.generate_content_stream(
                    model=model_id, contents=prompt
                ):
                    text = getattr(chunk, "text", "") or ""
                    if text:
                        yield "data: " + json.dumps({"chunk": text}) + "\n\n"
            except AttributeError:
                response = client.models.generate_content(
                    model=model_id, contents=prompt
                )
                text = getattr(response, "text", "") or str(response)
                yield "data: " + json.dumps({"chunk": text}) + "\n\n"
            yield "data: " + json.dumps({"done": True}) + "\n\n"
        except Exception as e:
            _logger.exception("[compare_ai_stream] error")
            yield "data: " + json.dumps({"error": str(e)}) + "\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
