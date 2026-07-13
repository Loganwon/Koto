"""Reusable execution primitives for deterministic document-review rules."""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, List, Tuple


Rule = Tuple[str, Callable[[re.Match[str], str], Dict[str, Any]]]


def append_pattern_annotations(
    annotations: List[Dict[str, Any]],
    content: str,
    rules: Iterable[Rule],
    *,
    min_length: int,
    max_length: int,
    truncate_to: int | None = None,
) -> None:
    """Apply regex rules with one consistent anchor-length safety policy."""
    for pattern, suggestion in rules:
        for match in re.finditer(pattern, content):
            text = match.group(0)
            if truncate_to is not None:
                text = text[:truncate_to]
            if min_length <= len(text) <= max_length:
                annotation = suggestion(match, text)
                if isinstance(annotation, dict):
                    annotations.append(annotation)
