# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Miscellaneous API blueprint.

Extracts notes, reminders, calendar, clipboard, search, data-pipeline,
code-generation, and file-network routes from web/app.py.
"""

import logging
import os

from flask import Blueprint, Response, jsonify, request

_logger = logging.getLogger("koto.routes.misc_api")

misc_api_bp = Blueprint("misc_api", __name__)


# ---------------------------------------------------------------------------
# Lazy helpers – avoid circular imports with web.app
# ---------------------------------------------------------------------------


def _get_workspace_dir():
    from web.runtime_context import get_workspace_dir

    return get_workspace_dir()


# ========================= Notes API =========================


@misc_api_bp.route("/api/notes/add", methods=["POST"])
def add_note() -> Response:
    """添加笔记"""
    from note_manager import get_note_manager

    data = request.json
    title = data.get("title", "")
    content = data.get("content", "")
    category = data.get("category", "default")
    tags = data.get("tags", [])

    note_manager = get_note_manager()
    note = note_manager.add_note(content, tags=tags, category=category)
    note_id = note.get("id") if isinstance(note, dict) else note

    return jsonify({"success": True, "note_id": note_id})


@misc_api_bp.route("/api/notes/list", methods=["GET"])
def list_notes() -> Response:
    """列出最近笔记"""
    from note_manager import get_note_manager

    limit = int(request.args.get("limit", 20))
    category = request.args.get("category")

    note_manager = get_note_manager()
    notes = note_manager.get_recent_notes(limit)

    return jsonify({"notes": notes})


@misc_api_bp.route("/api/notes/search", methods=["GET"])
def search_notes() -> Response:
    """搜索笔记"""
    from note_manager import get_note_manager

    query = request.args.get("query", "")
    note_manager = get_note_manager()
    results = note_manager.search_notes(query)

    return jsonify({"results": results})


@misc_api_bp.route("/api/notes/<note_id>", methods=["DELETE"])
def delete_note(note_id: str) -> Response:
    """删除笔记"""
    from note_manager import get_note_manager

    note_manager = get_note_manager()
    success = note_manager.delete_note(note_id)

    return jsonify({"success": success})


# ========================= Reminders API =========================


@misc_api_bp.route("/api/reminders/add", methods=["POST"])
def add_reminder() -> Response:
    """创建本地系统提醒
    请求体: {"title": str, "message": str, "time": ISO8601, "seconds": int}
    - 传 time (ISO 时间) 或 seconds (相对秒数) 任选其一
    """
    from datetime import datetime

    from reminder_manager import get_reminder_manager

    data = request.json or {}
    title = data.get("title") or "提醒"
    message = data.get("message") or ""
    icon = data.get("icon")
    remind_time = data.get("time")
    seconds = data.get("seconds")

    mgr = get_reminder_manager()
    if remind_time:
        try:
            dt = datetime.fromisoformat(remind_time)
        except Exception:
            return jsonify({"success": False, "error": "时间格式需为 ISO8601"}), 400
        rid = mgr.add_reminder(title, message, dt, icon)
    elif seconds is not None:
        try:
            sec = int(seconds)
        except Exception:
            return jsonify({"success": False, "error": "seconds 需为整数"}), 400
        rid = mgr.add_reminder_in(title, message, sec, icon)
    else:
        return jsonify({"success": False, "error": "需提供 time 或 seconds"}), 400

    return jsonify({"success": True, "reminder_id": rid})


@misc_api_bp.route("/api/reminders/list", methods=["GET"])
def list_reminders_api() -> Response:
    """列出所有提醒"""
    from reminder_manager import get_reminder_manager

    mgr = get_reminder_manager()
    return jsonify({"reminders": mgr.list_reminders()})


@misc_api_bp.route("/api/reminders/<reminder_id>", methods=["DELETE"])
def cancel_reminder(reminder_id: str) -> Response:
    """取消提醒"""
    from reminder_manager import get_reminder_manager

    mgr = get_reminder_manager()
    ok = mgr.cancel_reminder(reminder_id)
    return jsonify({"success": ok})


# ========================= Calendar API =========================


@misc_api_bp.route("/api/calendar/add", methods=["POST"])
def add_calendar_event() -> Response:
    """新增日程并自动创建本地提醒
    请求体: {"title": str, "description": str, "start": ISO8601, "end": ISO8601?, "remind_before_minutes": int?}
    """
    from datetime import datetime

    from calendar_manager import get_calendar_manager

    data = request.json or {}
    title = data.get("title") or "日程"
    description = data.get("description") or ""
    start = data.get("start")
    end = data.get("end")
    remind_before_minutes = int(data.get("remind_before_minutes") or 0)

    if not start:
        return jsonify({"success": False, "error": "start 不能为空 (ISO8601)"}), 400
    try:
        start_dt = datetime.fromisoformat(start)
    except Exception:
        return jsonify({"success": False, "error": "start 必须是 ISO8601 时间"}), 400
    end_dt = None
    if end:
        try:
            end_dt = datetime.fromisoformat(end)
        except Exception:
            return jsonify({"success": False, "error": "end 必须是 ISO8601 时间"}), 400

    mgr = get_calendar_manager()
    event_id = mgr.add_event(
        title, description, start_dt, end_dt, remind_before_minutes
    )
    return jsonify({"success": True, "event_id": event_id})


@misc_api_bp.route("/api/calendar/list", methods=["GET"])
def list_calendar_events() -> Response:
    from calendar_manager import get_calendar_manager

    limit = int(request.args.get("limit", 100))
    mgr = get_calendar_manager()
    return jsonify({"events": mgr.list_events(limit)})


@misc_api_bp.route("/api/calendar/<event_id>", methods=["DELETE"])
def delete_calendar_event(event_id: str) -> Response:
    from calendar_manager import get_calendar_manager

    mgr = get_calendar_manager()
    ok = mgr.delete_event(event_id)
    return jsonify({"success": ok})


# ========================= Clipboard API =========================


@misc_api_bp.route("/api/clipboard/history", methods=["GET"])
def get_clipboard_history() -> Response:
    """获取剪贴板历史"""
    from clipboard_manager import get_clipboard_manager

    limit = int(request.args.get("limit", 50))
    type_filter = request.args.get("type")
    clipboard_manager = get_clipboard_manager()
    history = clipboard_manager.get_history(limit)
    if type_filter:
        history = [item for item in history if item.get("type") == type_filter]

    return jsonify({"history": history})


@misc_api_bp.route("/api/clipboard/search", methods=["GET"])
def search_clipboard() -> Response:
    """搜索剪贴板历史"""
    from clipboard_manager import get_clipboard_manager

    query = request.args.get("query", "")
    type_filter = request.args.get("type")
    clipboard_manager = get_clipboard_manager()
    results = clipboard_manager.search(query)
    if type_filter:
        results = [item for item in results if item.get("type") == type_filter]

    return jsonify({"results": results})


@misc_api_bp.route("/api/clipboard/copy", methods=["POST"])
def copy_from_history() -> Response:
    """从历史中复制"""
    from clipboard_manager import get_clipboard_manager

    content = request.json.get("content")
    index = request.json.get("index")
    clipboard_manager = get_clipboard_manager()
    if index is not None:
        try:
            index = int(index)
        except Exception:
            return jsonify({"success": False, "error": "index 必须是整数"}), 400
        success = clipboard_manager.copy_from_history(index)
    else:
        success = clipboard_manager.copy_from_history(content or "")

    return jsonify({"success": success})


# ========================= Search API =========================


@misc_api_bp.route("/api/search/all", methods=["GET"])
def search_all() -> Response:
    """Global search across all indexed content.
    ---
    tags:
      - Search
    parameters:
      - in: query
        name: query
        type: string
        required: true
        description: Search query string
      - in: query
        name: max_results
        type: integer
        default: 50
        description: Maximum number of results to return
    responses:
      200:
        description: Search results
        schema:
          type: object
          properties:
            results:
              type: array
              items:
                type: object
            count:
              type: integer
              description: Total number of results
    """
    from search_engine import get_search_engine

    query = request.args.get("query", "")
    max_results = int(request.args.get("max_results", 50))

    search_engine = get_search_engine()
    results = search_engine.search_all(query, max_results)

    return jsonify(results)


@misc_api_bp.route("/api/search/files", methods=["GET"])
def search_files() -> Response:
    """搜索文件"""
    from search_engine import get_search_engine

    query = request.args.get("query", "")
    max_results = int(request.args.get("max_results", 20))

    search_engine = get_search_engine()
    results = search_engine.search_files(query, max_results)

    return jsonify({"results": results})


# ========================= Data Pipeline API =========================


@misc_api_bp.route("/api/data/extract-transform", methods=["POST"])
def data_extract_transform() -> Response:
    """数据提取与转换 - 场景1：跨应用数据搬运"""
    try:
        from datetime import datetime

        data = request.json
        source_type = data.get("source_type", "wechat_contact")
        source_data = data.get("source_data")
        target_format = data.get("target_format", "excel")
        output_filename = data.get(
            "output_filename", f'提取数据_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        )

        if target_format == "excel":
            ext = ".xlsx"
        elif target_format == "csv":
            ext = ".csv"
        else:
            ext = ".json"

        output_path = os.path.join(
            _get_workspace_dir(), "documents", f"{output_filename}{ext}"
        )

        from web.data_pipeline import CrossAppDataPipeline

        pipeline = CrossAppDataPipeline()
        result = pipeline.run_pipeline(
            source_type, source_data, target_format, output_path
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ========================= Code Generation API =========================


@misc_api_bp.route("/api/code/generate", methods=["POST"])
def code_generate() -> Response:
    """代码生成 - 场景2：帮助用户完成编程任务"""
    try:
        data = request.json
        template_name = data.get("template_name")
        description = data.get("description")
        language = data.get("language", "python")
        output_filename = data.get("output_filename")

        from web.code_generator import CodeGenerator

        generator = CodeGenerator()

        output_path = None
        if output_filename:
            output_path = os.path.join(_get_workspace_dir(), "code", output_filename)

        if template_name:
            result = generator.generate(
                template_name, output_path, **data.get("params", {})
            )
        elif description:
            result = generator.generate_from_description(description, language)
        else:
            return (
                jsonify(
                    {"success": False, "error": "需要提供template_name或description"}
                ),
                400,
            )

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@misc_api_bp.route("/api/code/templates", methods=["GET"])
def code_templates() -> Response:
    """获取可用代码模板列表"""
    try:
        from web.code_generator import CodeGenerator

        generator = CodeGenerator()

        language = request.args.get("language")
        templates = generator.list_templates(language)

        return jsonify(
            {"success": True, "templates": templates, "count": len(templates)}
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ========================= File Network API =========================


@misc_api_bp.route("/api/file-network/search", methods=["POST"])
def file_network_search() -> Response:
    """多维查询文件

    请求参数:
        query: 文本搜索查询（可选）
        file_type: 文件类型（docx, pdf等，可选）
        tags: 标签列表（可选）
        operation: 处理操作（annotate, edit等，可选）
        date_from: 开始日期（ISO格式，可选）
        date_to: 结束日期（ISO格式，可选）
        limit: 返回数量限制（默认50）
    """
    try:
        from web.processed_file_network import get_file_network

        data = request.json or {}
        file_network = get_file_network()

        result = file_network.search_files(
            query=data.get("query"),
            file_type=data.get("file_type"),
            tags=data.get("tags"),
            operation=data.get("operation"),
            date_from=data.get("date_from"),
            date_to=data.get("date_to"),
            limit=data.get("limit", 50),
        )

        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@misc_api_bp.route("/api/file-network/network", methods=["POST"])
def file_network_get_network() -> Response:
    """获取文件关系网络

    请求参数:
        file_id: 文件ID
        depth: 关系深度（1=直接关系，2=二级关系，默认2）
    """
    try:
        from web.processed_file_network import get_file_network

        data = request.json
        file_id = data.get("file_id")
        depth = data.get("depth", 2)

        if not file_id:
            return jsonify({"success": False, "error": "缺少file_id参数"}), 400

        file_network = get_file_network()
        result = file_network.get_file_network(file_id, depth)

        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@misc_api_bp.route("/api/file-network/statistics", methods=["GET"])
def file_network_statistics() -> Response:
    """获取文件网络统计信息"""
    try:
        from web.processed_file_network import get_file_network

        file_network = get_file_network()
        result = file_network.get_statistics()

        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@misc_api_bp.route("/api/file-network/register", methods=["POST"])
def file_network_register() -> Response:
    """手动注册文件到网络

    请求参数:
        file_path: 文件路径
        tags: 标签列表（可选）
        extract_snippets: 是否提取文本片段（默认true）
    """
    try:
        from web.processed_file_network import get_file_network

        data = request.json
        file_path = data.get("file_path")

        if not file_path:
            return jsonify({"success": False, "error": "缺少file_path参数"}), 400

        file_network = get_file_network()
        result = file_network.register_file(
            file_path=file_path,
            tags=data.get("tags"),
            extract_snippets=data.get("extract_snippets", True),
        )

        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
