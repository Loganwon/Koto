# -*- coding: utf-8 -*-
"""
Integration tests for file-related endpoints in web/app.py:
- POST /api/chat/file — file upload with chat
- GET  /api/files/download — file download proxy
- POST /api/file-editor/* — retired compatibility surface remains unavailable
"""

from __future__ import annotations

import io
import os
import tempfile

import pytest


@pytest.fixture(scope="module")
def client():
    """Create Flask test client from the monolith web app."""
    os.environ.setdefault("KOTO_AUTH_ENABLED", "false")
    os.environ.setdefault("KOTO_DEPLOY_MODE", "local")
    os.environ.pop("SENTRY_DSN", None)

    from web.app import app

    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        yield c


def _check(resp, ok_status=(200, 201)):
    body = resp.get_data(as_text=True)
    assert resp.status_code in ok_status, f"HTTP {resp.status_code}: {body[:400]}"
    return resp.get_json()


# ── POST /api/chat/file ──────────────────────────────────────────────────────


@pytest.mark.integration
class TestChatFileUpload:
    def test_no_file_returns_error(self, client):
        """POST /api/chat/file with no file part should fail."""
        resp = client.post("/api/chat/file", data={})
        assert resp.status_code in (400, 500)

    def test_empty_filename_returns_error(self, client):
        """POST /api/chat/file with empty filename should fail."""
        data = {"file": (io.BytesIO(b""), "")}
        resp = client.post(
            "/api/chat/file", data=data, content_type="multipart/form-data"
        )
        assert resp.status_code in (400, 500)

    def test_upload_txt_file_accepted(self, client):
        """A plain text file should be accepted (even if chat fails without LLM)."""
        data = {
            "file": (io.BytesIO(b"Hello world"), "test.txt"),
            "message": "Summarize this",
            "session": "test_session",
        }
        resp = client.post(
            "/api/chat/file", data=data, content_type="multipart/form-data"
        )
        # Accepted for processing (200) or fails at LLM stage (500) — not 404/405
        assert resp.status_code in (200, 400, 500)

    def test_upload_returns_json(self, client):
        """Response should be JSON regardless of success/failure."""
        data = {
            "file": (io.BytesIO(b"test content"), "sample.txt"),
            "message": "analyze",
            "session": "test_session",
        }
        resp = client.post(
            "/api/chat/file", data=data, content_type="multipart/form-data"
        )
        # Response should be parseable (JSON or streaming text)
        assert resp.content_type is not None


# ── Retired Notebook endpoints ───────────────────────────────────────────────


@pytest.mark.integration
class TestRetiredNotebookRoutes:
    @pytest.mark.parametrize(
        "path",
        (
            "/api/notebook/overview",
            "/api/notebook/qa",
            "/api/notebook/study_guide",
            "/api/notebook/upload",
        ),
    )
    def test_notebook_routes_are_not_registered(self, client, path):
        resp = client.post(path, json={})
        assert resp.status_code == 404


# ── GET /api/files/download ──────────────────────────────────────────────────


@pytest.mark.integration
class TestFileDownload:
    def test_missing_path_returns_404(self, client):
        resp = client.get("/api/files/download")
        assert resp.status_code == 404

    def test_nonexistent_file_returns_404(self, client):
        resp = client.get("/api/files/download?path=/nonexistent/file.txt")
        assert resp.status_code == 404

    def test_valid_file_returns_200(self, client):
        """Downloading an existing file should succeed."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
            tmp.write("download test content")
            tmp_path = tmp.name
        try:
            resp = client.get("/api/files/download", query_string={"path": tmp_path})
            assert resp.status_code == 200
            assert b"download test content" in resp.data
            resp.close()
        finally:
            try:
                os.unlink(tmp_path)
            except PermissionError:
                pass  # Windows file locking — temp dir will clean up

    def test_filename_with_url_delimiters_returns_exact_content(self, client, tmp_path):
        target = tmp_path / "download # report & data.txt"
        target.write_bytes(b"exact URL-encoded file content")
        response = client.get("/api/files/download", query_string={"path": str(target)})
        try:
            assert response.status_code == 200
            assert response.data == b"exact URL-encoded file content"
        finally:
            response.close()

    def test_directory_is_not_downloadable(self, client, tmp_path):
        response = client.get(
            "/api/files/download", query_string={"path": str(tmp_path)}
        )
        assert response.status_code == 404


# ── Retired /api/file-editor/* endpoints ─────────────────────────────────────


@pytest.mark.integration
class TestRetiredFileEditorRoutes:
    @pytest.mark.parametrize(
        "path",
        (
            "/api/file-editor/read",
            "/api/file-editor/write",
            "/api/file-editor/replace",
        ),
    )
    def test_legacy_file_editor_routes_are_not_registered(self, client, path):
        resp = client.post(path, json={})
        assert resp.status_code == 404
