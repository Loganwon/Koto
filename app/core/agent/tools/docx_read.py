"""Domain module - DOCX read tools."""

from __future__ import annotations

import json

from ..task_tools_common import _TEXT_LIMIT_DOCX_DEFAULT
from ._internal_fs import _resolve_path
from ._internal_normalize import _normalize_text_limit


def read_docx_content(path: str, max_chars: int = _TEXT_LIMIT_DOCX_DEFAULT) -> str:
    """Read DOCX paragraphs as structured JSON.

    Returns JSON with paragraphs and tables.
    """
    resolved = _resolve_path(path)
    if not resolved:
        return json.dumps({"error": f"File not found: {path}"}, ensure_ascii=False)

    max_chars = _normalize_text_limit(max_chars, _TEXT_LIMIT_DOCX_DEFAULT)

    try:
        from docx import Document as DocxDocument

        doc = DocxDocument(resolved)
        paragraphs = []
        tables = []
        total = 0
        for p in doc.paragraphs:
            if total >= max_chars:
                break
            paragraphs.append(
                {
                    "text": p.text,
                    "style": p.style.name if p.style else "",
                }
            )
            total += len(p.text)

        for table_index, table in enumerate(doc.tables):
            if total >= max_chars:
                break
            table_rows = []
            for row in table.rows:
                if total >= max_chars:
                    break
                values = [cell.text for cell in row.cells]
                table_rows.append(values)
                total += sum(len(v) for v in values)
            tables.append(
                {
                    "index": table_index,
                    "rows": table_rows,
                    "row_count": len(table.rows),
                    "column_count": len(table.columns),
                }
            )

        return json.dumps(
            {
                "paragraphs": paragraphs,
                "tables": tables,
                "total_paragraphs": len(doc.paragraphs),
                "total_tables": len(doc.tables),
                "truncated": (
                    len(paragraphs) < len(doc.paragraphs)
                    or len(tables) < len(doc.tables)
                    or any(
                        len(table_payload.get("rows") or [])
                        < int(table_payload.get("row_count") or 0)
                        for table_payload in tables
                    )
                ),
            },
            ensure_ascii=False,
        )
    except ImportError:
        return json.dumps({"error": "python-docx not installed"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def _read_docx_paragraph_window(
    path: str,
    *,
    max_chars: int,
    start: int,
    end: int,
) -> str:
    from docx import Document as DocxDocument

    doc = DocxDocument(path)
    start = max(1, int(start or 1))
    end = max(start, int(end or start))
    parts: list[str] = []
    total = 0
    for index, paragraph in enumerate(doc.paragraphs, start=1):
        if index < start:
            continue
        if index > end:
            break
        text = str(paragraph.text or "").strip()
        if not text:
            continue
        block = f"[Paragraph {index}]\n{text}"
        parts.append(block)
        total += len(block)
        if total >= max_chars:
            break
    return "\n\n".join(parts)
