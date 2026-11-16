"""Actual DOCX open/export/save must not silently erase native source structures."""

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
    _inventory,
    assert_docx_structure_preserved,
)
from app.core.file_assistant.save_service import (
    AutoSaveConflictError,
    AutoSavePersistenceService,
)
from app.core.file_assistant.service import FileAssistantService


def _fixture(path: Path, feature: str):
    document = Document()
    paragraph = document.add_paragraph("Original target")
    document.add_paragraph("Outside unchanged")
    if feature == "header_footer":
        document.sections[0].header.paragraphs[0].text = "Keep native header"
        document.sections[0].footer.paragraphs[0].text = "Keep native footer"
    if feature == "bookmark":
        start = OxmlElement("w:bookmarkStart")
        start.set(qn("w:id"), "20")
        start.set(qn("w:name"), "KeepBookmark")
        end = OxmlElement("w:bookmarkEnd")
        end.set(qn("w:id"), "20")
        paragraph._p.insert(0, start)
        paragraph._p.append(end)
    if feature == "revision":
        insertion = OxmlElement("w:ins")
        insertion.set(qn("w:id"), "40")
        insertion.set(qn("w:author"), "Reviewer")
        run = OxmlElement("w:r")
        text = OxmlElement("w:t")
        text.text = " Tracked addition"
        run.append(text)
        insertion.append(run)
        paragraph._p.append(insertion)
    if feature == "footnote":
        run = paragraph.add_run()._r
        reference = OxmlElement("w:footnoteReference")
        reference.set(qn("w:id"), "2")
        run.append(reference)
    if feature == "comment":
        for tag in ("commentRangeStart", "commentRangeEnd"):
            node = OxmlElement("w:" + tag)
            node.set(qn("w:id"), "5")
            if tag == "commentRangeStart":
                paragraph._p.insert(0, node)
            else:
                paragraph._p.append(node)
        reference = OxmlElement("w:commentReference")
        reference.set(qn("w:id"), "5")
        paragraph.add_run()._r.append(reference)
    if feature == "drawing":
        from PIL import Image

        image = io.BytesIO()
        Image.new("RGB", (2, 2), "red").save(image, format="PNG")
        image.seek(0)
        document.add_picture(image)
    document.save(path)
    if feature not in {"footnote", "comment"}:
        return
    part = "footnotes" if feature == "footnote" else "comments"
    item = "footnote" if feature == "footnote" else "comment"
    identifier = "2" if feature == "footnote" else "5"
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    author = ' w:author="Reviewer"' if feature == "comment" else ""
    xml = f'<w:{part} xmlns:w="{w}"><w:{item} w:id="{identifier}"{author}><w:p><w:r><w:t>Keep native {item}</w:t></w:r></w:p></w:{item}></w:{part}>'
    with zipfile.ZipFile(path) as archive:
        pieces = {name: archive.read(name) for name in archive.namelist()}
    pieces[f"word/{part}.xml"] = xml.encode()
    rels = ET.fromstring(pieces["word/_rels/document.xml.rels"])
    relns = "http://schemas.openxmlformats.org/package/2006/relationships"
    ET.SubElement(
        rels,
        "{" + relns + "}Relationship",
        {
            "Id": "rIdNativeFeature",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
            + part,
            "Target": part + ".xml",
        },
    )
    pieces["word/_rels/document.xml.rels"] = ET.tostring(rels)
    content_types = ET.fromstring(pieces["[Content_Types].xml"])
    ET.SubElement(
        content_types,
        "{http://schemas.openxmlformats.org/package/2006/content-types}Override",
        {
            "PartName": f"/word/{part}.xml",
            "ContentType": f"application/vnd.openxmlformats-officedocument.wordprocessingml.{part}+xml",
        },
    )
    pieces["[Content_Types].xml"] = ET.tostring(content_types)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, raw in pieces.items():
            archive.writestr(name, raw)


def _open_export(root: Path, feature: str):
    cache = root / "cache"
    cache.mkdir()
    original = root / "source.docx"
    _fixture(original, feature)
    file_id = "originalid"
    (cache / f"{file_id}.docx").write_bytes(original.read_bytes())
    service = FileAssistantService()
    data = service.parse_editor_file(original, file_id=file_id).data
    assert "Original target" in data["html"]
    data["html"] = data["html"].replace("Original target", "Edited target")
    exported = service.export_editor_file(
        file_type="docx",
        file_id=file_id,
        data=data,
        file_name="edited.docx",
        tmp_dir=cache,
    )
    assert (
        "Edited target" in Document(io.BytesIO(exported.raw_bytes)).paragraphs[0].text
    )
    return original, cache, file_id, data, exported.raw_bytes


@pytest.mark.parametrize("feature", ["bookmark", "revision", "footnote"])
def test_actual_open_export_rejects_native_structure_loss_and_preserves_source_and_draft(
    tmp_path, feature
):
    source, cache, file_id, data, draft = _open_export(tmp_path, feature)
    original = source.read_bytes()
    with pytest.raises(DocxStructureLossError) as caught:
        AutoSavePersistenceService().persist(
            tmp_dir=cache,
            file_id=file_id,
            raw_bytes=draft,
            suffix=".docx",
            explicit=True,
            ws_source_path="source.docx",
            workspace_dir=tmp_path,
            allowed_extensions={".docx"},
            fs_guard=lambda _: True,
            expected_source_sha256=hashlib.sha256(original).hexdigest(),
        )
    assert source.read_bytes() == original
    assert (cache / (file_id + ".docx")).read_bytes() == draft
    assert caught.value.lost_features
    # The existing export-copy path remains available and never replaces source.
    copy = FileAssistantService().export_editor_file(
        file_type="docx",
        file_id=file_id,
        data=data,
        file_name="copy.docx",
        tmp_dir=cache,
    )
    assert (
        Document(io.BytesIO(copy.raw_bytes))
        .paragraphs[0]
        .text.startswith("Edited target")
    )
    assert source.read_bytes() == original


@pytest.mark.parametrize("feature", ["header_footer", "drawing"])
def test_actual_supported_features_remain_saveable(tmp_path, feature, monkeypatch):
    source, cache, file_id, _data, draft = _open_export(tmp_path, feature)
    original = source.read_bytes()
    before = _inventory(original)
    after = _inventory(draft)
    assert all(after[key] >= count for key, count in before.items())
    monkeypatch.setattr(
        AutoSavePersistenceService, "_sync_registry", staticmethod(lambda _: None)
    )
    kwargs = dict(
        tmp_dir=cache,
        file_id=file_id,
        raw_bytes=draft,
        suffix=".docx",
        explicit=True,
        ws_source_path="source.docx",
        workspace_dir=tmp_path,
        allowed_extensions={".docx"},
        fs_guard=lambda _: True,
        expected_source_sha256=hashlib.sha256(original).hexdigest(),
    )
    result = AutoSavePersistenceService().persist(**kwargs)
    assert result.verified and result.src_written
    assert source.read_bytes() == draft
    reopened = Document(source)
    if feature == "header_footer":
        assert reopened.sections[0].header.paragraphs[0].text == "Keep native header"
        assert reopened.sections[0].footer.paragraphs[0].text == "Keep native footer"
    else:
        assert len(reopened.inline_shapes) == 1


def test_comment_part_without_live_anchors_is_explicitly_rejected(tmp_path):
    source, _cache, _file_id, _data, draft = _open_export(tmp_path, "comment")
    before = _inventory(source.read_bytes())
    after = _inventory(draft)
    assert before["comment_content"] == after["comment_content"] == 1
    assert before["comment_anchors"] == 1 and after["comment_anchors"] == 0
    with pytest.raises(DocxStructureLossError) as caught:
        assert_docx_structure_preserved(source.read_bytes(), draft)
    assert "comment_anchors" in caught.value.lost_features


def test_cache_only_browser_source_and_same_path_source_remain_intact_on_loss(tmp_path):
    source, cache, file_id, _data, draft = _open_export(tmp_path, "revision")
    cached = cache / (file_id + ".docx")
    original = cached.read_bytes()
    for source_path in ("", str(cached)):
        with pytest.raises(DocxStructureLossError):
            AutoSavePersistenceService().persist(
                tmp_dir=cache,
                file_id=file_id,
                raw_bytes=draft,
                suffix=".docx",
                explicit=True,
                ws_source_path=source_path,
                workspace_dir=tmp_path,
                allowed_extensions={".docx"},
                fs_guard=lambda _: True,
                expected_source_sha256=hashlib.sha256(original).hexdigest(),
            )
        assert cached.read_bytes() == original
        assert (cache / (file_id + ".koto-editor-draft.docx")).read_bytes() == draft


def test_source_hash_conflict_has_priority_and_plain_docx_is_not_blocked(
    tmp_path, monkeypatch
):
    source, cache, file_id, _data, draft = _open_export(tmp_path, "plain")
    original = source.read_bytes()
    kwargs = dict(
        tmp_dir=cache,
        file_id=file_id,
        raw_bytes=draft,
        suffix=".docx",
        explicit=True,
        ws_source_path="source.docx",
        workspace_dir=tmp_path,
        allowed_extensions={".docx"},
        fs_guard=lambda _: True,
    )
    with pytest.raises(AutoSaveConflictError):
        AutoSavePersistenceService().persist(**kwargs, expected_source_sha256="f" * 64)
    assert source.read_bytes() == original
    monkeypatch.setattr(
        AutoSavePersistenceService, "_sync_registry", staticmethod(lambda _: None)
    )
    assert (
        AutoSavePersistenceService()
        .persist(**kwargs, expected_source_sha256=hashlib.sha256(original).hexdigest())
        .verified
    )


def test_http_actual_open_rejects_loss_with_dirty_draft_receipt_and_copy_download(
    tmp_path, monkeypatch
):
    from flask import Flask

    import web.blueprints.workspace_assistant as routes

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cache_root = tmp_path / "tmp"
    (cache_root / "guardtest").mkdir(parents=True)
    source = workspace / "review.docx"
    _fixture(source, "revision")
    original = source.read_bytes()
    monkeypatch.setattr(routes, "_TMP_ROOT", cache_root)
    monkeypatch.setattr(routes, "_get_session_id", lambda: "guardtest")
    monkeypatch.setattr(routes, "_workspace_dir", lambda: workspace)
    monkeypatch.setattr(routes, "_fs_guard", lambda _: True)
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(routes.workspace_assistant_bp)
    client = app.test_client()
    opened = client.post(
        "/api/v1/workspace/open_file_by_path", json={"path": "review.docx"}
    )
    assert opened.status_code == 200, opened.get_data(as_text=True)
    payload = opened.get_json()
    data = payload["data"]
    data["html"] = data["html"].replace("Original target", "Edited target")
    response = client.post(
        "/api/v1/workspace/auto_save",
        json={
            "file_type": "docx",
            "file_id": payload["file_id"],
            "ws_source_path": "review.docx",
            "explicit": True,
            "data": data,
            "expected_source_sha256": hashlib.sha256(original).hexdigest(),
        },
    )
    assert response.status_code == 409
    receipt = response.get_json()
    assert receipt["code"] == "source_structure_loss"
    assert receipt["persisted"] is False and receipt["verified"] is False
    assert receipt["draft_preserved"] is True and receipt["can_save_copy"] is True
    assert "tracked_changes:ins" in receipt["lost_features"]
    assert source.read_bytes() == original
    draft_path = cache_root / "guardtest" / (payload["file_id"] + ".docx")
    assert Document(draft_path).paragraphs[0].text.startswith("Edited target")
    copy = client.post(
        "/api/v1/workspace/save_file",
        json={
            "file_type": "docx",
            "file_id": payload["file_id"],
            "file_name": "review-copy.docx",
            "data": data,
        },
    )
    assert copy.status_code == 200
    assert (
        Document(io.BytesIO(copy.data)).paragraphs[0].text.startswith("Edited target")
    )
    assert source.read_bytes() == original
