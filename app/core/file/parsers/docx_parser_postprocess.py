# -*- coding: utf-8 -*-
"""HTML post-processing helpers for the DOCX parser facade."""

from __future__ import annotations

import re


def deduplicate_images(html: str) -> str:
    """Remove duplicate inline base64 image tags while preserving first occurrence."""
    if html.count("<img") < 2:
        return html
    seen_prefixes: set[str] = set()
    result_parts: list[str] = []
    pos = 0
    for match in re.finditer(r"<img\s[^>]*>", html, re.IGNORECASE):
        image_tag = match.group()
        src_match = re.search(r'src="(data:[^"]{0,200})', image_tag)
        if src_match and src_match.group(1) in seen_prefixes:
            result_parts.append(html[pos : match.start()])
            pos = match.end()
            continue
        if src_match:
            seen_prefixes.add(src_match.group(1))
        result_parts.append(html[pos : match.end()])
        pos = match.end()
    result_parts.append(html[pos:])
    return "".join(result_parts)
