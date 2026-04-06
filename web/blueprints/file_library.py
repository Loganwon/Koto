# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Koto 智能文件库 (File Library) — 后端蓝图

提供文件夹挂载、文件树浏览、笔记本管理、AI 摘要/标签、跨文件问答等功能。
实时文件监听通过 WatchdogManager + WebSocket /files 命名空间推送变更。

Routes:
  GET    /api/file-library/mounts              — 获取已挂载文件夹列表
  POST   /api/file-library/mounts              — 挂载新文件夹
  DELETE /api/file-library/mounts              — 卸载文件夹
  GET    /api/file-library/tree                — 获取文件树（?root=<abspath>）
  POST   /api/file-library/parse               — 解析单个文件（返回内容+HTML）
  GET    /api/file-library/notebooks           — 获取所有笔记本
  POST   /api/file-library/notebooks           — 新建笔记本
  PATCH  /api/file-library/notebooks/<id>      — 修改笔记本名称/描述
  DELETE /api/file-library/notebooks/<id>      — 删除笔记本
  POST   /api/file-library/notebooks/<id>/files — 向笔记本添加文件
  DELETE /api/file-library/notebooks/<id>/files — 从笔记本移除文件
  GET    /api/file-library/notebooks/<id>/files — 列出笔记本中的文件
  POST   /api/file-library/summarize           — 为文件生成 AI 摘要和标签
  POST   /api/file-library/chat                — 跨文件 AI 问答（SSE 流式）
  GET    /api/file-library/related             — 获取相关文件推荐
  POST   /api/file-library/open-native         — 用系统程序打开文件
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Generator

from flask import Blueprint, Response, jsonify, request, stream_with_context

logger = logging.getLogger(__name__)

file_library_bp = Blueprint("file_library", __name__)

# Explicitly whitelisted notebook columns that may be updated via PATCH.
# Only these names are ever interpolated into SQL — values always use placeholders.
_NOTEBOOK_EDITABLE_COLS: frozenset[str] = frozenset({"name", "description", "color"})

# ─── Database Setup ────────────────────────────────────────────────────────


def _get_db_path() -> Path:
    from web.shared import PROJECT_ROOT
    data_dir = Path(PROJECT_ROOT) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "file_library.db"


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_get_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init_db():
    with _get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS notebooks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                description TEXT    DEFAULT '',
                color       TEXT    DEFAULT '#6366f1',
                created_at  REAL    NOT NULL,
                updated_at  REAL    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS notebook_files (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                notebook_id INTEGER NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
                file_path   TEXT    NOT NULL,
                added_at    REAL    NOT NULL,
                user_note   TEXT    DEFAULT '',
                UNIQUE(notebook_id, file_path)
            );

            CREATE TABLE IF NOT EXISTS file_metadata (
                file_path    TEXT PRIMARY KEY,
                summary      TEXT    DEFAULT '',
                tags_json    TEXT    DEFAULT '[]',
                last_indexed REAL    DEFAULT 0,
                file_mtime   REAL    DEFAULT 0
            );
        """)


# Initialize DB on import
try:
    _init_db()
except Exception as _e:
    logger.warning(f"[FileLib] DB 初始化失败: {_e}")


# ─── Mounts Persistence ────────────────────────────────────────────────────


def _get_settings_path() -> Path:
    from web.shared import PROJECT_ROOT
    return Path(PROJECT_ROOT) / "config" / "user_settings.json"


def _load_settings() -> dict:
    p = _get_settings_path()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_settings(data: dict):
    p = _get_settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    # Invalidate shared settings cache
    try:
        from web.shared import clear_user_settings_cache
        clear_user_settings_cache()
    except Exception:
        pass


def get_mounts() -> list[dict]:
    """Return list of mounted folder dicts: {path, name, pinned}."""
    settings = _load_settings()
    return settings.get("file_library", {}).get("mounts", [])


def _is_allowed_path(path: Path) -> bool:
    """Return True only if *path* resolves to within a mounted directory."""
    try:
        resolved = path.resolve()
    except Exception:
        return False
    for mount in get_mounts():
        try:
            resolved.relative_to(Path(mount["path"]).resolve())
            return True
        except ValueError:
            continue
    return False


def set_mounts(mounts: list[dict]):
    settings = _load_settings()
    if "file_library" not in settings:
        settings["file_library"] = {}
    settings["file_library"]["mounts"] = mounts
    _save_settings(settings)


# ─── Watchdog Manager ─────────────────────────────────────────────────────


class WatchdogManager:
    """Manages watchdog filesystem observers for mounted folders."""

    def __init__(self):
        self._observers: dict[str, object] = {}  # path → Observer
        self._lock = threading.Lock()
        self._socketio = None

    def set_socketio(self, socketio):
        self._socketio = socketio

    def _emit_change(self, event_type: str, src_path: str, dest_path: str | None = None):
        if not self._socketio:
            return
        payload = {"event": event_type, "path": src_path}
        if dest_path:
            payload["dest_path"] = dest_path
        try:
            self._socketio.emit("file_change", payload, namespace="/files")
        except Exception as e:
            logger.warning(f"[WatchdogManager] emit error: {e}")

    def schedule(self, folder_path: str):
        """Start watching a folder (idempotent)."""
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            logger.warning("[WatchdogManager] watchdog 未安装，跳过文件监听")
            return

        folder_path = os.path.normpath(folder_path)
        with self._lock:
            if folder_path in self._observers:
                return

        mgr = self

        class _Handler(FileSystemEventHandler):
            def on_created(self, ev):
                if not ev.is_directory:
                    mgr._emit_change("created", ev.src_path)

            def on_deleted(self, ev):
                if not ev.is_directory:
                    mgr._emit_change("deleted", ev.src_path)

            def on_modified(self, ev):
                if not ev.is_directory:
                    mgr._emit_change("modified", ev.src_path)

            def on_moved(self, ev):
                if not ev.is_directory:
                    mgr._emit_change("moved", ev.src_path, ev.dest_path)

        try:
            obs = Observer()
            obs.schedule(_Handler(), folder_path, recursive=True)
            obs.start()
            with self._lock:
                self._observers[folder_path] = obs
            logger.info(f"[WatchdogManager] 开始监听: {folder_path}")
        except Exception as e:
            logger.warning(f"[WatchdogManager] 无法监听 {folder_path}: {e}")

    def unschedule(self, folder_path: str):
        """Stop watching a folder."""
        folder_path = os.path.normpath(folder_path)
        with self._lock:
            obs = self._observers.pop(folder_path, None)
        if obs:
            try:
                obs.stop()
                obs.join(timeout=2)
            except Exception:
                pass
            logger.info(f"[WatchdogManager] 停止监听: {folder_path}")

    def schedule_all(self, mounts: list[dict]):
        """Schedule watching for all mounted folders (called on startup)."""
        for m in mounts:
            p = m.get("path", "")
            if p and os.path.isdir(p):
                self.schedule(p)

    def stop_all(self):
        with self._lock:
            paths = list(self._observers.keys())
        for p in paths:
            self.unschedule(p)


_watchdog_mgr = WatchdogManager()


def init_watchdog(socketio):
    """Call from app startup after socketio is created."""
    _watchdog_mgr.set_socketio(socketio)
    mounts = get_mounts()
    if mounts:
        t = threading.Thread(
            target=_watchdog_mgr.schedule_all,
            args=(mounts,),
            daemon=True,
            name="FileLibWatchdog",
        )
        t.start()


# ─── File Tree Builder ────────────────────────────────────────────────────


# Extensions to show in tree (broad, not limited to office only)
_TEXT_EXT = {
    ".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml",
    ".html", ".htm", ".css", ".sql", ".sh", ".bat", ".xml", ".csv",
    ".ini", ".cfg", ".toml", ".r", ".nb", ".ipynb", ".log",
}
_OFFICE_EXT = {".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".pdf"}
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}
_ALL_SUPPORTED = _TEXT_EXT | _OFFICE_EXT | _IMAGE_EXT


def _file_type_category(ext: str) -> str:
    ext = ext.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in (".docx", ".doc"):
        return "word"
    if ext in (".xlsx", ".xls"):
        return "spreadsheet"
    if ext in (".pptx", ".ppt"):
        return "presentation"
    if ext in (".csv",):
        return "csv"
    if ext in (".md",):
        return "markdown"
    if ext in (".py", ".js", ".ts", ".json", ".html", ".css", ".sql",
               ".sh", ".r", ".yaml", ".yml", ".xml", ".toml"):
        return "code"
    if ext in _IMAGE_EXT:
        return "image"
    return "text"


def _build_tree(dir_path: Path, root_path: Path | None = None, depth: int = 0, max_depth: int = 8) -> list[dict]:
    if depth > max_depth:
        return []
    if root_path is None:
        root_path = dir_path
    items = []
    try:
        entries = sorted(dir_path.iterdir(), key=lambda p: (0 if p.is_dir() else 1, p.name.lower()))
    except PermissionError:
        return []

    for p in entries:
        # Skip hidden and system dirs
        if p.name.startswith(".") or p.name in ("$RECYCLE.BIN", "System Volume Information"):
            continue
        rel = p.relative_to(root_path).as_posix() if root_path else p.name

        if p.is_dir():
            children = _build_tree(p, root_path, depth + 1, max_depth)
            items.append({
                "name": p.name,
                "type": "folder",
                "path": str(p),
                "rel": rel,
                "children": children,
                "childCount": len(children),
            })
        elif p.is_file() and p.suffix.lower() in _ALL_SUPPORTED:
            try:
                stat = p.stat()
                size_b = stat.st_size
                size_str = (
                    f"{size_b}B" if size_b < 1024
                    else f"{size_b / 1024:.1f}KB" if size_b < 1048576
                    else f"{size_b / 1048576:.1f}MB"
                )
                mtime_ms = int(stat.st_mtime * 1000)
            except OSError:
                size_str = ""
                mtime_ms = 0
            ext = p.suffix.lower()
            items.append({
                "name": p.name,
                "type": "file",
                "path": str(p),
                "rel": rel,
                "ext": ext.lstrip("."),
                "category": _file_type_category(ext),
                "size": size_str,
                "mtime": mtime_ms,
            })
    return items


# ─── Mounts API ───────────────────────────────────────────────────────────


@file_library_bp.route("/api/file-library/mounts", methods=["GET"])
def api_get_mounts():
    return jsonify({"mounts": get_mounts()})


@file_library_bp.route("/api/file-library/mounts", methods=["POST"])
def api_add_mount():
    data = request.get_json(force=True, silent=True) or {}
    folder_path = data.get("path", "").strip()
    if not folder_path:
        return jsonify({"success": False, "error": "path required"}), 400
    folder_path = os.path.normpath(folder_path)
    if not os.path.isdir(folder_path):
        return jsonify({"success": False, "error": "目录不存在"}), 404

    mounts = get_mounts()
    if any(os.path.normpath(m["path"]) == folder_path for m in mounts):
        return jsonify({"success": True, "message": "already mounted", "mounts": mounts})

    name = data.get("name") or os.path.basename(folder_path) or folder_path
    mounts.append({"path": folder_path, "name": name, "pinned": False})
    set_mounts(mounts)

    _watchdog_mgr.schedule(folder_path)
    return jsonify({"success": True, "mounts": mounts})


@file_library_bp.route("/api/file-library/mounts", methods=["DELETE"])
def api_remove_mount():
    data = request.get_json(force=True, silent=True) or {}
    folder_path = os.path.normpath(data.get("path", "").strip())
    mounts = [m for m in get_mounts() if os.path.normpath(m["path"]) != folder_path]
    set_mounts(mounts)
    _watchdog_mgr.unschedule(folder_path)
    return jsonify({"success": True, "mounts": mounts})


# ─── Tree API ─────────────────────────────────────────────────────────────


@file_library_bp.route("/api/file-library/tree")
def api_get_tree():
    root = request.args.get("root", "").strip()
    if not root:
        return jsonify({"error": "root required"}), 400
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        return jsonify({"error": "目录不存在"}), 404
    if not _is_allowed_path(root_path):
        return jsonify({"error": "路径不在已挂载目录中"}), 403
    tree = _build_tree(root_path, root_path)
    return jsonify({"root": str(root_path), "tree": tree})


# ─── File Parse API ──────────────────────────────────────────────────────


@file_library_bp.route("/api/file-library/parse", methods=["POST"])
def api_parse_file():
    """Parse a file by absolute path — returns content + rendered HTML."""
    data = request.get_json(force=True, silent=True) or {}
    file_path = data.get("path", "").strip()
    if not file_path:
        return jsonify({"error": "path required"}), 400

    p = Path(file_path).resolve()
    if not p.is_file():
        return jsonify({"error": "文件不存在"}), 404
    if not _is_allowed_path(p):
        return jsonify({"error": "路径不在已挂载目录中"}), 403

    ext = p.suffix.lower()

    # Text / code files — read directly
    if ext in _TEXT_EXT:
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        return jsonify({
            "success": True,
            "name": p.name,
            "category": _file_type_category(ext),
            "content": content,
            "rendered_html": None,
            "size": p.stat().st_size,
        })

    # Office / PDF — delegate to existing FileParser
    if ext in _OFFICE_EXT:
        try:
            from app.core.file_parser import FileParser
            result = FileParser.parse_file(str(p))
            content = result.get("content", "")
            rendered_html = ""
            if ext == ".docx":
                rendered_html = FileParser.render_html(str(p), "docx")
            elif ext in (".xlsx", ".xls"):
                rendered_html = FileParser.render_html(str(p), "xlsx")
            elif ext in (".pptx", ".ppt"):
                rendered_html = FileParser.render_html(str(p), "pptx")
            elif ext == ".csv":
                rendered_html = FileParser.render_html(str(p), "csv")

            return jsonify({
                "success": True,
                "name": p.name,
                "category": _file_type_category(ext),
                "content": content,
                "rendered_html": rendered_html,
                "size": p.stat().st_size,
            })
        except Exception as e:
            logger.warning(f"[FileLib] parse error for {file_path}: {e}")
            return jsonify({"error": str(e)}), 500

    return jsonify({"error": f"不支持的文件类型: {ext}"}), 415


# ─── Notebook CRUD API ─────────────────────────────────────────────────────


@file_library_bp.route("/api/file-library/notebooks", methods=["GET"])
def api_list_notebooks():
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, description, color, created_at, updated_at FROM notebooks ORDER BY updated_at DESC"
        ).fetchall()
        notebooks = []
        for r in rows:
            nb = dict(r)
            count = conn.execute(
                "SELECT COUNT(*) FROM notebook_files WHERE notebook_id=?", (r["id"],)
            ).fetchone()[0]
            nb["file_count"] = count
            notebooks.append(nb)
    return jsonify({"notebooks": notebooks})


@file_library_bp.route("/api/file-library/notebooks", methods=["POST"])
def api_create_notebook():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "新笔记本").strip()
    desc = data.get("description", "")
    color = data.get("color", "#6366f1")
    now = time.time()
    with _get_db() as conn:
        cur = conn.execute(
            "INSERT INTO notebooks (name, description, color, created_at, updated_at) VALUES (?,?,?,?,?)",
            (name, desc, color, now, now),
        )
        nb_id = cur.lastrowid
        row = conn.execute("SELECT * FROM notebooks WHERE id=?", (nb_id,)).fetchone()
    return jsonify({"success": True, "notebook": dict(row)}), 201


@file_library_bp.route("/api/file-library/notebooks/<int:nb_id>", methods=["PATCH"])
def api_update_notebook(nb_id: int):
    data = request.get_json(force=True, silent=True) or {}
    fields, vals = [], []
    for key in _NOTEBOOK_EDITABLE_COLS:
        if key in data:
            fields.append(f"{key}=?")
            vals.append(data[key])
    if not fields:
        return jsonify({"success": False, "error": "nothing to update"}), 400
    fields.append("updated_at=?")
    vals.append(time.time())
    vals.append(nb_id)
    with _get_db() as conn:
        conn.execute(f"UPDATE notebooks SET {', '.join(fields)} WHERE id=?", vals)
        row = conn.execute("SELECT * FROM notebooks WHERE id=?", (nb_id,)).fetchone()
    if not row:
        return jsonify({"success": False, "error": "not found"}), 404
    return jsonify({"success": True, "notebook": dict(row)})


@file_library_bp.route("/api/file-library/notebooks/<int:nb_id>", methods=["DELETE"])
def api_delete_notebook(nb_id: int):
    with _get_db() as conn:
        conn.execute("DELETE FROM notebooks WHERE id=?", (nb_id,))
    return jsonify({"success": True})


# ─── Notebook Files API ───────────────────────────────────────────────────


@file_library_bp.route("/api/file-library/notebooks/<int:nb_id>/files", methods=["GET"])
def api_list_notebook_files(nb_id: int):
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT nf.id, nf.file_path, nf.added_at, nf.user_note, "
            "fm.summary, fm.tags_json "
            "FROM notebook_files nf "
            "LEFT JOIN file_metadata fm ON fm.file_path=nf.file_path "
            "WHERE nf.notebook_id=? ORDER BY nf.added_at DESC",
            (nb_id,),
        ).fetchall()
    files = []
    for r in rows:
        item = dict(r)
        p = Path(item["file_path"])
        item["name"] = p.name
        item["exists"] = p.is_file()
        item["ext"] = p.suffix.lower().lstrip(".")
        item["category"] = _file_type_category(p.suffix.lower())
        try:
            item["tags"] = json.loads(item.pop("tags_json") or "[]")
        except Exception:
            item["tags"] = []
        if p.is_file():
            try:
                s = p.stat()
                item["size"] = s.st_size
                item["mtime"] = int(s.st_mtime * 1000)
            except OSError:
                item["size"] = 0
                item["mtime"] = 0
        files.append(item)
    return jsonify({"files": files})


@file_library_bp.route("/api/file-library/notebooks/<int:nb_id>/files", methods=["POST"])
def api_add_notebook_files(nb_id: int):
    data = request.get_json(force=True, silent=True) or {}
    paths = data.get("paths", [])
    if isinstance(paths, str):
        paths = [paths]
    now = time.time()
    added = []
    with _get_db() as conn:
        # verify notebook exists
        if not conn.execute("SELECT id FROM notebooks WHERE id=?", (nb_id,)).fetchone():
            return jsonify({"success": False, "error": "笔记本不存在"}), 404
        for fp in paths:
            fp = os.path.normpath(fp)
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO notebook_files (notebook_id, file_path, added_at) VALUES (?,?,?)",
                    (nb_id, fp, now),
                )
                added.append(fp)
            except Exception as e:
                logger.warning(f"[FileLib] add file error: {e}")
        conn.execute("UPDATE notebooks SET updated_at=? WHERE id=?", (now, nb_id))
    return jsonify({"success": True, "added": added})


@file_library_bp.route("/api/file-library/notebooks/<int:nb_id>/files", methods=["DELETE"])
def api_remove_notebook_file(nb_id: int):
    data = request.get_json(force=True, silent=True) or {}
    fp = os.path.normpath(data.get("path", ""))
    with _get_db() as conn:
        conn.execute(
            "DELETE FROM notebook_files WHERE notebook_id=? AND file_path=?",
            (nb_id, fp),
        )
    return jsonify({"success": True})


# ─── AI Summarize API ─────────────────────────────────────────────────────


def _extract_file_text(file_path: str, max_chars: int = 12000) -> str:
    """Extract plaintext from a file (best-effort)."""
    p = Path(file_path)
    if not p.is_file():
        return ""
    ext = p.suffix.lower()
    if ext in _TEXT_EXT:
        try:
            return p.read_text(encoding="utf-8", errors="replace")[:max_chars]
        except Exception:
            return ""
    if ext in _OFFICE_EXT:
        try:
            from app.core.file_parser import FileParser
            result = FileParser.parse_file(str(p))
            return (result.get("content") or "")[:max_chars]
        except Exception:
            return ""
    return ""


def _call_llm_text(prompt: str) -> str:
    """Synchronous LLM call — reuses existing LLM infrastructure."""
    try:
        from app.core.llm_client import get_llm_client
        client = get_llm_client()
        return client.generate(prompt)
    except Exception:
        pass
    try:
        from app.core.ai_providers import get_default_provider
        provider = get_default_provider()
        return provider.complete(prompt)
    except Exception:
        pass
    return ""


@file_library_bp.route("/api/file-library/summarize", methods=["POST"])
def api_summarize_file():
    """Generate AI summary + tags for a file. Stores in file_metadata table."""
    data = request.get_json(force=True, silent=True) or {}
    file_path = os.path.normpath(data.get("path", "").strip())

    if not os.path.isfile(file_path):
        return jsonify({"error": "文件不存在"}), 404

    # Check if already indexed and file not modified
    p = Path(file_path)
    try:
        current_mtime = p.stat().st_mtime
    except OSError:
        current_mtime = 0

    with _get_db() as conn:
        row = conn.execute(
            "SELECT summary, tags_json, file_mtime FROM file_metadata WHERE file_path=?",
            (file_path,),
        ).fetchone()
    if row and row["file_mtime"] == current_mtime and row["summary"]:
        try:
            tags = json.loads(row["tags_json"] or "[]")
        except Exception:
            tags = []
        return jsonify({"success": True, "summary": row["summary"], "tags": tags, "cached": True})

    # Run summarize in background thread; return immediately with task ID
    def _do_summarize():
        text = _extract_file_text(file_path)
        if not text.strip():
            return
        prompt = (
            "请对以下文件内容进行分析，返回 JSON 格式（只输出 JSON，不要额外说明）：\n"
            '{"summary": "100字以内的中文摘要", "tags": ["标签1", "标签2", "标签3"]}\n\n'
            f"文件名：{p.name}\n\n内容：\n{text[:8000]}"
        )
        raw = _call_llm_text(prompt)
        # Extract JSON from response
        summary, tags = "", []
        try:
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if m:
                obj = json.loads(m.group())
                summary = obj.get("summary", "")
                tags = obj.get("tags", [])
                if not isinstance(tags, list):
                    tags = []
        except Exception:
            summary = raw[:200] if raw else ""
            tags = []

        now = time.time()
        try:
            with _get_db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO file_metadata (file_path, summary, tags_json, last_indexed, file_mtime) "
                    "VALUES (?,?,?,?,?)",
                    (file_path, summary, json.dumps(tags, ensure_ascii=False), now, current_mtime),
                )
        except Exception as e:
            logger.warning(f"[FileLib] summarize DB write error: {e}")

    t = threading.Thread(target=_do_summarize, daemon=True)
    t.start()
    return jsonify({"success": True, "async": True, "message": "摘要生成中，请稍候…"})


@file_library_bp.route("/api/file-library/metadata", methods=["GET"])
def api_get_metadata():
    """Get cached metadata (summary + tags) for a file."""
    file_path = os.path.normpath(request.args.get("path", "").strip())
    with _get_db() as conn:
        row = conn.execute(
            "SELECT summary, tags_json FROM file_metadata WHERE file_path=?",
            (file_path,),
        ).fetchone()
    if not row:
        return jsonify({"summary": "", "tags": []})
    try:
        tags = json.loads(row["tags_json"] or "[]")
    except Exception:
        tags = []
    return jsonify({"summary": row["summary"] or "", "tags": tags})


# ─── Cross-file Chat API (SSE) ─────────────────────────────────────────────


@file_library_bp.route("/api/file-library/chat", methods=["POST"])
def api_notebook_chat():
    """Streaming cross-file Q&A. Uses SSE."""
    data = request.get_json(force=True, silent=True) or {}
    nb_id = data.get("notebook_id")
    message = data.get("message", "").strip()
    history = data.get("history", [])

    if not message:
        return jsonify({"error": "message required"}), 400

    # Gather file paths from notebook
    file_texts = []
    if nb_id:
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT file_path FROM notebook_files WHERE notebook_id=?", (nb_id,)
            ).fetchall()
        # Extract text with token budget: 6000 chars per file, up to 10 files
        MAX_PER_FILE = 6000
        MAX_TOTAL = 50000
        total = 0
        for row in rows[:10]:
            fp = row["file_path"]
            text = _extract_file_text(fp, MAX_PER_FILE)
            if text:
                remaining = MAX_TOTAL - total
                if remaining <= 0:
                    break
                snippet = text[:remaining]
                pname = Path(fp).name
                file_texts.append(f"【{pname}】\n{snippet}")
                total += len(snippet)

    context_block = "\n\n---\n\n".join(file_texts) if file_texts else ""
    system_prompt = (
        "你是一个智能文件助手，可以基于用户提供的文件内容回答问题。\n"
        f"以下是用户笔记本中共 {len(file_texts)} 个文件的内容摘录：\n\n"
        f"{context_block}\n\n"
        "请基于以上内容回答用户的问题。回答时请标注信息来源的文件名（用【文件名】格式）。"
    ) if context_block else "你是一个智能助手，请回答用户的问题。"

    # Build message list
    messages = [{"role": "system", "content": system_prompt}]
    for h in history[-6:]:  # last 6 turns
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": message})

    def _generate() -> Generator[str, None, None]:
        yield f"data: {json.dumps({'type': 'meta', 'file_count': len(file_texts)}, ensure_ascii=False)}\n\n"
        try:
            from app.core.llm_client import get_llm_client
            client = get_llm_client()
            for chunk in client.stream(messages):
                payload = json.dumps({"type": "chunk", "text": chunk}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
        except Exception:
            try:
                from app.core.ai_providers import get_default_provider
                provider = get_default_provider()
                full = provider.complete_messages(messages)
                payload = json.dumps({"type": "chunk", "text": full}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
            except Exception as e:
                payload = json.dumps({"type": "error", "text": f"AI 调用失败: {e}"}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(_generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Related Files API ────────────────────────────────────────────────────


@file_library_bp.route("/api/file-library/related")
def api_related_files():
    """Return top-3 related files in same notebook based on tag Jaccard similarity."""
    file_path = os.path.normpath(request.args.get("path", "").strip())
    nb_id = request.args.get("notebook_id", type=int)

    # Get tags for the target file
    with _get_db() as conn:
        row = conn.execute(
            "SELECT tags_json FROM file_metadata WHERE file_path=?", (file_path,)
        ).fetchone()
        target_tags: set = set()
        if row:
            try:
                target_tags = set(json.loads(row["tags_json"] or "[]"))
            except Exception:
                pass

        # Get all other files in same notebook
        if nb_id:
            rows = conn.execute(
                "SELECT nf.file_path, fm.tags_json FROM notebook_files nf "
                "LEFT JOIN file_metadata fm ON fm.file_path=nf.file_path "
                "WHERE nf.notebook_id=? AND nf.file_path!=?",
                (nb_id, file_path),
            ).fetchall()
        else:
            rows = []

    scored = []
    for r in rows:
        try:
            other_tags = set(json.loads(r["tags_json"] or "[]"))
        except Exception:
            other_tags = set()
        if target_tags or other_tags:
            inter = len(target_tags & other_tags)
            union = len(target_tags | other_tags)
            score = inter / union if union > 0 else 0
        else:
            score = 0
        p = Path(r["file_path"])
        scored.append({
            "path": r["file_path"],
            "name": p.name,
            "score": round(score, 3),
            "category": _file_type_category(p.suffix.lower()),
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return jsonify({"related": scored[:3]})


# ─── Open Native ──────────────────────────────────────────────────────────


@file_library_bp.route("/api/file-library/open-native", methods=["POST"])
def api_open_native():
    data = request.get_json(force=True, silent=True) or {}
    path = data.get("path", "").strip()
    if not path or not os.path.exists(path):
        return jsonify({"success": False, "error": "路径不存在"}), 404
    if not _is_allowed_path(Path(path)):
        return jsonify({"success": False, "error": "路径不在已挂载目录中"}), 403
    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
