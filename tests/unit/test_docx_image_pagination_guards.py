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


def test_docx_auto_pagination_ignores_existing_soft_break_widgets_when_measuring():
    src = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )

    assert "const _DOCX_SOFT_PAGE_BREAK_SELECTOR = '[data-soft-page-break]';" in src
    assert "const _DOCX_PAGE_BOUNDARY_SELECTOR = '[data-soft-page-break],[data-page-break]';" in src
    assert "function _suppressDocxSoftPageBreaksForMeasurement(root)" in src
    assert "root?.querySelectorAll?.(_DOCX_SOFT_PAGE_BREAK_SELECTOR)" in src
    assert "node.style.display = 'none';" in src
    assert "const restoreSoftBreaks = _suppressDocxSoftPageBreaksForMeasurement(view?.dom);" in src
    assert "restoreSoftBreaks();" in src


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

    assert "#wa-docx-editor [contenteditable=\"true\"] img" in css
    assert ".koto-img-wrapper" in css
    assert "break-inside: avoid" in css
    assert "page-break-inside: avoid" in css
    assert "#wa-docx-editor .ProseMirror p:has(.koto-img-wrapper)" in css
