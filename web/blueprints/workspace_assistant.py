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

from flask import Blueprint, Response, jsonify, request, send_file, stream_with_context

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


@workspace_assistant_bp.route("/api/v1/workspace/current_dir")
def get_current_workspace_dir():
    """Return the current workspace root path and display name."""
    from web.shared import WORKSPACE_DIR

    p = Path(WORKSPACE_DIR).resolve()
    return jsonify({"path": str(p), "name": p.name})


@workspace_assistant_bp.route("/api/v1/workspace/list_files")
def list_workspace_files():
    """
    获取工作区的文件树结构（全文件类型）。
    过滤掉隐藏文件和系统文件夹，以树状 JSON 返回。
    supported=true 表示 Koto 可直接打开和编辑该文件。
    """
    from web.shared import WORKSPACE_DIR

    root_path = Path(WORKSPACE_DIR).resolve()

    # Extensions that Koto can open and parse
    _openable = frozenset(_ALLOWED_EXT)

    def _file_category(ext: str) -> str:
        _map = {
            ".docx": "docx", ".doc": "docx",
            ".xlsx": "xlsx", ".xls": "xlsx",
            ".pptx": "pptx", ".ppt": "pptx",
            ".pdf": "pdf",
            ".txt": "text", ".md": "text", ".markdown": "text",
            ".py": "code", ".js": "code", ".ts": "code", ".json": "code",
            ".html": "code", ".css": "code", ".sh": "code", ".yaml": "code",
            ".png": "image", ".jpg": "image", ".jpeg": "image",
            ".gif": "image", ".svg": "image", ".webp": "image",
        }
        return _map.get(ext, "other")

    def _build_tree(dir_path: Path) -> list[dict]:
        items = []
        _skip = {"tmp", "backups", "editor-docs", "images", "__pycache__",
                  "node_modules", ".git", ".venv", "venv"}
        try:
            for p in sorted(dir_path.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
                if p.name.startswith(".") or p.name in _skip:
                    continue

                rel_path = p.relative_to(root_path).as_posix()

                if p.is_dir():
                    children = _build_tree(p)
                    items.append({
                        "name": p.name,
                        "type": "folder",
                        "path": rel_path,
                        "children": children,
                    })
                elif p.is_file():
                    ext = p.suffix.lower()
                    try:
                        stat = p.stat()
                        size_b = stat.st_size
                        size_str = (f"{size_b}B" if size_b < 1024
                                    else f"{size_b / 1024:.1f}KB" if size_b < 1048576
                                    else f"{size_b / 1048576:.1f}MB")
                        mtime_ms = int(stat.st_mtime * 1000)
                    except OSError:
                        size_str = ""
                        mtime_ms = 0
                    items.append({
                        "name": p.name,
                        "type": "file",
                        "ext": ext.lstrip("."),
                        "path": rel_path,
                        "size": size_str,
                        "mtime": mtime_ms,
                        "supported": ext in _openable,
                        "category": _file_category(ext),
                    })
        except PermissionError:
            pass

        return items

    tree = _build_tree(root_path)
    return jsonify({"files": tree, "workspace_name": root_path.name, "workspace_path": str(root_path)})


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
    return send_file(
        str(target), mimetype=mime, as_attachment=False, download_name=target.name
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/open_file_by_path
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/open_file_by_path", methods=["POST"])
def open_file_by_path():
    """
    直接从工作区路径打开并解析文件，无需先下载再上传。
    比 open_file 更高效，用于工作区文件树点击打开。
    Body (JSON): {"path": "relative/path/to/file.docx"}
    Response: 同 open_file
    """
    body = request.get_json(force=True, silent=True) or {}
    rel_path = (body.get("path") or "").strip()
    if not rel_path:
        return jsonify({"error": "缺少 path 字段"}), 400

    from web.shared import WORKSPACE_DIR

    root = Path(WORKSPACE_DIR).resolve()
    target = root.joinpath(rel_path).resolve()

    # Security: prevent path traversal
    try:
        target.relative_to(root)
    except ValueError:
        return jsonify({"error": "路径不合法"}), 403

    if not target.is_file():
        return jsonify({"error": "文件不存在"}), 404

    ext = target.suffix.lower()
    if ext not in _ALLOWED_EXT:
        return jsonify({"error": f"不支持的格式: {ext}"}), 400

    # Copy to tmp so editor can work with it (same as open_file)
    file_id = uuid.uuid4().hex
    tmp_path = _ensure_tmp_dir() / f"{file_id}{ext}"
    try:
        import shutil

        shutil.copy2(str(target), str(tmp_path))
    except Exception as ce:
        return jsonify({"error": f"文件复制失败: {ce}"}), 500

    try:
        from app.core.file.file_parser import (
            parse_docx,
            parse_pdf,
            parse_pptx_geometry,
            parse_xlsx,
        )

        if ext == ".docx":
            data = parse_docx(str(tmp_path))
            file_type = "docx"
        elif ext == ".xlsx":
            data = parse_xlsx(str(tmp_path))
            file_type = "xlsx"
        elif ext == ".pptx":
            data = parse_pptx_geometry(str(tmp_path))
            file_type = "pptx"
        elif ext == ".pdf":
            data = parse_pdf(str(tmp_path), file_id)
            file_type = "pdf"
        else:
            return jsonify({"error": "内部格式路由错误"}), 500

    except Exception as e:
        logger.error(f"[WorkspaceAssistant] 解析失败 {target.name}: {e}", exc_info=True)
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return jsonify({"error": f"文件解析失败: {str(e)}"}), 500

    return jsonify(
        {
            "file_id": file_id,
            "file_name": target.name,
            "file_type": file_type,
            "data": data,
        }
    )


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
        return (
            jsonify({"error": f"不支持的格式: {ext}，仅支持 {sorted(_ALLOWED_EXT)}"}),
            400,
        )

    # 暂存原始文件（用于 PDF.js raw 渲染等）
    file_id = uuid.uuid4().hex
    tmp_path = _ensure_tmp_dir() / f"{file_id}{ext}"
    uploaded.save(str(tmp_path))

    # 文件只暂存在 tmp 目录，不立即写入工作区。
    # 用户显式保存后才会写入 WORKSPACE_DIR（由 auto_save explicit=true 处理）。
    ws_path = request.form.get("ws_path", "").strip()

    try:
        from app.core.file.file_parser import (
            parse_docx,
            parse_pdf,
            parse_pptx_geometry,
            parse_xlsx,
        )

        if ext == ".docx":
            data = parse_docx(str(tmp_path))
            file_type = "docx"
        elif ext == ".xlsx":
            data = parse_xlsx(str(tmp_path))
            file_type = "xlsx"
        elif ext == ".pptx":
            data = parse_pptx_geometry(str(tmp_path))
            file_type = "pptx"
        elif ext == ".pdf":
            data = parse_pdf(str(tmp_path), file_id)
            file_type = "pdf"
        else:
            return jsonify({"error": "内部格式路由错误"}), 500

    except Exception as e:
        logger.error(
            f"[WorkspaceAssistant] 解析失败 {original_name}: {e}", exc_info=True
        )
        # 清理临时文件
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return jsonify({"error": f"文件解析失败: {str(e)}"}), 500

    return jsonify(
        {
            "file_id": file_id,
            "file_name": original_name,
            "file_type": file_type,
            "data": data,
        }
    )


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
    resp = send_file(str(target), mimetype=mime)
    # Prevent browser from caching — each save produces new bytes at the same URL
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


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
            # data is {snapshot: IWorkbookData, _images: []} from Univer frontend,
            # or a plain list (Luckysheet legacy), or a bare IWorkbookData dict.
            if isinstance(data, dict):
                # Prefer 'snapshot' key (new Univer format), fall back to whole dict
                wb_data = data.get("snapshot") or data
                images_data = data.get("_images", [])
            else:
                wb_data = data
                images_data = []
            raw_bytes = export_xlsx(wb_data, images_data)
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

            # Rich format (from _parse_slides) has a 'slides' key with full shape data
            if isinstance(data, dict) and "slides" in data:
                from web.blueprints.pptx_editor import _apply_edits as _pptx_apply

                with open(original_path, "rb") as _f:
                    orig_bytes = _f.read()
                raw_bytes = _pptx_apply(orig_bytes, data["slides"])
            else:
                # Legacy simple format fallback
                from app.core.file.file_parser import export_pptx

                raw_bytes = export_pptx(original_path, data)

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
# POST /api/v1/workspace/replace_image
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/replace_image", methods=["POST"])
def replace_image():
    """
    Replace a picture shape in a PPTX with a new uploaded image.
    Overwrites the tmp file in-place so subsequent save_file/auto_save exports
    use the new image without requiring a re-upload.

    Body: multipart/form-data
      file_id     — str (hex)
      slide_index — int
      shape_id    — int
      image       — file  (image/*)

    Returns: {"ok": true, "image_b64": "data:image/...;base64,..."}
    """
    file_id = request.form.get("file_id", "").strip()
    slide_index_str = request.form.get("slide_index", "").strip()
    shape_id_str = request.form.get("shape_id", "").strip()

    if not file_id or not file_id.isalnum():
        return jsonify({"error": "无效的 file_id"}), 400
    if not slide_index_str.isdigit() or not shape_id_str.isdigit():
        return jsonify({"error": "slide_index 和 shape_id 必须是整数"}), 400
    if "image" not in request.files:
        return jsonify({"error": "缺少 image 字段"}), 400

    img_file = request.files["image"]
    content_type = img_file.content_type or ""
    if not content_type.startswith("image/"):
        return jsonify({"error": "仅支持图片格式 (image/*)"}), 400

    img_bytes = img_file.read()
    if not img_bytes:
        return jsonify({"error": "图片文件为空"}), 400

    slide_index = int(slide_index_str)
    shape_id = int(shape_id_str)

    tmp_dir = _ensure_tmp_dir()
    matches = list(tmp_dir.glob(f"{file_id}.pptx"))
    if not matches:
        return jsonify({"error": "原始 PPTX 文件不存在或已过期"}), 404

    pptx_path = str(matches[0])
    try:
        import io as _io

        from pptx import Presentation

        prs = Presentation(pptx_path)
        if slide_index >= len(prs.slides):
            return jsonify({"error": "幻灯片序号超出范围"}), 400

        slide = prs.slides[slide_index]
        target_shape = None
        for shape in slide.shapes:
            if shape.shape_id == shape_id:
                target_shape = shape
                break

        if target_shape is None:
            return jsonify({"error": "未找到指定形状"}), 404

        left = target_shape.left
        top = target_shape.top
        width = target_shape.width
        height = target_shape.height

        # Remove old picture element from slide XML
        sp_elem = target_shape._element
        sp_elem.getparent().remove(sp_elem)

        # Insert new picture at the same position/size
        slide.shapes.add_picture(_io.BytesIO(img_bytes), left, top, width, height)

        # Overwrite tmp file in-place so later export/auto_save uses updated image
        prs.save(pptx_path)

    except Exception as e:
        logger.error(f"[WorkspaceAssistant] replace_image 失败: {e}", exc_info=True)
        return jsonify({"error": f"替换失败: {str(e)}"}), 500

    import base64 as _b64

    b64 = _b64.b64encode(img_bytes).decode("ascii")
    return jsonify({"ok": True, "image_b64": f"data:{content_type};base64,{b64}"})


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/auto_save
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/auto_save", methods=["POST"])
def auto_save():
    """
    Silently save edited content back to the workspace tmp file AND the original
    workspace source file (so switching back to the file shows latest changes).
    No download — just persists the current state so it survives a reload.
    Body (JSON):
      {"file_type": "docx"|"xlsx"|"pptx",
       "file_id": str,
       "ws_source_path": str,   # optional: workspace-relative path to overwrite
       "data": <editor_payload>}
    Returns: {"ok": true, "saved_at": "<ISO timestamp>"}
    """
    import datetime

    body = request.get_json(force=True, silent=True) or {}
    file_type = body.get("file_type", "").lower()
    file_id = body.get("file_id", "")
    ws_source_path = body.get("ws_source_path", "")  # e.g. "foo.docx"
    data = body.get("data")

    if not file_type or not file_id or data is None:
        return jsonify({"error": "缺少必要字段"}), 400
    if not file_id.isalnum():
        return jsonify({"error": "无效的 file_id"}), 400

    explicit = body.get("explicit", False)
    data_len = len(data) if isinstance(data, str) else (len(str(data)) if data else 0)
    logger.info(
        "[auto_save] explicit=%s file_id=%s...%s data_len=%d preview=%.120s",
        explicit,
        file_id[:8],
        file_id[-4:],
        data_len,
        (data[:120] if isinstance(data, str) else str(data)[:120]),
    )

    try:
        from app.core.file.file_parser import export_docx, export_pptx, export_xlsx

        if file_type == "docx":
            raw_bytes = export_docx(data)
            suffix = ".docx"
        elif file_type == "xlsx":
            # data is {snapshot: IWorkbookData, _images: []} from Univer frontend.
            # Fall back to bare dict or list for legacy compatibility.
            if isinstance(data, dict):
                wb_data = data.get("snapshot") or data
                images_data = data.get("_images", [])
            else:
                wb_data = data
                images_data = []
            raw_bytes = export_xlsx(wb_data, images_data)
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
        logger.error(
            "[WorkspaceAssistant] auto_save 失败 %s: %s", file_type, e, exc_info=True
        )
        return jsonify({"error": f"自动保存失败: {str(e)}"}), 500

    # 1. Overwrite the tmp file so raw/<file_id> still works for PDF.js etc.
    tmp_path = _ensure_tmp_dir() / f"{file_id}{suffix}"
    tmp_path.write_bytes(raw_bytes)
    logger.info(
        "[WorkspaceAssistant] auto_save tmp → %s (%d bytes)", tmp_path, len(raw_bytes)
    )

    # 2. Only write back to the original workspace file on explicit (user-triggered) saves.
    src_written = False
    if explicit and ws_source_path:
        try:
            from web.shared import WORKSPACE_DIR

            ws_root = Path(WORKSPACE_DIR).resolve()
            src_path = ws_root.joinpath(ws_source_path).resolve()
            # Path-traversal guard
            src_path.relative_to(ws_root)
            if src_path.suffix.lower() in _ALLOWED_EXT:
                src_path.parent.mkdir(parents=True, exist_ok=True)
                src_path.write_bytes(raw_bytes)
                src_written = True
                logger.info(
                    "[WorkspaceAssistant] auto_save src → %s (%d bytes)",
                    src_path,
                    len(raw_bytes),
                )
        except Exception as e:
            logger.warning(
                "[WorkspaceAssistant] auto_save: could not write source file: %s", e
            )
            if explicit:
                return jsonify({"error": f"保存失败: {str(e)}"}), 500

    saved_at = datetime.datetime.now().strftime("%H:%M")
    return jsonify({"ok": True, "saved_at": saved_at, "src_written": src_written})


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
        if old_target.is_dir():
            # Folder rename — no extension enforcement
            if not new_name:
                return jsonify({"error": "文件夹名无效"}), 400
            new_target = old_target.parent / new_name
            if new_target.exists():
                return jsonify({"error": "名称已存在"}), 409
            old_target.rename(new_target)
            new_rel = new_target.relative_to(root).as_posix()
            logger.info(f"[WorkspaceAssistant] 重命名文件夹: {old_path} -> {new_rel}")
            return jsonify({"ok": True, "path": new_rel, "name": new_name})
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


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/workspace/summarize  ?path=<relative_path>
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/summarize")
def summarize_workspace_file():
    """
    提取文件文本并通过 AI 生成 2-3 句摘要。
    支持 DOCX / XLSX / PPTX / PDF。
    ?path=relative/path/to/file.docx
    """
    import re

    from web.shared import WORKSPACE_DIR

    path = request.args.get("path", "").strip()
    if not path:
        return jsonify({"error": "缺少 path 参数"}), 400

    ws_root = Path(WORKSPACE_DIR).resolve()
    try:
        file_path = ws_root.joinpath(path).resolve()
        file_path.relative_to(ws_root)  # path-traversal guard
    except (ValueError, RuntimeError):
        return jsonify({"error": "非法路径"}), 400

    if not file_path.exists():
        return jsonify({"error": "文件不存在"}), 404

    ext = file_path.suffix.lower()
    if ext not in _ALLOWED_EXT:
        return jsonify({"error": "不支持此文件类型"}), 400

    # ── Extract plain text ─────────────────────────────────────────────────
    try:
        if ext == ".docx":
            from app.core.file.file_parser import parse_docx

            data = parse_docx(str(file_path))
            text = re.sub(r"<[^>]+>", " ", data.get("html", ""))
            text = re.sub(r"\s+", " ", text).strip()[:2000]

        elif ext == ".xlsx":
            from app.core.file.file_parser import parse_xlsx

            sheets = parse_xlsx(str(file_path))
            parts: list[str] = []
            for sheet in sheets[:2]:
                for row in (sheet.get("celldata") or [])[:80]:
                    v = row.get("v") or {}
                    val = v.get("v") if isinstance(v, dict) else None
                    if val is not None:
                        parts.append(str(val))
            text = " ".join(parts)[:2000]

        elif ext == ".pptx":
            from app.core.file.file_parser import parse_pptx

            slides = parse_pptx(str(file_path))
            parts = []
            for slide in slides[:6]:
                for shape in slide.get("texts", []):
                    parts.append(shape.get("text", ""))
            text = " ".join(parts)[:2000]

        elif ext == ".pdf":
            from app.core.file.file_parser import parse_pdf

            data = parse_pdf(str(file_path), str(uuid.uuid4()))
            pages = data.get("pages", [])
            text = " ".join(p.get("text", "") for p in pages[:4])[:2000]

        else:
            text = ""
    except Exception as e:
        logger.warning("[summarize] 提取文本失败 %s: %s", path, e)
        return jsonify({"error": "解析文件失败"}), 500

    text = text.strip()
    if not text:
        return jsonify({"summary": "（文件内容为空）", "path": path})

    # ── Call LLM for summary ───────────────────────────────────────────────
    # Use the app's get_client() — it inherits the proxy/relay config that
    # makes Gemini reachable in restricted regions (same client as main chat).
    try:
        from web.app import MODEL_MAP as _MM
        from web.app import get_client

        _DOC_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash-lite"]
        _model = _MM.get("CHAT") or _DOC_MODELS[0]
        # Interactions-only models can't do simple generate_content; use flash fallback
        if _model.startswith("deep-research"):
            _model = _DOC_MODELS[0]

        client = get_client()
        sum_prompt = (
            "请用2-3句话简洁概括以下文档内容，只输出摘要文字，不要解释或标题。\n\n"
            f"文档内容：{text}\n\n摘要："
        )
        response = client.models.generate_content(
            model=_model,
            contents=sum_prompt,
        )
        summary = (getattr(response, "text", None) or "").strip()
        if not summary:
            raise ValueError("AI 返回空内容")
        return jsonify({"summary": summary, "path": path})
    except Exception as e:
        logger.warning("[summarize] AI 摘要失败 %s: %s", path, e)
        return jsonify({"error": "AI 摘要暂不可用", "path": path})


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /api/v1/workspace/folder
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/folder", methods=["DELETE"])
def delete_workspace_folder():
    """
    递归删除工作区中的一个文件夹。
    Query param:  path=relative/path/to/folder
    """
    import shutil

    from web.shared import WORKSPACE_DIR

    root = Path(WORKSPACE_DIR).resolve()
    folderpath = request.args.get("path", "").strip()
    if not folderpath:
        return jsonify({"error": "缺少 path 参数"}), 400

    target = root.joinpath(folderpath).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return jsonify({"error": "路径不合法"}), 403

    if not target.is_dir():
        return jsonify({"error": "文件夹不存在"}), 404

    # Safety: never delete the workspace root itself
    if target == root:
        return jsonify({"error": "不能删除根工作区"}), 403

    shutil.rmtree(target)
    logger.info(f"[WorkspaceAssistant] 删除文件夹: {target}")
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/create_file
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/create_file", methods=["POST"])
def create_workspace_file():
    """
    在工作区指定目录创建一个新文件（空文件）。
    Body (JSON): {"folder": "relative/path", "name": "filename.txt"}
    folder 为 "" 时在工作区根目录创建。
    """
    import re

    from web.shared import WORKSPACE_DIR

    body = request.get_json(force=True, silent=True) or {}
    folder = (body.get("folder") or "").strip().strip("/")
    name = (body.get("name") or "").strip()

    # Validate name — must not contain path separators or forbidden chars
    if not name:
        return jsonify({"error": "文件名不能为空"}), 400
    if re.search(r'[/\\<>:"|?*\x00-\x1f]', name):
        return jsonify({"error": "文件名包含非法字符"}), 400

    root = Path(WORKSPACE_DIR).resolve()
    parent = root.joinpath(folder).resolve() if folder else root

    # Security: prevent path traversal
    try:
        parent.relative_to(root)
    except ValueError:
        return jsonify({"error": "路径不合法"}), 403

    if not parent.is_dir():
        return jsonify({"error": "目标目录不存在"}), 404

    target = parent / name
    if target.exists():
        return jsonify({"error": f'"{name}" 已存在'}), 409

    try:
        target.touch()
        rel = target.relative_to(root).as_posix()
        logger.info("[WorkspaceAssistant] 创建文件: %s", target)
        return jsonify({"ok": True, "path": rel, "name": name})
    except Exception as e:
        return jsonify({"error": f"创建失败: {e}"}), 500


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/create_folder
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/create_folder", methods=["POST"])
def create_workspace_folder():
    """
    在工作区指定目录创建一个新文件夹。
    Body (JSON): {"parent": "relative/path", "name": "foldername"}
    parent 为 "" 时在工作区根目录创建。
    """
    import re

    from web.shared import WORKSPACE_DIR

    body = request.get_json(force=True, silent=True) or {}
    parent_rel = (body.get("parent") or "").strip().strip("/")
    name = (body.get("name") or "").strip()

    if not name:
        return jsonify({"error": "文件夹名不能为空"}), 400
    if re.search(r'[/\\<>:"|?*\x00-\x1f]', name):
        return jsonify({"error": "文件夹名包含非法字符"}), 400

    root = Path(WORKSPACE_DIR).resolve()
    parent = root.joinpath(parent_rel).resolve() if parent_rel else root

    try:
        parent.relative_to(root)
    except ValueError:
        return jsonify({"error": "路径不合法"}), 403

    if not parent.is_dir():
        return jsonify({"error": "父目录不存在"}), 404

    target = parent / name
    if target.exists():
        return jsonify({"error": f'"{name}" 已存在'}), 409

    try:
        target.mkdir()
        rel = target.relative_to(root).as_posix()
        logger.info("[WorkspaceAssistant] 创建文件夹: %s", target)
        return jsonify({"ok": True, "path": rel, "name": name})
    except Exception as e:
        return jsonify({"error": f"创建失败: {e}"}), 500


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/set_workspace_dir
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/set_workspace_dir", methods=["POST"])
def set_workspace_dir_endpoint():
    """
    将工作区根目录切换到指定的本地文件夹。
    Body (JSON): {"path": "/absolute/path/to/folder"}
    持久化到 config/user_settings.json 并立即生效（无需重启）。
    """
    import json as _json

    body = request.get_json(force=True, silent=True) or {}
    new_path = (body.get("path") or "").strip()
    if not new_path:
        return jsonify({"error": "缺少 path 字段"}), 400

    target = Path(new_path).resolve()
    if not target.exists():
        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return jsonify({"error": f"无法创建目录: {e}"}), 400
    if not target.is_dir():
        return jsonify({"error": "路径不是文件夹"}), 400

    # Persist to user_settings.json
    from web.shared import PROJECT_ROOT, clear_user_settings_cache
    settings_path = Path(PROJECT_ROOT) / "config" / "user_settings.json"
    try:
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = _json.load(f)
        except Exception:
            settings = {}
        settings.setdefault("storage", {})["workspace_dir"] = str(target)
        with open(settings_path, "w", encoding="utf-8") as f:
            _json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return jsonify({"error": f"设置保存失败: {e}"}), 500

    # Invalidate cache and update live module variable (no restart needed)
    clear_user_settings_cache()
    import web.shared as _shared
    _shared.WORKSPACE_DIR = str(target)

    logger.info("[WorkspaceAssistant] 工作区已切换: %s", target)
    return jsonify({"ok": True, "path": str(target), "name": target.name})


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/chart-exec
# SSE endpoint for code/chart execution only.
# AI chat requests now go directly to /api/chat/stream from the frontend.
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/chart-exec", methods=["POST"])
def chart_exec():
    """
    Server-Sent Events endpoint for workspace AI requests.
    Accepts the same payload as the socket.io `doc_ai_request` event and
    streams events in SSE format so the frontend can consume them without
    needing socket.io at all.

    Body (JSON):
      prompt, context, selection, file_type, file_id, file_name,
      has_selection, history, language, csv_data, output_mode

    SSE Events (one JSON object per `data:` line):
      {"type":"progress","step":"analyzing"|"generating"|"formatting"|"complete","detail":"..."}
      {"type":"chunk","text":"..."}
      {"type":"proposals","proposals":[...],"summary":"..."}
      {"type":"tool_call","cmd":{...}}
      {"type":"complete","result":"...","has_proposals":bool}
      {"type":"error","message":"..."}
    """
    import json as _json
    import re
    import time

    body = request.get_json(force=True, silent=True) or {}
    prompt = body.get("prompt", "")
    context_text = body.get("context", "")
    selection = body.get("selection", "")
    file_type = body.get("file_type", "unknown")
    file_name = body.get("file_name", "")
    has_selection = bool(body.get("has_selection", False))
    history = body.get("history", [])
    language = body.get("language", "")
    csv_data = body.get("csv_data", "")
    output_mode = body.get("output_mode", "inline")

    if not prompt:
        return jsonify({"error": "缺少 prompt 字段"}), 400

    if context_text:
        prompt = f"{context_text}\n[用户请求]: {prompt}"

    def _sse(obj):
        return f"data: {_json.dumps(obj, ensure_ascii=False)}\n\n"

    def generate():
        try:
            from app.core.socket_handler import (
                _get_local_provider,
                _get_provider,
                _is_ollama_alive,
                _is_online_failure,
                _parse_tool_calls,
                _pick_online_model,
            )
        except ImportError as ie:
            yield _sse({"type": "error", "message": f"AI 模块加载失败: {ie}"})
            return

        # ── Code / chart execution mode ──────────────────────────────────────
        if language in ("python", "r"):
            try:
                from app.core.socket_handler import _call_llm_sync
                from app.core.sandbox import run_python, run_r
            except ImportError as ie2:
                yield _sse({"type": "error", "message": f"Sandbox 模块加载失败: {ie2}"})
                return

            lang_label = "Python (matplotlib/pandas)" if language == "python" else "R (ggplot2)"
            gen_prompt = (
                f"请根据以下任务，编写一段可以直接运行的 {lang_label} 代码。\n"
                "要求：\n"
                "1. 使用 matplotlib 或 pandas 绘图（Python）/ ggplot2（R）\n"
                "2. 将生成的图表保存为当前目录下的 chart.png 文件\n"
                "3. 对于 Python：使用 plt.savefig('chart.png', dpi=150, bbox_inches='tight')\n"
                "4. 对于 R：使用 ggsave('chart.png', dpi=150)\n"
                "5. 不要用 plt.show() 或任何 GUI 调用\n"
                "6. 只输出代码，不要任何 markdown 代码块标记（不要 ```）\n\n"
                f"任务描述：{prompt}\n"
            )
            if csv_data:
                gen_prompt += f"\n表格数据（CSV 格式）：\n{csv_data}\n"

            yield _sse({"type": "chunk", "text": f"🤖 正在为你生成 {language.upper()} 代码…\n"})

            code = _call_llm_sync(gen_prompt)
            if not code:
                yield _sse({"type": "code_result", "error": "AI 代码生成失败，请检查 API Key 配置。", "stdout": "", "stderr": "", "files": {}})
                yield _sse({"type": "complete", "result": "", "has_proposals": False})
                return

            import re as _re
            code = _re.sub(r"^```[a-z]*\n?", "", code.strip(), flags=_re.MULTILINE)
            code = code.strip().strip("`")

            yield _sse({"type": "chunk", "text": f"\n```{language}\n{code}\n```\n\n▶ 正在执行…\n"})

            if language == "python":
                result = run_python(code)
            else:
                result = run_r(code)

            yield _sse({"type": "code_result", **result})
            yield _sse({"type": "complete", "result": "", "has_proposals": False})
            return

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/quick-action
# Non-streaming quick text processing: polish, translate, summarize, etc.
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/quick-action", methods=["POST"])
def quick_action():
    """
    One-shot text processing for quick toolbar actions.
    Body: {action, text, file_type?}
    Response: {"result": "processed text", "original": "...", "action": "..."}
    """
    body = request.get_json(force=True, silent=True) or {}
    action = body.get("action", "")
    text = body.get("text", "")

    if not action or not text:
        return jsonify({"error": "缺少 action 或 text 字段"}), 400

    _PROMPTS = {
        "润色": (
            "请对以下文字进行润色优化，保持原意不变，使语言更流畅自然。"
            "直接输出润色后的文字，不要解释。\n\n"
        ),
        "翻译": (
            "请将以下文字翻译成另一种语言（中文→英文，英文→中文）。"
            "直接输出翻译结果，不要解释。\n\n"
        ),
        "总结": (
            "请对以下内容进行总结，提炼核心要点，简明扁要（不超过原文 1/3 长度）。"
            "直接输出总结内容，不要解释。\n\n"
        ),
        "续写": (
            "请根据以下内容的风格和主题进行续写，与原文保持一致的语气和格式。"
            "直接输出续写内容，不要解释。\n\n"
        ),
        "改写": (
            "请对以下文字进行改写，保持核心意思不变，但使用完全不同的表达方式和句式结构。"
            "直接输出改写后的文字，不要解释。\n\n"
        ),
        "解释": (
            "请对以下内容进行分析解释，说明其含义、背景或重要性，语言清晰易懂。"
            "直接输出解释内容，不要重复原文。\n\n"
        ),
    }

    # ── Chart visualization (sandboxed Python execution) ──
    if action in ("可视化", "chart"):
        lang = body.get("lang", "python").lower()
        task_desc = body.get("instruction", "") or "根据以下数据自动选择合适的图表类型并可视化"
        code_prompt = (
            "请根据以下任务，编写一段可以直接运行的 Python (matplotlib/pandas) 代码。\n"
            "要求：\n"
            "1. 包含所有必要的 import\n"
            "2. 在代码开头加入: import matplotlib; matplotlib.rcParams['font.sans-serif']=['SimHei','DejaVu Sans']; matplotlib.rcParams['axes.unicode_minus']=False\n"
            "3. 最后用 plt.savefig('chart.png', dpi=150, bbox_inches='tight') 保存，然后 plt.close()\n"
            "4. 绝对不要调用 plt.show()\n"
            "5. 只输出代码，不加任何 markdown 代码块标记\n\n"
            f"任务描述：{task_desc}\n"
            f"\n参考数据/文本：\n{text[:3000]}\n"
        )
        try:
            import re as _re
            from app.core.socket_handler import _call_llm_sync
            from app.core.sandbox import run_python

            raw_code = _call_llm_sync(code_prompt)
            if not raw_code:
                return jsonify({"error": "AI 代码生成失败，请检查 API Key 配置"}), 503
            raw_code = _re.sub(r"^```[a-z]*\n?", "", raw_code.strip(), flags=_re.MULTILINE)
            raw_code = raw_code.strip().strip("`").strip()
            result = run_python(raw_code)
            images = [
                {"name": name, "data": b64}
                for name, b64 in (result.get("files") or {}).items()
            ]
            return jsonify({
                "type": "chart_result",
                "code": raw_code,
                "images": images,
                "stdout": result.get("stdout", ""),
                "stderr": result.get("stderr", ""),
                "error": result.get("error"),
            })
        except Exception as exc:
            logger.error("[WorkspaceAI] chart failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    prompt_template = _PROMPTS.get(action)
    if not prompt_template:
        return jsonify({"error": f"不支持的操作: {action}"}), 400

    full_prompt = prompt_template + text
    try:
        from app.core.socket_handler import _call_llm_sync

        result = _call_llm_sync(full_prompt)
        if not result:
            return jsonify({"error": "AI 处理失败，请检查 API Key 配置"}), 503
        return jsonify({"result": result.strip(), "original": text, "action": action})
    except Exception as exc:
        logger.error("[WorkspaceAI] quick_action failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ─── Open file with native system application ─────────────────────────────────

@workspace_assistant_bp.route("/api/v1/workspace/open-native", methods=["POST"])
def api_open_native():
    """Open a file using the OS default application."""
    import subprocess, sys as _sys
    data = request.get_json(force=True, silent=True) or {}
    path = data.get("path", "").strip()
    if not path or not os.path.exists(path):
        return jsonify({"ok": False, "error": "路径不存在"}), 404
    try:
        if _sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif _sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ─── Browse local filesystem (lazy) ──────────────────────────────────────────

@workspace_assistant_bp.route("/api/v1/workspace/browse_local")
def browse_local():
    """
    Lazy filesystem browser — no WORKSPACE_DIR restriction.
    No path  → drives + quick-access locations (Windows) / home shortcuts (other).
    With path → all files and folders at that absolute path.
    """
    import sys as _sys

    path = request.args.get("path", "").strip()

    _openable = frozenset(_ALLOWED_EXT)

    def _file_category(ext: str) -> str:
        _MAP = {
            ".docx": "docx", ".doc": "docx",
            ".xlsx": "xlsx", ".xls": "xlsx",
            ".pptx": "pptx", ".ppt": "pptx",
            ".pdf": "pdf",
            ".txt": "text", ".md": "text", ".markdown": "text",
            ".py": "code", ".js": "code", ".ts": "code", ".json": "code",
            ".html": "code", ".css": "code", ".sh": "code", ".yaml": "code",
            ".png": "image", ".jpg": "image", ".jpeg": "image",
            ".gif": "image", ".svg": "image", ".webp": "image",
        }
        return _MAP.get(ext, "other")

    if not path:
        # Root level: drives + quick-access locations
        try:
            from web.blueprints.workspace import _list_drives, _quick_access_locations
            return jsonify({
                "is_root": True,
                "drives": _list_drives(),
                "quick_access": _quick_access_locations(),
            })
        except Exception as e:
            # Fallback: just return home dir
            home = Path.home()
            return jsonify({
                "is_root": True,
                "quick_access": [{"name": "主目录", "path": str(home), "type": "quick"}],
                "drives": [],
            })

    target = Path(path).resolve()
    if not target.exists():
        return jsonify({"error": "路径不存在"}), 404
    if not target.is_dir():
        return jsonify({"error": "不是文件夹"}), 400

    _SKIP = {
        "__pycache__", "node_modules", ".git", ".venv", "venv",
        "$RECYCLE.BIN", "System Volume Information",
    }

    entries: list[dict] = []
    try:
        for p in sorted(target.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
            if p.name.startswith(".") or p.name in _SKIP:
                continue
            if p.is_dir():
                entries.append({"name": p.name, "path": str(p), "type": "folder"})
            elif p.is_file():
                ext = p.suffix.lower()
                try:
                    st = p.stat()
                    sb = st.st_size
                    size_str = (
                        f"{sb}B" if sb < 1024
                        else f"{sb / 1024:.1f}KB" if sb < 1048576
                        else f"{sb / 1048576:.1f}MB"
                    )
                    mtime_ms = int(st.st_mtime * 1000)
                except OSError:
                    size_str = ""
                    mtime_ms = 0
                entries.append({
                    "name": p.name,
                    "path": str(p),
                    "type": "file",
                    "ext": ext.lstrip("."),
                    "size": size_str,
                    "mtime": mtime_ms,
                    "supported": ext in _openable,
                    "category": _file_category(ext),
                })
    except PermissionError:
        return jsonify({"error": "无访问权限", "entries": []}), 403

    parent = str(target.parent)
    if parent == str(target):
        parent = None  # Drive root (e.g. C:\)

    return jsonify({
        "is_root": False,
        "current": str(target),
        "parent": parent,
        "entries": entries,
    })


# ─── Serve any file by absolute path ─────────────────────────────────────────

@workspace_assistant_bp.route("/api/v1/workspace/serve_abs")
def serve_abs_file():
    """Return raw bytes of any file by absolute path (for file-system browser)."""
    path = request.args.get("path", "").strip()
    if not path:
        return jsonify({"error": "缺少 path 参数"}), 400
    target = Path(path).resolve()
    if not target.is_file():
        return jsonify({"error": "文件不存在"}), 404
    return send_file(str(target), as_attachment=False)


# ─── FS browser file operations (work on absolute paths) ──────────────────────

_FS_PROTECTED = {
    "windows", "program files", "program files (x86)", "programdata",
    "system volume information", "$recycle.bin",
}


def _fs_guard(p: Path) -> bool:
    """Return True if the path is safe to operate on (not a system root/dir)."""
    parts = {pp.lower() for pp in p.parts}
    if parts & _FS_PROTECTED:
        return False
    # Reject drive roots on Windows (e.g. C:\)
    if p == p.parent:
        return False
    return True


@workspace_assistant_bp.route("/api/v1/workspace/fs_delete", methods=["DELETE"])
def fs_delete():
    """
    Delete any file or folder by absolute path.
    Query param: path=<abs_path>
    """
    import shutil
    path = request.args.get("path", "").strip()
    if not path:
        return jsonify({"error": "缺少 path 参数"}), 400
    target = Path(path).resolve()
    if not _fs_guard(target):
        return jsonify({"error": "不允许删除系统路径"}), 403
    if not target.exists():
        return jsonify({"error": "路径不存在"}), 404
    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    except PermissionError:
        return jsonify({"error": "权限不足，无法删除"}), 403
    logger.info(f"[Browser] 删除: {target}")
    return jsonify({"ok": True})


@workspace_assistant_bp.route("/api/v1/workspace/fs_rename", methods=["PATCH"])
def fs_rename():
    """
    Rename file or folder by absolute path.
    Body (JSON): {"path": "<abs>", "name": "<new_name>"}
    """
    body = request.get_json(silent=True) or {}
    path = body.get("path", "").strip()
    new_name = body.get("name", "").strip()
    if not path or not new_name:
        return jsonify({"error": "缺少 path 或 name 参数"}), 400
    if "/" in new_name or "\\" in new_name:
        return jsonify({"error": "名称不能包含路径分隔符"}), 400
    target = Path(path).resolve()
    if not _fs_guard(target):
        return jsonify({"error": "不允许重命名系统路径"}), 403
    if not target.exists():
        return jsonify({"error": "路径不存在"}), 404
    # Preserve extension for files
    if target.is_file():
        stem = Path(new_name).stem or new_name
        final_name = stem + target.suffix.lower()
    else:
        final_name = new_name
    new_target = target.parent / final_name
    if new_target.exists():
        return jsonify({"error": "名称已存在"}), 409
    try:
        target.rename(new_target)
    except PermissionError:
        return jsonify({"error": "权限不足，无法重命名"}), 403
    logger.info(f"[Browser] 重命名: {target} -> {new_target}")
    return jsonify({"ok": True, "name": final_name, "path": str(new_target)})


@workspace_assistant_bp.route("/api/v1/workspace/fs_copy", methods=["POST"])
def fs_copy():
    """
    Copy or move a file/folder to a destination directory.
    Body (JSON): {"src": "<abs>", "dst_dir": "<abs_dir>", "move": false}
    """
    import shutil
    body = request.get_json(silent=True) or {}
    src = body.get("src", "").strip()
    dst_dir = body.get("dst_dir", "").strip()
    do_move = bool(body.get("move", False))
    if not src or not dst_dir:
        return jsonify({"error": "缺少 src 或 dst_dir 参数"}), 400
    src_path = Path(src).resolve()
    dst_path = Path(dst_dir).resolve()
    if not _fs_guard(src_path):
        return jsonify({"error": "不允许操作系统路径"}), 403
    if not src_path.exists():
        return jsonify({"error": "源路径不存在"}), 404
    if not dst_path.is_dir():
        return jsonify({"error": "目标不是有效文件夹"}), 400
    final = dst_path / src_path.name
    # Avoid overwriting
    if final.exists():
        base = src_path.stem
        ext = src_path.suffix
        n = 1
        while (dst_path / f"{base} ({n}){ext}").exists():
            n += 1
        final = dst_path / f"{base} ({n}){ext}"
    try:
        if do_move:
            shutil.move(str(src_path), str(final))
            op = "移动"
        else:
            if src_path.is_dir():
                shutil.copytree(str(src_path), str(final))
            else:
                shutil.copy2(str(src_path), str(final))
            op = "复制"
    except PermissionError:
        return jsonify({"error": "权限不足"}), 403
    logger.info(f"[Browser] {op}: {src_path} -> {final}")
    return jsonify({"ok": True, "name": final.name, "path": str(final)})
