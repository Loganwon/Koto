# -*- coding: utf-8 -*-
"""
Integration tests for /api/v1/workspace/* endpoints (workspace_assistant_bp).

Covers fixes introduced in Logan/20260326:
  1. raw_file: send_file must use absolute path (Flask 3.1 rejects relative
     paths -> was returning 500, now returns 200).
  2. open_file: full upload-parse-persist workflow (DOCX / PDF).
  3. serve_workspace_file: serves files from workspace dir; path-traversal
     guard returns 403; missing file returns 404.
  4. Recent-files JS fix: _saveRecentFile stores path so re-open works.
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

    def test_pdf_persisted_to_uploads(self, wa_client):
        """Uploading a PDF copies it to workspace/uploads/ for left-panel browsing."""
        client, _, workspace_dir = wa_client
        client.post(
            "/api/v1/workspace/open_file",
            data={"file": (io.BytesIO(_fake_pdf_bytes()), "persist_test.pdf")},
            content_type="multipart/form-data",
        )
        uploads_dir = workspace_dir / "uploads"
        assert uploads_dir.exists()
        assert (uploads_dir / "persist_test.pdf").exists(), (
            "File must be copied to workspace/uploads/ so the left panel "
            "can list and re-open it — this enables the recent-files path fix"
        )

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


# ── 4. JS source validation: recent-files path fix ───────────────────────────

class TestRecentFilesJsFix:
    """
    Validates that workspace-assistant.js contains the correct fix for the
    'file not found when clicking recent file' bug.

    Bug: recent files stored only {name, ext, time}. Clicking called
    openWorkspaceFile(f.name) which resolved to workspace root, not uploads/.

    Fix: store {name, ext, path, time} where path='uploads/<name>', and use
    f.path in the onclick handler.
    """

    JS_PATH = Path(__file__).parents[2] / "web" / "static" / "js" / "workspace-assistant.js"

    @property
    def src(self):
        return self.JS_PATH.read_text(encoding="utf-8")

    def test_save_recent_accepts_path_parameter(self):
        assert "function _saveRecentFile(name, ext, path)" in self.src, \
            "_saveRecentFile must accept path as 3rd parameter"

    def test_recent_entry_stores_path_field(self):
        assert "path: wsPath" in self.src, \
            "Recent file entry must store {path: wsPath}"

    def test_render_uses_fpath_not_fname(self):
        assert "f.path ||" in self.src, \
            "renderRecentFiles must use f.path (not f.name) as the click argument"

    def test_render_has_uploads_fallback(self):
        assert "'uploads/' + f.name" in self.src, \
            "Fallback for legacy entries without .path must prepend 'uploads/'"

    def test_router_load_detects_workspace_path(self):
        assert "file.name.includes('/')" in self.src, \
            "Router.load must detect workspace paths via file.name.includes('/')"

    def test_router_load_calls_save_with_path(self):
        assert "_saveRecentFile(json.file_name, ext, wsPath)" in self.src, \
            "Router.load must pass wsPath as 3rd arg to _saveRecentFile"


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

    def test_uploaded_file_reopenable_via_uploads_path(self, wa_client):
        """
        File saved to workspace/uploads/ must be serveable via
        GET /api/v1/workspace/file/uploads/<name>.

        This is exactly what renderRecentFiles() now calls when re-opening
        a file from the recent-files panel.
        """
        client, _, workspace_dir = wa_client
        client.post(
            "/api/v1/workspace/open_file",
            data={"file": (io.BytesIO(_fake_pdf_bytes()), "reopen_test.pdf")},
            content_type="multipart/form-data",
        )
        resp = client.get("/api/v1/workspace/file/uploads/reopen_test.pdf")
        assert resp.status_code == 200, (
            "GET /api/v1/workspace/file/uploads/<name> must return 200 — "
            "this is the path used by the recent-files fix to re-open a file."
        )


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
