"""Pure DOCX review-mark XML transformations used by task tools."""

from __future__ import annotations

from typing import Any, List

DOCX_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DOCX_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
DOCX_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
DOCX_COMMENTS_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
)
DOCX_COMMENTS_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
)
DOCX_COMMENT_MARKUP_TAGS = ("commentRangeStart", "commentRangeEnd", "commentReference")
DOCX_ACCEPT_REVIEW_REMOVE_TAGS = (
    "del",
    "moveFrom",
    "moveFromRangeStart",
    "moveFromRangeEnd",
)
DOCX_ACCEPT_REVIEW_UNWRAP_TAGS = ("ins", "moveTo")
DOCX_ACCEPT_REVIEW_METADATA_TAGS = (
    "moveToRangeStart",
    "moveToRangeEnd",
    "pPrChange",
    "rPrChange",
    "tblPrChange",
    "trPrChange",
    "tcPrChange",
    "sectPrChange",
    "numPrChange",
    "tblGridChange",
)


def normalize_docx_review_clear_scope(scope: str, aliases: dict[str, str]) -> str:
    normalized = str(scope or "").strip().lower()
    resolved = aliases.get(normalized, normalized)
    if resolved not in {"comments", "revisions", "all"}:
        raise ValueError("scope must be one of: comments, revisions, all")
    return resolved or "comments"


def _w_tag(local_name: str) -> str:
    return f"{{{DOCX_W_NS}}}{local_name}"


def _serialize_xml_root(root: Any) -> bytes:
    from lxml import etree

    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)


def _unwrap_xml_element(element: Any) -> bool:
    parent = element.getparent()
    if parent is None:
        return False
    index = parent.index(element)
    for offset, child in enumerate(list(element)):
        parent.insert(index + offset, child)
    parent.remove(element)
    return True


def _remove_comment_reference_element(element: Any) -> bool:
    parent = element.getparent()
    if parent is None:
        return False
    if parent.tag == _w_tag("r"):
        parent.remove(element)
        has_visible_children = any(child.tag != _w_tag("rPr") for child in parent)
        if not has_visible_children and not str(parent.text or "").strip():
            grandparent = parent.getparent()
            if grandparent is not None:
                grandparent.remove(parent)
        return True
    parent.remove(element)
    return True


def remove_docx_comment_markup(root: Any) -> int:
    count = 0
    namespaces = {"w": DOCX_W_NS}
    for tag_name in ("commentRangeStart", "commentRangeEnd"):
        for element in list(root.xpath(f".//w:{tag_name}", namespaces=namespaces)):
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)
                count += 1
    for element in list(root.xpath(".//w:commentReference", namespaces=namespaces)):
        if _remove_comment_reference_element(element):
            count += 1
    return count


def accept_docx_revision_markup(root: Any) -> int:
    count = 0
    namespaces = {"w": DOCX_W_NS}
    for tag_name in DOCX_ACCEPT_REVIEW_REMOVE_TAGS:
        for element in list(root.xpath(f".//w:{tag_name}", namespaces=namespaces)):
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)
                count += 1
    for tag_name in DOCX_ACCEPT_REVIEW_UNWRAP_TAGS:
        for element in list(root.xpath(f".//w:{tag_name}", namespaces=namespaces)):
            if _unwrap_xml_element(element):
                count += 1
    for tag_name in DOCX_ACCEPT_REVIEW_METADATA_TAGS:
        for element in list(root.xpath(f".//w:{tag_name}", namespaces=namespaces)):
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)
                count += 1
    return count


def remove_comments_relationships_xml(xml_bytes: bytes) -> tuple[bytes, int]:
    from lxml import etree

    root = etree.fromstring(xml_bytes)
    removed = 0
    relationship_tag = f"{{{DOCX_PKG_REL_NS}}}Relationship"
    for element in list(root):
        if element.tag != relationship_tag:
            continue
        target = str(element.get("Target") or "").strip().lower()
        relation_type = str(element.get("Type") or "").strip().lower()
        if (
            target.endswith("comments.xml")
            or relation_type == DOCX_COMMENTS_REL_TYPE.lower()
        ):
            root.remove(element)
            removed += 1
    return _serialize_xml_root(root), removed


def remove_comments_content_type_override(xml_bytes: bytes) -> tuple[bytes, int]:
    from lxml import etree

    root = etree.fromstring(xml_bytes)
    removed = 0
    override_tag = f"{{{DOCX_CT_NS}}}Override"
    for element in list(root):
        if element.tag != override_tag:
            continue
        part_name = str(element.get("PartName") or "").strip().lower()
        content_type = str(element.get("ContentType") or "").strip().lower()
        if (
            part_name == "/word/comments.xml"
            or content_type == DOCX_COMMENTS_CONTENT_TYPE.lower()
        ):
            root.remove(element)
            removed += 1
    return _serialize_xml_root(root), removed


def build_docx_review_clear_summary(
    scope: str,
    comments_removed: int,
    revisions_accepted: int,
    *,
    changed: bool,
) -> str:
    if not changed:
        return {
            "comments": "未发现可清除的 DOCX 批注。",
            "revisions": "未发现可清除的 DOCX 修订标记。",
        }.get(scope, "未发现可清除的 DOCX 批注或修订。")

    details: List[str] = []
    if scope in {"comments", "all"} and comments_removed:
        details.append(f"已清除 {comments_removed} 条批注")
    if scope in {"revisions", "all"} and revisions_accepted:
        details.append(f"已接受 {revisions_accepted} 处修订")
    if not details:
        details.append(
            {"comments": "已清除批注标记", "revisions": "已清除修订标记"}.get(
                scope, "已清除审阅标记"
            )
        )
    return "；".join(details)
