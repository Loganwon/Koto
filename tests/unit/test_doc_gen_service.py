"""Unit tests for DocGenService.

Tests use real python-docx / openpyxl / python-pptx writes into a temp dir.
reportlab (PDF) is optional — tests skip gracefully if not installed.
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest


def _get_service():
    from app.core.services.doc_gen_service import (
        DocGenRequest,
        DocGenService,
        DocSection,
    )

    return DocGenService, DocGenRequest, DocSection


@pytest.fixture()
def tmp_out():
    """Temp output dir compatible with Windows CI."""
    d = tempfile.mkdtemp(prefix="koto_docgen_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# DocGenRequest / DocSection construction
# ---------------------------------------------------------------------------


class TestDocGenRequest:
    def test_minimal_request_with_empty_sections(self):
        _, DocGenRequest, DocSection = _get_service()
        req = DocGenRequest(title="Test Doc", sections=[])
        assert req.title == "Test Doc"
        assert req.sections == []

    def test_sections_added(self):
        _, DocGenRequest, DocSection = _get_service()
        req = DocGenRequest(
            title="Report",
            sections=[
                DocSection(content_type="heading", content="Intro", level=1),
                DocSection(content_type="text", content="Body text"),
            ],
        )
        assert len(req.sections) == 2

    def test_section_content_type_stored(self):
        _, DocGenRequest, DocSection = _get_service()
        s = DocSection(content_type="bullet", content=["a", "b"])
        assert s.content_type == "bullet"
        assert s.content == ["a", "b"]


# ---------------------------------------------------------------------------
# Word generation
# ---------------------------------------------------------------------------


class TestGenerateWord:
    def test_generate_word_creates_file(self, tmp_out):
        DocGenService, DocGenRequest, DocSection = _get_service()
        svc = DocGenService()
        req = DocGenRequest(
            title="Unit Test Report",
            output_dir=tmp_out,
            sections=[
                DocSection(content_type="heading", content="Section 1", level=1),
                DocSection(content_type="text", content="Some body text."),
                DocSection(content_type="bullet", content=["Item A", "Item B"]),
            ],
        )
        path = svc.generate_word(req)
        assert os.path.exists(path)
        assert path.endswith(".docx")

    def test_generate_word_file_non_empty(self, tmp_out):
        DocGenService, DocGenRequest, DocSection = _get_service()
        svc = DocGenService()
        req = DocGenRequest(
            title="Hello",
            output_dir=tmp_out,
            sections=[DocSection(content_type="text", content="hi")],
        )
        path = svc.generate_word(req)
        assert os.path.getsize(path) > 0

    def test_generate_word_with_table(self, tmp_out):
        DocGenService, DocGenRequest, DocSection = _get_service()
        svc = DocGenService()
        req = DocGenRequest(
            title="Table Test",
            output_dir=tmp_out,
            sections=[
                DocSection(
                    content_type="table",
                    content=[["Name", "Value"], ["alpha", "1"], ["beta", "2"]],
                )
            ],
        )
        path = svc.generate_word(req)
        assert os.path.exists(path)


# ---------------------------------------------------------------------------
# Excel generation
# ---------------------------------------------------------------------------


class TestGenerateExcel:
    def test_generate_excel_creates_file(self, tmp_out):
        DocGenService, DocGenRequest, DocSection = _get_service()
        svc = DocGenService()
        req = DocGenRequest(
            title="Data Sheet",
            output_dir=tmp_out,
            sections=[
                DocSection(
                    content_type="table",
                    content=[["A", "B", "C"], ["1", "2", "3"]],
                )
            ],
        )
        path = svc.generate_excel(req)
        assert os.path.exists(path)
        assert path.endswith(".xlsx")

    def test_generate_excel_non_empty(self, tmp_out):
        DocGenService, DocGenRequest, DocSection = _get_service()
        svc = DocGenService()
        req = DocGenRequest(title="Sheet", output_dir=tmp_out, sections=[])
        path = svc.generate_excel(req)
        assert os.path.getsize(path) > 0


# ---------------------------------------------------------------------------
# PowerPoint generation
# ---------------------------------------------------------------------------


class TestGeneratePresentations:
    def test_generate_pptx_creates_file(self, tmp_out):
        DocGenService, DocGenRequest, DocSection = _get_service()
        svc = DocGenService()
        req = DocGenRequest(
            title="Slide Deck",
            output_dir=tmp_out,
            sections=[
                DocSection(content_type="heading", content="Slide 1", level=1),
                DocSection(content_type="text", content="Content for slide 1"),
            ],
        )
        path = svc.generate_presentation(req)
        assert os.path.exists(path)
        assert path.endswith(".pptx")


# ---------------------------------------------------------------------------
# PDF generation (optional — skip if reportlab not installed)
# ---------------------------------------------------------------------------


class TestGeneratePDF:
    def test_generate_pdf_creates_file(self, tmp_out):
        pytest.importorskip("reportlab", reason="reportlab not installed")
        DocGenService, DocGenRequest, DocSection = _get_service()
        svc = DocGenService()
        req = DocGenRequest(
            title="PDF Report",
            output_dir=tmp_out,
            sections=[
                DocSection(content_type="heading", content="Overview", level=1),
                DocSection(content_type="text", content="This is a PDF."),
            ],
        )
        path = svc.generate_pdf(req)
        assert os.path.exists(path)
        assert path.endswith(".pdf")
