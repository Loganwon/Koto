"""Pure DOCX-template transformations used by :mod:`task_tools`.

Path policy and result envelopes stay in the public tool module; this module
contains only document-content transformations and must not import it back.
"""
from __future__ import annotations

from typing import Any, Dict


def replace_docx_placeholders_in_paragraph(
    paragraph: Any, replacements: Dict[str, str]
) -> tuple[bool, str, str]:
    """Replace placeholders while retaining existing runs whenever possible."""
    before = paragraph.text
    after = before
    for key, value in replacements.items():
        after = after.replace(key, value)
    if after == before:
        return False, before, after
    for run in paragraph.runs:
        run_text = run.text
        for key, value in replacements.items():
            run_text = run_text.replace(key, value)
        run.text = run_text
    if paragraph.text != after:
        paragraph.text = after
    return True, before, after
