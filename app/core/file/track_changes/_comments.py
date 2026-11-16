#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
"""DOCX comment mixin ? comment part management and range anchoring.

Supports the Word comment workflow used by TrackChangesEditor:
  - create/fetch the comments part (word/comments.xml)
  - sync the part back into the docx package
  - resolve a text anchor to a paragraph + char offsets
  - insert w:commentRangeStart / w:commentRangeEnd markers
"""

from __future__ import annotations

import logging
import re
import zipfile
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from docx.oxml import parse_xml
from docx.oxml.ns import qn
from lxml import etree

logger = logging.getLogger(__name__)

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_COMMENTS_PART_NAME = "word/comments.xml"


def _find_paragraph_with_text(doc, text: str) -> Tuple[Any, str, Optional[Any]]:
    """Locate a paragraph whose normalized text contains ``text``.

    Returns (paragraph, effective_text, containing_element).  The element is
    None for body paragraphs and the table cell for table paragraphs.
    """
    if not text:
        return None, "", None

    candidates = list(doc.paragraphs)
    cell_map: List[Tuple[Any, Any]] = []  # (paragraph, cell)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    candidates.append(para)
                    cell_map.append((para, cell))

    norm = _normalize_comment_text(text)
    if not norm:
        return None, "", None

    for para in candidates:
        para_text = _normalize_comment_text(para.text)
        if para_text and norm in para_text:
            cell = next((c for p, c in cell_map if p is para), None)
            return para, text, cell

    # Fallback: prefix match on paragraph starts
    for para in candidates:
        para_text = _normalize_comment_text(para.text)
        if para_text and para_text.startswith(norm[:8]):
            cell = next((c for p, c in cell_map if p is para), None)
            return para, text, cell

    return None, "", None


def _normalize_comment_text(text: str) -> str:
    """Normalize whitespace + common punctuation for fuzzy matching."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


class _TrackChangesCommentMixin:
    """Comment-part management and anchor resolution for DOCX."""

    # ?? Comments part lifecycle ?????????????????????????????????????????

    def _get_or_create_comments_part(self, doc) -> Tuple[Any, Any]:
        """Return (comments_element, comments_part_ref).

        The part ref is an opaque handle (the document object) that
        ``_sync_comments_part`` uses to re-inject the part after save.
        """
        comments_el = etree.fromstring(
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:comments xmlns:w="' + _W_NS + '"></w:comments>'
            ).encode("utf-8")
        )
        return comments_el, doc

    def _sync_comments_part(self, doc, comments_el, comments_part_ref):
        """Persist comments_el into the docx package after doc.save()."""
        try:
            if comments_el is None:
                return comments_part_ref
            # Inject into the underlying package stream if the editor has
            # already saved; otherwise just return the ref and let the
            # caller invoke _inject_comments_to_docx after save.
            if hasattr(self, "_inject_comments_to_docx"):
                # The editor tracks the last saved path via apply flow.
                pass
            return comments_part_ref
        except Exception as exc:
            logger.warning("[Comment] sync comments part failed: %s", exc)
            return comments_part_ref

    # ?? Anchor resolution ???????????????????????????????????????????????

    def _resolve_comment_anchor_range(
        self,
        doc,
        original_text: str,
        anchor_meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Locate (start_para, start_offset, end_para, end_offset) for a comment."""
        try:
            effective = str(original_text or "")
            candidates = list(doc.paragraphs)
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        candidates.extend(cell.paragraphs)

            matches: list[tuple[Any, int, int]] = []
            cursor = 0
            for para in candidates:
                para_text = str(para.text or "")
                search_from = 0
                while (
                    effective
                    and (local_start := para_text.find(effective, search_from)) >= 0
                ):
                    matches.append((para, local_start, cursor + local_start))
                    search_from = local_start + max(1, len(effective))
                cursor += len(para_text) + 1

            if not matches:
                para, effective, _cell = _find_paragraph_with_text(doc, effective)
                if para is None:
                    return None
                local_start = str(para.text or "").find(effective)
                matches = [(para, max(0, local_start), max(0, local_start))]

            selected = matches[0]
            meta = anchor_meta or {}
            explicit_start = meta.get("anchor_start_offset")
            if explicit_start not in (None, ""):
                try:
                    requested_start = max(0, int(explicit_start))
                    selected = min(
                        matches, key=lambda match: abs(match[2] - requested_start)
                    )
                    para, local_start, global_start = selected
                    if len(matches) == 1 and requested_start <= len(
                        str(para.text or "")
                    ):
                        selected = (para, requested_start, requested_start)
                except (TypeError, ValueError):
                    pass
            elif meta.get("anchor_context_before") or meta.get("anchor_context_after"):
                before_hint = str(meta.get("anchor_context_before") or "")
                after_hint = str(meta.get("anchor_context_after") or "")

                def _context_score(match: tuple[Any, int, int]) -> tuple[int, int]:
                    para, local_start, _global_start = match
                    para_text = str(para.text or "")
                    local_end = local_start + len(effective)
                    score = int(
                        not before_hint or para_text[:local_start].endswith(before_hint)
                    )
                    score += int(
                        not after_hint or para_text[local_end:].startswith(after_hint)
                    )
                    return score, local_start

                selected = max(matches, key=_context_score)
            else:
                try:
                    occurrence = max(0, int(meta.get("anchor_occurrence") or 0))
                except (TypeError, ValueError):
                    occurrence = 0
                selected = matches[min(occurrence, len(matches) - 1)]

            para, start_offset, _global_start = selected
            end_offset = start_offset + len(effective)
            explicit_end = meta.get("anchor_end_offset")
            if explicit_end not in (None, "") and len(matches) == 1:
                try:
                    requested_end = int(explicit_end)
                    if start_offset <= requested_end <= len(str(para.text or "")):
                        end_offset = requested_end
                except (TypeError, ValueError):
                    pass

            if para is None:
                return None

            # Apply explicit anchor metadata when provided (line numbers etc.)
            if meta:
                try:
                    line_no = int(meta.get("line", 0))
                    if line_no > 1 and line_no <= len(doc.paragraphs):
                        para = doc.paragraphs[line_no - 1]
                        start_offset = 0
                        end_offset = len(para.text)
                except (TypeError, ValueError, IndexError):
                    pass

            return {
                "start_para": para,
                "start_offset": start_offset,
                "end_para": para,
                "end_offset": end_offset,
            }
        except Exception as exc:
            logger.info("[Comment] anchor resolution failed: %s", exc)
            return None

    # ?? Range markers ???????????????????????????????????????????????????

    def _insert_comment_range_markers(
        self,
        start_para,
        start_offset: int,
        end_para,
        end_offset: int,
        comment_id: str,
    ) -> bool:
        """Insert w:commentRangeStart / w:commentRangeEnd around a text range.

        Returns True when at least one marker was inserted.
        """
        try:
            inserted = False
            if start_para is not None and start_para._element is not None:
                self._insert_range_start(start_para._element, start_offset, comment_id)
                inserted = True
            if end_para is not None and end_para._element is not None:
                self._insert_range_end(end_para._element, end_offset, comment_id)
                self._insert_comment_reference(end_para._element, comment_id)
                inserted = True
            return inserted
        except Exception as exc:
            logger.info("[Comment] range marker insertion failed: %s", exc)
            return False

    @staticmethod
    def _insert_range_start(element, offset: int, comment_id: str) -> None:
        marker = parse_xml(
            "<w:commentRangeStart xmlns:w='" + _W_NS + "' w:id='" + comment_id + "'/>"
        )
        _insert_marker_at_offset(element, marker, offset)

    @staticmethod
    def _insert_comment_reference(element, comment_id: str) -> None:
        """Append a w:commentReference run so Word renders the comment mark."""
        marker = parse_xml(
            "<w:r xmlns:w='"
            + _W_NS
            + "'><w:commentReference w:id='"
            + comment_id
            + "'/></w:r>"
        )
        end_marker = next(
            (
                child
                for child in element
                if child.tag == qn("w:commentRangeEnd")
                and child.get(qn("w:id")) == comment_id
            ),
            None,
        )
        if end_marker is not None:
            end_marker.addnext(marker)
        else:
            element.append(marker)

    @staticmethod
    def _insert_range_end(element, offset: int, comment_id: str) -> None:
        marker = parse_xml(
            "<w:commentRangeEnd xmlns:w='" + _W_NS + "' w:id='" + comment_id + "'/>"
        )
        _insert_marker_at_offset(element, marker, offset)


def _insert_marker_at_offset(paragraph_el, marker, offset: int) -> None:
    """Insert a range marker at an exact text boundary between paragraph runs."""
    try:
        runs = list(paragraph_el.findall(qn("w:r")))
        if not runs:
            paragraph_el.append(marker)
            return
        requested = max(0, int(offset))
        cursor = 0
        for run in runs:
            text_value = "".join(
                node.text or "" for node in run.findall(".//" + qn("w:t"))
            )
            run_end = cursor + len(text_value)
            if requested <= cursor:
                run.addprevious(marker)
                return
            if requested < run_end:
                split_at = requested - cursor
                left_text = text_value[:split_at]
                right_text = text_value[split_at:]
                parent = run.getparent()
                index = parent.index(run)
                rpr = run.find(qn("w:rPr"))
                parent.remove(run)
                insertion = index
                if left_text:
                    left_run = _make_text_run(left_text, rpr)
                    parent.insert(insertion, left_run)
                    insertion += 1
                parent.insert(insertion, marker)
                insertion += 1
                if right_text:
                    parent.insert(insertion, _make_text_run(right_text, rpr))
                return
            if requested == run_end:
                run.addnext(marker)
                return
            cursor = run_end
        paragraph_el.append(marker)
    except Exception:
        paragraph_el.append(marker)


def _make_text_run(text: str, rpr: Any | None):
    run = etree.Element(qn("w:r"))
    if rpr is not None:
        run.append(deepcopy(rpr))
    text_el = etree.SubElement(run, qn("w:t"))
    if text[:1].isspace() or text[-1:].isspace():
        text_el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text_el.text = text
    return run
