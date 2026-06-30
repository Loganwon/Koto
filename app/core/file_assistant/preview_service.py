# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from app.core.file_assistant.open_service import (
    OpenFileByPathService,
    OpenFileInConfigError,
    OpenFileNotFoundError,
    OpenFilePermissionError,
    OpenFileUnsupportedTypeError,
    PathGuard,
)
from app.core.file_assistant.service import IMAGE_EXTENSIONS

logger = logging.getLogger(__name__)

TextParser = Callable[[str, int], str]
DocxCharCounter = Callable[[str], int]


@dataclass(frozen=True)
class FileContextPreview:
    path: str
    file_name: str
    file_type: str
    content_preview: str
    original_chars: int
    preview_error: str


class FileContextPreviewService:
    """Build lightweight text previews for AI file attachments."""

    def build(
        self,
        *,
        raw_path: str,
        workspace_dir: str | Path,
        app_config_dir: str | Path,
        allowed_extensions: Iterable[str],
        fs_guard: PathGuard,
        preview_limit: int,
        text_parser: TextParser | None = None,
        docx_char_counter: DocxCharCounter | None = None,
    ) -> FileContextPreview:
        target = OpenFileByPathService.resolve_target(
            raw_path=raw_path,
            workspace_dir=workspace_dir,
            app_config_dir=app_config_dir,
            fs_guard=fs_guard,
        )
        if not target.is_file():
            raise OpenFileNotFoundError("文件不存在")

        ext = target.suffix.lower()
        if ext not in {str(item).lower() for item in allowed_extensions}:
            raise OpenFileUnsupportedTypeError(f"不支持的格式: {ext}")

        file_type = self._file_type_for_extension(ext)
        preview_limit = self.normalize_preview_limit(preview_limit)
        extraction_limit = min(max(preview_limit * 2, 4_000), 60_000)

        preview_text = ""
        preview_error = ""
        original_chars = 0
        if ext not in IMAGE_EXTENSIONS:
            parser = text_parser or self._default_text_parser
            try:
                preview_text = parser(str(target), extraction_limit)
            except Exception as exc:
                logger.exception("[ai_context_preview] 文本预览异常 %s", target.name)
                preview_error = f"文件预览解析失败: {exc}"
                preview_text = ""
            else:
                if preview_text.startswith("Error parsing file:"):
                    logger.warning(
                        "[ai_context_preview] 文本预览解析失败 %s: %s",
                        target.name,
                        preview_text,
                    )
                    preview_error = preview_text
                    preview_text = ""
                elif preview_text.startswith("(File parsed but no text content:"):
                    preview_text = ""

            preview_chars = len("".join(preview_text.split()))
            if ext == ".docx":
                counter = docx_char_counter or self._default_docx_char_counter
                try:
                    original_chars = counter(str(target)) or preview_chars
                except Exception as exc:
                    logger.debug(
                        "[ai_context_preview] DOCX 字数统计回退到预览长度 %s: %s",
                        target.name,
                        exc,
                    )
                    original_chars = preview_chars
            else:
                original_chars = preview_chars
            preview_text = self.sample_text(preview_text, preview_limit)

        return FileContextPreview(
            path=raw_path,
            file_name=target.name,
            file_type=file_type,
            content_preview=preview_text,
            original_chars=original_chars,
            preview_error=preview_error,
        )

    @staticmethod
    def normalize_preview_limit(value: int) -> int:
        return max(1_000, min(int(value), 24_000))

    @staticmethod
    def sample_text(text: str, limit: int = 12_000) -> str:
        content = str(text or "")
        if len(content) <= limit:
            return content

        marker = "\n\n...[中间内容已省略]...\n\n"
        head = max(int(limit * 0.7), 1)
        tail = max(limit - head - len(marker), 0)
        if tail <= 0:
            return content[:limit]
        return content[:head] + marker + content[-tail:]

    @staticmethod
    def _file_type_for_extension(ext: str) -> str:
        if ext == ".docx":
            return "docx"
        if ext == ".xlsx":
            return "xlsx"
        if ext == ".pptx":
            return "pptx"
        if ext == ".pdf":
            return "pdf"
        if ext in IMAGE_EXTENSIONS:
            return "image"
        if ext in {".txt", ".md", ".markdown"}:
            return "text"
        return "code"

    @staticmethod
    def _default_text_parser(path: str, max_chars: int) -> str:
        from app.core.agent.task_tools import parse_file_to_text

        return parse_file_to_text(path, max_chars=max_chars)

    @staticmethod
    def _default_docx_char_counter(path: str) -> int:
        from app.core.file.parsers.docx_parser import count_docx_visible_chars

        return count_docx_visible_chars(path)


__all__ = [
    "FileContextPreview",
    "FileContextPreviewService",
    "OpenFileInConfigError",
    "OpenFileNotFoundError",
    "OpenFilePermissionError",
    "OpenFileUnsupportedTypeError",
]
