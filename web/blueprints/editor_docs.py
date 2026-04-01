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
  POST   /api/editor/docs/import       — Import a file (txt/md/docx/pdf)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid

from flask import Blueprint, Response, jsonify, request

_logger = logging.getLogger("koto.routes.editor_docs")

editor_docs_bp = Blueprint("editor_docs", __name__)

# ── Storage directory ──
_DOCS_DIR: str | None = None


def _get_docs_dir() -> str:
    global _DOCS_DIR
    if _DOCS_DIR is None:
        from web.shared import WORKSPACE_DIR
        _DOCS_DIR = os.path.join(WORKSPACE_DIR, "editor-docs")
    os.makedirs(_DOCS_DIR, exist_ok=True)
    return _DOCS_DIR


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

    # Extract text based on file type
    text = ""
    try:
        if ext in (".txt", ".md", ".csv", ".json", ".html", ".rtf"):
            text = raw.decode("utf-8", errors="replace")
        elif ext == ".docx":
            text = _extract_docx(raw)
        elif ext == ".pdf":
            text = _extract_pdf(raw)
        else:
            # Try plain text
            text = raw.decode("utf-8", errors="replace")
    except Exception as e:
        _logger.error("Import parse error for %s: %s", original_name, e)
        return jsonify({"error": f"无法解析文件: {e}"}), 400

    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    doc_name = os.path.splitext(original_name)[0][:200]
    doc = {
        "id": _new_id(),
        "name": doc_name,
        "content": text,
        "snapshot": None,
        "createdAt": now,
        "updatedAt": now,
        "importedFrom": original_name,
    }
    _write_doc(doc)
    _logger.info("Imported %s → doc %s (%d chars)", original_name, doc["id"], len(text))
    return jsonify({"id": doc["id"], "name": doc_name, "size": len(text)}), 201


@editor_docs_bp.route("/api/editor/docs/import_path", methods=["POST"])
def import_doc_from_path() -> Response:
    """Import a document from a server-side file path (JSON body: {"path": "..."})."""
    data = request.get_json(silent=True) or {}
    file_path = data.get("path", "")
    if not file_path:
        return jsonify({"error": "Missing 'path' in request body"}), 400

    try:
        with open(file_path, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        return jsonify({"error": f"File not found: {file_path}"}), 404
    except OSError as e:
        return jsonify({"error": str(e)}), 400

    original_name = os.path.basename(file_path)
    ext = os.path.splitext(original_name)[1].lower()

    text = ""
    try:
        if ext in (".txt", ".md", ".csv", ".json", ".html", ".rtf"):
            text = raw.decode("utf-8", errors="replace")
        elif ext == ".docx":
            text = _extract_docx(raw)
        elif ext == ".pdf":
            text = _extract_pdf(raw)
        else:
            text = raw.decode("utf-8", errors="replace")
    except Exception as e:
        _logger.error("Import_path parse error for %s: %s", file_path, e)
        return jsonify({"error": f"无法解析文件: {e}"}), 400

    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    doc_name = os.path.splitext(original_name)[0][:200]
    doc = {
        "id": _new_id(),
        "name": doc_name,
        "content": text,
        "snapshot": None,
        "createdAt": now,
        "updatedAt": now,
        "importedFrom": original_name,
    }
    _write_doc(doc)
    _logger.info("Imported path %s → doc %s (%d chars)", file_path, doc["id"], len(text))
    return jsonify({"id": doc["id"], "name": doc_name, "size": len(text)}), 201


# ── Text extraction helpers ──

def _extract_docx(raw_bytes: bytes) -> str:
    """Extract text from .docx using python-docx if available, else zipfile fallback."""
    try:
        import docx
        import io
        doc = docx.Document(io.BytesIO(raw_bytes))
        return "\n".join(p.text for p in doc.paragraphs)
    except ImportError:
        pass
    # Fallback: extract from XML inside zip
    import io
    import zipfile
    import xml.etree.ElementTree as ET
    try:
        z = zipfile.ZipFile(io.BytesIO(raw_bytes))
        xml_content = z.read("word/document.xml")
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


def _extract_pdf(raw_bytes: bytes) -> str:
    """Extract text from PDF using PyPDF2/pypdf if available."""
    try:
        import pypdf
        import io
        reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
        texts = []
        for page in reader.pages:
            texts.append(page.extract_text() or "")
        return "\n".join(texts)
    except ImportError:
        pass
    try:
        import PyPDF2
        import io
        reader = PyPDF2.PdfReader(io.BytesIO(raw_bytes))
        texts = []
        for page in reader.pages:
            texts.append(page.extract_text() or "")
        return "\n".join(texts)
    except ImportError:
        raise ValueError("PDF 解析需要 pypdf 或 PyPDF2 库，请安装后重试")
