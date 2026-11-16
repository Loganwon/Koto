"""Canonical PPTX editor parser/exporter used by the workspace boundary."""

from __future__ import annotations

import base64
import io
from typing import Any

from app.core.file.parsers.pptx_parser import parse_pptx_geometry


def parse_slides(raw_bytes: bytes) -> dict[str, Any]:
    """Parse PPTX bytes into the geometry contract consumed by the editor."""
    parsed = parse_pptx_geometry(io.BytesIO(raw_bytes))
    slides = parsed.get("slides", []) if isinstance(parsed, dict) else []
    for index, slide in enumerate(slides):
        if not isinstance(slide, dict):
            continue
        slide.setdefault("index", slide.get("slide_index", index))
        for shape in slide.get("shapes", []):
            if isinstance(shape, dict) and "type" not in shape and "_type" in shape:
                shape["type"] = shape["_type"]
    return parsed


def _remove_xml(element: Any) -> None:
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def _sync_text_frame(text_frame: Any, paragraph_edits: list[dict[str, Any]]) -> None:
    wanted_paragraphs = max(1, len(paragraph_edits))
    paragraphs = list(text_frame.paragraphs)
    while len(paragraphs) > wanted_paragraphs:
        _remove_xml(paragraphs.pop()._p)
    while len(paragraphs) < wanted_paragraphs:
        paragraphs.append(text_frame.add_paragraph())

    for paragraph_index, paragraph in enumerate(paragraphs):
        edit = (
            paragraph_edits[paragraph_index]
            if paragraph_index < len(paragraph_edits)
            else {}
        )
        run_edits = edit.get("runs") if isinstance(edit.get("runs"), list) else []
        runs = list(paragraph.runs)
        while len(runs) > len(run_edits):
            _remove_xml(runs.pop()._r)
        while len(runs) < len(run_edits):
            runs.append(paragraph.add_run())
        for run, run_edit in zip(runs, run_edits):
            run.text = str(run_edit.get("text") or "")
            font = run.font
            for key in ("bold", "italic", "underline"):
                if key in run_edit:
                    setattr(font, key, bool(run_edit[key]))
            if run_edit.get("size") is not None:
                from pptx.util import Pt

                font.size = Pt(float(run_edit["size"]))
            color = str(run_edit.get("color") or "").lstrip("#")
            if len(color) == 6:
                from pptx.dml.color import RGBColor

                font.color.rgb = RGBColor.from_string(color.upper())

        align = str(edit.get("align") or "").upper()
        if align:
            from pptx.enum.text import PP_ALIGN

            alignment = {
                "LEFT": PP_ALIGN.LEFT,
                "CENTER": PP_ALIGN.CENTER,
                "RIGHT": PP_ALIGN.RIGHT,
                "JUSTIFY": PP_ALIGN.JUSTIFY,
            }.get(align)
            if alignment is not None:
                paragraph.alignment = alignment


def apply_edits(orig_bytes: bytes, slides_edits: list[dict[str, Any]]) -> bytes:
    """Apply editor text/table changes while preserving the PPTX package."""
    from pptx import Presentation

    presentation = Presentation(io.BytesIO(orig_bytes))
    by_index = {
        int(item.get("slide_index", item.get("index", index))): item
        for index, item in enumerate(slides_edits or [])
        if isinstance(item, dict)
    }
    for slide_index, slide in enumerate(presentation.slides):
        slide_edit = by_index.get(slide_index)
        if not slide_edit:
            continue
        shape_edits = {
            int(item.get("id")): item
            for item in slide_edit.get("shapes", [])
            if isinstance(item, dict) and item.get("id") is not None
        }
        existing_shape_ids: set[int] = set()
        for shape in slide.shapes:
            existing_shape_ids.add(int(shape.shape_id))
            edit = shape_edits.get(int(shape.shape_id))
            if not edit:
                continue
            if getattr(shape, "has_text_frame", False):
                paragraphs = edit.get("paragraphs")
                if isinstance(paragraphs, list):
                    _sync_text_frame(shape.text_frame, paragraphs)
            if getattr(shape, "has_table", False) and isinstance(
                edit.get("cells"), list
            ):
                for cell_edit in edit["cells"]:
                    try:
                        cell = shape.table.cell(
                            int(cell_edit["row"]), int(cell_edit["col"])
                        )
                        cell.text = str(cell_edit.get("text") or "")
                    except (KeyError, IndexError, TypeError, ValueError):
                        continue

        for shape_edit in slide_edit.get("shapes", []):
            if not isinstance(shape_edit, dict):
                continue
            try:
                shape_id = int(shape_edit.get("id"))
            except (TypeError, ValueError):
                continue
            if shape_id in existing_shape_ids:
                continue
            shape_type = (
                str(shape_edit.get("type") or shape_edit.get("_type") or "")
                .strip()
                .lower()
            )
            image_source = str(shape_edit.get("image_b64") or "").strip()
            if shape_type not in {"picture", "image"} or not image_source:
                continue
            encoded = image_source.split(",", 1)[-1]
            try:
                image_bytes = base64.b64decode(encoded, validate=True)
                slide.shapes.add_picture(
                    io.BytesIO(image_bytes),
                    int(shape_edit.get("left") or 0),
                    int(shape_edit.get("top") or 0),
                    width=int(shape_edit.get("width") or 1),
                    height=int(shape_edit.get("height") or 1),
                )
            except (ValueError, TypeError, base64.binascii.Error):
                continue

    output = io.BytesIO()
    presentation.save(output)
    return output.getvalue()


__all__ = ["apply_edits", "parse_slides"]
