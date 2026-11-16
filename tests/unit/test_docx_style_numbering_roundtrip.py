"""Real workspace round trips retain ordinary style-inherited Word lists."""

from __future__ import annotations

import hashlib
import io

import pytest
from bs4 import BeautifulSoup
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.core.file.parsers.docx_numbering import resolve_paragraph_numbering
from app.core.file_assistant.save_service import AutoSavePersistenceService
from app.core.file_assistant.service import FileAssistantService


def _set_numpr(element, **values):
    properties = element.get_or_add_pPr()
    numpr = properties.find(qn("w:numPr"))
    if numpr is None:
        numpr = OxmlElement("w:numPr")
        properties.append(numpr)
    for name, value in values.items():
        child = OxmlElement("w:" + name)
        child.set(qn("w:val"), str(value))
        numpr.append(child)


@pytest.mark.parametrize(
    "style_name,tag", [("List Number", "ol"), ("List Bullet", "ul")]
)
@pytest.mark.parametrize("inherited", [False, True])
@pytest.mark.parametrize("cancelled", [False, True])
def test_actual_open_edit_export_source_save_reopen_retains_ordinary_lists(
    tmp_path, monkeypatch, style_name, tag, inherited, cancelled
):
    source = tmp_path / "source.docx"
    document = Document()
    style = document.styles[style_name]
    if inherited:
        # Neither custom name hints at a list. The nearest style contributes
        # ilvl while numId must come from a second basedOn ancestor.
        parent = document.styles.add_style("Editorial Body", WD_STYLE_TYPE.PARAGRAPH)
        parent.base_style = style
        _set_numpr(parent.element, ilvl=0)
        style = document.styles.add_style("Editorial Child", WD_STYLE_TYPE.PARAGRAPH)
        style.base_style = parent
    first = document.add_paragraph("Original target", style=style)
    document.add_paragraph("Outside unchanged", style=style)
    if inherited:
        # A partial direct numPr must not erase the style's inherited numId.
        _set_numpr(first._p, ilvl=0)
    if cancelled:
        cancelled_paragraph = document.add_paragraph("Cancelled target", style=style)
        _set_numpr(cancelled_paragraph._p, numId=0)
    document.add_paragraph("Plain tail")
    document.save(source)
    original = source.read_bytes()
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "styled.docx").write_bytes(original)
    service = FileAssistantService()

    opened = service.parse_editor_file(source, file_id="styled").data
    soup = BeautifulSoup(opened["html"], "html.parser")
    assert [item.get_text() for item in soup.select(f"{tag} > li")] == [
        "Original target",
        "Outside unchanged",
    ]
    assert not soup.select("ul" if tag == "ol" else "ol")
    if cancelled:
        node = soup.find(string="Cancelled target")
        assert node is not None and node.find_parent("li") is None
    opened["html"] = opened["html"].replace("Original target", "Edited target")
    exported = service.export_editor_file(
        file_type="docx",
        file_id="styled",
        data=opened,
        file_name="edited.docx",
        tmp_dir=cache,
    )
    assert (
        Document(io.BytesIO(exported.raw_bytes)).paragraphs[0].text == "Edited target"
    )
    monkeypatch.setattr(
        AutoSavePersistenceService, "_sync_registry", staticmethod(lambda _: None)
    )
    receipt = AutoSavePersistenceService().persist(
        tmp_dir=cache,
        file_id="styled",
        raw_bytes=exported.raw_bytes,
        suffix=".docx",
        explicit=True,
        ws_source_path="source.docx",
        workspace_dir=tmp_path,
        allowed_extensions={".docx"},
        fs_guard=lambda _: True,
        expected_source_sha256=hashlib.sha256(original).hexdigest(),
    )
    assert receipt.src_written and receipt.verified
    assert source.read_bytes() == exported.raw_bytes
    reopened = service.parse_editor_file(source, file_id="reopened").data
    soup = BeautifulSoup(reopened["html"], "html.parser")
    assert [item.get_text() for item in soup.select(f"{tag} > li")] == [
        "Edited target",
        "Outside unchanged",
    ]
    assert "Plain tail" in soup.get_text()
    if cancelled:
        node = soup.find(string="Cancelled target")
        assert node is not None and node.find_parent("li") is None


def test_style_name_without_numbering_does_not_create_a_list(tmp_path):
    source = tmp_path / "plain.docx"
    document = Document()
    style = document.styles.add_style("List Number Custom", WD_STYLE_TYPE.PARAGRAPH)
    document.add_paragraph("Plain target", style=style)
    document.save(source)

    html = (
        FileAssistantService().parse_editor_file(source, file_id="plain").data["html"]
    )
    assert not BeautifulSoup(html, "html.parser").select("ol, ul, li")


@pytest.mark.parametrize("number,level", [("broken", "0"), ("-1", "0"), ("1", "9")])
def test_invalid_direct_numbering_does_not_fall_back_to_style(number, level):
    document = Document()
    paragraph = document.add_paragraph("Invalid", style="List Number")
    _set_numpr(paragraph._p, numId=number, ilvl=level)
    assert resolve_paragraph_numbering(paragraph) is None


def test_cyclic_style_chain_terminates_without_inventing_numbering():
    document = Document()
    first = document.styles.add_style("Circular A", WD_STYLE_TYPE.PARAGRAPH)
    second = document.styles.add_style("Circular B", WD_STYLE_TYPE.PARAGRAPH)
    first.base_style = second
    second.base_style = first
    paragraph = document.add_paragraph("Plain", style=first)
    assert resolve_paragraph_numbering(paragraph) is None
