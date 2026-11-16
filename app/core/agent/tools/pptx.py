"""Domain module - PPTX tools."""

from __future__ import annotations

from app.core.agent.toolkits.foundation.pptx import add_pptx_slides as _pptx_add_slides
from app.core.agent.toolkits.foundation.pptx import (
    design_pptx_theme_layout as _pptx_design_theme_layout,
)
from app.core.agent.toolkits.foundation.pptx import (
    write_pptx_slides as _pptx_write_slides,
)

from ._internal_formats import _pptx_operation_context


def _read_pptx_slide_window(
    path: str,
    *,
    max_chars: int,
    start: int,
    end: int,
) -> str:
    from pptx import Presentation

    presentation = Presentation(path)
    start = max(1, int(start or 1))
    end = max(start, int(end or start))
    parts: list[str] = []
    total = 0
    for index, slide in enumerate(presentation.slides, start=1):
        if index < start:
            continue
        if index > end:
            break
        lines: list[str] = []
        for shape in slide.shapes:
            text = str(getattr(shape, "text", "") or "").strip()
            if text:
                lines.append(text)
        if not lines:
            continue
        block = f"[Slide {index}]\n" + "\n".join(lines)
        parts.append(block)
        total += len(block)
        if total >= max_chars:
            break
    return "\n\n".join(parts)


def write_pptx_slides(path: str, updates: str = "[]") -> str:
    """Compatibility facade for the PPTX text update operation."""
    return _pptx_write_slides(
        path,
        updates,
        context=_pptx_operation_context(),
    )


def design_pptx_theme_layout(
    path: str,
    style_brief: str = "",
    theme: str = "",
    palette: str = "",
    typography: str = "",
    density: str = "balanced",
    preserve_content: bool = True,
) -> str:
    """Compatibility facade for the PPTX theme and layout operation."""
    return _pptx_design_theme_layout(
        path,
        style_brief,
        theme,
        palette,
        typography,
        density,
        preserve_content,
        context=_pptx_operation_context(),
    )


def add_pptx_slides(path: str, slides: str = "[]") -> str:
    """Compatibility facade for the PPTX slide append operation."""
    return _pptx_add_slides(
        path,
        slides,
        context=_pptx_operation_context(),
    )
