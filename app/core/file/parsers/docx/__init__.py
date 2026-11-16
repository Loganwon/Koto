"""DOCX parser -- componentized document parser.

Parses .docx files into structured HTML/JSON with per-component
sub-parsers for tables, images, structure, and content.
"""

from __future__ import annotations

import base64
import io
import logging
import math
import mimetypes
import os
import re
from typing import Any

from app.core.file.image_utils import compress_image_bytes as _compress_image_bytes
from app.core.file.parsers.docx_parser_fallback import (
    extract_fallback_docx_metadata as _extract_fallback_docx_metadata,
)
from app.core.file.parsers.docx_parser_fallback import (
    normalize_mammoth_heading_contract as _normalize_mammoth_heading_contract,
)
from app.core.file.parsers.docx_parser_postprocess import (
    deduplicate_images as _deduplicate_images,
)

# Re-export from sub-modules for backward compatibility
from app.core.file.parsers.docx_parser_review import (
    _extract_docx_comments,
    _extract_docx_footnotes,
    _extract_docx_revisions,
    count_docx_visible_chars,
)
from app.core.file.parsers.docx_rich_renderer import _docx_to_rich_html

from .image import _extract_images_from_paragraphs, _get_floating_image_srcs
from .structure import _unwrap_layout_tables
from .table import _extract_table_styles, _inject_table_styles

logger = logging.getLogger(__name__)
_DOCX_PREVIEW_TARGET_PAGES = 3
_DOCX_RENDER_CONTRACT_VERSION = 1


def parse_docx(file_path: str, *, progressive_preview: bool = False) -> dict[str, Any]:
    """
    将 DOCX 转换为保留完整 Word 格式的内联样式 HTML。

    首先尝试 _docx_to_rich_html()（python-docx 全格式管线）；
    若失败则回退到 mammoth 语义化管线（含后处理 Pass）。

    Returns:
        {"html": str, "messages": list[str]}

    When ``progressive_preview`` is true, only the initial preview chunk is
    rendered and the result includes ``progressive.pending`` so the frontend can
    fetch the full document in the background before enabling editing.
    """
    messages_out: list[str] = []

    # ── Primary path: rich python-docx renderer ───────────────────────────
    try:
        rich_html, sections_data, headings, preview_meta = _docx_to_rich_html(
            file_path,
            progressive_preview=progressive_preview,
        )

        # strip <style>/<script> just in case
        rich_html = re.sub(
            r"<style[^>]*>.*?</style>|<script[^>]*>.*?</script>",
            "",
            rich_html,
            flags=re.DOTALL | re.IGNORECASE,
        )

        # Unwrap single-column layout tables that have no visible borders
        try:
            rich_html = _unwrap_layout_tables(rich_html)
        except Exception as exc:
            logger.warning("[DocxParser] 布局表格展开失败 (非致命): %s", exc)

        # Deduplicate images
        try:
            rich_html = _deduplicate_images(rich_html)
        except Exception as exc:
            logger.warning("[DocxParser] 图片去重失败 (非致命): %s", exc)

        # Extract <img> from <p> tags to prevent editor path errors
        try:
            rich_html = _extract_images_from_paragraphs(rich_html)
        except Exception as exc:
            logger.warning("[DocxParser] 图片段落提取失败 (非致命): %s", exc)

        # ── Extract page dimensions for frontend page-break overlay ───
        page_meta: dict[str, Any] = {}
        try:
            if sections_data:
                _sec0 = sections_data[0]
                page_meta = {
                    "page_width_px": _sec0.get("page_width_px", 0),
                    "page_height_px": _sec0.get("page_height_px", 0),
                    "margin_top_px": _sec0.get("margin_top_px", 0),
                    "margin_bottom_px": _sec0.get("margin_bottom_px", 0),
                    "margin_left_px": _sec0.get("margin_left_px", 0),
                    "margin_right_px": _sec0.get("margin_right_px", 0),
                    "doc_grid": _sec0.get("doc_grid", {}),
                    "header_html": _sec0.get("header_html", ""),
                    "footer_html": _sec0.get("footer_html", ""),
                }
                page_meta["sections"] = sections_data
        except Exception as meta_exc:
            logger.debug("[DocxParser] 页面元数据提取失败 (非致命): %s", meta_exc)

        result = {
            "html": rich_html,
            "messages": messages_out,
            "headings": headings,
            "render_contract_version": _DOCX_RENDER_CONTRACT_VERSION,
            "render_source": "rich",
            "render_degraded": False,
        }
        result.update(page_meta)
        if progressive_preview:
            result["progressive"] = {
                "pending": bool(preview_meta.get("pending")),
                "target_pages": preview_meta.get("target_pages")
                or _DOCX_PREVIEW_TARGET_PAGES,
            }
        # ── 提取 DOCX 批注 ──────────────────────────────────────────
        try:
            comments = _extract_docx_comments(file_path)
            if comments:
                result["comments"] = comments
        except Exception:
            pass
        try:
            proposals = _extract_docx_revisions(file_path)
            if proposals:
                result["proposals"] = proposals
        except Exception:
            pass
        try:
            footnotes = _extract_docx_footnotes(file_path)
            if footnotes:
                result["footnotes"] = footnotes
                result["footnote_reference_count"] = sum(
                    int(note.get("reference_count") or 0)
                    for note in footnotes
                    if isinstance(note, dict)
                )
        except Exception:
            pass
        return result

    except Exception as primary_exc:
        logger.warning("[DocxParser] 富格式渲染失败，回退到 mammoth: %s", primary_exc)

    # ── Fallback path: mammoth semantic renderer ──────────────────────────
    try:
        import mammoth
    except ImportError:
        raise RuntimeError(
            "python-docx 和 mammoth 均未安装，请执行: pip install python-docx mammoth"
        )

    def _img_handler(image: Any) -> dict[str, str]:
        """将图片转换为内联 base64 data URI，自动压缩大图。"""
        try:
            with image.open() as f:
                img_bytes = f.read()
            content_type = image.content_type or "image/png"
            img_bytes, content_type = _compress_image_bytes(img_bytes, content_type)
            b64 = base64.b64encode(img_bytes).decode("ascii")
            return {"src": f"data:{content_type};base64,{b64}"}
        except Exception as e:
            logger.warning(f"[DocxParser] 图片内联失败: {e}")
            return {"src": ""}

    try:
        with open(file_path, "rb") as f:
            result = mammoth.convert_to_html(
                f,
                convert_image=mammoth.images.img_element(_img_handler),
            )
        for msg in result.messages:
            messages_out.append(str(msg))

        clean_html = re.sub(
            r"<style[^>]*>.*?</style>|<script[^>]*>.*?</script>",
            "",
            result.value,
            flags=re.DOTALL | re.IGNORECASE,
        )
        clean_html = re.sub(
            r"(<p[^>]*>)(?:(?:body|h[1-6]|blockquote|strong|em|code|pre|table|td|th|ul|ol|li)\s*\{[^{}]*\})+",
            r"\1",
            clean_html,
            flags=re.IGNORECASE,
        )
        clean_html = re.sub(r"<p[^>]*>\s*</p>", "", clean_html)

        try:
            tbl_styles = _extract_table_styles(file_path)
            clean_html = _inject_table_styles(clean_html, tbl_styles)
        except Exception as exc:
            logger.warning("[DocxParser] 表格样式注入失败 (非致命): %s", exc)

        try:
            clean_html = _unwrap_layout_tables(clean_html)
        except Exception as exc:
            logger.warning("[DocxParser] 布局表格展开失败 (非致命): %s", exc)

        try:
            floating_srcs = _get_floating_image_srcs(file_path)
            if floating_srcs:
                imgs_html = "".join(
                    f'<img src="{src}" '
                    'style="float:right;max-width:28%;max-height:180px;'
                    'margin:0 0 10px 14px;object-fit:contain;border-radius:2px;" '
                    'alt="" />'
                    for src in floating_srcs
                )
                first_block = re.search(
                    r"<(?:p|h[1-6]|table|ul|ol|blockquote)\b", clean_html
                )
                if first_block:
                    clean_html = (
                        clean_html[: first_block.start()]
                        + imgs_html
                        + clean_html[first_block.start() :]
                    )
                else:
                    clean_html = imgs_html + clean_html
        except Exception as exc:
            logger.warning("[DocxParser] 浮动图片注入失败 (非致命): %s", exc)

        try:
            clean_html = _deduplicate_images(clean_html)
        except Exception as exc:
            logger.warning("[DocxParser] 图片去重失败 (非致命): %s", exc)

        clean_html, headings = _normalize_mammoth_heading_contract(clean_html)
        fallback_metadata = _extract_fallback_docx_metadata(file_path)
        fallback_result = {
            "html": clean_html,
            "messages": [
                *messages_out,
                "文档以兼容渲染模式打开；复杂版式可能与原始 Word 存在差异。",
            ],
            "headings": headings,
            "progressive": {
                "pending": False,
                "target_pages": (
                    _DOCX_PREVIEW_TARGET_PAGES if progressive_preview else None
                ),
            },
            "render_contract_version": _DOCX_RENDER_CONTRACT_VERSION,
            "render_source": "mammoth_fallback",
            "render_degraded": True,
            **fallback_metadata,
        }
        try:
            comments = _extract_docx_comments(file_path)
            if comments:
                fallback_result["comments"] = comments
        except Exception:
            pass
        try:
            proposals = _extract_docx_revisions(file_path)
            if proposals:
                fallback_result["proposals"] = proposals
        except Exception:
            pass
        try:
            footnotes = _extract_docx_footnotes(file_path)
            if footnotes:
                fallback_result["footnotes"] = footnotes
                fallback_result["footnote_reference_count"] = sum(
                    int(note.get("reference_count") or 0)
                    for note in footnotes
                    if isinstance(note, dict)
                )
        except Exception:
            pass
        return fallback_result
    except Exception as e:
        logger.error(f"[DocxParser] 解析失败: {e}")
        raise


# ─────────────────────────────────────────────────────────────────────────────
# XLSX → Univer Sheets IWorkbookData JSON
# ─────────────────────────────────────────────────────────────────────────────

__all__ = [
    "count_docx_visible_chars",
    "parse_docx",
    "_extract_docx_comments",
    "_extract_docx_revisions",
    "_extract_docx_footnotes",
]
