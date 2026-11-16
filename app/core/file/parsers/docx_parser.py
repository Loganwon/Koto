"""DOCX parser facade -- re-exports from componentized docx/ package.

This module is the stable public API.  All implementations live in
``app.core.file.parsers.docx.*`` sub-modules.
"""

from __future__ import annotations

# Re-export from component sub-modules
from app.core.file.parsers.docx import (  # noqa: F401
    _extract_images_from_paragraphs,
    _extract_table_styles,
    _get_floating_image_srcs,
    _inject_table_styles,
    _unwrap_layout_tables,
    parse_docx,
)
from app.core.file.parsers.docx_parser_fallback import (  # noqa: F401
    extract_fallback_docx_metadata as _extract_fallback_docx_metadata,
)
from app.core.file.parsers.docx_parser_fallback import (
    normalize_mammoth_heading_contract as _normalize_mammoth_heading_contract,
)
from app.core.file.parsers.docx_parser_postprocess import (  # noqa: F401
    deduplicate_images as _deduplicate_images,
)

# Direct re-exports used by tests and external consumers
from app.core.file.parsers.docx_parser_review import (  # noqa: F401
    _extract_docx_comments,
    _extract_docx_footnotes,
    _extract_docx_revisions,
    count_docx_visible_chars,
)
from app.core.file.parsers.docx_rich_renderer import _docx_to_rich_html  # noqa: F401
