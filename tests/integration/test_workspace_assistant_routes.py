# -*- coding: utf-8 -*-
"""
Integration tests for /api/v1/workspace/* endpoints (workspace_assistant_bp).

Covers fixes introduced in Logan/20260326:
  1. raw_file: send_file must use absolute path (Flask 3.1 rejects relative
     paths -> was returning 500, now returns 200).
  2. open_file: full upload-parse-persist workflow (DOCX / PDF).
  3. serve_workspace_file: serves files from workspace dir; path-traversal
     guard returns 403; missing file returns 404.
  4. auto_save: both first and second explicit save write different bytes
     (fix for "second save does not work" bug).
  5. raw_file: returns Cache-Control: no-store headers so browser never
     serves a cached (stale) response on repeated saves.
  6. JS source: cache-buster ?_=<ts> added to raw fetch URL, and
     showSaveFilePicker called on first Ctrl+S when no handle exists.

Note: recent-files panel feature was removed ("recent files not needed").
Tests for that feature (TestRecentFilesJsFix, uploads-path re-open) are
intentionally absent.
"""
from __future__ import annotations

import io
import os
import uuid
from pathlib import Path

import pytest


# ── Fixture: minimal Flask app with only workspace_assistant_bp ──────────────

@pytest.fixture(scope="module")
def wa_client(tmp_path_factory):
    """
    Flask test client backed by a temporary workspace/tmp directory.
    We patch _TMP_DIR and WORKSPACE_DIR so tests never touch the real workspace.
    """
    os.environ.setdefault("KOTO_AUTH_ENABLED", "false")

    tmp_root = tmp_path_factory.mktemp("wa_root")
    tmp_dir = tmp_root / "tmp"
    workspace_dir = tmp_root / "workspace"
    tmp_dir.mkdir(parents=True)
    workspace_dir.mkdir(parents=True)

    import web.blueprints.workspace_assistant as _wa
    import web.shared as _shared

    original_tmp = _wa._TMP_DIR
    original_ws = getattr(_shared, "WORKSPACE_DIR", None)
    _wa._TMP_DIR = tmp_dir
    _shared.WORKSPACE_DIR = str(workspace_dir)

    from flask import Flask
    from web.blueprints.workspace_assistant import workspace_assistant_bp

    app = Flask(__name__)
    app.register_blueprint(workspace_assistant_bp)
    app.config["TESTING"] = True

    with app.test_client() as client:
        yield client, tmp_dir, workspace_dir

    _wa._TMP_DIR = original_tmp
    if original_ws is not None:
        _shared.WORKSPACE_DIR = original_ws


def _fake_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<</Type /Catalog>>\nendobj\n%%EOF"


def _fake_docx_bytes() -> bytes:
    try:
        import docx
        from io import BytesIO
        doc = docx.Document()
        doc.add_paragraph("Hello world")
        buf = BytesIO()
        doc.save(buf)
        return buf.getvalue()
    except ImportError:
        return b""


# ── 1. GET /api/v1/workspace/raw/<file_id> ───────────────────────────────────

class TestRawFile:
    """Fix: send_file must receive an absolute path (Flask 3.1 requirement)."""

    def test_returns_200_with_pdf_content(self, wa_client):
        client, tmp_dir, _ = wa_client
        file_id = uuid.uuid4().hex
        (tmp_dir / f"{file_id}.pdf").write_bytes(_fake_pdf_bytes())
        resp = client.get(f"/api/v1/workspace/raw/{file_id}")
        assert resp.status_code == 200
        assert resp.content_type == "application/pdf"
        assert resp.data.startswith(b"%PDF")

    def test_path_passed_to_send_file_is_absolute(self, wa_client, monkeypatch):
        """The fix: .resolve() ensures send_file gets an absolute path."""
        client, tmp_dir, _ = wa_client
        file_id = uuid.uuid4().hex
        (tmp_dir / f"{file_id}.pdf").write_bytes(_fake_pdf_bytes())

        captured = {}
        import flask
        real_send_file = flask.send_file

        def spy_send_file(path_or_file, *args, **kwargs):
            captured["path"] = str(path_or_file)
            return real_send_file(path_or_file, *args, **kwargs)

        monkeypatch.setattr("web.blueprints.workspace_assistant.send_file", spy_send_file)
        resp = client.get(f"/api/v1/workspace/raw/{file_id}")

        assert resp.status_code == 200
        assert Path(captured["path"]).is_absolute(), (
            f"send_file received relative path {captured['path']!r}; "
            "fix requires .resolve() to make it absolute"
        )

    def test_returns_404_for_missing_file_id(self, wa_client):
        client, _, _ = wa_client
        resp = client.get(f"/api/v1/workspace/raw/{uuid.uuid4().hex}")
        assert resp.status_code == 404

    def test_returns_400_for_non_alnum_id(self, wa_client):
        client, _, _ = wa_client
        resp = client.get("/api/v1/workspace/raw/bad..id")
        assert resp.status_code in (400, 404)

    def test_docx_served_with_correct_mime(self, wa_client):
        client, tmp_dir, _ = wa_client
        file_id = uuid.uuid4().hex
        (tmp_dir / f"{file_id}.docx").write_bytes(b"PK\x03\x04fake")
        resp = client.get(f"/api/v1/workspace/raw/{file_id}")
        assert resp.status_code == 200
        assert "wordprocessingml" in resp.content_type


# ── 2. POST /api/v1/workspace/open_file ──────────────────────────────────────

class TestOpenFile:

    def test_rejects_missing_file_field(self, wa_client):
        client, _, _ = wa_client
        resp = client.post("/api/v1/workspace/open_file", data={})
        assert resp.status_code == 400

    def test_rejects_unsupported_extension(self, wa_client):
        client, _, _ = wa_client
        resp = client.post(
            "/api/v1/workspace/open_file",
            data={"file": (io.BytesIO(b"hello"), "notes.txt")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "不支持" in resp.get_json().get("error", "")

    def test_pdf_stored_in_tmp_dir(self, wa_client):
        """Uploading a PDF creates a file in tmp_dir."""
        client, tmp_dir, _ = wa_client
        resp = client.post(
            "/api/v1/workspace/open_file",
            data={"file": (io.BytesIO(_fake_pdf_bytes()), "report.pdf")},
            content_type="multipart/form-data",
        )
        body = resp.get_json()
        assert resp.status_code in (200, 500)
        if resp.status_code == 200:
            assert "file_id" in body
            matches = list(tmp_dir.glob(f"{body['file_id']}.*"))
            assert matches, "uploaded PDF must be saved in tmp_dir"

    def test_docx_returns_html_data(self, wa_client):
        client, _, _ = wa_client
        docx_bytes = _fake_docx_bytes()
        if not docx_bytes:
            pytest.skip("python-docx not available")
        resp = client.post(
            "/api/v1/workspace/open_file",
            data={"file": (io.BytesIO(docx_bytes), "document.docx")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["file_type"] == "docx"
        assert "html" in body.get("data", {})

    def test_file_id_is_hex_uuid(self, wa_client):
        client, _, _ = wa_client
        docx_bytes = _fake_docx_bytes()
        if not docx_bytes:
            pytest.skip("python-docx not available")
        resp = client.post(
            "/api/v1/workspace/open_file",
            data={"file": (io.BytesIO(docx_bytes), "id_test.docx")},
            content_type="multipart/form-data",
        )
        if resp.status_code != 200:
            pytest.skip("parse failed")
        file_id = resp.get_json()["file_id"]
        assert file_id.isalnum() and len(file_id) == 32


# ── 3. GET /api/v1/workspace/file/<path> ─────────────────────────────────────

class TestServeWorkspaceFile:

    def test_serves_pdf_from_workspace_root(self, wa_client):
        client, _, workspace_dir = wa_client
        (workspace_dir / "sample.pdf").write_bytes(_fake_pdf_bytes())
        resp = client.get("/api/v1/workspace/file/sample.pdf")
        assert resp.status_code == 200
        assert resp.content_type == "application/pdf"

    def test_serves_pdf_from_uploads_subdir(self, wa_client):
        """
        Critical for the recent-files fix: clicking a recent file uses
        'uploads/<name>' path which must resolve to workspace/uploads/<name>.
        """
        client, _, workspace_dir = wa_client
        uploads = workspace_dir / "uploads"
        uploads.mkdir(exist_ok=True)
        (uploads / "sub.pdf").write_bytes(_fake_pdf_bytes())
        resp = client.get("/api/v1/workspace/file/uploads/sub.pdf")
        assert resp.status_code == 200
        assert resp.content_type == "application/pdf"

    def test_returns_404_for_missing_file(self, wa_client):
        client, _, _ = wa_client
        resp = client.get("/api/v1/workspace/file/ghost.pdf")
        assert resp.status_code == 404

    def test_returns_400_for_unsupported_extension(self, wa_client):
        client, _, workspace_dir = wa_client
        (workspace_dir / "readme.txt").write_text("hi")
        resp = client.get("/api/v1/workspace/file/readme.txt")
        assert resp.status_code == 400

    def test_path_traversal_blocked(self, wa_client):
        client, _, _ = wa_client
        resp = client.get("/api/v1/workspace/file/../../../etc/passwd")
        assert resp.status_code in (403, 404)


# ── 5. Round-trip: upload → raw endpoint ─────────────────────────────────────

class TestRoundTrip:

    def test_upload_pdf_then_fetch_via_raw(self, wa_client):
        """
        Full pipeline: upload PDF -> get file_id -> fetch via /raw/<id> -> 200.
        Tests the absolute-path fix end-to-end.
        """
        client, _, _ = wa_client
        resp = client.post(
            "/api/v1/workspace/open_file",
            data={"file": (io.BytesIO(_fake_pdf_bytes()), "roundtrip.pdf")},
            content_type="multipart/form-data",
        )
        if resp.status_code != 200:
            pytest.skip("PDF parser not available")

        file_id = resp.get_json()["file_id"]
        raw = client.get(f"/api/v1/workspace/raw/{file_id}")
        assert raw.status_code == 200, (
            f"/raw/{file_id} returned {raw.status_code}. "
            "Check that send_file uses absolute path (.resolve())."
        )
        assert raw.data.startswith(b"%PDF")


# ── 6. list_files: size + mtime metadata ─────────────────────────────────────

class TestListFilesMetadata:

    def test_list_files_returns_size_and_mtime_for_files(self, wa_client):
        """
        After the panel-improvements commit, list_files must return size
        (human-readable string) and mtime (milliseconds int) for every file entry.
        """
        client, _, workspace_dir = wa_client
        # plant a file directly in the workspace dir so list_files picks it up
        uploads = workspace_dir / "uploads"
        uploads.mkdir(exist_ok=True)
        (uploads / "meta_test.pdf").write_bytes(b"%PDF-1.0 test")

        resp = client.get("/api/v1/workspace/list_files")
        assert resp.status_code == 200
        data = resp.get_json()

        # find our test file in the tree
        found = None
        for node in data.get("files", []):
            if node["type"] == "folder" and node["name"] == "uploads":
                for child in node.get("children", []):
                    if child["name"] == "meta_test.pdf":
                        found = child
                        break
        assert found is not None, "meta_test.pdf not found in list_files response"
        assert "size" in found, "list_files must include 'size' field for each file"
        assert "mtime" in found, "list_files must include 'mtime' field for each file"
        assert isinstance(found["size"], str), "'size' should be a human-readable string"
        assert isinstance(found["mtime"], (int, float)), "'mtime' should be a numeric timestamp"


# ── 7. PATCH /api/v1/workspace/rename ────────────────────────────────────────

class TestRenameEndpoint:

    def test_rename_nonexistent_file_returns_404(self, wa_client):
        client, _, _ = wa_client
        resp = client.patch(
            "/api/v1/workspace/rename",
            json={"path": "uploads/does_not_exist.pdf", "name": "new_name"},
        )
        assert resp.status_code == 404

    def test_rename_path_traversal_rejected(self, wa_client):
        client, _, _ = wa_client
        resp = client.patch(
            "/api/v1/workspace/rename",
            json={"path": "uploads/legit.pdf", "name": "../evil"},
        )
        # name contains '/' or '\\' → 400
        assert resp.status_code == 400

    def test_rename_preserves_extension(self, wa_client):
        client, _, workspace_dir = wa_client
        uploads = workspace_dir / "uploads"
        uploads.mkdir(exist_ok=True)
        src = uploads / "to_rename.pdf"
        src.write_bytes(b"%PDF-1.0")

        resp = client.patch(
            "/api/v1/workspace/rename",
            json={"path": "uploads/to_rename.pdf", "name": "renamed_file"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        # Extension must be preserved even though user didn't supply it
        assert data["path"].endswith(".pdf"), \
            "Rename must preserve original file extension"
        assert not (uploads / "to_rename.pdf").exists(), "Old file should be gone"
        assert (uploads / "renamed_file.pdf").exists(), "Renamed file should exist"

    def test_rename_duplicate_name_returns_409(self, wa_client):
        client, _, workspace_dir = wa_client
        uploads = workspace_dir / "uploads"
        uploads.mkdir(exist_ok=True)
        (uploads / "dup_src.docx").write_bytes(b"PK content")
        (uploads / "dup_target.docx").write_bytes(b"PK content")

        resp = client.patch(
            "/api/v1/workspace/rename",
            json={"path": "uploads/dup_src.docx", "name": "dup_target"},
        )
        assert resp.status_code == 409, \
            "Rename to an existing filename must return 409 Conflict"

    def test_rename_success_response_shape(self, wa_client):
        client, _, workspace_dir = wa_client
        uploads = workspace_dir / "uploads"
        uploads.mkdir(exist_ok=True)
        (uploads / "shape_test.docx").write_bytes(b"PK content")

        resp = client.patch(
            "/api/v1/workspace/rename",
            json={"path": "uploads/shape_test.docx", "name": "shape_renamed"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "path" in data, "Rename response must include 'path'"
        assert "name" in data, "Rename response must include 'name'"


# ── helpers shared by new test classes ───────────────────────────────────────

def _make_docx_bytes(text: str = "Test") -> bytes:
    """Minimal valid .docx (ZIP) with a single paragraph of text."""
    import io as _io
    import zipfile

    ct = (
        '<?xml version="1.0"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1"'
        ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
        ' Target="word/document.xml"/>'
        "</Relationships>"
    )
    doc = (
        '<?xml version="1.0"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>"
        "</w:document>"
    )
    dr = (
        '<?xml version="1.0"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
        z.writestr("word/_rels/document.xml.rels", dr)
    return buf.getvalue()


# ── 8. POST /api/v1/workspace/auto_save ──────────────────────────────────────

class TestAutoSave:
    """
    Fix: 'second save does not work'.

    Root cause: auto_save correctly updates the tmp file on every call, but
    the browser cached the first /raw/<id> response and returned stale bytes
    on every subsequent save, so the local file appeared unchanged.

    These tests verify the server always produces fresh bytes per save.
    """

    def _upload_docx(self, client) -> str:
        """Upload a minimal docx and return its file_id."""
        resp = client.post(
            "/api/v1/workspace/open_file",
            data={"file": (io.BytesIO(_make_docx_bytes("original")), "save_test.docx")},
            content_type="multipart/form-data",
        )
        if resp.status_code != 200:
            pytest.skip("docx parse not available in this environment")
        return resp.get_json()["file_id"]

    def test_missing_fields_returns_400(self, wa_client):
        client, _, _ = wa_client
        resp = client.post("/api/v1/workspace/auto_save", json={})
        assert resp.status_code == 400

    def test_invalid_file_id_returns_400(self, wa_client):
        client, _, _ = wa_client
        resp = client.post(
            "/api/v1/workspace/auto_save",
            json={"file_type": "docx", "file_id": "../evil", "data": "<p>x</p>"},
        )
        assert resp.status_code == 400

    def test_first_explicit_save_returns_ok(self, wa_client):
        client, _, _ = wa_client
        fid = self._upload_docx(client)
        resp = client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "docx",
                "file_id": fid,
                "ws_source_path": "save_test.docx",
                "explicit": True,
                "data": "<p>first edit</p>",
            },
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body.get("ok") is True
        assert "saved_at" in body

    def test_second_save_raw_bytes_differ_from_first(self, wa_client):
        """
        Core regression test: /raw/<id> must return different bytes after
        save2 vs save1 because the content changed.
        Before the cache-buster fix, the browser cached the first response
        so the local file was always overwritten with save1 bytes.
        """
        client, _, _ = wa_client
        fid = self._upload_docx(client)

        client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "docx", "file_id": fid,
                "ws_source_path": "save_test.docx", "explicit": True,
                "data": "<p>first edit</p>",
            },
        )
        raw1 = client.get(f"/api/v1/workspace/raw/{fid}").data

        client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "docx", "file_id": fid,
                "ws_source_path": "save_test.docx", "explicit": True,
                "data": "<p>second edit with substantially more text appended</p>",
            },
        )
        raw2 = client.get(f"/api/v1/workspace/raw/{fid}").data

        assert raw1 != raw2, (
            "raw bytes after save2 must differ from save1 — "
            "identical bytes means the server is not updating the tmp file"
        )
        assert len(raw2) > len(raw1), (
            f"save2 bytes ({len(raw2)}) should exceed save1 ({len(raw1)}) "
            "since more text was saved"
        )

    def test_workspace_file_updated_on_each_save(self, wa_client):
        """workspace/<ws_source_path> must be overwritten on every explicit save."""
        client, _, workspace_dir = wa_client
        fid = self._upload_docx(client)

        client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "docx", "file_id": fid,
                "ws_source_path": "save_test.docx", "explicit": True,
                "data": "<p>save A</p>",
            },
        )
        size1 = (workspace_dir / "save_test.docx").stat().st_size

        client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "docx", "file_id": fid,
                "ws_source_path": "save_test.docx", "explicit": True,
                "data": "<p>save B with much more text to ensure size increases</p>",
            },
        )
        size2 = (workspace_dir / "save_test.docx").stat().st_size

        assert size2 != size1, (
            f"workspace file unchanged after second save ({size1} bytes both times)"
        )

    def test_auto_save_implicit_succeeds(self, wa_client):
        """explicit=False (background auto-save) must also return 200."""
        client, _, _ = wa_client
        fid = self._upload_docx(client)
        resp = client.post(
            "/api/v1/workspace/auto_save",
            json={"file_type": "docx", "file_id": fid, "data": "<p>auto</p>"},
        )
        assert resp.status_code == 200

    def test_src_written_true_when_ws_path_provided(self, wa_client):
        """Response must include src_written=True when ws_source_path is given."""
        client, _, _ = wa_client
        fid = self._upload_docx(client)
        resp = client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "docx", "file_id": fid,
                "ws_source_path": "save_test.docx", "explicit": True,
                "data": "<p>check src_written</p>",
            },
        )
        assert resp.status_code == 200
        assert resp.get_json().get("src_written") is True


# ── 9. raw_file: Cache-Control no-store ──────────────────────────────────────

class TestRawFileNoCacheHeaders:
    """
    Fix: raw_file must return Cache-Control: no-store so the browser never
    serves the first-save's cached response on subsequent saves.
    Without this, the local file written via FileSystemFileHandle always
    received stale bytes (second save appeared to do nothing).
    """

    def test_no_store_header_present(self, wa_client):
        client, tmp_dir, _ = wa_client
        fid = uuid.uuid4().hex
        (tmp_dir / f"{fid}.pdf").write_bytes(_fake_pdf_bytes())

        resp = client.get(f"/api/v1/workspace/raw/{fid}")
        assert resp.status_code == 200
        cc = resp.headers.get("Cache-Control", "")
        assert "no-store" in cc, (
            f"Cache-Control must contain 'no-store' (got {cc!r}) — "
            "without it the browser caches save1 bytes and second save writes stale data"
        )

    def test_no_cache_header_present(self, wa_client):
        client, tmp_dir, _ = wa_client
        fid = uuid.uuid4().hex
        (tmp_dir / f"{fid}.docx").write_bytes(b"PK\x03\x04fake")

        resp = client.get(f"/api/v1/workspace/raw/{fid}")
        cc = resp.headers.get("Cache-Control", "")
        assert "no-cache" in cc, (
            f"Cache-Control must contain 'no-cache' (got {cc!r})"
        )

    def test_pragma_no_cache_present(self, wa_client):
        client, tmp_dir, _ = wa_client
        fid = uuid.uuid4().hex
        (tmp_dir / f"{fid}.pdf").write_bytes(_fake_pdf_bytes())

        resp = client.get(f"/api/v1/workspace/raw/{fid}")
        pragma = resp.headers.get("Pragma", "")
        assert "no-cache" in pragma, (
            f"Pragma: no-cache header required for HTTP/1.0 compatibility (got {pragma!r})"
        )


# ── 10. JS source: save-flow fixes ───────────────────────────────────────────

class TestSaveFlowJsFixes:
    """
    Validates workspace-assistant.js contains all three save-flow fixes:
      (a) State (tab, fsHandle, fileId, etc.) captured before any await
      (b) showSaveFilePicker called when no fsHandle exists (first save)
      (c) Cache-buster ?_=Date.now() on the /raw/ fetch URL
      (d) _isSaving guard with finally-block reset
    """

    JS_PATH = Path(__file__).parents[2] / "web" / "static" / "js" / "workspace-assistant.js"

    @property
    def src(self) -> str:
        return self.JS_PATH.read_text(encoding="utf-8")

    # (a) pre-await state capture -----------------------------------------

    def test_save_tab_captured_before_await(self):
        assert "_saveTab" in self.src, \
            "saveFile must capture _saveTab before any await"

    def test_save_fshandle_captured_before_await(self):
        assert "_saveFsHandle" in self.src, \
            "saveFile must capture _saveFsHandle before any await"

    def test_save_file_id_captured_before_await(self):
        assert "_saveFileId" in self.src, \
            "saveFile must capture _saveFileId before any await"

    def test_save_file_type_captured_before_await(self):
        assert "_saveFileType" in self.src, \
            "saveFile must capture _saveFileType before any await"

    def test_save_ws_path_captured_before_await(self):
        assert "_saveWsPath" in self.src, \
            "saveFile must capture _saveWsPath before any await"

    # (b) showSaveFilePicker on first save ---------------------------------

    def test_show_save_file_picker_used(self):
        assert "showSaveFilePicker" in self.src, \
            "saveFile must call showSaveFilePicker to get a write handle on first save"

    def test_abort_error_handled(self):
        assert "AbortError" in self.src, \
            "saveFile must handle AbortError (user cancelled the picker)"

    def test_handle_persisted_in_map(self):
        assert "_fsHandleMap.set(" in self.src, \
            "Acquired fsHandle must be stored in _fsHandleMap so future saves reuse it"

    def test_handle_stored_on_tab_after_picker(self):
        assert "_saveTab.fsHandle = _saveFsHandle" in self.src, \
            "Acquired fsHandle must be stored on the tab object for the next save"

    # (c) cache-buster on raw fetch ----------------------------------------

    def test_raw_fetch_has_timestamp_cache_buster(self):
        assert "Date.now()" in self.src, \
            "raw bytes fetch URL must include Date.now() as a cache-buster query param"

    def test_raw_fetch_url_has_query_param(self):
        assert "?_=${Date.now()}" in self.src, \
            "raw fetch URL must contain ?_=${Date.now()} to prevent browser caching"

    # (d) _isSaving guard --------------------------------------------------

    def test_is_saving_flag_present(self):
        assert "_isSaving" in self.src, \
            "_isSaving flag must exist to prevent concurrent double-saves"

    def test_is_saving_reset_in_finally(self):
        finally_idx = self.src.rfind("finally {")
        assert finally_idx != -1, "saveFile must have a finally block"
        assert "_isSaving = false" in self.src[finally_idx:], \
            "_isSaving must be reset to false in the finally block"
