# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Document mutation routes extracted from the workspace assistant blueprint."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from flask import Blueprint, jsonify, request, send_file

logger = logging.getLogger(__name__)

_PDF_CONVERT_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def register_workspace_document_routes(
    blueprint: Blueprint,
    *,
    workspace_dir: Callable[[], str],
    ensure_tmp_dir: Callable[[], Path],
) -> None:
    """Register file-patch and PDF mutation routes on the workspace blueprint."""
    workspace_assistant_bp = blueprint
    _workspace_dir = workspace_dir
    _ensure_tmp_dir = ensure_tmp_dir

    @workspace_assistant_bp.route("/api/v1/workspace/patch_file", methods=["POST"])
    def patch_file():
        """
        Apply text-replacement proposals to an existing file and return the patched
        file for browser download.  Used by the multi-document content-sync feature
        so AI-generated proposals can be exported without modifying disk.

        Body (JSON):
          {
            "path":      "/absolute/or/workspace-relative/path/to/file.docx",
            "proposals": [
              {"original_text": "...", "proposed_text": "..."},
              ...
            ]
          }

        Supported formats: .docx, .txt, .md
        Returns: patched file binary (Content-Disposition: attachment)
        """
        import io as _io

        body = request.get_json(force=True, silent=True) or {}
        raw_path = (body.get("path") or "").strip()
        proposals = body.get("proposals") or []
        if not raw_path:
            return (jsonify({"error": "缺少 path 字段"}), 400)
        if not proposals:
            return (jsonify({"error": "缺少 proposals 字段"}), 400)
        target: "Path | None" = None
        candidate = Path(raw_path)
        if candidate.is_absolute() and candidate.is_file():
            target = candidate.resolve()
        else:
            try:
                ws_root = Path(_workspace_dir()).resolve()
                rel_try = ws_root.joinpath(raw_path).resolve()
                if rel_try.is_file():
                    target = rel_try
            except Exception:
                pass
        if target is None:
            return (jsonify({"error": "文件不存在或路径无效"}), 404)
        ext = target.suffix.lower()
        file_name = target.name
        if ext not in (".docx", ".txt", ".md"):
            return (
                jsonify(
                    {
                        "error": f"暂不支持对 {ext} 格式进行文本修补，请使用 .docx / .txt / .md"
                    }
                ),
                400,
            )
        clean = [
            p
            for p in proposals
            if isinstance(p, dict)
            and (p.get("original_text") or "").strip()
            and (p.get("proposed_text") or "").strip()
        ]
        if not clean:
            return (jsonify({"error": "proposals 中没有有效的修改条目"}), 400)
        if ext == ".docx":
            try:
                from docx import Document

                doc = Document(str(target))

                def _replace_in_para(para, orig: str, new: str) -> bool:
                    """Replace *orig* with *new* inside *para*, preserving run structure."""
                    full = para.text
                    if orig not in full:
                        return False
                    for run in para.runs:
                        if orig in run.text:
                            run.text = run.text.replace(orig, new)
                            return True
                    new_full = full.replace(orig, new, 1)
                    if para.runs:
                        para.runs[0].text = new_full
                        for run in para.runs[1:]:
                            run.text = ""
                    return True

                def _replace_all(orig: str, new: str):
                    for para in doc.paragraphs:
                        _replace_in_para(para, orig, new)
                    for table in doc.tables:
                        for row in table.rows:
                            for cell in row.cells:
                                for para in cell.paragraphs:
                                    _replace_in_para(para, orig, new)

                for p in clean:
                    orig = p["original_text"].strip()
                    new = p["proposed_text"].strip()
                    _replace_all(orig, new)
                buf = _io.BytesIO()
                doc.save(buf)
                buf.seek(0)
                return send_file(
                    buf,
                    mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    as_attachment=True,
                    download_name=f"修改后_{file_name}",
                )
            except ImportError:
                return (
                    jsonify(
                        {"error": "python-docx 未安装，请执行: pip install python-docx"}
                    ),
                    500,
                )
            except Exception as exc:
                logger.error("[patch_file] DOCX 修补失败: %s", exc, exc_info=True)
                return (jsonify({"error": f"DOCX 修补失败: {str(exc)}"}), 500)
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
            for p in clean:
                content = content.replace(
                    p["original_text"].strip(), p["proposed_text"].strip(), 1
                )
            buf = _io.BytesIO(content.encode("utf-8"))
            mime = (
                "text/markdown; charset=utf-8"
                if ext == ".md"
                else "text/plain; charset=utf-8"
            )
            return send_file(
                buf,
                mimetype=mime,
                as_attachment=True,
                download_name=f"修改后_{file_name}",
            )
        except Exception as exc:
            logger.error("[patch_file] TXT/MD 修补失败: %s", exc, exc_info=True)
            return (jsonify({"error": f"文本修补失败: {str(exc)}"}), 500)

    @workspace_assistant_bp.route(
        "/api/v1/workspace/pdf/save_annotations", methods=["POST"]
    )
    def pdf_save_annotations():
        """
        Embed client-side annotations into the PDF binary and return the modified file
        for download.

        Body (JSON):
          {
            "file_id": str,          — tmp file identifier (hex)
            "annotations": [...],    — array of annotation objects from KotoPdfViewer
            "filename": str          — original filename (used for download name)
          }

        Returns the annotated PDF as an attachment.
        """
        body = request.get_json(silent=True) or {}
        file_id = str(body.get("file_id", ""))
        annotations = body.get("annotations", [])
        filename = body.get("filename", "annotated.pdf")
        if not file_id.isalnum():
            return (jsonify({"error": "无效的 file_id"}), 400)
        tmp_dir = _ensure_tmp_dir()
        matches = list(tmp_dir.glob(f"{file_id}.pdf"))
        if not matches:
            matches = list(tmp_dir.glob(f"{file_id}.*"))
            matches = [m for m in matches if m.suffix.lower() == ".pdf"]
        if not matches:
            return (jsonify({"error": "找不到 PDF 文件"}), 404)
        pdf_path = str(matches[0])
        try:
            from app.core.services.pdf_annotator import embed_annotations

            pdf_bytes = embed_annotations(pdf_path, annotations)
        except Exception as exc:
            logger.error("[pdf_save_annotations] 注释嵌入失败: %s", exc, exc_info=True)
            return (jsonify({"error": f"注释嵌入失败: {str(exc)}"}), 500)
        import io as _io

        buf = _io.BytesIO(pdf_bytes)
        safe_name = filename if filename.lower().endswith(".pdf") else filename + ".pdf"
        return send_file(
            buf, mimetype="application/pdf", as_attachment=True, download_name=safe_name
        )

    @workspace_assistant_bp.route(
        "/api/v1/workspace/pdf/load_annotations/", methods=["GET"]
    )
    def pdf_load_annotations_missing_file_id():
        """Return a clear error when no cached PDF file id is provided."""
        return (jsonify({"error": "file_id 不能为空"}), 400)

    @workspace_assistant_bp.route(
        "/api/v1/workspace/pdf/load_annotations/<file_id>", methods=["GET"]
    )
    def pdf_load_annotations(file_id: str):
        """
        Read annotations embedded in a cached PDF and return them as JSON.

        Returns:
          {"annotations": [...]}
        """
        if not file_id.isalnum():
            return (jsonify({"error": "无效的 file_id"}), 400)
        tmp_dir = _ensure_tmp_dir()
        matches = [
            m for m in tmp_dir.glob(f"{file_id}.*") if m.suffix.lower() == ".pdf"
        ]
        if not matches:
            return (jsonify({"error": "找不到 PDF 文件"}), 404)
        pdf_path = str(matches[0])
        try:
            from app.core.services.pdf_annotator import read_annotations

            annotations = read_annotations(pdf_path)
        except Exception as exc:
            logger.error("[pdf_load_annotations] 批注读取失败: %s", exc, exc_info=True)
            return (jsonify({"error": f"批注读取失败: {str(exc)}"}), 500)
        return jsonify({"annotations": annotations})

    @workspace_assistant_bp.route("/api/v1/workspace/pdf/page_ops", methods=["POST"])
    def pdf_page_ops():
        """
        Reconstruct a PDF with pages in the requested order / rotation.
        Used by the Page Manager for reorder, rotate, delete, and split (export subset).

        Body (JSON):
          {
            "file_id": str,   — tmp file identifier (hex)
            "pages": [{"orig_page": int, "rotation": int}, ...]
          }

        Returns the new PDF as an attachment.
        """
        body = request.get_json(silent=True) or {}
        file_id = str(body.get("file_id", ""))
        pages = body.get("pages", [])
        if not file_id.isalnum():
            return (jsonify({"error": "无效的 file_id"}), 400)
        if not pages:
            return (jsonify({"error": "pages 不能为空"}), 400)
        tmp_dir = _ensure_tmp_dir()
        matches = [
            m for m in tmp_dir.glob(f"{file_id}.*") if m.suffix.lower() == ".pdf"
        ]
        if not matches:
            return (jsonify({"error": "找不到 PDF 文件"}), 404)
        pdf_path = str(matches[0])
        orig_name = matches[0].name
        try:
            from app.core.services.pdf_annotator import apply_page_ops

            pdf_bytes = apply_page_ops(pdf_path, pages)
        except ValueError as exc:
            return (jsonify({"error": str(exc)}), 400)
        except Exception as exc:
            logger.error("[pdf_page_ops] 页面操作失败: %s", exc, exc_info=True)
            return (jsonify({"error": f"页面操作失败: {str(exc)}"}), 500)
        import io as _io

        buf = _io.BytesIO(pdf_bytes)
        response = send_file(
            buf, mimetype="application/pdf", as_attachment=True, download_name=orig_name
        )
        response.headers["X-Koto-Page-Count"] = str(len(pages))
        return response

    @workspace_assistant_bp.route("/api/v1/workspace/pdf/convert", methods=["POST"])
    def pdf_convert():
        """
        Convert a cached PDF to another format.

        Body (JSON):
          {
            "file_id"      : str,   — tmp file identifier (hex)
            "target_format": str,   — "docx" | "xlsx" | "pptx"
            "filename"     : str    — original filename (used for download name, optional)
          }

        Returns the converted file as an attachment.
        """
        body = request.get_json(silent=True) or {}
        file_id = str(body.get("file_id", ""))
        target_fmt = str(body.get("target_format", "")).lower().lstrip(".")
        filename = body.get("filename", "converted")
        if not file_id.isalnum():
            return (jsonify({"error": "无效的 file_id"}), 400)
        if target_fmt not in _PDF_CONVERT_MIME:
            return (
                jsonify(
                    {
                        "error": f"不支持的目标格式 '{target_fmt}'，支持：docx / xlsx / pptx"
                    }
                ),
                400,
            )
        tmp_dir = _ensure_tmp_dir()
        matches = [
            m for m in tmp_dir.glob(f"{file_id}.*") if m.suffix.lower() == ".pdf"
        ]
        if not matches:
            return (jsonify({"error": "找不到 PDF 文件"}), 404)
        pdf_path = str(matches[0])
        stem = Path(filename).stem or "converted"
        download_name = f"{stem}.{target_fmt}"
        warning = ""
        try:
            from app.core.services.pdf_annotator import (
                pdf_to_docx,
                pdf_to_pptx,
                pdf_to_xlsx,
            )

            if target_fmt == "docx":
                file_bytes, warning = pdf_to_docx(pdf_path)
            elif target_fmt == "xlsx":
                file_bytes = pdf_to_xlsx(pdf_path)
            elif target_fmt == "pptx":
                file_bytes = pdf_to_pptx(pdf_path)
            else:
                return (jsonify({"error": "内部错误"}), 500)
        except Exception as exc:
            logger.error("[pdf_convert] 格式转换失败: %s", exc, exc_info=True)
            return (jsonify({"error": f"格式转换失败: {str(exc)}"}), 500)
        import io as _io

        resp = send_file(
            _io.BytesIO(file_bytes),
            mimetype=_PDF_CONVERT_MIME[target_fmt],
            as_attachment=True,
            download_name=download_name,
        )
        import hashlib as _hashlib

        resp.headers["X-Koto-Operation-Status"] = "converted"
        resp.headers["X-Koto-Artifact-Bytes"] = str(len(file_bytes))
        resp.headers["X-Koto-Artifact-SHA256"] = _hashlib.sha256(file_bytes).hexdigest()
        if warning:
            resp.headers["X-Koto-Warning"] = warning
        return resp

    @workspace_assistant_bp.route(
        "/api/v1/workspace/pdf/remove_watermark", methods=["POST"]
    )
    def pdf_remove_watermark():
        """
        Local structural watermark removal for documents the user is authorized to edit.
        Body: {"file_id": str, "use_ai": bool}
        Returns the cleaned PDF as an attachment.
        """
        body = request.get_json(silent=True) or {}
        file_id = str(body.get("file_id", ""))
        if not file_id or not file_id.replace("-", "").replace("_", "").isalnum():
            return (jsonify({"error": "无效的 file_id"}), 400)
        tmp_dir = _ensure_tmp_dir()
        matches = [
            m for m in tmp_dir.glob(f"{file_id}.*") if m.suffix.lower() == ".pdf"
        ]
        if not matches:
            return (jsonify({"error": "找不到对应的 PDF 文件，请重新打开"}), 404)
        pdf_path = str(matches[0])
        try:
            from app.core.services.pdf_annotator import remove_watermark

            pdf_bytes, removed_count, method_used = remove_watermark(pdf_path)
        except Exception as exc:
            logger.error("[pdf_remove_watermark] 失败: %s", exc, exc_info=True)
            return (jsonify({"error": f"去水印失败: {str(exc)}"}), 500)
        import io as _io

        orig_stem = matches[0].stem
        resp = send_file(
            _io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"{orig_stem}_去水印.pdf",
        )
        import hashlib as _hashlib

        input_bytes = Path(pdf_path).read_bytes()
        input_hash = _hashlib.sha256(input_bytes).hexdigest()
        output_hash = _hashlib.sha256(pdf_bytes).hexdigest()
        changed = input_hash != output_hash
        resp.headers["X-Koto-Removed-Count"] = str(removed_count)
        resp.headers["X-Koto-Method"] = method_used
        resp.headers["X-Koto-Reason"] = (
            "supported-watermark-removed"
            if removed_count
            else "no-supported-watermark-detected"
        )
        resp.headers["X-Koto-Changed"] = "true" if changed else "false"
        resp.headers["X-Koto-Operation-Status"] = "changed" if changed else "noop"
        resp.headers["X-Koto-Input-SHA256"] = input_hash
        resp.headers["X-Koto-Output-SHA256"] = output_hash
        return resp
