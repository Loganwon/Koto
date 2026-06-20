# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_PDF_OCR_THRESHOLD = 50


def _configure_tesseract() -> bool:
    try:
        import pytesseract  # type: ignore
    except ImportError:
        return False

    from app.core.shared.system_paths import resolve_tesseract_cmd

    path = resolve_tesseract_cmd()
    if path:
        pytesseract.pytesseract.tesseract_cmd = path
        return True
    return False


def _ocr_pdf_pages(file_path: str, page_indices: list[int]) -> dict[int, str]:
    try:
        import fitz
        import pytesseract
        from PIL import Image  # type: ignore
    except ImportError as exc:
        logger.info("[PdfOCR] 依赖缺失，跳过 OCR: %s", exc)
        return {}

    if not _configure_tesseract():
        logger.warning(
            "[PdfOCR] 未找到 Tesseract 可执行文件。"
            " 请通过 TESSERACT_CMD 指定路径，或安装 Tesseract-OCR。"
        )
        return {}

    results: dict[int, str] = {}
    try:
        doc = fitz.open(file_path)
        try:
            langs = pytesseract.get_languages()
            lang = "+".join(
                lc for lc in ("chi_sim", "chi_tra", "eng") if lc in langs
            ) or "eng"
        except Exception:
            lang = "eng"

        for idx in page_indices:
            if idx >= len(doc):
                continue
            page = doc[idx]
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            try:
                text = pytesseract.image_to_string(img, lang=lang).strip()
            except pytesseract.pytesseract.TesseractError as exc:
                logger.warning("[PdfOCR] lang=%s 失败，回退 eng: %s", lang, exc)
                text = pytesseract.image_to_string(img, lang="eng").strip()
            results[idx] = text
        doc.close()
    except Exception as exc:
        logger.warning("[PdfOCR] OCR 执行失败: %s", exc)
    return results


def _flatten_pdf_outline(reader: Any, items: list, depth: int = 0) -> list:
    result = []
    for item in items:
        if isinstance(item, list):
            result.extend(_flatten_pdf_outline(reader, item, depth + 1))
        else:
            page_num = None
            try:
                page_num = reader.get_destination_page_number(item) + 1
            except Exception:
                pass
            children = _flatten_pdf_outline(
                reader,
                getattr(item, "children", []),
                depth + 1,
            )
            result.append(
                {
                    "title": str(getattr(item, "title", "") or ""),
                    "page": page_num,
                    "depth": depth,
                    "children": children,
                }
            )
    return result


def _get_pdf_meta(file_path: str) -> tuple[list, dict]:
    outline: list = []
    meta: dict = {}
    try:
        from pypdf import PdfReader as _PdfReader  # type: ignore

        reader = _PdfReader(file_path)
        if reader.metadata:
            raw_meta = reader.metadata
            meta = {
                "title": str(raw_meta.get("/Title") or ""),
                "author": str(raw_meta.get("/Author") or ""),
                "created": str(raw_meta.get("/CreationDate") or ""),
                "modified": str(raw_meta.get("/ModDate") or ""),
            }
        outline = _flatten_pdf_outline(reader, reader.outline)
    except Exception as exc:
        logger.debug("[PdfParser] 书签/元数据提取失败（非致命）: %s", exc)
    return outline, meta


def _apply_ocr_fallback(
    file_path: str,
    pages_text: list[dict[str, Any]],
    full_text_parts: list[str],
    page_count: int,
    raw_url: str,
    outline: list | None = None,
    meta: dict | None = None,
) -> dict[str, Any]:
    scanned_indices = [
        i for i, page in enumerate(pages_text)
        if len(page["text"].strip()) < _PDF_OCR_THRESHOLD
    ]
    ocr_applied = False
    if scanned_indices:
        logger.info(
            "[PdfParser] 发现 %s 页文本稀少，尝试 OCR: 页码 %s",
            len(scanned_indices),
            [i + 1 for i in scanned_indices],
        )
        ocr_results = _ocr_pdf_pages(file_path, scanned_indices)
        for idx, text in ocr_results.items():
            if text:
                pages_text[idx]["text"] = text
                full_text_parts.append(text)
                ocr_applied = True

    return {
        "text": "\n\n".join(full_text_parts),
        "page_count": page_count,
        "raw_url": raw_url,
        "pages": pages_text,
        "ocr_applied": ocr_applied,
        "outline": outline or [],
        "metadata": meta or {},
    }


def parse_pdf(file_path: str, file_id: str) -> dict[str, Any]:
    raw_url = f"/api/v1/workspace/raw/{file_id}"
    outline, meta = _get_pdf_meta(file_path)
    pages_text: list[dict[str, Any]] = []
    full_text_parts: list[str] = []
    page_count = 0

    try:
        import pdfplumber  # type: ignore

        with pdfplumber.open(file_path) as pdf:
            page_count = len(pdf.pages)
            for i, page in enumerate(pdf.pages):
                try:
                    page_text = page.extract_text() or ""
                except Exception as exc:
                    logger.warning(
                        "[PdfParser/pdfplumber] 第 %s 页文本提取失败: %s",
                        i + 1,
                        exc,
                    )
                    page_text = ""
                pages_text.append({"page": i + 1, "text": page_text})
                if page_text:
                    full_text_parts.append(page_text)

        return _apply_ocr_fallback(
            file_path,
            pages_text,
            full_text_parts,
            page_count,
            raw_url,
            outline,
            meta,
        )
    except ImportError:
        logger.info("[PdfParser] pdfplumber 未安装，尝试 pypdf/PyPDF2")
    except Exception as exc:
        logger.warning("[PdfParser] pdfplumber 解析失败: %s，尝试下一库", exc)

    for pkg_name, mod_name in [("pypdf", "pypdf"), ("PyPDF2", "PyPDF2")]:
        try:
            mod = __import__(mod_name)
            PdfReader = getattr(mod, "PdfReader")
            with open(file_path, "rb") as fh:
                reader = PdfReader(fh)
                page_count = len(reader.pages)
                for i, page in enumerate(reader.pages):
                    try:
                        page_text = page.extract_text() or ""
                    except Exception as exc:
                        logger.warning(
                            "[PdfParser/%s] 第 %s 页文本提取失败: %s",
                            pkg_name,
                            i + 1,
                            exc,
                        )
                        page_text = ""
                    pages_text.append({"page": i + 1, "text": page_text})
                    if page_text:
                        full_text_parts.append(page_text)

            return _apply_ocr_fallback(
                file_path,
                pages_text,
                full_text_parts,
                page_count,
                raw_url,
                outline,
                meta,
            )
        except ImportError:
            logger.info("[PdfParser] %s 未安装，尝试下一库", pkg_name)
            continue
        except Exception as exc:
            logger.warning("[PdfParser] %s 解析失败: %s，尝试下一库", pkg_name, exc)
            pages_text = []
            full_text_parts = []
            continue

    logger.warning(
        "[PdfParser] pdfplumber / pypdf / PyPDF2 均不可用，尝试纯 OCR。"
        " 建议执行: pip install pdfplumber"
    )
    try:
        import fitz

        doc = fitz.open(file_path)
        page_count = len(doc)
        doc.close()
    except Exception:
        page_count = 0

    if page_count:
        ocr_results = _ocr_pdf_pages(file_path, list(range(page_count)))
        for i in range(page_count):
            text = ocr_results.get(i, "")
            pages_text.append({"page": i + 1, "text": text})
            if text:
                full_text_parts.append(text)
        return {
            "text": "\n\n".join(full_text_parts),
            "page_count": page_count,
            "raw_url": raw_url,
            "pages": pages_text,
            "ocr_applied": bool(ocr_results),
            "outline": outline,
            "metadata": meta,
        }

    return {
        "text": "",
        "page_count": 0,
        "raw_url": raw_url,
        "pages": [],
        "ocr_applied": False,
        "outline": outline,
        "metadata": meta,
    }


__all__ = ["parse_pdf"]
