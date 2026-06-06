# -*- coding: utf-8 -*-
"""
Integration tests for the "create new file → open it" user journey.

Scenario the user reported as broken:
  1. Right-click folder in workspace tree → "新建文件"
  2. Type a filename (e.g. report.docx, sheet.xlsx, slides.pptx, note.txt)
  3. Press Enter — file is created via POST /api/v1/workspace/create_file
  4. Click the newly-created file in the tree
     → GET handled by openWorkspaceFile which calls
       POST /api/v1/workspace/open_file_by_path
  5. Expected: file opens in the editor
     Actual (before fix): HTTP 400 "文件内容为空，无法解析" because create_file
     used target.touch() which produces a 0-byte file, tripping the 0-byte guard.

Root-cause fix:
  create_workspace_file (and fs_create_file) now call _seed_new_file() which
  writes a minimal-valid template for .docx/.xlsx/.pptx and a stub PDF for
  .pdf so the resulting file is never 0-byte.

Coverage matrix:
  ┌──────────────────────────────────────────────────────────────────────┐
  │ API under test                   │ scenarios                        │
  ├──────────────────────────────────────────────────────────────────────┤
  │ POST /api/v1/workspace/create_file│ happy-path per extension         │
  │                                  │ validation errors                │
  │                                  │ duplicate name → 409             │
  │                                  │ path traversal → 403             │
  ├──────────────────────────────────────────────────────────────────────┤
  │ POST /api/v1/workspace/open_file_by_path│ round-trip after create   │
  │                                  │ newly created file opens OK      │
  ├──────────────────────────────────────────────────────────────────────┤
  │ POST /api/v1/fs/create_file      │ happy-path + seed check          │
  ├──────────────────────────────────────────────────────────────────────┤
  │ cleanup_tmp_dir()                │ unit-level: removes old/0-byte   │
  └──────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

# ── shared fixture ─────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def wa_client(tmp_path_factory):
    """Flask test client with isolated tmp + workspace directories."""
    os.environ.setdefault("KOTO_AUTH_ENABLED", "false")

    root = tmp_path_factory.mktemp("create_open_root")
    tmp_dir = root / "tmp"
    workspace_dir = root / "workspace"
    tmp_dir.mkdir(parents=True)
    workspace_dir.mkdir(parents=True)

    import web.blueprints.workspace_assistant as _wa
    import web.shared as _shared

    orig_tmp = _wa._TMP_DIR
    orig_ws = getattr(_shared, "WORKSPACE_DIR", None)
    _wa._TMP_DIR = tmp_dir
    _shared.WORKSPACE_DIR = str(workspace_dir)

    from flask import Flask

    from web.blueprints.workspace_assistant import workspace_assistant_bp

    app = Flask(__name__)
    app.register_blueprint(workspace_assistant_bp)
    app.config["TESTING"] = True

    with app.test_client() as client:
        yield client, tmp_dir, workspace_dir

    _wa._TMP_DIR = orig_tmp
    if orig_ws is not None:
        _shared.WORKSPACE_DIR = orig_ws


# ── helpers ────────────────────────────────────────────────────────────────


def _create(client, name: str, folder: str = ""):
    return client.post(
        "/api/v1/workspace/create_file",
        data=json.dumps({"folder": folder, "name": name}),
        content_type="application/json",
    )


def _open_by_path(client, path: str):
    return client.post(
        "/api/v1/workspace/open_file_by_path",
        data=json.dumps({"path": path}),
        content_type="application/json",
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1.  create_workspace_file — basic happy paths
# ══════════════════════════════════════════════════════════════════════════════


class TestCreateFileHappyPath:
    """POST /api/v1/workspace/create_file — successful creation."""

    def test_create_txt_returns_ok(self, wa_client):
        client, _, ws = wa_client
        resp = _create(client, "note.txt")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["name"] == "note.txt"
        assert "path" in body

    def test_created_txt_file_exists_on_disk(self, wa_client):
        client, _, ws = wa_client
        _create(client, "exists_check.txt")
        assert (ws / "exists_check.txt").exists()

    def test_create_returns_relative_path(self, wa_client):
        client, _, ws = wa_client
        resp = _create(client, "rel_path_test.txt")
        body = resp.get_json()
        assert not os.path.isabs(body["path"]), (
            "path in response must be workspace-relative, got: " + body["path"]
        )

    def test_create_in_subfolder(self, wa_client):
        client, _, ws = wa_client
        sub = ws / "notes"
        sub.mkdir(exist_ok=True)
        resp = _create(client, "sub_note.txt", folder="notes")
        assert resp.status_code == 200
        assert (sub / "sub_note.txt").exists()

    def test_create_folder_structure_in_path(self, wa_client):
        client, _, ws = wa_client
        deep = ws / "a" / "b"
        deep.mkdir(parents=True, exist_ok=True)
        resp = _create(client, "deep.txt", folder="a/b")
        assert resp.status_code == 200
        assert (deep / "deep.txt").exists()


# ══════════════════════════════════════════════════════════════════════════════
# 2.  Seed content — newly created files must NOT be 0-byte for Office formats
# ══════════════════════════════════════════════════════════════════════════════


class TestNewFileNotZeroByte:
    """The core regression: create_file must produce non-zero-byte files for
    .docx / .xlsx / .pptx / .pdf so they can be opened immediately."""

    def _check_non_zero(self, wa_client, name: str):
        client, _, ws = wa_client
        resp = _create(client, name)
        assert resp.status_code == 200, f"create {name} failed: {resp.get_json()}"
        rel = resp.get_json()["path"]
        full = ws / rel
        size = full.stat().st_size
        assert size > 0, (
            f"Newly created {name} must not be 0 bytes — got {size} bytes. "
            "While open_file_by_path now auto-repairs 0-byte files, it is still "
            "better to seed them on create so the workspace never stores corrupt files."
        )

    def test_new_docx_is_not_zero_byte(self, wa_client):
        self._check_non_zero(wa_client, "new_doc.docx")

    def test_new_xlsx_is_not_zero_byte(self, wa_client):
        self._check_non_zero(wa_client, "new_sheet.xlsx")

    def test_new_pptx_is_not_zero_byte(self, wa_client):
        self._check_non_zero(wa_client, "new_slides.pptx")

    def test_new_pdf_is_not_zero_byte(self, wa_client):
        self._check_non_zero(wa_client, "new_doc.pdf")

    def test_new_txt_may_be_zero_byte(self, wa_client):
        """Plain text files are fine as 0-byte — not parsed by the file guard."""
        client, _, ws = wa_client
        resp = _create(client, "empty_text.txt")
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 3.  Full round-trip: create → open_file_by_path (the actual user journey)
# ══════════════════════════════════════════════════════════════════════════════


class TestCreateThenOpen:
    """After creating a file the user immediately clicks it in the file tree.
    That triggers open_file_by_path, which must succeed (not return 400)."""

    def _round_trip(self, wa_client, name: str):
        client, _, ws = wa_client
        cr = _create(client, name)
        assert cr.status_code == 200, f"create failed: {cr.get_json()}"
        rel_path = cr.get_json()["path"]
        op = _open_by_path(client, rel_path)
        return op

    def test_create_then_open_docx(self, wa_client):
        resp = self._round_trip(wa_client, "journey_doc.docx")
        assert resp.status_code == 200, (
            f"Opening newly-created .docx returned {resp.status_code}: "
            f"{resp.get_json()}"
        )
        body = resp.get_json()
        assert body.get("file_type") == "docx"

    def test_create_then_open_xlsx(self, wa_client):
        resp = self._round_trip(wa_client, "journey_sheet.xlsx")
        assert resp.status_code == 200, (
            f"Opening newly-created .xlsx returned {resp.status_code}: "
            f"{resp.get_json()}"
        )
        body = resp.get_json()
        assert body.get("file_type") == "xlsx"

    def test_create_then_open_pptx(self, wa_client):
        resp = self._round_trip(wa_client, "journey_slides.pptx")
        assert resp.status_code == 200, (
            f"Opening newly-created .pptx returned {resp.status_code}: "
            f"{resp.get_json()}"
        )
        body = resp.get_json()
        assert body.get("file_type") == "pptx"

    def test_create_then_open_returns_file_id(self, wa_client):
        """file_id is required by the frontend for auto-save / export."""
        client, _, _ = wa_client
        cr = _create(client, "fid_test.docx")
        rel = cr.get_json()["path"]
        op = _open_by_path(client, rel)
        assert op.status_code == 200
        body = op.get_json()
        assert "file_id" in body, "Response must include file_id"
        assert body["file_id"], "file_id must not be empty"

    def test_create_then_open_returns_file_name(self, wa_client):
        client, _, _ = wa_client
        cr = _create(client, "fname_test.xlsx")
        rel = cr.get_json()["path"]
        op = _open_by_path(client, rel)
        assert op.status_code == 200
        body = op.get_json()
        assert body.get("file_name") == "fname_test.xlsx"

    def test_open_file_by_path_without_prior_create_still_works(self, wa_client):
        """Directly place a real docx in the workspace and open it."""
        client, _, ws = wa_client
        try:
            import io

            import docx

            doc = docx.Document()
            doc.add_paragraph("hello")
            buf = io.BytesIO()
            doc.save(buf)
            (ws / "direct_place.docx").write_bytes(buf.getvalue())
        except ImportError:
            pytest.skip("python-docx not installed")
        op = _open_by_path(client, "direct_place.docx")
        assert op.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 4.  create_workspace_file — validation / error paths
# ══════════════════════════════════════════════════════════════════════════════


class TestCreateFileValidation:
    """POST /api/v1/workspace/create_file must enforce its contract."""

    def test_empty_name_returns_400(self, wa_client):
        client, _, _ = wa_client
        resp = _create(client, "")
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_missing_name_field_returns_400(self, wa_client):
        client, _, _ = wa_client
        resp = client.post(
            "/api/v1/workspace/create_file",
            data=json.dumps({"folder": ""}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_name_with_slash_returns_400(self, wa_client):
        client, _, _ = wa_client
        resp = _create(client, "sub/dir/evil.txt")
        assert resp.status_code == 400

    def test_name_with_backslash_returns_400(self, wa_client):
        client, _, _ = wa_client
        resp = _create(client, "evil\\path.txt")
        assert resp.status_code == 400

    def test_name_with_null_byte_returns_400(self, wa_client):
        client, _, _ = wa_client
        resp = _create(client, "null\x00byte.txt")
        assert resp.status_code == 400

    def test_duplicate_name_returns_409(self, wa_client):
        client, _, ws = wa_client
        _create(client, "dupe_test.txt")
        resp = _create(client, "dupe_test.txt")
        assert resp.status_code == 409
        body = resp.get_json()
        assert "已存在" in body.get("error", "")

    def test_nonexistent_folder_returns_404(self, wa_client):
        client, _, _ = wa_client
        resp = _create(client, "file.txt", folder="no_such_folder")
        assert resp.status_code == 404

    def test_path_traversal_returns_403(self, wa_client):
        client, _, _ = wa_client
        resp = _create(client, "escape.txt", folder="../../../etc")
        assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# 5.  fs_create_file — absolute-path variant (file-browser context menu)
# ══════════════════════════════════════════════════════════════════════════════


class TestFsCreateFile:
    """POST /api/v1/fs/create_file uses absolute paths (file browser)."""

    def test_fs_create_txt_in_workspace(self, wa_client):
        client, _, ws = wa_client
        resp = client.post(
            "/api/v1/fs/create_file",
            data=json.dumps({"parent": str(ws), "name": "fs_note.txt"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert (ws / "fs_note.txt").exists()

    def test_fs_create_docx_is_not_zero_byte(self, wa_client):
        client, _, ws = wa_client
        resp = client.post(
            "/api/v1/fs/create_file",
            data=json.dumps({"parent": str(ws), "name": "fs_new.docx"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert (ws / "fs_new.docx").stat().st_size > 0

    def test_fs_create_xlsx_is_not_zero_byte(self, wa_client):
        client, _, ws = wa_client
        resp = client.post(
            "/api/v1/fs/create_file",
            data=json.dumps({"parent": str(ws), "name": "fs_new.xlsx"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert (ws / "fs_new.xlsx").stat().st_size > 0

    def test_fs_create_pptx_is_not_zero_byte(self, wa_client):
        client, _, ws = wa_client
        resp = client.post(
            "/api/v1/fs/create_file",
            data=json.dumps({"parent": str(ws), "name": "fs_new.pptx"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert (ws / "fs_new.pptx").stat().st_size > 0

    def test_fs_create_missing_parent_returns_400(self, wa_client):
        client, _, _ = wa_client
        resp = client.post(
            "/api/v1/fs/create_file",
            data=json.dumps({"name": "orphan.txt"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_fs_create_nonexistent_parent_returns_404(self, wa_client):
        client, _, _ = wa_client
        resp = client.post(
            "/api/v1/fs/create_file",
            data=json.dumps({"parent": "/no/such/path/anywhere", "name": "x.txt"}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_fs_create_duplicate_returns_409(self, wa_client):
        client, _, ws = wa_client
        client.post(
            "/api/v1/fs/create_file",
            data=json.dumps({"parent": str(ws), "name": "fs_dupe.txt"}),
            content_type="application/json",
        )
        resp = client.post(
            "/api/v1/fs/create_file",
            data=json.dumps({"parent": str(ws), "name": "fs_dupe.txt"}),
            content_type="application/json",
        )
        assert resp.status_code == 409


# ══════════════════════════════════════════════════════════════════════════════
# 6.  cleanup_tmp_dir() unit tests
# ══════════════════════════════════════════════════════════════════════════════


class TestCleanupTmpDir:
    """cleanup_tmp_dir() must remove 0-byte and expired files."""

    def test_cleanup_removes_zero_byte_file(self, tmp_path):
        import web.blueprints.workspace_assistant as _wa

        orig = _wa._TMP_DIR
        _wa._TMP_DIR = tmp_path
        try:
            (tmp_path / "empty.pptx").write_bytes(b"")
            removed = _wa.cleanup_tmp_dir(max_age_hours=24)
            assert removed >= 1
            assert not (tmp_path / "empty.pptx").exists()
        finally:
            _wa._TMP_DIR = orig

    def test_cleanup_removes_old_file(self, tmp_path):
        import web.blueprints.workspace_assistant as _wa

        orig = _wa._TMP_DIR
        _wa._TMP_DIR = tmp_path
        try:
            old = tmp_path / "old.pptx"
            old.write_bytes(b"PK fake content here")
            # Back-date mtime to 2 days ago
            old_mtime = time.time() - 2 * 86400
            os.utime(old, (old_mtime, old_mtime))
            removed = _wa.cleanup_tmp_dir(max_age_hours=24)
            assert removed >= 1
            assert not old.exists()
        finally:
            _wa._TMP_DIR = orig

    def test_cleanup_keeps_recent_file(self, tmp_path):
        import web.blueprints.workspace_assistant as _wa

        orig = _wa._TMP_DIR
        _wa._TMP_DIR = tmp_path
        try:
            recent = tmp_path / "recent.pptx"
            recent.write_bytes(b"PK fake content here")
            removed = _wa.cleanup_tmp_dir(max_age_hours=24)
            assert removed == 0
            assert recent.exists()
        finally:
            _wa._TMP_DIR = orig

    def test_cleanup_returns_count(self, tmp_path):
        import web.blueprints.workspace_assistant as _wa

        orig = _wa._TMP_DIR
        _wa._TMP_DIR = tmp_path
        try:
            for i in range(3):
                (tmp_path / f"zero_{i}.pptx").write_bytes(b"")
            removed = _wa.cleanup_tmp_dir(max_age_hours=24)
            assert removed == 3
        finally:
            _wa._TMP_DIR = orig

    def test_cleanup_on_empty_dir_returns_zero(self, tmp_path):
        import web.blueprints.workspace_assistant as _wa

        orig = _wa._TMP_DIR
        _wa._TMP_DIR = tmp_path
        try:
            removed = _wa.cleanup_tmp_dir(max_age_hours=24)
            assert removed == 0
        finally:
            _wa._TMP_DIR = orig

    def test_list_files_triggers_cleanup(self, wa_client):
        """GET /api/v1/workspace/list_files should silently run cleanup."""
        client, tmp_dir, _ = wa_client
        (tmp_dir / "stale_from_list.pptx").write_bytes(b"")
        resp = client.get("/api/v1/workspace/list_files")
        assert resp.status_code == 200
        # After the list call the 0-byte file should be gone
        assert not (tmp_dir / "stale_from_list.pptx").exists()
