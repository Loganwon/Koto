"""Component module extracted from docx_parser.py -- god-file refactoring Phase 3."""

from __future__ import annotations

import base64
import logging
import mimetypes

from app.core.file.image_utils import compress_image_bytes as _compress_image_bytes

logger = logging.getLogger(__name__)


def _get_floating_image_srcs(docx_path: str) -> list[str]:
    """
    Return base64 data URIs for floating (anchor-positioned) images in a DOCX.

    mammoth only converts <wp:inline> images; <wp:anchor> images (floated to a
    fixed page position, e.g. a resume photo) are silently skipped.
    Uses namespace-aware ElementTree parsing so attribute order never matters.
    """
    import xml.etree.ElementTree as _ET
    import zipfile as _zipfile

    # Full OOXML namespace URIs — must match exactly (not prefix aliases)
    IMG_TYPE = (
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
    )
    WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
    R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

    result: list[str] = []
    try:
        with _zipfile.ZipFile(docx_path, "r") as z:
            file_list = z.namelist()

            # Locate document.xml and its rels (case-insensitive for robustness)
            doc_name = next(
                (n for n in file_list if n.lower() == "word/document.xml"), None
            )
            rels_name = next(
                (n for n in file_list if n.lower() == "word/_rels/document.xml.rels"),
                None,
            )
            if not doc_name or not rels_name:
                return result

            # ── rel_id → media path via ElementTree (handles ANY attribute order) ──
            rels_root = _ET.fromstring(z.read(rels_name))
            rel_map: dict[str, str] = {}
            for rel in rels_root:
                rid = rel.get("Id", "")
                rtype = rel.get("Type", "")
                tgt = rel.get("Target", "")
                if rid and IMG_TYPE in rtype and tgt:
                    rel_map[rid] = tgt if tgt.startswith("word/") else f"word/{tgt}"

            # ── Walk document.xml, separate inline vs anchor image embed IDs ──
            doc_root = _ET.fromstring(z.read(doc_name))

            inline_ids: set[str] = set()
            floating_ids: list[str] = []

            for inline in doc_root.iter(f"{{{WP_NS}}}inline"):
                for blip in inline.iter(f"{{{A_NS}}}blip"):
                    eid = blip.get(f"{{{R_NS}}}embed")
                    if eid:
                        inline_ids.add(eid)

            for anchor in doc_root.iter(f"{{{WP_NS}}}anchor"):
                for blip in anchor.iter(f"{{{A_NS}}}blip"):
                    eid = blip.get(f"{{{R_NS}}}embed")
                    if eid:
                        floating_ids.append(eid)

            seen: set[str] = set()
            for rel_id in floating_ids:
                if rel_id in inline_ids or rel_id in seen:
                    continue
                seen.add(rel_id)
                media_path = rel_map.get(rel_id)
                if not media_path:
                    logger.debug(
                        "[floating_imgs] no media path for rel_id=%s; rel_map keys=%s",
                        rel_id,
                        list(rel_map)[:8],
                    )
                    continue
                try:
                    img_bytes = z.read(media_path)
                    mime = mimetypes.guess_type(media_path)[0] or "image/png"
                    img_bytes, mime = _compress_image_bytes(img_bytes, mime)
                    b64 = base64.b64encode(img_bytes).decode("ascii")
                    result.append(f"data:{mime};base64,{b64}")
                except Exception as e:
                    logger.debug("[floating_imgs] failed to read %s: %s", media_path, e)
    except Exception as exc:
        logger.warning("[_get_floating_image_srcs] %s", exc)
    return result


def _extract_images_from_paragraphs(html: str) -> str:
    """将 <p> 标签内的 <img> 元素移到段落外部，避免编辑器路径错误。

    TipTap/ProseMirror 不允许图片 void 元素嵌套在段落块元素中，否则在
    规范化时会抛出路径错误。

    规则：
    - 若段落只包含一个 <img>（忽略空白），则整个 <p>...</p> 替换为裸 <img>。
    - 若段落混合了文字和图片，则将 <img> 提取出来放在段落之后。
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return html

    def _has_visible_paragraph_content(tag) -> bool:
        for child in tag.children:
            if getattr(child, "name", None) == "img":
                continue
            if getattr(child, "name", None) == "br":
                continue
            text = str(child).strip()
            if text:
                return True
        return False

    soup = BeautifulSoup(html, "html.parser")
    changed = False

    def _extract_paragraph_images(p_tag, *, wrap_in_paragraph: bool) -> None:
        nonlocal changed
        imgs = list(p_tag.find_all("img"))
        if not imgs:
            return

        insert_after = p_tag
        for img in imgs:
            extracted_img = img.extract()
            if wrap_in_paragraph:
                extracted_img["data-koto-layout"] = (
                    extracted_img.get("data-koto-layout") or "top-bottom"
                )
                img_row = soup.new_tag("p")
                img_row["class"] = "koto-docx-image-row"
                img_row.append(extracted_img)
                insert_after.insert_after(img_row)
                insert_after = img_row
            else:
                insert_after.insert_after(extracted_img)
                insert_after = extracted_img
            changed = True

        if not _has_visible_paragraph_content(p_tag):
            p_tag.decompose()

    for p_tag in list(soup.find_all("p")):
        if "koto-docx-image-row" in (p_tag.get("class") or []):
            continue
        if getattr(p_tag.parent, "name", "") in ("td", "th"):
            continue
        imgs = list(p_tag.find_all("img"))
        if not imgs:
            continue
        _extract_paragraph_images(p_tag, wrap_in_paragraph=False)

    return str(soup) if changed else html
