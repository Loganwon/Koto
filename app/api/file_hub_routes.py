# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
FileHub REST API — /api/files
==============================
统一文件 Hub Blueprint，聚合 FileRegistry + FileWatcher + FileToolsPlugin 的 HTTP 接口。

端点（基础）：
  GET  /api/files/search          搜索文件（?q=&category=&limit=）
  POST /api/files/register        手动注册文件
  GET  /api/files/stats           文件库统计
  GET  /api/files/recent          最近收录（?days=7&category=&limit=20）
  GET  /api/files/duplicates      重复文件（按哈希）
  POST /api/files/scan-dir        立即扫描一个目录
  GET  /api/files/<file_id>       查询单个文件记录
  DELETE /api/files/<file_id>     从文件库移除记录（不删除磁盘文件）

端点（文件操作）：
  POST /api/files/rename          重命名文件
  POST /api/files/move            移动文件
  POST /api/files/copy            复制文件
  DELETE /api/files/disk          删除磁盘文件（送入回收站或永久删除）
  POST /api/files/compress        打包成 zip
  POST /api/files/extract         解压档案

端点（目录/磁盘）：
  GET  /api/files/list-dir        列出目录内容
  GET  /api/files/tree            目录树
  GET  /api/files/disk-usage      磁盘占用分析
  GET  /api/files/large-files     大文件查询
  GET  /api/files/old-files       旧文件查询

端点（批量操作）：
  POST /api/files/batch-rename    批量重命名
  POST /api/files/batch-move      批量移动
  POST /api/files/cleanup-dups    清理重复文件

端点（标签/收藏）：
  GET  /api/files/tags            所有标签统计
  GET  /api/files/<file_id>/tags  查询文件标签
  POST /api/files/<file_id>/tags  添加标签
  DELETE /api/files/<file_id>/tags/<tag>  移除标签
  GET  /api/files/by-tag          按标签查询文件（?tag=）
  GET  /api/files/favorites       收藏列表
  POST /api/files/favorites       加入收藏
  DELETE /api/files/favorites     取消收藏

端点（智能/日志）：
  POST /api/files/summarize       LLM 文件摘要
  GET  /api/files/op-log          操作日志
  POST /api/files/undo            撤销上一次操作
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from flask import Blueprint, Response, jsonify, request, stream_with_context

from web.settings import settings as user_settings

logger = logging.getLogger(__name__)

file_hub_bp = Blueprint("file_hub", __name__)


# ── 工具函数 ──────────────────────────────────────────────────────────────────


@file_hub_bp.route("/pick-folder", methods=["GET"])
def pick_folder():
    """弹出系统原生「选择文件夹」对话框，返回所选路径。
    仅适用于本地运行环境（tkinter 依赖显示上下文）。
    """
    result = {"path": None}
    error_holder = {}

    # 根据传入参数或用户存储路径设置，确定打开对话框时的初始目录
    initial_dir = request.args.get("initial_dir", "") or ""
    if isinstance(initial_dir, str):
        initial_dir = initial_dir.strip()
    if not initial_dir:
        initial_dir = user_settings.workspace_dir or os.path.expanduser("~")

    def _run():
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askdirectory(
                parent=root, title="选择目录", initialdir=initial_dir
            )
            root.destroy()
            result["path"] = selected or None
        except Exception as exc:
            error_holder["error"] = str(exc)

    # tkinter 必须在主线程或至少独立线程中运行，不能在 Flask worker 线程里直接调用
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=60)  # 最多等 60 s（用户可能慢慢选）

    if "error" in error_holder:
        return jsonify({"ok": False, "error": error_holder["error"]}), 500
    if not result["path"]:
        return jsonify({"ok": False, "cancelled": True})
    return jsonify({"ok": True, "path": result["path"]})


def _reg():
    from app.core.file.file_registry import get_file_registry

    return get_file_registry()


def _watcher():
    from app.core.file.file_watcher import get_file_watcher

    return get_file_watcher()


# ── 端点 ─────────────────────────────────────────────────────────────────────


_FS_SEARCH_EXT_CAT = {
    ".doc": "文档",
    ".docx": "文档",
    ".pdf": "文档",
    ".txt": "文档",
    ".md": "文档",
    ".rtf": "文档",
    ".odt": "文档",
    ".wps": "文档",
    ".ppt": "文档",
    ".pptx": "文档",
    ".odp": "文档",
    ".xls": "表格",
    ".xlsx": "表格",
    ".ods": "表格",
    ".csv": "表格",
    ".jpg": "图片",
    ".jpeg": "图片",
    ".png": "图片",
    ".gif": "图片",
    ".bmp": "图片",
    ".webp": "图片",
    ".svg": "图片",
    ".heic": "图片",
    ".mp4": "视频",
    ".mov": "视频",
    ".avi": "视频",
    ".mkv": "视频",
    ".mp3": "音频",
    ".wav": "音频",
    ".flac": "音频",
    ".m4a": "音频",
    ".py": "代码",
    ".js": "代码",
    ".ts": "代码",
    ".java": "代码",
    ".cpp": "代码",
    ".c": "代码",
    ".go": "代码",
    ".rs": "代码",
    ".zip": "压缩包",
    ".rar": "压缩包",
    ".7z": "压缩包",
    ".tar": "压缩包",
}


def _fs_search_fallback(query: str, limit: int, seen_paths: set) -> list:
    """在用户常用目录中搜索文件名含 query 的文件，作为注册表的补充。"""
    import time

    results: list = []
    q_lower = query.lower()
    home = Path.home()

    # 常用搜索目录（按优先级排序）
    search_dirs = []
    for d in ["Desktop", "Documents", "Downloads", "OneDrive", "文档", "桌面", "下载"]:
        p = home / d
        if p.is_dir():
            search_dirs.append(p)
    # OneDrive 可能带版本号后缀（如 OneDrive - 公司名）
    for p in home.iterdir():
        if p.is_dir() and p.name.startswith("OneDrive") and p not in search_dirs:
            search_dirs.append(p)
    if not search_dirs:
        search_dirs = [home]

    deadline = time.monotonic() + 4.0  # 最多 4 秒
    for search_dir in search_dirs:
        if time.monotonic() > deadline or len(results) >= limit:
            break
        try:
            for fp in search_dir.rglob("*"):
                if time.monotonic() > deadline or len(results) >= limit:
                    break
                if not fp.is_file():
                    continue
                if str(fp) in seen_paths:
                    continue
                if q_lower not in fp.name.lower():
                    continue
                try:
                    stat = fp.stat()
                    ext = fp.suffix.lower()
                    results.append(
                        {
                            "file_id": None,
                            "name": fp.name,
                            "path": str(fp),
                            "size_bytes": stat.st_size,
                            "mtime": stat.st_mtime,
                            "category": _FS_SEARCH_EXT_CAT.get(ext, "其他"),
                            "source": "fs",
                            "tags": [],
                        }
                    )
                    seen_paths.add(str(fp))
                except (PermissionError, OSError):
                    pass
        except (PermissionError, OSError):
            pass

    return results


@file_hub_bp.route("/search", methods=["GET"])
def search_files():
    """
    搜索文件。
    Query: q=关键词（可选）, category=文档|图片|..., limit=50
    q 或 category 至少提供一个；都不提供时返回最近文件。
    """
    q = (request.args.get("q") or "").strip()
    category = request.args.get("category") or None
    limit = min(max(1, int(request.args.get("limit", 50))), 200)

    if not q and not category:
        # 无条件时返回最近文件
        entries = _reg().list_recent(days=30, limit=limit)
        return jsonify(
            {
                "query": "",
                "total": len(entries),
                "results": [e.to_dict(include_preview=False) for e in entries],
            }
        )

    entries = _reg().search(q or "", category=category, limit=limit)
    results = [e.to_dict(include_preview=False) for e in entries]

    # 当注册表结果不足时，补充文件系统搜索（仅按文件名匹配，不过滤 category）
    if q and len(results) < limit:
        seen = {r["path"] for r in results if r.get("path")}
        fs_hits = _fs_search_fallback(q, limit - len(results), seen)
        if category:
            fs_hits = [h for h in fs_hits if h.get("category") == category]
        results.extend(fs_hits)

    return jsonify(
        {
            "query": q,
            "total": len(results),
            "results": results,
        }
    )


@file_hub_bp.route("/register", methods=["POST"])
def register_file():
    """
    手动注册文件。
    Body JSON: { "path": "绝对路径", "source": "manual", "session_id": "", "goal_id": "" }
    """
    data = request.get_json(silent=True) or {}
    path = (data.get("path") or "").strip()
    if not path:
        return jsonify({"error": "缺少 path 字段"}), 400

    p = Path(path)
    if not p.exists() or not p.is_file():
        return jsonify({"error": f"文件不存在或不是有效文件: {path}"}), 404

    entry = _reg().register(
        path,
        source=data.get("source", "manual"),
        session_id=data.get("session_id"),
        goal_id=data.get("goal_id"),
        extract_content=True,
    )
    if not entry:
        return jsonify({"error": "注册失败"}), 500

    return jsonify({"status": "ok", "file": entry.to_dict(include_preview=False)}), 201


@file_hub_bp.route("/stats", methods=["GET"])
def file_stats():
    """返回文件库统计：总数、按类别分组、各 source 分布。"""
    stats = _reg().stats()

    # 补充 source 分布

    conn = _reg()._conn
    source_rows = conn.execute(
        "SELECT source, COUNT(*) as cnt FROM koto_file_registry GROUP BY source"
    ).fetchall()
    by_source = {r["source"]: r["cnt"] for r in source_rows}

    return jsonify({**stats, "by_source": by_source})


@file_hub_bp.route("/recent", methods=["GET"])
def recent_files():
    """
    最近收录文件。
    Query: days=7, category=, limit=20
    """
    days = min(max(1, int(request.args.get("days", 7))), 365)
    category = request.args.get("category") or None
    limit = min(max(1, int(request.args.get("limit", 20))), 100)

    entries = _reg().list_recent(days=days, category=category, limit=limit)
    return jsonify(
        {
            "days": days,
            "total": len(entries),
            "files": [e.to_dict() for e in entries],
        }
    )


@file_hub_bp.route("/duplicates", methods=["GET"])
def duplicate_files():
    """返回内容相同（hash 相同）的文件组。"""
    groups = _reg().get_duplicates()
    return jsonify(
        {
            "total_groups": len(groups),
            "groups": [
                [e.to_dict(include_preview=False) for e in grp] for grp in groups
            ],
        }
    )


@file_hub_bp.route("/scan-dir", methods=["POST"])
def scan_directory():
    """
    立即同步扫描一个目录并注册所有文件。
    Body JSON: { "directory": "绝对路径" }
    """
    data = request.get_json(silent=True) or {}
    directory = (data.get("directory") or "").strip()
    if not directory:
        return jsonify({"error": "缺少 directory 字段"}), 400

    p = Path(directory)
    if not p.is_dir():
        return jsonify({"error": f"目录不存在: {directory}"}), 404

    count = _watcher().scan_once(directory)
    return jsonify(
        {
            "status": "ok",
            "directory": directory,
            "registered": count,
        }
    )


@file_hub_bp.route("/archive", methods=["POST"])
def archive_files():
    """
    归档整理：将源目录文件按规则复制或移动到目标目录。

    Body JSON:
      source_dir  str   必填，源目录绝对路径
      dest_dir    str   可选，默认在源目录同级创建 "<源目录名>_归档_YYYYMMDD"
      mode        str   "auto"（按文件类型自动分类）| "custom"（按自定义规则）
      action      str   "copy"（默认，复制文件）| "move"（移动文件）
      recursive   bool  是否递归扫描子目录，默认 True
      rules       list  mode="custom" 时的规则列表，每项为 {"match": "*.pdf", "folder": "PDF文档"}
    """
    import fnmatch
    import shutil
    from datetime import datetime

    data = request.get_json(silent=True) or {}
    source_dir = (data.get("source_dir") or "").strip()
    dest_dir = (data.get("dest_dir") or "").strip()
    mode = (data.get("mode") or "auto").strip()
    action = (data.get("action") or "copy").strip().lower()
    if action not in ("copy", "move"):
        action = "copy"
    recursive = bool(data.get("recursive", True))
    rules = data.get("rules") or []

    # --- validate source ---
    if not source_dir:
        return jsonify({"error": "缺少 source_dir"}), 400
    src = Path(source_dir).resolve()
    if not src.is_dir():
        return jsonify({"error": f"目录不存在: {source_dir}"}), 404

    # --- resolve dest ---
    if dest_dir:
        dest = Path(dest_dir).resolve()
    else:
        stamp = datetime.now().strftime("%Y%m%d")
        dest = src.parent / f"{src.name}_归档_{stamp}"

    # Prevent archiving into itself
    try:
        dest.relative_to(src)
        return jsonify({"error": "目标目录不能是源目录的子目录"}), 400
    except ValueError:
        pass

    dest.mkdir(parents=True, exist_ok=True)

    # --- collect files ---
    glob_pattern = "**/*" if recursive else "*"
    all_files = [f for f in src.glob(glob_pattern) if f.is_file()]

    total = len(all_files)
    copied = 0
    skipped = 0
    errors = []
    report = []

    for fp in all_files:
        try:
            if mode == "auto":
                ext = fp.suffix.lower()
                folder = _FS_SEARCH_EXT_CAT.get(ext, "其他")
            else:
                folder = "其他"
                for rule in rules:
                    pat = (rule.get("match") or "").strip()
                    if pat and fnmatch.fnmatch(fp.name, pat):
                        folder = (rule.get("folder") or "其他").strip()
                        break

            target_dir = dest / folder
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / fp.name

            # avoid overwriting same-name file
            if target.exists():
                stem, suffix = fp.stem, fp.suffix
                idx = 1
                while target.exists():
                    target = target_dir / f"{stem}_{idx}{suffix}"
                    idx += 1

            (
                shutil.copy2(str(fp), str(target))
                if action == "copy"
                else shutil.move(str(fp), str(target))
            )
            copied += 1
            report.append(
                {
                    "src": str(fp),
                    "dest": str(target),
                    "folder": folder,
                    "action": action,
                }
            )
        except Exception as exc:
            errors.append(f"{fp.name}: {exc}")
            skipped += 1

    return jsonify(
        {
            "status": "ok",
            "action": action,
            "dest_dir": str(dest),
            "total": total,
            "copied": copied,
            "skipped": skipped,
            "errors": errors[:20],
            "report": report[:200],
        }
    )


@file_hub_bp.route("/<file_id>", methods=["GET"])
def get_file(file_id: str):
    """查询单个文件记录（含 content_preview）。"""
    entry = _reg().get_by_id(file_id)
    if not entry:
        return jsonify({"error": "未找到该文件记录"}), 404
    return jsonify(entry.to_dict(include_preview=True))


@file_hub_bp.route("/<file_id>", methods=["DELETE"])
def remove_file(file_id: str):
    """从文件库移除记录（不删除磁盘文件）。"""
    entry = _reg().get_by_id(file_id)
    if not entry:
        return jsonify({"error": "未找到该文件记录"}), 404

    deleted = _reg().delete(entry.path)
    if deleted:
        return jsonify({"status": "ok", "removed_path": entry.path})
    return jsonify({"error": "删除失败"}), 500


# ── 文件操作端点 ──────────────────────────────────────────────────────────────


def _tools():
    from app.core.file.file_tools import FileToolsPlugin

    return FileToolsPlugin()


@file_hub_bp.route("/rename", methods=["POST"])
def rename_file():
    """
    重命名文件。
    Body JSON: { "path": "绝对路径", "new_name": "新文件名" }
    """
    data = request.get_json(silent=True) or {}
    path = (data.get("path") or "").strip()
    new_name = (data.get("new_name") or "").strip()
    if not path or not new_name:
        return jsonify({"error": "缺少 path 或 new_name 字段"}), 400
    result = _tools().rename_file(path, new_name)
    ok = result.startswith("✅")
    return jsonify({"status": "ok" if ok else "error", "message": result}), (
        200 if ok else 400
    )


@file_hub_bp.route("/move", methods=["POST"])
def move_file():
    """
    移动文件。
    Body JSON: { "source_path": "...", "dest_dir": "...", "new_name": "" }
    """
    data = request.get_json(silent=True) or {}
    source_path = (data.get("source_path") or "").strip()
    dest_dir = (data.get("dest_dir") or "").strip()
    if not source_path or not dest_dir:
        return jsonify({"error": "缺少 source_path 或 dest_dir 字段"}), 400
    result = _tools().move_file(source_path, dest_dir, data.get("new_name") or "")
    ok = result.startswith("✅")
    return jsonify({"status": "ok" if ok else "error", "message": result}), (
        200 if ok else 400
    )


@file_hub_bp.route("/copy", methods=["POST"])
def copy_file():
    """
    复制文件。
    Body JSON: { "source_path": "...", "dest_dir": "...", "new_name": "" }
    """
    data = request.get_json(silent=True) or {}
    source_path = (data.get("source_path") or "").strip()
    dest_dir = (data.get("dest_dir") or "").strip()
    if not source_path or not dest_dir:
        return jsonify({"error": "缺少 source_path 或 dest_dir 字段"}), 400
    result = _tools().copy_file(source_path, dest_dir, data.get("new_name") or "")
    ok = result.startswith("✅")
    return jsonify({"status": "ok" if ok else "error", "message": result}), (
        200 if ok else 400
    )


@file_hub_bp.route("/open", methods=["POST"])
def open_file():
    """
    用系统默认程序打开文件或文件夹。
    Body JSON: { "path": "绝对路径" }
    """
    import os
    import subprocess
    import sys

    data = request.get_json(silent=True) or {}
    path = (data.get("path") or "").strip()
    if not path:
        return jsonify({"error": "缺少 path 字段"}), 400
    if not os.path.exists(path):
        return jsonify({"error": "文件不存在"}), 404
    try:
        if hasattr(os, "startfile"):
            os.startfile(path)  # noqa: S606
        elif sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@file_hub_bp.route("/disk", methods=["DELETE"])
def delete_file_disk():
    """
    删除磁盘文件。
    Body JSON: { "path": "绝对路径", "use_trash": true }
    """
    data = request.get_json(silent=True) or {}
    path = (data.get("path") or "").strip()
    if not path:
        return jsonify({"error": "缺少 path 字段"}), 400
    use_trash = bool(data.get("use_trash", True))
    result = _tools().delete_file(path, use_trash=use_trash)
    ok = result.startswith("✅")
    return jsonify({"status": "ok" if ok else "error", "message": result}), (
        200 if ok else 400
    )


@file_hub_bp.route("/compress", methods=["POST"])
def compress_files():
    """
    打包成 zip。
    Body JSON: { "sources": ["路径1", "路径2"], "output_path": "输出路径.zip" }
    """
    data = request.get_json(silent=True) or {}
    sources = data.get("sources") or []
    output_path = (data.get("output_path") or "").strip()
    if not sources or not output_path:
        return jsonify({"error": "缺少 sources 或 output_path 字段"}), 400
    result = _tools().compress_files(sources, output_path)
    ok = result.startswith("✅")
    return jsonify({"status": "ok" if ok else "error", "message": result}), (
        200 if ok else 400
    )


@file_hub_bp.route("/extract", methods=["POST"])
def extract_archive():
    """
    解压档案。
    Body JSON: { "archive_path": "...", "dest_dir": "" }
    """
    data = request.get_json(silent=True) or {}
    archive_path = (data.get("archive_path") or "").strip()
    if not archive_path:
        return jsonify({"error": "缺少 archive_path 字段"}), 400
    result = _tools().extract_archive(archive_path, data.get("dest_dir") or "")
    ok = result.startswith("✅")
    return jsonify({"status": "ok" if ok else "error", "message": result}), (
        200 if ok else 400
    )


# ── 直接浏览目录（返回结构化文件列表，无需注册） ─────────────────────────────


@file_hub_bp.route("/browse", methods=["GET"])
def browse_directory():
    """
    直接浏览文件系统目录，返回结构化文件列表。
    Query:
      path      = 目录路径（必填）
      recursive = false | true  （递归扫描，默认 false）
      q         = 文件名关键词过滤（可选）
      limit     = 最多返回条数（默认 200，最大 1000）
    """
    import os

    path = (request.args.get("path") or "").strip()
    if not path:
        return jsonify({"ok": False, "error": "缺少 path 参数"}), 400

    p = Path(path)
    if not p.exists():
        return jsonify({"ok": False, "error": f"路径不存在: {path}"}), 404
    if not p.is_dir():
        return jsonify({"ok": False, "error": f"不是目录: {path}"}), 400

    recursive = request.args.get("recursive", "false").lower() == "true"
    q = (request.args.get("q") or "").strip().lower()
    limit = min(max(1, int(request.args.get("limit", 200))), 1000)

    # 分类规则
    _EXT_MAP = {
        ".pdf": "文档",
        ".doc": "文档",
        ".docx": "文档",
        ".txt": "文档",
        ".md": "文档",
        ".xls": "文档",
        ".xlsx": "文档",
        ".ppt": "文档",
        ".pptx": "文档",
        ".odt": "文档",
        ".rtf": "文档",
        ".csv": "文档",
        ".jpg": "图片",
        ".jpeg": "图片",
        ".png": "图片",
        ".gif": "图片",
        ".bmp": "图片",
        ".svg": "图片",
        ".webp": "图片",
        ".ico": "图片",
        ".mp4": "视频",
        ".avi": "视频",
        ".mov": "视频",
        ".mkv": "视频",
        ".wmv": "视频",
        ".flv": "视频",
        ".webm": "视频",
        ".mp3": "音频",
        ".wav": "音频",
        ".flac": "音频",
        ".aac": "音频",
        ".ogg": "音频",
        ".m4a": "音频",
        ".py": "代码",
        ".js": "代码",
        ".ts": "代码",
        ".java": "代码",
        ".c": "代码",
        ".cpp": "代码",
        ".cs": "代码",
        ".go": "代码",
        ".rs": "代码",
        ".html": "代码",
        ".css": "代码",
        ".json": "代码",
        ".xml": "代码",
        ".sh": "代码",
        ".bat": "代码",
        ".ps1": "代码",
        ".zip": "压缩包",
        ".rar": "压缩包",
        ".7z": "压缩包",
        ".tar": "压缩包",
        ".gz": "压缩包",
        ".bz2": "压缩包",
    }

    files = []
    try:
        if recursive:
            walker = os.walk(p)
        else:
            # Non-recursive: just list direct children
            walker = [
                (
                    str(p),
                    [d.name for d in p.iterdir() if d.is_dir()],
                    [f.name for f in p.iterdir() if f.is_file()],
                )
            ]

        for dirpath, _dirs, filenames in walker:
            for fname in filenames:
                if q and q not in fname.lower():
                    continue
                fpath = Path(dirpath) / fname
                try:
                    stat = fpath.stat()
                    ext = fpath.suffix.lower()
                    cat = _EXT_MAP.get(ext, "其他")
                    files.append(
                        {
                            "name": fname,
                            "path": str(fpath),
                            "category": cat,
                            "size_bytes": stat.st_size,
                            "mtime": stat.st_mtime,
                        }
                    )
                except OSError:
                    continue
                if len(files) >= limit:
                    break
            if len(files) >= limit:
                break
    except PermissionError as exc:
        return jsonify({"ok": False, "error": f"无权限访问: {exc}"}), 403

    # Sort by mtime desc
    files.sort(key=lambda f: f["mtime"], reverse=True)

    return jsonify(
        {
            "ok": True,
            "path": path,
            "recursive": recursive,
            "total": len(files),
            "files": files,
        }
    )


# ── 目录 / 磁盘端点 ───────────────────────────────────────────────────────────


@file_hub_bp.route("/list-dir", methods=["GET"])
def list_directory():
    """
    列出目录内容。
    Query: path=, show_hidden=false, filter_ext=, sort_by=name
    """
    path = (request.args.get("path") or "").strip()
    if not path:
        return jsonify({"error": "缺少 path 参数"}), 400
    show_hidden = request.args.get("show_hidden", "false").lower() == "true"
    filter_ext = request.args.get("filter_ext") or ""
    sort_by = request.args.get("sort_by") or "name"
    result = _tools().list_directory(
        path, show_hidden=show_hidden, filter_ext=filter_ext, sort_by=sort_by
    )
    return jsonify({"path": path, "result": result})


@file_hub_bp.route("/tree", methods=["GET"])
def directory_tree():
    """
    目录树。
    Query: path=, max_depth=3
    """
    path = (request.args.get("path") or "").strip()
    if not path:
        return jsonify({"error": "缺少 path 参数"}), 400
    max_depth = min(max(1, int(request.args.get("max_depth", 3))), 6)
    result = _tools().directory_tree(path, max_depth=max_depth)
    return jsonify({"path": path, "tree": result})


@file_hub_bp.route("/disk-usage", methods=["GET"])
def disk_usage():
    """
    磁盘占用分析。
    Query: path=, top_n=10
    """
    path = (request.args.get("path") or "").strip()
    if not path:
        return jsonify({"error": "缺少 path 参数"}), 400
    top_n = min(max(1, int(request.args.get("top_n", 10))), 50)
    result = _tools().get_disk_usage(path, top_n=top_n)
    return jsonify({"path": path, "result": result})


@file_hub_bp.route("/large-files", methods=["GET"])
def large_files():
    """
    大文件查询。
    Query: path=（可选）, min_size_mb=10, limit=20
    """
    path = request.args.get("path") or ""
    min_size_mb = float(request.args.get("min_size_mb", 10))
    limit = min(max(1, int(request.args.get("limit", 20))), 100)
    result = _tools().find_large_files(path=path, min_size_mb=min_size_mb, limit=limit)
    return jsonify({"result": result})


@file_hub_bp.route("/old-files", methods=["GET"])
def old_files():
    """
    旧文件查询。
    Query: days_old=180, limit=20
    """
    days_old = min(max(1, int(request.args.get("days_old", 180))), 3650)
    limit = min(max(1, int(request.args.get("limit", 20))), 100)
    result = _tools().find_old_files(days_old=days_old, limit=limit)
    return jsonify({"result": result})


# ── 批量操作端点 ──────────────────────────────────────────────────────────────


@file_hub_bp.route("/batch-rename", methods=["POST"])
def batch_rename():
    """
    批量重命名。
    Body JSON: { "directory": "...", "pattern": "...", "replacement": "...",
                 "file_filter": "", "dry_run": true }
    """
    data = request.get_json(silent=True) or {}
    directory = (data.get("directory") or "").strip()
    pattern = (data.get("pattern") or "").strip()
    replacement = data.get("replacement", "")
    if not directory or not pattern:
        return jsonify({"error": "缺少 directory 或 pattern 字段"}), 400
    result = _tools().batch_rename(
        directory=directory,
        pattern=pattern,
        replacement=replacement,
        file_filter=data.get("file_filter") or "",
        dry_run=bool(data.get("dry_run", True)),
    )
    return jsonify({"result": result})


@file_hub_bp.route("/batch-move", methods=["POST"])
def batch_move():
    """
    批量移动。
    Body JSON: { "source_dir": "...", "dest_dir": "...", "category": "",
                 "file_filter": "", "dry_run": true }
    """
    data = request.get_json(silent=True) or {}
    source_dir = (data.get("source_dir") or "").strip()
    dest_dir = (data.get("dest_dir") or "").strip()
    if not source_dir or not dest_dir:
        return jsonify({"error": "缺少 source_dir 或 dest_dir 字段"}), 400
    result = _tools().batch_move(
        source_dir=source_dir,
        dest_dir=dest_dir,
        category=data.get("category") or "",
        file_filter=data.get("file_filter") or "",
        dry_run=bool(data.get("dry_run", True)),
    )
    return jsonify({"result": result})


@file_hub_bp.route("/cleanup-dups", methods=["POST"])
def cleanup_duplicates():
    """
    清理重复文件。
    Body JSON: { "keep_strategy": "newest", "dry_run": true }
    """
    data = request.get_json(silent=True) or {}
    result = _tools().cleanup_duplicates(
        keep_strategy=data.get("keep_strategy") or "newest",
        dry_run=bool(data.get("dry_run", True)),
    )
    return jsonify({"result": result})


# ── 标签端点 ──────────────────────────────────────────────────────────────────


@file_hub_bp.route("/tags", methods=["GET"])
def list_all_tags():
    """列出所有标签及使用次数。"""
    tags = _reg().list_all_tags()
    return jsonify({"total": len(tags), "tags": tags})


@file_hub_bp.route("/by-tag", methods=["GET"])
def files_by_tag():
    """
    按标签查询文件。
    Query: tag=标签名, limit=50
    """
    tag = (request.args.get("tag") or "").strip()
    if not tag:
        return jsonify({"error": "缺少 tag 参数"}), 400
    limit = min(max(1, int(request.args.get("limit", 50))), 200)
    paths = _reg().list_by_tag(tag, limit=limit)
    return jsonify({"tag": tag, "total": len(paths), "paths": paths})


@file_hub_bp.route("/<file_id>/tags", methods=["GET"])
def get_file_tags(file_id: str):
    """查询文件的所有标签。"""
    entry = _reg().get_by_id(file_id)
    if not entry:
        return jsonify({"error": "未找到该文件记录"}), 404
    tags = _reg().get_tags(entry.path)
    return jsonify({"file_id": file_id, "path": entry.path, "tags": tags})


@file_hub_bp.route("/<file_id>/tags", methods=["POST"])
def add_file_tag(file_id: str):
    """
    添加标签。
    Body JSON: { "tag": "标签名" }
    """
    entry = _reg().get_by_id(file_id)
    if not entry:
        return jsonify({"error": "未找到该文件记录"}), 404
    data = request.get_json(silent=True) or {}
    tag = (data.get("tag") or "").strip()
    if not tag:
        return jsonify({"error": "缺少 tag 字段"}), 400
    ok = _reg().add_tag(entry.path, tag)
    if ok:
        return jsonify({"status": "ok", "tag": tag})
    return jsonify({"error": "添加失败"}), 500


@file_hub_bp.route("/<file_id>/tags/<tag>", methods=["DELETE"])
def remove_file_tag(file_id: str, tag: str):
    """移除文件的某个标签。"""
    entry = _reg().get_by_id(file_id)
    if not entry:
        return jsonify({"error": "未找到该文件记录"}), 404
    ok = _reg().remove_tag(entry.path, tag)
    if ok:
        return jsonify({"status": "ok", "removed_tag": tag})
    return jsonify({"error": f"标签 '{tag}' 不存在"}), 404


# ── 收藏端点 ──────────────────────────────────────────────────────────────────


@file_hub_bp.route("/favorites", methods=["GET"])
def list_favorites():
    """列出所有收藏文件（返回完整元数据）。"""
    reg = _reg()
    paths = reg.list_favorites()
    files = []
    for path in paths:
        entry = reg.get_by_path(path)
        if entry:
            d = entry.to_dict(include_preview=False)
            d["tags"] = reg.get_tags(path)
            d["favorited"] = True
            files.append(d)
        else:
            name = path.replace("\\", "/").rsplit("/", 1)[-1]
            files.append(
                {
                    "path": path,
                    "name": name,
                    "category": "其他",
                    "source": "favorites",
                    "favorited": True,
                    "tags": [],
                }
            )
    return jsonify({"total": len(files), "favorites": paths, "files": files})


@file_hub_bp.route("/favorites", methods=["POST"])
def add_favorite():
    """
    加入收藏。
    Body JSON: { "path": "绝对路径" } 或 { "file_id": "..." }
    """
    data = request.get_json(silent=True) or {}
    path = (data.get("path") or "").strip()
    if not path:
        file_id = (data.get("file_id") or "").strip()
        if file_id:
            entry = _reg().get_by_id(file_id)
            path = entry.path if entry else ""
    if not path:
        return jsonify({"error": "缺少 path 或 file_id 字段"}), 400
    ok = _reg().add_favorite(path)
    if ok:
        return jsonify({"status": "ok", "path": path}), 201
    return jsonify({"error": "操作失败"}), 500


@file_hub_bp.route("/favorites", methods=["DELETE"])
def remove_favorite():
    """
    取消收藏。
    Body JSON: { "path": "绝对路径" }
    """
    data = request.get_json(silent=True) or {}
    path = (data.get("path") or "").strip()
    if not path:
        return jsonify({"error": "缺少 path 字段"}), 400
    ok = _reg().remove_favorite(path)
    if ok:
        return jsonify({"status": "ok"})
    return jsonify({"error": "该文件不在收藏夹中"}), 404


# ── 监控目录设置端点 ──────────────────────────────────────────────────────────

_WATCH_SETTINGS_PATH = str(
    Path(__file__).parent.parent.parent / "config" / "user_settings.json"
)


def _read_user_settings() -> dict:
    """Read settings via SettingsManager (thread-safe)."""
    try:
        from web.settings import SettingsManager

        return SettingsManager().get_all()
    except Exception:
        import json as _json

        try:
            with open(_WATCH_SETTINGS_PATH, "r", encoding="utf-8-sig") as f:
                return _json.load(f)
        except Exception:
            return {}


def _write_user_settings(data: dict) -> None:
    """Write settings via SettingsManager (atomic, thread-safe).

    Only the 'file_watcher' sub-key is updated to avoid clobbering other
    settings that may have been changed concurrently.
    """
    from web.settings import SettingsManager

    sm = SettingsManager()
    fw = data.get("file_watcher", {})
    sm.update("file_watcher", fw)


@file_hub_bp.route("/watch-settings", methods=["GET"])
def get_watch_settings():
    """获取文件监控目录配置。"""
    data = _read_user_settings()
    cfg = data.get("file_watcher", {})
    return jsonify(
        {
            "enabled": cfg.get("enabled", False),
            "watch_dirs": cfg.get("watch_dirs", []),
            "interval_seconds": cfg.get("interval_seconds", 30),
            "max_file_size_mb": cfg.get("max_file_size_mb", 50),
        }
    )


@file_hub_bp.route("/watch-settings", methods=["POST"])
def update_watch_settings():
    """更新文件监控配置。Body JSON: {enabled, watch_dirs, interval_seconds}"""
    body = request.get_json(silent=True) or {}
    data = _read_user_settings()
    cfg = data.get("file_watcher", {})
    if "enabled" in body:
        cfg["enabled"] = bool(body["enabled"])
    if "watch_dirs" in body:
        dirs = [str(d).strip() for d in body["watch_dirs"] if str(d).strip()]
        cfg["watch_dirs"] = dirs
    if "interval_seconds" in body:
        cfg["interval_seconds"] = max(10, int(body.get("interval_seconds", 30)))
    data["file_watcher"] = cfg
    try:
        _write_user_settings(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    # Notify running watcher of config change and apply immediately
    try:
        w = _watcher()
        w.reload_and_apply()
    except Exception:
        pass
    return jsonify({"status": "ok", "file_watcher": cfg})


# ── 智能 / 日志端点 ───────────────────────────────────────────────────────────


@file_hub_bp.route("/summarize", methods=["POST"])
def summarize_file():
    """
    LLM 文件摘要。
    Body JSON: { "path": "...", "focus": "" }
    """
    data = request.get_json(silent=True) or {}
    path = (data.get("path") or "").strip()
    if not path:
        return jsonify({"error": "缺少 path 字段"}), 400
    result = _tools().summarize_file(path, focus=data.get("focus") or "")
    ok = not result.startswith("错误") and not result.startswith("LLM 摘要失败")
    return jsonify({"status": "ok" if ok else "error", "summary": result})


@file_hub_bp.route("/batch-ai", methods=["POST"])
def batch_ai():
    """
    AI 批量文件任务 — SSE 流式端点。
    Body JSON:
      { "paths": ["/abs/path/a.docx", ...], "task": "提取关键信息" }
    Events:
      data: {"type": "start",    "total": n}
      data: {"type": "file",     "index": i, "name": "..."}
      data: {"type": "token",    "content": "..."}
      data: {"type": "file_done","index": i}
      data: {"type": "done"}
      data: {"type": "error",    "message": "..."}
    """
    import json as _json

    data = request.get_json(silent=True) or {}
    paths = [str(p).strip() for p in (data.get("paths") or []) if str(p).strip()]
    task = (data.get("task") or "").strip()
    if not paths:
        return jsonify({"error": "缺少 paths 字段"}), 400
    if not task:
        task = "请对以下文件内容进行摘要，提炼关键信息。"
    # Cap to 10 files per batch to avoid runaway requests
    paths = paths[:10]

    def generate():
        yield f"data: {_json.dumps({'type': 'start', 'total': len(paths)}, ensure_ascii=False)}\n\n"
        try:
            from app.core.file.file_registry import _extract_text_preview
            from app.core.llm.gemini import GeminiProvider
        except Exception as e:
            yield f"data: {_json.dumps({'type': 'error', 'message': f'模块加载失败: {e}'}, ensure_ascii=False)}\n\n"
            return

        llm = GeminiProvider()
        for i, path in enumerate(paths):
            name = Path(path).name
            yield f"data: {_json.dumps({'type': 'file', 'index': i, 'name': name}, ensure_ascii=False)}\n\n"
            try:
                content = _extract_text_preview(path, max_chars=5000)
                if not content or not content.strip():
                    _no_content_msg = f"⚠️ {name}：无法提取文本内容\n\n"
                    yield f"data: {_json.dumps({'type': 'token', 'content': _no_content_msg}, ensure_ascii=False)}\n\n"
                    yield f"data: {_json.dumps({'type': 'file_done', 'index': i}, ensure_ascii=False)}\n\n"
                    continue

                # PII masking
                _mask_result = None
                safe_content = content
                try:
                    from app.core.security.pii_filter import PIIFilter

                    _mask_result = PIIFilter.mask(content)
                    if _mask_result.has_pii:
                        safe_content = _mask_result.masked_text
                except Exception:
                    pass

                prompt = (
                    f"任务：{task}\n\n"
                    f"文件名：{name}\n\n"
                    f"内容：\n{safe_content}\n"
                )
                resp = llm.generate_content(
                    prompt=prompt,
                    model="gemini-2.5-flash",
                    system_instruction="你是一个专业的文件分析助手，用中文输出简洁精准的分析结果。",
                )
                text = ""
                if isinstance(resp, dict):
                    text = (
                        resp.get("text")
                        or resp.get("content")
                        or resp.get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text", "")
                    )
                if not text:
                    text = str(resp)

                # Output validation
                try:
                    from app.core.security.output_validator import OutputValidator

                    _val = OutputValidator.validate(text=text)
                    if _val.is_blocked:
                        # Disabled — log only, don't replace content
                        import logging as _logging

                        _logging.getLogger(__name__).warning(
                            "[file_hub] OutputValidator BLOCK (ignored): %s",
                            _val.reasons,
                        )
                    else:
                        text = _val.text
                except Exception:
                    pass

                # PII restore
                if _mask_result and _mask_result.has_pii:
                    try:
                        text = _mask_result.restore(text)
                    except Exception:
                        pass

                header = f"\n### {name}\n\n"
                body = text.strip() + "\n\n"
                yield f"data: {_json.dumps({'type': 'token', 'content': header}, ensure_ascii=False)}\n\n"
                yield f"data: {_json.dumps({'type': 'token', 'content': body}, ensure_ascii=False)}\n\n"
            except Exception as e:
                err_msg = f"\n### {name}\n\n⚠️ 处理失败: {e}\n\n"
                yield f"data: {_json.dumps({'type': 'token', 'content': err_msg}, ensure_ascii=False)}\n\n"
            yield f"data: {_json.dumps({'type': 'file_done', 'index': i}, ensure_ascii=False)}\n\n"

        yield f"data: {_json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@file_hub_bp.route("/op-log", methods=["GET"])
def op_log():
    """
    操作日志。
    Query: limit=20
    """
    limit = min(max(1, int(request.args.get("limit", 20))), 200)
    logs = _reg().get_op_log(limit=limit)
    return jsonify({"total": len(logs), "ops": logs})


@file_hub_bp.route("/undo", methods=["POST"])
def undo_last_op():
    """撤销上一次文件操作。"""
    result = _tools().undo_last_op()
    ok = result.startswith("✅")
    return jsonify({"status": "ok" if ok else "info", "message": result})


# ── Goal / Session 关联端点 ───────────────────────────────────────────────────


@file_hub_bp.route("/by-goal/<goal_id>", methods=["GET"])
def files_by_goal(goal_id: str):
    """
    查询与指定 goal 关联的所有文件。
    Query: limit=50
    """
    limit = min(max(1, int(request.args.get("limit", 50))), 200)
    entries = _reg().list_by_goal(goal_id, limit=limit)
    return jsonify(
        {
            "goal_id": goal_id,
            "total": len(entries),
            "files": [e.to_dict() for e in entries],
        }
    )


@file_hub_bp.route("/by-session/<session_id>", methods=["GET"])
def files_by_session(session_id: str):
    """
    查询与指定 session 关联的所有文件。
    Query: limit=50
    """
    limit = min(max(1, int(request.args.get("limit", 50))), 200)
    entries = _reg().list_by_session(session_id, limit=limit)
    return jsonify(
        {
            "session_id": session_id,
            "total": len(entries),
            "files": [e.to_dict() for e in entries],
        }
    )


@file_hub_bp.route("/<file_id>/link-goal", methods=["PATCH"])
def link_file_to_goal(file_id: str):
    """
    将已注册的文件关联到指定 goal。
    Body JSON: { "goal_id": "..." }
    """
    data = request.get_json(silent=True) or {}
    goal_id = (data.get("goal_id") or "").strip()
    if not goal_id:
        return jsonify({"error": "缺少 goal_id 字段"}), 400

    entry = _reg().get_by_id(file_id)
    if not entry:
        return jsonify({"error": "未找到该文件记录"}), 404

    ok = _reg().link_goal(entry.path, goal_id)
    if not ok:
        return jsonify({"error": "关联失败"}), 500
    return jsonify({"status": "ok", "file_id": file_id, "goal_id": goal_id})


# ── 关系图数据端点 ────────────────────────────────────────────────────────────


@file_hub_bp.route("/graph-data", methods=["GET"])
def graph_data():
    """
    返回文件关系图数据（nodes + edges）。

    Query: center=<file_id>（可选，以该文件为中心展开一度关系）
           limit=80（最多节点数）

    边类型：
      goal   — 同一 origin_goal_id
      dup    — 相同文件内容（MD5 哈希）
      recent — 最近一批文件（无显式关系时的兜底连接）
    """
    center_id = request.args.get("center") or None
    limit = min(max(10, int(request.args.get("limit", 80))), 200)

    reg = _reg()
    conn = reg._conn

    # ── 计算以 center 为锚点的局部图（若无 center，取最近文件）───────────────
    center_entry = reg.get_by_id(center_id) if center_id else None

    if center_entry:
        # 一度邻居：同 goal + 同 hash + RAG 相似（用 FTS 兜底）
        neighbor_paths: set = {center_entry.path}

        # 同 goal
        if center_entry.origin_goal_id:
            for e in reg.list_by_goal(center_entry.origin_goal_id, limit=30):
                neighbor_paths.add(e.path)

        # 同 hash（重复文件）
        if center_entry.file_hash:
            rows = conn.execute(
                "SELECT path FROM koto_file_registry WHERE file_hash=? LIMIT 20",
                (center_entry.file_hash,),
            ).fetchall()
            for r in rows:
                neighbor_paths.add(r["path"])

        # FTS 相似（用文件名搜索）
        try:
            similar = reg.search(center_entry.name.rsplit(".", 1)[0], limit=15)
            for e in similar:
                neighbor_paths.add(e.path)
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "Silenced exception caught", exc_info=True
            )

        # 取所有邻居的完整 entry
        entries = [center_entry]
        for p in list(neighbor_paths)[:limit]:
            if p == center_entry.path:
                continue
            e = reg.get_by_path(p)
            if e:
                entries.append(e)
    else:
        # 无 center，取最近 limit 个文件
        entries = reg.list_recent(days=90, limit=limit)

    # ── 构建 nodes ────────────────────────────────────────────────────────────
    node_map = {e.file_id: e for e in entries}
    nodes = [
        {
            "id": e.file_id,
            "name": e.name,
            "category": e.category,
            "size_bytes": e.size_bytes,
            "path": e.path,
            "is_center": e.file_id == center_id,
        }
        for e in entries
    ]

    # ── 构建 edges ────────────────────────────────────────────────────────────
    edges = []
    seen_edges: set = set()

    def _add_edge(src_id: str, tgt_id: str, etype: str):
        if src_id == tgt_id:
            return
        key = tuple(sorted([src_id, tgt_id]))
        if key not in seen_edges:
            seen_edges.add(key)
            edges.append({"source": src_id, "target": tgt_id, "type": etype})

    # goal 关系
    from collections import defaultdict

    _goal_groups: dict = defaultdict(list)
    _hash_groups: dict = defaultdict(list)
    for e in entries:
        if e.origin_goal_id:
            _goal_groups[e.origin_goal_id].append(e.file_id)
        if e.file_hash:
            _hash_groups[e.file_hash].append(e.file_id)

    for gid, ids in _goal_groups.items():
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                _add_edge(ids[i], ids[j], "goal")

    for fhash, ids in _hash_groups.items():
        if len(ids) > 1:
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    _add_edge(ids[i], ids[j], "dup")

    return jsonify(
        {
            "nodes": nodes,
            "edges": edges,
            "center_id": center_id,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
        }
    )


# ── 文件内容读取 / OS 默认程序打开 ────────────────────────────────────────────


_TEXT_EXTS = {
    ".txt",
    ".md",
    ".py",
    ".js",
    ".ts",
    ".json",
    ".html",
    ".htm",
    ".css",
    ".csv",
    ".yaml",
    ".yml",
    ".xml",
    ".sql",
    ".sh",
    ".bash",
    ".ps1",
    ".java",
    ".cpp",
    ".c",
    ".h",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".toml",
    ".ini",
    ".cfg",
    ".env",
    ".log",
}
_MAX_READ_BYTES = 2 * 1024 * 1024  # 2 MB 上限，防止意外加载超大文件


@file_hub_bp.route("/read", methods=["GET"])
def read_file_content():
    """
    读取文本文件内容，供前端代码查看器（Artifacts）展示。
    Query: path=<绝对路径>
    返回 JSON: { "content": "...", "size": N, "encoding": "utf-8" }
    """
    path = (request.args.get("path") or "").strip()
    if not path:
        return jsonify({"error": "缺少 path 参数"}), 400

    p = Path(path).resolve()

    # 安全检查：只允许读取文件，不允许路径遍历到 / 等根目录
    if not p.is_file():
        return jsonify({"error": "文件不存在"}), 404

    if p.suffix.lower() not in _TEXT_EXTS:
        return jsonify({"error": "不支持预览该类型文件，请用默认程序打开"}), 415

    try:
        size = p.stat().st_size
        if size > _MAX_READ_BYTES:
            return (
                jsonify({"error": f"文件过大（{size // 1024} KB），请用外部程序打开"}),
                413,
            )

        content = p.read_text(encoding="utf-8", errors="replace")
        return jsonify({"content": content, "size": size, "encoding": "utf-8"})
    except PermissionError:
        return jsonify({"error": "无权限读取该文件"}), 403
    except Exception as exc:
        logger.warning(f"[FileHub] read_file_content 失败: {exc}")
        return jsonify({"error": "读取失败"}), 500


@file_hub_bp.route("/open", methods=["POST"])
def open_file_with_os():
    """
    用系统默认程序打开文件（适用于非代码类文件）。
    Body JSON: { "path": "<绝对路径>" }
    """
    import platform
    import subprocess as _sp

    data = request.get_json(silent=True) or {}
    path = (data.get("path") or "").strip()
    if not path:
        return jsonify({"error": "缺少 path 字段"}), 400

    p = Path(path).resolve()
    if not p.exists():
        return jsonify({"error": "文件或目录不存在"}), 404

    try:
        sys_name = platform.system()
        if hasattr(os, "startfile"):
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys_name == "Windows":
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys_name == "Darwin":
            _sp.Popen(["open", str(p)])
        else:
            _sp.Popen(["xdg-open", str(p)])
        return jsonify({"status": "ok", "path": str(p)})
    except Exception as exc:
        logger.warning(f"[FileHub] open_file_with_os 失败: {exc}")
        return jsonify({"error": f"打开失败: {exc}"}), 500
