# -*- coding: utf-8 -*-
"""Shared, user-visible DOCX style fallback handling for task tools."""
from __future__ import annotations

from typing import Any


def apply_docx_style(target: Any, style_name: Any) -> str:
    """Apply a Word style and describe a non-fatal fallback for task results.

    User-provided templates often omit built-in styles such as ``Caption``.
    The content is still valid when that happens, but the task result must say
    that it kept the target's existing/default formatting instead of silently
    claiming full fidelity.
    """
    style = str(style_name or "").strip()
    if not style:
        return ""
    try:
        target.style = style
    except Exception as exc:
        return (
            f"未能应用 Word 样式“{style}”，已保留默认或现有格式"
            f"（{type(exc).__name__}）。"
        )
    return ""
