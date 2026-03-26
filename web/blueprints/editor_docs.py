# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""
Editor Document Store API — /api/editor/docs

Lightweight REST API for the Univer Canvas file assistant.
Documents are stored as JSON files under workspace/editor-docs/.

Routes:
  GET    /api/editor/docs              — List all documents
  POST   /api/editor/docs              — Create a new blank document
  GET    /api/editor/docs/<id>         — Get document content
  PUT    /api/editor/docs/<id>         — Save/update document
  PATCH  /api/editor/docs/<id>         — Rename document
  DELETE /api/editor/docs/<id>         — Delete document
  POST   /api/editor/docs/import       — Import a file (docx/pdf/xlsx/pptx/csv/code/txt/md)
  GET    /api/editor/docs/<id>/raw     — Serve original binary (PDF)
"""

from __future__ import annotations

import csv as _csv
import io
import json
import logging
import mimetypes
import os
import re
import time
import uuid
import zipfile

from flask import Blueprint, Response, jsonify, request, send_file

_logger = logging.getLogger("koto.routes.editor_docs")

editor_docs_bp = Blueprint("editor_docs", __name__)

# ── Storage directories ──
_DOCS_DIR: str | None = None


def _get_docs_dir() -> str:
    global _DOCS_DIR
    if _DOCS_DIR is None:
        from web.shared import WORKSPACE_DIR
        _DOCS_DIR = os.path.join(WORKSPACE_DIR, "editor-docs")
    os.makedirs(_DOCS_DIR, exist_ok=True)
    return _DOCS_DIR


def _get_raw_dir() -> str:
    """Directory for original binary imports (PDF etc.)."""
    d = os.path.join(_get_docs_dir(), "raw")
    os.makedirs(d, exist_ok=True)
    return d


def _get_images_dir(doc_id: str) -> str:
    """Per-document image directory for DOCX/PPT embedded images."""
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id)
    d = os.path.join(_get_docs_dir(), safe_id, "images")
    os.makedirs(d, exist_ok=True)
    return d


def _doc_path(doc_id: str) -> str:
    # Sanitize id to prevent path traversal
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id)
    if not safe_id:
        raise ValueError("Invalid document ID")
    return os.path.join(_get_docs_dir(), f"{safe_id}.json")


def _read_doc(doc_id: str) -> dict | None:
    path = _doc_path(doc_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_doc(doc: dict) -> None:
    path = _doc_path(doc["id"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ── List all docs ──
@editor_docs_bp.route("/api/editor/docs", methods=["GET"])
def list_docs() -> Response:
    docs_dir = _get_docs_dir()
    docs = []
    for fname in sorted(os.listdir(docs_dir)):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(docs_dir, fname), "r", encoding="utf-8") as f:
                d = json.load(f)
            docs.append({
                "id": d["id"],
                "name": d.get("name", "未命名"),
                "updatedAt": d.get("updatedAt", ""),
                "createdAt": d.get("createdAt", ""),
                "size": len(d.get("content", "")),
                "viewerType": (d.get("viewerData") or {}).get("type"),
            })
        except Exception as e:
            _logger.warning("Bad doc file %s: %s", fname, e)
    # Sort by updatedAt descending (most recent first)
    docs.sort(key=lambda x: x.get("updatedAt", ""), reverse=True)
    return jsonify({"docs": docs})


# ── Create blank doc ──
@editor_docs_bp.route("/api/editor/docs", methods=["POST"])
def create_doc() -> Response:
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "未命名文档").strip()[:200]
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    doc = {
        "id": _new_id(),
        "name": name,
        "content": "",
        "snapshot": None,
        "viewerData": None,
        "createdAt": now,
        "updatedAt": now,
    }
    _write_doc(doc)
    _logger.info("Created doc %s: %s", doc["id"], name)
    return jsonify({"id": doc["id"], "name": doc["name"]}), 201


# ── Get doc ──
@editor_docs_bp.route("/api/editor/docs/<doc_id>", methods=["GET"])
def get_doc(doc_id: str) -> Response:
    doc = _read_doc(doc_id)
    if not doc:
        return jsonify({"error": "Not found"}), 404
    return jsonify(doc)


# ── Serve original binary (PDF) ──
@editor_docs_bp.route("/api/editor/docs/<doc_id>/raw", methods=["GET"])
def get_doc_raw(doc_id: str) -> Response:
    doc = _read_doc(doc_id)
    if not doc:
        return jsonify({"error": "Not found"}), 404
    imported_from = doc.get("importedFrom", "")
    ext = os.path.splitext(imported_from)[1].lower() if imported_from else ""
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id)
    raw_path = os.path.join(_get_raw_dir(), f"{safe_id}{ext}")
    if not os.path.exists(raw_path):
        return jsonify({"error": "Raw file not found"}), 404
    mime = mimetypes.guess_type(raw_path)[0] or "application/octet-stream"
    return send_file(raw_path, mimetype=mime, as_attachment=False)


# ── Save/update doc ──
@editor_docs_bp.route("/api/editor/docs/<doc_id>", methods=["PUT"])
def update_doc(doc_id: str) -> Response:
    doc = _read_doc(doc_id)
    if not doc:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json(silent=True) or {}
    if "content" in data:
        doc["content"] = data["content"]
    if "snapshot" in data:
        doc["snapshot"] = data["snapshot"]
    if "name" in data:
        doc["name"] = str(data["name"]).strip()[:200]
    doc["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _write_doc(doc)
    return jsonify({"ok": True})


# ── Rename doc ──
@editor_docs_bp.route("/api/editor/docs/<doc_id>", methods=["PATCH"])
def rename_doc(doc_id: str) -> Response:
    doc = _read_doc(doc_id)
    if not doc:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()[:200]
    if not name:
        return jsonify({"error": "Name required"}), 400
    doc["name"] = name
    doc["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _write_doc(doc)
    return jsonify({"ok": True})


# ── Delete doc ──
@editor_docs_bp.route("/api/editor/docs/<doc_id>", methods=["DELETE"])
def delete_doc(doc_id: str) -> Response:
    path = _doc_path(doc_id)
    if not os.path.exists(path):
        return jsonify({"error": "Not found"}), 404
    os.remove(path)
    _logger.info("Deleted doc %s", doc_id)
    return jsonify({"ok": True})


# ── Import file ──
# Supported: .txt .md .docx .pdf .xlsx .xls .pptx .csv .json .html .rtf
#            + code files: .py .js .ts .sh .yaml .toml .rs .go .java .c .cpp .cs .rb .php
@editor_docs_bp.route("/api/editor/docs/import", methods=["POST"])
def import_doc() -> Response:
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    original_name = f.filename
    ext = os.path.splitext(original_name)[1].lower()
    raw = f.read()

    doc_id = _new_id()
    text = ""
    viewer_data = None

    try:
        if ext == ".pdf":
            text = _extract_pdf(raw)
            # Save original PDF bytes for iframe rendering
            safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id)
            raw_path = os.path.join(_get_raw_dir(), f"{safe_id}.pdf")
            with open(raw_path, "wb") as rf:
                rf.write(raw)
            viewer_data = {"type": "pdf"}

        elif ext in (".xlsx", ".xls"):
            viewer_data = _extract_excel(raw)
            text = _excel_to_text(viewer_data)

        elif ext == ".pptx":
            viewer_data = _extract_ppt(raw, doc_id)
            text = _ppt_to_text(viewer_data)

        elif ext == ".csv":
            viewer_data = _extract_csv(raw)
            # Plain text for AI = raw CSV
            text = raw.decode("utf-8", errors="replace")

        elif ext == ".docx":
            text = _extract_docx(raw)
            images = _extract_docx_images(raw, doc_id)
            if images:
                viewer_data = {"type": "docx", "images": images}

        elif ext == ".md":
            text = raw.decode("utf-8", errors="replace")
            viewer_data = {"type": "markdown"}

        elif ext in _CODE_EXTENSIONS:
            text = raw.decode("utf-8", errors="replace")
            viewer_data = {"type": "code", "lang": _detect_code_lang(ext)}

        elif ext in (".txt", ".json", ".html", ".rtf"):
            text = raw.decode("utf-8", errors="replace")

        else:
            # Generic: try UTF-8 text
            text = raw.decode("utf-8", errors="replace")

    except Exception as e:
        _logger.error("Import parse error for %s: %s", original_name, e)
        return jsonify({"error": f"无法解析文件: {e}"}), 400

    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    doc_name = os.path.splitext(original_name)[0][:200]
    doc = {
        "id": doc_id,
        "name": doc_name,
        "content": text,
        "snapshot": None,
        "viewerData": viewer_data,
        "createdAt": now,
        "updatedAt": now,
        "importedFrom": original_name,
    }
    _write_doc(doc)
    _logger.info("Imported %s → doc %s (%d chars, viewer=%s)",
                 original_name, doc_id, len(text),
                 viewer_data.get("type") if viewer_data else "none")
    return jsonify({
        "id": doc_id,
        "name": doc_name,
        "size": len(text),
        "viewerType": viewer_data.get("type") if viewer_data else None,
    }), 201


# ══════════════════════════════════════════════════════════════════
# Extraction helpers
# ══════════════════════════════════════════════════════════════════

_CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".sh", ".bash",
    ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".rs", ".go", ".java", ".c", ".cpp", ".cc", ".h", ".hpp",
    ".cs", ".rb", ".php", ".swift", ".kt", ".scala", ".r",
    ".sql", ".lua", ".pl", ".ps1",
}

_LANG_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".sh": "bash",
    ".bash": "bash",
    ".ps1": "powershell",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".sql": "sql",
    ".lua": "lua",
    ".r": "r",
    ".json": "json",
    ".html": "html",
    ".css": "css",
    ".xml": "xml",
    ".md": "markdown",
}


def _detect_code_lang(ext: str) -> str:
    return _LANG_MAP.get(ext.lower(), "text")


def _extract_docx(raw_bytes: bytes) -> str:
    """Extract plain text from .docx."""
    try:
        import docx
        doc = docx.Document(io.BytesIO(raw_bytes))
        return "\n".join(p.text for p in doc.paragraphs)
    except ImportError:
        pass
    # Fallback: extract from XML inside zip
    try:
        z = zipfile.ZipFile(io.BytesIO(raw_bytes))
        xml_content = z.read("word/document.xml")
        import xml.etree.ElementTree as ET
        tree = ET.fromstring(xml_content)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        texts = []
        for p in tree.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
            runs = p.findall(".//w:t", ns)
            line = "".join(r.text or "" for r in runs)
            texts.append(line)
        return "\n".join(texts)
    except Exception as e:
        raise ValueError(f"Failed to parse docx: {e}") from e


def _extract_docx_images(raw_bytes: bytes, doc_id: str) -> list[dict]:
    """Extract embedded images from .docx, save to disk, return URL list."""
    images = []
    try:
        import docx
        doc = docx.Document(io.BytesIO(raw_bytes))
        img_dir = _get_images_dir(doc_id)
        idx = 0
        for rel in doc.part.rels.values():
            if "image" not in rel.reltype:
                continue
            try:
                img_part = rel.target_part
                blob = img_part.blob
                content_type = img_part.content_type or "image/png"
                # Map mime type to extension
                ext_map = {
                    "image/png": ".png",
                    "image/jpeg": ".jpg",
                    "image/gif": ".gif",
                    "image/bmp": ".bmp",
                    "image/tiff": ".tiff",
                    "image/webp": ".webp",
                    "image/svg+xml": ".svg",
                }
                img_ext = ext_map.get(content_type, ".png")
                filename = f"img_{idx:03d}{img_ext}"
                img_path = os.path.join(img_dir, filename)
                with open(img_path, "wb") as imgf:
                    imgf.write(blob)
                safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id)
                url = f"/api/workspace/editor-docs/{safe_id}/images/{filename}"
                images.append({"filename": filename, "url": url, "type": content_type})
                idx += 1
            except Exception as ex:
                _logger.debug("Skipping image rel: %s", ex)
    except ImportError:
        # python-docx not available — try zipfile approach
        try:
            img_dir = _get_images_dir(doc_id)
            z = zipfile.ZipFile(io.BytesIO(raw_bytes))
            idx = 0
            for name in z.namelist():
                if name.startswith("word/media/"):
                    blob = z.read(name)
                    filename = os.path.basename(name)
                    img_path = os.path.join(img_dir, filename)
                    with open(img_path, "wb") as imgf:
                        imgf.write(blob)
                    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id)
                    url = f"/api/workspace/editor-docs/{safe_id}/images/{filename}"
                    images.append({"filename": filename, "url": url})
                    idx += 1
        except Exception as ex:
            _logger.debug("Zipfile image extraction failed: %s", ex)
    except Exception as ex:
        _logger.warning("DOCX image extraction error: %s", ex)
    return images


def _extract_pdf(raw_bytes: bytes) -> str:
    """Extract text from PDF using pdfplumber (preferred) / pypdf / PyPDF2."""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            pages = []
            for page in pdf.pages:
                t = page.extract_text() or ""
                pages.append(t)
        return "\n".join(pages)
    except ImportError:
        pass
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        pass
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(raw_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        raise ValueError("PDF 解析需要 pdfplumber 或 pypdf 库，请安装后重试")


def _extract_excel(raw_bytes: bytes) -> dict:
    """Extract structured data from .xlsx/.xls using openpyxl."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), read_only=True, data_only=True)
    sheets = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = []
        row_count = 0
        for row in ws.iter_rows(values_only=True):
            # Convert cells to JSON-serializable types
            cells = []
            for cell in row:
                if cell is None:
                    cells.append({"v": "", "t": "s"})
                elif isinstance(cell, (int, float)):
                    cells.append({"v": cell, "t": "n"})
                elif isinstance(cell, bool):
                    cells.append({"v": cell, "t": "b"})
                else:
                    cells.append({"v": str(cell), "t": "s"})
            rows.append(cells)
            row_count += 1
            if row_count >= 1000:
                break
        sheets.append({"name": sheet_name, "rows": rows})
    wb.close()
    return {"type": "excel", "sheets": sheets}


def _excel_to_text(viewer_data: dict) -> str:
    """Flatten excel viewerData to plain text for AI analysis."""
    lines = []
    for sheet in viewer_data.get("sheets", []):
        lines.append(f"=== {sheet['name']} ===")
        for row in sheet.get("rows", []):
            lines.append("\t".join(str(c.get("v", "")) for c in row))
    return "\n".join(lines)


def _extract_ppt(raw_bytes: bytes, doc_id: str) -> dict:
    """Extract structured data from .pptx using python-pptx."""
    try:
        from pptx import Presentation
        from pptx.util import MSO_SHAPE_TYPE  # type: ignore
    except ImportError:
        raise ValueError("PPT 解析需要 python-pptx 库，请安装后重试")

    prs = Presentation(io.BytesIO(raw_bytes))
    img_dir = _get_images_dir(doc_id)
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id)
    slides_data = []
    img_idx = 0

    for slide_idx, slide in enumerate(prs.slides):
        title = ""
        body_parts = []
        notes = ""
        slide_images = []

        for shape in slide.shapes:
            # Extract images
            try:
                if shape.shape_type == 13:  # MSO_SHAPE_TYPE.PICTURE
                    blob = shape.image.blob
                    content_type = shape.image.content_type or "image/png"
                    ext_map = {
                        "image/png": ".png", "image/jpeg": ".jpg",
                        "image/gif": ".gif", "image/bmp": ".bmp",
                        "image/webp": ".webp",
                    }
                    img_ext = ext_map.get(content_type, ".png")
                    filename = f"slide{slide_idx:02d}_img{img_idx:03d}{img_ext}"
                    img_path = os.path.join(img_dir, filename)
                    with open(img_path, "wb") as imgf:
                        imgf.write(blob)
                    url = f"/api/workspace/editor-docs/{safe_id}/images/{filename}"
                    slide_images.append({"filename": filename, "url": url})
                    img_idx += 1
            except Exception:
                pass

            # Extract text
            if not shape.has_text_frame:
                continue
            text = shape.text_frame.text.strip()
            if not text:
                continue
            # Heuristic: title placeholder
            if shape.placeholder_format and shape.placeholder_format.idx == 0:
                title = text
            else:
                body_parts.append(text)

        # Extract notes
        if slide.has_notes_slide:
            notes_tf = slide.notes_slide.notes_text_frame
            notes = notes_tf.text.strip() if notes_tf else ""

        slides_data.append({
            "index": slide_idx,
            "title": title,
            "body": "\n".join(body_parts),
            "notes": notes,
            "images": slide_images,
        })

    return {"type": "ppt", "slides": slides_data}


def _ppt_to_text(viewer_data: dict) -> str:
    """Flatten ppt viewerData to plain text for AI analysis."""
    lines = []
    for slide in viewer_data.get("slides", []):
        idx = slide.get("index", 0) + 1
        title = slide.get("title", "")
        body = slide.get("body", "")
        notes = slide.get("notes", "")
        lines.append(f"=== 幻灯片 {idx}{': ' + title if title else ''} ===")
        if body:
            lines.append(body)
        if notes:
            lines.append(f"[备注] {notes}")
    return "\n\n".join(lines)


def _extract_csv(raw_bytes: bytes) -> dict:
    """Parse CSV into structured {type, headers, rows}."""
    text = raw_bytes.decode("utf-8", errors="replace")
    reader = _csv.reader(io.StringIO(text))
    all_rows = list(reader)
    if not all_rows:
        return {"type": "csv", "headers": [], "rows": []}
    headers = all_rows[0]
    rows = all_rows[1:1001]   # Cap at 1000 data rows
    return {"type": "csv", "headers": headers, "rows": rows}
