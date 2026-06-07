# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Small file-operation helper for the legacy chat FILE_OP branch.

The workspace assistant and whitebox file-task runtime do not use this module.
It remains only for simple chat requests such as reading a workspace file,
listing a directory, or triggering the existing folder catalog organizer.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Callable


def _workspace_dir() -> str:
    from web.runtime_context import get_workspace_dir

    return get_workspace_dir()


def _call_app_factory(name: str, fallback: Callable[[], Any] | None = None) -> Any:
    try:
        from web.runtime_context import call_app_factory

        return call_app_factory(name)
    except Exception:
        return fallback() if fallback is not None else None


class FileOperator:
    """Simple local file helper retained for the legacy chat FILE_OP branch."""

    FILE_KEYWORDS = [
        "读取文件",
        "打开文件",
        "查看文件",
        "读文件",
        "看看文件",
        "创建文件",
        "新建文件",
        "写入文件",
        "保存文件",
        "删除文件",
        "移动文件",
        "复制文件",
        "重命名",
        "文件列表",
        "目录",
        "文件夹",
        "列出文件",
        "自动归纳",
        "自动整理",
        "归纳文件夹",
        "整理文件夹",
        "归档文件夹",
        "微信文件归纳",
        "read file",
        "open file",
        "create file",
        "delete file",
        "list files",
        "directory",
        "folder",
    ]

    FOLDER_ORGANIZE_KEYWORDS = [
        "自动归纳",
        "自动整理",
        "归纳",
        "整理",
        "归档",
        "归类",
        "分类",
        "文件夹",
        "目录",
        "微信文件",
        "wechat files",
    ]

    @classmethod
    def is_file_operation(cls, text: str) -> bool:
        text_lower = str(text or "").lower()
        return any(keyword in text_lower for keyword in cls.FILE_KEYWORDS)

    @classmethod
    def _is_folder_organize_intent(cls, text_lower: str) -> bool:
        has_action = any(keyword in text_lower for keyword in ["归纳", "整理", "归档", "归类", "分类"])
        has_target = any(keyword in text_lower for keyword in ["文件夹", "目录", "路径", "文件"])
        if has_action and has_target:
            return True
        return any(keyword in text_lower for keyword in cls.FOLDER_ORGANIZE_KEYWORDS)

    @classmethod
    def _extract_path_from_text(cls, user_input: str) -> str:
        patterns = [
            r'["\']([^"\']+)["\']',
            r'([A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]*)',
            r"(\.?/[\w\-./ ]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, str(user_input or ""))
            if match:
                candidate = match.group(1).strip().strip("，。,.;；")
                if candidate:
                    return candidate
        return ""

    @classmethod
    def execute(cls, user_input: str) -> dict:
        text_lower = str(user_input or "").lower()
        result = {"success": False, "action": "", "message": "", "content": ""}

        if cls._is_folder_organize_intent(text_lower):
            return cls._execute_folder_organize(user_input, result)

        if any(keyword in text_lower for keyword in ["读取", "打开文件", "查看文件", "读文件", "看看", "read file", "open file"]):
            return cls._execute_read_file(user_input, result)

        if any(keyword in text_lower for keyword in ["文件列表", "目录", "列出文件", "list files", "directory", "文件夹里"]):
            return cls._execute_list_files(user_input, result)

        if any(keyword in text_lower for keyword in ["创建文件", "新建文件", "写入文件", "保存到", "create file"]):
            result["message"] = "请使用代码生成功能，Koto 会自动保存生成的文件到 workspace"
            return result

        result["message"] = "无法识别该文件操作，请尝试：读取文件、列出目录等"
        return result

    @classmethod
    def _execute_folder_organize(cls, user_input: str, result: dict) -> dict:
        folder_path = cls._extract_path_from_text(user_input)
        if not folder_path:
            folder_path = str(_call_app_factory("get_default_wechat_files_dir", lambda: "") or "")

        if not folder_path:
            result["message"] = (
                "请提供要归纳的文件夹路径（可用引号包裹），或在 config/user_settings.json 中设置 "
                "storage.wechat_files_dir 作为默认路径"
            )
            return result

        workspace_dir = _workspace_dir()
        if not os.path.isabs(folder_path):
            folder_path = os.path.join(workspace_dir, folder_path)

        if not os.path.isdir(folder_path):
            result["message"] = f"目录不存在: {folder_path}"
            return result

        try:
            from web.folder_catalog_organizer import FolderCatalogOrganizer

            analyzer = _call_app_factory("get_file_analyzer")
            organizer = _call_app_factory("get_file_organizer")
            organize_root = str(_call_app_factory("get_organize_root", lambda: workspace_dir) or workspace_dir)
            summary = FolderCatalogOrganizer(organize_root, analyzer, organizer).organize_folder(folder_path)
            if not summary.get("success"):
                result["message"] = f"自动归纳失败: {summary.get('error', '未知错误')}"
                return result

            result["success"] = True
            result["action"] = "folder_auto_catalog"
            result["message"] = (
                f"归纳完成：{summary.get('organized_count', 0)}/{summary.get('total_files', 0)} 个文件已归纳"
                f"\n来源目录: {summary.get('source_dir', folder_path)}"
                f"\n清单(MD): {summary.get('report_markdown', '')}"
                f"\n清单(JSON): {summary.get('report_json', '')}"
            )
            return result
        except Exception as exc:
            result["message"] = f"自动归纳异常: {exc}"
            return result

    @classmethod
    def _execute_read_file(cls, user_input: str, result: dict) -> dict:
        filepath = cls._extract_file_or_dir_path(user_input)
        if not filepath:
            result["message"] = "请指定要读取的文件路径"
            return result

        filepath = cls._resolve_workspace_path(filepath)
        if not os.path.exists(filepath):
            result["message"] = f"文件不存在: {filepath}"
            return result

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as handle:
                content = handle.read()
            if len(content) > 10000:
                content = content[:10000] + "\n\n... (文件过长，已截断)"
            result["success"] = True
            result["action"] = "read_file"
            result["message"] = f"已读取文件: {os.path.basename(filepath)}"
            result["content"] = f"```\n{content}\n```"
            return result
        except Exception as exc:
            result["message"] = f"读取文件失败: {exc}"
            return result

    @classmethod
    def _execute_list_files(cls, user_input: str, result: dict) -> dict:
        dirpath = cls._extract_file_or_dir_path(user_input) or _workspace_dir()
        dirpath = cls._resolve_workspace_path(dirpath)
        if not os.path.isdir(dirpath):
            result["message"] = f"目录不存在: {dirpath}"
            return result

        try:
            file_list = []
            for item in os.listdir(dirpath)[:50]:
                item_path = os.path.join(dirpath, item)
                if os.path.isdir(item_path):
                    file_list.append(f"[dir] {item}/")
                else:
                    size = os.path.getsize(item_path)
                    size_text = f"{size / 1024:.1f}KB" if size > 1024 else f"{size}B"
                    file_list.append(f"[file] {item} ({size_text})")
            result["success"] = True
            result["action"] = "list_files"
            result["message"] = f"目录: {dirpath}"
            result["content"] = "\n".join(file_list) if file_list else "空目录"
            return result
        except Exception as exc:
            result["message"] = f"读取目录失败: {exc}"
            return result

    @classmethod
    def _extract_file_or_dir_path(cls, user_input: str) -> str:
        patterns = [
            r'["\']([^"\']+)["\']',
            r"([A-Za-z]:\\[^\s]+)",
            r"(\.?/[^\s]+)",
            r"(\S+\.\w{1,5})(?:\s|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, str(user_input or ""))
            if match:
                return match.group(1).strip().strip("，。,.;；")
        return ""

    @classmethod
    def _resolve_workspace_path(cls, path: str) -> str:
        if os.path.isabs(path):
            return path
        workspace_path = os.path.join(_workspace_dir(), path)
        return workspace_path if os.path.exists(workspace_path) else path

    @classmethod
    def watch_directory(cls, directory: str, callback=None, patterns=None) -> dict:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer

            patterns = patterns or ["*.txt", "*.pdf", "*.docx", "*.xlsx", "*.csv"]

            class ChangeHandler(FileSystemEventHandler):
                def on_created(self, event):
                    if not event.is_directory and callback:
                        filename = os.path.basename(event.src_path)
                        if any(filename.endswith(pattern.replace("*", "")) for pattern in patterns):
                            callback("created", event.src_path)

                def on_modified(self, event):
                    if not event.is_directory and callback:
                        filename = os.path.basename(event.src_path)
                        if any(filename.endswith(pattern.replace("*", "")) for pattern in patterns):
                            callback("modified", event.src_path)

            observer = Observer()
            observer.schedule(ChangeHandler(), directory, recursive=True)
            observer.start()
            return {"success": True, "observer": observer, "message": f"已开始监听目录: {directory}"}
        except Exception as exc:
            return {"success": False, "message": f"无法监听目录: {exc}"}

    @classmethod
    def get_file_metadata(cls, filepath: str) -> dict:
        try:
            if not os.path.exists(filepath):
                return {"success": False, "message": "文件不存在"}
            stat = os.stat(filepath)
            return {
                "success": True,
                "filepath": filepath,
                "filename": os.path.basename(filepath),
                "size": f"{stat.st_size / 1024:.2f} KB",
                "created": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "extension": os.path.splitext(filepath)[1],
                "is_file": os.path.isfile(filepath),
            }
        except Exception as exc:
            return {"success": False, "message": f"无法获取文件信息: {exc}"}
