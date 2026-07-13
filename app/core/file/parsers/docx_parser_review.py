# -*- coding: utf-8 -*-
"""DOCX comments, revisions, footnotes, and stable anchor extraction."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def _xml_local_name(tag: Any) -> str:
    text = str(tag or "")
    return text.split("}", 1)[-1] if "}" in text else text


def _xml_attr_by_local_name(el: Any, attr_name: str) -> str:
    if el is None:
        return ""
    target = str(attr_name or "").strip()
    if not target:
        return ""
    for key, value in getattr(el, "attrib", {}).items():
        if _xml_local_name(key) == target and value not in (None, ""):
            return str(value)
    return ""


def _coerce_docx_comment_flag(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "on", "yes"}:
        return True
    if normalized in {"0", "false", "off", "no"}:
        return False
    return None


def _merge_docx_comment_extension_parts(zf: Any, comments_map: dict[str, dict]) -> None:
    from xml.etree import ElementTree as ET

    if not comments_map:
        return

    names = set(zf.namelist())
    comment_order = list(comments_map.values())

    def _merge_extended_entry(comment: dict[str, Any], entry: dict[str, Any]) -> None:
        para_id = str(entry.get("para_id") or "").strip()
        if para_id:
            comment["para_id"] = para_id
        parent_para_id = str(entry.get("parent_para_id") or "").strip()
        if parent_para_id:
            comment["parent_para_id"] = parent_para_id
        durable_id = str(entry.get("durable_id") or "").strip()
        if durable_id:
            comment["durable_id"] = durable_id
        if "done" in entry and entry.get("done") is not None:
            comment["done"] = bool(entry.get("done"))
        if "resolved" in entry and entry.get("resolved") is not None:
            comment["resolved"] = bool(entry.get("resolved"))

    def _has_same_para_id(entry: dict[str, Any], comment: dict[str, Any]) -> bool:
        entry_para_id = str(entry.get("para_id") or "").strip()
        comment_para_id = str(comment.get("para_id") or "").strip()
        return bool(
            entry_para_id and comment_para_id and entry_para_id == comment_para_id
        )

    ext_by_para: dict[str, dict[str, Any]] = {}
    ext_sequence: list[dict[str, Any]] = []
    ext_name = (
        "word/commentsExtended.xml" if "word/commentsExtended.xml" in names else ""
    )
    if ext_name:
        try:
            ext_tree = ET.fromstring(zf.read(ext_name))
            for ext_el in ext_tree.iter():
                if _xml_local_name(getattr(ext_el, "tag", "")) != "commentEx":
                    continue
                entry: dict[str, Any] = {}
                para_id = _xml_attr_by_local_name(ext_el, "paraId").strip()
                parent_para_id = _xml_attr_by_local_name(ext_el, "paraIdParent").strip()
                done_state = _coerce_docx_comment_flag(
                    _xml_attr_by_local_name(ext_el, "done")
                )
                resolved_state = _coerce_docx_comment_flag(
                    _xml_attr_by_local_name(ext_el, "resolved")
                )
                if para_id:
                    entry["para_id"] = para_id
                if parent_para_id:
                    entry["parent_para_id"] = parent_para_id
                if done_state is not None:
                    entry["done"] = done_state
                if resolved_state is not None:
                    entry["resolved"] = resolved_state
                if not entry:
                    continue
                ext_sequence.append(entry)
                if para_id:
                    ext_by_para[para_id] = entry
        except Exception:
            pass

    matched_comment_ids: set[str] = set()
    for comment in comment_order:
        para_id = str(comment.get("para_id") or "").strip()
        if para_id and para_id in ext_by_para:
            _merge_extended_entry(comment, ext_by_para[para_id])
            matched_comment_ids.add(str(comment.get("id") or "").strip())

    unmatched_ext_entries = [
        entry
        for entry in ext_sequence
        if not any(_has_same_para_id(entry, comment) for comment in comment_order)
    ]
    unmatched_comments_for_ext = [
        comment
        for comment in comment_order
        if str(comment.get("id") or "").strip() not in matched_comment_ids
    ]
    if unmatched_ext_entries and len(unmatched_ext_entries) == len(
        unmatched_comments_for_ext
    ):
        for comment, entry in zip(unmatched_comments_for_ext, unmatched_ext_entries):
            _merge_extended_entry(comment, entry)

    ids_by_para: dict[str, dict[str, Any]] = {}
    ids_sequence: list[dict[str, Any]] = []
    ids_name = "word/commentsIds.xml" if "word/commentsIds.xml" in names else ""
    if ids_name:
        try:
            ids_tree = ET.fromstring(zf.read(ids_name))
            for id_el in ids_tree.iter():
                if _xml_local_name(getattr(id_el, "tag", "")) != "commentId":
                    continue
                para_id = _xml_attr_by_local_name(id_el, "paraId").strip()
                durable_id = (
                    _xml_attr_by_local_name(id_el, "durableId").strip()
                    or _xml_attr_by_local_name(id_el, "val").strip()
                    or _xml_attr_by_local_name(id_el, "id").strip()
                )
                if not durable_id:
                    continue
                entry = {"durable_id": durable_id}
                if para_id:
                    entry["para_id"] = para_id
                    ids_by_para[para_id] = entry
                ids_sequence.append(entry)
        except Exception:
            pass

    matched_durable_comment_ids: set[str] = set()
    for comment in comment_order:
        para_id = str(comment.get("para_id") or "").strip()
        if para_id and para_id in ids_by_para:
            _merge_extended_entry(comment, ids_by_para[para_id])
            matched_durable_comment_ids.add(str(comment.get("id") or "").strip())

    unmatched_id_entries = [
        entry
        for entry in ids_sequence
        if not any(_has_same_para_id(entry, comment) for comment in comment_order)
    ]
    unmatched_comments_for_ids = [
        comment
        for comment in comment_order
        if str(comment.get("id") or "").strip() not in matched_durable_comment_ids
        and not str(comment.get("durable_id") or "").strip()
    ]
    if unmatched_id_entries and len(unmatched_id_entries) == len(
        unmatched_comments_for_ids
    ):
        for comment, entry in zip(unmatched_comments_for_ids, unmatched_id_entries):
            _merge_extended_entry(comment, entry)

    para_to_comment_id = {
        str(comment.get("para_id") or "").strip(): str(comment.get("id") or "").strip()
        for comment in comment_order
        if str(comment.get("para_id") or "").strip()
        and str(comment.get("id") or "").strip()
    }
    for comment in comment_order:
        parent_para_id = str(comment.get("parent_para_id") or "").strip()
        if parent_para_id and parent_para_id in para_to_comment_id:
            comment["parent_id"] = para_to_comment_id[parent_para_id]


def _extract_docx_comments(file_path: str) -> list[dict[str, Any]]:
    """
    从 DOCX 的 word/comments.xml 提取批注信息。

    Returns:
        [{id, author, initials, date, text, anchor_text, para_id, parent_id, durable_id, done}]
        若无批注或解析失败返回空列表。
    """
    import zipfile
    from xml.etree import ElementTree as ET

    ns = {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
    }

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            # ── 解析 comments.xml ────────────────────────────────────
            if "word/comments.xml" not in zf.namelist():
                return []
            comments_xml = zf.read("word/comments.xml")
            comments_tree = ET.fromstring(comments_xml)
            comments_map: dict[str, dict] = {}
            for c in comments_tree.findall(".//w:comment", ns):
                cid = c.get(f"{{{ns['w']}}}id", "")
                author = c.get(f"{{{ns['w']}}}author", "")
                date = c.get(f"{{{ns['w']}}}date", "")
                initials = _xml_attr_by_local_name(c, "initials").strip()
                para_id = _xml_attr_by_local_name(c, "paraId").strip()
                parent_para_id = _xml_attr_by_local_name(c, "paraIdParent").strip()
                done_state = _coerce_docx_comment_flag(
                    _xml_attr_by_local_name(c, "done")
                )
                resolved_state = _coerce_docx_comment_flag(
                    _xml_attr_by_local_name(c, "resolved")
                )
                # 拼接所有 <w:t> 文本
                texts = [t.text or "" for t in c.findall(".//w:t", ns)]
                comment_payload = {
                    "id": cid,
                    "author": author,
                    "initials": initials,
                    "date": date,
                    "text": "".join(texts).strip(),
                    "anchor_text": "",
                    "anchor_start_offset": None,
                    "anchor_end_offset": None,
                    "para_id": para_id,
                    "parent_para_id": parent_para_id,
                    "parent_id": "",
                    "durable_id": "",
                }
                if done_state is not None:
                    comment_payload["done"] = done_state
                if resolved_state is not None:
                    comment_payload["resolved"] = resolved_state
                comments_map[cid] = comment_payload

            if not comments_map:
                return []

            _merge_docx_comment_extension_parts(zf, comments_map)

            # ── 从 document.xml 提取批注锚定原文 ────────────────────
            if "word/document.xml" in zf.namelist():
                doc_xml = zf.read("word/document.xml")
                doc_tree = ET.fromstring(doc_xml)
                # 构建 commentRangeStart id → 对应的 body 元素范围
                body = doc_tree.find(".//w:body", ns)
                if body is not None:
                    _extract_anchor_texts(body, comments_map, ns)

            return list(comments_map.values())
    except Exception as exc:
        logger.debug("[DocxParser] 批注提取失败 (非致命): %s", exc)
        return []


def _collect_docx_text_from_element(el: Any, *, include_deleted: bool = True) -> str:
    parts: list[str] = []

    def _walk(node: Any, *, deleted: bool = False) -> None:
        tag = _xml_local_name(getattr(node, "tag", ""))
        if tag == "del":
            deleted = True
        if deleted and not include_deleted:
            return
        if tag == "instrText":
            return
        if tag in {"t", "delText"} and getattr(node, "text", None):
            parts.append(str(node.text))
        elif tag in {"tab", "br", "cr"}:
            parts.append(" ")
        elif tag in {"noBreakHyphen", "softHyphen"}:
            parts.append("-")
        for child in list(node):
            _walk(child, deleted=deleted)

    _walk(el)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _format_docx_revision_rationale(change_kind: str, author: str, date: str) -> str:
    label_map = {
        "replace": "原生修订",
        "delete": "原生删除",
        "insert": "原生插入",
    }
    parts = [label_map.get(change_kind, "原生修订")]
    author_text = str(author or "").strip()
    date_text = str(date or "").strip()
    if author_text:
        parts.append(author_text)
    if date_text:
        parts.append(date_text)
    return " · ".join(parts)


def _extract_docx_revisions(file_path: str) -> list[dict[str, Any]]:
    import zipfile
    from xml.etree import ElementTree as ET

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    skip_tags = {
        "bookmarkStart",
        "bookmarkEnd",
        "proofErr",
        "permStart",
        "permEnd",
        "commentRangeStart",
        "commentRangeEnd",
    }

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            if "word/document.xml" not in zf.namelist():
                return []

            doc_tree = ET.fromstring(zf.read("word/document.xml"))
            body = doc_tree.find(".//w:body", ns)
            if body is None:
                return []

            revisions: list[dict[str, Any]] = []
            for paragraph_index, p_el in enumerate(body.findall(".//w:p", ns), start=1):
                paragraph_text = _collect_docx_text_from_element(
                    p_el, include_deleted=False
                )
                children = list(p_el)
                child_index = 0

                while child_index < len(children):
                    child = children[child_index]
                    tag = _xml_local_name(getattr(child, "tag", ""))
                    if tag not in {"del", "ins"}:
                        child_index += 1
                        continue

                    author = child.get(f"{{{ns['w']}}}author", "")
                    date = child.get(f"{{{ns['w']}}}date", "")
                    change_id = (
                        child.get(f"{{{ns['w']}}}id", "")
                        or f"{paragraph_index}-{child_index}"
                    )

                    if tag == "del":
                        deleted_text = _collect_docx_text_from_element(
                            child, include_deleted=True
                        )
                        if not deleted_text:
                            child_index += 1
                            continue

                        next_index = child_index + 1
                        while (
                            next_index < len(children)
                            and _xml_local_name(
                                getattr(children[next_index], "tag", "")
                            )
                            in skip_tags
                        ):
                            next_index += 1

                        if (
                            next_index < len(children)
                            and _xml_local_name(
                                getattr(children[next_index], "tag", "")
                            )
                            == "ins"
                        ):
                            ins_child = children[next_index]
                            inserted_text = _collect_docx_text_from_element(
                                ins_child, include_deleted=True
                            )
                            ins_author = (
                                ins_child.get(f"{{{ns['w']}}}author", "") or author
                            )
                            ins_date = ins_child.get(f"{{{ns['w']}}}date", "") or date
                            revisions.append(
                                {
                                    "id": f"docx-revision-{change_id}",
                                    "source": "docx_revision",
                                    "action": "replace",
                                    "original_text": deleted_text,
                                    "proposed_text": inserted_text,
                                    "anchor_text": paragraph_text
                                    or inserted_text
                                    or deleted_text,
                                    "rationale": _format_docx_revision_rationale(
                                        "replace", ins_author, ins_date
                                    ),
                                    "author": ins_author,
                                    "date": ins_date,
                                    "read_only": True,
                                    "apply_disabled": True,
                                }
                            )
                            child_index = next_index + 1
                            continue

                        revisions.append(
                            {
                                "id": f"docx-revision-{change_id}",
                                "source": "docx_revision",
                                "action": "delete",
                                "original_text": deleted_text,
                                "proposed_text": "",
                                "anchor_text": paragraph_text or deleted_text,
                                "rationale": _format_docx_revision_rationale(
                                    "delete", author, date
                                ),
                                "author": author,
                                "date": date,
                                "read_only": True,
                                "apply_disabled": True,
                            }
                        )
                        child_index += 1
                        continue

                    inserted_text = _collect_docx_text_from_element(
                        child, include_deleted=True
                    )
                    if inserted_text:
                        revisions.append(
                            {
                                "id": f"docx-revision-{change_id}",
                                "source": "docx_revision",
                                "action": "insert",
                                "original_text": "",
                                "proposed_text": inserted_text,
                                "anchor_text": paragraph_text or inserted_text,
                                "rationale": _format_docx_revision_rationale(
                                    "insert", author, date
                                ),
                                "author": author,
                                "date": date,
                                "read_only": True,
                                "apply_disabled": True,
                            }
                        )
                    child_index += 1

            return revisions
    except Exception as exc:
        logger.debug("[DocxParser] 修订提取失败 (非致命): %s", exc)
        return []


def _extract_docx_footnotes(file_path: str) -> list[dict[str, Any]]:
    """Extract referenced DOCX footnotes from word/footnotes.xml."""
    import zipfile
    from xml.etree import ElementTree as ET

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

    def _local_name(tag: str) -> str:
        return tag.split("}", 1)[-1] if "}" in tag else tag

    def _collect_note_text(note_el: Any) -> str:
        parts: list[str] = []
        for child in note_el.iter():
            tag = _local_name(getattr(child, "tag", ""))
            if tag == "t" and child.text:
                parts.append(child.text)
            elif tag in {"tab", "br", "cr"}:
                parts.append(" ")
        return re.sub(r"\s+", " ", "".join(parts)).strip()

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            if "word/footnotes.xml" not in zf.namelist():
                return []

            ref_counts: dict[str, int] = {}
            if "word/document.xml" in zf.namelist():
                doc_tree = ET.fromstring(zf.read("word/document.xml"))
                for ref_el in doc_tree.findall(".//w:footnoteReference", ns):
                    note_id = str(ref_el.get(f"{{{ns['w']}}}id") or "").strip()
                    if note_id:
                        ref_counts[note_id] = ref_counts.get(note_id, 0) + 1

            footnotes_tree = ET.fromstring(zf.read("word/footnotes.xml"))
            footnotes: list[dict[str, Any]] = []
            for footnote_el in footnotes_tree.findall(".//w:footnote", ns):
                note_id = str(footnote_el.get(f"{{{ns['w']}}}id") or "").strip()
                if not note_id:
                    continue

                reference_count = ref_counts.get(note_id, 0)
                if reference_count <= 0:
                    continue

                footnotes.append(
                    {
                        "id": note_id,
                        "text": _collect_note_text(footnote_el),
                        "type": str(
                            footnote_el.get(f"{{{ns['w']}}}type") or "footnote"
                        ),
                        "reference_count": reference_count,
                    }
                )

            return footnotes
    except Exception as exc:
        logger.debug("[DocxParser] 脚注提取失败 (非致命): %s", exc)
        return []


def count_docx_visible_chars(file_path: str) -> int:
    """Approximate Word/WPS-style count from visible main-document text.

    This intentionally counts only visible text in ``word/document.xml`` so the
    result is not limited by AI preview truncation and does not pull in header,
    footer, comment, or field-instruction text.
    """
    import zipfile
    from xml.etree import ElementTree as ET

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

    def _local_name(tag: str) -> str:
        return tag.split("}", 1)[-1] if "}" in tag else tag

    parts: list[str] = []

    def _walk(el: Any, *, deleted: bool = False) -> None:
        tag = _local_name(getattr(el, "tag", ""))
        if tag == "del":
            deleted = True
        if deleted:
            for child in el:
                _walk(child, deleted=True)
            return
        if tag == "instrText":
            return
        if tag == "t" and el.text:
            parts.append(el.text)
        elif tag in {"tab", "br", "cr"}:
            parts.append(" ")
        elif tag in {"noBreakHyphen", "softHyphen"}:
            parts.append("-")
        for child in el:
            _walk(child, deleted=deleted)

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            if "word/document.xml" not in zf.namelist():
                return 0
            doc_tree = ET.fromstring(zf.read("word/document.xml"))
            body = doc_tree.find(".//w:body", ns)
            if body is None:
                return 0
            _walk(body)
    except Exception as exc:
        logger.debug("[DocxParser] DOCX 可见文字统计失败 (非致命): %s", exc)
        return 0

    return len(re.sub(r"\s+", "", "".join(parts)))


def _extract_anchor_texts(
    body_el: Any, comments_map: dict[str, dict], ns: dict[str, str]
) -> None:
    """遍历 document.xml body，提取批注锚点文本与稳定定位元数据。"""

    events: list[tuple[str, str]] = []

    def _walk(el: Any) -> None:
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag == "commentRangeStart":
            cid = el.get(f"{{{ns['w']}}}id", "")
            events.append(("start", cid))
        elif tag == "commentRangeEnd":
            cid = el.get(f"{{{ns['w']}}}id", "")
            events.append(("end", cid))
        elif tag == "t" and el.text:
            events.append(("text", el.text))
        elif tag in {"tab", "br", "cr"}:
            events.append(("text", " "))
        elif tag in {"noBreakHyphen", "softHyphen"}:
            events.append(("text", "-"))
        for child in el:
            _walk(child)
        if tag == "p":
            events.append(("paragraph_break", "\n"))

    _walk(body_el)

    active_ids: set[str] = set()
    full_text_parts: list[str] = []
    cursor = 0

    for etype, val in events:
        if etype == "start":
            if (
                val in comments_map
                and comments_map[val].get("anchor_start_offset") is None
            ):
                comments_map[val]["anchor_start_offset"] = cursor
            active_ids.add(val)
            continue
        if etype == "end":
            if (
                val in comments_map
                and comments_map[val].get("anchor_end_offset") is None
            ):
                comments_map[val]["anchor_end_offset"] = cursor
            active_ids.discard(val)
            continue
        if etype == "paragraph_break":
            full_text_parts.append(val)
            cursor += len(val)
            continue
        if etype == "text" and active_ids:
            for cid in active_ids:
                if cid in comments_map:
                    comments_map[cid]["anchor_text"] += val
        if etype == "text":
            full_text_parts.append(val)
            cursor += len(val)

    full_text = "".join(full_text_parts)
    for cid in active_ids:
        if cid in comments_map and comments_map[cid].get("anchor_end_offset") is None:
            comments_map[cid]["anchor_end_offset"] = cursor

    for comment in comments_map.values():
        start_offset = comment.get("anchor_start_offset")
        end_offset = comment.get("anchor_end_offset")
        if not isinstance(start_offset, int) or not isinstance(end_offset, int):
            continue
        if end_offset < start_offset:
            continue

        comment["anchor_context_before"] = full_text[
            max(0, start_offset - 48) : start_offset
        ]
        comment["anchor_context_after"] = full_text[end_offset : end_offset + 48]

        anchor_text = str(comment.get("anchor_text") or "")
        if not anchor_text:
            continue

        occurrence = 0
        search_from = 0
        while search_from < start_offset:
            hit = full_text.find(anchor_text, search_from)
            if hit == -1 or hit >= start_offset:
                break
            occurrence += 1
            search_from = hit + max(len(anchor_text), 1)
        comment["anchor_occurrence"] = occurrence
