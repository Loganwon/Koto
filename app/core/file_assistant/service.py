# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import zipfile

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv",
    ".py", ".js", ".ts", ".json", ".html", ".css", ".xml",
    ".sh", ".bash", ".yaml", ".yml",
    ".c", ".cpp", ".h", ".hpp", ".java", ".rb", ".go",
    ".rs", ".cs", ".php", ".swift", ".kt", ".r", ".sql",
    ".toml", ".ini", ".cfg", ".conf",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}

OFFICE_EXTENSIONS = {".docx", ".xlsx", ".pptx", ".pdf"}

ALLOWED_EXTENSIONS = OFFICE_EXTENSIONS | TEXT_EXTENSIONS | IMAGE_EXTENSIONS

PPTX_MAX_BYTES = 100 * 1024 * 1024

DocxOpenParser = Callable[..., dict[str, Any]]
CopyDocxToTmp = Callable[..., None]
PptxParser = Callable[[bytes], dict[str, Any]]
PptxExporter = Callable[[str, Any], bytes]


class UnsupportedFileTypeError(ValueError):
    """Raised when the file assistant cannot open or export a format."""


class FileTooLargeError(ValueError):
    """Raised when an otherwise supported file exceeds editor limits."""

    def __init__(self, message: str, *, status_code: int = 413) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ParsedEditorFile:
    file_type: str
    data: dict[str, Any]


@dataclass(frozen=True)
class ExportedEditorFile:
    raw_bytes: bytes
    mime: str
    file_name: str
    suffix: str


class FileAssistantService:
    """Format dispatch boundary for the workspace file assistant."""

    def parse_editor_file(
        self,
        file_path: str | Path,
        *,
        file_id: str,
        display_name: str | None = None,
        text_source_path: str | Path | None = None,
        source_path: str | Path | None = None,
        docx_open_parser: DocxOpenParser | None = None,
        docx_copy_to_tmp: CopyDocxToTmp | None = None,
        pptx_parser: PptxParser | None = None,
    ) -> ParsedEditorFile:
        path = Path(file_path)
        name = display_name or path.name
        ext = path.suffix.lower()

        if ext == ".docx":
            if docx_open_parser is not None:
                data = docx_open_parser(
                    path,
                    file_id,
                    source_path=Path(source_path) if source_path is not None else None,
                )
            elif docx_copy_to_tmp is not None:
                data = self.parse_docx_for_workspace_open(
                    path,
                    file_id=file_id,
                    source_path=Path(source_path) if source_path is not None else None,
                    copy_to_tmp=docx_copy_to_tmp,
                )
            else:
                from app.core.file.parsers.docx_parser import parse_docx

                data = parse_docx(str(path))
                data["raw_url"] = f"/api/v1/workspace/raw/{file_id}"
            return ParsedEditorFile(file_type="docx", data=data)

        if ext == ".xlsx":
            from app.core.file.parsers.xlsx_parser import parse_xlsx

            return ParsedEditorFile(
                file_type="xlsx",
                data=parse_xlsx(str(path), original_name=name),
            )

        if ext == ".pptx":
            size = path.stat().st_size
            if size > PPTX_MAX_BYTES:
                raise FileTooLargeError(
                    f"PPTX 文件过大 ({size / 1048576:.0f} MB)，可能包含嵌入视频。"
                    "Koto 当前不支持超过 100 MB 的 PPTX 文件，建议先在 PowerPoint 中删除视频后再打开。"
                )
            parser = pptx_parser or self._default_pptx_parser
            return ParsedEditorFile(file_type="pptx", data=parser(path.read_bytes()))

        if ext == ".pdf":
            from app.core.file.parsers.pdf_parser import parse_pdf

            return ParsedEditorFile(file_type="pdf", data=parse_pdf(str(path), file_id))

        if ext in IMAGE_EXTENSIONS:
            return ParsedEditorFile(
                file_type="image",
                data={"raw_url": f"/api/v1/workspace/raw/{file_id}"},
            )

        if ext in TEXT_EXTENSIONS:
            source = Path(text_source_path) if text_source_path is not None else path
            content = source.read_text(encoding="utf-8", errors="replace")
            file_type = "text" if ext in {".txt", ".md", ".markdown", ".csv"} else "code"
            return ParsedEditorFile(
                file_type=file_type,
                data={"content": content, "language": ext.lstrip("."), "extension": ext},
            )

        raise UnsupportedFileTypeError(f"不支持的格式: {ext}")

    def parse_docx_for_workspace_open(
        self,
        tmp_path: str | Path,
        *,
        file_id: str,
        source_path: str | Path | None = None,
        copy_to_tmp: CopyDocxToTmp | None = None,
    ) -> dict[str, Any]:
        from app.core.file.parsers.docx_parser import parse_docx

        tmp = Path(tmp_path)
        source = Path(source_path) if source_path is not None else None

        try:
            data = parse_docx(str(tmp))
        except Exception as exc:
            if source is None or copy_to_tmp is None or not self.should_retry_docx_tmp_parse(exc, tmp):
                raise
            copy_to_tmp(source, tmp, ext=".docx")
            data = parse_docx(str(tmp))

        data["raw_url"] = f"/api/v1/workspace/raw/{file_id}"
        return data

    def load_full_docx(self, file_path: str | Path, *, file_id: str) -> dict[str, Any]:
        parsed = self.parse_editor_file(file_path, file_id=file_id)
        if parsed.file_type != "docx":
            raise UnsupportedFileTypeError("DOCX 完整加载仅支持 .docx 文件")
        return parsed.data

    def export_editor_file(
        self,
        *,
        file_type: str,
        file_id: str = "",
        data: Any,
        file_name: str,
        tmp_dir: str | Path | None = None,
        pptx_exporter: PptxExporter | None = None,
    ) -> ExportedEditorFile:
        kind = (file_type or "").lower()

        if kind == "docx":
            from app.core.file.exporters.docx_exporter import export_docx

            original_path = self._original_tmp_path(tmp_dir, file_id, ".docx")
            raw_bytes = export_docx(data, original_path=original_path)
            return ExportedEditorFile(
                raw_bytes=raw_bytes,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                file_name=self._ensure_suffix(file_name, ".docx"),
                suffix=".docx",
            )

        if kind == "xlsx":
            from app.core.file.exporters.xlsx_exporter import export_workbook_payload

            raw_bytes = export_workbook_payload(data)
            return ExportedEditorFile(
                raw_bytes=raw_bytes,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                file_name=self._ensure_suffix(file_name, ".xlsx"),
                suffix=".xlsx",
            )

        if kind == "pptx":
            if pptx_exporter is None:
                raise FileNotFoundError("PPTX 保存需要原始文件上下文")
            raw_bytes = pptx_exporter(file_id, data)
            return ExportedEditorFile(
                raw_bytes=raw_bytes,
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                file_name=self._ensure_suffix(file_name, ".pptx"),
                suffix=".pptx",
            )

        if kind in {"text", "code"}:
            content = data if isinstance(data, str) else (data.get("content", "") if isinstance(data, dict) else "")
            suffix = Path(file_name).suffix.lower() if file_name else ".txt"
            mime = "text/markdown; charset=utf-8" if suffix == ".md" else "text/plain; charset=utf-8"
            return ExportedEditorFile(
                raw_bytes=content.encode("utf-8"),
                mime=mime,
                file_name=file_name,
                suffix=suffix or ".txt",
            )

        raise UnsupportedFileTypeError(f"不支持的导出格式: {kind}")

    @staticmethod
    def _default_pptx_parser(raw_bytes: bytes) -> dict[str, Any]:
        from web.blueprints.pptx_editor import _parse_slides as _pptx_rich_parse

        return _pptx_rich_parse(raw_bytes)

    @staticmethod
    def _ensure_suffix(file_name: str, suffix: str) -> str:
        if file_name.lower().endswith(suffix):
            return file_name
        return Path(file_name).stem + suffix

    @staticmethod
    def _original_tmp_path(tmp_dir: str | Path | None, file_id: str, suffix: str) -> str | None:
        if not tmp_dir or not file_id:
            return None
        original = Path(tmp_dir) / f"{file_id}{suffix}"
        return str(original) if original.is_file() else None

    @staticmethod
    def should_retry_docx_tmp_parse(exc: Exception, tmp_path: str | Path) -> bool:
        if isinstance(exc, zipfile.BadZipFile):
            return True

        message = str(exc or "")
        tmp_str = str(tmp_path)
        return (
            ("Package not found at" in message and tmp_str in message)
            or "File is not a zip file" in message
            or "not a zip file" in message
            or not Path(tmp_path).is_file()
        )
