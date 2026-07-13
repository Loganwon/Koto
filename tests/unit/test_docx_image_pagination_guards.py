from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_docx_auto_pagination_does_not_split_image_blocks():
    src = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )

    assert "function _docxBlockAvoidsAutoSplit" in src
    assert "element.querySelector?.('img,.koto-img-wrapper')" in src
    assert "if (!_docxBlockAvoidsAutoSplit(node, domEl))" in src
    assert "_planDocxTextBlockBreaks(" in src


def test_docx_auto_pagination_measures_text_without_reintroducing_a_hidden_break_path():
    src = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )

    assert "const _DOCX_SOFT_PAGE_BREAK_SELECTOR = '[data-soft-page-break]';" in src
    assert (
        "const _DOCX_PAGE_BOUNDARY_SELECTOR = '[data-soft-page-break],[data-page-break]';"
        in src
    )
    assert "function _suppressDocxSoftPageBreaksForMeasurement" not in src
    assert (
        "'.koto-inline-page-break-anchor, [data-soft-page-break], .koto-pb-header, .koto-pb-footer'"
        in src
    )
    assert "contentHeight = Math.max(0, contentHeight - anchor.offsetHeight);" in src


def test_docx_inline_page_breaks_align_to_page_not_paragraph_indent():
    src = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )

    assert "const pageLeftOffsetPx = _measureRelativeLeftPx(domEl, pmDom);" in src
    assert "function _alignSoftBreakWidgetToRenderedPage" in src
    assert "widget.style.marginLeft = `${-pageOffset}px`;" in src
    assert "widget.style.width = renderedWidth + 'px';" in src
    assert "function _resolveRenderedDocxPageGeometry" in src
    assert (
        "const pageGeometry = _resolveRenderedDocxPageGeometry(pmDom, pageW, mLeft);"
        in src
    )
    assert "const renderedPageWidthPx = pageGeometry.pageWidthPx;" in src
    assert "if (blockH > remaining && (usedH > 0 || blockH > contentH))" in src
    assert "nextUsed = contentH;" in src
    assert "never advance through pages that have no rendered boundary" in src


def test_docx_auto_pagination_names_top_level_boundary_helper_precisely():
    src = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )

    assert "function _isTopLevelDocxPaginationBoundaryEl(element)" in src
    assert "_isDocxPaginationBoundaryEl" not in src
    assert "element.matches?.(_DOCX_PAGE_BOUNDARY_SELECTOR)" in src


def test_docx_image_css_marks_images_as_unsplittable():
    css = (_repo_root() / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )

    assert '#wa-docx-editor [contenteditable="true"] img' in css
    assert ".koto-img-wrapper" in css
    assert "break-inside: avoid" in css
    assert "page-break-inside: avoid" in css
    assert "#wa-docx-editor .ProseMirror p:has(.koto-img-wrapper)" in css


def test_docx_image_node_view_preserves_rendered_size_and_style_attributes():
    src = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )

    assert "img.className = 'koto-docx-img';" in src
    assert "img.style.height = attrs.height || 'auto';" in src
    assert "img.style.maxWidth = attrs.maxWidth || '100%';" in src
    assert "img.style.maxHeight = attrs.maxHeight || '';" in src
    assert "img.style.objectFit = attrs.objectFit || 'contain';" in src
    assert "img.style.borderRadius = attrs.borderRadius || '';" in src
