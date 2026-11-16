# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Images, runs, hyperlinks, comments, and revisions for rich DOCX HTML."""

from __future__ import annotations

import base64
import html
import logging
from typing import Any

from app.core.file.image_utils import compress_image_bytes as _compress_image_bytes
from app.core.file.parsers.docx_rich_renderer_helpers import (
    _docx_revision_data_attrs,
    _emu_to_px,
)

logger = logging.getLogger(__name__)


def build_inline_renderers(dependencies: dict[str, Any]):
    """Build mutually recursive inline renderers for one document context."""
    qn = dependencies["qn"]
    _build_css_font_family_stack = dependencies["build_css_font_family_stack"]
    _detect_toc_info = dependencies["detect_toc_info"]
    _read_bold_state_from_rpr = dependencies["read_bold_state_from_rpr"]

    def _color_from_xml(elem) -> str | None:
        """Extract theme/RGB color from a w:color XML element."""
        if elem is None:
            return None
        val = elem.get(qn("w:val"))
        if val and val.lower() not in ("auto", "none", ""):
            if len(val) == 6:
                return "#" + val.upper()
        return None

    def _encode_image_part(part) -> str:
        """Encode an image relationship part to base64 data URI."""
        try:
            img_bytes = part.blob
            content_type = part.content_type or "image/png"
            img_bytes, content_type = _compress_image_bytes(img_bytes, content_type)
            b64 = base64.b64encode(img_bytes).decode("ascii")
            return f"data:{content_type};base64,{b64}"
        except Exception as exc:
            logger.debug("[RichHtml] image encode failed: %s", exc)
            return ""

    def _inline_img_html(drawing_elem, doc) -> str:
        """Render wp:inline drawing as <img> HTML."""
        try:
            blipFill = drawing_elem.find(".//" + qn("a:blip"))
            if blipFill is None:
                return ""
            rId = blipFill.get(qn("r:embed"))
            if not rId:
                return ""
            part = doc.part.related_parts.get(rId)
            if part is None:
                return ""
            src = _encode_image_part(part)
            if not src:
                return ""
            ext = drawing_elem.find(".//" + qn("wp:extent"))
            style = ""
            if ext is not None:
                cx = int(ext.get("cx", 0))
                if cx:
                    w_px = _emu_to_px(cx)
                    style = f' style="width:{w_px}px;max-width:100%"'
            return f'<img src="{src}" alt=""{style} />'
        except Exception as exc:
            logger.debug("[RichHtml] inline img failed: %s", exc)
            return ""

    def _anchor_img_html(drawing_elem, doc) -> str:
        """Render wp:anchor (floating) drawing as <img> HTML.

        Reads OOXML positioning attributes to reproduce Word's layout:
          - wp:positionH / wp:positionV  → CSS float or margin
          - wp:wrapSquare/Tight          → float (left / right)
          - wp:wrapTopAndBottom          → display:block, centred
          - wp:wrapNone                  → inline-block (behind/in-front)
        Falls back to float:right when no positioning info is present.
        """
        try:
            blipFill = drawing_elem.find(".//" + qn("a:blip"))
            if blipFill is None:
                return ""
            rId = blipFill.get(qn("r:embed"))
            if not rId:
                return ""
            part = doc.part.related_parts.get(rId)
            if part is None:
                return ""
            src = _encode_image_part(part)
            if not src:
                return ""
            ext = drawing_elem.find(".//" + qn("wp:extent"))
            size_style = ""
            if ext is not None:
                cx = int(ext.get("cx", 0))
                if cx:
                    w_px = _emu_to_px(cx)
                    size_style = f"width:{w_px}px;"
            pos_h = drawing_elem.find(qn("wp:positionH"))
            h_align = None
            if pos_h is not None:
                align_el = pos_h.find(qn("wp:align"))
                if align_el is not None and align_el.text:
                    h_align = align_el.text.strip().lower()
            has_wrap_square = drawing_elem.find(qn("wp:wrapSquare")) is not None
            has_wrap_tight = drawing_elem.find(qn("wp:wrapTight")) is not None
            has_wrap_none = drawing_elem.find(qn("wp:wrapNone")) is not None
            has_wrap_tb = drawing_elem.find(qn("wp:wrapTopAndBottom")) is not None
            if has_wrap_none:
                pos_style = "display:inline-block;vertical-align:middle;margin:4px 8px;"
            elif has_wrap_tb:
                pos_style = "display:block;margin:10px auto;"
            elif has_wrap_square or has_wrap_tight:
                if h_align in ("left", "inside"):
                    pos_style = "float:left;margin:0 14px 10px 0;"
                else:
                    pos_style = "float:right;margin:0 0 10px 14px;"
            elif h_align == "center":
                pos_style = "display:block;margin:10px auto;"
            elif h_align == "left":
                pos_style = "float:left;margin:0 14px 10px 0;"
            else:
                pos_style = "float:right;margin:0 0 10px 14px;"
            full_style = pos_style + size_style + "max-width:100%;"
            return f'<img src="{src}" alt="" style="{full_style}" />'
        except Exception as exc:
            logger.debug("[RichHtml] anchor img failed: %s", exc)
            return ""

    def _run_html(run, doc) -> str:
        """Convert a single w:r run to HTML span(s), handling images and hyperlinks."""
        drawing = run._element.find(qn("w:drawing"))
        if drawing is not None:
            inline = drawing.find(qn("wp:inline"))
            anchor = drawing.find(qn("wp:anchor"))
            if inline is not None:
                return _inline_img_html(inline, doc)
            if anchor is not None:
                return _anchor_img_html(anchor, doc)

        def _note_reference_html() -> str:
            markers: list[str] = []
            for tag_name, data_attr in (
                ("w:footnoteReference", "data-koto-footnote-ref"),
                ("w:endnoteReference", "data-koto-endnote-ref"),
            ):
                for ref_el in run._element.findall(qn(tag_name)):
                    note_id = str(ref_el.get(qn("w:id")) or "").strip()
                    if not note_id:
                        continue
                    cls_name = (
                        "koto-footnote-ref"
                        if "footnote" in tag_name
                        else "koto-endnote-ref"
                    )
                    escaped_id = html.escape(note_id, quote=True)
                    markers.append(
                        f'<sup class="{cls_name}" {data_attr}="{escaped_id}">{escaped_id}</sup>'
                    )
            return "".join(markers)

        note_ref_html = _note_reference_html()
        text = run.text or ""
        if not text:
            deleted_text_nodes = [
                node.text or "" for node in run._element.findall(qn("w:delText"))
            ]
            if deleted_text_nodes:
                text = "".join(deleted_text_nodes)
        _p_el = run._element.getparent()
        while _p_el is not None:
            _local = _p_el.tag.split("}")[-1] if "}" in _p_el.tag else _p_el.tag
            if _local == "p":
                break
            _p_el = _p_el.getparent()
        _is_toc_run, _ = _detect_toc_info(p_el=_p_el)
        _has_tab_elem = run._element.find(qn("w:tab")) is not None
        _has_tab_char = "\t" in text
        _tab_html = ""
        if _has_tab_elem or _has_tab_char:
            _tab_html = (
                '<span class="koto-toc-tab"></span>' if _is_toc_run else "\xa0" * 6
            )
        if not text:
            if _has_tab_elem:
                return _tab_html + note_ref_html
            return note_ref_html

        def _esc(_t: str) -> str:
            return (
                _t.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
            )

        tab_segments: list[str] | None = None
        if _has_tab_char:
            tab_segments = [_esc(seg) for seg in text.split("\t")]
            text = ""
        else:
            text = _esc(text)
        styles: list[str] = []
        f = run.font
        fn = f.name
        ea_font: str = ""
        try:
            _rPr = run._element.find(qn("w:rPr"))
            if _rPr is not None:
                _rFonts = _rPr.find(qn("w:rFonts"))
                if _rFonts is not None:
                    ea_font = (
                        _rFonts.get(qn("w:eastAsia"), "")
                        or _rFonts.get(qn("w:cs"), "")
                        or ""
                    )
        except Exception:
            pass
        _font_family_stack = _build_css_font_family_stack(fn, ea_font)
        if _font_family_stack:
            styles.append(f"font-family:{_font_family_stack}")
        if not _is_toc_run:
            try:
                fsize = f.size
                if fsize is not None:
                    pt_val = round(fsize.pt, 1)
                    styles.append(f"font-size:{pt_val}pt")
            except Exception:
                pass
        try:
            color_xml = run._element.find(qn("w:rPr") + "/" + qn("w:color"))
            if color_xml is None:
                rpr = run._element.find(qn("w:rPr"))
                if rpr is not None:
                    color_xml = rpr.find(qn("w:color"))
            hex_color = _color_from_xml(color_xml)
            if hex_color:
                styles.append(f"color:{hex_color}")
        except Exception:
            try:
                rgb = f.color.rgb
                if rgb:
                    styles.append(f"color:#{rgb}")
            except Exception:
                pass
        decorations: list[str] = []
        _run_rpr = run._element.find(qn("w:rPr"))
        _run_bold_state = _read_bold_state_from_rpr(_run_rpr)
        if _run_bold_state is not None and (not _is_toc_run):
            styles.append(
                "font-weight:bold" if bool(_run_bold_state) else "font-weight:normal"
            )
        if f.italic:
            styles.append("font-style:italic")
        if f.underline and (not _is_toc_run):
            decorations.append("underline")
        if f.strike:
            decorations.append("line-through")
        if decorations:
            styles.append(f"text-decoration:{' '.join(decorations)}")
        if f.superscript:
            styles.append("vertical-align:super;font-size:smaller")
        elif f.subscript:
            styles.append("vertical-align:sub;font-size:smaller")
        try:
            highlight_xml = None
            rpr2 = run._element.find(qn("w:rPr"))
            if rpr2 is not None:
                highlight_xml = rpr2.find(qn("w:highlight"))
            if highlight_xml is not None:
                hval = highlight_xml.get(qn("w:val"), "")
                _HL_MAP = {
                    "yellow": "#FFFF00",
                    "green": "#00FF00",
                    "cyan": "#00FFFF",
                    "magenta": "#FF00FF",
                    "blue": "#0000FF",
                    "red": "#FF0000",
                    "darkBlue": "#00008B",
                    "darkCyan": "#008B8B",
                    "darkGreen": "#006400",
                    "darkMagenta": "#8B008B",
                    "darkRed": "#8B0000",
                    "darkYellow": "#808000",
                    "darkGray": "#A9A9A9",
                    "lightGray": "#D3D3D3",
                }
                if hval in _HL_MAP:
                    styles.append(f"background-color:{_HL_MAP[hval]}")
        except Exception:
            pass
        if tab_segments is not None:
            if styles:
                style_str = ";".join(styles)
                _styled = [
                    f'<span style="{style_str}">{seg}</span>' if seg else ""
                    for seg in tab_segments
                ]
                return _tab_html.join(_styled) + note_ref_html
            return _tab_html.join(tab_segments) + note_ref_html
        if styles:
            style_str = ";".join(styles)
            return f'<span style="{style_str}">{text}</span>' + note_ref_html
        return text + note_ref_html

    def _render_inline_hyperlink_html(
        hyperlink_el, para, doc, toc_class: str = ""
    ) -> str:
        from docx.text.run import Run

        rId = hyperlink_el.get(qn("r:id"))
        url = ""
        if rId:
            try:
                url = para.part.relationships[rId].target_ref
            except Exception:
                pass
        if not url:
            anchor_val = hyperlink_el.get(qn("w:anchor"), "")
            if anchor_val:
                url = "#" + anchor_val
        link_inner = ""
        for r_elem in hyperlink_el.findall(qn("w:r")):
            link_inner += _run_html(Run(r_elem, para), doc)
        if not link_inner:
            return ""
        esc_url = url.replace('"', "&quot;")
        target_attr = "" if url.startswith("#") else ' target="_blank"'
        if toc_class:
            link_style = (
                "display:flex;align-items:baseline;flex:1;min-width:0;color:#1155CC;"
            )
        else:
            link_style = "color:#1155CC;text-decoration:underline;"
        return f'<a href="{esc_url}"{target_attr} style="{link_style}">{link_inner}</a>'

    def _render_docx_revision_html(
        change_el,
        para,
        doc,
        *,
        action: str,
        review_id: str,
        toc_class: str = "",
        paired_insert_el=None,
    ) -> str:
        deleted_html = (
            _render_inline_children_html(change_el, para, doc, toc_class=toc_class)
            if change_el is not None
            else ""
        )
        inserted_html = (
            _render_inline_children_html(
                paired_insert_el, para, doc, toc_class=toc_class
            )
            if paired_insert_el is not None
            else ""
        )
        author_text = str(
            (
                paired_insert_el.get(qn("w:author"))
                if paired_insert_el is not None
                else ""
            )
            or (change_el.get(qn("w:author")) if change_el is not None else "")
            or ""
        ).strip()
        date_text = str(
            (paired_insert_el.get(qn("w:date")) if paired_insert_el is not None else "")
            or (change_el.get(qn("w:date")) if change_el is not None else "")
            or ""
        ).strip()
        wrapper_attrs = _docx_revision_data_attrs(
            review_id, action, author_text, date_text
        )
        if action == "replace":
            if not deleted_html and (not inserted_html):
                return ""
            return f'<span class="koto-docx-track-change koto-docx-track-change-replace"{wrapper_attrs}><span class="koto-docx-track-change-delete">{deleted_html}</span><span class="koto-docx-track-change-insert">{inserted_html}</span></span>'
        if action == "delete":
            if not deleted_html:
                return ""
            return f'<span class="koto-docx-track-change koto-docx-track-change-delete-only"{wrapper_attrs}><span class="koto-docx-track-change-delete">{deleted_html}</span></span>'
        if not inserted_html:
            return ""
        return f'<span class="koto-docx-track-change koto-docx-track-change-insert-only"{wrapper_attrs}><span class="koto-docx-track-change-insert">{inserted_html}</span></span>'

    def _render_inline_children_html(
        container_el,
        para,
        doc,
        toc_class: str = "",
        active_comment_ids: list[str] | None = None,
    ) -> str:
        from docx.text.run import Run

        parts: list[str] = []
        active_comments = active_comment_ids if active_comment_ids is not None else []
        children = list(container_el)
        index = 0
        skip_tags = {"bookmarkStart", "bookmarkEnd", "proofErr", "permStart", "permEnd"}

        def _append_with_comment_anchors(fragment: str) -> None:
            if not fragment:
                return
            wrapped = fragment
            for comment_id in reversed(active_comments):
                escaped_id = html.escape(comment_id, quote=True)
                wrapped = f'<span class="koto-docx-comment-anchor" data-koto-review-id="{escaped_id}" data-koto-review-source="docx_comment">{wrapped}</span>'
            parts.append(wrapped)

        while index < len(children):
            child = children[index]
            tag_name = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag_name == "commentRangeStart":
                comment_id = str(child.get(qn("w:id"), "") or "").strip()
                if comment_id and comment_id not in active_comments:
                    active_comments.append(comment_id)
                index += 1
                continue
            if tag_name == "commentRangeEnd":
                comment_id = str(child.get(qn("w:id"), "") or "").strip()
                if comment_id in active_comments:
                    active_comments.remove(comment_id)
                index += 1
                continue
            if tag_name == "hyperlink":
                _append_with_comment_anchors(
                    _render_inline_hyperlink_html(child, para, doc, toc_class=toc_class)
                )
                index += 1
                continue
            if tag_name == "r":
                _append_with_comment_anchors(_run_html(Run(child, para), doc))
                index += 1
                continue
            if tag_name == "del":
                change_id = child.get(qn("w:id"), "") or f"inline-del-{index}"
                next_index = index + 1
                while next_index < len(children):
                    next_tag = (
                        children[next_index].tag.split("}")[-1]
                        if "}" in children[next_index].tag
                        else children[next_index].tag
                    )
                    if next_tag in skip_tags:
                        next_index += 1
                        continue
                    break
                if next_index < len(children):
                    next_child = children[next_index]
                    next_tag = (
                        next_child.tag.split("}")[-1]
                        if "}" in next_child.tag
                        else next_child.tag
                    )
                    if next_tag == "ins":
                        _append_with_comment_anchors(
                            _render_docx_revision_html(
                                child,
                                para,
                                doc,
                                action="replace",
                                review_id=f"docx-revision-{change_id}",
                                toc_class=toc_class,
                                paired_insert_el=next_child,
                            )
                        )
                        index = next_index + 1
                        continue
                _append_with_comment_anchors(
                    _render_docx_revision_html(
                        child,
                        para,
                        doc,
                        action="delete",
                        review_id=f"docx-revision-{change_id}",
                        toc_class=toc_class,
                    )
                )
                index += 1
                continue
            if tag_name == "ins":
                change_id = child.get(qn("w:id"), "") or f"inline-ins-{index}"
                _append_with_comment_anchors(
                    _render_docx_revision_html(
                        child,
                        para,
                        doc,
                        action="insert",
                        review_id=f"docx-revision-{change_id}",
                        toc_class=toc_class,
                    )
                )
                index += 1
                continue
            index += 1
        return "".join(parts)

    return (
        _color_from_xml,
        _encode_image_part,
        _inline_img_html,
        _anchor_img_html,
        _run_html,
        _render_inline_hyperlink_html,
        _render_docx_revision_html,
        _render_inline_children_html,
    )
