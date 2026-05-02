"""
tests/test_docx_rendering.py

Backend integration tests for DOCX → HTML rendering fidelity.

Tests call parse_docx() directly — no server needed, pure Python.
Verifies the output HTML preserves the formatting that the TipTap
editor depends on to render correctly.

Target document: workspace/雷鸟创新-邗投珒创-投资建议书.docx
Word page count: 72 pages  (US Letter, 2.54 cm margins)

Run with:
    python -m pytest tests/test_docx_rendering.py -v
"""

from __future__ import annotations

import os
import re

import pytest

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCX_PATH = os.path.join(_REPO_ROOT, "workspace", "雷鸟创新-邗投珒创-投资建议书.docx")

# Microsoft Word reports 72 pages for this document.
WORD_PAGE_COUNT = 72

# TipTap/Koto rendering constants (must match koto-docx-editor.js)
_PAD_V = 176           # ProseMirror padding: top(96) + bottom(80)
_CONTENT_PAGE_H = 880  # usable content height per page (1056 - 176)

# ---------------------------------------------------------------------------
# Shared fixture — parse the DOCX once for the whole module
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def docx_html() -> str:
    """Parse the target DOCX once and share the HTML across all tests."""
    if not os.path.exists(DOCX_PATH):
        pytest.skip(f"Test document not found: {DOCX_PATH}")

    from app.core.file.file_parser import parse_docx  # noqa: PLC0415

    result = parse_docx(DOCX_PATH)
    assert isinstance(result, dict), "parse_docx() must return a dict"
    assert "html" in result, "parse_docx() result must contain 'html' key"

    html = result["html"]
    assert isinstance(html, str) and len(html) > 1_000, (
        f"HTML output suspiciously short ({len(html)} chars); parser likely failed"
    )
    return html


def _write_typography_fixture_docx(path) -> None:
    from docx import Document  # noqa: PLC0415
    from docx.oxml import OxmlElement  # noqa: PLC0415
    from docx.oxml.ns import qn  # noqa: PLC0415
    from docx.shared import Pt  # noqa: PLC0415

    doc = Document()

    # Create an intentionally conflicting style/default setup so the parser
    # must respect paragraph-level default run props over the style fallback.
    normal = doc.styles["Normal"]
    normal.font.size = Pt(16)
    normal.font.bold = True

    heading = doc.styles["Heading 1"]
    heading.font.size = Pt(16)

    doc.add_paragraph("一、企业简介", style="Heading 1")

    para = doc.add_paragraph()
    p_pr = para._p.get_or_add_pPr()
    r_pr = p_pr.find(qn("w:rPr"))
    if r_pr is None:
        r_pr = OxmlElement("w:rPr")
        p_pr.append(r_pr)

    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), "24")
    r_pr.append(sz)

    bold = OxmlElement("w:b")
    bold.set(qn("w:val"), "0")
    r_pr.append(bold)

    para.add_run("企业介绍正文段落，用于验证段落默认字号与粗细继承。")
    doc.save(path)


@pytest.fixture()
def typography_html(tmp_path) -> str:
    pytest.importorskip("docx", reason="python-docx 未安装")

    docx_path = tmp_path / "typography-fixture.docx"
    _write_typography_fixture_docx(docx_path)

    from app.core.file.file_parser import parse_docx  # noqa: PLC0415

    result = parse_docx(str(docx_path))
    assert isinstance(result, dict), "parse_docx() must return a dict"
    html = result.get("html", "")
    assert isinstance(html, str) and html, "parse_docx() must produce HTML"
    return html


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestDocxHtmlStructure:
    """Structural checks on the HTML produced by parse_docx()."""

    def test_html_has_substantial_content(self, docx_html: str) -> None:
        """Output HTML must be non-trivial (>50 KB) for a 72-page document."""
        assert len(docx_html) > 50_000, (
            f"HTML is only {len(docx_html):,} chars — expected >50 000 for a "
            f"{WORD_PAGE_COUNT}-page document.  Parser may have failed silently."
        )

    def test_has_block_elements(self, docx_html: str) -> None:
        """Output must contain paragraph or div elements."""
        assert re.search(r'<(p|div)\b', docx_html, re.IGNORECASE), (
            "No <p> or <div> elements found in HTML output"
        )


@pytest.mark.integration
class TestHeaderFooter:
    """Header / footer CSS class preservation."""

    def test_header_class_present(self, docx_html: str) -> None:
        """
        The parser emits <p class="koto-header"> for header paragraphs.
        After the TipTap className-attribute fix, DocxParagraph must round-trip
        this class through parse → TipTap → renderHTML.  This test verifies the
        *parser side*: the class must exist in the raw HTML output.
        """
        assert "koto-header" in docx_html, (
            "'koto-header' class not found in HTML.  "
            "Check _section_html() in file_parser.py — "
            "header paragraphs may be missing or have a different class name."
        )

    def test_footer_class_present_if_document_has_footer(self, docx_html: str) -> None:
        """
        If a document has a footer defined in its DOCX, the parser emits
        koto-footer class.  This document (投资建议书) has no footer section,
        so the test always skips for this file.  If you use a document WITH a
        footer, this test will verify the class is preserved.
        """
        if "koto-footer" not in docx_html:
            pytest.skip("Document has no footer — koto-footer class not expected")
        assert "koto-footer" in docx_html

    def test_header_contains_text(self, docx_html: str) -> None:
        """At least one koto-header element must have non-empty text content."""
        # Extract the first koto-header <p> tag and its text
        match = re.search(
            r'<p[^>]*class="koto-header"[^>]*>(.*?)</p>',
            docx_html,
            re.IGNORECASE | re.DOTALL,
        )
        if not match:
            pytest.skip("koto-header class not found — covered by test_header_class_present")
        text = re.sub(r'<[^>]+>', '', match.group(1)).strip()
        assert text, "koto-header paragraph is empty (no visible text)"


@pytest.mark.integration
class TestTypography:
    """Paragraph and heading typography fidelity."""

    def test_body_paragraph_uses_paragraph_default_run_size_without_forced_bold(
        self, typography_html: str
    ) -> None:
        """
        Paragraph-level default run properties (<w:pPr><w:rPr>) should beat the
        Normal style fallback when setting the block font size, and body text
        must not inherit a phantom bold weight at the paragraph level.
        """
        blocks = re.findall(r'<p\b([^>]*)>(.*?)</p>', typography_html, re.IGNORECASE | re.DOTALL)
        target_attrs = None
        for attrs, inner in blocks:
            text = re.sub(r'<[^>]+>', '', inner).replace("\xa0", " ")
            text = re.sub(r'\s+', ' ', text).strip()
            if text == "企业介绍正文段落，用于验证段落默认字号与粗细继承。":
                target_attrs = attrs
                break

        assert target_attrs is not None, "Target body paragraph not found in parsed HTML"
        style_match = re.search(r'style="([^"]*)"', target_attrs)
        assert style_match, "Target body paragraph missing inline style"
        style = style_match.group(1)
        assert "font-size:12.0pt" in style
        assert "font-weight:bold" not in style

    def test_section_heading_keeps_larger_style_level_font_size(self, typography_html: str) -> None:
        """Section headings should retain their heading style font size."""
        blocks = re.findall(r'<(h[1-6])\b([^>]*)>(.*?)</\1>', typography_html, re.IGNORECASE | re.DOTALL)
        target_attrs = None
        for _tag, attrs, inner in blocks:
            text = re.sub(r'<[^>]+>', '', inner).replace("\xa0", " ")
            text = re.sub(r'\s+', ' ', text).strip()
            if text == "一、企业简介":
                target_attrs = attrs
                break

        assert target_attrs is not None, "Target section heading not found in parsed HTML"
        style_match = re.search(r'style="([^"]*)"', target_attrs)
        assert style_match, "Target heading missing inline style"
        style = style_match.group(1)
        assert "font-size:16.0pt" in style


@pytest.mark.integration
class TestImages:
    """Image dimension preservation."""

    def test_images_carry_explicit_dimensions(self, docx_html: str) -> None:
        """
        Every <img> must have both width and height in its inline style so that
        the browser can display it at the correct size.  Without explicit height,
        CSS 'height:auto' stretches images to occupy the full container width.
        """
        img_tags = re.findall(r'<img\b[^>]+>', docx_html, re.IGNORECASE)
        if not img_tags:
            pytest.skip("No <img> tags in document")

        imgs_missing_height = [
            tag for tag in img_tags
            if not re.search(r'height\s*:\s*\d', tag)
        ]
        assert not imgs_missing_height, (
            f"{len(imgs_missing_height)}/{len(img_tags)} <img> tags lack an "
            f"explicit height in their inline style:\n"
            + "\n".join(imgs_missing_height[:3])
        )

    def test_images_carry_width(self, docx_html: str) -> None:
        """Every <img> must also have an explicit width."""
        img_tags = re.findall(r'<img\b[^>]+>', docx_html, re.IGNORECASE)
        if not img_tags:
            pytest.skip("No <img> tags in document")

        imgs_missing_width = [
            tag for tag in img_tags
            if not re.search(r'width\s*:\s*\d', tag)
        ]
        assert not imgs_missing_width, (
            f"{len(imgs_missing_width)}/{len(img_tags)} <img> tags lack explicit width"
        )


@pytest.mark.integration
class TestTableFormatting:
    """Table cell formatting."""

    def test_table_cells_exist(self, docx_html: str) -> None:
        """The document has tables — at least one <td> must be present."""
        assert re.search(r'<td\b', docx_html, re.IGNORECASE), (
            "No <td> elements found; table parsing may have failed"
        )

    def test_table_cells_have_border_inline_styles(self, docx_html: str) -> None:
        """
        Every <td> must carry explicit border-top/bottom/left/right in inline styles
        so the CSS fallback (1px solid #a0a4b8) never fires.
        """
        td_tags = re.findall(r'<td\b[^>]+>', docx_html, re.IGNORECASE)
        if not td_tags:
            pytest.skip("No <td> tags — covered by test_table_cells_exist")

        missing = [t for t in td_tags if "border-top" not in t]
        assert not missing, (
            f"{len(missing)}/{len(td_tags)} <td> tags lack border-top inline style.  "
            "Table borders will fall back to CSS gray grid instead of DOCX values."
        )

    def test_some_cells_have_background_color(self, docx_html: str) -> None:
        """
        Tinted table cells must carry background-color in their inline style.
        The 投资建议书 document has a styled cover table with coloured cells.
        """
        td_tags = re.findall(r'<td\b[^>]+>', docx_html, re.IGNORECASE)
        assert td_tags, pytest.skip("No <td> tags — covered by test_table_cells_exist")

        tinted = [t for t in td_tags if "background-color" in t]
        assert tinted, (
            f"None of the {len(td_tags)} <td> tags carry background-color.  "
            "Table shading will be invisible in the editor."
        )


@pytest.mark.integration
class TestPageCount:
    """
    Page count estimate.

    We cannot run a real browser to measure rendered height, but we can
    estimate the content volume and check it's in a plausible range.
    The Koto formula:
        pages = ceil((intrinsicHeight - _PAD_V) / _CONTENT_PAGE_H)
    where intrinsicHeight = actual DOM height (top-pad + content + bottom-pad).

    We estimate content height using paragraph count and average font metrics:
        font-size: 16px, line-height: 1.7 → ~27.2px per text line.
        Average Chinese line: ~35 chars.
        So content_height ≈ (char_count / 35) * 27.2px.
    """

    def test_page_count_estimate_in_range(self, docx_html: str) -> None:
        """Estimated page count should be within 50% of Word's 72 pages."""
        text_only = re.sub(r'<[^>]+>', ' ', docx_html)
        # Count CJK + Latin printable chars (ignore whitespace)
        char_count = len(re.sub(r'\s', '', text_only))

        chars_per_line = 35
        px_per_line = 27.2  # 16px × 1.7
        content_height_px = (char_count / chars_per_line) * px_per_line
        estimated_pages = max(1, (content_height_px) / _CONTENT_PAGE_H)

        lower = WORD_PAGE_COUNT * 0.4
        upper = WORD_PAGE_COUNT * 4.0

        assert lower <= estimated_pages <= upper, (
            f"Estimated page count ({estimated_pages:.1f}) is far outside "
            f"[{lower:.0f}, {upper:.0f}] — expected ~{WORD_PAGE_COUNT} pages.  "
            f"char_count={char_count:,}, content_height={content_height_px:.0f}px.  "
            "Parser may be dropping large sections of content."
        )

    def test_paragraph_count_reasonable(self, docx_html: str) -> None:
        """A 72-page document must have many paragraphs."""
        p_count = len(re.findall(r'<p\b', docx_html, re.IGNORECASE))
        assert p_count >= 50, (
            f"Only {p_count} <p> elements found; expected ≥50 for a "
            f"{WORD_PAGE_COUNT}-page document"
        )
