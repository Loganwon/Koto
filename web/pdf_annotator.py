"""
pdf_annotator.py — Embed / read PDF annotations, page ops, and format conversion.

Annotation types supported (matching KotoPdfViewer JS):
  highlight, underline, strikethrough, note (free-text), draw (ink)

All coordinates are expressed as **PDF points** from the bottom-left origin
(standard PDF coordinate system).  The frontend converts CSS pixels to PDF
points before calling save_annotations.

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
            ArrayObject, DictionaryObject, FloatObject,
            NameObject, NumberObject, TextStringObject,
        )
    except ImportError as exc:
        raise RuntimeError("pypdf is required for annotation embedding") from exc

    with open(pdf_path, "rb") as fh:
        reader = PdfReader(fh)
        writer = PdfWriter()
        writer.clone_reader_document_root(reader)

        for annot in annotations:
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
    return out.getvalue()


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
                        annot = annot_ref.get_object() if hasattr(annot_ref, "get_object") else annot_ref
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

        for spec in pages:
            orig = int(spec.get("orig_page", 0))
            rotation = int(spec.get("rotation", 0))
            if orig < 1 or orig > total:
                logger.warning(f"[PdfAnnotator] page_ops: 无效页码 {orig}，跳过")
                continue
            page = reader.pages[orig - 1]
            if rotation:
                # pypdf page.rotate() takes clockwise degrees (90, 180, 270)
                page = page.rotate(rotation % 360)
            writer.add_page(page)

    out = BytesIO()
    writer.write(out)
    return out.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# Format conversion
# ─────────────────────────────────────────────────────────────────────────────

def pdf_to_docx(pdf_path: str) -> tuple[bytes, str]:
    """
    Convert PDF to DOCX.  Returns (docx_bytes, warning_message).
    Uses doc_converter which tries LibreOffice first, then pypdf text extraction.
    """
    import tempfile, os, shutil
    from web.doc_converter import convert_to_docx  # type: ignore

    with tempfile.TemporaryDirectory() as tmp:
        out_path, warning = convert_to_docx(pdf_path, output_dir=tmp)
        with open(out_path, "rb") as fh:
            data = fh.read()
    return data, warning


def pdf_to_xlsx(pdf_path: str) -> bytes:
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

    wb = Workbook()
    ws = wb.active
    ws.title = "内容"

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables() or []
            if tables:
                for table in tables:
                    for row in table:
                        ws.append([str(cell or "") for cell in row])
                    ws.append([])  # blank spacer row between tables
            else:
                text = page.extract_text() or ""
                if text.strip():
                    ws.append([f"=== 第 {page_num} 页 ==="])
                    for line in text.splitlines():
                        ws.append([line])
                    ws.append([])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def pdf_to_pptx(pdf_path: str) -> bytes:
    """
    Convert each PDF page to a full-page image slide in PPTX.
    Requires PyMuPDF (fitz) and python-pptx.
    """
    try:
        import fitz  # type: ignore  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for PDF→PPTX conversion") from exc
    try:
        from pptx import Presentation  # type: ignore
        from pptx.util import Inches  # type: ignore
    except ImportError as exc:
        raise RuntimeError("python-pptx is required for PDF→PPTX conversion") from exc

    doc = fitz.open(pdf_path)
    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]  # completely blank layout

    for page_obj in doc:
        mat = fitz.Matrix(2.0, 2.0)  # 2× scale → ~144 DPI
        pix = page_obj.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        slide = prs.slides.add_slide(blank_layout)
        slide.shapes.add_picture(BytesIO(img_bytes), 0, 0, prs.slide_width, prs.slide_height)

    doc.close()
    buf = BytesIO()
    prs.save(buf)
    return buf.getvalue()


def remove_watermark(pdf_path: str, use_ai: bool = True,
                     api_key: str | None = None) -> tuple[bytes, int, str]:
    """
    Attempt to remove watermarks from a PDF.

    Strategy 1: Structural detection — find repeated light-coloured or
    keyword-matched text that appears on multiple pages and redact it.
    Strategy 2: Gemini Vision fallback — if structural detection finds nothing
    and *use_ai* is True and *api_key* is provided, ask Gemini to identify
    watermark text, then redact matching regions.

    Returns (pdf_bytes, n_regions_removed, method_used).
    """
    try:
        import fitz  # PyMuPDF  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for watermark removal") from exc

    import fitz  # noqa: E402 (conditional import above handles missing dep)

    doc = fitz.open(pdf_path)
    page_count = len(doc)
    removed = 0
    method = "structural"

    if page_count == 0:
        return doc.tobytes(), 0, "none"

    WATERMARK_KEYWORDS = [
        "confidential", "机密", "draft", "草稿", "internal", "内部",
        "sample", "watermark", "水印", "copyright", "版权",
        "do not copy", "禁止复制", "仅供内部", "for internal use",
    ]
    # ── Strategy 1: structural detection ─────────────────────────────────────
    sample_pages = min(5, page_count)
    candidate_map: dict[str, dict] = {}

    for pg_idx in range(sample_pages):
        page = doc[pg_idx]
        try:
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        except Exception:
            continue
        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    txt = span.get("text", "").strip()
                    if not txt:
                        continue
                    # Light colour ≈ watermark
                    c = span.get("color", 0)
                    r_ch = (c >> 16) & 0xFF
                    g_ch = (c >> 8) & 0xFF
                    b_ch = c & 0xFF
                    is_light = r_ch > 170 and g_ch > 170 and b_ch > 170
                    txt_lower = txt.lower()
                    is_keyword = any(kw in txt_lower for kw in WATERMARK_KEYWORDS)
                    if is_light or is_keyword:
                        key = txt_lower[:50]
                        if key not in candidate_map:
                            candidate_map[key] = {"text": txt, "pages": []}
                        candidate_map[key]["pages"].append(pg_idx)

    # Text appearing on ≥2 sample pages is a watermark candidate
    threshold = max(2, sample_pages // 2)
    watermark_texts = {
        v["text"] for v in candidate_map.values() if len(v["pages"]) >= threshold
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
                page.apply_redactions()
                removed += len(areas)

    # ── Strategy 2: AI-assisted detection ────────────────────────────────────
    if removed == 0 and use_ai and api_key:
        method = "ai"
        try:
            page = doc[0]
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat)
            import base64
            img_b64 = base64.b64encode(pix.tobytes("png")).decode()

            import google.generativeai as genai  # type: ignore
            import PIL.Image
            import io as _io
            import json
            import re

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.5-flash")
            pil_img = PIL.Image.open(_io.BytesIO(pix.tobytes("png")))
            prompt = (
                "请识别这个PDF页面上的水印内容。水印通常是半透明文字或图案，重复出现在页面上。"
                "请返回JSON格式（只返回JSON，不要其他文字）：\n"
                "{\"has_watermark\": bool, \"watermark_texts\": [\"文字1\"], \"description\": \"描述\"}"
            )
            response = model.generate_content([prompt, pil_img])
            json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if json_match:
                ai_result = json.loads(json_match.group())
                if ai_result.get("has_watermark") and ai_result.get("watermark_texts"):
                    for pg_idx in range(page_count):
                        page = doc[pg_idx]
                        areas = []
                        for wt in ai_result["watermark_texts"]:
                            areas.extend(page.search_for(wt, quads=False))
                        for area in areas:
                            page.add_redact_annot(area, fill=(1, 1, 1))
                        if areas:
                            page.apply_redactions()
                            removed += len(areas)
        except Exception as ai_err:
            logger.warning("[remove_watermark] AI 检测失败: %s", ai_err)
            method = "structural_only"

    buf = BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue(), removed, method


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

_SUBTYPE_MAP = {
    "highlight":     "/Highlight",
    "underline":     "/Underline",
    "strikethrough": "/StrikeOut",
    "note":          "/FreeText",
    "draw":          "/Ink",
    "rect":          "/Square",
    "ellipse":       "/Circle",
    "line":          "/Line",
    "arrow":         "/Line",
    "textbox":       "/FreeText",
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
        pdf_w, pdf_h = _page_dimensions(page)
        css_w = float(annot.get("pageWidth") or annot.get("page_width") or pdf_w)
        css_h = float(annot.get("pageHeight") or annot.get("page_height") or pdf_h)
        sx = pdf_w / css_w if css_w > 0 else 1.0
        sy = pdf_h / css_h if css_h > 0 else 1.0
        x1 = x * sx
        x2 = (x + w) * sx
        y1 = pdf_h - ((y + h) * sy)
        y2 = pdf_h - (y * sy)
        return [x1, y1, x2, y2]
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
            ArrayObject, DictionaryObject, FloatObject, NameObject,
            NumberObject, RectangleObject, TextStringObject,
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

    if annot.get("content"):
        obj[NameObject("/Contents")] = TextStringObject(annot["content"])

    # QuadPoints for highlight / underline / strikethrough
    if annot_type in ("highlight", "underline", "strikethrough") and rects:
        quad_points: list[float] = []
        for r in rects:
            x1, y1, x2, y2 = r[0], r[1], r[2], r[3]
            # PDF QuadPoints order: bottom-left, bottom-right, top-left, top-right
            quad_points += [x1, y1, x2, y1, x1, y2, x2, y2]
        obj[NameObject("/QuadPoints")] = ArrayObject(
            [FloatObject(v) for v in quad_points]
        )

    # InkList for draw annotations
    if annot_type == "draw":
        ink_list_raw: list = annot.get("inkList", [])
        ink_array = ArrayObject()
        for stroke in ink_list_raw:
            stroke_pts: list[float] = []
            for pt in stroke:
                stroke_pts += [float(pt[0]), float(pt[1])]
            ink_array.append(ArrayObject([FloatObject(v) for v in stroke_pts]))
        obj[NameObject("/InkList")] = ink_array

    # Shape annotations: override /Rect and add shape-specific keys
    if annot_type == "rect":
        x, y, w, h = (annot.get("x", 0), annot.get("y", 0),
                      annot.get("w", 50), annot.get("h", 30))
        obj[NameObject("/Rect")] = ArrayObject(
            [FloatObject(x), FloatObject(y), FloatObject(x + w), FloatObject(y + h)])
    elif annot_type == "ellipse":
        cx, cy = annot.get("cx", 0), annot.get("cy", 0)
        rx, ry = annot.get("rx", 25), annot.get("ry", 15)
        obj[NameObject("/Rect")] = ArrayObject(
            [FloatObject(cx - rx), FloatObject(cy - ry), FloatObject(cx + rx), FloatObject(cy + ry)])
    elif annot_type in ("line", "arrow"):
        x1, y1 = annot.get("x1", 0), annot.get("y1", 0)
        x2, y2 = annot.get("x2", 100), annot.get("y2", 0)
        obj[NameObject("/Rect")] = ArrayObject([
            FloatObject(min(x1, x2)), FloatObject(min(y1, y2)),
            FloatObject(max(x1, x2)), FloatObject(max(y1, y2))])
        obj[NameObject("/L")] = ArrayObject(
            [FloatObject(x1), FloatObject(y1), FloatObject(x2), FloatObject(y2)])
        if annot_type == "arrow":
            obj[NameObject("/LE")] = ArrayObject(
                [NameObject("/None"), NameObject("/OpenArrow")])
    elif annot_type == "textbox":
        x, y, w, h = (annot.get("x", 0), annot.get("y", 0),
                      annot.get("w", 120), annot.get("h", 30))
        obj[NameObject("/Rect")] = ArrayObject(
            [FloatObject(x), FloatObject(y), FloatObject(x + w), FloatObject(y + h)])
        text = annot.get("text", "")
        if text:
            obj[NameObject("/Contents")] = TextStringObject(text)
        font_size = annot.get("fontSize", 14)
        r, g, b = color_vals
        obj[NameObject("/DA")] = TextStringObject(f"/Helvetica {font_size} Tf {r:.2f} {g:.2f} {b:.2f} rg")

    # Border style (line width) for shape and draw annotations
    if annot_type in ("rect", "ellipse", "line", "arrow", "draw"):
        lw = float(annot.get("lineWidth", 2))
        obj[NameObject("/BS")] = DictionaryObject({
            NameObject("/W"): FloatObject(lw),
            NameObject("/S"): NameObject("/S"),
        })

    return obj


def _parse_annot_object(annot: Any, page_num: int) -> dict | None:
    """Convert a pypdf annotation DictionaryObject back to a frontend-compatible dict."""
    try:
        subtype = str(annot.get("/Subtype", ""))
        annot_type = _SUBTYPE_REVERSE.get(subtype)
        if not annot_type:
            return None

        rect_raw = annot.get("/Rect")
        rect = [float(v) for v in rect_raw] if rect_raw else [0, 0, 0, 0]

        color_raw = annot.get("/C")
        color = _pdf_color_to_hex(color_raw) if color_raw else "#FFFF00"
        content = str(annot.get("/Contents", "") or "")

        result: dict[str, Any] = {
            "id": f"pdf-{page_num}-{int(rect[0])}-{int(rect[1])}",
            "type": annot_type,
            "page": page_num,
            "color": color,
            "content": content,
            "rects": [rect],
        }

        # Recover individual rects from QuadPoints
        qp_raw = annot.get("/QuadPoints")
        if qp_raw:
            qp = [float(v) for v in qp_raw]
            rects: list[list[float]] = []
            for i in range(0, len(qp), 8):
                if i + 7 < len(qp):
                    xs = [qp[i], qp[i+2], qp[i+4], qp[i+6]]
                    ys = [qp[i+1], qp[i+3], qp[i+5], qp[i+7]]
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
                    ink_list.append([[pts[j], pts[j+1]] for j in range(0, len(pts), 2)])
                result["inkList"] = ink_list

        return result
    except Exception as e:
        logger.debug(f"[PdfAnnotator] _parse_annot_object 失败: {e}")
        return None
