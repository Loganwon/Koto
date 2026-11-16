# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""High-fidelity OOXML-to-HTML renderer used by the DOCX parser facade."""

from __future__ import annotations

import html
import logging
import math
import re
from typing import Any

logger = logging.getLogger(__name__)
_DOCX_PREVIEW_TARGET_PAGES = 3
_DOCX_PREVIEW_UNITS_PER_PAGE = 34
_DOCX_PREVIEW_MAX_TABLE_ROWS = 18
from app.core.file.parsers.docx_numbering import resolve_paragraph_numbering
from app.core.file.parsers.docx_rich_inline_renderer import build_inline_renderers
from app.core.file.parsers.docx_rich_paragraph_semantics import (
    build_paragraph_semantics,
)
from app.core.file.parsers.docx_rich_renderer_helpers import (
    _estimate_paragraph_units,
    _resolve_para_style_ref,
    _twips_to_pt,
)


def _docx_to_rich_html(
    file_path: str, *, progressive_preview: bool = False
) -> tuple[str, list[dict], list[dict], dict[str, Any]]:
    """
    将 DOCX 转换为保留完整 Word 格式的内联样式 HTML。

    使用 python-docx 直接读取 OOXML，提取:
      - 段落对齐/缩进/行距/段前段后
      - 标题级别 (Heading 1-6 / 标题 1-6) → <h1>-<h6>
      - 行内字体名称、大小、颜色、粗体、斜体、下划线、删除线、上下标
      - 超链接 → <a href="...">
      - 有序/无序列表 → <ol>/<ul> 按 numId 分组
      - 表格: 列宽、合并单元格、边框、单元格背景色、垂直对齐
      - 内联图片 (wp:inline) 和浮动图片 (wp:anchor) → base64 <img>
      - 页眉/页脚 → <div class="koto-header">/<div class="koto-footer">
    """
    try:
        from docx import Document
        from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml.ns import qn
        from docx.shared import Pt, RGBColor
    except ImportError:
        raise RuntimeError("python-docx 未安装，请执行: pip install python-docx")
    _HEADING_MAP: dict[str, str] = {
        "heading 1": "h1",
        "heading 2": "h2",
        "heading 3": "h3",
        "heading 4": "h4",
        "heading 5": "h5",
        "heading 6": "h6",
        "heading1": "h1",
        "heading2": "h2",
        "heading3": "h3",
        "heading4": "h4",
        "heading5": "h5",
        "heading6": "h6",
        "标题 1": "h1",
        "标题 2": "h2",
        "标题 3": "h3",
        "标题 4": "h4",
        "标题 5": "h5",
        "标题 6": "h6",
        "标题1": "h1",
        "标题2": "h2",
        "标题3": "h3",
        "标题4": "h4",
        "标题5": "h5",
        "标题6": "h6",
        "一级标题": "h1",
        "二级标题": "h2",
        "三级标题": "h3",
        "subheading 1": "h2",
        "subheading 2": "h3",
    }
    _VISUAL_TITLE_STYLE_KEYS: set[str] = {
        "title",
        "subtitle",
        "标题",
        "副标题",
        "封面标题",
        "封面副标题",
    }
    _HEADING_TYPOGRAPHY_FALLBACKS: dict[str, dict[str, str]] = {
        "h1": {"font-size": "16.0pt", "font-weight": "bold"},
        "h2": {"font-size": "14.0pt", "font-weight": "bold"},
        "h3": {"font-size": "12.0pt", "font-weight": "bold"},
        "h4": {"font-size": "11.0pt", "font-weight": "bold"},
        "h5": {"font-size": "10.5pt", "font-weight": "bold"},
        "h6": {"font-size": "10.5pt", "font-weight": "bold"},
    }
    _ALIGN_MAP = {
        WD_ALIGN_PARAGRAPH.LEFT: "left",
        WD_ALIGN_PARAGRAPH.CENTER: "center",
        WD_ALIGN_PARAGRAPH.RIGHT: "right",
        WD_ALIGN_PARAGRAPH.JUSTIFY: "justify",
        WD_ALIGN_PARAGRAPH.DISTRIBUTE: "justify",
    }
    _CN_FONT_MAP_P: dict[str, str] = {
        "黑体": "SimHei",
        "宋体": "SimSun",
        "楷体": "KaiTi",
        "仿宋": "FangSong",
        "微软雅黑": "Microsoft YaHei",
        "华文中宋": "STZhongsong",
        "华文宋体": "STSong",
        "华文黑体": "STHeiti",
        "华文楷体": "STKaiti",
        "华文仿宋": "STFangsong",
        "方正书宋": "FZShuSong-Z01",
        "方正黑体": "FZHei-B01",
    }
    _CN_FONT_EQUIVALENTS: dict[str, tuple[str, ...]] = {}
    for _cn_name, _ascii_name in _CN_FONT_MAP_P.items():
        _CN_FONT_EQUIVALENTS[_cn_name] = (_cn_name, _ascii_name)
        _CN_FONT_EQUIVALENTS[_ascii_name] = (_cn_name, _ascii_name)
    _EMPTY_STYLE_DEFAULTS: dict[str, Any] = {
        "style_name": "",
        "style_id": "",
        "text_align": None,
        "space_before": None,
        "space_after": None,
        "line_height": None,
        "line_spacing_rule": None,
        "line_spacing_twips": None,
        "font_size": None,
        "font_family": None,
        "first_line_indent_twips": None,
        "left_indent_twips": None,
        "keep_with_next": None,
        "keep_together": None,
        "page_break_before": None,
        "widow_control": None,
    }
    _style_defaults_cache: dict[object, dict[str, Any]] = {}
    _heading_manifest: list[dict[str, Any]] = []
    _generated_heading_id_counts: dict[str, int] = {}

    (
        _rgb_to_hex,
        _build_css_font_family_stack,
        _is_heading_style_key,
        _is_visual_title_style_key,
        _style_chain_has_visual_title,
        _style_chain_has_heading,
        _apply_heading_typography_fallback,
        _p_elem_has_toc_anchor,
        _p_elem_has_toc_field,
        _p_elem_text_content,
        _find_bookmark_id,
        _make_generated_heading_anchor,
        _resolve_body_heading_anchor,
        _record_body_heading,
        _should_emit_heading_manifest_entry,
        _p_elem_looks_like_toc_line,
        _should_promote_outline_heading,
        _classify_paragraph_block,
        _line_spacing_to_css,
        _read_on_off_prop,
        _read_paragraph_layout_props_from_ppr,
        _read_bold_state_from_rpr,
        _read_rpr_font_props,
        _resolve_style_defaults,
        _extract_paragraph_layout_semantics,
        _paragraph_layout_data_attrs,
        _detect_toc_info,
        _detect_outline_level,
    ) = build_paragraph_semantics(
        {
            "RGBColor": RGBColor,
            "qn": qn,
            "align_map": _ALIGN_MAP,
            "cn_font_equivalents": _CN_FONT_EQUIVALENTS,
            "empty_style_defaults": _EMPTY_STYLE_DEFAULTS,
            "heading_map": _HEADING_MAP,
            "heading_typography_fallbacks": _HEADING_TYPOGRAPHY_FALLBACKS,
            "visual_title_style_keys": _VISUAL_TITLE_STYLE_KEYS,
            "generated_heading_id_counts": _generated_heading_id_counts,
            "heading_manifest": _heading_manifest,
            "style_defaults_cache": _style_defaults_cache,
        }
    )

    (
        _color_from_xml,
        _encode_image_part,
        _inline_img_html,
        _anchor_img_html,
        _run_html,
        _render_inline_hyperlink_html,
        _render_docx_revision_html,
        _render_inline_children_html,
    ) = build_inline_renderers(
        {
            "qn": qn,
            "build_css_font_family_stack": _build_css_font_family_stack,
            "detect_toc_info": _detect_toc_info,
            "read_bold_state_from_rpr": _read_bold_state_from_rpr,
        }
    )

    def _para_style(para, style_ref=None) -> dict[str, str]:
        """Extract paragraph CSS properties as a dict."""
        css: dict[str, str] = {}
        pf = para.paragraph_format
        _p_pPr = None
        _para_rpr_props = _read_rpr_font_props(None)
        try:
            _p_pPr = para._element.find(qn("w:pPr"))
            if _p_pPr is not None:
                _para_rpr_props = _read_rpr_font_props(_p_pPr.find(qn("w:rPr")))
        except Exception:
            _p_pPr = None
            _para_rpr_props = _read_rpr_font_props(None)
        _style_defaults = _resolve_style_defaults(
            style_ref if style_ref is not None else _resolve_para_style_ref(para)
        )
        _align_val = None
        try:
            if _p_pPr is not None:
                _p_jc = _p_pPr.find(qn("w:jc"))
                if _p_jc is not None:
                    _align_val = _p_jc.get(qn("w:val"), "")
        except Exception:
            pass
        if not _align_val:
            _sr = style_ref if style_ref is not None else _resolve_para_style_ref(para)
            if _sr is not None and hasattr(_sr, "_element"):
                try:
                    _st_pPr = _sr._element.find(qn("w:pPr"))
                    if _st_pPr is not None:
                        _st_jc = _st_pPr.find(qn("w:jc"))
                        if _st_jc is not None:
                            _align_val = _st_jc.get(qn("w:val"), "")
                except Exception:
                    pass
        if _align_val in ("center", "right", "justify", "distribute"):
            css["text-align"] = "justify" if _align_val == "distribute" else _align_val

        def _resolve_spacing(attr_name):
            """Return pt value or None, walking paragraph → style → base_style chain."""
            try:
                val = getattr(pf, attr_name)
                if val is not None:
                    return _twips_to_pt(val.twips)
            except Exception:
                pass
            return _style_defaults.get(attr_name)

        sb = _resolve_spacing("space_before")
        sa = _resolve_spacing("space_after")
        if sb is not None:
            css["margin-top"] = f"{sb}pt"
        if sa is not None:
            css["margin-bottom"] = f"{sa}pt"
        _line_height = None
        try:
            _line_height = _line_spacing_to_css(pf.line_spacing, pf.line_spacing_rule)
        except Exception:
            pass
        if _line_height is None:
            _line_height = _style_defaults.get("line_height")
        if _line_height is not None:
            css["line-height"] = _line_height
        _fs = _para_rpr_props.get("font_size")
        if _fs is None:
            _fs = _style_defaults.get("font_size")
        if _fs is not None:
            css["font-size"] = f"{_fs}pt"
        _ff = _para_rpr_props.get("font_family") or _style_defaults.get("font_family")
        if _ff:
            css["font-family"] = _ff
        _fw = None
        if (
            _para_rpr_props.get("font_weight_set")
            and _para_rpr_props.get("font_weight") == "normal"
        ):
            _fw = "normal"
        _direct_sr = (
            style_ref if style_ref is not None else _resolve_para_style_ref(para)
        )
        if _fw is None and _direct_sr is not None:
            _direct_rpr_props = _read_rpr_font_props(None)
            try:
                if hasattr(_direct_sr, "_element"):
                    _direct_rpr_props = _read_rpr_font_props(
                        _direct_sr._element.find(qn("w:rPr"))
                    )
            except Exception:
                _direct_rpr_props = _read_rpr_font_props(None)
            if _direct_rpr_props.get("font_weight_set"):
                _fw = _direct_rpr_props.get("font_weight")
            if _fw is None:
                try:
                    _direct_bold = _direct_sr.font.bold
                    if _direct_bold is True:
                        _fw = "bold"
                    elif _direct_bold is False:
                        _fw = "normal"
                except Exception:
                    pass
        if _fw:
            css["font-weight"] = _fw
        _fi = None
        if (
            _para_rpr_props.get("font_style_set")
            and _para_rpr_props.get("font_style") == "normal"
        ):
            _fi = "normal"
        _direct_sr_fi = (
            style_ref if style_ref is not None else _resolve_para_style_ref(para)
        )
        if _fi is None and _direct_sr_fi is not None:
            _direct_rpr_props = _read_rpr_font_props(None)
            try:
                if hasattr(_direct_sr_fi, "_element"):
                    _direct_rpr_props = _read_rpr_font_props(
                        _direct_sr_fi._element.find(qn("w:rPr"))
                    )
            except Exception:
                _direct_rpr_props = _read_rpr_font_props(None)
            if _direct_rpr_props.get("font_style_set"):
                _fi = _direct_rpr_props.get("font_style")
            if _fi is None:
                try:
                    _direct_italic = _direct_sr_fi.font.italic
                    if _direct_italic is True:
                        _fi = "italic"
                    elif _direct_italic is False:
                        _fi = "normal"
                except Exception:
                    pass
        if _fi:
            css["font-style"] = _fi
        try:
            fli = pf.first_line_indent
            if fli is not None and fli != 0:
                pt_val = _twips_to_pt(fli.twips)
                if pt_val is not None:
                    css["text-indent"] = f"{pt_val}pt"
        except Exception:
            pass
        try:
            li = pf.left_indent
            if li is not None and li != 0:
                pt_val = _twips_to_pt(li.twips)
                if pt_val is not None:
                    css["padding-left"] = f"{pt_val}pt"
        except Exception:
            pass
        return css

    def _para_html(
        para,
        doc,
        tag: str = "p",
        style_ref=None,
        anchor_id: str | None = None,
        extra_class: str | None = None,
        extra_role: str | None = None,
        active_comment_ids: list[str] | None = None,
    ) -> str:
        """Render a paragraph to an HTML block element."""
        style_ref = (
            style_ref if style_ref is not None else _resolve_para_style_ref(para)
        )
        css = _para_style(para, style_ref=style_ref)
        layout_attrs = _paragraph_layout_data_attrs(para, style_ref=style_ref)
        bm_id = (anchor_id or _find_bookmark_id(para._element) or "").strip() or None
        toc_class = ""
        _is_toc, _toc_level = _detect_toc_info(
            para=para, p_el=para._element, style_ref=style_ref
        )
        if _is_toc:
            toc_class = f"koto-toc-{_toc_level}"
        inner = _render_inline_children_html(
            para._element,
            para,
            doc,
            toc_class=toc_class,
            active_comment_ids=active_comment_ids,
        )
        if not inner.strip():
            inner = "<br/>"
        _apply_heading_typography_fallback(tag, css, inner)
        style_str = ";".join((f"{k}:{v}" for k, v in css.items()))
        if toc_class:
            _skip = {
                "font-size",
                "font-weight",
                "line-height",
                "margin-top",
                "margin-bottom",
                "display",
                "align-items",
            }
            toc_parts = [p for p in css.items() if p[0] not in _skip]
            style_str = "display:flex;align-items:baseline;" + ";".join(
                (f"{k}:{v}" for k, v in toc_parts)
            )
        style_attr = f' style="{style_str}"' if style_str else ""
        id_attr = f' id="{bm_id}"' if bm_id else ""
        role_attr = f' data-koto-role="{extra_role}"' if extra_role else ""
        layout_attr = "".join(
            (
                f' {attr_name}="{html.escape(str(attr_value), quote=True)}"'
                for attr_name, attr_value in layout_attrs.items()
            )
        )
        _class_tokens: list[str] = []
        if toc_class:
            _class_tokens.extend((tok for tok in toc_class.split() if tok))
        if extra_class:
            _class_tokens.extend((tok for tok in str(extra_class).split() if tok))
        if _class_tokens:
            _class_tokens = list(dict.fromkeys(_class_tokens))
        class_attr = f''' class="{' '.join(_class_tokens)}"''' if _class_tokens else ""
        return f"<{tag}{id_attr}{class_attr}{role_attr}{layout_attr}{style_attr}>{inner}</{tag}>"

    def _table_has_visible_borders(tbl_elem) -> bool:
        """Check if a table has any non-nil visible border in w:tblBorders or its table style."""
        tblPr = tbl_elem.find(qn("w:tblPr"))
        if tblPr is None:
            return False
        tblBorders = tblPr.find(qn("w:tblBorders"))
        if tblBorders is not None:
            border_tags = [
                "w:top",
                "w:left",
                "w:bottom",
                "w:right",
                "w:insideH",
                "w:insideV",
            ]
            for bt in border_tags:
                b_elem = tblBorders.find(qn(bt))
                if b_elem is not None:
                    val = b_elem.get(qn("w:val"), "none")
                    if val not in ("none", "nil", ""):
                        return True
        tblStyle_el = tblPr.find(qn("w:tblStyle"))
        if tblStyle_el is not None:
            return True
        return False

    def _border_elem_to_css(b_el) -> str:
        """Convert a single w:top/w:left/etc. border element to a CSS border value.
        Returns 'none' if explicitly disabled, or a string like '0.5pt solid #000'.
        Returns '' (empty) if the element is missing (meaning: no explicit override).
        """
        if b_el is None:
            return ""
        val = b_el.get(qn("w:val"), "none")
        if val in ("none", "nil", ""):
            return "none"
        sz = b_el.get(qn("w:sz"), "4")
        clr = b_el.get(qn("w:color"), "auto")
        try:
            sz_pt = round(int(sz) / 8, 2)
        except (TypeError, ValueError):
            sz_pt = 0.5
        clr_css = f"#{clr}" if clr and clr.lower() != "auto" else "#000"
        return f"{sz_pt}pt solid {clr_css}"

    def _get_table_border_defaults(tbl_elem) -> dict:
        """Extract table-level border defaults from w:tblBorders.

        Returns a dict with keys: top, bottom, left, right, insideH, insideV.
        Each value is a CSS border string like '0.5pt solid #000', 'none',
        or None when the element is absent.
        """
        defaults = {
            "top": None,
            "bottom": None,
            "left": None,
            "right": None,
            "insideH": None,
            "insideV": None,
        }
        tblPr = tbl_elem.find(qn("w:tblPr"))
        if tblPr is None:
            return defaults
        tblBorders = tblPr.find(qn("w:tblBorders"))
        if tblBorders is None:
            return defaults
        for key, wtag in (
            ("top", "w:top"),
            ("bottom", "w:bottom"),
            ("left", "w:left"),
            ("right", "w:right"),
            ("insideH", "w:insideH"),
            ("insideV", "w:insideV"),
        ):
            b_el = tblBorders.find(qn(wtag))
            css = _border_elem_to_css(b_el)
            if css != "":
                defaults[key] = css
        return defaults

    def _get_tblStyle_border_defaults(tbl_elem, doc) -> dict:
        """Look up the table's referenced style (w:tblStyle) and return its
        tblBorders as a border-defaults dict (same format as _get_table_border_defaults).
        Returns all-None dict if no style, no borders, or any error.
        """
        defaults = {
            "top": None,
            "bottom": None,
            "left": None,
            "right": None,
            "insideH": None,
            "insideV": None,
        }
        try:
            tblPr = tbl_elem.find(qn("w:tblPr"))
            if tblPr is None:
                return defaults
            tblStyle_el = tblPr.find(qn("w:tblStyle"))
            if tblStyle_el is None:
                return defaults
            style_id = tblStyle_el.get(qn("w:val"))
            if not style_id or doc is None:
                return defaults
            target_style = None
            for st in doc.styles:
                if st.style_id == style_id:
                    target_style = st
                    break
            if target_style is None:
                return defaults
            style_tblBorders = target_style._element.find(".//" + qn("w:tblBorders"))
            if style_tblBorders is None:
                return defaults
            for key, wtag in (
                ("top", "w:top"),
                ("bottom", "w:bottom"),
                ("left", "w:left"),
                ("right", "w:right"),
                ("insideH", "w:insideH"),
                ("insideV", "w:insideV"),
            ):
                b_el = style_tblBorders.find(qn(wtag))
                css = _border_elem_to_css(b_el)
                if css != "":
                    defaults[key] = css
        except Exception:
            pass
        return defaults

    def _table_html(
        tbl,
        doc,
        *,
        max_rows: int | None = None,
        active_comment_ids: list[str] | None = None,
    ) -> str:
        """Render a docx Table to an HTML <table>."""
        tbl_elem = tbl._tbl
        has_borders = _table_has_visible_borders(tbl_elem)
        tblGrid = tbl_elem.find(qn("w:tblGrid"))
        col_widths_twips: list[int] = []
        if tblGrid is not None:
            for gc in tblGrid.findall(qn("w:gridCol")):
                w_val = gc.get(qn("w:w"))
                try:
                    col_widths_twips.append(int(w_val))
                except (TypeError, ValueError):
                    col_widths_twips.append(0)
        total_w = sum(col_widths_twips) or 1
        tbl_border_defs = _get_table_border_defaults(tbl_elem)
        if all((v is None for v in tbl_border_defs.values())):
            style_borders = _get_tblStyle_border_defaults(tbl_elem, doc)
            if any((v is not None for v in style_borders.values())):
                tbl_border_defs = style_borders
        all_row_elems = tbl_elem.findall(qn("w:tr"))
        table_is_truncated = bool(max_rows and len(all_row_elems) > max_rows)
        render_row_elems = (
            all_row_elems[:max_rows] if table_is_truncated else all_row_elems
        )
        num_rows = len(render_row_elems)
        num_cols_grid = len(col_widths_twips) or 1
        col_widths_px: list[int] = (
            [max(1, round(t / 15)) for t in col_widths_twips]
            if col_widths_twips
            else []
        )
        _WORD_DEFAULT_CELL_MAR = {"top": 0.0, "bottom": 0.0, "left": 5.4, "right": 5.4}
        _tbl_cell_mar: dict[str, float] = dict(_WORD_DEFAULT_CELL_MAR)
        _tblPr = tbl_elem.find(qn("w:tblPr"))
        if _tblPr is not None:
            _tblCellMar = _tblPr.find(qn("w:tblCellMar"))
            if _tblCellMar is not None:
                for _side in ("top", "bottom", "left", "right"):
                    _el = _tblCellMar.find(qn(f"w:{_side}"))
                    if _el is None and _side == "left":
                        _el = _tblCellMar.find(qn("w:start"))
                    if _el is None and _side == "right":
                        _el = _tblCellMar.find(qn("w:end"))
                    if _el is not None:
                        try:
                            _tbl_cell_mar[_side] = round(
                                int(_el.get(qn("w:w"), 0)) / 20, 2
                            )
                        except (TypeError, ValueError):
                            pass
        parts: list[str] = ["<table"]
        parts.append(
            ' class="koto-docx-table" style="border-collapse:collapse;width:100%;">'
        )
        if col_widths_twips:
            parts.append("<colgroup>")
            for w_twips in col_widths_twips:
                pct = round(w_twips / total_w * 100, 2)
                parts.append(f'<col style="width:{pct}%">')
            parts.append("</colgroup>")
        for ri, row_elem in enumerate(render_row_elems):
            row_h_rule = None
            row_h = None
            try:
                trPr = row_elem.find(qn("w:trPr"))
                if trPr is not None:
                    trH = trPr.find(qn("w:trHeight"))
                    if trH is not None:
                        row_h = trH.get(qn("w:val"))
                        row_h_rule = trH.get(qn("w:hRule"), "auto")
            except Exception:
                pass
            row_style = ""
            if row_h and row_h_rule == "exact":
                try:
                    h_pt = _twips_to_pt(int(row_h))
                    row_style = f' data-koto-row-height="{h_pt}pt"'
                except Exception:
                    pass
            parts.append(f"<tr{row_style}>")
            tc_elems = row_elem.findall(qn("w:tc"))
            for ci, cell_elem in enumerate(tc_elems):
                tcPr = cell_elem.find(qn("w:tcPr"))
                vmerge = tcPr.find(qn("w:vMerge")) if tcPr is not None else None
                if vmerge is not None and vmerge.get(qn("w:val")) != "restart":
                    continue
                colspan = 1
                rowspan = 1
                cell_style_parts: list[str] = []
                if tcPr is not None:
                    gs = tcPr.find(qn("w:gridSpan"))
                    if gs is not None:
                        try:
                            colspan = int(gs.get(qn("w:val"), 1))
                        except (TypeError, ValueError):
                            colspan = 1
                    try:
                        col_idx_in_grid = 0
                        for prev_tc in tc_elems:
                            if prev_tc is cell_elem:
                                break
                            prev_gs_elem = prev_tc.find(
                                qn("w:tcPr") + "/" + qn("w:gridSpan")
                            )
                            if prev_gs_elem is not None:
                                try:
                                    col_idx_in_grid += int(
                                        prev_gs_elem.get(qn("w:val"), 1)
                                    )
                                except (TypeError, ValueError):
                                    col_idx_in_grid += 1
                            else:
                                col_idx_in_grid += 1
                        for next_row_elem in render_row_elems[ri + 1 :]:
                            next_cells = next_row_elem.findall(qn("w:tc"))
                            target_ci = 0
                            found_continue = False
                            for nc in next_cells:
                                if target_ci == col_idx_in_grid:
                                    nc_vmerge = nc.find(
                                        qn("w:tcPr") + "/" + qn("w:vMerge")
                                    )
                                    if (
                                        nc_vmerge is not None
                                        and nc_vmerge.get(qn("w:val")) != "restart"
                                    ):
                                        rowspan += 1
                                        found_continue = True
                                    break
                                nc_gs = nc.find(qn("w:tcPr") + "/" + qn("w:gridSpan"))
                                try:
                                    target_ci += (
                                        int(nc_gs.get(qn("w:val"), 1))
                                        if nc_gs is not None
                                        else 1
                                    )
                                except (TypeError, ValueError):
                                    target_ci += 1
                            if not found_continue:
                                break
                    except Exception:
                        pass
                    shd = tcPr.find(qn("w:shd"))
                    if shd is not None:
                        fill = shd.get(qn("w:fill"), "")
                        if fill and fill.upper() not in ("AUTO", "FFFFFF", ""):
                            cell_style_parts.append(f"background-color:#{fill}")
                    tcW = tcPr.find(qn("w:tcW"))
                    if tcW is not None:
                        w_val = tcW.get(qn("w:w"))
                        w_type = tcW.get(qn("w:type"), "dxa")
                        try:
                            if w_type == "pct" and w_val:
                                pct = round(int(w_val) / 5000 * 100, 2)
                                cell_style_parts.append(f"width:{pct}%")
                            elif w_type == "dxa" and w_val and (total_w > 1):
                                pct = round(int(w_val) / total_w * 100, 2)
                                cell_style_parts.append(f"width:{pct}%")
                        except (TypeError, ValueError):
                            pass
                    vAlign = tcPr.find(qn("w:vAlign"))
                    if vAlign is not None:
                        v_val = vAlign.get(qn("w:val"), "")
                        _VA_MAP = {"top": "top", "center": "middle", "bottom": "bottom"}
                        va_css = _VA_MAP.get(v_val)
                        if va_css:
                            cell_style_parts.append(f"vertical-align:{va_css}")
                tcBorders = tcPr.find(qn("w:tcBorders")) if tcPr is not None else None
                try:
                    _cell_grid_col = 0
                    for _prev in tc_elems:
                        if _prev is cell_elem:
                            break
                        _prev_gs = _prev.find(qn("w:tcPr") + "/" + qn("w:gridSpan"))
                        _cell_grid_col += (
                            int(_prev_gs.get(qn("w:val"), 1))
                            if _prev_gs is not None
                            else 1
                        )
                    _cell_grid_end_col = _cell_grid_col + colspan - 1
                except Exception:
                    _cell_grid_col = ci
                    _cell_grid_end_col = ci
                _is_first_row = ri == 0
                _is_last_row = ri == num_rows - 1
                _is_first_col = _cell_grid_col == 0
                _is_last_col = _cell_grid_end_col >= num_cols_grid - 1
                _side_map = {
                    "top": ("w:top", "insideH" if not _is_first_row else "top"),
                    "bottom": ("w:bottom", "insideH" if not _is_last_row else "bottom"),
                    "left": ("w:left", "insideV" if not _is_first_col else "left"),
                    "right": ("w:right", "insideV" if not _is_last_col else "right"),
                }
                _border_css_values: list[str] = []
                for side, (wtag, tbl_def_key) in _side_map.items():
                    cell_b = None
                    if tcBorders is not None:
                        cell_b = _border_elem_to_css(tcBorders.find(qn(wtag)))
                    if cell_b is None or cell_b == "":
                        cell_b = tbl_border_defs.get(tbl_def_key)
                    if cell_b:
                        _border_css_values.append(cell_b)
                        cell_style_parts.append(f"border-{side}:{cell_b}")
                    else:
                        _border_css_values.append("none")
                        cell_style_parts.append(f"border-{side}:none")
                _cell_pad = dict(_tbl_cell_mar)
                _tcMar = tcPr.find(qn("w:tcMar")) if tcPr is not None else None
                if _tcMar is not None:
                    for _side in ("top", "bottom", "left", "right"):
                        _el = _tcMar.find(qn(f"w:{_side}"))
                        if _el is None and _side == "left":
                            _el = _tcMar.find(qn("w:start"))
                        if _el is None and _side == "right":
                            _el = _tcMar.find(qn("w:end"))
                        if _el is not None:
                            try:
                                _cell_pad[_side] = round(
                                    int(_el.get(qn("w:w"), 0)) / 20, 2
                                )
                            except (TypeError, ValueError):
                                pass
                _pt = _cell_pad["top"]
                _pb = _cell_pad["bottom"]
                _pl = _cell_pad["left"]
                _pr = _cell_pad["right"]
                if _pt == _pb == 0 and _pl == _pr:
                    cell_style_parts.append(f"padding:0 {_pr}pt")
                elif _pt == _pb and _pl == _pr:
                    cell_style_parts.append(f"padding:{_pt}pt {_pr}pt")
                else:
                    cell_style_parts.append(f"padding:{_pt}pt {_pr}pt {_pb}pt {_pl}pt")
                cell_style = ";".join(cell_style_parts)
                td_attrs = f' style="{cell_style}"'
                if _border_css_values and all(
                    (_val.strip().lower() == "none" for _val in _border_css_values)
                ):
                    td_attrs += ' data-koto-borderless-cell="true"'
                if colspan > 1:
                    td_attrs += f' colspan="{colspan}"'
                if rowspan > 1:
                    td_attrs += f' rowspan="{rowspan}"'
                if col_widths_px:
                    try:
                        _cw_start = 0
                        for _prev in tc_elems:
                            if _prev is cell_elem:
                                break
                            _prev_gs = _prev.find(qn("w:tcPr") + "/" + qn("w:gridSpan"))
                            _cw_start += (
                                int(_prev_gs.get(qn("w:val"), 1))
                                if _prev_gs is not None
                                else 1
                            )
                        _cw_vals = col_widths_px[_cw_start : _cw_start + colspan]
                        if _cw_vals:
                            td_attrs += f''' data-colwidth="{','.join((str(v) for v in _cw_vals))}"'''
                    except Exception:
                        pass
                cell_inner: list[str] = []
                for p_elem in cell_elem.findall(qn("w:p")):
                    from docx.text.paragraph import Paragraph as _Paragraph

                    cell_para = _Paragraph(p_elem, doc)
                    cell_inner.append(
                        _para_html(
                            cell_para, doc, "p", active_comment_ids=active_comment_ids
                        )
                    )
                if not cell_inner:
                    cell_inner = ["<p></p>"]
                parts.append(f"<td{td_attrs}>{''.join(cell_inner)}</td>")
            parts.append("</tr>")
        if table_is_truncated:
            remaining_rows = max(0, len(all_row_elems) - len(render_row_elems))
            parts.append(
                f'<tr data-koto-preview-more="true"><td colspan="{num_cols_grid}" style="padding:6pt 5.4pt;border-top:1px dashed #aeb7c6;border-bottom:none;border-left:none;border-right:none;background:#f6f8fb;color:#5f6b7a;font-style:italic;">表格其余 {remaining_rows} 行正在后台加载…</td></tr>'
            )
        parts.append("</table>")
        return "".join(parts)

    def _section_html(section_obj, doc, cls: str) -> str:
        """Render a header or footer to HTML.

        Handles:
        - Multi-paragraph headers/footers
        - Tab-based left/center/right alignment converted to flex layout
        - PAGE/NUMPAGES field codes replaced by dynamic placeholder spans
          (the TipTap NodeView updates .koto-hdr-page-num per page)
        - Paragraphs that contain only field chars but no literal text
        """
        try:
            paras = section_obj.paragraphs
            if not paras:
                return ""

            def _has_content(p) -> bool:
                """True if the paragraph has visible text OR field chars."""
                if p.text.strip():
                    return True
                xml = p._element.xml if hasattr(p._element, "xml") else ""
                return "fldChar" in xml or "instrText" in xml

            def _tabs_to_flex(p_html: str) -> str:
                """Convert tab-based header/footer to a flex row.

                Word headers commonly use tabs for left/center/right alignment.
                We detect <span> elements that contain only tab characters and
                use them as separators to create a flex layout.
                """
                import re as _re

                if "\t" not in p_html:
                    return p_html
                m = _re.match("(<p[^>]*>)(.*)(</p>)$", p_html, _re.DOTALL)
                if not m:
                    return p_html
                open_tag, inner, close_tag = (m.group(1), m.group(2), m.group(3))
                _TAB_MARKER = "\x00TAB\x00"
                inner = _re.sub("<span[^>]*>\\s*\\t\\s*</span>", _TAB_MARKER, inner)
                inner = inner.replace("\t", _TAB_MARKER)
                parts = inner.split(_TAB_MARKER)
                parts = [p.strip() for p in parts]
                if len(parts) < 2:
                    return p_html
                flex_style = "display:flex;justify-content:space-between;align-items:baseline;width:100%"
                if 'style="' in open_tag:
                    open_tag = open_tag.replace('style="', f'style="{flex_style};', 1)
                else:
                    open_tag = open_tag[:-1] + f' style="{flex_style}">'
                spans = []
                for i, part in enumerate(parts):
                    if not part:
                        part = "&nbsp;"
                    align = (
                        "left"
                        if i == 0
                        else "right" if i == len(parts) - 1 else "center"
                    )
                    spans.append(
                        f'<span class="koto-hdr-col" style="text-align:{align};flex-shrink:0">{part}</span>'
                    )
                return open_tag + "".join(spans) + close_tag

            def _build_field_aware_inner(p) -> str:
                """Build the inner HTML for a header/footer paragraph.

                Unlike _para_html (which renders all w:t text), this function
                handles complex field sequences (PAGE, NUMPAGES) by:
                  - Skipping the cached result runs between fldChar/separate
                    and fldChar/end
                  - Injecting a koto-hdr-page-num / koto-hdr-num-pages span
                    in their place so the TipTap NodeView can update them

                Non-field runs are delegated to _run_html.
                """
                from docx.text.paragraph import Paragraph as _Para
                from docx.text.run import Run as _Run

                parts: list[str] = []
                _in_field = False
                _after_sep = False
                _cur_instr: list[str] = []
                for child in p._element:
                    tag_name = (
                        child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    )
                    if tag_name == "hyperlink":
                        rId = child.get(qn("r:id"))
                        url = ""
                        if rId:
                            try:
                                url = p.part.relationships[rId].target_ref
                            except Exception:
                                pass
                        if not url:
                            anchor_val = child.get(qn("w:anchor"), "")
                            if anchor_val:
                                url = "#" + anchor_val
                        link_inner = ""
                        for r_elem in child.findall(qn("w:r")):
                            run_obj = _Run(r_elem, p)
                            link_inner += _run_html(run_obj, doc)
                        if link_inner:
                            esc_url = url.replace('"', "&quot;")
                            target_attr = (
                                "" if url.startswith("#") else ' target="_blank"'
                            )
                            parts.append(
                                f'<a href="{esc_url}"{target_attr} style="color:#1155CC;text-decoration:underline;">{link_inner}</a>'
                            )
                        continue
                    if tag_name != "r":
                        continue
                    fldChar_el = child.find(qn("w:fldChar"))
                    instrText_el = child.find(qn("w:instrText"))
                    if fldChar_el is not None:
                        ftype = fldChar_el.get(qn("w:fldCharType"), "")
                        if ftype == "begin":
                            _in_field = True
                            _after_sep = False
                            _cur_instr = []
                        elif ftype == "separate" and _in_field:
                            _after_sep = True
                        elif ftype == "end" and _in_field:
                            instr = " ".join(_cur_instr).strip().upper()
                            instr_words = set(instr.split())
                            if "PAGE" in instr_words and "NUMPAGES" not in instr_words:
                                parts.append(
                                    '<span class="koto-hdr-page-num" style="font-size:inherit;color:inherit" contenteditable="false">1</span>'
                                )
                            elif (
                                "NUMPAGES" in instr_words
                                or "SECTIONPAGES" in instr_words
                            ):
                                parts.append(
                                    '<span class="koto-hdr-num-pages" style="font-size:inherit;color:inherit" contenteditable="false">1</span>'
                                )
                            _in_field = False
                            _after_sep = False
                        continue
                    if instrText_el is not None:
                        if _in_field and (not _after_sep):
                            _cur_instr.append(instrText_el.text or "")
                        continue
                    if _in_field and _after_sep:
                        continue
                    run_obj = _Run(child, p)
                    parts.append(_run_html(run_obj, doc))
                return "".join(parts)

            texts = []
            for p in paras:
                if not _has_content(p):
                    continue
                inner = _build_field_aware_inner(p)
                if not inner.strip():
                    inner = "<br/>"
                css = _para_style(p)
                style_str = ";".join((f"{k}:{v}" for k, v in css.items()))
                style_attr = f' style="{style_str}"' if style_str else ""
                p_html = f'<p class="{cls}"{style_attr}>{inner}</p>'
                _nbsp6 = "\xa0" * 6
                p_html = p_html.replace(_nbsp6, "\t")
                p_html = _tabs_to_flex(p_html)
                texts.append(p_html)
            if not texts:
                return ""
            return "".join(texts)
        except Exception:
            return ""

    from docx.oxml.ns import qn as _qn

    doc = Document(file_path)
    body_parts: list[str] = []
    active_body_comment_ids: list[str] = []
    preview_units_limit = (
        _DOCX_PREVIEW_TARGET_PAGES * _DOCX_PREVIEW_UNITS_PER_PAGE
        if progressive_preview
        else None
    )
    preview_units_used = 0
    preview_truncated = False
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    current_list_id: int | None = None
    current_list_tag: str = "ul"
    current_list_items: list[str] = []

    def _record_preview_units(units: int) -> None:
        nonlocal preview_units_used
        if preview_units_limit is not None:
            preview_units_used += max(1, units)

    def _would_exceed_preview(units: int) -> bool:
        if preview_units_limit is None:
            return False
        if not body_parts:
            return False
        return preview_units_used + max(1, units) > preview_units_limit

    def _estimate_table_units(tbl_el) -> int:
        row_count = len(tbl_el.findall(qn("w:tr")))
        cell_count = len(tbl_el.findall(".//" + qn("w:tc")))
        return max(6, min(220, row_count * 2 + math.ceil(cell_count / 24)))

    def _flush_list() -> bool:
        nonlocal current_list_id, current_list_items
        if current_list_items:
            _list_units = max(2, min(24, len(current_list_items) * 2))
            if _would_exceed_preview(_list_units):
                return False
            body_parts.append(
                f"<{current_list_tag}>"
                + "".join((f"<li>{item}</li>" for item in current_list_items))
                + f"</{current_list_tag}>"
            )
            _record_preview_units(_list_units)
        current_list_id = None
        current_list_items = []
        return True

    stop_render = False
    body_elem = doc.element.body
    current_section_idx = 0
    for child_elem in body_elem:
        if stop_render:
            break
        tag_local = (
            child_elem.tag.split("}")[-1] if "}" in child_elem.tag else child_elem.tag
        )
        if tag_local == "p":
            para = Paragraph(child_elem, doc)
            style_ref = _resolve_para_style_ref(para)
            style_defaults = _resolve_style_defaults(style_ref)
            numbering = resolve_paragraph_numbering(para, style_ref)
            if numbering is not None:
                num_id, ilvl = numbering
                list_tag = "ul"
                try:
                    numbering_part = doc.part.numbering_part
                    if numbering_part is not None:
                        num_elem = numbering_part._element.find(
                            f""".//{qn('w:num')}[@{qn('w:numId')}="{num_id}"]"""
                        )
                        if num_elem is not None:
                            abstractNumId_elem = num_elem.find(qn("w:abstractNumId"))
                            if abstractNumId_elem is not None:
                                abs_id = abstractNumId_elem.get(qn("w:val"), "")
                                abs_num = numbering_part._element.find(
                                    f""".//{qn('w:abstractNum')}[@{qn('w:abstractNumId')}="{abs_id}"]"""
                                )
                                if abs_num is not None:
                                    lvl = abs_num.find(
                                        f""".//{qn('w:lvl')}[@{qn('w:ilvl')}="{ilvl}"]"""
                                    )
                                    if lvl is not None:
                                        numFmt = lvl.find(qn("w:numFmt"))
                                        if numFmt is not None:
                                            fmt_val = numFmt.get(qn("w:val"), "")
                                            if fmt_val in (
                                                "decimal",
                                                "lowerLetter",
                                                "upperLetter",
                                                "lowerRoman",
                                                "upperRoman",
                                                "chineseCounting",
                                            ):
                                                list_tag = "ol"
                except Exception as exc:
                    logger.warning(
                        "[DocxRichRenderer] Failed to resolve list numbering; rendering the paragraph with the safe list fallback: %s",
                        exc,
                    )
                if num_id != current_list_id or list_tag != current_list_tag:
                    if not _flush_list():
                        preview_truncated = True
                        stop_render = True
                        break
                    current_list_id = num_id
                    current_list_tag = list_tag
                current_list_items.append(
                    _render_inline_children_html(
                        child_elem,
                        para,
                        doc,
                        active_comment_ids=active_body_comment_ids,
                    )
                    or "&nbsp;"
                )
                continue
            if not _flush_list():
                preview_truncated = True
                stop_render = True
                break
            _has_explicit_pb = any(
                (
                    br.get(qn("w:type"), "") == "page"
                    for br in child_elem.findall(".//" + qn("w:br"))
                )
            )
            _has_section_pb = False
            try:
                _pPr = child_elem.find(qn("w:pPr"))
                if _pPr is not None:
                    _sectPr = _pPr.find(qn("w:sectPr"))
                    if _sectPr is not None:
                        _type_el = _sectPr.find(qn("w:type"))
                        _stype = (
                            _type_el.get(qn("w:val"), "nextPage")
                            if _type_el is not None
                            else "nextPage"
                        )
                        if _stype != "continuous":
                            _has_section_pb = True
            except Exception as exc:
                logger.warning(
                    "[DocxRichRenderer] Failed to inspect a section page break; continuing without an inferred section boundary: %s",
                    exc,
                )
            block_tag, block_role = _classify_paragraph_block(
                para, child_elem, style_ref=style_ref, style_defaults=style_defaults
            )
            _para_units = _estimate_paragraph_units(para)
            if _would_exceed_preview(_para_units):
                preview_truncated = True
                stop_render = True
                break
            heading_anchor_id = _resolve_body_heading_anchor(
                child_elem, block_tag, block_role
            )
            if _should_emit_heading_manifest_entry(
                block_tag, block_role, child_elem, style_defaults, style_ref
            ):
                heading_anchor_id = _record_body_heading(
                    child_elem, block_tag, anchor_id=heading_anchor_id
                )
            body_parts.append(
                _para_html(
                    para,
                    doc,
                    block_tag,
                    style_ref=style_ref,
                    anchor_id=heading_anchor_id,
                    extra_class=(
                        "koto-visual-title" if block_role == "visual_title" else None
                    ),
                    extra_role=None if block_role == "body" else block_role,
                    active_comment_ids=active_body_comment_ids,
                )
            )
            _record_preview_units(_para_units)
            if _has_explicit_pb or _has_section_pb:
                if _would_exceed_preview(1):
                    preview_truncated = True
                    stop_render = True
                    break
                next_section_idx = (
                    current_section_idx + 1 if _has_section_pb else current_section_idx
                )
                body_parts.append(
                    f'<div data-page-break="true" data-section-idx="{next_section_idx}" data-current-section-idx="{current_section_idx}" data-next-section-idx="{next_section_idx}" class="koto-page-break" contenteditable="false"></div>'
                )
                _record_preview_units(1)
                current_section_idx = next_section_idx
        elif tag_local == "tbl":
            if not _flush_list():
                preview_truncated = True
                stop_render = True
                break
            _table_units = _estimate_table_units(child_elem)
            _table_row_limit = None
            if preview_units_limit is not None:
                _remaining_units = max(0, preview_units_limit - preview_units_used)
                if body_parts and _remaining_units < _table_units:
                    preview_truncated = True
                    stop_render = True
                    break
                if not body_parts and _remaining_units <= _table_units:
                    _table_row_limit = max(
                        4,
                        min(
                            _DOCX_PREVIEW_MAX_TABLE_ROWS,
                            max(4, _remaining_units // 2 or 4),
                        ),
                    )
                    preview_truncated = True
            tbl = Table(child_elem, doc)
            body_parts.append(
                _table_html(
                    tbl,
                    doc,
                    max_rows=_table_row_limit,
                    active_comment_ids=active_body_comment_ids,
                )
            )
            if _table_row_limit is not None:
                _record_preview_units(max(6, _table_row_limit * 2))
                stop_render = True
            else:
                _record_preview_units(_table_units)
        elif tag_local == "sdt":
            if not _flush_list():
                preview_truncated = True
                stop_render = True
                break
            _is_toc_sdt = False
            try:
                _sdtPr = child_elem.find(qn("w:sdtPr"))
                if _sdtPr is not None:
                    _dpg = _sdtPr.find(".//" + qn("w:docPartGallery"))
                    if _dpg is not None:
                        _gval = _dpg.get(qn("w:val"), "")
                        if "Table of Contents" in _gval or "目录" in _gval:
                            _is_toc_sdt = True
            except Exception as exc:
                logger.warning(
                    "[DocxRichRenderer] Failed to classify a structured document tag; rendering it without the TOC wrapper: %s",
                    exc,
                )
            if _is_toc_sdt:
                body_parts.append('<div class="koto-toc">')
                _record_preview_units(1)
            sdtContent = child_elem.find(qn("w:sdtContent"))
            if sdtContent is not None:
                for sdt_child in sdtContent:
                    sdt_tag = (
                        sdt_child.tag.split("}")[-1]
                        if "}" in sdt_child.tag
                        else sdt_child.tag
                    )
                    if sdt_tag == "p":
                        para = Paragraph(sdt_child, doc)
                        style_ref = _resolve_para_style_ref(para)
                        style_defaults = _resolve_style_defaults(style_ref)
                        _btag, _block_role = _classify_paragraph_block(
                            para,
                            sdt_child,
                            style_ref=style_ref,
                            style_defaults=style_defaults,
                        )
                        _para_units = _estimate_paragraph_units(para)
                        if _would_exceed_preview(_para_units):
                            preview_truncated = True
                            stop_render = True
                            break
                        heading_anchor_id = _resolve_body_heading_anchor(
                            sdt_child, _btag, _block_role
                        )
                        if _should_emit_heading_manifest_entry(
                            _btag, _block_role, sdt_child, style_defaults, style_ref
                        ):
                            heading_anchor_id = _record_body_heading(
                                sdt_child, _btag, anchor_id=heading_anchor_id
                            )
                        body_parts.append(
                            _para_html(
                                para,
                                doc,
                                _btag,
                                style_ref=style_ref,
                                anchor_id=heading_anchor_id,
                                extra_class=(
                                    "koto-visual-title"
                                    if _block_role == "visual_title"
                                    else None
                                ),
                                extra_role=(
                                    None if _block_role == "body" else _block_role
                                ),
                                active_comment_ids=active_body_comment_ids,
                            )
                        )
                        _record_preview_units(_para_units)
                    elif sdt_tag == "tbl":
                        _table_units = _estimate_table_units(sdt_child)
                        _table_row_limit = None
                        if preview_units_limit is not None:
                            _remaining_units = max(
                                0, preview_units_limit - preview_units_used
                            )
                            if body_parts and _remaining_units < _table_units:
                                preview_truncated = True
                                stop_render = True
                                break
                            if not body_parts and _remaining_units <= _table_units:
                                _table_row_limit = max(
                                    4,
                                    min(
                                        _DOCX_PREVIEW_MAX_TABLE_ROWS,
                                        max(4, _remaining_units // 2 or 4),
                                    ),
                                )
                                preview_truncated = True
                        tbl = Table(sdt_child, doc)
                        body_parts.append(
                            _table_html(
                                tbl,
                                doc,
                                max_rows=_table_row_limit,
                                active_comment_ids=active_body_comment_ids,
                            )
                        )
                        if _table_row_limit is not None:
                            _record_preview_units(max(6, _table_row_limit * 2))
                            stop_render = True
                            break
                        _record_preview_units(_table_units)
            if _is_toc_sdt:
                body_parts.append("</div>")
            if stop_render:
                break
        elif tag_local == "sectPr":
            pass
    if not stop_render and (not _flush_list()):
        preview_truncated = True
        stop_render = True
    sections_data: list[dict] = []
    try:
        _emu_px = lambda e: round(e / 914400 * 96) if e else 0
        _twips_px = lambda t: round(t / 20.0 / 72.0 * 96.0, 2) if t else 0

        def _parse_int_attr(value) -> int:
            try:
                return int(value)
            except Exception:
                return 0

        def _extract_section_doc_grid(section) -> dict[str, Any]:
            grid_info = {
                "enabled": False,
                "type": "",
                "line_pitch_twips": 0,
                "line_pitch_px": 0,
                "char_space": 0,
            }
            try:
                sect_pr = getattr(section, "_sectPr", None)
                if sect_pr is None:
                    return grid_info
                doc_grid = sect_pr.find(qn("w:docGrid"))
                if doc_grid is None:
                    return grid_info
                line_pitch = _parse_int_attr(doc_grid.get(qn("w:linePitch")))
                char_space = _parse_int_attr(doc_grid.get(qn("w:charSpace")))
                grid_info.update(
                    {
                        "enabled": True,
                        "type": str(doc_grid.get(qn("w:type")) or ""),
                        "line_pitch_twips": line_pitch,
                        "line_pitch_px": _twips_px(line_pitch),
                        "char_space": char_space,
                    }
                )
            except Exception:
                return grid_info
            return grid_info

        for sec in doc.sections:
            sec_info: dict = {
                "page_width_px": _emu_px(sec.page_width),
                "page_height_px": _emu_px(sec.page_height),
                "margin_top_px": _emu_px(sec.top_margin),
                "margin_bottom_px": _emu_px(sec.bottom_margin),
                "margin_left_px": _emu_px(sec.left_margin),
                "margin_right_px": _emu_px(sec.right_margin),
                "doc_grid": _extract_section_doc_grid(sec),
            }
            try:
                sec_info["header_html"] = _section_html(sec.header, doc, "koto-header")
            except Exception:
                sec_info["header_html"] = ""
            try:
                sec_info["footer_html"] = _section_html(sec.footer, doc, "koto-footer")
            except Exception:
                sec_info["footer_html"] = ""
            try:
                sec_info["first_header_html"] = (
                    _section_html(sec.first_page_header, doc, "koto-header")
                    if sec.different_first_page_header_footer
                    else ""
                )
            except Exception:
                sec_info["first_header_html"] = ""
            try:
                sec_info["first_footer_html"] = (
                    _section_html(sec.first_page_footer, doc, "koto-footer")
                    if sec.different_first_page_header_footer
                    else ""
                )
            except Exception:
                sec_info["first_footer_html"] = ""
            try:
                sec_info["even_header_html"] = _section_html(
                    sec.even_page_header, doc, "koto-header"
                )
            except Exception:
                sec_info["even_header_html"] = ""
            try:
                sec_info["even_footer_html"] = _section_html(
                    sec.even_page_footer, doc, "koto-footer"
                )
            except Exception:
                sec_info["even_footer_html"] = ""
            sections_data.append(sec_info)
    except Exception as sec_exc:
        import logging as _log

        _log.getLogger(__name__).debug(
            "[DocxParser] 节段信息提取失败 (非致命): %s", sec_exc
        )
    preview_meta = {
        "pending": bool(progressive_preview and preview_truncated),
        "target_pages": _DOCX_PREVIEW_TARGET_PAGES if progressive_preview else None,
    }
    return ("\n".join(body_parts), sections_data, _heading_manifest, preview_meta)
