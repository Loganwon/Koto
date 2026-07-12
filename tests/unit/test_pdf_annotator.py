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


def test_remove_watermark_removes_repeated_light_text(tmp_path):
    import pymupdf

    from web.pdf_annotator import remove_watermark

    source = tmp_path / "watermarked.pdf"
    doc = pymupdf.open()
    for _ in range(3):
        page = doc.new_page()
        page.insert_text(
            (180, 400),
            "CONFIDENTIAL",
            fontsize=24,
            color=(0.8, 0.8, 0.8),
        )
        page.insert_text((72, 72), "Keep this content", fontsize=12)
    doc.save(source)
    doc.close()

    cleaned_bytes, removed_count, method = remove_watermark(
        str(source), use_ai=False
    )

    cleaned = pymupdf.open(stream=cleaned_bytes, filetype="pdf")
    cleaned_text = "\n".join(page.get_text() for page in cleaned)
    cleaned.close()

    assert removed_count == 3
    assert method == "structural"
    assert "CONFIDENTIAL" not in cleaned_text
    assert cleaned_text.count("Keep this content") == 3
