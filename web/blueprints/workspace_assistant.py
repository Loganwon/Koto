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

from flask import (
    Blueprint,
    Response,
    jsonify,
    request,
    send_file,
    session,
    stream_with_context,
)

logger = logging.getLogger(__name__)

workspace_assistant_bp = Blueprint("workspace_assistant", __name__)

# ─── Critical static asset check ─────────────────────────────────────────────
# Prevents silent failures when univer-dist bundle files are missing.
_CRITICAL_ASSETS = [
    Path("web") / "static" / "univer-dist" / "assets" / "sheets-main.js",
    Path("web") / "static" / "univer-dist" / "assets" / "sheets-main.css",
    Path("web") / "static" / "js" / "workspace-assistant.js",
]


def _check_critical_assets() -> list[str]:
    """Return list of missing critical asset paths."""
    missing = []
    for p in _CRITICAL_ASSETS:
        if not p.exists():
            missing.append(str(p))
    return missing


_missing_at_startup = _check_critical_assets()
if _missing_at_startup:
    logger.error(
        "⚠️  关键静态资源缺失！Excel 加载将失败。缺失文件: %s\n"
        "修复方法: 在 web/univer-editor/ 目录下执行 npm run build 重新构建，"
        "或使用 git checkout <commit> -- web/static/univer-dist/ 恢复。",
        ", ".join(_missing_at_startup),
    )

# 临时文件存储目录根。保持绝对路径，避免调用方切换 cwd 后解析到错误目录。
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_TMP_ROOT = _PROJECT_ROOT / "workspace" / "tmp"
# Backward-compatible hook used by older tests and callers that patch a fixed
# tmp directory. When left untouched, runtime uses session-scoped subdirs below.
_TMP_DIR = _TMP_ROOT
_DEFAULT_TMP_DIR = _TMP_DIR

# 纯文本 / 代码文件后缀（直接读取 UTF-8 内容）
_TEXT_EXTS = {
    ".txt",
    ".md",
    ".markdown",
    ".py",
    ".js",
    ".ts",
    ".json",
    ".html",
    ".css",
    ".xml",
    ".sh",
    ".bash",
    ".yaml",
    ".yml",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".java",
    ".rb",
    ".go",
    ".rs",
    ".cs",
    ".php",
    ".swift",
    ".kt",
    ".r",
    ".sql",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
}

# 图片文件后缀
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}

# 允许上传的文件后缀
_ALLOWED_EXT = {".docx", ".xlsx", ".pptx", ".pdf"} | _TEXT_EXTS | _IMAGE_EXTS
_EDITOR_OPEN_EXT = {".docx", ".xlsx", ".pptx", ".pdf"} | _IMAGE_EXTS


def _get_session_id() -> str:
    """Return a per-browser session ID, creating one if absent.

    This is the only isolation guarantor between users on a shared instance.
    The ID is stored in a signed Flask session cookie so it survives page reloads
    without a database.
    """
    sid = session.get("ws_session_id")
    if not sid:
        sid = uuid.uuid4().hex
        session["ws_session_id"] = sid
        session.permanent = True
    return sid


def _legacy_tmp_dir_override() -> Path | None:
    legacy_tmp = Path(globals().get("_TMP_DIR", _TMP_ROOT))
    if legacy_tmp != _DEFAULT_TMP_DIR:
        return legacy_tmp.resolve()
    return None


def _ensure_tmp_dir() -> Path:
    """Return an isolated tmp directory for the current browser session."""
    legacy_tmp = _legacy_tmp_dir_override()
    if legacy_tmp is not None:
        legacy_tmp.mkdir(parents=True, exist_ok=True)
        return legacy_tmp

    sid = _get_session_id()
    tmp_dir = _TMP_ROOT / sid
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return tmp_dir


def _tmp_workspace_relpath(file_id: str, ext: str) -> str:
    """Return the workspace-relative path for the current session temp file."""
    if _legacy_tmp_dir_override() is not None:
        return f"tmp/{file_id}{ext}"

    sid = _get_session_id()
    return f"tmp/{sid}/{file_id}{ext}"


def cleanup_tmp_dir(max_age_hours: int = 24) -> int:
    """Remove stale or empty workspace tmp files and return the delete count."""
    import time

    tmp_root = _legacy_tmp_dir_override() or _TMP_ROOT
    if not tmp_root.exists():
        return 0

    cutoff = time.time() - (max_age_hours * 3600)
    removed = 0
    for path in sorted(tmp_root.rglob("*"), reverse=True):
        try:
            if path.is_file():
                stat = path.stat()
                if stat.st_size == 0 or stat.st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass
        except OSError:
            logger.debug("[WorkspaceAssistant] failed to cleanup tmp path: %s", path)
    return removed


def _seed_new_file(target: Path) -> None:
    """Create a minimal valid file for formats that cannot be empty."""
    target.parent.mkdir(parents=True, exist_ok=True)
    ext = target.suffix.lower()

    if ext == ".docx":
        from docx import Document

        doc = Document()
        doc.add_paragraph("")
        doc.save(str(target))
        return

    if ext == ".xlsx":
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws["A1"] = ""
        wb.save(str(target))
        return

    if ext == ".pptx":
        from pptx import Presentation

        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        slide.shapes.title.text = "Untitled Presentation"
        if len(slide.placeholders) > 1:
            slide.placeholders[1].text = "Created by Koto"
        prs.save(str(target))
        return

    if ext == ".pdf":
        target.write_bytes(
            b"%PDF-1.4\n"
            b"1 0 obj\n<</Type /Catalog /Pages 2 0 R>>\nendobj\n"
            b"2 0 obj\n<</Type /Pages /Kids [3 0 R] /Count 1>>\nendobj\n"
            b"3 0 obj\n<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]>>\nendobj\n"
            b"trailer\n<</Root 1 0 R>>\n%%EOF\n"
        )
        return

    target.touch()


def _ext(filename: str) -> str:
    return Path(filename).suffix.lower()


def _tmp_file_path(file_id: str, ext: str) -> Path:
    return _ensure_tmp_dir() / f"{file_id}{ext}"


def _parse_docx_workspace_open(tmp_path: Path, file_id: str) -> dict:
    from app.core.file.file_parser import parse_docx

    data = parse_docx(str(tmp_path))
    data["raw_url"] = f"/api/v1/workspace/raw/{file_id}"
    return data


def _parse_pptx_workspace_file(tmp_path: Path) -> dict:
    parser = globals().get("parse_pptx_geometry")
    if parser is None:
        from app.core.file.file_parser import parse_pptx_geometry as parser

    parsed = parser(str(tmp_path.resolve()))
    slides = parsed.get("slides", []) if isinstance(parsed, dict) else []
    for i, slide in enumerate(slides):
        if not isinstance(slide, dict):
            continue
        slide.setdefault("index", slide.get("slide_index", i))
        for shape in slide.get("shapes", []):
            if isinstance(shape, dict) and "type" not in shape and "_type" in shape:
                shape["type"] = shape["_type"]
    return parsed


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/workspace/asset_health — verify critical static assets exist
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/asset_health")
def asset_health():
    """Quick check that all critical frontend assets are present on disk."""
    missing = _check_critical_assets()
    if missing:
        return jsonify({"ok": False, "missing": missing}), 500
    return jsonify({"ok": True, "missing": []})


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
    try:
        cleanup_tmp_dir()
    except Exception:
        logger.debug("[WorkspaceAssistant] tmp cleanup failed before listing files")

    # Extensions that Koto can open and parse
    _openable = frozenset(_EDITOR_OPEN_EXT)

    def _file_category(ext: str) -> str:
        _map = {
            ".docx": "docx",
            ".doc": "docx",
            ".xlsx": "xlsx",
            ".xls": "xlsx",
            ".pptx": "pptx",
            ".ppt": "pptx",
            ".pdf": "pdf",
            ".txt": "text",
            ".md": "text",
            ".markdown": "text",
            ".py": "code",
            ".js": "code",
            ".ts": "code",
            ".json": "code",
            ".html": "code",
            ".css": "code",
            ".sh": "code",
            ".yaml": "code",
            ".png": "image",
            ".jpg": "image",
            ".jpeg": "image",
            ".gif": "image",
            ".svg": "image",
            ".webp": "image",
        }
        return _map.get(ext, "other")

    def _build_tree(dir_path: Path) -> list[dict]:
        items = []
        _skip = {
            "tmp",
            "backups",
            "editor-docs",
            "images",
            "__pycache__",
            "node_modules",
            "ppt_sessions",
            ".git",
            ".venv",
            "venv",
        }
        try:
            for p in sorted(
                dir_path.iterdir(), key=lambda x: (x.is_file(), x.name.lower())
            ):
                if p.name.startswith(".") or p.name in _skip:
                    continue

                rel_path = p.relative_to(root_path).as_posix()

                if p.is_dir():
                    children = _build_tree(p)
                    items.append(
                        {
                            "name": p.name,
                            "type": "folder",
                            "path": rel_path,
                            "children": children,
                        }
                    )
                elif p.is_file():
                    ext = p.suffix.lower()
                    try:
                        stat = p.stat()
                        size_b = stat.st_size
                        size_str = (
                            f"{size_b}B"
                            if size_b < 1024
                            else (
                                f"{size_b / 1024:.1f}KB"
                                if size_b < 1048576
                                else f"{size_b / 1048576:.1f}MB"
                            )
                        )
                        mtime_ms = int(stat.st_mtime * 1000)
                    except OSError:
                        size_str = ""
                        mtime_ms = 0
                    items.append(
                        {
                            "name": p.name,
                            "type": "file",
                            "ext": ext.lstrip("."),
                            "path": rel_path,
                            "size": size_str,
                            "mtime": mtime_ms,
                            "supported": ext in _openable,
                            "category": _file_category(ext),
                        }
                    )
        except PermissionError:
            pass

        return items

    tree = _build_tree(root_path)
    return jsonify(
        {
            "name": root_path.name,
            "path": str(root_path),
            "type": "folder",
            "children": tree,
            "files": tree,
            "workspace_name": root_path.name,
            "workspace_path": str(root_path),
        }
    )


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

    if target.suffix.lower() not in _EDITOR_OPEN_EXT:
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
    if _has_traversal_path_part(rel_path):
        return jsonify({"error": "路径不合法"}), 403

    from web.shared import WORKSPACE_DIR

    root = Path(WORKSPACE_DIR).resolve()
    requested = Path(rel_path)
    source_path = rel_path
    if requested.is_absolute():
        target = requested.resolve()
        if _has_protected_path_part(rel_path, target):
            return jsonify({"error": "不允许访问系统目录"}), 403
        try:
            target.relative_to(_APP_CONFIG_DIR)
            return jsonify({"error": "不允许访问应用配置目录"}), 403
        except ValueError:
            pass
        if not _fs_guard(target):
            return jsonify({"error": "路径不合法"}), 403
        source_path = str(target)
    else:
        target = root.joinpath(rel_path).resolve()
        # Security: prevent path traversal
        try:
            target.relative_to(root)
        except ValueError:
            return jsonify({"error": "路径不合法"}), 403

    if not target.is_file():
        return jsonify({"error": "文件不存在"}), 404

    ext = target.suffix.lower()
    if ext not in _EDITOR_OPEN_EXT:
        return jsonify({"error": f"不支持的格式: {ext}"}), 400

    if requested.is_absolute():
        try:
            target.relative_to(root)
            outside_workspace = False
        except ValueError:
            outside_workspace = True
        if outside_workspace and target.stat().st_size == 0:
            return jsonify({"error": "路径不合法"}), 403

    if ext in {".docx", ".xlsx", ".pptx", ".pdf"} and target.stat().st_size == 0:
        try:
            _seed_new_file(target)
        except Exception as se:
            return jsonify({"error": f"文件自动修复失败: {se}"}), 500

    # Copy to tmp so editor can work with it (same as open_file)
    file_id = uuid.uuid4().hex
    tmp_path = _ensure_tmp_dir() / f"{file_id}{ext}"
    try:
        import shutil

        shutil.copy2(str(target), str(tmp_path))
    except Exception as ce:
        return jsonify({"error": f"文件复制失败: {ce}"}), 500

    try:
        from app.core.file.file_parser import parse_pdf, parse_xlsx

        if ext == ".docx":
            data = _parse_docx_workspace_open(tmp_path, file_id)
            html_len = len(data.get("html", ""))
            logger.info(
                f"[open_file_by_path] {target.name} 解析成功, HTML={html_len // 1024}KB, messages={data.get('messages', [])}"
            )
            file_type = "docx"
        elif ext == ".xlsx":
            data = parse_xlsx(str(tmp_path), original_name=target.name)
            file_type = "xlsx"
        elif ext == ".pptx":
            _pptx_size = tmp_path.stat().st_size
            if _pptx_size > 100 * 1024 * 1024:
                return (
                    jsonify(
                        {
                            "error": f"PPTX 文件过大 ({_pptx_size / 1048576:.0f} MB)，可能包含嵌入视频。"
                            f"Koto 当前不支持超过 100 MB 的 PPTX 文件，建议先在 PowerPoint 中删除视频后再打开。"
                        }
                    ),
                    413,
                )
            data = _parse_pptx_workspace_file(tmp_path)
            file_type = "pptx"
        elif ext == ".pdf":
            data = parse_pdf(str(tmp_path), file_id)
            file_type = "pdf"
        elif ext in _IMAGE_EXTS:
            file_type = "image"
            data = {"raw_url": f"/api/v1/workspace/raw/{file_id}"}
        elif ext in _TEXT_EXTS:
            content = target.read_text(encoding="utf-8", errors="replace")
            file_type = "text" if ext in (".txt", ".md", ".markdown") else "code"
            data = {"content": content, "language": ext.lstrip("."), "extension": ext}
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
            "ws_source_path": source_path,
            "temp_path": _tmp_workspace_relpath(file_id, ext),
            "data": data,
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/read_for_ai
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/read_for_ai", methods=["POST"])
def read_file_for_ai():
    """
    返回工作区文件的纯文本内容，供 AI 技能（file_diff_checker、excel_data_filler 等）
    在不打开编辑器的情况下读取其他文件。

    Body (JSON): {"path": "relative/path/to/file"}
    Response:
      {
        "text":      "<plain text content>",
        "file_type": "docx" | "xlsx" | "pptx" | "text" | ...,
        "name":      "filename.ext",
        "chars":     <int>
      }

    Security: path is resolved against WORKSPACE_DIR and must be inside it
    (path-traversal guard same as open_file_by_path).
    The endpoint returns at most 100 000 characters to prevent accidental
    memory dumps of huge binary files.
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
    _MAX_CHARS = 100_000

    try:
        if ext in _TEXT_EXTS:
            text = target.read_text(encoding="utf-8", errors="replace")
            file_type = "text"
        elif ext == ".docx":
            # Write a tmp copy so parser can open it
            _tmp = _ensure_tmp_dir() / f"{uuid.uuid4().hex}.docx"
            import shutil

            shutil.copy2(str(target), str(_tmp))
            try:
                from app.core.file.file_parser import parse_docx

                _d = parse_docx(str(_tmp))
                # Prefer plain text; fall back to stripping HTML tags
                raw_html = _d.get("html", "")
                import re as _re

                text = _re.sub(r"<[^>]+>", "", raw_html)
                file_type = "docx"
            finally:
                _tmp.unlink(missing_ok=True)
        elif ext == ".xlsx":
            _tmp = _ensure_tmp_dir() / f"{uuid.uuid4().hex}.xlsx"
            import shutil

            shutil.copy2(str(target), str(_tmp))
            try:
                from app.core.file.file_parser import parse_xlsx

                _d = parse_xlsx(str(_tmp), original_name=target.name)
                # Return CSV representation of each sheet
                sheets = _d.get("sheets", [])
                lines = []
                for sh in sheets:
                    lines.append(f"# Sheet: {sh.get('name', '?')}")
                    lines.append(sh.get("csv", ""))
                text = "\n".join(lines)
                file_type = "xlsx"
            finally:
                _tmp.unlink(missing_ok=True)
        elif ext == ".pptx":
            _tmp = _ensure_tmp_dir() / f"{uuid.uuid4().hex}.pptx"
            import shutil

            shutil.copy2(str(target), str(_tmp))
            try:
                from web.blueprints.pptx_editor import _parse_slides as _pptx_parse

                with open(str(_tmp), "rb") as _f:
                    _raw = _f.read()
                _d = _pptx_parse(_raw)
                slides = _d.get("slides", [])
                lines = []
                for i, sl in enumerate(slides):
                    lines.append(f"# Slide {i + 1}")
                    for shape in sl.get("shapes", []):
                        t = shape.get("text", "").strip()
                        if t:
                            lines.append(t)
                text = "\n".join(lines)
                file_type = "pptx"
            finally:
                _tmp.unlink(missing_ok=True)
        else:
            return jsonify({"error": f"不支持读取该格式作为 AI 文本: {ext}"}), 400

    except Exception as e:
        logger.error("[read_for_ai] 读取失败 %s: %s", target.name, e, exc_info=True)
        return jsonify({"error": f"读取失败: {e}"}), 500

    # Truncate to cap
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS] + f"\n…（内容过长，已截断至 {_MAX_CHARS} 字符）"

    return jsonify(
        {
            "text": text,
            "file_type": file_type,
            "name": target.name,
            "chars": len(text),
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

    if ext not in _EDITOR_OPEN_EXT:
        return (
            jsonify({"error": f"不支持的格式: {ext}，仅支持 {sorted(_ALLOWED_EXT)}"}),
            400,
        )

    # 暂存原始文件（用于 PDF.js raw 渲染等）
    file_id = uuid.uuid4().hex
    tmp_path = _ensure_tmp_dir() / f"{file_id}{ext}"
    uploaded.save(str(tmp_path))
    if tmp_path.stat().st_size == 0:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return jsonify({"error": f"文件为空，无法解析: {original_name}"}), 400

    # 文件只暂存在 tmp 目录，不立即写入工作区。
    # 用户显式保存后才会写入 WORKSPACE_DIR（由 auto_save explicit=true 处理）。
    ws_path = request.form.get("ws_path", "").strip()

    try:
        from app.core.file.file_parser import parse_pdf, parse_xlsx

        if ext == ".docx":
            data = _parse_docx_workspace_open(tmp_path, file_id)
            file_type = "docx"
        elif ext == ".xlsx":
            data = parse_xlsx(str(tmp_path), original_name=original_name)
            file_type = "xlsx"
        elif ext == ".pptx":
            _pptx_size = tmp_path.stat().st_size
            if _pptx_size > 100 * 1024 * 1024:
                return (
                    jsonify(
                        {
                            "error": f"PPTX 文件过大 ({_pptx_size / 1048576:.0f} MB)，可能包含嵌入视频。"
                            f"Koto 当前不支持超过 100 MB 的 PPTX 文件，建议先在 PowerPoint 中删除视频后再打开。"
                        }
                    ),
                    413,
                )
            data = _parse_pptx_workspace_file(tmp_path)
            file_type = "pptx"
        elif ext == ".pdf":
            data = parse_pdf(str(tmp_path), file_id)
            file_type = "pdf"
        elif ext in _IMAGE_EXTS:
            file_type = "image"
            data = {"raw_url": f"/api/v1/workspace/raw/{file_id}"}
        elif ext in _TEXT_EXTS:
            content = tmp_path.read_text(encoding="utf-8", errors="replace")
            file_type = "text" if ext in (".txt", ".md", ".markdown") else "code"
            data = {"content": content, "language": ext.lstrip("."), "extension": ext}
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
            "ws_source_path": ws_path or "",
            "temp_path": _tmp_workspace_relpath(file_id, ext),
            "data": data,
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/workspace/raw/<file_id>
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/raw/<path:file_id>")
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
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
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
            # Use original DOCX as template if available
            _orig = _ensure_tmp_dir() / f"{file_id}.docx" if file_id else None
            _orig_path = str(_orig) if _orig and _orig.is_file() else None
            raw_bytes = export_docx(data, original_path=_orig_path)
            mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if not file_name.endswith(".docx"):
                file_name = Path(file_name).stem + ".docx"

        elif file_type == "xlsx":
            # data is {snapshot: IWorkbookData, _images: []} from Univer frontend,
            # or a bare IWorkbookData dict.
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

        elif file_type in ("text", "code"):
            content = (
                data
                if isinstance(data, str)
                else (data.get("content", "") if isinstance(data, dict) else "")
            )
            raw_bytes = content.encode("utf-8")
            ext_guess = Path(file_name).suffix.lower() if file_name else ".txt"
            mime = (
                "text/markdown; charset=utf-8"
                if ext_guess == ".md"
                else "text/plain; charset=utf-8"
            )

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
# POST /api/v1/workspace/upload_image
# GET  /api/v1/workspace/tmp_image/<session_id>/<filename>
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/upload_image", methods=["POST"])
def upload_image():
    """
    Upload a chart/image data URI, save it as a session-scoped temp file, and
    return a stable server URL.

    Converting the multi-MB base64 string to a short server URL before inserting
    into WangEditor/Slate prevents the virtual DOM from bloating (which freezes
    the browser) and keeps the exported DOCX clean (the export pipeline can fetch
    the bytes from disk instead of embedding a giant base64 inline attribute).

    Body (JSON): {"data": "data:image/png;base64,..."}
    Returns:     {"ok": true, "url": "/api/v1/workspace/tmp_image/{sid}/{uuid}.png"}
    """
    import base64 as _b64
    import mimetypes as _mime

    body = request.get_json(force=True, silent=True) or {}
    data_uri = body.get("data", "")
    if not isinstance(data_uri, str) or not data_uri.startswith("data:image/"):
        return jsonify({"error": "无效的图片数据 (须为 data:image/... URI)"}), 400

    # Parse: data:image/png;base64,<b64_payload>
    try:
        header, _, b64_str = data_uri.partition(",")
        mime = header.split(":")[1].split(";")[0]  # e.g. "image/png"
        img_bytes = _b64.b64decode(b64_str)
    except Exception:
        return jsonify({"error": "图片数据解码失败"}), 400

    if len(img_bytes) > 10 * 1024 * 1024:
        return jsonify({"error": "图片大小超过 10 MB 限制"}), 413

    # Map MIME type to a safe file extension
    ext = _mime.guess_extension(mime) or ".png"
    if ext in (".jpe", ".jfif"):
        ext = ".jpg"
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
        ext = ".png"

    # Save to session-scoped tmp/images/ directory
    img_id = uuid.uuid4().hex
    sid = _get_session_id()
    img_dir = _TMP_ROOT / sid / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    img_path = img_dir / f"{img_id}{ext}"
    img_path.write_bytes(img_bytes)

    url = f"/api/v1/workspace/tmp_image/{sid}/{img_id}{ext}"
    logger.debug("[upload_image] saved %d bytes → %s", len(img_bytes), url)
    return jsonify({"ok": True, "url": url})


@workspace_assistant_bp.route("/api/v1/workspace/save_to_workspace", methods=["POST"])
def save_to_workspace():
    """
    Save an AI-generated asset (image or file) directly into the workspace
    directory so it appears in the file tree.

    Body (JSON) — image mode:
      {"type": "image",
       "src_url": "/api/v1/workspace/tmp_image/<sid>/<uuid.png>",
       "filename": "chart.png"}

    Body (JSON) — file mode:
      {"type": "file",
       "data": "<base64-encoded bytes>",
       "filename": "修改后_foo.docx"}

    Returns: {"ok": true, "ws_path": "images/chart.png"}
    """
    import base64 as _b64
    import shutil

    body = request.get_json(force=True, silent=True) or {}
    asset_type = body.get("type", "")
    filename = (body.get("filename") or "").strip()

    # Validate filename: no path separators
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return jsonify({"error": "无效的文件名"}), 400

    from web.shared import WORKSPACE_DIR

    ws_root = Path(WORKSPACE_DIR).resolve()

    if asset_type == "image":
        src_url = body.get("src_url", "")
        # Expected: /api/v1/workspace/tmp_image/<session_id>/<filename>
        prefix = "/api/v1/workspace/tmp_image/"
        if not src_url.startswith(prefix):
            return jsonify({"error": "无效的图片 URL"}), 400
        parts = src_url[len(prefix) :].split("/")
        if len(parts) != 2:
            return jsonify({"error": "无效的图片路径"}), 400
        sid, img_fname = parts
        # Validate both components
        if len(sid) != 32 or not all(c in "0123456789abcdef" for c in sid):
            return jsonify({"error": "无效的 session_id"}), 400
        if not img_fname or "/" in img_fname or "\\" in img_fname or ".." in img_fname:
            return jsonify({"error": "无效的图片文件名"}), 400
        src_path = (_TMP_ROOT / sid / "images" / img_fname).resolve()
        try:
            src_path.relative_to(_TMP_ROOT.resolve())
        except ValueError:
            return jsonify({"error": "路径非法"}), 403
        if not src_path.is_file():
            return jsonify({"error": "临时图片不存在或已过期"}), 404
        dest_dir = ws_root / "images"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = _unique_path(dest_dir, filename)
        shutil.copy2(str(src_path), str(dest))

    elif asset_type == "file":
        data_b64 = body.get("data", "")
        if not data_b64:
            return jsonify({"error": "缺少 data 字段"}), 400
        try:
            file_bytes = _b64.b64decode(data_b64)
        except Exception:
            return jsonify({"error": "数据解码失败"}), 400
        if len(file_bytes) > 50 * 1024 * 1024:
            return jsonify({"error": "文件大小超过 50 MB"}), 413
        ext = Path(filename).suffix.lower()
        if ext not in _ALLOWED_EXT:
            return jsonify({"error": f"不支持的格式: {ext}"}), 400
        dest = _unique_path(ws_root, filename)
        dest.write_bytes(file_bytes)

    else:
        return jsonify({"error": "type 须为 image 或 file"}), 400

    ws_rel = str(dest.relative_to(ws_root)).replace("\\", "/")
    logger.info("[save_to_workspace] saved %s → %s", asset_type, ws_rel)
    return jsonify({"ok": True, "ws_path": ws_rel})


def _unique_path(directory: Path, filename: str) -> Path:
    """Return a non-colliding path inside directory, appending _1, _2 … as needed."""
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    i = 1
    while True:
        candidate = directory / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


@workspace_assistant_bp.route("/api/v1/workspace/tmp_image/<session_id>/<filename>")
def serve_tmp_image(session_id: str, filename: str):
    """
    Serve a previously uploaded temp image file by its session-scoped URL.
    Both session_id and filename are validated to prevent path traversal.
    """
    # Validate session_id: must be exactly 32 lowercase hex characters (uuid4().hex)
    if len(session_id) != 32 or not all(c in "0123456789abcdef" for c in session_id):
        return jsonify({"error": "无效的 session_id"}), 400
    # Validate filename: no path separators or parent-dir references
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return jsonify({"error": "无效的文件名"}), 400

    img_path = (_TMP_ROOT / session_id / "images" / filename).resolve()
    # Path-traversal guard (belt-and-suspenders)
    try:
        img_path.relative_to(_TMP_ROOT.resolve())
    except ValueError:
        return jsonify({"error": "路径非法"}), 403

    if not img_path.is_file():
        return jsonify({"error": "图片不存在或已过期"}), 404

    _mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }
    mime = _mime_map.get(img_path.suffix.lower(), "image/png")
    resp = send_file(str(img_path), mimetype=mime)
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


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
    if ws_source_path and not Path(str(ws_source_path)).is_absolute():
        rel_parts = [p for p in str(ws_source_path).replace("\\", "/").split("/") if p]
        if any(part == ".." for part in rel_parts):
            return jsonify({"error": "路径不合法"}), 403

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
            _orig = _ensure_tmp_dir() / f"{file_id}.docx" if file_id else None
            _orig_path = str(_orig) if _orig and _orig.is_file() else None
            raw_bytes = export_docx(data, original_path=_orig_path)
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
        elif file_type in ("text", "code"):
            content = (
                data
                if isinstance(data, str)
                else (data.get("content", "") if isinstance(data, dict) else "")
            )
            raw_bytes = content.encode("utf-8")
            # Derive the original extension from the tmp file
            tmp_dir = _ensure_tmp_dir()
            existing = [
                f
                for f in tmp_dir.glob(f"{file_id}.*")
                if f.suffix.lower() in _TEXT_EXTS
            ]
            suffix = existing[0].suffix.lower() if existing else ".txt"
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
            raw_source_path = str(ws_source_path)
            raw_path = Path(raw_source_path).expanduser()
            is_external_abs = raw_path.is_absolute()
            if is_external_abs:
                src_path = raw_path.resolve()
                if _has_protected_path_part(raw_source_path, src_path):
                    return jsonify({"error": "路径不合法"}), 403
            else:
                src_path = ws_root.joinpath(raw_source_path).resolve()
                src_path.relative_to(ws_root)

            if src_path.suffix.lower() in _ALLOWED_EXT and (
                not is_external_abs or src_path.parent.exists()
            ):
                src_path.parent.mkdir(parents=True, exist_ok=True)
                src_path.write_bytes(raw_bytes)
                src_written = True
                logger.info(
                    "[WorkspaceAssistant] auto_save src → %s (%d bytes)",
                    src_path,
                    len(raw_bytes),
                )
                # 3. Sync file registry so FileHub shows updated mtime & preview.
                try:
                    from app.core.file.file_registry import get_file_registry

                    _reg = get_file_registry()
                    _reg.batch_register(
                        [str(src_path)], source="editor", extract_content=False
                    )
                    logger.debug(
                        "[WorkspaceAssistant] auto_save registry synced: %s",
                        src_path.name,
                    )
                except Exception as _re:
                    logger.debug(
                        "[WorkspaceAssistant] auto_save registry sync skipped: %s", _re
                    )
                # 4. Version snapshot — keep last 10 versions per file.
                try:
                    snap_dir = src_path.parent / ".koto_versions" / src_path.stem
                    snap_dir.mkdir(parents=True, exist_ok=True)
                    ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    snap_path = snap_dir / f"{ts_str}{suffix}"
                    snap_path.write_bytes(raw_bytes)
                    snaps = sorted(snap_dir.glob(f"*{suffix}"))
                    for old_snap in snaps[:-10]:
                        old_snap.unlink(missing_ok=True)
                    logger.debug(
                        "[WorkspaceAssistant] version snapshot: %s", snap_path.name
                    )
                except Exception as _ve:
                    logger.debug(
                        "[WorkspaceAssistant] version snapshot failed: %s", _ve
                    )
        except Exception as e:
            logger.warning(
                "[WorkspaceAssistant] auto_save: could not write source file: %s", e
            )
            if explicit and not Path(str(ws_source_path)).is_absolute():
                return jsonify({"error": f"保存失败: {str(e)}"}), 500

    saved_at = datetime.datetime.now().strftime("%H:%M")
    return jsonify({"ok": True, "saved_at": saved_at, "src_written": src_written})


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/workspace/versions   — list version snapshots for a file
# POST /api/v1/workspace/restore-version — restore a snapshot
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/versions", methods=["GET"])
def list_versions():
    """
    列出文件的历史版本快照。
    Query: path=relative/path/to/file.docx
    Returns: {"versions": [{name, snap_path, saved_at, size_bytes}]}
    """
    from web.shared import WORKSPACE_DIR

    rel = request.args.get("path", "").strip()
    if not rel:
        return jsonify({"error": "缺少 path 参数"}), 400

    ws_root = Path(WORKSPACE_DIR).resolve()
    src = ws_root.joinpath(rel).resolve()
    try:
        src.relative_to(ws_root)
    except ValueError:
        return jsonify({"error": "路径非法"}), 400

    snap_dir = src.parent / ".koto_versions" / src.stem
    if not snap_dir.is_dir():
        return jsonify({"versions": []})

    suffix = src.suffix.lower()
    snaps = sorted(snap_dir.glob(f"*{suffix}"), reverse=True)
    result = []
    for s in snaps[:20]:
        try:
            stat = s.stat()
            result.append(
                {
                    "name": s.name,
                    "snap_path": str(s),
                    "saved_at": s.stem.replace("_", " "),
                    "size_bytes": stat.st_size,
                }
            )
        except Exception:
            pass
    return jsonify({"versions": result})


@workspace_assistant_bp.route("/api/v1/workspace/restore-version", methods=["POST"])
def restore_version():
    """
    将版本快照恢复为当前文件。
    Body JSON: { "snap_path": "abs/path/to/snapshot.docx", "target_path": "relative/target.docx" }
    """
    import shutil

    from web.shared import WORKSPACE_DIR

    body = request.get_json(force=True, silent=True) or {}
    snap_path_str = body.get("snap_path", "").strip()
    target_rel = body.get("target_path", "").strip()
    if not snap_path_str or not target_rel:
        return jsonify({"error": "缺少 snap_path 或 target_path"}), 400

    snap = Path(snap_path_str)
    if not snap.is_file():
        return jsonify({"error": "快照文件不存在"}), 404

    ws_root = Path(WORKSPACE_DIR).resolve()
    target = ws_root.joinpath(target_rel).resolve()
    try:
        target.relative_to(ws_root)
    except ValueError:
        return jsonify({"error": "target_path 非法"}), 400
    if target.suffix.lower() not in _ALLOWED_EXT:
        return jsonify({"error": "不支持的格式"}), 400

    try:
        shutil.copy2(str(snap), str(target))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"ok": True, "restored_to": str(target)})


@workspace_assistant_bp.route("/api/v1/workspace/checkpoint", methods=["POST"])
def create_checkpoint():
    """
    Create a pre-agent checkpoint for a file (Step 4.3).
    Body JSON: { "path": "relative/path/to/file.docx", "label": "agent_pre" }
    Returns: { "ok": true, "snap_path": "..." }
    """
    import shutil

    from web.shared import WORKSPACE_DIR

    body = request.get_json(force=True, silent=True) or {}
    rel = body.get("path", "").strip()
    label = body.get("label", "agent_pre")
    if not rel:
        return jsonify({"error": "缺少 path 参数"}), 400

    ws_root = Path(WORKSPACE_DIR).resolve()
    src = ws_root.joinpath(rel).resolve()
    try:
        src.relative_to(ws_root)
    except ValueError:
        return jsonify({"error": "路径非法"}), 400

    if not src.is_file():
        return jsonify({"error": "文件不存在"}), 404

    suffix = src.suffix.lower()
    snap_dir = src.parent / ".koto_versions" / src.stem
    snap_dir.mkdir(parents=True, exist_ok=True)
    ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    snap_path = snap_dir / f"{ts_str}_{label}{suffix}"
    try:
        shutil.copy2(str(src), str(snap_path))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"ok": True, "snap_path": str(snap_path), "target_path": rel})


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
    if _has_traversal_path_part(filepath):
        return jsonify({"error": "路径不合法"}), 403

    target = root.joinpath(filepath).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return jsonify({"error": "路径不合法"}), 403

    if not target.is_file():
        return jsonify({"error": "文件不存在"}), 404

    try:
        try:
            from send2trash import send2trash
        except ImportError:
            send2trash = None

        if send2trash is not None:
            send2trash(str(target))
            logger.info(f"[WorkspaceAssistant] 将文件放入回收站: {target}")
        else:
            target.unlink()
            logger.info(f"[WorkspaceAssistant] 直接删除文件: {target}")
    except Exception as e:
        logger.error(f"[WorkspaceAssistant] 移动文件到回收站失败: {e}")
        target.unlink(missing_ok=True)
        logger.info(f"[WorkspaceAssistant] 直接删除文件: {target}")

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

        _DOC_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
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

    try:
        try:
            from send2trash import send2trash
        except ImportError:
            send2trash = None

        if send2trash is not None:
            send2trash(str(target))
            logger.info(f"[WorkspaceAssistant] 将文件夹放入回收站: {target}")
        else:
            shutil.rmtree(target)
            logger.info(f"[WorkspaceAssistant] 直接删除文件夹: {target}")
    except Exception as e:
        logger.error(f"[WorkspaceAssistant] 移动文件夹到回收站失败: {e}")
        shutil.rmtree(target, ignore_errors=True)
        logger.info(f"[WorkspaceAssistant] 直接删除文件夹: {target}")

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
        _seed_new_file(target)
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
    if _has_protected_path_part(new_path, target):
        return jsonify({"error": "不允许将系统目录设为工作区"}), 403
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
# GET /api/v1/workspace/ollama-status
# Check if local Ollama is running and which models are available.
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/ollama-status")
def ollama_status():
    """Return {running: bool, model: str|null, models: [str]}."""
    try:
        import requests as _req

        r = _req.get(
            "http://127.0.0.1:11434/api/tags",
            timeout=3,
            proxies={"http": None, "https": None},  # bypass system proxy for localhost
        )
        data = r.json()
        models = [m["name"] for m in data.get("models", [])]
        if not models:
            return jsonify({"running": True, "model": None, "models": []})

        # 1. Prefer the model configured in user_settings.json
        try:
            import json as _js
            import os as _os

            from web.shared import PROJECT_ROOT as _PR

            _cfg_path = _os.path.join(_PR, "config", "user_settings.json")
            with open(_cfg_path, "r", encoding="utf-8") as _f:
                _cfg = _js.load(_f)
            _configured = (
                _cfg.get("local_model") or _cfg.get("ai", {}).get("local_model") or ""
            ).strip()
            if _configured and _configured in models:
                return jsonify(
                    {"running": True, "model": _configured, "models": models}
                )
        except Exception:
            pass

        # 2. Fall back to size-based preference (include 9b)
        preferred = next(
            (
                m
                for m in models
                if any(
                    k in m.lower()
                    for k in ("9b", "7b", "8b", "13b", "14b", "32b", "70b")
                )
            ),
            models[0],
        )
        return jsonify({"running": True, "model": preferred, "models": models})
    except Exception:
        return jsonify({"running": False, "model": None, "models": []})


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/quick-action
# Non-streaming quick text processing: polish, translate, summarize, etc.
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/quick-action", methods=["POST"])
def quick_action():
    """
    One-shot text processing for quick toolbar actions.
    Body: {action, text, file_type?, locked_model?}
    Response: {"result": "processed text", "original": "...", "action": "..."}
    """
    body = request.get_json(force=True, silent=True) or {}
    action = body.get("action", "")
    text = body.get("text", "")
    full_text = body.get("full_text", "")  # full document for RAG context
    locked_model = body.get("locked_model", "auto")

    # Respect use_local_only setting if caller didn't explicitly set locked_model
    if locked_model == "auto":
        try:
            from web.settings import SettingsManager as _WSM

            if _WSM().get("ai", "use_local_only"):
                locked_model = "local"
        except Exception:
            pass

    # Accept both Chinese and English action keys from different frontend entry points.
    _action_aliases = {
        "polish": "润色",
        "translate": "翻译",
        "summarize": "总结",
        "summary": "总结",
        "continue": "续写",
        "rewrite": "改写",
        "explain": "解释",
        "visualize": "可视化",
    }
    if isinstance(action, str):
        action = _action_aliases.get(action.strip().lower(), action)

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
        task_desc = (
            body.get("instruction", "") or "根据以下数据自动选择合适的图表类型并可视化"
        )
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

            from app.core.sandbox import run_python
            from app.core.socket_handler import (
                _get_local_provider,
                _get_provider,
                _is_ollama_alive,
                _is_online_failure,
                _pick_online_model,
            )

            chart_used_local = False
            if locked_model == "local":
                if not _is_ollama_alive():
                    return (
                        jsonify({"error": "本地 Ollama 未运行，请先启动 Ollama 服务"}),
                        503,
                    )
                local = _get_local_provider()
                raw = local.generate_content(prompt=code_prompt, stream=False)
                raw_code = raw.get("content", "") if isinstance(raw, dict) else str(raw)
                chart_used_local = True
            else:
                raw_code = None
                try:
                    provider = _get_provider()
                    raw = provider.generate_content(
                        prompt=code_prompt,
                        model=_pick_online_model(),
                        stream=False,
                    )
                    raw_code = (
                        raw.get("content", "") if isinstance(raw, dict) else str(raw)
                    )
                except Exception as _ce:
                    if _is_online_failure(_ce):
                        logger.warning(
                            "[WorkspaceAI] chart cloud unavailable, trying local…"
                        )
                    else:
                        raise
                if not raw_code:
                    if not _is_ollama_alive():
                        return (
                            jsonify({"error": "AI 代码生成失败，请检查 API Key 配置"}),
                            503,
                        )
                    local = _get_local_provider()
                    raw = local.generate_content(prompt=code_prompt, stream=False)
                    raw_code = (
                        raw.get("content", "") if isinstance(raw, dict) else str(raw)
                    )
                    chart_used_local = True
            if not raw_code:
                return jsonify({"error": "AI 代码生成失败，请检查 API Key 配置"}), 503
            raw_code = _re.sub(
                r"^```[a-z]*\n?", "", raw_code.strip(), flags=_re.MULTILINE
            )
            raw_code = raw_code.strip().strip("`").strip()
            result = run_python(raw_code)
            images = [
                {"name": name, "data": b64}
                for name, b64 in (result.get("files") or {}).items()
            ]
            return jsonify(
                {
                    "type": "chart_result",
                    "code": raw_code,
                    "images": images,
                    "stdout": result.get("stdout", ""),
                    "stderr": result.get("stderr", ""),
                    "error": result.get("error"),
                    "used_local_model": chart_used_local,
                }
            )
        except Exception as exc:
            logger.error("[WorkspaceAI] chart failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    prompt_template = _PROMPTS.get(action)
    if not prompt_template:
        return jsonify({"error": f"不支持的操作: {action}"}), 400

    # Build document context via RAG if full_text is provided and long
    _rag_info = None
    doc_context_prefix = ""
    if full_text:
        try:
            from app.core.file.doc_chunker import DocChunker as _DC

            if len(full_text) > _DC.CHUNK_THRESHOLD:
                _chunks = _DC.chunk(full_text)
                _retrieved = _DC.retrieve(_chunks, query=text, top_k=4)
                doc_context_prefix = (
                    f"[文档上下文（RAG检索，共{len(_chunks)}段，已检索{len(_retrieved)}段）]\n"
                    + "\n\n---\n\n".join(_retrieved)
                    + "\n\n"
                )
                _rag_info = {
                    "total_chunks": len(_chunks),
                    "retrieved_chunks": len(_retrieved),
                }
            else:
                doc_context_prefix = f"[文档内容]\n{full_text}\n\n"
        except Exception:
            pass

    full_prompt = doc_context_prefix + prompt_template + text
    # ── EditorAIPipeline: PII filter + skill injection ────────────────────────
    _qa_mask_result = None
    _qa_skill_ids: list = []
    _qa_force_local = False
    try:
        from app.core.editor_ai_pipeline import EditorAIPipeline

        _qa_ft = (body.get("file_type") or "").lower().strip()
        _qa_pipeline = EditorAIPipeline.preprocess(
            prompt=full_prompt,
            history=[],
            file_type=_qa_ft,
            output_mode="edit",
            base_system_instruction="",
            user_input_raw=text,
        )
        full_prompt = _qa_pipeline.safe_prompt
        _qa_mask_result = _qa_pipeline.mask_result
        _qa_skill_ids = _qa_pipeline.skill_ids
        _qa_force_local = _qa_pipeline.force_local
        # Privacy routing disabled — PII masking is sufficient
        # if _qa_force_local and locked_model == "auto":
        #     locked_model = "local"
    except Exception as _qpe:
        logger.debug("[WorkspaceAI] EditorAIPipeline.preprocess skipped: %s", _qpe)
    try:
        from app.core.socket_handler import (
            _call_llm_sync,
            _get_local_provider,
            _get_provider,
            _is_ollama_alive,
            _is_online_failure,
            _pick_online_model,
        )

        if locked_model == "local":
            if not _is_ollama_alive():
                return (
                    jsonify({"error": "本地 Ollama 未运行，请先启动 Ollama 服务"}),
                    503,
                )
            local = _get_local_provider()
            raw = local.generate_content(prompt=full_prompt, stream=False)
            result = raw.get("content", "") if isinstance(raw, dict) else str(raw)
            used_local = True
        else:
            # Try cloud first, fall back to local
            result = None
            used_local = False
            try:
                provider = _get_provider()
                raw = provider.generate_content(
                    prompt=full_prompt,
                    model=_pick_online_model(),
                    stream=False,
                )
                result = raw.get("content", "") if isinstance(raw, dict) else str(raw)
            except Exception as _ce:
                if _is_online_failure(_ce):
                    logger.warning(
                        "[WorkspaceAI] cloud unavailable (%s), trying local…", _ce
                    )
                else:
                    raise
            if not result:
                if not _is_ollama_alive():
                    return (
                        jsonify(
                            {"error": "AI 处理失败，请检查 API Key 配置或 Ollama 状态"}
                        ),
                        503,
                    )
                local = _get_local_provider()
                raw = local.generate_content(prompt=full_prompt, stream=False)
                result = raw.get("content", "") if isinstance(raw, dict) else str(raw)
                used_local = True

        if not result:
            return (
                jsonify({"error": "AI 处理失败，请检查 API Key 配置或 Ollama 状态"}),
                503,
            )

        # ── EditorAIPipeline: PII restore + output validation + suggestions ──
        _qa_suggestions = []
        try:
            from app.core.editor_ai_pipeline import EditorAIPipeline

            _qa_post = EditorAIPipeline.postprocess(
                response_text=result,
                mask_result=_qa_mask_result,
                skill_ids=_qa_skill_ids,
                user_prompt=text,
                file_type=(body.get("file_type") or ""),
            )
            result = _qa_post.text
            _qa_suggestions = _qa_post.suggestions
            if _qa_post.validation_action == "BLOCK":
                result = _qa_post.text  # already replaced with safe message
        except Exception as _qpoe:
            logger.debug(
                "[WorkspaceAI] EditorAIPipeline.postprocess skipped: %s", _qpoe
            )

        resp = {
            "result": result.strip(),
            "original": text,
            "action": action,
            "used_local_model": used_local,
        }
        if _rag_info:
            resp["rag_info"] = _rag_info
        if _qa_suggestions:
            resp["skill_suggestions"] = _qa_suggestions
        return jsonify(resp)
    except Exception as exc:
        logger.error("[WorkspaceAI] quick_action failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ─── Open file with native system application ─────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/open-native", methods=["POST"])
def api_open_native():
    """Open a file using the OS default application."""
    import subprocess
    import sys as _sys

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

    _openable = frozenset(_EDITOR_OPEN_EXT)

    def _file_category(ext: str) -> str:
        _MAP = {
            ".docx": "docx",
            ".doc": "docx",
            ".xlsx": "xlsx",
            ".xls": "xlsx",
            ".pptx": "pptx",
            ".ppt": "pptx",
            ".pdf": "pdf",
            ".txt": "text",
            ".md": "text",
            ".markdown": "text",
            ".py": "code",
            ".js": "code",
            ".ts": "code",
            ".json": "code",
            ".html": "code",
            ".css": "code",
            ".sh": "code",
            ".yaml": "code",
            ".png": "image",
            ".jpg": "image",
            ".jpeg": "image",
            ".gif": "image",
            ".svg": "image",
            ".webp": "image",
        }
        return _MAP.get(ext, "other")

    if not path:
        # Root level: drives + quick-access locations
        try:
            from web.blueprints.workspace import _list_drives, _quick_access_locations

            return jsonify(
                {
                    "is_root": True,
                    "drives": _list_drives(),
                    "quick_access": _quick_access_locations(),
                }
            )
        except Exception as e:
            # Fallback: just return home dir
            home = Path.home()
            return jsonify(
                {
                    "is_root": True,
                    "quick_access": [
                        {"name": "主目录", "path": str(home), "type": "quick"}
                    ],
                    "drives": [],
                }
            )

    target = Path(path).resolve()
    if not target.exists():
        return jsonify({"error": "路径不存在"}), 404
    if not target.is_dir():
        return jsonify({"error": "不是文件夹"}), 400

    _SKIP = {
        "__pycache__",
        "node_modules",
        ".git",
        ".venv",
        "venv",
        "ppt_sessions",
        "$RECYCLE.BIN",
        "System Volume Information",
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
                        f"{sb}B"
                        if sb < 1024
                        else (
                            f"{sb / 1024:.1f}KB"
                            if sb < 1048576
                            else f"{sb / 1048576:.1f}MB"
                        )
                    )
                    mtime_ms = int(st.st_mtime * 1000)
                except OSError:
                    size_str = ""
                    mtime_ms = 0
                entries.append(
                    {
                        "name": p.name,
                        "path": str(p),
                        "type": "file",
                        "ext": ext.lstrip("."),
                        "size": size_str,
                        "mtime": mtime_ms,
                        "supported": ext in _openable,
                        "category": _file_category(ext),
                    }
                )
    except PermissionError:
        return jsonify({"error": "无访问权限", "entries": []}), 403

    parent = str(target.parent)
    if parent == str(target):
        parent = None  # Drive root (e.g. C:\)

    return jsonify(
        {
            "is_root": False,
            "current": str(target),
            "parent": parent,
            "entries": entries,
        }
    )


# ─── Serve any file by absolute path ─────────────────────────────────────────

# Application config directory — must never be served over the API
_APP_CONFIG_DIR = (Path(__file__).resolve().parents[2] / "config").resolve()
_PROTECTED_PATH_PARTS = {
    "etc",
    "root",
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "system volume information",
    "$recycle.bin",
}


def _has_traversal_path_part(raw_path: str) -> bool:
    import re

    return any(part == ".." for part in re.split(r"[\\/]+", str(raw_path or "")))


def _has_protected_path_part(raw_path: str, resolved: Path | None = None) -> bool:
    import re

    raw_parts = {
        part.strip().lower()
        for part in re.split(r"[\\/]+", str(raw_path or ""))
        if part.strip()
    }
    if raw_parts & _PROTECTED_PATH_PARTS:
        return True
    if resolved is not None:
        resolved_parts = {part.lower() for part in resolved.parts}
        if resolved_parts & _PROTECTED_PATH_PARTS:
            return True
    return False


@workspace_assistant_bp.route("/api/v1/workspace/serve_abs")
def serve_abs_file():
    """Return raw bytes of any file by absolute path (for file-system browser)."""
    path = request.args.get("path", "").strip()
    if not path:
        return jsonify({"error": "缺少 path 参数"}), 400
    target = Path(path).resolve()
    if _has_protected_path_part(path, target):
        return jsonify({"error": "不允许访问系统目录"}), 403
    # Block access to the application config directory (contains secrets/tokens)
    try:
        target.relative_to(_APP_CONFIG_DIR)
        return jsonify({"error": "不允许访问应用配置目录"}), 403
    except ValueError:
        pass
    if not target.is_file():
        return jsonify({"error": "文件不存在"}), 404
    return send_file(str(target), as_attachment=False)


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/open_abs_file
# ─────────────────────────────────────────────────────────────────────────────

# Video extensions stored inside PPTX/DOCX ZIP packages
_PPTX_VIDEO_EXTS = frozenset(
    {
        ".mp4",
        ".mov",
        ".wmv",
        ".avi",
        ".m4v",
        ".mkv",
        ".flv",
        ".webm",
        ".asf",
        ".mpg",
        ".mpeg",
    }
)


@workspace_assistant_bp.route("/api/v1/workspace/open_abs_file", methods=["POST"])
def open_abs_file():
    """
    Parse a file by absolute path — server reads directly from disk, no browser round-trip.
    This replaces the old serve_abs → blob → Router.load flow for browser-opened files.
    Includes fast ZIP pre-scan to reject PPTX/DOCX containing embedded video before
    any heavy parsing begins.

    Body (JSON): {"path": "/absolute/path/to/file.pptx"}
    Response: same format as open_file
    """
    body = request.get_json(force=True, silent=True) or {}
    abs_path = (body.get("path") or "").strip()
    if not abs_path:
        return jsonify({"error": "缺少 path 字段"}), 400

    target = Path(abs_path).resolve()

    # Security: block config dir and system dirs
    try:
        target.relative_to(_APP_CONFIG_DIR)
        return jsonify({"error": "不允许访问应用配置目录"}), 403
    except ValueError:
        pass
    if not _fs_guard(target):
        return jsonify({"error": "路径不合法"}), 403

    if not target.is_file():
        return jsonify({"error": "文件不存在"}), 404

    ext = target.suffix.lower()
    if ext not in _ALLOWED_EXT:
        return jsonify({"error": f"不支持的格式: {ext}"}), 400

    file_size = target.stat().st_size

    # ── PPTX pre-flight checks (must run BEFORE copying or reading file bytes) ──
    if ext == ".pptx":
        # 1. Fast ZIP scan for embedded video — reads only central directory (~milliseconds)
        import zipfile as _zipfile

        _found_video = None
        try:
            with _zipfile.ZipFile(str(target)) as _zf:
                for _zname in _zf.namelist():
                    if Path(_zname).suffix.lower() in _PPTX_VIDEO_EXTS:
                        _found_video = Path(_zname).name
                        break
        except Exception:
            pass
        if _found_video:
            logger.warning(
                "[open_abs_file] PPTX contains video %s, rejecting", _found_video
            )
            return (
                jsonify(
                    {
                        "error": (
                            f"该 PPTX 包含嵌入视频（{_found_video}），Koto 当前不支持含视频的 PPTX 文件。\n"
                            f"请先在 PowerPoint 中选中视频 → 删除 → 另存为，然后重新打开。"
                        )
                    }
                ),
                415,
            )
        # 2. Size guard (no video found but still very large → likely huge images)
        if file_size > 50 * 1024 * 1024:
            return (
                jsonify(
                    {
                        "error": f"PPTX 文件过大（{file_size / 1048576:.0f} MB），Koto 限制 50 MB。"
                        f"建议压缩图片后重试。"
                    }
                ),
                413,
            )

    # Copy to session tmp dir (parser works on a sandboxed copy)
    file_id = uuid.uuid4().hex
    tmp_path = _ensure_tmp_dir() / f"{file_id}{ext}"
    try:
        import shutil

        shutil.copy2(str(target), str(tmp_path))
    except Exception as ce:
        return jsonify({"error": f"文件读取失败: {ce}"}), 500

    try:
        from app.core.file.file_parser import parse_pdf, parse_xlsx

        if ext == ".docx":
            data = _parse_docx_workspace_open(tmp_path, file_id)
            file_type = "docx"
        elif ext == ".xlsx":
            data = parse_xlsx(str(tmp_path), original_name=target.name)
            file_type = "xlsx"
        elif ext == ".pptx":
            data = _parse_pptx_workspace_file(tmp_path)
            file_type = "pptx"
        elif ext == ".pdf":
            data = parse_pdf(str(tmp_path), file_id)
            file_type = "pdf"
        elif ext in _IMAGE_EXTS:
            file_type = "image"
            data = {"raw_url": f"/api/v1/workspace/raw/{file_id}"}
        elif ext in _TEXT_EXTS:
            content = target.read_text(encoding="utf-8", errors="replace")
            file_type = "text" if ext in (".txt", ".md", ".markdown") else "code"
            data = {
                "content": content,
                "language": ext.lstrip("."),
                "extension": ext.lstrip("."),
            }
        else:
            return jsonify({"error": "内部格式路由错误"}), 500

    except Exception as e:
        logger.error("[open_abs_file] 解析失败 %s: %s", target.name, e, exc_info=True)
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


@workspace_assistant_bp.route("/api/v1/workspace/docx_full", methods=["POST"])
def load_full_docx():
    """Hydrate a preview-opened DOCX to its full HTML payload."""
    body = request.get_json(force=True, silent=True) or {}
    file_id = (body.get("file_id") or "").strip()
    if not file_id:
        return jsonify({"error": "缺少 file_id 字段"}), 400

    tmp_path = _tmp_file_path(file_id, ".docx")
    if not tmp_path.is_file():
        return jsonify({"error": "DOCX 临时文件不存在或已过期"}), 404

    try:
        from app.core.file.file_parser import parse_docx

        data = parse_docx(str(tmp_path))
        data["raw_url"] = f"/api/v1/workspace/raw/{file_id}"
    except Exception as exc:
        logger.error(
            "[load_full_docx] 完整解析失败 %s: %s", file_id, exc, exc_info=True
        )
        return jsonify({"error": f"DOCX 完整加载失败: {exc}"}), 500

    return jsonify({"file_id": file_id, "file_type": "docx", "data": data})


# ─── FS browser file operations (work on absolute paths) ──────────────────────

_FS_PROTECTED = _PROTECTED_PATH_PARTS


def _fs_guard(p: Path) -> bool:
    """Return True if the path is safe to operate on (not a system root/dir)."""
    parts = {pp.lower() for pp in p.parts}
    if parts & _FS_PROTECTED:
        return False
    # Reject drive roots on Windows (e.g. C:\)
    if p == p.parent:
        return False
    # Protect application config directory (contains JWT secrets, token data, etc.)
    try:
        p.relative_to(_APP_CONFIG_DIR)
        return False
    except ValueError:
        pass
    return True


@workspace_assistant_bp.route("/api/v1/fs/create_file", methods=["POST"])
def fs_create_file():
    body = request.get_json(force=True, silent=True) or {}
    parent_raw = (body.get("parent") or "").strip()
    name = (body.get("name") or "").strip()
    if not parent_raw or not name:
        return jsonify({"error": "缺少 parent 或 name 字段"}), 400
    if any(sep in name for sep in ("/", "\\")) or "\x00" in name:
        return jsonify({"error": "文件名不合法"}), 400

    parent = Path(parent_raw).expanduser().resolve()
    if not _fs_guard(parent):
        return jsonify({"error": "路径不安全"}), 403
    if not parent.exists():
        return jsonify({"error": "父目录不存在"}), 404
    if not parent.is_dir():
        return jsonify({"error": "parent 不是目录"}), 400

    target = (parent / name).resolve()
    if not _fs_guard(target):
        return jsonify({"error": "路径不安全"}), 403
    if target.exists():
        return jsonify({"error": f'"{name}" 已存在'}), 409
    if target.suffix.lower() not in _ALLOWED_EXT:
        return jsonify({"error": f"不支持的格式: {target.suffix.lower()}"}), 400

    try:
        _seed_new_file(target)
        return jsonify({"ok": True, "path": str(target), "name": name})
    except Exception as exc:
        return jsonify({"error": f"创建失败: {exc}"}), 500


@workspace_assistant_bp.route("/api/v1/fs/create_folder", methods=["POST"])
def fs_create_folder():
    body = request.get_json(force=True, silent=True) or {}
    parent_raw = (body.get("parent") or "").strip()
    name = (body.get("name") or "").strip()
    if not parent_raw or not name:
        return jsonify({"error": "缺少 parent 或 name 字段"}), 400
    if any(sep in name for sep in ("/", "\\")) or "\x00" in name:
        return jsonify({"error": "文件夹名不合法"}), 400

    parent = Path(parent_raw).expanduser().resolve()
    if not _fs_guard(parent):
        return jsonify({"error": "路径不安全"}), 403
    if not parent.exists():
        return jsonify({"error": "父目录不存在"}), 404
    if not parent.is_dir():
        return jsonify({"error": "parent 不是目录"}), 400

    target = (parent / name).resolve()
    if not _fs_guard(target):
        return jsonify({"error": "路径不安全"}), 403
    if target.exists():
        return jsonify({"error": f'"{name}" 已存在'}), 409

    try:
        target.mkdir()
        return jsonify({"ok": True, "path": str(target), "name": name})
    except Exception as exc:
        return jsonify({"error": f"创建失败: {exc}"}), 500


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/patch_file
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/patch_file", methods=["POST"])
def patch_file():
    """
    Apply text-replacement proposals to an existing file and return the patched
    file for browser download.  Used by the multi-document content-sync feature
    so AI-generated proposals can be exported without modifying disk.

    Body (JSON):
      {
        "path":      "/absolute/or/workspace-relative/path/to/file.docx",
        "proposals": [
          {"original_text": "...", "proposed_text": "..."},
          ...
        ]
      }

    Supported formats: .docx, .txt, .md
    Returns: patched file binary (Content-Disposition: attachment)
    """
    import io as _io

    body = request.get_json(force=True, silent=True) or {}
    raw_path = (body.get("path") or "").strip()
    proposals = body.get("proposals") or []

    if not raw_path:
        return jsonify({"error": "缺少 path 字段"}), 400
    if not proposals:
        return jsonify({"error": "缺少 proposals 字段"}), 400

    # Resolve to an absolute path; try workspace-relative first, then absolute
    target: "Path | None" = None
    candidate = Path(raw_path)
    if candidate.is_absolute() and candidate.is_file():
        target = candidate.resolve()
    else:
        try:
            from web.shared import WORKSPACE_DIR

            ws_root = Path(WORKSPACE_DIR).resolve()
            rel_try = ws_root.joinpath(raw_path).resolve()
            if rel_try.is_file():
                target = rel_try
        except Exception:
            pass

    if target is None:
        return jsonify({"error": "文件不存在或路径无效"}), 404

    ext = target.suffix.lower()
    file_name = target.name

    if ext not in (".docx", ".txt", ".md"):
        return (
            jsonify(
                {
                    "error": f"暂不支持对 {ext} 格式进行文本修补，请使用 .docx / .txt / .md"
                }
            ),
            400,
        )

    # Only include well-formed proposals
    clean = [
        p
        for p in proposals
        if isinstance(p, dict)
        and (p.get("original_text") or "").strip()
        and (p.get("proposed_text") or "").strip()
    ]
    if not clean:
        return jsonify({"error": "proposals 中没有有效的修改条目"}), 400

    # ── DOCX: python-docx paragraph / table cell replacement ─────────────────
    if ext == ".docx":
        try:
            from docx import Document

            doc = Document(str(target))

            def _replace_in_para(para, orig: str, new: str) -> bool:
                """Replace *orig* with *new* inside *para*, preserving run structure."""
                full = para.text
                if orig not in full:
                    return False
                # Fast path: orig lives entirely inside a single run
                for run in para.runs:
                    if orig in run.text:
                        run.text = run.text.replace(orig, new)
                        return True
                # Slow path: orig spans multiple runs — rebuild first run, clear rest
                new_full = full.replace(orig, new, 1)
                if para.runs:
                    para.runs[0].text = new_full
                    for run in para.runs[1:]:
                        run.text = ""
                return True

            def _replace_all(orig: str, new: str):
                for para in doc.paragraphs:
                    _replace_in_para(para, orig, new)
                for table in doc.tables:
                    for row in table.rows:
                        for cell in row.cells:
                            for para in cell.paragraphs:
                                _replace_in_para(para, orig, new)

            for p in clean:
                orig = p["original_text"].strip()
                new = p["proposed_text"].strip()
                _replace_all(orig, new)

            buf = _io.BytesIO()
            doc.save(buf)
            buf.seek(0)
            return send_file(
                buf,
                mimetype="application/"
                "vnd.openxmlformats-officedocument.wordprocessingml.document",
                as_attachment=True,
                download_name=f"修改后_{file_name}",
            )
        except ImportError:
            return (
                jsonify(
                    {"error": "python-docx 未安装，请执行: pip install python-docx"}
                ),
                500,
            )
        except Exception as exc:
            logger.error("[patch_file] DOCX 修补失败: %s", exc, exc_info=True)
            return jsonify({"error": f"DOCX 修补失败: {str(exc)}"}), 500

    # ── TXT / MD: plain string replacement ───────────────────────────────────
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        for p in clean:
            content = content.replace(
                p["original_text"].strip(), p["proposed_text"].strip(), 1
            )
        buf = _io.BytesIO(content.encode("utf-8"))
        mime = (
            "text/markdown; charset=utf-8"
            if ext == ".md"
            else "text/plain; charset=utf-8"
        )
        return send_file(
            buf, mimetype=mime, as_attachment=True, download_name=f"修改后_{file_name}"
        )
    except Exception as exc:
        logger.error("[patch_file] TXT/MD 修补失败: %s", exc, exc_info=True)
        return jsonify({"error": f"文本修补失败: {str(exc)}"}), 500


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/audio_overview
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/audio_overview", methods=["POST"])
def audio_overview():
    """
    Generate a two-host podcast audio overview from a set of files.

    Body JSON:
      { "files": [{"name": "...", "content": "..."}], "session_id": "..." }

    SSE stream:
      {"event": "script",    "data": [{speaker, text}, ...]}
      {"event": "progress",  "data": "合成音频…"}
      {"event": "audio_url", "data": "/static/audio_cache/podcast_xxx.mp3"}
      {"event": "error",     "data": "…"}
    """
    import asyncio
    import uuid as _uuid

    body = request.get_json(force=True, silent=True) or {}
    files = body.get("files") or []
    if not files:
        return jsonify({"error": "缺少 files 字段"}), 400

    combined_text = "\n\n".join(
        f"=== {f.get('name', '文件')} ===\n{f.get('content', '')}" for f in files
    )[:20000]

    session_id = body.get("session_id") or _uuid.uuid4().hex[:12]

    def _generate():
        import json as _json

        try:
            from web.app import MODEL_MAP as _MM
            from web.app import get_client
            from web.audio_overview import AudioOverviewGenerator

            client = get_client()

            # Pick a suitable model
            _model = _MM.get("CHAT") or "gemini-2.5-flash-lite"
            if _model.startswith("deep-research"):
                _model = "gemini-2.5-flash-lite"

            # Build a simple wrapper that AudioOverviewGenerator expects
            class _ModelAdapter:
                def generate_content(self, prompt):
                    resp = client.models.generate_content(model=_model, contents=prompt)
                    return resp

            gen = AudioOverviewGenerator(
                output_dir=os.path.join(
                    os.path.dirname(os.path.dirname(__file__)), "static", "audio_cache"
                )
            )

            loop = asyncio.new_event_loop()
            script = loop.run_until_complete(
                gen.generate_script(combined_text, _ModelAdapter())
            )
            if not script:
                yield f"data: {_json.dumps({'event': 'error', 'data': '脚本生成失败，请重试'}, ensure_ascii=False)}\n\n"
                return

            yield f"data: {_json.dumps({'event': 'script', 'data': script}, ensure_ascii=False)}\n\n"

            # Attempt TTS synthesis
            try:
                audio_path = loop.run_until_complete(
                    gen.synthesize_audio(script, session_id)
                )
                loop.close()
                if audio_path and os.path.exists(audio_path):
                    audio_url = "/static/audio_cache/" + os.path.basename(audio_path)
                    yield f"data: {_json.dumps({'event': 'audio_url', 'data': audio_url}, ensure_ascii=False)}\n\n"
                else:
                    yield f"data: {_json.dumps({'event': 'audio_url', 'data': None}, ensure_ascii=False)}\n\n"
            except Exception as tts_err:
                loop.close()
                logger.warning("[audio_overview] TTS 失败: %s", tts_err)
                yield f"data: {_json.dumps({'event': 'audio_url', 'data': None}, ensure_ascii=False)}\n\n"

        except Exception as exc:
            logger.error("[audio_overview] 失败: %s", exc, exc_info=True)
            yield f"data: {_json.dumps({'event': 'error', 'data': str(exc)}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(_generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/notebook_guide
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/notebook_guide", methods=["POST"])
def notebook_guide():
    """
    Generate a 4-section study guide (学习包) from attached files.

    Body JSON:
      { "files": [{"name": "...", "content": "..."}] }

    SSE stream (one event per section):
      {"section": "summary",  "content": "..."}
      {"section": "points",   "content": "..."}
      {"section": "faq",      "content": "..."}
      {"section": "glossary", "content": "..."}
      {"section": "done"}
      {"section": "error",    "content": "..."}
    """
    body = request.get_json(force=True, silent=True) or {}
    files = body.get("files") or []
    if not files:
        return jsonify({"error": "缺少 files 字段"}), 400

    combined_text = "\n\n".join(
        f"=== {f.get('name', '文件')} ===\n{f.get('content', '')}" for f in files
    )[:24000]

    SECTIONS = [
        (
            "summary",
            "执行摘要",
            "请用200-300字对以下资料进行执行摘要，抓住核心结论和关键数据，不要逐条列点。",
        ),
        (
            "points",
            "关键要点",
            "请从以下资料中提炼5-8条关键要点，每条以「·」开头，包含具体数据或结论，不要泛泛而谈。",
        ),
        (
            "faq",
            "常见问答",
            "请根据以下资料生成5个读者最可能提出的问题及详细解答，格式：Q: 问题\nA: 解答",
        ),
        (
            "glossary",
            "核心词汇",
            "请从以下资料中提取8-12个专业术语或核心概念，每个词汇后附一句简洁定义，格式：**词汇** — 定义",
        ),
    ]

    def _generate():
        import json as _json

        try:
            from web.app import MODEL_MAP as _MM
            from web.app import get_client

            client = get_client()
            _model = _MM.get("CHAT") or "gemini-2.5-flash-lite"
            if _model.startswith("deep-research"):
                _model = "gemini-2.5-flash-lite"

            for sec_key, sec_label, sec_prompt in SECTIONS:
                full_prompt = (
                    f"{sec_prompt}\n\n"
                    f"资料内容（共 {len(files)} 个文件）:\n{combined_text}"
                )
                try:
                    resp = client.models.generate_content(
                        model=_model, contents=full_prompt
                    )
                    content = (getattr(resp, "text", None) or "").strip()
                    if not content:
                        content = "（AI 暂无回复）"
                except Exception as sec_err:
                    content = f"（生成失败: {sec_err}）"

                yield f"data: {_json.dumps({'section': sec_key, 'label': sec_label, 'content': content}, ensure_ascii=False)}\n\n"

            yield f"data: {_json.dumps({'section': 'done'}, ensure_ascii=False)}\n\n"

        except Exception as exc:
            logger.error("[notebook_guide] 失败: %s", exc, exc_info=True)
            yield f"data: {_json.dumps({'section': 'error', 'content': str(exc)}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(_generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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


# ─── Upload external file(s) straight into a folder ──────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/upload-to-folder", methods=["POST"])
def upload_to_folder():
    """
    Receive one or more uploaded files and write them into a target folder.
    Form fields:
      dest_dir   — absolute path of the destination folder (required)
      file       — one or more file uploads (required)
    Returns: {"ok": True, "saved": [{"name": ..., "path": ...}, ...]}
    """
    import werkzeug.utils as _wz

    dest_dir = (request.form.get("dest_dir") or "").strip()
    if not dest_dir:
        return jsonify({"error": "缺少 dest_dir 参数"}), 400

    dst = Path(dest_dir).resolve()
    if not _fs_guard(dst):
        return jsonify({"error": "不允许操作系统路径"}), 403
    if not dst.is_dir():
        return jsonify({"error": "目标不是有效文件夹"}), 400

    uploaded_files = request.files.getlist("file")
    if not uploaded_files:
        return jsonify({"error": "没有收到文件"}), 400

    saved = []
    for f in uploaded_files:
        raw_name = _wz.secure_filename(f.filename or "file")
        if not raw_name:
            continue
        target = dst / raw_name
        # Avoid overwriting existing file
        if target.exists():
            stem = Path(raw_name).stem
            ext = Path(raw_name).suffix
            n = 1
            while (dst / f"{stem} ({n}){ext}").exists():
                n += 1
            target = dst / f"{stem} ({n}){ext}"
        try:
            f.save(str(target))
            saved.append({"name": target.name, "path": str(target)})
            logger.info("[Browser] upload-to-folder: %s -> %s", f.filename, target)
        except PermissionError:
            return jsonify({"error": f"权限不足，无法写入 {target.name}"}), 403

    return jsonify({"ok": True, "saved": saved})


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/pdf/save_annotations
# POST /api/v1/workspace/pdf/load_annotations/<file_id>
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route(
    "/api/v1/workspace/pdf/save_annotations", methods=["POST"]
)
def pdf_save_annotations():
    """
    Embed client-side annotations into the PDF binary and return the modified file
    for download.

    Body (JSON):
      {
        "file_id": str,          — tmp file identifier (hex)
        "annotations": [...],    — array of annotation objects from KotoPdfViewer
        "filename": str          — original filename (used for download name)
      }

    Returns the annotated PDF as an attachment.
    """
    body = request.get_json(silent=True) or {}
    file_id = str(body.get("file_id", ""))
    annotations = body.get("annotations", [])
    filename = body.get("filename", "annotated.pdf")

    # Sanitize file_id: only allow alphanumeric
    if not file_id.isalnum():
        return jsonify({"error": "无效的 file_id"}), 400

    tmp_dir = _ensure_tmp_dir()
    matches = list(tmp_dir.glob(f"{file_id}.pdf"))
    if not matches:
        # Also try without extension
        matches = list(tmp_dir.glob(f"{file_id}.*"))
        matches = [m for m in matches if m.suffix.lower() == ".pdf"]
    if not matches:
        return jsonify({"error": "找不到 PDF 文件"}), 404

    pdf_path = str(matches[0])

    try:
        from web.pdf_annotator import embed_annotations

        pdf_bytes = embed_annotations(pdf_path, annotations)
    except Exception as exc:
        logger.error("[pdf_save_annotations] 注释嵌入失败: %s", exc, exc_info=True)
        return jsonify({"error": f"注释嵌入失败: {str(exc)}"}), 500

    import io as _io

    buf = _io.BytesIO(pdf_bytes)
    safe_name = filename if filename.lower().endswith(".pdf") else filename + ".pdf"
    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=safe_name,
    )


@workspace_assistant_bp.route(
    "/api/v1/workspace/pdf/load_annotations/<file_id>", methods=["GET"]
)
def pdf_load_annotations(file_id: str):
    """
    Read annotations embedded in a cached PDF and return them as JSON.

    Returns:
      {"annotations": [...]}
    """
    if not file_id.isalnum():
        return jsonify({"error": "无效的 file_id"}), 400

    tmp_dir = _ensure_tmp_dir()
    matches = [m for m in tmp_dir.glob(f"{file_id}.*") if m.suffix.lower() == ".pdf"]
    if not matches:
        return jsonify({"error": "找不到 PDF 文件"}), 404

    pdf_path = str(matches[0])

    try:
        from web.pdf_annotator import read_annotations

        annotations = read_annotations(pdf_path)
    except Exception as exc:
        logger.error("[pdf_load_annotations] 批注读取失败: %s", exc, exc_info=True)
        return jsonify({"error": f"批注读取失败: {str(exc)}"}), 500

    return jsonify({"annotations": annotations})


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/pdf/page_ops
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route("/api/v1/workspace/pdf/page_ops", methods=["POST"])
def pdf_page_ops():
    """
    Reconstruct a PDF with pages in the requested order / rotation.
    Used by the Page Manager for reorder, rotate, delete, and split (export subset).

    Body (JSON):
      {
        "file_id": str,   — tmp file identifier (hex)
        "pages": [{"orig_page": int, "rotation": int}, ...]
      }

    Returns the new PDF as an attachment.
    """
    body = request.get_json(silent=True) or {}
    file_id = str(body.get("file_id", ""))
    pages = body.get("pages", [])

    if not file_id.isalnum():
        return jsonify({"error": "无效的 file_id"}), 400
    if not pages:
        return jsonify({"error": "pages 不能为空"}), 400

    tmp_dir = _ensure_tmp_dir()
    matches = [m for m in tmp_dir.glob(f"{file_id}.*") if m.suffix.lower() == ".pdf"]
    if not matches:
        return jsonify({"error": "找不到 PDF 文件"}), 404

    pdf_path = str(matches[0])
    orig_name = matches[0].name

    try:
        from web.pdf_annotator import apply_page_ops

        pdf_bytes = apply_page_ops(pdf_path, pages)
    except Exception as exc:
        logger.error("[pdf_page_ops] 页面操作失败: %s", exc, exc_info=True)
        return jsonify({"error": f"页面操作失败: {str(exc)}"}), 500

    import io as _io

    buf = _io.BytesIO(pdf_bytes)
    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=orig_name,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/pdf/convert
# ─────────────────────────────────────────────────────────────────────────────

_PDF_CONVERT_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


@workspace_assistant_bp.route("/api/v1/workspace/pdf/convert", methods=["POST"])
def pdf_convert():
    """
    Convert a cached PDF to another format.

    Body (JSON):
      {
        "file_id"      : str,   — tmp file identifier (hex)
        "target_format": str,   — "docx" | "xlsx" | "pptx"
        "filename"     : str    — original filename (used for download name, optional)
      }

    Returns the converted file as an attachment.
    """
    body = request.get_json(silent=True) or {}
    file_id = str(body.get("file_id", ""))
    target_fmt = str(body.get("target_format", "")).lower().lstrip(".")
    filename = body.get("filename", "converted")

    if not file_id.isalnum():
        return jsonify({"error": "无效的 file_id"}), 400
    if target_fmt not in _PDF_CONVERT_MIME:
        return (
            jsonify(
                {"error": f"不支持的目标格式 '{target_fmt}'，支持：docx / xlsx / pptx"}
            ),
            400,
        )

    tmp_dir = _ensure_tmp_dir()
    matches = [m for m in tmp_dir.glob(f"{file_id}.*") if m.suffix.lower() == ".pdf"]
    if not matches:
        return jsonify({"error": "找不到 PDF 文件"}), 404

    pdf_path = str(matches[0])
    stem = Path(filename).stem or "converted"
    download_name = f"{stem}.{target_fmt}"
    warning = ""

    try:
        from web.pdf_annotator import pdf_to_docx, pdf_to_pptx, pdf_to_xlsx

        if target_fmt == "docx":
            file_bytes, warning = pdf_to_docx(pdf_path)
        elif target_fmt == "xlsx":
            file_bytes = pdf_to_xlsx(pdf_path)
        elif target_fmt == "pptx":
            file_bytes = pdf_to_pptx(pdf_path)
        else:
            return jsonify({"error": "内部错误"}), 500
    except Exception as exc:
        logger.error("[pdf_convert] 格式转换失败: %s", exc, exc_info=True)
        return jsonify({"error": f"格式转换失败: {str(exc)}"}), 500

    import io as _io

    resp = send_file(
        _io.BytesIO(file_bytes),
        mimetype=_PDF_CONVERT_MIME[target_fmt],
        as_attachment=True,
        download_name=download_name,
    )
    if warning:
        resp.headers["X-Koto-Warning"] = warning
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/pdf/remove_watermark
# ─────────────────────────────────────────────────────────────────────────────


@workspace_assistant_bp.route(
    "/api/v1/workspace/pdf/remove_watermark", methods=["POST"]
)
def pdf_remove_watermark():
    """
    AI-assisted watermark removal.
    Body: {"file_id": str, "use_ai": bool}
    Returns the cleaned PDF as an attachment.
    """
    body = request.get_json(silent=True) or {}
    file_id = str(body.get("file_id", ""))
    use_ai = bool(body.get("use_ai", True))

    # Validate file_id: must be alphanumeric/hyphen/underscore only (prevents path traversal)
    if not file_id or not file_id.replace("-", "").replace("_", "").isalnum():
        return jsonify({"error": "无效的 file_id"}), 400

    tmp_dir = _ensure_tmp_dir()
    matches = [m for m in tmp_dir.glob(f"{file_id}.*") if m.suffix.lower() == ".pdf"]
    if not matches:
        return jsonify({"error": "找不到对应的 PDF 文件，请重新打开"}), 404

    pdf_path = str(matches[0])

    api_key = None
    if use_ai:
        import os

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY")

    try:
        from web.pdf_annotator import remove_watermark

        pdf_bytes, removed_count, method_used = remove_watermark(
            pdf_path, use_ai=use_ai, api_key=api_key
        )
    except Exception as exc:
        logger.error("[pdf_remove_watermark] 失败: %s", exc, exc_info=True)
        return jsonify({"error": f"去水印失败: {str(exc)}"}), 500

    import io as _io

    orig_stem = matches[0].stem
    resp = send_file(
        _io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{orig_stem}_去水印.pdf",
    )
    resp.headers["X-Koto-Removed-Count"] = str(removed_count)
    resp.headers["X-Koto-Method"] = method_used
    return resp
