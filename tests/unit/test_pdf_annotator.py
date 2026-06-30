# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

from io import BytesIO


def test_embed_annotations_accepts_frontend_rect_objects(tmp_path):
    from pypdf import PdfReader, PdfWriter

    from web.pdf_annotator import embed_annotations

    source = tmp_path / "source.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with source.open("wb") as fh:
        writer.write(fh)

    annotated = embed_annotations(
        str(source),
        [
            {
                "type": "highlight",
                "page": 1,
                "pageWidth": 306,
                "pageHeight": 396,
                "rects": [{"x": 10, "y": 20, "w": 80, "h": 12}],
                "color": "#FFFF00",
                "content": "AI建议：关注此处",
            }
        ],
    )

    reader = PdfReader(BytesIO(annotated))
    annots = reader.pages[0].get("/Annots")

    assert annots
    annot = annots[0].get_object()
    assert str(annot.get("/Subtype")) == "/Highlight"
    assert "AI建议" in str(annot.get("/Contents"))
