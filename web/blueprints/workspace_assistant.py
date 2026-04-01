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
                if (
                    p.name.startswith(".")
                    or p.name.startswith("_")
                    or p.name in ("tmp", "backups", "editor-docs", "images")
                ):
                    continue

                rel_path = p.relative_to(root_path).as_posix()

                if p.is_dir():
                    children = _build_tree(p)
                    if children:
                        items.append(
                            {
                                "name": p.name,
                                "type": "folder",
                                "path": rel_path,
                                "children": children,
                            }
                        )
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
                    items.append(
                        {
                            "name": p.name,
                            "type": "file",
                            "ext": p.suffix.lower().replace(".", ""),
                            "path": rel_path,
                            "size": size_str,
                            "mtime": mtime_ms,
                        }
                    )
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

    # 持久化保存到 workspace/ 根目录（直接可见，无需子文件夹）
    # Skip copy if the file already lives in the workspace (opened via workspace panel).
    ws_path = request.form.get("ws_path", "").strip()
    if not ws_path:
        try:
            from web.shared import WORKSPACE_DIR

            root_dir = Path(WORKSPACE_DIR)
            root_dir.mkdir(parents=True, exist_ok=True)
            persistent_path = root_dir / original_name
            import shutil

            shutil.copy2(str(tmp_path), str(persistent_path))
        except Exception as pe:
            logger.warning(f"[WorkspaceAssistant] 持久化失败 {original_name}: {pe}")

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

    # 2. Write back to the original workspace file so re-opening loads latest content.
    src_written = False
    if ws_source_path:
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
