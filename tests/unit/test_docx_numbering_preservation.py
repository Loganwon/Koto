"""Numbering loss must be rejected without banning ordinary equivalent lists."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.core.file_assistant.docx_preservation import (
    DocxStructureLossError,
    _numbering_groups,
    assert_docx_structure_preserved,
)
from app.core.file_assistant.save_service import AutoSavePersistenceService
from app.core.file_assistant.service import FileAssistantService

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def numbered_docx(
    path: Path, *, start=1, levels=(0, 0, 0), groups=None, pattern="%1.", restart=None
):
    document = Document()
    numbering = document.part.numbering_part.element
    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), "42")
    for level in (0, 1):
        definition = OxmlElement("w:lvl")
        definition.set(qn("w:ilvl"), str(level))
        fields = [
            ("start", str(start if level == 0 else 1)),
            ("numFmt", "decimal"),
            ("lvlText", pattern if level == 0 else "%1.%2."),
        ]
        if restart is not None and level == 1:
            fields.append(("lvlRestart", str(restart)))
        for name, value in fields:
            child = OxmlElement("w:" + name)
            child.set(qn("w:val"), value)
            definition.append(child)
        abstract.append(definition)
    numbering.append(abstract)
    groups = groups or tuple(0 for _ in levels)
    for group in sorted(set(groups)):
        number = OxmlElement("w:num")
        number.set(qn("w:numId"), str(42 + group))
        reference = OxmlElement("w:abstractNumId")
        reference.set(qn("w:val"), "42")
        number.append(reference)
        numbering.append(number)
    for index, (level, group) in enumerate(zip(levels, groups)):
        paragraph = document.add_paragraph(
            "Original target" if index == 0 else f"Outside item {index}"
        )
        properties = paragraph._p.get_or_add_pPr()
        num = OxmlElement("w:numPr")
        for name, value in (("ilvl", str(level)), ("numId", str(42 + group))):
            child = OxmlElement("w:" + name)
            child.set(qn("w:val"), value)
            num.append(child)
        properties.append(num)
    document.save(path)


def open_export(path, cache):
    cache.mkdir(exist_ok=True)
    original = path.read_bytes()
    (cache / "numberedid.docx").write_bytes(original)
    service = FileAssistantService()
    data = service.parse_editor_file(path, file_id="numberedid").data
    data["html"] = data["html"].replace("Original target", "Edited target")
    draft = service.export_editor_file(
        file_type="docx",
        file_id="numberedid",
        data=data,
        file_name="draft.docx",
        tmp_dir=cache,
    ).raw_bytes
    return data, draft


def rewrite_package(raw, change):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        pieces = {name: archive.read(name) for name in archive.namelist()}
    change(pieces)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in pieces.items():
            archive.writestr(name, content)
    return output.getvalue()


@pytest.mark.parametrize(
    "options",
    [
        {"start": 5},
        {"levels": (0, 1, 0)},
        {"pattern": "[%1]"},
        {"levels": (0, 0, 0, 0), "groups": (0, 0, 1, 1)},
    ],
)
def test_real_open_export_source_save_refuses_numbering_loss_and_keeps_editor_draft(
    tmp_path, options
):
    source = tmp_path / "source.docx"
    numbered_docx(source, **options)
    original = source.read_bytes()
    cache = tmp_path / "cache"
    _data, draft = open_export(source, cache)
    assert Document(io.BytesIO(draft)).paragraphs[0].text == "Edited target"
    with pytest.raises(DocxStructureLossError) as caught:
        AutoSavePersistenceService().persist(
            tmp_dir=cache,
            file_id="numberedid",
            raw_bytes=draft,
            suffix=".docx",
            explicit=True,
            ws_source_path="source.docx",
            workspace_dir=tmp_path,
            allowed_extensions={".docx"},
            fs_guard=lambda _: True,
            expected_source_sha256=hashlib.sha256(original).hexdigest(),
        )
    assert "numbering_semantics" in caught.value.lost_features
    assert source.read_bytes() == original
    assert (cache / "numberedid.docx").read_bytes() == draft


def test_ordinary_list_number_remains_saveable(tmp_path, monkeypatch):
    source = tmp_path / "ordinary.docx"
    document = Document()
    document.add_paragraph("Original target", style="List Number")
    document.add_paragraph("Outside item", style="List Number")
    document.save(source)
    original = source.read_bytes()
    cache = tmp_path / "cache"
    data, draft = open_export(source, cache)
    assert "<ol>" in data["html"]
    assert_docx_structure_preserved(original, draft)
    monkeypatch.setattr(
        AutoSavePersistenceService, "_sync_registry", staticmethod(lambda _: None)
    )
    result = AutoSavePersistenceService().persist(
        tmp_dir=cache,
        file_id="numberedid",
        raw_bytes=draft,
        suffix=".docx",
        explicit=True,
        ws_source_path="ordinary.docx",
        workspace_dir=tmp_path,
        allowed_extensions={".docx"},
        fs_guard=lambda _: True,
        expected_source_sha256=hashlib.sha256(original).hexdigest(),
    )
    assert result.verified and result.src_written


def test_style_only_numbering_explicitly_missing_from_draft_is_rejected(tmp_path):
    path = tmp_path / "ordinary.docx"
    document = Document()
    document.add_paragraph("Original target", style="List Number")
    document.save(path)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "numberedid.docx").write_bytes(path.read_bytes())
    draft = (
        FileAssistantService()
        .export_editor_file(
            file_type="docx",
            file_id="numberedid",
            data={"html": "<p>Edited target</p>"},
            file_name="draft.docx",
            tmp_dir=cache,
        )
        .raw_bytes
    )
    assert not _numbering_groups(draft)
    with pytest.raises(DocxStructureLossError, match="numbering_semantics"):
        assert_docx_structure_preserved(path.read_bytes(), draft)


def test_semantically_identical_numbering_id_remap_and_native_text_edit_are_allowed(
    tmp_path,
):
    path = tmp_path / "native.docx"
    numbered_docx(path, start=5, levels=(0, 1, 0), pattern="[%1]")
    source = path.read_bytes()

    def remap(pieces):
        body = ET.fromstring(pieces["word/document.xml"])
        for node in body.iter(W + "numId"):
            if node.get(W + "val") == "42":
                node.set(W + "val", "142")
        for node in body.iter(W + "t"):
            if node.text == "Original target":
                node.text = "Edited target"
        definitions = ET.fromstring(pieces["word/numbering.xml"])
        for node in definitions.findall(W + "abstractNum"):
            if node.get(W + "abstractNumId") == "42":
                node.set(W + "abstractNumId", "242")
        for node in definitions.findall(W + "num"):
            if node.get(W + "numId") == "42":
                node.set(W + "numId", "142")
                node.find(W + "abstractNumId").set(W + "val", "242")
        pieces["word/document.xml"] = ET.tostring(body)
        pieces["word/numbering.xml"] = ET.tostring(definitions)

    draft = rewrite_package(source, remap)
    assert _numbering_groups(source) == _numbering_groups(draft)
    assert_docx_structure_preserved(source, draft)
    assert Document(io.BytesIO(draft)).paragraphs[0].text == "Edited target"


@pytest.mark.parametrize(
    "field,value",
    [
        ("start", "5"),
        ("numFmt", "upperRoman"),
        ("lvlText", "[%1]"),
        ("lvlRestart", "0"),
    ],
)
def test_same_count_native_numbering_format_change_is_rejected(tmp_path, field, value):
    path = tmp_path / "numbered.docx"
    numbered_docx(path, levels=(0, 1, 1), restart=1)
    source = path.read_bytes()

    def mutate(pieces):
        definitions = ET.fromstring(pieces["word/numbering.xml"])
        abstract = next(
            node
            for node in definitions.findall(W + "abstractNum")
            if node.get(W + "abstractNumId") == "42"
        )
        level = abstract.findall(W + "lvl")[1 if field == "lvlRestart" else 0]
        level.find(W + field).set(W + "val", value)
        pieces["word/numbering.xml"] = ET.tostring(definitions)

    with pytest.raises(DocxStructureLossError, match="numbering_semantics"):
        assert_docx_structure_preserved(source, rewrite_package(source, mutate))


def test_restart_override_is_compared_by_effective_value_not_definition_ids(tmp_path):
    path = tmp_path / "override.docx"
    numbered_docx(path)
    source = path.read_bytes()

    def override(pieces):
        root = ET.fromstring(pieces["word/numbering.xml"])
        number = next(
            node for node in root.findall(W + "num") if node.get(W + "numId") == "42"
        )
        level = ET.SubElement(number, W + "lvlOverride", {W + "ilvl": "0"})
        ET.SubElement(level, W + "startOverride", {W + "val": "7"})
        pieces["word/numbering.xml"] = ET.tostring(root)

    with pytest.raises(DocxStructureLossError, match="numbering_semantics"):
        assert_docx_structure_preserved(source, rewrite_package(source, override))


def test_actual_native_python_docx_text_edit_preserves_complex_numbering(tmp_path):
    from app.core.agent.file_mutation_transaction import FileMutationTransaction
    from app.core.agent.file_task_document_metrics import (
        assert_transaction_structure_preserved,
    )

    path = tmp_path / "native.docx"
    numbered_docx(path, start=5, levels=(0, 1, 0), pattern="[%1]")
    original = path.read_bytes()
    transaction = FileMutationTransaction(str(path), run_id="numbering-native")
    transaction.begin()
    document = Document(path)
    document.paragraphs[0].text = "Edited target"
    document.save(path)
    assert_transaction_structure_preserved(transaction)
    transaction.commit()
    assert _numbering_groups(original) == _numbering_groups(path.read_bytes())
    assert Document(path).paragraphs[0].text == "Edited target"


def test_actual_http_save_rejects_numbering_loss_and_preserves_dirty_editor_copy(
    tmp_path, monkeypatch
):
    from flask import Flask

    import web.blueprints.workspace_assistant as routes

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "numbered.docx"
    numbered_docx(source, start=5, levels=(0, 1, 0))
    original = source.read_bytes()
    cache_root = tmp_path / "tmp"
    (cache_root / "numberguard").mkdir(parents=True)
    monkeypatch.setattr(routes, "_TMP_ROOT", cache_root)
    monkeypatch.setattr(routes, "_get_session_id", lambda: "numberguard")
    monkeypatch.setattr(routes, "_workspace_dir", lambda: workspace)
    monkeypatch.setattr(routes, "_fs_guard", lambda _: True)
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(routes.workspace_assistant_bp)
    client = app.test_client()
    opened = client.post(
        "/api/v1/workspace/open_file_by_path", json={"path": "numbered.docx"}
    )
    assert opened.status_code == 200
    payload = opened.get_json()
    data = payload["data"]
    data["html"] = data["html"].replace("Original target", "Edited target")
    saved = client.post(
        "/api/v1/workspace/auto_save",
        json={
            "file_type": "docx",
            "file_id": payload["file_id"],
            "data": data,
            "explicit": True,
            "ws_source_path": "numbered.docx",
            "expected_source_sha256": hashlib.sha256(original).hexdigest(),
        },
    )
    assert saved.status_code == 409
    result = saved.get_json()
    assert (
        result["code"] == "source_structure_loss"
        and "numbering_semantics" in result["lost_features"]
    )
    assert (
        result["persisted"] is False
        and result["verified"] is False
        and result["draft_preserved"] is True
    )
    assert source.read_bytes() == original
    draft = cache_root / "numberguard" / (payload["file_id"] + ".docx")
    assert Document(draft).paragraphs[0].text == "Edited target"
