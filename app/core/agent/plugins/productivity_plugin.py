# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
ProductivityPlugin — 低风险本地辅助能力

工具：
  • list_directory      — 浏览文件夹内容
  • get_clipboard_text   — 读取当前剪贴板文本
  • set_clipboard_text   — 写入文本到剪贴板
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from app.core.agent.base import AgentPlugin

logger = logging.getLogger(__name__)

# 工作区根目录（可通过环境变量覆盖）
_WORKSPACE = os.environ.get(
    "KOTO_WORKSPACE", os.path.join(os.path.dirname(__file__), "../../../../workspace")
)
_WORKSPACE = os.path.abspath(_WORKSPACE)


class ProductivityPlugin(AgentPlugin):

    @property
    def name(self) -> str:
        return "Productivity"

    @property
    def description(self) -> str:
        return "Local productivity tools: directory browsing and clipboard helpers."

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "list_directory",
                "func": self.list_directory,
                "description": "列出指定目录的文件和子文件夹（不填则列出工作区根目录）",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "path": {
                            "type": "STRING",
                            "description": "目录路径（相对于工作区或绝对路径，默认工作区根目录）",
                        },
                        "show_hidden": {
                            "type": "BOOLEAN",
                            "description": "是否显示隐藏文件（默认 false）",
                        },
                    },
                },
            },
            {
                "name": "get_clipboard_text",
                "func": self.get_clipboard_text,
                "description": "读取当前剪贴板中的文本内容",
                "parameters": {"type": "OBJECT", "properties": {}},
            },
            {
                "name": "set_clipboard_text",
                "func": self.set_clipboard_text,
                "description": "将文本写入剪贴板，方便用户粘贴使用",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "text": {"type": "STRING", "description": "要写入剪贴板的文本"}
                    },
                    "required": ["text"],
                },
            },
        ]

    # ─────────────────────────── 实现 ────────────────────────────────────────

    def _resolve_path(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = Path(_WORKSPACE) / p
        return p.resolve()

    # ── list_directory ────────────────────────────────────────────────────────
    def list_directory(self, path: str = "", show_hidden: bool = False) -> str:
        target = self._resolve_path(path) if path else Path(_WORKSPACE)
        if not target.exists():
            return f"错误：路径不存在 → {target}"
        if not target.is_dir():
            return f"错误：{target} 不是目录"

        items = []
        for entry in sorted(target.iterdir()):
            if not show_hidden and entry.name.startswith("."):
                continue
            kind = "/" if entry.is_dir() else ""
            try:
                size = "" if entry.is_dir() else f"  {entry.stat().st_size:,} bytes"
            except Exception:
                size = ""
            items.append(
                f"{'[DIR] ' if entry.is_dir() else '[FILE]'} {entry.name}{kind}{size}"
            )

        if not items:
            return f"目录为空：{target}"
        return f"目录内容（{target}）：\n" + "\n".join(items)

    # ── clipboard ─────────────────────────────────────────────────────────────
    def get_clipboard_text(self) -> str:
        try:
            import pyperclip

            text = pyperclip.paste()
            return text if text else "(剪贴板为空)"
        except ImportError:
            return "错误：需要安装 pyperclip（pip install pyperclip）"
        except Exception as exc:
            return f"读取剪贴板失败：{exc}"

    def set_clipboard_text(self, text: str) -> str:
        try:
            import pyperclip

            pyperclip.copy(text)
            preview = text[:80] + ("..." if len(text) > 80 else "")
            return f"已写入剪贴板（{len(text)} 个字符）：{preview}"
        except ImportError:
            return "错误：需要安装 pyperclip（pip install pyperclip）"
        except Exception as exc:
            return f"写入剪贴板失败：{exc}"
