"""
pdf_annotator.py — Embed / read PDF annotations, page ops, and format conversion.

Annotation types supported (matching KotoPdfViewer JS):
  highlight, underline, strikethrough, note, draw, shapes, textbox

The browser sends top-left CSS-pixel coordinates together with the rendered
page size.  This module owns the conversion to PDF points, including page
rotation.  Keeping that conversion in one place prevents individual tools
from silently writing annotations at the wrong location.

Format conversion:
  pdf_to_docx  — via doc_converter (LibreOffice → pypdf text fallback)
  pdf_to_xlsx  — via pdfplumber table extraction → openpyxl
  pdf_to_pptx  — via PyMuPDF page images → python-pptx slides
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def embed_annotations(pdf_path: str, annotations: list[dict]) -> bytes:
    """
    Read *pdf_path*, embed *annotations*, and return the modified PDF bytes.

    Each annotation dict must have:
        page   : int   — 1-based page number
        type   : str   — "highlight" | "underline" | "strikethrough" | "note" | "draw"
        color  : str   — hex color, e.g. "#FFFF00"
        rects  : list  — list of [x1, y1, x2, y2] in PDF points (for text annots)
        content: str   — optional text (used for notes)
        inkList: list  — for draw: list of point arrays [[x,y], ...]

    Returns the bytes of the annotated PDF.
    """
    try:
        from pypdf import PdfReader, PdfWriter  # type: ignore
        from pypdf.generic import (  # type: ignore
            ArrayObject,
            DictionaryObject,
            FloatObject,
            NameObject,
            NumberObject,
            TextStringObject,
        )
    except ImportError as exc:
        raise RuntimeError("pypdf is required for annotation embedding") from exc

    with open(pdf_path, "rb") as fh:
        reader = PdfReader(fh)
        writer = PdfWriter()
        writer.clone_reader_document_root(reader)

        prepared_annotations: list[dict] = []
        for index, source_annot in enumerate(annotations):
            annot = dict(source_annot)
            annot["_koto_id"] = f"koto-{index}-{str(annot.get('id') or 'annotation')}"
            prepared_annotations.append(annot)
            page_num = int(annot.get("page", 1))
            if page_num < 1 or page_num > len(writer.pages):
                logger.warning(f"[PdfAnnotator] 无效页码 {page_num}，跳过")
                continue
            page = writer.pages[page_num - 1]
            annot_obj = _build_annot_object(annot, page, writer)
            if annot_obj is None:
                continue
            if "/Annots" not in page:
                page[NameObject("/Annots")] = ArrayObject()
            page["/Annots"].append(writer._add_object(annot_obj))  # type: ignore[attr-defined]

    out = BytesIO()
    writer.write(out)
    raw_output = out.getvalue()
    return _ensure_annotation_appearances(raw_output, prepared_annotations)


def _ensure_annotation_appearances(pdf_bytes: bytes, annotations: list[dict]) -> bytes:
    """Generate portable appearance streams for annotations written by pypdf.

    Chromium, Poppler and Acrobat do not consistently synthesize appearances
    for hand-built FreeText annotations. Without an /AP stream, a text box can
    render as a solid colour block or appear empty even though /Contents exists.
    PyMuPDF reliably creates the appearance while preserving the PDF location.
    """
    try:
        import pymupdf as fitz  # type: ignore
    except ImportError:
        return pdf_bytes

    source_by_id = {
        str(annotation.get("_koto_id") or ""): annotation for annotation in annotations
    }
    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page in document:
            for annotation in list(page.annots() or []):
                annotation_id = str((annotation.info or {}).get("id", "") or "")
                source = source_by_id.get(annotation_id)
                if source is None:
                    continue
                if source.get("type") == "textbox":
                    rect = fitz.Rect(annotation.rect)
                    text = str(source.get("text") or source.get("content") or "")
                    fontsize = float(source.get("fontSize", 14) or 14)
                    page_height = float(
                        source.get("pageHeight")
                        or source.get("page_height")
                        or page.rect.height
                    )
                    fontsize *= float(page.rect.height) / max(page_height, 1.0)
                    rgb = _hex_to_pdf_color(str(source.get("color", "#000000")))
                    page.delete_annot(annotation)
                    flattened = any(ord(char) > 255 for char in text)
                    if flattened:
                        flattened = _insert_complex_textbox_image(
                            page, rect, text, max(1.0, fontsize), rgb
                        )
                    replacement = page.add_freetext_annot(
                        rect,
                        "" if flattened else text,
                        fontsize=max(1.0, fontsize),
                        fontname="helv",
                        text_color=tuple(rgb),
                        fill_color=None,
                        border_color=None,
                    )
                    replacement.update()
                    if flattened:
                        replacement.set_info(
                            content=text,
                            subject="KotoFlattenedTextBox",
                        )
                    safe_id = "".join(
                        char for char in annotation_id if char.isalnum() or char in "-_"
                    )
                    if safe_id:
                        document.xref_set_key(replacement.xref, "NM", f"({safe_id})")
                else:
                    # Shape, ink and markup annotations also benefit from an
                    # explicit appearance when opened outside Koto.
                    annotation.update()
        output = BytesIO()
        document.save(output, garbage=4, deflate=True)
        document.close()
        return output.getvalue()
    except Exception:
        logger.warning(
            "[PdfAnnotator] Failed to generate annotation appearances; "
            "returning structurally valid annotations",
            exc_info=True,
        )
        return pdf_bytes


def _insert_complex_textbox_image(
    page: Any,
    rect: Any,
    text: str,
    fontsize: float,
    rgb: list[float],
) -> bool:
    """Flatten non-Latin textbox text with an embedded glyph-capable font.

    PDF FreeText appearances are restricted to the standard 14 fonts in many
    viewers, which turns CJK text into question marks. A transparent text image
    preserves the visible edit while a metadata-only FreeText annotation keeps
    the original Unicode content available to Koto when the PDF is reopened.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except ImportError:
        return False

    font_candidates = (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    )
    font_path = next(
        (candidate for candidate in font_candidates if candidate.exists()), None
    )
    if font_path is None:
        return False

    scale = 2
    width = max(2, int(float(rect.width) * scale))
    height = max(2, int(float(rect.height) * scale))
    font = ImageFont.truetype(str(font_path), max(8, int(fontsize * scale)))
    image = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    max_width = max(1, width - 4 * scale)
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        current = ""
        for char in paragraph:
            candidate = current + char
            bbox = draw.textbbox((0, 0), candidate, font=font)
            if current and bbox[2] - bbox[0] > max_width:
                lines.append(current)
                current = char
            else:
                current = candidate
        lines.append(current)
    color = tuple(max(0, min(255, round(value * 255))) for value in rgb) + (255,)
    draw.multiline_text(
        (2 * scale, 0),
        "\n".join(lines),
        font=font,
        fill=color,
        spacing=max(1, int(fontsize * 0.2 * scale)),
    )
    png = BytesIO()
    image.save(png, format="PNG")
    page.insert_image(rect, stream=png.getvalue(), overlay=True, keep_proportion=False)
    return True


def read_annotations(pdf_path: str) -> list[dict]:
    """
    Read annotations embedded in *pdf_path* and return them as a list of dicts
    compatible with the KotoPdfViewer annotation format.
    """
    result: list[dict] = []
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        logger.warning("[PdfAnnotator] pypdf not installed — cannot read annotations")
        return result

    try:
        with open(pdf_path, "rb") as fh:
            reader = PdfReader(fh)
            for page_num, page in enumerate(reader.pages, start=1):
                annots = page.get("/Annots")
                if not annots:
                    continue
                for annot_ref in annots:
                    try:
                        annot = (
                            annot_ref.get_object()
                            if hasattr(annot_ref, "get_object")
                            else annot_ref
                        )
                        parsed = _parse_annot_object(annot, page_num)
                        if parsed:
                            result.append(parsed)
                    except Exception as e:
                        logger.debug(f"[PdfAnnotator] 解析批注失败: {e}")
    except Exception as e:
        logger.error(f"[PdfAnnotator] 读取 PDF 失败: {e}")
    return result


def apply_page_ops(pdf_path: str, pages: list[dict]) -> bytes:
    """
    Reconstruct a PDF from *pdf_path* using the given page specification.

    *pages* is an ordered list of dicts (from the Page Manager):
        [{"orig_page": int, "rotation": int}, ...]

    - Pages are included in the requested order.
    - Pages not listed are excluded (delete support).
    - Rotation of 90 / 180 / 270 is applied to each page.

    Returns the bytes of the new PDF.
    """
    try:
        from pypdf import PdfReader, PdfWriter  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pypdf is required for page operations") from exc

    with open(pdf_path, "rb") as fh:
        reader = PdfReader(fh)
        total = len(reader.pages)
        writer = PdfWriter()

        for index, spec in enumerate(pages):
            if not isinstance(spec, dict):
                raise ValueError(f"第 {index + 1} 个页面操作必须是对象")
            try:
                orig = int(spec.get("orig_page", 0))
                rotation = int(spec.get("rotation", 0)) % 360
            except (TypeError, ValueError) as exc:
                raise ValueError(f"第 {index + 1} 个页面操作参数无效") from exc
            if orig < 1 or orig > total:
                raise ValueError(f"页码 {orig} 超出有效范围 1-{total}")
            if rotation not in (0, 90, 180, 270):
                raise ValueError(f"第 {index + 1} 个页面旋转角度必须为 0/90/180/270")
            page = reader.pages[orig - 1]
            if rotation:
                # pypdf page.rotate() takes clockwise degrees (90, 180, 270)
                page = page.rotate(rotation)
            writer.add_page(page)

        if not writer.pages:
            raise ValueError("页面操作不能生成空 PDF")

    out = BytesIO()
    writer.write(out)
    return out.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# Format conversion
# ─────────────────────────────────────────────────────────────────────────────


def pdf_to_docx(pdf_path: str) -> tuple[bytes, str]:
    """
    Convert PDF to an editable DOCX while retaining page boundaries, basic text
    styling, alignment, and embedded images. Scanned pages fall back to a page
    image instead of failing with an empty document.
    """
    try:
        import pymupdf as fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for PDF→DOCX conversion") from exc
    try:
        from docx import Document  # type: ignore
        from docx.enum.text import WD_ALIGN_PARAGRAPH  # type: ignore
        from docx.shared import Inches, Pt, RGBColor  # type: ignore
    except ImportError as exc:
        raise RuntimeError("python-docx is required for PDF→DOCX conversion") from exc

    document = Document()
    section = document.sections[0]
    section.top_margin = Pt(36)
    section.bottom_margin = Pt(36)
    section.left_margin = Pt(36)
    section.right_margin = Pt(36)
    image_fallback_pages = 0

    with fitz.open(pdf_path) as pdf:
        if len(pdf):
            first_rect = pdf[0].rect
            section.page_width = Pt(float(first_rect.width))
            section.page_height = Pt(float(first_rect.height))

        for page_index, page in enumerate(pdf):
            blocks = sorted(
                page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE).get(
                    "blocks", []
                ),
                key=lambda block: (
                    round(float(block.get("bbox", (0, 0, 0, 0))[1]), 1),
                    float(block.get("bbox", (0, 0, 0, 0))[0]),
                ),
            )
            emitted = False
            for block in blocks:
                block_type = block.get("type")
                if block_type == 0:
                    for line in block.get("lines", []):
                        spans = line.get("spans", [])
                        text = "".join(str(span.get("text", "")) for span in spans)
                        if not text.strip():
                            continue
                        paragraph = document.add_paragraph()
                        bbox = line.get("bbox", block.get("bbox", (0, 0, 0, 0)))
                        page_width = max(float(page.rect.width), 1.0)
                        left_gap = float(bbox[0])
                        right_gap = page_width - float(bbox[2])
                        if abs(left_gap - right_gap) < page_width * 0.06:
                            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        elif left_gap > page_width * 0.55:
                            paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                        else:
                            paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
                        for span in spans:
                            value = str(span.get("text", ""))
                            if not value:
                                continue
                            run = paragraph.add_run(value)
                            font_name = str(span.get("font", ""))
                            run.bold = "bold" in font_name.lower()
                            run.italic = any(
                                token in font_name.lower()
                                for token in ("italic", "oblique")
                            )
                            size = float(span.get("size", 0) or 0)
                            if size:
                                run.font.size = Pt(max(1.0, min(size, 200.0)))
                            if font_name:
                                run.font.name = font_name
                            color = int(span.get("color", 0) or 0)
                            run.font.color.rgb = RGBColor(
                                (color >> 16) & 0xFF,
                                (color >> 8) & 0xFF,
                                color & 0xFF,
                            )
                        emitted = True
                elif block_type == 1 and block.get("image"):
                    try:
                        available_width = max(
                            float(
                                section.page_width
                                - section.left_margin
                                - section.right_margin
                            ),
                            1,
                        )
                        document.add_picture(
                            BytesIO(block["image"]),
                            width=Inches(min(available_width / 914400.0, 7.5)),
                        )
                        emitted = True
                    except Exception:
                        logger.debug("Could not embed PDF image block", exc_info=True)

            if not emitted:
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                available_width = max(
                    float(
                        section.page_width - section.left_margin - section.right_margin
                    ),
                    1,
                )
                document.add_picture(
                    BytesIO(pix.tobytes("png")),
                    width=Inches(min(available_width / 914400.0, 7.5)),
                )
                image_fallback_pages += 1
            if page_index < len(pdf) - 1:
                document.add_page_break()

    output = BytesIO()
    document.save(output)
    warning = ""
    if image_fallback_pages:
        warning = f"{image_fallback_pages} 页未检测到可编辑文字，已按页面图像保留。"
    return output.getvalue(), warning


def pdf_to_xlsx_with_report(pdf_path: str) -> tuple[bytes, str]:
    """
    Extract tables from PDF pages and write to XLSX.
    Falls back to plain text rows when no tables are detected.
    Requires pdfplumber and openpyxl.
    """
    try:
        import pdfplumber  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pdfplumber is required for PDF→XLSX conversion") from exc
    try:
        from openpyxl import Workbook  # type: ignore
    except ImportError as exc:
        raise RuntimeError("openpyxl is required for PDF→XLSX conversion") from exc

    from openpyxl.styles import Alignment, Font, PatternFill  # type: ignore
    from openpyxl.utils import get_column_letter  # type: ignore

    wb = Workbook()
    wb.remove(wb.active)
    extracted_units = 0

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            ws = wb.create_sheet(title=f"第{page_num}页")
            current_row = 1
            tables = page.extract_tables() or []
            if tables:
                for table_index, table in enumerate(tables, start=1):
                    if len(tables) > 1:
                        ws.cell(current_row, 1, f"表格 {table_index}").font = Font(
                            bold=True
                        )
                        current_row += 1
                    for row_index, row in enumerate(table):
                        extracted_units += sum(
                            1 for value in (row or []) if str(value or "").strip()
                        )
                        for col_index, value in enumerate(row or [], start=1):
                            cell = ws.cell(
                                current_row,
                                col_index,
                                "" if value is None else str(value),
                            )
                            cell.alignment = Alignment(
                                horizontal="center" if row_index == 0 else "left",
                                vertical="top",
                                wrap_text=True,
                            )
                            if row_index == 0:
                                cell.font = Font(bold=True)
                                cell.fill = PatternFill("solid", fgColor="E8EEF7")
                        current_row += 1
                    current_row += 1
            else:
                text = page.extract_text() or ""
                if text.strip():
                    for line_number, line in enumerate(text.splitlines(), start=1):
                        if line.strip():
                            extracted_units += 1
                        ws.cell(current_row, 1, line_number)
                        content_cell = ws.cell(current_row, 2, line)
                        content_cell.alignment = Alignment(
                            horizontal="left", vertical="top", wrap_text=True
                        )
                        current_row += 1
                    ws.column_dimensions["A"].width = 8

            for column in range(1, ws.max_column + 1):
                max_length = max(
                    (
                        len(str(ws.cell(row, column).value or ""))
                        for row in range(1, ws.max_row + 1)
                    ),
                    default=0,
                )
                ws.column_dimensions[get_column_letter(column)].width = min(
                    max(max_length + 2, 8), 60
                )
            ws.freeze_panes = "A2" if ws.max_row > 1 else None

    warning = ""
    if not wb.worksheets:
        wb.create_sheet("内容")
    if extracted_units == 0:
        warning = "未检测到可转换的表格或文本；扫描型页面无法直接生成可编辑单元格。"
        first_sheet = wb.worksheets[0]
        first_sheet.cell(1, 1, warning)
        first_sheet.column_dimensions["A"].width = 72

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue(), warning


def pdf_to_xlsx(pdf_path: str) -> bytes:
    """Backward-compatible byte-only PDF→XLSX conversion."""
    return pdf_to_xlsx_with_report(pdf_path)[0]


def pdf_to_pptx(pdf_path: str) -> bytes:
    """
    Convert each PDF page to a full-page image slide in PPTX.
    Requires PyMuPDF (fitz) and python-pptx.
    """
    try:
        import pymupdf as fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for PDF→PPTX conversion") from exc
    try:
        from pptx import Presentation  # type: ignore
        from pptx.dml.color import RGBColor  # type: ignore
        from pptx.util import Inches  # type: ignore
    except ImportError as exc:
        raise RuntimeError("python-pptx is required for PDF→PPTX conversion") from exc

    prs = Presentation()
    blank_layout = prs.slide_layouts[6]

    with fitz.open(pdf_path) as doc:
        if len(doc):
            first = doc[0].rect
            ratio = max(float(first.width), 1.0) / max(float(first.height), 1.0)
            if ratio >= 1:
                prs.slide_width = Inches(13.333)
                prs.slide_height = Inches(13.333 / ratio)
            else:
                prs.slide_height = Inches(13.333)
                prs.slide_width = Inches(13.333 * ratio)

        for page_obj in doc:
            pix = page_obj.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
            img_bytes = pix.tobytes("png")
            slide = prs.slides.add_slide(blank_layout)
            page_ratio = max(float(page_obj.rect.width), 1.0) / max(
                float(page_obj.rect.height), 1.0
            )
            slide_ratio = float(prs.slide_width) / max(float(prs.slide_height), 1.0)
            if page_ratio >= slide_ratio:
                width = prs.slide_width
                height = int(width / page_ratio)
                left, top = 0, int((prs.slide_height - height) / 2)
            else:
                height = prs.slide_height
                width = int(height * page_ratio)
                left, top = int((prs.slide_width - width) / 2), 0
            slide.background.fill.solid()
            slide.background.fill.fore_color.rgb = RGBColor(255, 255, 255)
            slide.shapes.add_picture(BytesIO(img_bytes), left, top, width, height)

    buf = BytesIO()
    prs.save(buf)
    return buf.getvalue()


def remove_watermark(
    pdf_path: str, use_ai: bool = True, api_key: str | None = None
) -> tuple[bytes, int, str]:
    """
    Attempt to remove watermarks from a PDF.

    Deterministic local strategies:
      1. remove PDF watermark annotations;
      2. redact repeated, light, large, diagonal, or keyword-matched text;
      3. remove repeated central image XObjects used as image watermarks.

    ``use_ai`` and ``api_key`` remain as compatibility parameters only. The
    implementation intentionally does not send document content to a cloud API.

    Returns (pdf_bytes, n_regions_removed, method_used).
    """
    try:
        import pymupdf as fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for watermark removal") from exc

    import re

    source_bytes = Path(pdf_path).read_bytes()
    doc = fitz.open(stream=source_bytes, filetype="pdf")
    page_count = len(doc)
    removed = 0

    if page_count == 0:
        data = doc.tobytes()
        doc.close()
        return data, 0, "none"

    WATERMARK_KEYWORDS = [
        "confidential",
        "机密",
        "draft",
        "草稿",
        "internal",
        "内部",
        "sample",
        "watermark",
        "水印",
        "copyright",
        "版权",
        "do not copy",
        "禁止复制",
        "仅供内部",
        "for internal use",
    ]

    def _normalized_text(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip().casefold()

    # ── Strategy 1: explicit watermark annotations ───────────────────────────
    for page in doc:
        annotations = list(page.annots() or [])
        for annotation in annotations:
            type_name = str((annotation.type or (None, ""))[1] or "").casefold()
            content = _normalized_text((annotation.info or {}).get("content", ""))
            if "watermark" in type_name or "水印" in content:
                page.delete_annot(annotation)
                removed += 1

    # ── Strategy 2: structural text detection ────────────────────────────────
    sample_pages = min(20, page_count)
    candidate_map: dict[str, dict[str, Any]] = {}

    for pg_idx in range(sample_pages):
        page = doc[pg_idx]
        try:
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)[
                "blocks"
            ]
        except Exception:
            continue
        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                direction = line.get("dir", (1.0, 0.0))
                is_diagonal = abs(float(direction[1] or 0.0)) > 0.15
                for span in line.get("spans", []):
                    txt = span.get("text", "").strip()
                    if not txt:
                        continue
                    # Light colour ≈ watermark
                    c = span.get("color", 0)
                    r_ch = (c >> 16) & 0xFF
                    g_ch = (c >> 8) & 0xFF
                    b_ch = c & 0xFF
                    alpha = int(span.get("alpha", 255) or 255)
                    font_size = float(span.get("size", 0) or 0)
                    is_light = r_ch > 170 and g_ch > 170 and b_ch > 170
                    span_bbox = fitz.Rect(span.get("bbox", (0, 0, 0, 0)))
                    span_center = (
                        (span_bbox.x0 + span_bbox.x1) / 2.0,
                        (span_bbox.y0 + span_bbox.y1) / 2.0,
                    )
                    is_central = (
                        page.rect.width * 0.15
                        <= span_center[0]
                        <= page.rect.width * 0.85
                        and page.rect.height * 0.15
                        <= span_center[1]
                        <= page.rect.height * 0.85
                    )
                    txt_lower = _normalized_text(txt)
                    is_keyword = any(kw in txt_lower for kw in WATERMARK_KEYWORDS)
                    is_strong_single_page_signal = (
                        is_diagonal and font_size >= 18
                    ) or (is_light and is_central and font_size >= 24)
                    looks_like_watermark = (
                        is_keyword
                        or (is_light and (font_size >= 14 or alpha < 220))
                        or (is_diagonal and font_size >= 18)
                    )
                    if looks_like_watermark:
                        key = txt_lower[:120]
                        entry = candidate_map.setdefault(
                            key,
                            {
                                "text": txt,
                                "pages": set(),
                                "keyword": False,
                                "strong": False,
                            },
                        )
                        entry["pages"].add(pg_idx)
                        entry["keyword"] = bool(entry["keyword"] or is_keyword)
                        entry["strong"] = bool(
                            entry["strong"] or is_strong_single_page_signal
                        )

    threshold = 1 if sample_pages == 1 else max(2, (sample_pages + 1) // 2)
    watermark_texts = {
        value["text"]
        for value in candidate_map.values()
        if len(value["pages"]) >= threshold
        or (sample_pages == 1 and (value["keyword"] or value["strong"]))
    }

    if watermark_texts:
        for pg_idx in range(page_count):
            page = doc[pg_idx]
            areas: list = []
            for wt in watermark_texts:
                areas.extend(page.search_for(wt, quads=False))
            for area in areas:
                page.add_redact_annot(area, fill=(1, 1, 1))
            if areas:
                try:
                    page.apply_redactions(images=0, graphics=0)
                except TypeError:
                    page.apply_redactions()
                removed += len(areas)

    # ── Strategy 3: repeated central image XObjects ──────────────────────────
    image_candidates: dict[int, dict[str, Any]] = {}
    for pg_idx in range(sample_pages):
        page = doc[pg_idx]
        page_area = max(float(page.rect.width * page.rect.height), 1.0)
        for info in page.get_image_info(xrefs=True):
            xref = int(info.get("xref", 0) or 0)
            bbox = fitz.Rect(info.get("bbox", (0, 0, 0, 0)))
            ratio = float(bbox.get_area()) / page_area
            center = (bbox.x0 + bbox.x1) / 2.0, (bbox.y0 + bbox.y1) / 2.0
            is_central = (
                page.rect.width * 0.2 <= center[0] <= page.rect.width * 0.8
                and page.rect.height * 0.2 <= center[1] <= page.rect.height * 0.8
            )
            if xref > 0 and is_central and 0.05 <= ratio <= 0.8:
                entry = image_candidates.setdefault(xref, {"pages": set(), "count": 0})
                entry["pages"].add(pg_idx)
                entry["count"] += 1

    image_threshold = 1 if sample_pages == 1 else max(2, (sample_pages + 1) // 2)
    for xref, candidate in image_candidates.items():
        # For a single-page document, only remove an image with a soft mask;
        # otherwise a central photo would be indistinguishable from a watermark.
        has_soft_mask = any(
            image[0] == xref and int(image[1] or 0) > 0
            for page in doc
            for image in page.get_images(full=True)
        )
        if len(candidate["pages"]) < image_threshold:
            continue
        if sample_pages == 1 and not has_soft_mask:
            continue
        try:
            for page in doc:
                page.delete_image(xref)
            removed += int(candidate["count"])
        except Exception:
            logger.debug(
                "Could not remove repeated PDF image xref=%s", xref, exc_info=True
            )

    if removed == 0:
        doc.close()
        return source_bytes, 0, "none"

    buf = BytesIO()
    doc.save(buf, garbage=4, deflate=True)
    doc.close()
    return buf.getvalue(), removed, "structural" if removed else "none"


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

_SUBTYPE_MAP = {
    "highlight": "/Highlight",
    "underline": "/Underline",
    "strikethrough": "/StrikeOut",
    "note": "/Text",
    "draw": "/Ink",
    "rect": "/Square",
    "ellipse": "/Circle",
    "line": "/Line",
    "arrow": "/Line",
    "textbox": "/FreeText",
}

_SUBTYPE_REVERSE: dict[str, str] = {v: k for k, v in _SUBTYPE_MAP.items()}


def _hex_to_pdf_color(hex_color: str) -> list[float]:
    """Convert '#RRGGBB' to [r, g, b] in [0.0, 1.0] range."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return [1.0, 1.0, 0.0]  # yellow fallback
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return [r, g, b]


def _pdf_color_to_hex(color_array: Any) -> str:
    """Convert a PDF color array to '#RRGGBB'."""
    try:
        vals = [float(v) for v in color_array]
        if len(vals) == 3:
            r, g, b = [int(v * 255) for v in vals]
            return "#{:02X}{:02X}{:02X}".format(r, g, b)
    except Exception:
        pass
    return "#FFFF00"


def _page_dimensions(page: Any) -> tuple[float, float]:
    """Return page width/height in PDF points."""
    try:
        box = page.mediabox
        return float(box.width), float(box.height)
    except Exception:
        return 612.0, 792.0


def _page_rotation(page: Any) -> int:
    """Return the effective clockwise page rotation in quarter turns."""
    try:
        return int(page.get("/Rotate", 0) or 0) % 360
    except Exception:
        return 0


def _frontend_point_to_pdf(
    x: Any, y: Any, annot: dict, page: Any
) -> tuple[float, float] | None:
    """Convert one top-left CSS point to unrotated PDF user-space points."""
    try:
        css_x = float(x)
        css_y = float(y)
    except Exception:
        return None

    pdf_w, pdf_h = _page_dimensions(page)
    rotation = _page_rotation(page)
    view_w, view_h = (pdf_h, pdf_w) if rotation in (90, 270) else (pdf_w, pdf_h)
    css_w = float(annot.get("pageWidth") or annot.get("page_width") or view_w)
    css_h = float(annot.get("pageHeight") or annot.get("page_height") or view_h)
    if css_w <= 0 or css_h <= 0:
        return None
    screen_x = css_x * view_w / css_w
    screen_y = css_y * view_h / css_h

    if rotation == 90:
        return screen_y, screen_x
    if rotation == 180:
        return pdf_w - screen_x, screen_y
    if rotation == 270:
        return pdf_w - screen_y, pdf_h - screen_x
    return screen_x, pdf_h - screen_y


def _frontend_box_to_pdf(
    x: Any, y: Any, width: Any, height: Any, annot: dict, page: Any
) -> list[float] | None:
    """Convert a CSS box to a normalized PDF rectangle."""
    try:
        css_x = float(x)
        css_y = float(y)
        css_w = float(width)
        css_h = float(height)
    except Exception:
        return None
    if css_w <= 0 or css_h <= 0:
        return None
    corners = [
        _frontend_point_to_pdf(px, py, annot, page)
        for px, py in (
            (css_x, css_y),
            (css_x + css_w, css_y),
            (css_x, css_y + css_h),
            (css_x + css_w, css_y + css_h),
        )
    ]
    if any(point is None for point in corners):
        return None
    xs = [point[0] for point in corners if point is not None]
    ys = [point[1] for point in corners if point is not None]
    return [min(xs), min(ys), max(xs), max(ys)]


def _frontend_rect_to_pdf(rect: Any, annot: dict, page: Any) -> list[float] | None:
    """Convert a frontend top-left CSS rect to a PDF bottom-left point rect."""
    if isinstance(rect, dict):
        try:
            x = float(rect.get("x", 0))
            y = float(rect.get("y", 0))
            w = float(rect.get("w", rect.get("width", 0)))
            h = float(rect.get("h", rect.get("height", 0)))
        except Exception:
            return None
        if w <= 0 or h <= 0:
            return None
        return _frontend_box_to_pdf(x, y, w, h, annot, page)
    if isinstance(rect, (list, tuple)) and len(rect) >= 4:
        try:
            return [float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])]
        except Exception:
            return None
    return None


def _normalize_annotation_rects(annot: dict, page: Any) -> list[list[float]]:
    """Normalize supported frontend/PDF rect formats to PDF point rectangles."""
    rects = annot.get("rects", [])
    if not isinstance(rects, list):
        return []
    normalized: list[list[float]] = []
    for rect in rects:
        converted = _frontend_rect_to_pdf(rect, annot, page)
        if converted is not None:
            normalized.append(converted)
    return normalized


def _build_annot_object(annot: dict, page: Any, writer: Any) -> Any | None:
    """Build a pypdf DictionaryObject for the given annotation dict."""
    try:
        from pypdf.generic import (  # type: ignore
            ArrayObject,
            DictionaryObject,
            FloatObject,
            NameObject,
            NumberObject,
            RectangleObject,
            TextStringObject,
        )
    except ImportError:
        return None

    annot_type = annot.get("type", "highlight")
    subtype = _SUBTYPE_MAP.get(annot_type)
    if not subtype:
        logger.warning(f"[PdfAnnotator] 未知批注类型: {annot_type}")
        return None

    color_vals = _hex_to_pdf_color(annot.get("color", "#FFFF00"))
    pdf_color = ArrayObject([FloatObject(v) for v in color_vals])

    # Bounding rect (union of all rects, or first rect)
    rects: list = _normalize_annotation_rects(annot, page)
    if rects:
        all_x1 = [r[0] for r in rects]
        all_y1 = [r[1] for r in rects]
        all_x2 = [r[2] for r in rects]
        all_y2 = [r[3] for r in rects]
        bbox = [min(all_x1), min(all_y1), max(all_x2), max(all_y2)]
    else:
        bbox = [0, 0, 100, 20]

    obj = DictionaryObject()
    obj[NameObject("/Type")] = NameObject("/Annot")
    obj[NameObject("/Subtype")] = NameObject(subtype)
    obj[NameObject("/Rect")] = ArrayObject([FloatObject(v) for v in bbox])
    obj[NameObject("/C")] = pdf_color
    obj[NameObject("/F")] = NumberObject(4)  # Print flag
    if annot.get("_koto_id"):
        obj[NameObject("/NM")] = TextStringObject(str(annot["_koto_id"]))

    if annot.get("content"):
        obj[NameObject("/Contents")] = TextStringObject(annot["content"])

    # QuadPoints for highlight / underline / strikethrough
    if annot_type in ("highlight", "underline", "strikethrough") and rects:
        quad_points: list[float] = []
        for r in rects:
            x1, y1, x2, y2 = r[0], r[1], r[2], r[3]
            # PDF text-markup order: top-left, top-right, bottom-left,
            # bottom-right. Reversing the vertical pairs makes highlights
            # disappear or render as a bow-tie in stricter PDF viewers.
            quad_points += [x1, y2, x2, y2, x1, y1, x2, y1]
        obj[NameObject("/QuadPoints")] = ArrayObject(
            [FloatObject(v) for v in quad_points]
        )

    # InkList for draw annotations
    if annot_type == "draw":
        ink_list_raw: list = annot.get("inkList", [])
        if not ink_list_raw and isinstance(annot.get("points"), list):
            ink_list_raw = [annot["points"]]
        ink_array = ArrayObject()
        ink_points: list[tuple[float, float]] = []
        for stroke in ink_list_raw:
            stroke_pts: list[float] = []
            for pt in stroke:
                if isinstance(pt, dict):
                    converted = _frontend_point_to_pdf(
                        pt.get("x", 0), pt.get("y", 0), annot, page
                    )
                elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    converted = _frontend_point_to_pdf(pt[0], pt[1], annot, page)
                else:
                    converted = None
                if converted is not None:
                    ink_points.append(converted)
                    stroke_pts += [converted[0], converted[1]]
            if len(stroke_pts) >= 4:
                ink_array.append(ArrayObject([FloatObject(v) for v in stroke_pts]))
        obj[NameObject("/InkList")] = ink_array
        if ink_points:
            padding = max(float(annot.get("lineWidth", 2) or 2), 1.0)
            xs = [point[0] for point in ink_points]
            ys = [point[1] for point in ink_points]
            obj[NameObject("/Rect")] = ArrayObject(
                [
                    FloatObject(min(xs) - padding),
                    FloatObject(min(ys) - padding),
                    FloatObject(max(xs) + padding),
                    FloatObject(max(ys) + padding),
                ]
            )

    # Shape annotations: override /Rect and add shape-specific keys
    if annot_type == "rect":
        x, y, w, h = (
            annot.get("x", 0),
            annot.get("y", 0),
            annot.get("w", 50),
            annot.get("h", 30),
        )
        shape_rect = _frontend_box_to_pdf(x, y, w, h, annot, page)
        if shape_rect:
            obj[NameObject("/Rect")] = ArrayObject(
                [FloatObject(value) for value in shape_rect]
            )
    elif annot_type == "ellipse":
        cx, cy = annot.get("cx", 0), annot.get("cy", 0)
        rx, ry = annot.get("rx", 25), annot.get("ry", 15)
        shape_rect = _frontend_box_to_pdf(
            float(cx) - float(rx),
            float(cy) - float(ry),
            float(rx) * 2,
            float(ry) * 2,
            annot,
            page,
        )
        if shape_rect:
            obj[NameObject("/Rect")] = ArrayObject(
                [FloatObject(value) for value in shape_rect]
            )
    elif annot_type in ("line", "arrow"):
        x1, y1 = annot.get("x1", 0), annot.get("y1", 0)
        x2, y2 = annot.get("x2", 100), annot.get("y2", 0)
        point1 = _frontend_point_to_pdf(x1, y1, annot, page)
        point2 = _frontend_point_to_pdf(x2, y2, annot, page)
        if point1 and point2:
            pdf_x1, pdf_y1 = point1
            pdf_x2, pdf_y2 = point2
            padding = max(float(annot.get("lineWidth", 2) or 2), 1.0)
            obj[NameObject("/Rect")] = ArrayObject(
                [
                    FloatObject(min(pdf_x1, pdf_x2) - padding),
                    FloatObject(min(pdf_y1, pdf_y2) - padding),
                    FloatObject(max(pdf_x1, pdf_x2) + padding),
                    FloatObject(max(pdf_y1, pdf_y2) + padding),
                ]
            )
            obj[NameObject("/L")] = ArrayObject(
                [
                    FloatObject(pdf_x1),
                    FloatObject(pdf_y1),
                    FloatObject(pdf_x2),
                    FloatObject(pdf_y2),
                ]
            )
        if annot_type == "arrow":
            obj[NameObject("/LE")] = ArrayObject(
                [NameObject("/None"), NameObject("/OpenArrow")]
            )
    elif annot_type == "textbox":
        x, y, w, h = (
            annot.get("x", 0),
            annot.get("y", 0),
            annot.get("w", 120),
            annot.get("h", 30),
        )
        text_rect = _frontend_box_to_pdf(x, y, w, h, annot, page)
        if text_rect:
            obj[NameObject("/Rect")] = ArrayObject(
                [FloatObject(value) for value in text_rect]
            )
        text = annot.get("text", "")
        if text:
            obj[NameObject("/Contents")] = TextStringObject(text)
        pdf_w, pdf_h = _page_dimensions(page)
        rotation = _page_rotation(page)
        view_h = pdf_w if rotation in (90, 270) else pdf_h
        css_h = float(annot.get("pageHeight") or annot.get("page_height") or view_h)
        font_size = float(annot.get("fontSize", 14) or 14) * view_h / max(css_h, 1.0)
        r, g, b = color_vals
        obj[NameObject("/DA")] = TextStringObject(
            f"/Helvetica {font_size} Tf {r:.2f} {g:.2f} {b:.2f} rg"
        )
    elif annot_type == "note":
        x, y = annot.get("x", 0), annot.get("y", 0)
        note_rect = _frontend_box_to_pdf(x, y, 24, 24, annot, page)
        if note_rect:
            obj[NameObject("/Rect")] = ArrayObject(
                [FloatObject(value) for value in note_rect]
            )
        note_text = annot.get("text") or annot.get("content") or ""
        if note_text:
            obj[NameObject("/Contents")] = TextStringObject(str(note_text))
        obj[NameObject("/Name")] = NameObject("/Comment")

    # Border style (line width) for shape and draw annotations
    if annot_type in ("rect", "ellipse", "line", "arrow", "draw"):
        lw = float(annot.get("lineWidth", 2))
        obj[NameObject("/BS")] = DictionaryObject(
            {
                NameObject("/W"): FloatObject(lw),
                NameObject("/S"): NameObject("/S"),
            }
        )

    return obj


def _parse_annot_object(annot: Any, page_num: int) -> dict | None:
    """Convert a pypdf annotation DictionaryObject back to a frontend-compatible dict."""
    try:
        subtype = str(annot.get("/Subtype", ""))
        annot_type = _SUBTYPE_REVERSE.get(subtype)
        if subtype == "/Line":
            line_endings = [str(value) for value in (annot.get("/LE") or [])]
            annot_type = (
                "arrow"
                if any(value not in ("/None", "None") for value in line_endings)
                else "line"
            )
        if not annot_type:
            return None

        rect_raw = annot.get("/Rect")
        rect = [float(v) for v in rect_raw] if rect_raw else [0, 0, 0, 0]

        color_raw = annot.get("/C")
        color = _pdf_color_to_hex(color_raw) if color_raw else "#FFFF00"
        content = str(annot.get("/Contents", "") or "")
        subject = str(annot.get("/Subj", "") or "")
        default_appearance = str(annot.get("/DA", "") or "")
        if not color_raw and default_appearance:
            import re

            color_match = re.search(
                r"([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+rg",
                default_appearance,
            )
            if color_match:
                color = _pdf_color_to_hex(
                    [float(value) for value in color_match.groups()]
                )

        result: dict[str, Any] = {
            "id": f"pdf-{page_num}-{int(rect[0])}-{int(rect[1])}",
            "type": annot_type,
            "page": page_num,
            "color": color,
            "content": content,
            "text": content,
            "coordinateSpace": "pdf",
            "flattened": subject == "KotoFlattenedTextBox",
            "rects": [rect],
        }
        if default_appearance:
            import re

            font_match = re.search(r"/\S+\s+([0-9.]+)\s+Tf", default_appearance)
            if font_match:
                result["pdfFontSize"] = float(font_match.group(1))

        # Recover individual rects from QuadPoints
        qp_raw = annot.get("/QuadPoints")
        if qp_raw:
            qp = [float(v) for v in qp_raw]
            rects: list[list[float]] = []
            for i in range(0, len(qp), 8):
                if i + 7 < len(qp):
                    xs = [qp[i], qp[i + 2], qp[i + 4], qp[i + 6]]
                    ys = [qp[i + 1], qp[i + 3], qp[i + 5], qp[i + 7]]
                    rects.append([min(xs), min(ys), max(xs), max(ys)])
            if rects:
                result["rects"] = rects

        # Reconstruct ink strokes
        if annot_type == "draw":
            il_raw = annot.get("/InkList")
            if il_raw:
                ink_list: list[list[list[float]]] = []
                for stroke in il_raw:
                    pts = [float(v) for v in stroke]
                    ink_list.append(
                        [[pts[j], pts[j + 1]] for j in range(0, len(pts), 2)]
                    )
                result["inkList"] = ink_list

        if annot_type in ("line", "arrow"):
            line_raw = annot.get("/L")
            if line_raw and len(line_raw) >= 4:
                result["line"] = [float(value) for value in line_raw[:4]]

        return result
    except Exception as e:
        logger.debug(f"[PdfAnnotator] _parse_annot_object 失败: {e}")
        return None
