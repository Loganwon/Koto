# Copyright (C) 2024-2026 Koto AI. All rights reserved.
# SPDX-License-Identifier: LicenseRef-Koto-Proprietary
"""Resolve paragraph numbering properties without guessing from style names."""

from __future__ import annotations

from docx.oxml.ns import qn


def resolve_paragraph_numbering(paragraph, style_ref=None) -> tuple[int, int] | None:
    """Merge direct numPr and the nearest style/basedOn numPr properties.

    numId and ilvl inherit independently. An explicit numId=0 suppresses
    numbering, including numbering inherited from a paragraph style.
    """
    properties: dict[str, str | None] = {}

    def read_missing(element) -> None:
        ppr = element.find(qn("w:pPr"))
        numpr = ppr.find(qn("w:numPr")) if ppr is not None else None
        if numpr is None:
            return
        for name in ("numId", "ilvl"):
            child = numpr.find(qn("w:" + name))
            if name not in properties and child is not None:
                properties[name] = child.get(qn("w:val"))

    read_missing(paragraph._element)
    style = style_ref if style_ref is not None else paragraph.style
    visited = set()
    while style is not None and style._element not in visited:
        visited.add(style._element)
        read_missing(style._element)
        if "numId" in properties and "ilvl" in properties:
            break
        style = style.base_style

    try:
        num_id = int(properties["numId"])
        level = int(properties.get("ilvl", "0"))
    except (KeyError, TypeError, ValueError):
        return None
    if num_id <= 0 or not 0 <= level <= 8:
        return None
    return num_id, level
