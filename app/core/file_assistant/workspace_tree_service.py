# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

from pathlib import Path
from typing import Iterable


class WorkspaceTreeService:
    """Build file-tree payloads for the workspace file assistant."""

    DEFAULT_SKIP_NAMES = {
        "tmp",
        "backups",
        "editor-docs",
        "images",
        "ppt_sessions",
        "__pycache__",
        "node_modules",
        ".git",
        ".venv",
        "venv",
    }

    CATEGORY_BY_EXTENSION = {
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
        ".bmp": "image",
        ".svg": "image",
        ".webp": "image",
    }

    def build_workspace_tree(
        self,
        *,
        root_path: str | Path,
        allowed_extensions: Iterable[str],
        skip_names: Iterable[str] | None = None,
    ) -> dict:
        root = Path(root_path).resolve()
        allowed = frozenset(str(ext).lower() for ext in allowed_extensions)
        skip = set(skip_names or self.DEFAULT_SKIP_NAMES)
        return {
            "files": self._build_tree(root, root, allowed, skip),
            "workspace_name": root.name,
            "workspace_path": str(root),
        }

    def _build_tree(
        self,
        dir_path: Path,
        root_path: Path,
        allowed_extensions: frozenset[str],
        skip_names: set[str],
    ) -> list[dict]:
        items: list[dict] = []
        try:
            children = sorted(dir_path.iterdir(), key=lambda path: (path.is_file(), path.name.lower()))
            for path in children:
                if path.name.startswith(".") or path.name in skip_names:
                    continue

                rel_path = path.relative_to(root_path).as_posix()
                if path.is_dir():
                    items.append(
                        {
                            "name": path.name,
                            "type": "folder",
                            "path": rel_path,
                            "children": self._build_tree(path, root_path, allowed_extensions, skip_names),
                        }
                    )
                elif path.is_file():
                    items.append(self.file_entry(path, rel_path, allowed_extensions))
        except PermissionError:
            pass
        return items

    @classmethod
    def file_entry(cls, path: Path, display_path: str, allowed_extensions: Iterable[str]) -> dict:
        ext = path.suffix.lower()
        size_str, mtime_ms = cls.file_stat_summary(path)
        allowed = frozenset(str(item).lower() for item in allowed_extensions)
        return {
            "name": path.name,
            "type": "file",
            "ext": ext.lstrip("."),
            "path": display_path,
            "size": size_str,
            "mtime": mtime_ms,
            "supported": ext in allowed,
            "category": cls.file_category(ext),
        }

    @classmethod
    def file_category(cls, ext: str) -> str:
        return cls.CATEGORY_BY_EXTENSION.get(str(ext).lower(), "other")

    @staticmethod
    def file_stat_summary(path: Path) -> tuple[str, int]:
        try:
            stat = path.stat()
            size_bytes = stat.st_size
            size_str = (
                f"{size_bytes}B"
                if size_bytes < 1024
                else f"{size_bytes / 1024:.1f}KB"
                if size_bytes < 1048576
                else f"{size_bytes / 1048576:.1f}MB"
            )
            return size_str, int(stat.st_mtime * 1000)
        except OSError:
            return "", 0


__all__ = ["WorkspaceTreeService"]
