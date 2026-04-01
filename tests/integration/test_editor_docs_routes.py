# -*- coding: utf-8 -*-
"""
Integration tests for /api/editor/docs/* endpoints (editor_docs_bp).

Verifies the full CRUD lifecycle for the Univer editor document store:
  GET    /api/editor/docs              — list
  POST   /api/editor/docs              — create
  GET    /api/editor/docs/<id>         — fetch
  PUT    /api/editor/docs/<id>         — save/update
  PATCH  /api/editor/docs/<id>         — rename
  DELETE /api/editor/docs/<id>         — delete
  POST   /api/editor/docs/import_path  — import from server path
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

# ── Minimal app fixture (editor_docs_bp only, no monolith) ───────────────────


@pytest.fixture(scope="module")
def editor_client(tmp_path_factory):
    """Flask test client with editor_docs_bp registered against a temp docs dir."""
    os.environ.setdefault("KOTO_AUTH_ENABLED", "false")

    docs_dir = tmp_path_factory.mktemp("editor_docs")
    # Point the blueprint's lazy dir resolver to the temp dir
    import web.blueprints.editor_docs as _ed_mod

    _ed_mod._DOCS_DIR = str(docs_dir)

    from flask import Flask

    from web.blueprints.editor_docs import editor_docs_bp

    app = Flask(__name__)
    app.register_blueprint(editor_docs_bp)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c

    # Cleanup: reset module-level cache for other test runs
    _ed_mod._DOCS_DIR = None


def _json(resp):
    body = resp.get_data(as_text=True)
    assert resp.status_code in (200, 201), f"HTTP {resp.status_code}: {body[:400]}"
    return resp.get_json()


# ─────────────────────────────────────────────────────────────────────────────
# List
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestEditorDocsList:
    def test_list_returns_200(self, editor_client):
        resp = editor_client.get("/api/editor/docs")
        assert resp.status_code == 200

    def test_list_returns_docs_array(self, editor_client):
        data = _json(editor_client.get("/api/editor/docs"))
        assert "docs" in data
        assert isinstance(data["docs"], list)


# ─────────────────────────────────────────────────────────────────────────────
# Create
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestEditorDocsCreate:
    def test_create_returns_201(self, editor_client):
        resp = editor_client.post(
            "/api/editor/docs",
            data=json.dumps({"name": "Test Doc"}),
            content_type="application/json",
        )
        assert resp.status_code == 201

    def test_create_returns_id(self, editor_client):
        resp = editor_client.post(
            "/api/editor/docs",
            data=json.dumps({"name": "Test Doc 2"}),
            content_type="application/json",
        )
        data = resp.get_json()
        assert "id" in data

    def test_create_default_name(self, editor_client):
        resp = editor_client.post(
            "/api/editor/docs",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data.get("name") or data.get("id")


# ─────────────────────────────────────────────────────────────────────────────
# Full CRUD lifecycle
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestEditorDocsCRUD:
    @pytest.fixture(autouse=True)
    def _create_doc(self, editor_client):
        resp = editor_client.post(
            "/api/editor/docs",
            data=json.dumps({"name": "CRUD Test"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        self.doc_id = resp.get_json()["id"]

    def test_get_returns_200(self, editor_client):
        resp = editor_client.get(f"/api/editor/docs/{self.doc_id}")
        assert resp.status_code == 200

    def test_get_returns_correct_id(self, editor_client):
        data = _json(editor_client.get(f"/api/editor/docs/{self.doc_id}"))
        assert data.get("id") == self.doc_id

    def test_update_saves_content(self, editor_client):
        payload = {"content": "Hello world", "type": "text"}
        resp = editor_client.put(
            f"/api/editor/docs/{self.doc_id}",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        fetched = _json(editor_client.get(f"/api/editor/docs/{self.doc_id}"))
        assert fetched.get("content") == "Hello world"

    def test_rename_updates_name(self, editor_client):
        resp = editor_client.patch(
            f"/api/editor/docs/{self.doc_id}",
            data=json.dumps({"name": "Renamed Doc"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        fetched = _json(editor_client.get(f"/api/editor/docs/{self.doc_id}"))
        assert fetched.get("name") == "Renamed Doc"

    def test_delete_returns_200(self, editor_client):
        resp = editor_client.delete(f"/api/editor/docs/{self.doc_id}")
        assert resp.status_code == 200

    def test_get_after_delete_returns_404(self, editor_client):
        editor_client.delete(f"/api/editor/docs/{self.doc_id}")
        resp = editor_client.get(f"/api/editor/docs/{self.doc_id}")
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Error cases
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestEditorDocsErrors:
    def test_get_nonexistent_returns_404(self, editor_client):
        resp = editor_client.get("/api/editor/docs/doesnotexist999")
        assert resp.status_code == 404

    def test_update_nonexistent_returns_404(self, editor_client):
        resp = editor_client.put(
            "/api/editor/docs/doesnotexist999",
            data=json.dumps({"content": "x"}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_delete_nonexistent_returns_404(self, editor_client):
        resp = editor_client.delete("/api/editor/docs/doesnotexist999")
        assert resp.status_code == 404

    def test_path_traversal_blocked(self, editor_client):
        resp = editor_client.get("/api/editor/docs/../../etc/passwd")
        assert resp.status_code in (400, 404)


# ─────────────────────────────────────────────────────────────────────────────
# Import from path (txt/md)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestEditorDocsImportPath:
    def test_import_txt_file(self, editor_client, tmp_path):
        txt = tmp_path / "sample.txt"
        txt.write_text("Hello from import", encoding="utf-8")
        resp = editor_client.post(
            "/api/editor/docs/import_path",
            data=json.dumps({"path": str(txt)}),
            content_type="application/json",
        )
        assert resp.status_code in (200, 201)
        data = resp.get_json()
        assert "id" in data

    def test_import_md_file(self, editor_client, tmp_path):
        md = tmp_path / "readme.md"
        md.write_text("# Heading\n\nsome text", encoding="utf-8")
        resp = editor_client.post(
            "/api/editor/docs/import_path",
            data=json.dumps({"path": str(md)}),
            content_type="application/json",
        )
        assert resp.status_code in (200, 201)

    def test_import_nonexistent_path_returns_error(self, editor_client):
        resp = editor_client.post(
            "/api/editor/docs/import_path",
            data=json.dumps({"path": "/nonexistent/path/xyz.txt"}),
            content_type="application/json",
        )
        assert resp.status_code in (400, 404, 500)

    def test_import_missing_path_key_returns_400(self, editor_client):
        resp = editor_client.post(
            "/api/editor/docs/import_path",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 400
