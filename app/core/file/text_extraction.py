"""Plain-text extraction for files used by Agent read tools.

This module is intentionally transport- and model-free.  It exposes one atomic
read capability and does not start a workflow or make an LLM call.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


def parse_source_file(file_path: str, *, strict: bool = False) -> str:
    """Return plain text; read tools may request explicit parse failures."""

    path = Path(file_path)
    suffix = path.suffix.lower()

    try:
        if suffix == ".pdf":
            from app.core.file.parsers.pdf_parser import parse_pdf

            result = parse_pdf(str(path), str(uuid.uuid4()))
            return result.get("text", "")

        if suffix in {".doc", ".docx"}:
            from app.core.file.parsers.docx_parser import parse_docx

            result = parse_docx(str(path))
            html = result.get("html", "") or result.get("content", "")
            return re.sub(r"<[^>]+>", " ", html).strip()

        if suffix in {".xls", ".xlsx", ".xlsm"}:
            from app.core.file.parsers.xlsx_parser import parse_xlsx

            result = parse_xlsx(str(path), path.name)
            lines: list[str] = []
            for sheet_id, sheet in result.get("sheets", {}).items():
                lines.append(f"[Sheet: {sheet.get('name', sheet_id)}]")
                cell_data = sheet.get("cellData", {})
                for row_index in sorted(cell_data, key=lambda value: int(value)):
                    row = cell_data[row_index]
                    max_column = max((int(key) for key in row), default=-1)
                    cells = []
                    for column in range(max_column + 1):
                        cell = row.get(column) or row.get(str(column)) or {}
                        cells.append(str(cell.get("v", "") or ""))
                    lines.append("\t".join(cells))
            return "\n".join(lines)

        if suffix in {".ppt", ".pptx"}:
            from app.core.file.parsers.pptx_parser import parse_pptx

            slides = parse_pptx(str(path))
            lines: list[str] = []
            for slide in slides:
                lines.append(f"[Slide {slide.get('slide_index', '?') + 1}]")
                for text_item in slide.get("texts", []):
                    lines.append(text_item.get("text", ""))
            return "\n".join(lines)

        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.warning("[TextExtraction] Failed to parse %s: %s", file_path, exc)
        if strict:
            raise
        return ""


__all__ = ["parse_source_file"]
