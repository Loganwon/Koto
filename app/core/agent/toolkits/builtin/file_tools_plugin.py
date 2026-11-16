# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
FileToolsPlugin — Agent 文件能力插件
======================================
向 ToolRegistry 注册以下文件操作工具：
  基础操作：find_file, read_file_snippet, list_recent_files, organize_file
            rename_file, move_file, copy_file, delete_file
  目录分析：list_directory, directory_tree, get_disk_usage, find_large_files,
            find_old_files
  批量操作：batch_rename, batch_move, cleanup_duplicates
  压缩归档：compress_files, extract_archive
  标签收藏：manage_tag, manage_favorite
  撤  销  ：undo_last_op

注册方式::
    from app.core.agent.toolkits.builtin.file_tools_plugin import register_file_tools
    register_file_tools(tool_registry_instance)
"""

from __future__ import annotations

import logging
import re
import tarfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.agent.base import AgentPlugin
from app.core.agent.toolkits.builtin.file_tools_schemas import build_file_tool_schemas
from app.core.file.path_policy import DEFAULT_FILE_PATH_POLICY, FilePathPolicy
from app.core.services.file_service import FileService

logger = logging.getLogger(__name__)


class FileToolsPlugin(AgentPlugin):
    """Koto 文件能力 AgentPlugin。"""

    def __init__(self, path_policy: FilePathPolicy = DEFAULT_FILE_PATH_POLICY) -> None:
        self.path_policy = path_policy
        self.file_service = FileService(path_policy=path_policy)

    @property
    def name(self) -> str:
        return "FileTools"

    @property
    def description(self) -> str:
        return "文件搜索、读取与整理工具"

    def get_tools(self) -> List[Dict[str, Any]]:
        return build_file_tool_schemas(
            find_file=self.find_file,
            read_file_snippet=self.read_file_snippet,
            read_full_document=self.read_full_document,
            list_recent_files=self.list_recent_files,
            organize_file=self.organize_file,
            rename_file=self.rename_file,
            move_file=self.move_file,
            copy_file=self.copy_file,
            delete_file=self.delete_file,
            list_directory=self.list_directory,
            directory_tree=self.directory_tree,
            get_disk_usage=self.get_disk_usage,
            find_large_files=self.find_large_files,
            find_old_files=self.find_old_files,
            batch_rename=self.batch_rename,
            batch_move=self.batch_move,
            cleanup_duplicates=self.cleanup_duplicates,
            compress_files=self.compress_files,
            extract_archive=self.extract_archive,
            manage_tag=self.manage_tag,
            manage_favorite=self.manage_favorite,
            undo_last_op=self.undo_last_op,
        )

    def find_file(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 10,
    ) -> str:
        """统一文件搜索：先查 FileRegistry，再用系统 FileScanner 补充。"""
        limit = min(max(1, int(limit)), 50)
        from app.core.file.file_registry import get_file_registry

        reg = get_file_registry()
        entries = reg.search(query, category=category or None, limit=limit)

        results = []
        for e in entries:
            results.append(
                {
                    "path": e.path,
                    "name": e.name,
                    "category": e.category,
                    "size_kb": round(e.size_bytes / 1024, 1),
                    "snippet": e.snippet,
                }
            )

        # 如果 FileRegistry 结果不足，再尝试调用 FileScanner 补充
        if len(results) < limit:
            try:
                extra = self._scanner_fallback(query, limit - len(results))
                seen_paths = {r["path"] for r in results}
                for item in extra:
                    if item["path"] not in seen_paths:
                        results.append(item)
            except Exception as e:
                logger.debug(f"[FileTools] scanner fallback 失败: {e}")

        if not results:
            return f"未找到与 '{query}' 相关的文件。"

        lines = [f"共找到 {len(results)} 个相关文件：\n"]
        for i, r in enumerate(results, 1):
            lines.append(
                f"{i}. [{r['category']}] {r['name']}  ({r['size_kb']} KB)\n"
                f"   路径: {r['path']}\n"
                + (f"   摘要: {r['snippet']}\n" if r.get("snippet") else "")
            )
        return "\n".join(lines)

    def read_full_document(self, path: str, max_chars: int = 200_000) -> str:
        """读取本地文件的完整全文内容，适用于全文作为 LLM 参考上下文的场景。"""
        max_chars = min(max(1_000, int(max_chars)), 200_000)
        p = Path(path)
        if not p.exists():
            return f"错误：文件不存在 → {path}"
        if not p.is_file():
            return f"错误：路径不是文件 → {path}"
        size_mb = p.stat().st_size / (1024 * 1024)
        if size_mb > 100:
            return f"错误：文件过大（{size_mb:.1f} MB），超过 100 MB 安全限制，请缩小读取范围或拆分文件"
        try:
            from app.core.file.file_registry import _extract_text_full

            content = _extract_text_full(str(p), max_chars=max_chars)
            if not content or not content.strip():
                return f"（无法提取文本内容，文件类型：{p.suffix}）"
            char_count = len(content)
            was_truncated = char_count >= max_chars
            header = (
                f"📄 {p.name}  "
                f"({size_mb:.1f} MB | {char_count:,} 字符"
                f"{'，已截断至上限' if was_truncated else ''})"
                f"\n{'─' * 60}\n"
            )
            return header + content
        except Exception as e:
            return f"读取失败：{e}"

    def read_file_snippet(self, path: str, max_chars: int = 3000) -> str:
        """读取本地文件内容片段。"""
        max_chars = min(max(100, int(max_chars)), 10000)
        p = Path(path)
        if not p.exists():
            return f"错误：文件不存在 → {path}"
        if not p.is_file():
            return f"错误：路径不是文件 → {path}"
        if p.stat().st_size > 50 * 1024 * 1024:
            return f"错误：文件过大（>{50} MB），请使用专用工具处理"

        # 先尝试从 FileRegistry 缓存的 content_preview 读取（快速）
        try:
            from app.core.file.file_registry import (
                _extract_text_preview,
                get_file_registry,
            )

            reg = get_file_registry()
            entry = reg.get_by_path(str(p))
            if entry and entry.content_preview:
                preview = entry.content_preview[:max_chars]
                suffix = "…（已截断）" if len(entry.content_preview) > max_chars else ""
                return preview + suffix
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "Silenced exception caught", exc_info=True
            )

        # 直接提取
        try:
            from app.core.file.file_registry import _extract_text_preview

            content = _extract_text_preview(str(p), max_chars=max_chars)
            if content:
                suffix = "…（已截断）" if len(content) >= max_chars else ""
                return content + suffix
            return f"（无法提取文本内容，文件类型：{p.suffix}）"
        except Exception as e:
            return f"读取失败：{e}"

    def list_recent_files(
        self,
        days: int = 7,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> str:
        """列出近期收录文件。"""
        days = min(max(1, int(days)), 365)
        limit = min(max(1, int(limit)), 100)
        from app.core.file.file_registry import get_file_registry

        reg = get_file_registry()
        entries = reg.list_recent(days=days, category=category or None, limit=limit)

        if not entries:
            return f"最近 {days} 天内没有新收录的文件。"

        lines = [f"最近 {days} 天新收录文件（{len(entries)} 个）：\n"]
        for i, e in enumerate(entries, 1):
            lines.append(
                f"{i}. [{e.category}] {e.name}  ({round(e.size_bytes / 1024, 1)} KB)\n"
                f"   路径: {e.path}\n"
                f"   收录时间: {e.indexed_at[:16]}\n"
            )
        return "\n".join(lines)

    def organize_file(self, source_path: str, category_hint: str = "") -> str:
        """将文件整理到合适目录，并注册到 FileRegistry。"""
        p = Path(source_path)
        if not p.exists():
            return f"错误：文件不存在 → {source_path}"
        if not p.is_file():
            return f"错误：不是有效文件 → {source_path}"

        # 先确保文件在 FileRegistry 中
        from app.core.file.file_registry import get_file_registry

        reg = get_file_registry()
        entry = reg.register(str(p), source="manual", extract_content=True)

        if not entry:
            return f"注册失败：{source_path}"

        # 尝试调用 FileOrganizer
        try:
            import importlib

            organizer_mod = importlib.import_module("app.core.services.file_organizer")
            FileOrganizer = getattr(organizer_mod, "FileOrganizer", None)
            if FileOrganizer:
                organizer = FileOrganizer()
                result = organizer.organize_file(
                    source_path, category_hint=category_hint
                )
                final_path = (
                    result.get("final_path", source_path)
                    if isinstance(result, dict)
                    else source_path
                )
                # 更新注册表中的路径（如果被移动）
                if final_path != source_path and Path(final_path).exists():
                    reg.delete(source_path)
                    reg.register(final_path, source="organizer", extract_content=False)
                return (
                    f"整理完成：{p.name}\n"
                    f"  类别: {entry.category}\n"
                    f"  最终路径: {final_path}\n"
                    + (
                        f"  操作: {result.get('action', '')}"
                        if isinstance(result, dict)
                        else ""
                    )
                )
        except Exception as e:
            logger.debug(f"[FileTools] FileOrganizer 不可用，仅完成注册: {e}")

        return (
            f"已将文件收录到 Koto 文件库：\n"
            f"  名称: {entry.name}\n"
            f"  类别: {entry.category}\n"
            f"  路径: {entry.path}\n"
            f"  大小: {round(entry.size_bytes / 1024, 1)} KB"
        )

    # ── 基础文件操作实现 ──────────────────────────────────────────────────────

    def rename_file(self, path: str, new_name: str) -> str:
        """重命名文件，保持在原目录。"""
        if not self.path_policy.is_outside_protected_dirs(path):
            return "错误：路径在系统保护目录中"
        p = Path(path)
        if not p.exists():
            return f"错误：文件不存在 → {path}"
        if not p.is_file():
            return f"错误：不是文件 → {path}"
        new_name = new_name.strip()
        if not new_name or any(c in new_name for c in r'\/:*?"<>|'):
            return "错误：新文件名含非法字符或为空"
        new_path = p.parent / new_name
        if new_path.exists():
            return f"错误：目标文件已存在 → {new_path}"
        result = self.file_service.rename_file(str(p), new_name)
        if not result.get("success"):
            return f"重命名失败：{result.get('error', '未知错误')}"
        try:
            from app.core.file.file_registry import get_file_registry

            reg = get_file_registry()
            if not reg.update_path(path, str(new_path)):
                reg.register(str(new_path), source="rename")
            reg.log_op("rename", path, str(new_path))
        except Exception as e:
            logger.debug(f"[FileTools] registry sync after rename failed: {e}")
        return f"✅ 重命名成功：{p.name}  →  {new_name}\n   路径：{new_path}"

    def move_file(self, source_path: str, dest_dir: str, new_name: str = "") -> str:
        """移动文件到另一个目录。"""
        if not self.path_policy.is_outside_protected_dirs(source_path):
            return "错误：源路径在系统保护目录中"
        if not self.path_policy.is_outside_protected_dirs(dest_dir):
            return "错误：目标路径在系统保护目录中"
        src = Path(source_path)
        if not src.exists():
            return f"错误：源文件不存在 → {source_path}"
        if not src.is_file():
            return f"错误：不是文件 → {source_path}"
        dest_d = Path(dest_dir)
        dest_d.mkdir(parents=True, exist_ok=True)
        fname = new_name.strip() if new_name else src.name
        if any(c in fname for c in r'\/:*?"<>|'):
            return "错误：文件名含非法字符"
        new_path = dest_d / fname
        if new_path.exists():
            return f"错误：目标文件已存在 → {new_path}"
        result = self.file_service.move_file(str(src), str(new_path))
        if not result.get("success"):
            return f"移动失败：{result.get('error', '未知错误')}"
        try:
            from app.core.file.file_registry import get_file_registry

            reg = get_file_registry()
            if not reg.update_path(str(src), str(new_path)):
                reg.register(str(new_path), source="move")
            reg.log_op("move", str(src), str(new_path))
        except Exception as e:
            logger.debug(f"[FileTools] registry sync after move failed: {e}")
        return f"✅ 移动成功：{src.name}\n   目标：{new_path}"

    def copy_file(self, source_path: str, dest_dir: str, new_name: str = "") -> str:
        """复制文件到另一个目录。"""
        if not self.path_policy.is_outside_protected_dirs(source_path):
            return "错误：源路径在系统保护目录中"
        if not self.path_policy.is_outside_protected_dirs(dest_dir):
            return "错误：目标路径在系统保护目录中"
        src = Path(source_path)
        if not src.exists():
            return f"错误：源文件不存在 → {source_path}"
        if not src.is_file():
            return f"错误：不是文件 → {source_path}"
        dest_d = Path(dest_dir)
        dest_d.mkdir(parents=True, exist_ok=True)
        fname = new_name.strip() if new_name else src.name
        if any(c in fname for c in r'\/:*?"<>|'):
            return "错误：文件名含非法字符"
        new_path = dest_d / fname
        if new_path.exists():
            return f"错误：目标文件已存在 → {new_path}"
        result = self.file_service.copy_file(str(src), str(new_path))
        if not result.get("success"):
            return f"复制失败：{result.get('error', '未知错误')}"
        try:
            from app.core.file.file_registry import get_file_registry

            reg = get_file_registry()
            reg.register(str(new_path), source="copy")
            reg.log_op("copy", str(src), str(new_path))
        except Exception as e:
            logger.debug(f"[FileTools] registry sync after copy failed: {e}")
        return f"✅ 复制成功：{src.name}  →  {new_path}"

    def delete_file(self, path: str, use_trash: bool = True) -> str:
        """删除文件，默认使用系统回收站。"""
        if not self.path_policy.is_outside_protected_dirs(path):
            return "错误：路径在系统保护目录中"
        p = Path(path)
        if not p.exists():
            return f"错误：文件不存在 → {path}"
        if not p.is_file():
            return f"错误：不是文件 → {path}"
        try:
            if use_trash:
                result = self.file_service.delete_path(str(p), use_trash=True)
                if not result.get("success"):
                    return f"删除失败：{result.get('error', '未知错误')}"
                use_trash = bool(result.get("trash", False))
            else:
                result = self.file_service.delete_path(str(p), use_trash=False)
                if not result.get("success"):
                    return f"删除失败：{result.get('error', '未知错误')}"
        except Exception as e:
            return f"删除失败：{e}"
        try:
            from app.core.file.file_registry import get_file_registry

            reg = get_file_registry()
            reg.delete(path)
            reg.log_op("delete", path, meta={"trash": use_trash})
        except Exception as e:
            logger.debug(f"[FileTools] registry sync after delete failed: {e}")
        mode = "已送入回收站" if use_trash else "已永久删除"
        return f"✅ {mode}：{p.name}"

    # ── 目录浏览 / 磁盘分析 ───────────────────────────────────────────────────

    def list_directory(
        self,
        path: str,
        show_hidden: bool = False,
        filter_ext: str = "",
        sort_by: str = "name",
    ) -> str:
        """列出目录内容。"""
        listing = self.file_service.list_directory(path, max_items=1000)
        if not listing.get("success"):
            error = listing.get("error", "未知错误")
            if "不存在" in error:
                return f"错误：路径不存在 → {path}"
            if "不是目录" in error:
                return f"错误：不是目录 → {path}"
            return f"列目录失败：{error}"
        items = []
        for child in listing.get("items", []):
            name = str(child.get("name", ""))
            if not show_hidden and name.startswith("."):
                continue
            if (
                filter_ext
                and child.get("type") == "file"
                and str(child.get("suffix", "")).lower() != filter_ext.lower()
            ):
                continue
            child_path = Path(str(child.get("path", name)))
            try:
                mtime = child_path.stat().st_mtime
            except OSError:
                mtime = 0
            items.append(
                {
                    "name": name,
                    "type": "目录" if child.get("type") == "dir" else "文件",
                    "size_bytes": int(child.get("size") or 0),
                    "mtime": mtime,
                }
            )
        if sort_by == "size":
            items.sort(key=lambda x: x["size_bytes"], reverse=True)
        elif sort_by == "mtime":
            items.sort(key=lambda x: x["mtime"], reverse=True)
        else:
            items.sort(key=lambda x: (x["type"] == "文件", x["name"].lower()))
        if not items:
            return f"目录为空：{path}"
        import datetime

        lines = [f"📁 {path}  （共 {len(items)} 项）\n"]
        for it in items:
            icon = "📁" if it["type"] == "目录" else "📄"
            sz = (
                f"  {round(it['size_bytes']/1024,1)} KB" if it["type"] == "文件" else ""
            )
            mt = datetime.datetime.fromtimestamp(it["mtime"]).strftime("%Y-%m-%d %H:%M")
            lines.append(f"  {icon} {it['name']}{sz}  [{mt}]")
        return "\n".join(lines)

    def directory_tree(self, path: str, max_depth: int = 3) -> str:
        """以树状结构展示目录。"""
        root = Path(path)
        if not root.exists() or not root.is_dir():
            return f"错误：目录不存在 → {path}"
        max_depth = min(max(1, int(max_depth)), 6)
        lines: List[str] = [str(root)]

        def _walk(directory: Path, prefix: str, depth: int):
            if depth > max_depth:
                return
            try:
                candidates = list(directory.iterdir())
            except OSError:
                return
            children: List[tuple[Path, bool]] = []
            for child in candidates:
                try:
                    children.append((child, child.is_dir()))
                except OSError:
                    # Windows can enumerate stale or protected entries whose
                    # metadata cannot be read. One bad child must not make the
                    # complete workspace tree endpoint fail.
                    continue
            children.sort(key=lambda item: (not item[1], item[0].name.lower()))
            for i, (child, is_directory) in enumerate(children):
                connector = "└── " if i == len(children) - 1 else "├── "
                lines.append(
                    f"{prefix}{connector}{child.name}" + ("/" if is_directory else "")
                )
                if is_directory:
                    extension = "    " if i == len(children) - 1 else "│   "
                    _walk(child, prefix + extension, depth + 1)

        _walk(root, "", 1)
        return "\n".join(lines)

    def get_disk_usage(self, path: str, top_n: int = 10) -> str:
        """分析目录磁盘占用，列出 Top N 子目录（按大小降序）。"""
        root = Path(path)
        if not root.exists() or not root.is_dir():
            return f"错误：目录不存在 → {path}"
        top_n = min(max(1, int(top_n)), 50)

        # 计算总大小
        def _dir_size(d: Path) -> int:
            total = 0
            try:
                for p in d.rglob("*"):
                    if p.is_file():
                        try:
                            total += p.stat().st_size
                        except Exception:
                            import logging

                            logging.getLogger(__name__).warning(
                                "Silenced exception caught", exc_info=True
                            )
            except Exception:
                import logging

                logging.getLogger(__name__).warning(
                    "Silenced exception caught", exc_info=True
                )
            return total

        total_bytes = _dir_size(root)
        sub_sizes = []
        try:
            for child in root.iterdir():
                if child.is_dir():
                    sz = _dir_size(child)
                    sub_sizes.append((child.name, sz))
                elif child.is_file():
                    try:
                        sub_sizes.append((child.name + " (文件)", child.stat().st_size))
                    except Exception:
                        import logging

                        logging.getLogger(__name__).warning(
                            "Silenced exception caught", exc_info=True
                        )
        except PermissionError:
            return f"错误：没有权限访问 {path}"
        sub_sizes.sort(key=lambda x: x[1], reverse=True)

        def _fmt(b: int) -> str:
            if b >= 1024**3:
                return f"{b/1024**3:.2f} GB"
            if b >= 1024**2:
                return f"{b/1024**2:.2f} MB"
            return f"{b/1024:.1f} KB"

        lines = [f"📊 磁盘占用分析：{path}", f"   总大小：{_fmt(total_bytes)}\n"]
        for i, (name, sz) in enumerate(sub_sizes[:top_n], 1):
            pct = f"{sz/total_bytes*100:.1f}%" if total_bytes else "  -"
            lines.append(f"  {i:2}. {name:<40} {_fmt(sz):>10}  {pct}")
        return "\n".join(lines)

    def find_large_files(
        self,
        path: str = "",
        min_size_mb: float = 10.0,
        limit: int = 20,
    ) -> str:
        """查找大文件。"""
        min_bytes = int(float(min_size_mb) * 1024 * 1024)
        limit = min(max(1, int(limit)), 100)

        if path:
            root = Path(path)
            if not root.exists() or not root.is_dir():
                return f"错误：目录不存在 → {path}"
            results = []
            for p in root.rglob("*"):
                if p.is_file():
                    try:
                        sz = p.stat().st_size
                        if sz >= min_bytes:
                            results.append((str(p), sz))
                    except Exception:
                        import logging

                        logging.getLogger(__name__).warning(
                            "Silenced exception caught", exc_info=True
                        )
            results.sort(key=lambda x: x[1], reverse=True)
            results = results[:limit]
        else:
            from app.core.file.file_registry import get_file_registry

            entries = get_file_registry().list_large_files(
                min_bytes=min_bytes, limit=limit
            )
            results = [(e.path, e.size_bytes) for e in entries]

        if not results:
            return f"未找到大于 {min_size_mb} MB 的文件。"

        def _fmt(b: int) -> str:
            if b >= 1024**3:
                return f"{b/1024**3:.2f} GB"
            return f"{b/1024**2:.2f} MB"

        lines = [f"🔍 大文件列表（>{min_size_mb} MB，共 {len(results)} 个）：\n"]
        for i, (fpath, sz) in enumerate(results, 1):
            lines.append(f"  {i:2}. {_fmt(sz):>10}  {fpath}")
        return "\n".join(lines)

    def find_old_files(self, days_old: int = 180, limit: int = 20) -> str:
        """在 Koto 文件库中查找长期未修改的旧文件。"""
        import datetime

        days_old = min(max(1, int(days_old)), 3650)
        limit = min(max(1, int(limit)), 100)
        from app.core.file.file_registry import get_file_registry

        entries = get_file_registry().list_old_files(days_old=days_old, limit=limit)
        if not entries:
            return f"Koto 文件库中没有超过 {days_old} 天未修改的文件记录。"
        lines = [f"🕰️ 超过 {days_old} 天未修改的文件（{len(entries)} 个）：\n"]
        for i, e in enumerate(entries, 1):
            mt = datetime.datetime.fromtimestamp(e.mtime).strftime("%Y-%m-%d")
            lines.append(
                f"  {i:2}. [{e.category}] {e.name}  ({round(e.size_bytes/1024,1)} KB，最后修改 {mt})\n"
                f"      {e.path}"
            )
        return "\n".join(lines)

    # ── 批量操作 ──────────────────────────────────────────────────────────────

    def batch_rename(
        self,
        directory: str,
        pattern: str,
        replacement: str,
        file_filter: str = "",
        dry_run: bool = True,
    ) -> str:
        """批量重命名。"""
        d = Path(directory)
        if not d.is_dir():
            return f"错误：目录不存在 → {directory}"
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"错误：正则表达式无效 → {e}"
        candidates = []
        for child in sorted(d.iterdir()):
            if not child.is_file():
                continue
            if file_filter and child.suffix.lower() != file_filter.lower():
                continue
            new_name = regex.sub(replacement, child.name)
            if new_name != child.name:
                candidates.append((child, new_name))

        if not candidates:
            return "没有符合条件的文件需要重命名。"

        lines = [
            f"{'[预演] ' if dry_run else ''}批量重命名 {len(candidates)} 个文件：\n"
        ]
        errors = []
        for src, new_name in candidates:
            new_path = src.parent / new_name
            lines.append(f"  {src.name}  →  {new_name}")
            if not dry_run:
                if new_path.exists():
                    errors.append(f"  ⚠️ 跳过（目标已存在）: {new_name}")
                    continue
                try:
                    result = self.file_service.rename_file(str(src), new_name)
                    if not result.get("success"):
                        errors.append(
                            f"  ❌ 失败 {src.name}: {result.get('error', '未知错误')}"
                        )
                        continue
                    from app.core.file.file_registry import get_file_registry

                    reg = get_file_registry()
                    if not reg.update_path(str(src), str(new_path)):
                        reg.register(str(new_path), source="rename")
                    reg.log_op("rename", str(src), str(new_path))
                except Exception as e:
                    errors.append(f"  ❌ 失败 {src.name}: {e}")
        if errors:
            lines += errors
        if dry_run:
            lines.append("\n⚠️ 这是预演结果，未实际执行。设 dry_run=false 执行重命名。")
        else:
            lines.append("\n✅ 重命名完成")
        return "\n".join(lines)

    def batch_move(
        self,
        source_dir: str,
        dest_dir: str,
        category: str = "",
        file_filter: str = "",
        dry_run: bool = True,
    ) -> str:
        """批量移动文件。"""
        src_d = Path(source_dir)
        if not src_d.is_dir():
            return f"错误：来源目录不存在 → {source_dir}"
        if not dry_run:
            result = self.file_service.create_directory(dest_dir)
            if not result.get("success"):
                return f"移动失败：{result.get('error', '未知错误')}"

        _EXT_CAT: Dict[str, str] = {}
        _CAT_EXTS = {
            "文档": {
                ".doc",
                ".docx",
                ".pdf",
                ".txt",
                ".md",
                ".ppt",
                ".pptx",
                ".xls",
                ".xlsx",
                ".csv",
            },
            "图片": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".heic"},
            "视频": {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm"},
            "音频": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"},
            "代码": {".py", ".js", ".ts", ".java", ".c", ".cpp", ".cs", ".go", ".rs"},
            "压缩包": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"},
        }
        for cat, exts in _CAT_EXTS.items():
            for e in exts:
                _EXT_CAT[e] = cat

        candidates = []
        for child in src_d.iterdir():
            if not child.is_file():
                continue
            if file_filter and child.suffix.lower() != file_filter.lower():
                continue
            if category and _EXT_CAT.get(child.suffix.lower(), "其他") != category:
                continue
            candidates.append(child)

        if not candidates:
            return "没有符合条件的文件。"

        lines = [
            f"{'[预演] ' if dry_run else ''}批量移动 {len(candidates)} 个文件 → {dest_dir}\n"
        ]
        errors = []
        for src in sorted(candidates):
            new_path = Path(dest_dir) / src.name
            lines.append(f"  {src.name}")
            if not dry_run:
                if new_path.exists():
                    errors.append(f"  ⚠️ 跳过（目标已存在）: {src.name}")
                    continue
                try:
                    result = self.file_service.move_path(str(src), str(new_path))
                    if not result.get("success"):
                        errors.append(
                            f"  ❌ 失败 {src.name}: {result.get('error', '未知错误')}"
                        )
                        continue
                    from app.core.file.file_registry import get_file_registry

                    reg = get_file_registry()
                    if not reg.update_path(str(src), str(new_path)):
                        reg.register(str(new_path), source="move")
                    reg.log_op("move", str(src), str(new_path))
                except Exception as e:
                    errors.append(f"  ❌ 失败 {src.name}: {e}")
        if errors:
            lines += errors
        if dry_run:
            lines.append("\n⚠️ 预演结果，设 dry_run=false 执行实际移动。")
        else:
            lines.append("\n✅ 批量移动完成")
        return "\n".join(lines)

    def cleanup_duplicates(
        self,
        keep_strategy: str = "newest",
        dry_run: bool = True,
    ) -> str:
        """清理重复文件。"""
        from app.core.file.file_registry import get_file_registry

        reg = get_file_registry()
        groups = reg.get_duplicates()
        if not groups:
            return "Koto 文件库中没有检测到重复文件。"

        keep_strategy = keep_strategy.strip().lower()
        lines = [
            f"{'[预演] ' if dry_run else ''}重复文件清理（保留策略：{keep_strategy}）\n"
        ]
        total_to_remove = 0
        total_freed = 0

        for grp in groups:
            if keep_strategy == "oldest":
                grp.sort(key=lambda e: e.mtime)
            elif keep_strategy == "shortest_path":
                grp.sort(key=lambda e: len(e.path))
            else:  # newest（默认）
                grp.sort(key=lambda e: e.mtime, reverse=True)
            keeper = grp[0]
            to_remove = grp[1:]
            lines.append(f"  ✅ 保留: {keeper.path}")
            for e in to_remove:
                lines.append(f"  🗑️ 删除: {e.path}  ({round(e.size_bytes/1024,1)} KB)")
                total_to_remove += 1
                total_freed += e.size_bytes
                if not dry_run:
                    try:
                        p = Path(e.path)
                        if p.exists():
                            result = self.file_service.delete_path(
                                str(p), use_trash=True
                            )
                            if not result.get("success"):
                                lines.append(
                                    f"    ❌ 删除失败: {result.get('error', '未知错误')}"
                                )
                                continue
                        reg.delete(e.path)
                        reg.log_op(
                            "delete",
                            e.path,
                            meta={"reason": "duplicate", "trash": True},
                        )
                    except Exception as ex:
                        lines.append(f"    ❌ 删除失败: {ex}")

        def _fmt(b: int) -> str:
            return f"{b/1024**2:.2f} MB" if b >= 1024**2 else f"{b/1024:.1f} KB"

        lines.append(
            f"\n合计：{len(groups)} 组重复，{total_to_remove} 个副本，"
            f"可释放 {_fmt(total_freed)}"
        )
        if dry_run:
            lines.append("⚠️ 预演结果，设 dry_run=false 执行实际清理。")
        return "\n".join(lines)

    # ── 压缩 / 解压 ───────────────────────────────────────────────────────────

    def compress_files(self, sources: List[str], output_path: str) -> str:
        """打包成 zip 档。"""
        out = Path(output_path)
        if out.exists():
            return f"错误：输出文件已存在 → {output_path}"
        out.parent.mkdir(parents=True, exist_ok=True)
        added = 0
        try:
            with zipfile.ZipFile(str(out), "w", zipfile.ZIP_DEFLATED) as zf:
                for src in sources:
                    p = Path(src)
                    if not p.exists():
                        continue
                    if p.is_file():
                        zf.write(str(p), p.name)
                        added += 1
                    elif p.is_dir():
                        for child in p.rglob("*"):
                            if child.is_file():
                                zf.write(str(child), str(child.relative_to(p.parent)))
                                added += 1
        except Exception as e:
            return f"压缩失败：{e}"
        if added == 0:
            try:
                out.unlink()
            except Exception:
                import logging

                logging.getLogger(__name__).warning(
                    "Silenced exception caught", exc_info=True
                )
            return "错误：没有有效文件可以压缩"
        size_kb = round(out.stat().st_size / 1024, 1)
        try:
            from app.core.file.file_registry import get_file_registry

            reg = get_file_registry()
            reg.register(str(out), source="manual")
            reg.log_op("compress", str(sources), str(out))
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "Silenced exception caught", exc_info=True
            )
        return f"✅ 已打包 {added} 个文件 → {output_path}  ({size_kb} KB)"

    def extract_archive(self, archive_path: str, dest_dir: str = "") -> str:
        """解压档案文件。"""
        arc = Path(archive_path)
        if not arc.exists():
            return f"错误：文件不存在 → {archive_path}"
        dest = Path(dest_dir) if dest_dir else arc.parent / arc.stem
        dest.mkdir(parents=True, exist_ok=True)
        ext = arc.suffix.lower()
        try:
            if ext == ".zip":
                with zipfile.ZipFile(str(arc), "r") as zf:
                    for zi in zf.infolist():
                        if zi.is_dir():
                            continue
                        target = dest / zi.filename
                        if not target.resolve().is_relative_to(dest.resolve()):
                            continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(zf.read(zi))
            elif ext in {".tar", ".gz", ".bz2", ".xz", ".tgz"}:
                with tarfile.open(str(arc), "r:*") as tf:
                    for member in tf.getmembers():
                        target = dest / member.name
                        if not target.resolve().is_relative_to(dest.resolve()):
                            continue
                        tf.extract(member, str(dest), filter="data")
            else:
                return f"不支持的压缩格式：{ext}（支持 zip / tar / tar.gz / tar.bz2）"
        except Exception as e:
            return f"解压失败：{e}"
        # 注册释放的文件
        registered = 0
        try:
            from app.core.file.file_registry import get_file_registry

            reg = get_file_registry()
            for child in dest.rglob("*"):
                if child.is_file():
                    reg.register(str(child), source="extract", extract_content=False)
                    registered += 1
            reg.log_op("extract", str(arc), str(dest))
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "Silenced exception caught", exc_info=True
            )
        return f"✅ 解压完成 → {dest}\n   共释放 {registered} 个文件"

    # ── 标签 / 收藏 ───────────────────────────────────────────────────────────

    def manage_tag(
        self,
        action: str,
        path: str = "",
        tag: str = "",
    ) -> str:
        """管理文件标签。"""
        from app.core.file.file_registry import get_file_registry

        reg = get_file_registry()
        action = action.strip().lower()

        if action == "list_all":
            tags = reg.list_all_tags()
            if not tags:
                return "当前没有任何标签。"
            lines = [f"所有标签（共 {len(tags)} 个）："]
            for t in tags:
                lines.append(f"  [{t['count']}] {t['tag']}")
            return "\n".join(lines)

        if action == "files_by_tag":
            if not tag:
                return "错误：请提供 tag 参数"
            paths = reg.list_by_tag(tag)
            if not paths:
                return f"没有标记了 '{tag}' 的文件。"
            lines = [f"标签 '{tag}' 的文件（{len(paths)} 个）："]
            for i, p in enumerate(paths, 1):
                lines.append(f"  {i}. {p}")
            return "\n".join(lines)

        if not path:
            return "错误：请提供 path 参数"

        if action == "list":
            tags = reg.get_tags(path)
            if not tags:
                return f"文件没有标签：{path}"
            return f"文件标签：{', '.join(tags)}\n路径：{path}"

        if action == "add":
            if not tag:
                return "错误：请提供 tag 参数"
            ok = reg.add_tag(path, tag)
            return f"✅ 已添加标签 '{tag}' → {Path(path).name}" if ok else "操作失败"

        if action == "remove":
            if not tag:
                return "错误：请提供 tag 参数"
            ok = reg.remove_tag(path, tag)
            return f"✅ 已移除标签 '{tag}'" if ok else f"标签 '{tag}' 不存在"

        if action == "clear":
            n = reg.clear_tags(path)
            return f"✅ 已清除 {n} 个标签"

        return f"未知操作：{action}（支持 add / remove / list / clear / list_all / files_by_tag）"

    def manage_favorite(self, action: str, path: str = "") -> str:
        """管理收藏夹。"""
        from app.core.file.file_registry import get_file_registry

        reg = get_file_registry()
        action = action.strip().lower()

        if action == "list":
            favs = reg.list_favorites()
            if not favs:
                return "收藏夹为空。"
            lines = [f"⭐ 收藏夹（{len(favs)} 个文件）："]
            for i, p in enumerate(favs, 1):
                name = Path(p).name
                lines.append(f"  {i}. {name}\n      {p}")
            return "\n".join(lines)

        if not path:
            return "错误：请提供 path 参数"

        if action == "add":
            ok = reg.add_favorite(path)
            return f"⭐ 已加入收藏：{Path(path).name}" if ok else "操作失败"

        if action == "remove":
            ok = reg.remove_favorite(path)
            return f"✅ 已取消收藏：{Path(path).name}" if ok else "该文件不在收藏夹中"

        return f"未知操作：{action}（支持 add / remove / list）"

    # ── 撤销 ──────────────────────────────────────────────────────────────────

    def undo_last_op(self) -> str:
        """撤销上一次文件操作。"""
        from app.core.file.file_registry import get_file_registry

        reg = get_file_registry()
        op = reg.pop_last_undoable_op()
        if not op:
            return "没有可撤销的操作记录。"
        op_type = op.get("op_type", "")
        src = op.get("src_path", "")
        dst = op.get("dst_path", "")
        meta = op.get("meta", {})

        try:
            if op_type == "rename" and src and dst:
                p = Path(dst)
                if p.exists():
                    result = self.file_service.rename_file(str(p), Path(src).name)
                    if not result.get("success"):
                        return f"撤销失败：{result.get('error', '未知错误')}"
                    reg.update_path(dst, src)
                    return f"✅ 已撤销重命名：{Path(dst).name}  →  {Path(src).name}"
                return f"撤销失败：文件不存在 → {dst}"

            elif op_type == "move" and src and dst:
                p = Path(dst)
                if p.exists():
                    result = self.file_service.move_path(str(p), src)
                    if not result.get("success"):
                        return f"撤销失败：{result.get('error', '未知错误')}"
                    reg.update_path(dst, src)
                    return (
                        f"✅ 已撤销移动：{Path(dst).name} 已还原到 {Path(src).parent}"
                    )
                return f"撤销失败：文件不存在 → {dst}"

            elif op_type == "copy" and dst:
                p = Path(dst)
                if p.exists():
                    result = self.file_service.delete_path(str(p))
                    if not result.get("success"):
                        return f"撤销失败：{result.get('error', '未知错误')}"
                    reg.delete(dst)
                    return f"✅ 已撤销复制：副本 {Path(dst).name} 已删除"
                return f"撤销失败：副本不存在 → {dst}"

            elif op_type == "delete" and src:
                if meta.get("trash"):
                    return (
                        f"文件 '{Path(src).name}' 已送入系统回收站，"
                        "请手动从回收站还原（右键→还原）。"
                    )
                return f"⚠️ 该文件已永久删除，无法自动撤销：{src}"

            else:
                return f"不支持撤销的操作类型：{op_type}"
        except Exception as e:
            return f"撤销失败：{e}"

    # ── 内部工具 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _scanner_fallback(query: str, limit: int) -> List[Dict[str, Any]]:
        """尝试通过 FileScanner 补充搜索结果。"""
        import importlib

        scanner_mod = importlib.import_module("app.core.services.file_scanner")
        FileScanner = getattr(scanner_mod, "FileScanner", None)
        if not FileScanner:
            return []
        scanner = FileScanner()
        raw = scanner.search_files(query, limit=limit)
        results = []
        for item in (raw if isinstance(raw, list) else []):
            path = item.get("path") or item.get("file_path") or ""
            if path:
                results.append(
                    {
                        "path": path,
                        "name": Path(path).name,
                        "category": item.get("category", "其他"),
                        "size_kb": item.get("size_kb", 0),
                        "snippet": item.get("snippet", ""),
                    }
                )
        return results


# ============================================================================
# 便捷注册函数
# ============================================================================


def register_file_tools(registry: Any):
    """
    将 FileToolsPlugin 注册到 ToolRegistry。

    用法::
        from app.core.agent.toolkits.builtin.file_tools_plugin import register_file_tools
        register_file_tools(tool_registry_instance)
    """
    plugin = FileToolsPlugin()
    registry.register_plugin(plugin)
    logger.info("[FileTools] ✅ 文件工具已注册到 ToolRegistry（23 个工具）")
