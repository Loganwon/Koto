# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Paragraph semantics and style resolution for the rich DOCX renderer."""

from __future__ import annotations

import re
from typing import Any

from app.core.file.parsers.docx_rich_renderer_helpers import (
    _extract_toc_level_from_style,
    _is_toc_style_key,
    _looks_like_outline_only_body_sentence,
    _looks_like_structural_heading_prefix,
    _norm_style_key,
    _parse_int_prop,
    _pt_to_twips,
    _quote_css_font_family,
    _resolve_para_style_ref,
    _slugify_heading_anchor,
    _twips_to_pt,
)


def build_paragraph_semantics(dependencies: dict[str, Any]):
    """Build paragraph classifiers while sharing one document render context."""
    RGBColor = dependencies["RGBColor"]
    qn = dependencies["qn"]
    _ALIGN_MAP = dependencies["align_map"]
    _CN_FONT_EQUIVALENTS = dependencies["cn_font_equivalents"]
    _EMPTY_STYLE_DEFAULTS = dependencies["empty_style_defaults"]
    _HEADING_MAP = dependencies["heading_map"]
    _HEADING_TYPOGRAPHY_FALLBACKS = dependencies["heading_typography_fallbacks"]
    _VISUAL_TITLE_STYLE_KEYS = dependencies["visual_title_style_keys"]
    _generated_heading_id_counts = dependencies["generated_heading_id_counts"]
    _heading_manifest = dependencies["heading_manifest"]
    _style_defaults_cache = dependencies["style_defaults_cache"]

    def _rgb_to_hex(rgb: RGBColor | None) -> str | None:
        if rgb is None:
            return None
        try:
            return "#{:02X}{:02X}{:02X}".format(
                int(rgb.red), int(rgb.green), int(rgb.blue)
            )
        except Exception:
            return None

    def _build_css_font_family_stack(*names: str | None) -> str | None:
        _tokens: list[str] = []
        _seen: set[str] = set()
        for _name in names:
            _raw = str(_name or "").strip().strip("'\"")
            if not _raw:
                continue
            for _candidate in _CN_FONT_EQUIVALENTS.get(_raw, (_raw,)):
                _norm = _candidate.lower()
                if _norm in _seen:
                    continue
                _seen.add(_norm)
                _tokens.append(_candidate)
        if not _tokens:
            return None
        return ",".join((_quote_css_font_family(_token) for _token in _tokens))

    def _is_heading_style_key(val: str | None) -> str | None:
        """Return h1..h6 if the style key represents a heading style."""
        if not val:
            return None
        _raw = str(val).strip().lower()
        if _raw in _HEADING_MAP:
            return _HEADING_MAP[_raw]
        _k = _norm_style_key(val)
        if _k.startswith("heading") and len(_k) > 7 and _k[7:].isdigit():
            _lv = int(_k[7:])
            if 1 <= _lv <= 6:
                return f"h{_lv}"
        if _k.startswith("标题"):
            _digits = "".join((ch for ch in _k if ch.isdigit()))
            if _digits:
                _lv = int(_digits)
                if 1 <= _lv <= 6:
                    return f"h{_lv}"
        return None

    def _is_visual_title_style_key(val: str | None) -> bool:
        """Return True for title-like paragraph styles that are visual, not structural."""
        _k = _norm_style_key(val)
        if not _k:
            return False
        return _k in _VISUAL_TITLE_STYLE_KEYS

    def _style_chain_has_visual_title(style_ref) -> bool:
        """Return True when any style in the base-style chain is title-like."""
        _visited_ids: set[int] = set()
        _style_iter = style_ref
        while _style_iter is not None:
            _eid = id(getattr(_style_iter, "_element", None))
            if _eid in _visited_ids:
                break
            _visited_ids.add(_eid)
            try:
                _sname = getattr(_style_iter, "name", "") or ""
                _sid = getattr(_style_iter, "style_id", "") or ""
                if _is_visual_title_style_key(_sname) or _is_visual_title_style_key(
                    _sid
                ):
                    return True
            except Exception:
                pass
            try:
                _style_iter = _style_iter.base_style
            except Exception:
                break

    def _style_chain_has_heading(style_ref) -> bool:
        """Return True when any style in the base-style chain resolves to a heading."""
        _visited_ids: set[int] = set()
        _style_iter = style_ref
        while _style_iter is not None:
            _eid = id(getattr(_style_iter, "_element", None))
            if _eid in _visited_ids:
                break
            _visited_ids.add(_eid)
            try:
                _sname = getattr(_style_iter, "name", "") or ""
                _sid = getattr(_style_iter, "style_id", "") or ""
                if _is_heading_style_key(_sname) or _is_heading_style_key(_sid):
                    return True
            except Exception:
                pass
            try:
                _style_iter = _style_iter.base_style
            except Exception:
                break
        return False
        return False

    def _apply_heading_typography_fallback(
        tag: str, css: dict[str, str], inner_html: str
    ) -> None:
        """Keep semantic headings readable when DOCX outline metadata has no font props."""
        _fallback = _HEADING_TYPOGRAPHY_FALLBACKS.get((tag or "").lower())
        if not _fallback:
            return
        _inner_lower = inner_html.lower()
        if "font-size" not in css and "font-size:" not in _inner_lower:
            css["font-size"] = _fallback["font-size"]
        if "font-weight" not in css and "font-weight:" not in _inner_lower:
            css["font-weight"] = _fallback["font-weight"]

    def _p_elem_has_toc_anchor(p_el) -> bool:
        """True when paragraph has internal TOC hyperlink targets like #_Toc*."""
        if p_el is None:
            return False
        try:
            for _hl in p_el.findall(qn("w:hyperlink")):
                _a = (_hl.get(qn("w:anchor")) or "").lower()
                if _a.startswith("_toc"):
                    return True
        except Exception:
            return False
        return False

    def _p_elem_has_toc_field(p_el) -> bool:
        """True when paragraph carries a TOC/PAGEREF field code."""
        if p_el is None:
            return False
        try:
            _instr = " ".join(
                (_node.text or "" for _node in p_el.iter(qn("w:instrText")))
            )
            _instr_norm = re.sub("\\s+", " ", _instr).strip().upper()
            if not _instr_norm:
                return False
            return " TOC " in f" {_instr_norm} " or (
                " PAGEREF " in f" {_instr_norm} " and "_TOC" in _instr_norm
            )
        except Exception:
            return False

    def _p_elem_text_content(p_el) -> str:
        """Extract visible paragraph text from runs for structural heuristics."""
        if p_el is None:
            return ""
        try:
            _text = "".join((_node.text or "" for _node in p_el.iter(qn("w:t"))))
            return re.sub("\\s+", " ", _text).strip()
        except Exception:
            return ""

    def _find_bookmark_id(p_el) -> str:
        """Return the first visible bookmark id attached to a paragraph element."""
        if p_el is None:
            return ""
        try:
            for _bm in p_el.findall(qn("w:bookmarkStart")):
                _name = (_bm.get(qn("w:name"), "") or "").strip()
                if _name and (not _name.startswith("_GoBack")):
                    return _name
        except Exception:
            return ""
        return ""

    def _make_generated_heading_anchor(text: str) -> str:
        """Generate a unique synthetic anchor id for a body heading."""
        _base = f"koto-heading-{_slugify_heading_anchor(text)}"
        _count = _generated_heading_id_counts.get(_base, 0)
        _generated_heading_id_counts[_base] = _count + 1
        return _base if _count == 0 else f"{_base}-{_count + 1}"

    def _resolve_body_heading_anchor(p_el, tag: str | None, block_role: str) -> str:
        """Return a stable DOM id for structural headings even when excluded from nav manifest."""
        if block_role != "structural_heading":
            return ""
        if not tag or not re.fullmatch("h[1-6]", (tag or "").lower()):
            return ""
        _text = _p_elem_text_content(p_el)
        if not _text:
            return ""
        return _find_bookmark_id(p_el) or _make_generated_heading_anchor(_text)

    def _record_body_heading(
        p_el, tag: str | None, anchor_id: str | None = None
    ) -> str:
        """Append a parser-owned body heading manifest entry and return its anchor id."""
        if not tag or not re.fullmatch("h[1-6]", (tag or "").lower()):
            return ""
        _text = _p_elem_text_content(p_el)
        if not _text:
            return ""
        _anchor_id = (
            (anchor_id or "").strip()
            or _find_bookmark_id(p_el)
            or _make_generated_heading_anchor(_text)
        )
        _heading_manifest.append(
            {"level": int(tag[1]), "text": _text, "id": _anchor_id}
        )
        return _anchor_id

    def _should_emit_heading_manifest_entry(
        tag: str | None, block_role: str, p_el=None, style_defaults=None, style_ref=None
    ) -> bool:
        """Populate the navigation manifest for structural headings with durable title signals."""
        if block_role != "structural_heading":
            return False
        if not tag or not re.fullmatch("h[1-6]", str(tag).lower()):
            return False
        _style_defaults = style_defaults or {}
        try:
            _style_name = _style_defaults.get("style_name") or ""
        except Exception:
            _style_name = ""
        try:
            _style_id = _style_defaults.get("style_id") or ""
        except Exception:
            _style_id = ""
        if _is_heading_style_key(_style_name) or _is_heading_style_key(_style_id):
            return True
        if _style_chain_has_heading(style_ref):
            return True
        _text = _p_elem_text_content(p_el)
        return bool(_text and _looks_like_structural_heading_prefix(_text))

    def _p_elem_looks_like_toc_line(p_el) -> bool:
        """Heuristic for field-updated TOC lines that only keep visible text."""
        _text = _p_elem_text_content(p_el)
        if not _text or len(_text) > 160:
            return False
        if re.search("[。！？；;，,]", _text):
            return False
        if re.search("(?:\\.{2,}|…{2,})\\s*\\d{1,4}$", _text):
            return True
        return re.match("^.{1,80}\\s+\\d{1,4}$", _text) is not None

    def _should_promote_outline_heading(para, p_el, tag: str | None) -> bool:
        """Reject outlineLvl-only body-like paragraphs from becoming structural headings."""
        if not tag:
            return False
        _text = _p_elem_text_content(p_el)
        if not _text:
            return False
        _max_len = 90 if tag == "h1" else 60
        if len(_text) > _max_len:
            return False
        if _looks_like_outline_only_body_sentence(_text):
            return False
        try:
            _first_line_indent = para.paragraph_format.first_line_indent
            if _first_line_indent is not None and getattr(
                _first_line_indent, "twips", 0
            ):
                return False
        except Exception:
            pass
        return True

    def _classify_paragraph_block(
        para, p_el, style_ref=None, style_defaults=None
    ) -> tuple[str, str]:
        """Classify a body paragraph once into structural heading, visual title, TOC line, or body.

        Returns (html_tag, role), where role is one of:
        - structural_heading
        - visual_title
        - toc_line
        - body

        This is the parser-owned single source of truth for the heading
        manifest and emitted heading tags. Callers must not re-canonicalize the
        result in a second pass.
        """
        _sr = style_ref if style_ref is not None else _resolve_para_style_ref(para)
        _style_defaults = (
            style_defaults
            if style_defaults is not None
            else _resolve_style_defaults(_sr)
        )
        try:
            _style_name = _style_defaults.get("style_name") or ""
        except Exception:
            _style_name = ""
        try:
            _style_id = _style_defaults.get("style_id") or ""
        except Exception:
            _style_id = ""
        _is_toc_para, _ = _detect_toc_info(para=para, p_el=p_el, style_ref=_sr)
        if _is_toc_para:
            return ("p", "toc_line")
        if _is_visual_title_style_key(_style_name) or _is_visual_title_style_key(
            _style_id
        ):
            return ("p", "visual_title")
        _direct_heading_tag = _is_heading_style_key(
            _style_name
        ) or _is_heading_style_key(_style_id)
        if _direct_heading_tag:
            return (_direct_heading_tag, "structural_heading")
        if _style_chain_has_visual_title(_sr):
            return ("p", "visual_title")
        _outline_tag, _via_outlinelvl = _detect_outline_level(para, p_el)
        if (
            _via_outlinelvl
            and _outline_tag
            and _should_promote_outline_heading(para, p_el, _outline_tag)
        ):
            return (_outline_tag, "structural_heading")
        return ("p", "body")

    def _line_spacing_to_css(ls, ls_rule) -> str | None:
        from docx.enum.text import WD_LINE_SPACING

        if ls is None:
            return None
        _FIXED_MULT = {
            WD_LINE_SPACING.SINGLE: 1.0,
            WD_LINE_SPACING.ONE_POINT_FIVE: 1.5,
            WD_LINE_SPACING.DOUBLE: 2.0,
        }
        if ls_rule in _FIXED_MULT:
            return f"{_FIXED_MULT[ls_rule]}"
        if ls_rule in (WD_LINE_SPACING.MULTIPLE, None):
            try:
                mult = round(float(ls), 4)
                if 0 < mult < 1.0:
                    mult = 1.0
                return f"{mult}"
            except (TypeError, ValueError):
                pass
            try:
                return f"{round(ls.pt, 2)}pt"
            except Exception:
                return None
        try:
            return f"{round(ls.pt, 2)}pt"
        except Exception:
            return None

    def _read_on_off_prop(el) -> bool | None:
        """Return OOXML on/off state for elements like <w:b/> or <w:i w:val="0"/>."""
        if el is None:
            return None
        try:
            _val = el.get(qn("w:val"))
        except Exception:
            _val = None
        if _val is None or str(_val).strip() == "":
            return True
        _norm = str(_val).strip().lower()
        if _norm in ("0", "false", "off", "no"):
            return False
        return True

    def _read_paragraph_layout_props_from_ppr(p_pr) -> dict[str, Any]:
        layout = {
            "space_before_twips": None,
            "space_after_twips": None,
            "line_spacing_rule": None,
            "line_spacing_twips": None,
            "first_line_indent_twips": None,
            "left_indent_twips": None,
            "keep_with_next": None,
            "keep_together": None,
            "page_break_before": None,
            "widow_control": None,
        }
        if p_pr is None:
            return layout
        try:
            spacing_el = p_pr.find(qn("w:spacing"))
            if spacing_el is not None:
                layout["space_before_twips"] = _parse_int_prop(
                    spacing_el.get(qn("w:before"))
                )
                layout["space_after_twips"] = _parse_int_prop(
                    spacing_el.get(qn("w:after"))
                )
                layout["line_spacing_twips"] = _parse_int_prop(
                    spacing_el.get(qn("w:line"))
                )
                line_rule = str(spacing_el.get(qn("w:lineRule")) or "").strip()
                if line_rule:
                    layout["line_spacing_rule"] = line_rule
                elif layout["line_spacing_twips"] is not None:
                    layout["line_spacing_rule"] = "auto"
        except Exception:
            pass
        try:
            ind_el = p_pr.find(qn("w:ind"))
            if ind_el is not None:
                layout["first_line_indent_twips"] = _parse_int_prop(
                    ind_el.get(qn("w:firstLine"))
                )
                layout["left_indent_twips"] = _parse_int_prop(ind_el.get(qn("w:left")))
        except Exception:
            pass
        for tag_name, key in (
            ("w:keepNext", "keep_with_next"),
            ("w:keepLines", "keep_together"),
            ("w:pageBreakBefore", "page_break_before"),
            ("w:widowControl", "widow_control"),
        ):
            try:
                layout[key] = _read_on_off_prop(p_pr.find(qn(tag_name)))
            except Exception:
                pass
        return layout

    def _read_bold_state_from_rpr(rpr_el) -> bool | None:
        """Read effective bold state from a run-property element, including CJK bCs."""
        if rpr_el is None:
            return None
        _bold_state = _read_on_off_prop(rpr_el.find(qn("w:b")))
        if _bold_state is None:
            _bold_state = _read_on_off_prop(rpr_el.find(qn("w:bCs")))
        return _bold_state

    def _read_rpr_font_props(rpr_el) -> dict[str, Any]:
        """Extract default font props from a run-properties XML element."""
        _props: dict[str, Any] = {
            "font_size": None,
            "font_family": None,
            "font_weight": None,
            "font_weight_set": False,
            "font_style": None,
            "font_style_set": False,
        }
        if rpr_el is None:
            return _props
        try:
            _sz = rpr_el.find(qn("w:sz"))
            if _sz is None:
                _sz = rpr_el.find(qn("w:szCs"))
            if _sz is not None:
                _raw = _sz.get(qn("w:val")) or _sz.get("val") or ""
                if _raw:
                    _props["font_size"] = round(int(_raw) / 2, 1)
        except Exception:
            pass
        try:
            _rFonts = rpr_el.find(qn("w:rFonts"))
            if _rFonts is not None:
                for _key in ("w:eastAsia", "w:ascii", "w:hAnsi", "w:cs"):
                    _font_name = _rFonts.get(qn(_key), "") or ""
                    if _font_name:
                        _props["font_family"] = _build_css_font_family_stack(_font_name)
                        break
        except Exception:
            pass
        try:
            _bold_state = _read_bold_state_from_rpr(rpr_el)
            if _bold_state is not None:
                _props["font_weight_set"] = True
                _props["font_weight"] = "bold" if _bold_state else "normal"
        except Exception:
            pass
        try:
            _italic_state = _read_on_off_prop(rpr_el.find(qn("w:i")))
            if _italic_state is None:
                _italic_state = _read_on_off_prop(rpr_el.find(qn("w:iCs")))
            if _italic_state is not None:
                _props["font_style_set"] = True
                _props["font_style"] = "italic" if _italic_state else "normal"
        except Exception:
            pass
        return _props

    def _resolve_style_defaults(style_ref) -> dict[str, Any]:
        if style_ref is None or not hasattr(style_ref, "_element"):
            return _EMPTY_STYLE_DEFAULTS
        try:
            _style_id_key = style_ref.style_id or ""
        except Exception:
            _style_id_key = ""
        try:
            _style_name_key = style_ref.name or ""
        except Exception:
            _style_name_key = ""
        if _style_id_key or _style_name_key:
            _cache_key: object = (_style_id_key, _style_name_key)
        else:
            _cache_key = id(style_ref._element)
        _cached = _style_defaults_cache.get(_cache_key)
        if _cached is not None:
            return _cached
        _resolved = dict(_EMPTY_STYLE_DEFAULTS)
        try:
            _resolved["style_name"] = style_ref.name or ""
        except Exception:
            pass
        try:
            _resolved["style_id"] = style_ref.style_id or ""
        except Exception:
            pass
        _style = style_ref
        while _style:
            try:
                _spf = _style.paragraph_format
            except Exception:
                _spf = None
            try:
                _pPr = _style._element.find(qn("w:pPr"))
            except Exception:
                _pPr = None
            _layout_props = _read_paragraph_layout_props_from_ppr(_pPr)
            try:
                _rPr = _style._element.find(qn("w:rPr"))
            except Exception:
                _rPr = None
            _rpr_props = _read_rpr_font_props(_rPr)
            if _spf is not None:
                if _resolved["text_align"] is None:
                    try:
                        _align = _ALIGN_MAP.get(_spf.alignment)
                        if _align:
                            _resolved["text_align"] = _align
                    except Exception:
                        pass
                if _resolved["space_before"] is None:
                    try:
                        _val = _spf.space_before
                        if _val is not None:
                            _resolved["space_before"] = _twips_to_pt(_val.twips)
                    except Exception:
                        pass
                    if (
                        _resolved["space_before"] is None
                        and _layout_props["space_before_twips"] is not None
                    ):
                        _resolved["space_before"] = _twips_to_pt(
                            _layout_props["space_before_twips"]
                        )
                if _resolved["space_after"] is None:
                    try:
                        _val = _spf.space_after
                        if _val is not None:
                            _resolved["space_after"] = _twips_to_pt(_val.twips)
                    except Exception:
                        pass
                    if (
                        _resolved["space_after"] is None
                        and _layout_props["space_after_twips"] is not None
                    ):
                        _resolved["space_after"] = _twips_to_pt(
                            _layout_props["space_after_twips"]
                        )
                if _resolved["line_height"] is None:
                    try:
                        _line_height = _line_spacing_to_css(
                            _spf.line_spacing, _spf.line_spacing_rule
                        )
                        if _line_height is not None:
                            _resolved["line_height"] = _line_height
                    except Exception:
                        pass
            if (
                _resolved["line_spacing_rule"] is None
                and _layout_props["line_spacing_rule"] is not None
            ):
                _resolved["line_spacing_rule"] = _layout_props["line_spacing_rule"]
            if (
                _resolved["line_spacing_twips"] is None
                and _layout_props["line_spacing_twips"] is not None
            ):
                _resolved["line_spacing_twips"] = _layout_props["line_spacing_twips"]
            if (
                _resolved["first_line_indent_twips"] is None
                and _layout_props["first_line_indent_twips"] is not None
            ):
                _resolved["first_line_indent_twips"] = _layout_props[
                    "first_line_indent_twips"
                ]
            if (
                _resolved["left_indent_twips"] is None
                and _layout_props["left_indent_twips"] is not None
            ):
                _resolved["left_indent_twips"] = _layout_props["left_indent_twips"]
            if (
                _resolved["keep_with_next"] is None
                and _layout_props["keep_with_next"] is not None
            ):
                _resolved["keep_with_next"] = _layout_props["keep_with_next"]
            if (
                _resolved["keep_together"] is None
                and _layout_props["keep_together"] is not None
            ):
                _resolved["keep_together"] = _layout_props["keep_together"]
            if (
                _resolved["page_break_before"] is None
                and _layout_props["page_break_before"] is not None
            ):
                _resolved["page_break_before"] = _layout_props["page_break_before"]
            if (
                _resolved["widow_control"] is None
                and _layout_props["widow_control"] is not None
            ):
                _resolved["widow_control"] = _layout_props["widow_control"]
            if _resolved["font_size"] is None:
                try:
                    _fsize = _style.font.size
                    if _fsize is not None:
                        _resolved["font_size"] = round(_fsize.pt, 1)
                except Exception:
                    pass
                if (
                    _resolved["font_size"] is None
                    and _rpr_props["font_size"] is not None
                ):
                    _resolved["font_size"] = _rpr_props["font_size"]
            if _resolved["font_family"] is None:
                try:
                    if _rpr_props["font_family"]:
                        _resolved["font_family"] = _rpr_props["font_family"]
                    if _resolved["font_family"] is None:
                        _fn = _style.font.name
                        if _fn:
                            _resolved["font_family"] = _build_css_font_family_stack(_fn)
                except Exception:
                    pass
            if _resolved["text_align"] is None:
                try:
                    _pPr = _style._element.find(qn("w:pPr"))
                    if _pPr is not None:
                        _jc = _pPr.find(qn("w:jc"))
                        if _jc is not None:
                            _align = _jc.get(qn("w:val"), "")
                            if _align in ("left", "center", "right", "justify"):
                                _resolved["text_align"] = _align
                            elif _align == "distribute":
                                _resolved["text_align"] = "justify"
                except Exception:
                    pass
            if (
                _resolved["space_before"] is not None
                and _resolved["space_after"] is not None
                and (_resolved["line_height"] is not None)
                and (_resolved["font_size"] is not None)
                and (_resolved["font_family"] is not None)
            ):
                break
            try:
                _style = _style.base_style
            except Exception:
                _style = None
        _style_defaults_cache[_cache_key] = _resolved
        return _resolved

    def _extract_paragraph_layout_semantics(para, style_ref=None) -> dict[str, Any]:
        style_ref = (
            style_ref if style_ref is not None else _resolve_para_style_ref(para)
        )
        style_defaults = _resolve_style_defaults(style_ref)
        try:
            p_pr = para._element.find(qn("w:pPr"))
        except Exception:
            p_pr = None
        direct_layout = _read_paragraph_layout_props_from_ppr(p_pr)
        return {
            "space_before_twips": (
                direct_layout["space_before_twips"]
                if direct_layout["space_before_twips"] is not None
                else _pt_to_twips(style_defaults.get("space_before"))
            ),
            "space_after_twips": (
                direct_layout["space_after_twips"]
                if direct_layout["space_after_twips"] is not None
                else _pt_to_twips(style_defaults.get("space_after"))
            ),
            "line_spacing_rule": direct_layout["line_spacing_rule"]
            or style_defaults.get("line_spacing_rule"),
            "line_spacing_twips": (
                direct_layout["line_spacing_twips"]
                if direct_layout["line_spacing_twips"] is not None
                else style_defaults.get("line_spacing_twips")
            ),
            "first_line_indent_twips": (
                direct_layout["first_line_indent_twips"]
                if direct_layout["first_line_indent_twips"] is not None
                else style_defaults.get("first_line_indent_twips")
            ),
            "left_indent_twips": (
                direct_layout["left_indent_twips"]
                if direct_layout["left_indent_twips"] is not None
                else style_defaults.get("left_indent_twips")
            ),
            "keep_with_next": (
                direct_layout["keep_with_next"]
                if direct_layout["keep_with_next"] is not None
                else style_defaults.get("keep_with_next")
            ),
            "keep_together": (
                direct_layout["keep_together"]
                if direct_layout["keep_together"] is not None
                else style_defaults.get("keep_together")
            ),
            "page_break_before": (
                direct_layout["page_break_before"]
                if direct_layout["page_break_before"] is not None
                else style_defaults.get("page_break_before")
            ),
            "widow_control": (
                direct_layout["widow_control"]
                if direct_layout["widow_control"] is not None
                else style_defaults.get("widow_control")
            ),
        }

    def _paragraph_layout_data_attrs(para, style_ref=None) -> dict[str, str]:
        semantics = _extract_paragraph_layout_semantics(para, style_ref=style_ref)
        attrs: dict[str, str] = {}
        for key, attr_name in (
            ("space_before_twips", "data-koto-space-before-twips"),
            ("space_after_twips", "data-koto-space-after-twips"),
            ("line_spacing_twips", "data-koto-line-twips"),
            ("first_line_indent_twips", "data-koto-first-line-indent-twips"),
            ("left_indent_twips", "data-koto-left-indent-twips"),
        ):
            value = semantics.get(key)
            if value is not None:
                attrs[attr_name] = str(value)
        line_rule = semantics.get("line_spacing_rule")
        if line_rule:
            attrs["data-koto-line-rule"] = str(line_rule)
        for key, attr_name in (
            ("keep_with_next", "data-koto-keep-next"),
            ("keep_together", "data-koto-keep-lines"),
            ("page_break_before", "data-koto-page-break-before"),
            ("widow_control", "data-koto-widow-control"),
        ):
            value = semantics.get(key)
            if value is not None:
                attrs[attr_name] = "1" if bool(value) else "0"
        return attrs

    def _detect_toc_info(para=None, p_el=None, style_ref=None) -> tuple[bool, str]:
        """Detect whether a paragraph is a TOC entry and return (is_toc, level)."""
        level = "1"
        style_candidates: list[str] = []
        if para is not None:
            _style_defaults = _resolve_style_defaults(
                style_ref if style_ref is not None else _resolve_para_style_ref(para)
            )
            try:
                style_candidates.append(_style_defaults.get("style_name") or "")
            except Exception:
                pass
            try:
                style_candidates.append(_style_defaults.get("style_id") or "")
            except Exception:
                pass
            try:
                if p_el is None:
                    p_el = para._element
            except Exception:
                pass
        if p_el is not None:
            try:
                _pPr = p_el.find(qn("w:pPr"))
                if _pPr is not None:
                    _pSt = _pPr.find(qn("w:pStyle"))
                    if _pSt is not None:
                        style_candidates.append(_pSt.get(qn("w:val")) or "")
            except Exception:
                pass
        _has_toc_anchor = _p_elem_has_toc_anchor(p_el)
        _has_toc_field = _p_elem_has_toc_field(p_el)
        _has_tab = False
        if p_el is not None:
            try:
                _has_tab = p_el.find(".//" + qn("w:tab")) is not None
            except Exception:
                _has_tab = False
        _looks_like_toc_line = _p_elem_looks_like_toc_line(p_el)
        _has_toc_signal = (
            _has_toc_anchor or _has_toc_field or _has_tab or _looks_like_toc_line
        )
        for _sv in style_candidates:
            if _is_toc_style_key(_sv):
                if not _has_toc_signal:
                    continue
                level = _extract_toc_level_from_style(_sv)
                return (True, level)
        if p_el is not None:
            try:
                if _has_tab and (_has_toc_anchor or _has_toc_field):
                    return (True, "1")
            except Exception:
                pass
        return (False, level)

    def _detect_outline_level(para, p_el, style_ref=None) -> tuple[str | None, bool]:
        """Detect heading level only from paragraph-level w:outlineLvl metadata.

        Direct heading styles are handled separately by `_classify_paragraph_block`.
        Returning `via_outlinelvl=True` means callers must still validate that the
        paragraph is short-form structural content rather than body prose that only
        carries outline metadata.
        """
        try:
            pPr = p_el.find(qn("w:pPr"))
            if pPr is not None:
                olvl = pPr.find(qn("w:outlineLvl"))
                if olvl is not None:
                    val = olvl.get(qn("w:val"))
                    if val is not None:
                        lvl = int(val)
                        if lvl == 9:
                            return (None, False)
                        if 0 <= lvl <= 5:
                            return (f"h{lvl + 1}", True)
        except Exception:
            pass
        return (None, False)

    return (
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
    )
