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


# ── Export doc to workspace ──
# Binary formats that can be reconstructed: docx (via python-docx)
# Binary formats served from raw/: pdf, xlsx, xls, pptx, ppt, doc
# Text-based formats (write content with original ext): txt, md, csv, json, html, rtf + all code extensions
_TEXT_EXTS = {
    '.txt', '.md', '.csv', '.json', '.html', '.htm', '.rtf',
    '.py', '.js', '.ts', '.jsx', '.tsx', '.sh', '.bash', '.zsh',
    '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
    '.rs', '.go', '.java', '.c', '.cpp', '.cc', '.cs', '.rb', '.php',
    '.sql', '.r', '.kt', '.swift', '.m', '.h', '.hpp', '.lua',
    '.xml', '.tex', '.rst', '.adoc',
}
_RAW_BINARY_EXTS = {'.pdf', '.xlsx', '.xls', '.pptx', '.ppt', '.doc'}


@editor_docs_bp.route("/api/editor/docs/<doc_id>/export", methods=["POST"])
def export_doc_to_workspace(doc_id: str) -> Response:
    """将文档导出到工作区，根据原始格式选择输出类型：
    - 文本类（.md/.csv/.py 等）→ 原扩展名写文本内容
    - .docx → 用 python-docx 生成真正的 Word 文件
    - 其他二进制（.pdf/.xlsx/.pptx 等）→ 从 raw/ 复制原始文件
    - 无原始格式 → .txt
    """
    doc = _read_doc(doc_id)
    if not doc:
        return jsonify({"error": "Not found"}), 404

    content = doc.get("content", "")
    raw_name = doc.get("name") or "未命名文档"
    imported_from = doc.get("importedFrom", "") or ""

    # Determine original extension
    orig_ext = os.path.splitext(imported_from)[1].lower() if imported_from else ""

    # Build safe stem (use importedFrom stem if available, else doc name)
    base = os.path.splitext(os.path.basename(imported_from))[0] if imported_from else raw_name
    stem = base.rsplit(".", 1)[0] if ("." in base and not imported_from) else base
    safe_stem = re.sub(r'[\\/:*?"<>|]', "_", stem).strip() or "文档"

    from web.shared import WORKSPACE_DIR
    ws = str(WORKSPACE_DIR)

    # ── Case 1: .docx → generate with formatting (snapshot) or plain text ──
    if orig_ext == ".docx":
        try:
            snapshot = doc.get("snapshot")
            if snapshot and isinstance(snapshot, dict) and snapshot.get("body"):
                docx_bytes = _snapshot_to_docx(snapshot)
            else:
                import docx as _docx
                document = _docx.Document()
                for para_text in content.split("\n"):
                    document.add_paragraph(para_text)
                buf = io.BytesIO()
                document.save(buf)
                docx_bytes = buf.getvalue()
            filename = safe_stem + ".docx"
            out_path = os.path.join(ws, filename)
            with open(out_path, "wb") as fout:
                fout.write(docx_bytes)
            _logger.info("Exported doc %s → %s (docx, snapshot=%s)", doc_id, out_path, bool(snapshot))
            return jsonify({"ok": True, "path": out_path, "filename": filename})
        except Exception as e:
            _logger.warning("DOCX export failed for %s: %s — falling back to txt", doc_id, e)
            orig_ext = ".txt"

    # ── Case 2: binary formats → copy raw file ───────────────────────────
    if orig_ext in _RAW_BINARY_EXTS:
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id)
        raw_path = os.path.join(_get_raw_dir(), f"{safe_id}{orig_ext}")
        if os.path.exists(raw_path):
            import shutil
            filename = safe_stem + orig_ext
            out_path = os.path.join(ws, filename)
            shutil.copy2(raw_path, out_path)
            _logger.info("Exported doc %s → %s (raw copy)", doc_id, out_path)
            return jsonify({"ok": True, "path": out_path, "filename": filename})
        # Raw not found → fall through to text export

    # ── Case 3: text-based formats → write content with original ext ─────
    if orig_ext in _TEXT_EXTS:
        out_ext = orig_ext
    else:
        out_ext = ".txt"  # new docs or unknown binary without raw

    filename = safe_stem + out_ext
    out_path = os.path.join(ws, filename)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    _logger.info("Exported doc %s → %s (text)", doc_id, out_path)
    return jsonify({"ok": True, "path": out_path, "filename": filename})


# ── Download doc (for native Save-As dialog) ──
@editor_docs_bp.route("/api/editor/docs/<doc_id>/download", methods=["GET"])
def download_doc(doc_id: str) -> Response:
    """返回文档字节流，供前端原生 Save-As 对话框使用。
    - .docx → python-docx 生成 Word 字节流
    - 二进制（.pdf/.xlsx 等）→ 直接发送 raw/ 原始文件
    - 文本（.md/.py 等）/ 新文档 → UTF-8 文本流
    """
    doc = _read_doc(doc_id)
    if not doc:
        return jsonify({"error": "Not found"}), 404

    content = doc.get("content", "")
    raw_name = doc.get("name") or "未命名文档"
    imported_from = doc.get("importedFrom", "") or ""

    orig_ext = os.path.splitext(imported_from)[1].lower() if imported_from else ""
    base = os.path.splitext(os.path.basename(imported_from))[0] if imported_from else raw_name
    safe_stem = re.sub(r'[\\/:*?"<>|]', "_", base).strip() or "文档"

    # Case 1: .docx → generate with formatting (snapshot) or plain text
    if orig_ext == ".docx":
        try:
            snapshot = doc.get("snapshot")
            if snapshot and isinstance(snapshot, dict) and snapshot.get("body"):
                docx_bytes = _snapshot_to_docx(snapshot)
            else:
                import docx as _docx
                document = _docx.Document()
                for para_text in content.split("\n"):
                    document.add_paragraph(para_text)
                buf2 = io.BytesIO()
                document.save(buf2)
                docx_bytes = buf2.getvalue()
            filename = safe_stem + ".docx"
            buf = io.BytesIO(docx_bytes)
            return send_file(
                buf,
                as_attachment=True,
                download_name=filename,
                mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        except Exception as e:
            _logger.warning("DOCX download failed: %s – falling back to txt", e)
            orig_ext = ".txt"

    # Case 2: binary → serve raw file
    if orig_ext in _RAW_BINARY_EXTS:
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id)
        raw_path = os.path.join(_get_raw_dir(), f"{safe_id}{orig_ext}")
        if os.path.exists(raw_path):
            filename = safe_stem + orig_ext
            mime, _ = mimetypes.guess_type(filename)
            return send_file(
                raw_path,
                as_attachment=True,
                download_name=filename,
                mimetype=mime or "application/octet-stream",
            )

    # Case 3: text / fallback
    out_ext = orig_ext if orig_ext in _TEXT_EXTS else ".txt"
    filename = safe_stem + out_ext
    buf = io.BytesIO(content.encode("utf-8"))
    mime, _ = mimetypes.guess_type(filename)
    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype=mime or "text/plain; charset=utf-8",
    )


# ── Serve embedded images (DOCX / PPTX) ──
@editor_docs_bp.route("/api/workspace/editor-docs/<doc_id>/images/<path:filename>", methods=["GET"])
def serve_doc_image(doc_id: str, filename: str) -> Response:
    """Serve embedded images extracted from DOCX/PPTX files."""
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id)
    safe_filename = os.path.basename(filename)  # prevent path traversal
    img_dir = os.path.join(_get_docs_dir(), safe_id, "images")
    img_path = os.path.join(img_dir, safe_filename)
    if not os.path.exists(img_path):
        return jsonify({"error": "Not found"}), 404
    mime, _ = mimetypes.guess_type(safe_filename)
    return send_file(img_path, mimetype=mime or "image/png")


# ── Update xlsx / csv cell values ──
@editor_docs_bp.route("/api/editor/docs/<doc_id>/cells", methods=["PUT"])
def update_doc_cells(doc_id: str) -> Response:
    """Save edited cell values for xlsx or csv documents.

    Body JSON for xlsx:  { "sheets": [{ "name": "Sheet1", "rows": [[{"v": val, "t": type}, ...]] }] }
    Body JSON for csv:   { "headers": [...], "rows": [[...], ...] }
    """
    doc = _read_doc(doc_id)
    if not doc:
        return jsonify({"error": "Not found"}), 404

    imported_from = doc.get("importedFrom", "") or ""
    ext = os.path.splitext(imported_from)[1].lower()
    data = request.get_json(silent=True) or {}

    if ext in (".xlsx", ".xls"):
        sheets_data = data.get("sheets", [])
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id)
        raw_path = os.path.join(_get_raw_dir(), f"{safe_id}.xlsx")
        if not os.path.exists(raw_path):
            return jsonify({"error": "Raw XLSX not found — reimport the file"}), 404
        try:
            import openpyxl
            wb = openpyxl.load_workbook(raw_path)
            for sheet_update in sheets_data:
                sname = sheet_update.get("name")
                ws = wb[sname] if sname and sname in wb.sheetnames else wb.active
                for ri, row in enumerate(sheet_update.get("rows", []), start=1):
                    for ci, cell_data in enumerate(row, start=1):
                        v = cell_data.get("v", "")
                        # Numeric coercion
                        if cell_data.get("t") == "n" and v != "":
                            try:
                                fv = float(v)
                                v = int(fv) if fv == int(fv) else fv
                            except (ValueError, TypeError):
                                pass
                        ws.cell(row=ri, column=ci, value=v if v != "" else None)
            wb.save(raw_path)
            # Refresh viewer_data + content
            with open(raw_path, "rb") as rf:
                new_vd = _extract_excel(rf.read())
            doc["viewerData"] = new_vd
            doc["content"] = _excel_to_text(new_vd)
            doc["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            _write_doc(doc)
            return jsonify({"ok": True})
        except Exception as e:
            _logger.error("XLSX cell update failed for %s: %s", doc_id, e)
            return jsonify({"error": str(e)}), 500

    elif ext == ".csv":
        headers = data.get("headers", [])
        rows = data.get("rows", [])
        buf = io.StringIO()
        writer = _csv.writer(buf)
        if headers:
            writer.writerow([str(h) for h in headers])
        for row in rows:
            writer.writerow([str(c) if c is not None else "" for c in row])
        new_csv = buf.getvalue()
        doc["content"] = new_csv
        doc["viewerData"] = _extract_csv(new_csv.encode("utf-8"))
        doc["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _write_doc(doc)
        return jsonify({"ok": True})

    return jsonify({"error": f"Cell editing not supported for {ext}"}), 400


# ── Update PPTX slide texts ──
@editor_docs_bp.route("/api/editor/docs/<doc_id>/slide-texts", methods=["PUT"])
def update_slide_texts(doc_id: str) -> Response:
    """Save edited title/body text back into a PPTX file.

    Body JSON: { "slides": [{ "index": 0, "title": "...", "body": "..." }, ...] }
    """
    doc = _read_doc(doc_id)
    if not doc:
        return jsonify({"error": "Not found"}), 404

    imported_from = doc.get("importedFrom", "") or ""
    ext = os.path.splitext(imported_from)[1].lower()
    if ext != ".pptx":
        return jsonify({"error": "Not a PPTX file"}), 400

    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id)
    raw_path = os.path.join(_get_raw_dir(), f"{safe_id}.pptx")
    if not os.path.exists(raw_path):
        return jsonify({"error": "Raw PPTX not found — reimport the file"}), 404

    data = request.get_json(silent=True) or {}
    slides_updates = data.get("slides", [])

    try:
        from pptx import Presentation

        with open(raw_path, "rb") as fh:
            prs = Presentation(io.BytesIO(fh.read()))

        for update in slides_updates:
            idx = update.get("index", 0)
            if idx >= len(prs.slides):
                continue
            slide = prs.slides[idx]

            # Locate title (ph idx 0) and body (ph idx 1) placeholders
            title_shape = None
            body_shape = None
            for shape in slide.shapes:
                if not shape.has_text_frame:
                    continue
                ph = getattr(shape, "placeholder_format", None)
                if ph is not None:
                    if ph.idx == 0 and title_shape is None:
                        title_shape = shape
                    elif ph.idx in (1, 2) and body_shape is None:
                        body_shape = shape

            if title_shape and "title" in update:
                _pptx_set_shape_text(title_shape, update["title"])
            if body_shape and "body" in update:
                _pptx_set_shape_text(body_shape, update["body"])

        buf = io.BytesIO()
        prs.save(buf)
        new_bytes = buf.getvalue()

        with open(raw_path, "wb") as fh:
            fh.write(new_bytes)

        # Refresh viewer_data + content
        new_vd = _extract_ppt(new_bytes, doc_id)
        doc["viewerData"] = new_vd
        doc["content"] = _ppt_to_text(new_vd)
        doc["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _write_doc(doc)

        return jsonify({"ok": True})
    except Exception as e:
        _logger.error("PPTX slide update failed for %s: %s", doc_id, e)
        return jsonify({"error": str(e)}), 500


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
            # Save raw bytes for round-trip and download
            safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id)
            raw_path = os.path.join(_get_raw_dir(), f"{safe_id}.docx")
            with open(raw_path, "wb") as rf:
                rf.write(raw)
            text = _extract_docx(raw)
            images = _extract_docx_images(raw, doc_id)
            viewer_data = {"type": "docx", "images": images}

        elif ext in (".xlsx", ".xls"):
            # Save raw bytes so edits can be written back
            safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id)
            raw_path = os.path.join(_get_raw_dir(), f"{safe_id}.xlsx")
            with open(raw_path, "wb") as rf:
                rf.write(raw)
            viewer_data = _extract_excel(raw)
            text = _excel_to_text(viewer_data)

        elif ext == ".pptx":
            # Save raw bytes so text edits can be written back
            safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id)
            raw_path = os.path.join(_get_raw_dir(), f"{safe_id}.pptx")
            with open(raw_path, "wb") as rf:
                rf.write(raw)
            viewer_data = _extract_ppt(raw, doc_id)
            text = _ppt_to_text(viewer_data)

        elif ext == ".csv":
            viewer_data = _extract_csv(raw)
            # Plain text for AI = raw CSV
            text = raw.decode("utf-8", errors="replace")

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

    # Generate rich Univer snapshot for DOCX
    snapshot = None
    if ext == ".docx":
        try:
            snapshot = _docx_to_snapshot(raw, doc_id)
        except Exception as snap_err:
            _logger.warning("DOCX snapshot generation failed: %s", snap_err)

    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    doc_name = os.path.splitext(original_name)[0][:200]
    doc = {
        "id": doc_id,
        "name": doc_name,
        "content": text,
        "snapshot": snapshot,
        "viewerData": viewer_data,
        "createdAt": now,
        "updatedAt": now,
        "importedFrom": original_name,
    }
    _write_doc(doc)
    _logger.info("Imported %s → doc %s (%d chars, viewer=%s, snapshot=%s)",
                 original_name, doc_id, len(text),
                 viewer_data.get("type") if viewer_data else "none",
                 "yes" if snapshot else "no")
    return jsonify({
        "id": doc_id,
        "name": doc_name,
        "size": len(text),
        "viewerType": viewer_data.get("type") if viewer_data else None,
    }), 201


@editor_docs_bp.route("/api/editor/docs/import_path", methods=["POST"])
def import_doc_from_path() -> Response:
    """从服务器本地路径导入文件到编辑器。
    Body JSON: { "path": "绝对路径" }
    返回与 /api/editor/docs/import 相同的结构。
    """
    data = request.get_json(silent=True) or {}
    path = (data.get("path") or "").strip()
    if not path:
        return jsonify({"error": "缺少 path 字段"}), 400
    if not os.path.isfile(path):
        return jsonify({"error": "文件不存在或不是有效文件"}), 404

    with open(path, "rb") as fh:
        raw = fh.read()
    original_name = os.path.basename(path)
    ext = os.path.splitext(original_name)[1].lower()

    doc_id = _new_id()
    text = ""
    viewer_data = None
    try:
        if ext == ".pdf":
            text = _extract_pdf(raw)
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
            text = raw.decode("utf-8", errors="replace")
        elif ext == ".docx":
            safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id)
            raw_path_d = os.path.join(_get_raw_dir(), f"{safe_id}.docx")
            with open(raw_path_d, "wb") as rf:
                rf.write(raw)
            text = _extract_docx(raw)
            images = _extract_docx_images(raw, doc_id)
            viewer_data = {"type": "docx", "images": images}
        elif ext in (".xlsx", ".xls"):
            safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id)
            raw_path_x = os.path.join(_get_raw_dir(), f"{safe_id}.xlsx")
            with open(raw_path_x, "wb") as rf:
                rf.write(raw)
            viewer_data = _extract_excel(raw)
            text = _excel_to_text(viewer_data)
        elif ext == ".pptx":
            safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", doc_id)
            raw_path_p = os.path.join(_get_raw_dir(), f"{safe_id}.pptx")
            with open(raw_path_p, "wb") as rf:
                rf.write(raw)
            viewer_data = _extract_ppt(raw, doc_id)
            text = _ppt_to_text(viewer_data)
        elif ext == ".md":
            text = raw.decode("utf-8", errors="replace")
            viewer_data = {"type": "markdown"}
        elif ext in _CODE_EXTENSIONS:
            text = raw.decode("utf-8", errors="replace")
            viewer_data = {"type": "code", "lang": _detect_code_lang(ext)}
        else:
            text = raw.decode("utf-8", errors="replace")
    except Exception as e:
        _logger.error("import_path parse error for %s: %s", original_name, e)
        return jsonify({"error": f"无法解析文件: {e}"}), 400

    snapshot = None
    if ext == ".docx":
        try:
            snapshot = _docx_to_snapshot(raw, doc_id)
        except Exception as snap_err:
            _logger.warning("DOCX snapshot generation failed: %s", snap_err)

    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    doc_name = os.path.splitext(original_name)[0][:200]
    doc = {
        "id": doc_id,
        "name": doc_name,
        "content": text,
        "snapshot": snapshot,
        "viewerData": viewer_data,
        "createdAt": now,
        "updatedAt": now,
        "importedFrom": original_name,
    }
    _write_doc(doc)
    _logger.info("import_path %s → doc %s (snapshot=%s)", original_name, doc_id, "yes" if snapshot else "no")
    return jsonify({
        "id": doc_id,
        "name": doc_name,
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


# ── DOCX ↔ Univer snapshot converters ──────────────────────────────────────

def _docx_to_snapshot(raw_bytes: bytes, doc_id: str) -> dict | None:
    """Convert DOCX bytes to a Univer IDocumentData snapshot JSON.

    Maps:
      Heading 1-6  → bold + graduated font size
      run.bold/italic/underline → ts.bl / ts.it / ts.ul
      run.font.size             → ts.fs (points)
      run.font.color.rgb        → ts.cl.rgb
      para.alignment            → paragraphStyle.horizontalAlign
    """
    try:
        import docx as _docx_lib
        doc = _docx_lib.Document(io.BytesIO(raw_bytes))
    except ImportError:
        return None
    except Exception as ex:
        _logger.warning("_docx_to_snapshot failed: %s", ex)
        return None

    _HEADING_SIZES: dict[int, int] = {1: 28, 2: 24, 3: 20, 4: 16, 5: 14, 6: 13}
    _HEADING_COLORS: dict[int, str] = {
        1: "1F3864", 2: "1F3864", 3: "243F60",
        4: "404040", 5: "595959", 6: "595959",
    }

    data_stream = ""
    text_runs: list[dict] = []
    paragraphs_list: list[dict] = []

    def _rgb_str(rgb_obj) -> str | None:
        try:
            s = str(rgb_obj)
            return s.upper() if len(s) == 6 else None
        except Exception:
            return None

    for para in doc.paragraphs:
        style_name = (para.style.name or "Normal") if para.style else "Normal"
        is_heading = "Heading" in style_name
        heading_level = 1
        if is_heading:
            parts = style_name.split()
            if parts and parts[-1].isdigit():
                heading_level = min(int(parts[-1]), 6)

        for run in para.runs:
            if not run.text:
                continue
            run_start = len(data_stream)
            data_stream += run.text
            run_end = len(data_stream)

            ts: dict = {}
            if run.bold or is_heading:
                ts["bl"] = 1
            if run.italic:
                ts["it"] = 1
            if run.underline:
                ts["ul"] = {"s": 1}
            if run.font.size:
                try:
                    ts["fs"] = int(run.font.size.pt)
                except Exception:
                    pass
            if "fs" not in ts and is_heading:
                ts["fs"] = _HEADING_SIZES.get(heading_level, 14)
            try:
                if run.font.color and run.font.color.type is not None and run.font.color.rgb:
                    c = _rgb_str(run.font.color.rgb)
                    if c:
                        ts["cl"] = {"rgb": c}
            except Exception:
                pass
            if is_heading and "cl" not in ts:
                ts["cl"] = {"rgb": _HEADING_COLORS.get(heading_level, "000000")}
            if run.font.name:
                ts["ff"] = run.font.name
            if ts:
                text_runs.append({"st": run_start, "ed": run_end, "ts": ts})

        para_item: dict = {"startIndex": len(data_stream)}
        try:
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            _ALIGN_MAP = {
                WD_ALIGN_PARAGRAPH.CENTER: 2,
                WD_ALIGN_PARAGRAPH.RIGHT: 3,
                WD_ALIGN_PARAGRAPH.JUSTIFY: 4,
            }
            al = _ALIGN_MAP.get(para.alignment)
            if al:
                para_item["paragraphStyle"] = {"horizontalAlign": al}
        except Exception:
            pass
        paragraphs_list.append(para_item)
        data_stream += "\r"

    if not data_stream.strip("\r\n "):
        return None

    section_break_idx = len(data_stream)
    data_stream += "\n"
    return {
        "id": f"koto-doc-{doc_id}",
        "body": {
            "dataStream": data_stream,
            "textRuns": text_runs,
            "paragraphs": paragraphs_list,
            "sectionBreaks": [{"startIndex": section_break_idx}],
        },
        "documentStyle": {
            "pageSize": {"width": 595.28, "height": 841.89},
            "marginTop": 72,
            "marginBottom": 72,
            "marginLeft": 90,
            "marginRight": 90,
        },
    }


def _snapshot_to_docx(snapshot: dict) -> bytes:
    """Convert a Univer IDocumentData snapshot back to DOCX bytes, preserving formatting."""
    import docx as _docx_lib
    from docx.shared import Pt, RGBColor

    doc = _docx_lib.Document()
    body_data = snapshot.get("body") or {}
    data_stream: str = body_data.get("dataStream", "")
    text_runs_data: list = body_data.get("textRuns") or []

    if not data_stream:
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()

    # Remove trailing section-break \n; split on paragraph-end \r
    stream = data_stream.rstrip("\n")
    para_texts_raw = stream.split("\r")

    abs_pos = 0
    for para_text in para_texts_raw:
        if not para_text:
            doc.add_paragraph()
            abs_pos += 1  # the \r
            continue

        para = doc.add_paragraph()
        para_end = abs_pos + len(para_text)
        pos = abs_pos

        while pos < para_end:
            # Find textRun covering position pos
            covering = None
            for tr in text_runs_data:
                st = tr.get("st", 0)
                ed = tr.get("ed", 0)
                if st <= pos < ed:
                    covering = tr
                    break

            if covering:
                seg_end = min(covering["ed"], para_end)
                seg_text = data_stream[pos:seg_end]
                ts = covering.get("ts") or {}
                pos = seg_end
            else:
                next_start = para_end
                for tr in text_runs_data:
                    st = tr.get("st", 0)
                    if st > pos:
                        next_start = min(next_start, st)
                seg_text = data_stream[pos:next_start]
                ts = {}
                pos = next_start

            if not seg_text:
                continue

            run = para.add_run(seg_text)
            if ts.get("bl"):
                run.bold = True
            if ts.get("it"):
                run.italic = True
            if ts.get("ul"):
                run.underline = True
            if ts.get("fs"):
                try:
                    run.font.size = Pt(float(ts["fs"]))
                except Exception:
                    pass
            cl = ts.get("cl")
            if isinstance(cl, dict) and cl.get("rgb"):
                try:
                    rgb_str = str(cl["rgb"]).lstrip("#")
                    if len(rgb_str) == 6:
                        run.font.color.rgb = RGBColor(
                            int(rgb_str[0:2], 16),
                            int(rgb_str[2:4], 16),
                            int(rgb_str[4:6], 16),
                        )
                except Exception:
                    pass
            if ts.get("ff"):
                try:
                    run.font.name = str(ts["ff"])
                except Exception:
                    pass

        abs_pos = para_end + 1  # +1 for the \r

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def _pptx_set_shape_text(shape, new_text: str) -> None:
    """Replace text in a PPTX shape's text frame, preserving per-run formatting."""
    from copy import deepcopy
    from pptx.oxml.ns import qn as _qn

    tf = shape.text_frame
    lines = new_text.split("\n") if new_text else [""]
    paras = list(tf.paragraphs)

    for i, line in enumerate(lines):
        if i < len(paras):
            para = paras[i]
            if para.runs:
                para.runs[0].text = line
                for extra_run in para.runs[1:]:
                    extra_run._r.getparent().remove(extra_run._r)
            else:
                from lxml import etree
                r_elem = etree.SubElement(para._p, _qn("a:r"))
                t_elem = etree.SubElement(r_elem, _qn("a:t"))
                t_elem.text = line
        else:
            # Add paragraph by cloning the last one
            tmpl = paras[-1]._p if paras else None
            from lxml import etree
            if tmpl is not None:
                new_p = deepcopy(tmpl)
                for t in new_p.findall(".//" + _qn("a:t")):
                    t.text = line
                tf._txBody.append(new_p)
            else:
                p_elem = etree.SubElement(tf._txBody, _qn("a:p"))
                r_elem = etree.SubElement(p_elem, _qn("a:r"))
                t_elem = etree.SubElement(r_elem, _qn("a:t"))
                t_elem.text = line

    # Remove surplus paragraphs if new text is shorter
    for surplus_para in paras[len(lines):]:
        p_elem = surplus_para._p
        parent = p_elem.getparent()
        if parent is not None:
            parent.remove(p_elem)


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
