# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto 全格式 AI 工作区 BFF 层 — Phase 1-5 后端路由
Routes:
  POST /api/v1/workspace/open_file   — 上传并解析文件，返回标准化 JSON
  GET  /api/v1/workspace/raw/<id>    — 返回暂存的原始文件字节（供 PDF.js 渲染）
  POST /api/v1/workspace/save_file   — 接收编辑数据，导出原格式文件并触发下载
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

logger = logging.getLogger(__name__)

workspace_assistant_bp = Blueprint("workspace_assistant", __name__)

# 临时文件存储目录（相对于项目根）
_TMP_DIR = Path("workspace") / "tmp"

# 允许上传的文件后缀
_ALLOWED_EXT = {".docx", ".xlsx", ".pptx", ".pdf"}


def _ensure_tmp_dir() -> Path:
    _TMP_DIR.mkdir(parents=True, exist_ok=True)
    return _TMP_DIR


def _ext(filename: str) -> str:
    return Path(filename).suffix.lower()

# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/workspace/list_files
# ─────────────────────────────────────────────────────────────────────────────

@workspace_assistant_bp.route("/api/v1/workspace/list_files")
def list_workspace_files():
    """
    获取工作区的文件树结构，仅包含支持的文件类型（DOCX, XLSX, PPTX, PDF）。
    过滤掉隐藏文件和无用文件夹，以树状 JSON 返回。
    """
    from web.shared import WORKSPACE_DIR
    root_path = Path(WORKSPACE_DIR).resolve()

    def _build_tree(dir_path: Path) -> list[dict]:
        items = []
        try:
            for p in dir_path.iterdir():
                if p.name.startswith(".") or p.name.startswith("_") or p.name in ("tmp", "backups", "editor-docs", "images"):
                    continue
                
                rel_path = p.relative_to(root_path).as_posix()
                
                if p.is_dir():
                    children = _build_tree(p)
                    if children:
                        items.append({
                            "name": p.name,
                            "type": "folder",
                            "path": rel_path,
                            "children": children
                        })
                elif p.is_file() and p.suffix.lower() in _ALLOWED_EXT:
                    try:
                        stat = p.stat()
                        size_b = stat.st_size
                        if size_b < 1024:
                            size_str = f"{size_b}B"
                        elif size_b < 1024 * 1024:
                            size_str = f"{size_b / 1024:.1f}KB"
                        else:
                            size_str = f"{size_b / 1024 / 1024:.1f}MB"
                        mtime_ms = int(stat.st_mtime * 1000)
                    except OSError:
                        size_str = ""
                        mtime_ms = 0
                    items.append({
                        "name": p.name,
                        "type": "file",
                        "ext": p.suffix.lower().replace(".", ""),
                        "path": rel_path,
                        "size": size_str,
                        "mtime": mtime_ms,
                    })
        except PermissionError:
            pass

        items.sort(key=lambda x: (0 if x["type"] == "folder" else 1, x["name"].lower()))
        return items

    tree = _build_tree(root_path)
    return jsonify({"files": tree})


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/workspace/file/<path:filepath>
# ─────────────────────────────────────────────────────────────────────────────

@workspace_assistant_bp.route("/api/v1/workspace/file/<path:filepath>")
def serve_workspace_file(filepath: str):
    """
    从工作区目录安全地提供文件下载（用于左侧文件树点击打开）。
    防范路径遍历攻击，仅返回支持格式的文件。
    """
    from web.shared import WORKSPACE_DIR
    root = Path(WORKSPACE_DIR).resolve()
    target = root.joinpath(filepath).resolve()

    # Security: prevent path traversal
    try:
        target.relative_to(root)
    except ValueError:
        return jsonify({"error": "路径不合法"}), 403

    if not target.is_file():
        return jsonify({"error": "文件不存在"}), 404

    if target.suffix.lower() not in _ALLOWED_EXT:
        return jsonify({"error": "不支持的文件类型"}), 400

    mime_map = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pdf": "application/pdf",
    }
    mime = mime_map.get(target.suffix.lower(), "application/octet-stream")
    return send_file(str(target), mimetype=mime, as_attachment=False,
                     download_name=target.name)


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/open_file
# ─────────────────────────────────────────────────────────────────────────────

@workspace_assistant_bp.route("/api/v1/workspace/open_file", methods=["POST"])
def open_file():
    """
    接受 multipart/form-data 上传，解析文件并返回适合前端多态渲染器的标准 JSON。
    Body: file=<binary>
    Response:
      {"file_id": str, "file_name": str, "file_type": str, "data": <parsed>}
    """
    if "file" not in request.files:
        return jsonify({"error": "缺少 file 字段"}), 400

    uploaded = request.files["file"]
    original_name = uploaded.filename or "unknown"
    ext = _ext(original_name)

    if ext not in _ALLOWED_EXT:
        return jsonify({"error": f"不支持的格式: {ext}，仅支持 {sorted(_ALLOWED_EXT)}"}), 400

    # 暂存原始文件（用于 PDF.js raw 渲染等）
    file_id = uuid.uuid4().hex
    tmp_path = _ensure_tmp_dir() / f"{file_id}{ext}"
    uploaded.save(str(tmp_path))

    # 持久化保存到 workspace/uploads/（重启后仍可在左侧面板看到）
    try:
        from web.shared import WORKSPACE_DIR
        uploads_dir = Path(WORKSPACE_DIR) / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(original_name).stem
        persistent_path = uploads_dir / original_name
        counter = 1
        while persistent_path.exists():
            persistent_path = uploads_dir / f"{stem}_{counter}{ext}"
            counter += 1
        import shutil
        shutil.copy2(str(tmp_path), str(persistent_path))
    except Exception as pe:
        logger.warning(f"[WorkspaceAssistant] 持久化失败 {original_name}: {pe}")

    try:
        from app.core.file.file_parser import (
            parse_docx,
            parse_pdf,
            parse_pptx,
            parse_xlsx,
        )

        if ext == ".docx":
            data = parse_docx(str(tmp_path))
            file_type = "docx"
        elif ext == ".xlsx":
            data = parse_xlsx(str(tmp_path))
            file_type = "xlsx"
        elif ext == ".pptx":
            data = parse_pptx(str(tmp_path))
            file_type = "pptx"
        elif ext == ".pdf":
            data = parse_pdf(str(tmp_path), file_id)
            file_type = "pdf"
        else:
            return jsonify({"error": "内部格式路由错误"}), 500

    except Exception as e:
        logger.error(f"[WorkspaceAssistant] 解析失败 {original_name}: {e}", exc_info=True)
        # 清理临时文件
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return jsonify({"error": f"文件解析失败: {str(e)}"}), 500

    return jsonify({
        "file_id": file_id,
        "file_name": original_name,
        "file_type": file_type,
        "data": data,
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/workspace/raw/<file_id>
# ─────────────────────────────────────────────────────────────────────────────

@workspace_assistant_bp.route("/api/v1/workspace/raw/<file_id>")
def raw_file(file_id: str):
    """
    返回暂存的原始文件（用于 PDF.js 直接渲染）。
    file_id 只允许十六进制字符，防止路径遍历。
    """
    # 安全校验：仅允许十六进制 file_id
    if not file_id.isalnum():
        return jsonify({"error": "无效的 file_id"}), 400

    tmp_dir = _ensure_tmp_dir()
    # 搜索匹配的文件（file_id + 任意后缀）
    matches = list(tmp_dir.glob(f"{file_id}.*"))
    if not matches:
        return jsonify({"error": "文件不存在或已过期"}), 404

    target = matches[0].resolve()  # Always use absolute path for send_file
    mime_map = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    mime = mime_map.get(target.suffix.lower(), "application/octet-stream")
    return send_file(str(target), mimetype=mime)


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/save_file
# ─────────────────────────────────────────────────────────────────────────────

@workspace_assistant_bp.route("/api/v1/workspace/save_file", methods=["POST"])
def save_file():
    """
    接收编辑后数据，导出为原格式二进制并触发浏览器下载。
    Body (JSON):
      {"file_type": "docx"|"xlsx"|"pptx",
       "file_id": str,          # PPTX 需要原始文件 ID
       "data": <editor_payload>,
       "file_name": str}        # 可选，用于下载文件名
    """
    body = request.get_json(force=True, silent=True) or {}
    file_type = body.get("file_type", "").lower()
    file_id = body.get("file_id", "")
    data = body.get("data")
    file_name = body.get("file_name", f"koto_export.{file_type}")

    if not file_type or data is None:
        return jsonify({"error": "缺少 file_type 或 data 字段"}), 400

    try:
        from app.core.file.file_parser import export_docx, export_pptx, export_xlsx

        if file_type == "docx":
            raw_bytes = export_docx(data)  # data = HTML string
            mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if not file_name.endswith(".docx"):
                file_name = Path(file_name).stem + ".docx"

        elif file_type == "xlsx":
            # data may be a plain list (legacy) or {sheets, _images} dict (new)
            if isinstance(data, dict):
                sheets_data = data.get("sheets", [])
                images_data = data.get("_images", [])
            else:
                sheets_data = data
                images_data = []
            raw_bytes = export_xlsx(sheets_data, images_data)
            mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if not file_name.endswith(".xlsx"):
                file_name = Path(file_name).stem + ".xlsx"

        elif file_type == "pptx":
            # 找回原始暂存文件
            if not file_id or not file_id.isalnum():
                return jsonify({"error": "PPTX 导出需要有效的 file_id"}), 400
            tmp_dir = _ensure_tmp_dir()
            matches = list(tmp_dir.glob(f"{file_id}.pptx"))
            if not matches:
                return jsonify({"error": "原始 PPTX 文件不存在或已过期"}), 404
            original_path = str(matches[0])
            raw_bytes = export_pptx(original_path, data)  # data = slides JSON
            mime = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            if not file_name.endswith(".pptx"):
                file_name = Path(file_name).stem + ".pptx"

        else:
            return jsonify({"error": f"不支持的导出格式: {file_type}"}), 400

    except Exception as e:
        logger.error(f"[WorkspaceAssistant] 导出失败 {file_type}: {e}", exc_info=True)
        return jsonify({"error": f"导出失败: {str(e)}"}), 500

    import io
    return send_file(
        io.BytesIO(raw_bytes),
        mimetype=mime,
        as_attachment=True,
        download_name=file_name,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/auto_save
# ─────────────────────────────────────────────────────────────────────────────

@workspace_assistant_bp.route("/api/v1/workspace/auto_save", methods=["POST"])
def auto_save():
    """
    Silently save edited content back to the workspace tmp file.
    No download — just persists the current state so it survives a reload.
    Body (JSON):
      {"file_type": "docx"|"xlsx"|"pptx",
       "file_id": str,
       "data": <editor_payload>}
    Returns: {"ok": true, "saved_at": "<ISO timestamp>"}
    """
    import datetime, io as _io
    body = request.get_json(force=True, silent=True) or {}
    file_type = body.get("file_type", "").lower()
    file_id = body.get("file_id", "")
    data = body.get("data")

    if not file_type or not file_id or data is None:
        return jsonify({"error": "缺少必要字段"}), 400
    if not file_id.isalnum():
        return jsonify({"error": "无效的 file_id"}), 400

    try:
        from app.core.file.file_parser import export_docx, export_pptx, export_xlsx

        if file_type == "docx":
            raw_bytes = export_docx(data)
            suffix = ".docx"
        elif file_type == "xlsx":
            sheets_data = data.get("sheets", data) if isinstance(data, dict) else data
            images_data = data.get("_images", []) if isinstance(data, dict) else []
            raw_bytes = export_xlsx(sheets_data, images_data)
            suffix = ".xlsx"
        elif file_type == "pptx":
            tmp_dir = _ensure_tmp_dir()
            matches = list(tmp_dir.glob(f"{file_id}.pptx"))
            if not matches:
                return jsonify({"error": "原始 PPTX 文件不存在或已过期"}), 404
            raw_bytes = export_pptx(str(matches[0]), data)
            suffix = ".pptx"
        else:
            return jsonify({"error": f"不支持的格式: {file_type}"}), 400

    except Exception as e:
        logger.error("[WorkspaceAssistant] auto_save 失败 %s: %s", file_type, e, exc_info=True)
        return jsonify({"error": f"自动保存失败: {str(e)}"}), 500

    # Overwrite the tmp file in-place so raw/<file_id> still works
    tmp_path = _ensure_tmp_dir() / f"{file_id}{suffix}"
    tmp_path.write_bytes(raw_bytes)
    logger.debug("[WorkspaceAssistant] auto_save wrote %d bytes → %s", len(raw_bytes), tmp_path)

    saved_at = datetime.datetime.now().strftime("%H:%M")
    return jsonify({"ok": True, "saved_at": saved_at})


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /api/v1/workspace/file  ?path=<relative_path>
# ─────────────────────────────────────────────────────────────────────────────

@workspace_assistant_bp.route("/api/v1/workspace/file", methods=["DELETE"])
def delete_workspace_file():
    """
    删除工作区中的一个文件（用于左侧面板的 × 按钮）。
    Query param:  path=relative/path/to/file
    """
    from web.shared import WORKSPACE_DIR
    root = Path(WORKSPACE_DIR).resolve()
    filepath = request.args.get("path", "").strip()
    if not filepath:
        return jsonify({"error": "缺少 path 参数"}), 400

    target = root.joinpath(filepath).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return jsonify({"error": "路径不合法"}), 403

    if not target.is_file():
        return jsonify({"error": "文件不存在"}), 404

    if target.suffix.lower() not in _ALLOWED_EXT:
        return jsonify({"error": "不支持的文件类型"}), 400

    target.unlink()
    logger.info(f"[WorkspaceAssistant] 删除文件: {target}")
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /api/v1/workspace/rename
# ─────────────────────────────────────────────────────────────────────────────

@workspace_assistant_bp.route("/api/v1/workspace/rename", methods=["PATCH"])
def rename_workspace_file():
    """
    重命名工作区文件。
    Body (JSON): {"path": "uploads/old.docx", "name": "new_name.docx"}
    Extension must stay the same; new_name must not contain path separators.
    """
    from web.shared import WORKSPACE_DIR
    root = Path(WORKSPACE_DIR).resolve()
    body = request.get_json(silent=True) or {}
    old_path = body.get("path", "").strip()
    new_name = body.get("name", "").strip()

    if not old_path or not new_name:
        return jsonify({"error": "缺少 path 或 name 参数"}), 400

    if "/" in new_name or "\\" in new_name:
        return jsonify({"error": "文件名不能包含路径分隔符"}), 400

    old_target = root.joinpath(old_path).resolve()
    try:
        old_target.relative_to(root)
    except ValueError:
        return jsonify({"error": "路径不合法"}), 403

    if not old_target.is_file():
        return jsonify({"error": "文件不存在"}), 404

    # Preserve original extension even if user omitted/changed it
    old_ext = old_target.suffix.lower()
    stem = Path(new_name).stem
    if not stem:
        return jsonify({"error": "文件名无效"}), 400
    final_name = stem + old_ext

    new_target = old_target.parent / final_name
    if new_target.exists():
        return jsonify({"error": "文件名已存在"}), 409

    old_target.rename(new_target)
    new_rel = new_target.relative_to(root).as_posix()
    logger.info(f"[WorkspaceAssistant] 重命名: {old_path} -> {new_rel}")
    return jsonify({"ok": True, "path": new_rel, "name": final_name})
