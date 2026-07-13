"""Evidence rules for user-visible, read-only file-task answers."""

from __future__ import annotations

import re
from typing import Any, Dict

_EXPLICIT_QUOTE_REQUEST = re.compile(
    r"(?:直接)?引(?:用|文)|原文(?:句|摘录|原话)|\b(?:quote|citation|cite)\b",
    re.IGNORECASE,
)
_BLOCK_QUOTE_LINE = re.compile(r'(?m)^\s*>\s*(?:“([^”\n]+)”|"([^"\n]+)")\s*$')
_BLOCK_QUOTE_PREFIX = re.compile(r"(?m)^\s*>\s+")


def requests_verbatim_quote(task: str) -> bool:
    """Whether the user explicitly asked for a verbatim source quotation."""
    return bool(_EXPLICIT_QUOTE_REQUEST.search(str(task or "")))


def source_grounding_policy(*, task: str, has_source_context: bool) -> Dict[str, Any]:
    """Build an explicit model-facing policy for file-backed analysis."""
    return {
        "mode": "source_grounded",
        "has_source_context": bool(has_source_context),
        "verbatim_quotes_requested": requests_verbatim_quote(task),
        "rules": [
            "Only state facts, names, figures, chapter claims, and conclusions supported by the read file context or tool results.",
            "Separate a source fact from your inference; label any inference as an interpretation or summary.",
            "Do not fabricate page numbers, citations, quotations, statistics, named cases, or author claims.",
            "Use a direct quotation only when the user explicitly asked for one and the exact quoted text appears in the read context.",
            "When a direct quotation was not requested, express conclusions as a summary without quotation marks or blockquote formatting.",
        ],
    }


def sanitize_unverified_readonly_quotes(*, task: str, text: str) -> str:
    """Downgrade quote formatting to a summary when no quote was requested.

    This is a last-line presentation guard, not a substitute for the model
    policy above. It prevents an unsupported paraphrase from being shown as a
    verbatim source quotation after the model has already produced it.
    """
    value = str(text or "")
    if not value or requests_verbatim_quote(task):
        return value
    # Only rewrite a complete Markdown quote line.  Models often mix Chinese
    # and ASCII quotation marks for short terms; attempting to rewrite inline
    # quotes can cross delimiters and corrupt otherwise grounded prose.
    value = _BLOCK_QUOTE_LINE.sub(
        lambda match: f"- 概括：{(match.group(1) or match.group(2) or '').strip()}",
        value,
    )
    return _BLOCK_QUOTE_PREFIX.sub("- 概括：", value)
