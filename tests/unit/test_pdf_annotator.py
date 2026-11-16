# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations

from io import BytesIO


def _annotation_object(pdf_bytes: bytes, index: int = 0):
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(pdf_bytes))
    return reader.pages[0]["/Annots"][index].get_object()


def _rect_values(annotation) -> list[float]:
    return [round(float(value), 3) for value in annotation["/Rect"]]


def test_embed_annotations_accepts_frontend_rect_objects(tmp_path):
    from pypdf import PdfReader, PdfWriter

    from app.core.services.pdf_annotator import embed_annotations

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


def test_embed_textbox_converts_css_coordinates_and_preserves_text(tmp_path):
    from pypdf import PdfWriter

    from app.core.services.pdf_annotator import embed_annotations

    source = tmp_path / "textbox-source.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with source.open("wb") as handle:
        writer.write(handle)

    annotated = embed_annotations(
        str(source),
        [
            {
                "type": "textbox",
                "page": 1,
                "pageWidth": 306,
                "pageHeight": 396,
                "x": 30,
                "y": 40,
                "w": 100,
                "h": 30,
                "text": "Positioned text",
                "fontSize": 14,
                "color": "#CC0000",
            }
        ],
    )

    annotation = _annotation_object(annotated)
    assert str(annotation["/Subtype"]) == "/FreeText"
    assert str(annotation["/Contents"]) == "Positioned text"
    assert _rect_values(annotation) == [60.0, 652.0, 260.0, 712.0]
    assert "/Helv 28.0 Tf" in str(annotation["/DA"])


def test_embed_textbox_generates_visible_non_solid_appearance(tmp_path):
    import pymupdf
    from pypdf import PdfWriter

    from app.core.services.pdf_annotator import embed_annotations

    source = tmp_path / "textbox-appearance-source.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with source.open("wb") as handle:
        writer.write(handle)

    annotated = embed_annotations(
        str(source),
        [
            {
                "type": "textbox",
                "page": 1,
                "pageWidth": 306,
                "pageHeight": 396,
                "x": 30,
                "y": 40,
                "w": 100,
                "h": 30,
                "text": "VISIBLE EDIT",
                "fontSize": 14,
                "color": "#CC0000",
            }
        ],
    )

    rendered = pymupdf.open(stream=annotated, filetype="pdf")
    pixmap = rendered[0].get_pixmap(alpha=False, annots=True)
    red_pixels = 0
    for y in range(80, 140):
        for x in range(60, 260):
            offset = (y * pixmap.width + x) * pixmap.n
            red, green, blue = pixmap.samples[offset : offset + 3]
            if red > 140 and green < 100 and blue < 100:
                red_pixels += 1
    rendered.close()

    assert red_pixels > 50
    assert red_pixels < 3000  # guard against the old solid colour rectangle


def test_embed_cjk_textbox_is_visible_and_keeps_unicode_metadata(tmp_path):
    import pymupdf
    from pypdf import PdfWriter

    from app.core.services.pdf_annotator import embed_annotations

    source = tmp_path / "cjk-textbox-source.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with source.open("wb") as handle:
        writer.write(handle)

    annotated = embed_annotations(
        str(source),
        [
            {
                "type": "textbox",
                "page": 1,
                "pageWidth": 306,
                "pageHeight": 396,
                "x": 30,
                "y": 40,
                "w": 100,
                "h": 30,
                "text": "中文编辑",
                "fontSize": 14,
                "color": "#CC0000",
            }
        ],
    )

    annotation = _annotation_object(annotated)
    assert str(annotation["/Contents"]) == "中文编辑"
    assert str(annotation["/Subj"]) == "KotoFlattenedTextBox"

    rendered = pymupdf.open(stream=annotated, filetype="pdf")
    pixmap = rendered[0].get_pixmap(alpha=False, annots=True)
    red_pixels = 0
    for y in range(80, 140):
        for x in range(60, 260):
            offset = (y * pixmap.width + x) * pixmap.n
            red, green, blue = pixmap.samples[offset : offset + 3]
            if red > 140 and green < 100 and blue < 100:
                red_pixels += 1
    rendered.close()

    assert red_pixels > 50
    assert red_pixels < 3000


def test_embed_draw_accepts_frontend_points_and_flips_y_axis(tmp_path):
    from pypdf import PdfWriter

    from app.core.services.pdf_annotator import embed_annotations

    source = tmp_path / "draw-source.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with source.open("wb") as handle:
        writer.write(handle)

    annotated = embed_annotations(
        str(source),
        [
            {
                "type": "draw",
                "page": 1,
                "pageWidth": 306,
                "pageHeight": 396,
                "points": [{"x": 10, "y": 20}, {"x": 30, "y": 40}],
                "lineWidth": 2,
            }
        ],
    )

    annotation = _annotation_object(annotated)
    ink_values = [float(value) for value in annotation["/InkList"][0]]
    assert ink_values == [20.0, 752.0, 60.0, 712.0]
    assert _rect_values(annotation) == [12.0, 704.0, 68.0, 760.0]


def test_embed_note_preserves_frontend_position_and_content(tmp_path):
    from pypdf import PdfWriter

    from app.core.services.pdf_annotator import embed_annotations

    source = tmp_path / "note-source.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with source.open("wb") as handle:
        writer.write(handle)

    annotated = embed_annotations(
        str(source),
        [
            {
                "type": "note",
                "page": 1,
                "pageWidth": 306,
                "pageHeight": 396,
                "x": 50,
                "y": 60,
                "text": "Remember this",
            }
        ],
    )

    annotation = _annotation_object(annotated)
    assert str(annotation["/Subtype"]) == "/Text"
    assert str(annotation["/Contents"]) == "Remember this"
    assert _rect_values(annotation) == [100.0, 652.0, 120.0, 672.0]


def test_embed_textbox_honors_rotated_page_viewport(tmp_path):
    from pypdf import PdfWriter

    from app.core.services.pdf_annotator import embed_annotations

    source = tmp_path / "rotated-source.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    page.rotate(90)
    with source.open("wb") as handle:
        writer.write(handle)

    annotated = embed_annotations(
        str(source),
        [
            {
                "type": "textbox",
                "page": 1,
                "pageWidth": 396,
                "pageHeight": 306,
                "x": 10,
                "y": 20,
                "w": 30,
                "h": 40,
                "text": "Rotated",
            }
        ],
    )

    assert _rect_values(_annotation_object(annotated)) == [40.0, 20.0, 120.0, 80.0]


def test_read_annotations_marks_pdf_coordinate_space_for_frontend_hydration(tmp_path):
    from pypdf import PdfWriter

    from app.core.services.pdf_annotator import embed_annotations, read_annotations

    source = tmp_path / "roundtrip-source.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with source.open("wb") as handle:
        writer.write(handle)

    annotated = embed_annotations(
        str(source),
        [
            {
                "type": "textbox",
                "page": 1,
                "pageWidth": 306,
                "pageHeight": 396,
                "x": 30,
                "y": 40,
                "w": 100,
                "h": 30,
                "text": "Reload me",
                "fontSize": 14,
                "color": "#CC0000",
            },
            {
                "type": "line",
                "page": 1,
                "pageWidth": 306,
                "pageHeight": 396,
                "x1": 10,
                "y1": 20,
                "x2": 30,
                "y2": 40,
            },
        ],
    )
    saved = tmp_path / "roundtrip-annotated.pdf"
    saved.write_bytes(annotated)

    loaded = read_annotations(str(saved))

    loaded_by_type = {item["type"]: item for item in loaded}
    assert set(loaded_by_type) == {"textbox", "line"}
    assert all(item["coordinateSpace"] == "pdf" for item in loaded)
    assert loaded_by_type["textbox"]["text"] == "Reload me"
    assert loaded_by_type["textbox"]["color"] == "#CC0000"
    assert loaded_by_type["textbox"]["pdfFontSize"] == 28.0
    assert loaded_by_type["line"]["line"] == [20.0, 752.0, 60.0, 712.0]


def test_remove_watermark_removes_repeated_light_text(tmp_path):
    import pymupdf

    from app.core.services.pdf_annotator import remove_watermark

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

    cleaned_bytes, removed_count, method = remove_watermark(str(source), use_ai=False)

    cleaned = pymupdf.open(stream=cleaned_bytes, filetype="pdf")
    cleaned_text = "\n".join(page.get_text() for page in cleaned)
    cleaned.close()

    assert removed_count == 3
    assert method == "structural"
    assert "CONFIDENTIAL" not in cleaned_text
    assert cleaned_text.count("Keep this content") == 3


def test_remove_watermark_changes_rendered_pixels_not_only_text_extraction(tmp_path):
    import pymupdf

    from app.core.services.pdf_annotator import remove_watermark

    source = tmp_path / "visual-watermark.pdf"
    document = pymupdf.open()
    for _ in range(2):
        page = document.new_page(width=612, height=792)
        page.insert_text(
            (170, 410),
            "CONFIDENTIAL",
            fontsize=28,
            color=(0.72, 0.72, 0.72),
        )
        page.insert_text((72, 72), "Keep this content", fontsize=12)
    document.save(source)
    document.close()

    def non_white_pixels(pdf_bytes: bytes | None = None) -> int:
        doc = (
            pymupdf.open(stream=pdf_bytes, filetype="pdf")
            if pdf_bytes is not None
            else pymupdf.open(source)
        )
        pixmap = doc[0].get_pixmap(matrix=pymupdf.Matrix(1, 1), alpha=False)
        samples = pixmap.samples
        count = 0
        for y in range(370, 430):
            for x in range(150, 420):
                offset = (y * pixmap.width + x) * pixmap.n
                if min(samples[offset : offset + 3]) < 245:
                    count += 1
        doc.close()
        return count

    before = non_white_pixels()
    cleaned_bytes, removed_count, _ = remove_watermark(str(source), use_ai=False)
    after = non_white_pixels(cleaned_bytes)

    assert removed_count == 2
    assert before > 100
    assert after < before * 0.1


def test_remove_watermark_detects_strong_single_page_visual_signal(tmp_path):
    import pymupdf

    from app.core.services.pdf_annotator import remove_watermark

    source = tmp_path / "single-page-watermark.pdf"
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_text(
        (190, 410),
        "ACME REVIEW",
        fontsize=30,
        color=(0.78, 0.78, 0.78),
    )
    page.insert_text((72, 72), "Keep this content", fontsize=12)
    document.save(source)
    document.close()

    cleaned_bytes, removed_count, method = remove_watermark(str(source), use_ai=False)
    cleaned = pymupdf.open(stream=cleaned_bytes, filetype="pdf")
    cleaned_text = cleaned[0].get_text()
    cleaned.close()

    assert removed_count == 1
    assert method == "structural"
    assert "ACME REVIEW" not in cleaned_text
    assert "Keep this content" in cleaned_text


def test_remove_watermark_keeps_single_page_dark_heading(tmp_path):
    import pymupdf

    from app.core.services.pdf_annotator import remove_watermark

    source = tmp_path / "single-page-heading.pdf"
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((190, 410), "ANNUAL REPORT", fontsize=30, color=(0, 0, 0))
    document.save(source)
    document.close()

    cleaned_bytes, removed_count, method = remove_watermark(str(source), use_ai=False)
    cleaned = pymupdf.open(stream=cleaned_bytes, filetype="pdf")
    cleaned_text = cleaned[0].get_text()
    cleaned.close()

    assert removed_count == 0
    assert method == "none"
    assert "ANNUAL REPORT" in cleaned_text
    assert cleaned_bytes == source.read_bytes()


def test_scanned_pdf_to_xlsx_returns_visible_noneditable_warning(tmp_path):
    import pymupdf
    from openpyxl import load_workbook
    from PIL import Image, ImageDraw

    from app.core.services.pdf_annotator import pdf_to_xlsx_with_report

    image = Image.new("RGB", (640, 320), "white")
    ImageDraw.Draw(image).text((30, 30), "SCANNED INVOICE 2026", fill="black")
    image_path = tmp_path / "scan.png"
    image.save(image_path)

    source = tmp_path / "scanned.pdf"
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_image(pymupdf.Rect(36, 60, 576, 330), filename=str(image_path))
    document.save(source)
    document.close()

    output, warning = pdf_to_xlsx_with_report(str(source))
    workbook = load_workbook(BytesIO(output))

    assert "扫描型页面" in warning
    assert warning in str(workbook.worksheets[0]["A1"].value)
