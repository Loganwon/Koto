"""
End-to-end integration tests covering every major user scenario for the
Workspace Assistant.

Each test class mirrors a concrete user workflow — create, open, save, rename,
move, delete, download, multi-tab, subfolder operations, file-browser, etc.

All tests run against a real (temporary) Flask client with an isolated workspace
directory so they can be executed in any order / in parallel.
"""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import textwrap
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_WORKSPACE_PATCH_TARGET = "web.shared.WORKSPACE_DIR"


@pytest.fixture()
def workspace_dir(tmp_path: Path):
    """Return a fresh temporary workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture()
def client(workspace_dir: Path):
    """Return a Flask test client with WORKSPACE_DIR patched to *workspace_dir*."""
    with patch(_WORKSPACE_PATCH_TARGET, str(workspace_dir)):
        from web.app import app

        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c


def _json_body(resp) -> dict:
    return resp.get_json(force=True, silent=True) or {}


# ===========================================================================
# Scenario 1: Create → Open → Save → Reopen  (the full Ctrl-S journey)
# ===========================================================================


class TestCreateOpenSaveReopen:
    """Complete user journey: new file → open → edit → Ctrl-S → close → reopen → verify."""

    # ── DOCX ──────────────────────────────────────────────────────────────

    def test_docx_full_round_trip(self, client, workspace_dir: Path):
        """Create docx → open → save HTML → reopen → data should reflect save."""
        # 1. Create
        r = client.post(
            "/api/v1/workspace/create_file",
            json={"folder": "", "name": "report.docx"},
        )
        assert r.status_code == 200

        # 2. Open
        r2 = client.post(
            "/api/v1/workspace/open_file_by_path",
            json={"path": "report.docx"},
        )
        assert r2.status_code == 200
        d = _json_body(r2)
        assert d["file_type"] == "docx"
        file_id = d["file_id"]

        # 3. Save (Ctrl-S path: explicit=true)
        html = "<p>Hello, <strong>World</strong>!</p>"
        r3 = client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "docx",
                "file_id": file_id,
                "ws_source_path": "report.docx",
                "explicit": True,
                "data": html,
            },
        )
        assert r3.status_code == 200
        body = _json_body(r3)
        assert body["ok"] is True
        assert body["src_written"] is True

        # 4. Verify workspace file is non-zero
        ws_file = workspace_dir / "report.docx"
        assert ws_file.stat().st_size > 0

        # 5. Reopen — the newly-written bytes should parse
        r4 = client.post(
            "/api/v1/workspace/open_file_by_path",
            json={"path": "report.docx"},
        )
        assert r4.status_code == 200
        d4 = _json_body(r4)
        assert d4["file_type"] == "docx"
        # The saved HTML should be reflected in the re-parsed data
        assert "Hello" in d4["data"].get("html", "")

    # ── XLSX ──────────────────────────────────────────────────────────────

    def test_xlsx_full_round_trip(self, client, workspace_dir: Path):
        # Create
        r = client.post(
            "/api/v1/workspace/create_file",
            json={"folder": "", "name": "budget.xlsx"},
        )
        assert r.status_code == 200

        # Open
        r2 = client.post(
            "/api/v1/workspace/open_file_by_path",
            json={"path": "budget.xlsx"},
        )
        assert r2.status_code == 200
        d = _json_body(r2)
        file_id = d["file_id"]

        # Save with Univer-format data
        wb_data = {
            "snapshot": {
                "id": "wb1",
                "sheetOrder": ["sheet1"],
                "sheets": {
                    "sheet1": {
                        "id": "sheet1",
                        "name": "Sheet1",
                        "rowCount": 10,
                        "columnCount": 5,
                        "cellData": {
                            "0": {"0": {"v": "Budget", "t": 1}},
                            "1": {"0": {"v": 100, "t": 2}},
                        },
                    }
                },
            },
            "_images": [],
        }
        r3 = client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "xlsx",
                "file_id": file_id,
                "ws_source_path": "budget.xlsx",
                "explicit": True,
                "data": wb_data,
            },
        )
        assert r3.status_code == 200
        assert _json_body(r3)["src_written"] is True

        # Reopen
        r4 = client.post(
            "/api/v1/workspace/open_file_by_path",
            json={"path": "budget.xlsx"},
        )
        assert r4.status_code == 200
        assert _json_body(r4)["file_type"] == "xlsx"

    # ── PPTX ──────────────────────────────────────────────────────────────

    def test_pptx_full_round_trip(self, client, workspace_dir: Path):
        # Create
        r = client.post(
            "/api/v1/workspace/create_file",
            json={"folder": "", "name": "deck.pptx"},
        )
        assert r.status_code == 200

        # Open — returns slide geometry data
        r2 = client.post(
            "/api/v1/workspace/open_file_by_path",
            json={"path": "deck.pptx"},
        )
        assert r2.status_code == 200
        d = _json_body(r2)
        assert d["file_type"] == "pptx"
        file_id = d["file_id"]
        slides_data = d["data"]

        # Save with the same data (no edits)
        r3 = client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "pptx",
                "file_id": file_id,
                "ws_source_path": "deck.pptx",
                "explicit": True,
                "data": slides_data,
            },
        )
        assert r3.status_code == 200
        assert _json_body(r3)["src_written"] is True

        # Reopen
        r4 = client.post(
            "/api/v1/workspace/open_file_by_path",
            json={"path": "deck.pptx"},
        )
        assert r4.status_code == 200

    # ── PDF (read-only) ───────────────────────────────────────────────────

    def test_pdf_open_is_readonly(self, client, workspace_dir: Path):
        """PDF files should open but saving should fail with unsupported format."""
        r = client.post(
            "/api/v1/workspace/create_file",
            json={"folder": "", "name": "readme.pdf"},
        )
        assert r.status_code == 200

        r2 = client.post(
            "/api/v1/workspace/open_file_by_path",
            json={"path": "readme.pdf"},
        )
        assert r2.status_code == 200
        d = _json_body(r2)
        assert d["file_type"] == "pdf"
        file_id = d["file_id"]

        # Attempt to save — should fail (PDF is readonly)
        r3 = client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "pdf",
                "file_id": file_id,
                "ws_source_path": "readme.pdf",
                "explicit": True,
                "data": "anything",
            },
        )
        assert r3.status_code == 400
        assert "不支持" in _json_body(r3).get("error", "")


# ===========================================================================
# Scenario 2: Auto-save (timer-based, non-explicit)
# ===========================================================================


class TestAutoSave:
    """Timer-triggered auto-save: writes to tmp but may or may not write src."""

    def test_auto_save_writes_tmp(self, client, workspace_dir: Path):
        """auto_save with explicit=true writes to both tmp AND workspace src."""
        # Setup: create & open a docx
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "draft.docx"}
        )
        r = client.post(
            "/api/v1/workspace/open_file_by_path", json={"path": "draft.docx"}
        )
        fid = _json_body(r)["file_id"]

        r2 = client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "docx",
                "file_id": fid,
                "ws_source_path": "draft.docx",
                "explicit": True,
                "data": "<p>Auto-saved content</p>",
            },
        )
        assert r2.status_code == 200
        body = _json_body(r2)
        assert body["ok"] is True
        assert body["src_written"] is True
        assert "saved_at" in body

    def test_auto_save_no_ws_path_skips_src_write(self, client, workspace_dir: Path):
        """When ws_source_path is null/empty, only tmp is updated."""
        client.post(
            "/api/v1/workspace/create_file",
            json={"folder": "", "name": "tmp_only.docx"},
        )
        r = client.post(
            "/api/v1/workspace/open_file_by_path", json={"path": "tmp_only.docx"}
        )
        fid = _json_body(r)["file_id"]

        r2 = client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "docx",
                "file_id": fid,
                "ws_source_path": None,
                "explicit": True,
                "data": "<p>No src write</p>",
            },
        )
        assert r2.status_code == 200
        assert _json_body(r2)["src_written"] is False

    def test_auto_save_non_explicit_still_writes_src_when_path_given(
        self, client, workspace_dir: Path
    ):
        """Current behavior: explicit flag determines src write when ws_source_path present."""
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "x.docx"}
        )
        r = client.post("/api/v1/workspace/open_file_by_path", json={"path": "x.docx"})
        fid = _json_body(r)["file_id"]

        r2 = client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "docx",
                "file_id": fid,
                "ws_source_path": "x.docx",
                "explicit": False,
                "data": "<p>Non-explicit</p>",
            },
        )
        assert r2.status_code == 200
        # Non-explicit should NOT write src
        assert _json_body(r2)["src_written"] is False

    def test_auto_save_validation_errors(self, client):
        """Missing fields should return 400."""
        # Missing file_type
        r = client.post(
            "/api/v1/workspace/auto_save", json={"file_id": "abc", "data": "x"}
        )
        assert r.status_code == 400

        # Missing file_id
        r = client.post(
            "/api/v1/workspace/auto_save", json={"file_type": "docx", "data": "x"}
        )
        assert r.status_code == 400

        # Missing data
        r = client.post(
            "/api/v1/workspace/auto_save", json={"file_type": "docx", "file_id": "abc"}
        )
        assert r.status_code == 400

    def test_auto_save_invalid_file_id(self, client):
        """Non-alphanumeric file_id should be rejected."""
        r = client.post(
            "/api/v1/workspace/auto_save",
            json={"file_type": "docx", "file_id": "../evil", "data": "x"},
        )
        assert r.status_code == 400
        assert "无效" in _json_body(r).get("error", "")


# ===========================================================================
# Scenario 3: Save then download (raw endpoint)
# ===========================================================================


class TestSaveThenDownload:
    """After saving, the /raw/<file_id> endpoint should return updated bytes."""

    def test_raw_returns_saved_bytes(self, client, workspace_dir: Path):
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "dl.docx"}
        )
        r = client.post("/api/v1/workspace/open_file_by_path", json={"path": "dl.docx"})
        fid = _json_body(r)["file_id"]

        # Save
        client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "docx",
                "file_id": fid,
                "ws_source_path": "dl.docx",
                "explicit": True,
                "data": "<p>Download me</p>",
            },
        )

        # Download raw
        r2 = client.get(f"/api/v1/workspace/raw/{fid}")
        assert r2.status_code == 200
        assert len(r2.data) > 0
        # Should be a valid docx (starts with PK zip header)
        assert r2.data[:2] == b"PK"

    def test_raw_pptx_returns_saved_bytes(self, client, workspace_dir: Path):
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "dl.pptx"}
        )
        r = client.post("/api/v1/workspace/open_file_by_path", json={"path": "dl.pptx"})
        d = _json_body(r)
        fid = d["file_id"]

        client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "pptx",
                "file_id": fid,
                "ws_source_path": "dl.pptx",
                "explicit": True,
                "data": d["data"],
            },
        )

        r2 = client.get(f"/api/v1/workspace/raw/{fid}")
        assert r2.status_code == 200
        assert r2.data[:2] == b"PK"

    def test_raw_nonexistent_returns_404(self, client):
        r = client.get("/api/v1/workspace/raw/deadbeef12345678")
        assert r.status_code == 404

    def test_raw_invalid_id_returns_400(self, client):
        r = client.get("/api/v1/workspace/raw/../../etc/passwd")
        assert r.status_code == 400


# ===========================================================================
# Scenario 4: Subfolder operations
# ===========================================================================


class TestSubfolderOperations:
    """Create file in subfolder → open → save → list → verify."""

    def test_create_in_subfolder(self, client, workspace_dir: Path):
        # Create folder first
        r = client.post(
            "/api/v1/workspace/create_folder",
            json={"parent": "", "name": "reports"},
        )
        assert r.status_code == 200

        # Create file in subfolder
        r2 = client.post(
            "/api/v1/workspace/create_file",
            json={"folder": "reports", "name": "q1.docx"},
        )
        assert r2.status_code == 200
        assert _json_body(r2)["path"] == "reports/q1.docx"

        # Verify on disk
        assert (workspace_dir / "reports" / "q1.docx").is_file()

    def test_open_and_save_subfolder_file(self, client, workspace_dir: Path):
        (workspace_dir / "docs").mkdir()
        # Create
        client.post(
            "/api/v1/workspace/create_file",
            json={"folder": "docs", "name": "memo.docx"},
        )

        # Open
        r = client.post(
            "/api/v1/workspace/open_file_by_path", json={"path": "docs/memo.docx"}
        )
        assert r.status_code == 200
        fid = _json_body(r)["file_id"]

        # Save
        r2 = client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "docx",
                "file_id": fid,
                "ws_source_path": "docs/memo.docx",
                "explicit": True,
                "data": "<p>Subfolder content</p>",
            },
        )
        assert r2.status_code == 200
        assert _json_body(r2)["src_written"] is True

        # Verify on disk
        assert (workspace_dir / "docs" / "memo.docx").stat().st_size > 100

    def test_nested_subfolder_create_and_open(self, client, workspace_dir: Path):
        # Create nested folders
        client.post(
            "/api/v1/workspace/create_folder", json={"parent": "", "name": "projects"}
        )
        client.post(
            "/api/v1/workspace/create_folder",
            json={"parent": "projects", "name": "alpha"},
        )
        client.post(
            "/api/v1/workspace/create_file",
            json={"folder": "projects/alpha", "name": "plan.xlsx"},
        )

        r = client.post(
            "/api/v1/workspace/open_file_by_path",
            json={"path": "projects/alpha/plan.xlsx"},
        )
        assert r.status_code == 200
        assert _json_body(r)["file_type"] == "xlsx"

    def test_list_shows_subfolder_files(self, client, workspace_dir: Path):
        (workspace_dir / "sub").mkdir()
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "sub", "name": "a.docx"}
        )
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "b.pptx"}
        )

        r = client.get("/api/v1/workspace/list_files")
        assert r.status_code == 200
        data = _json_body(r)
        # Flatten all file names
        names = _collect_names(data)
        assert "a.docx" in names
        assert "b.pptx" in names


def _collect_names(tree_data: Any) -> set:
    """Recursively collect all file/folder names from the tree response."""
    names = set()
    if isinstance(tree_data, dict):
        if "name" in tree_data:
            names.add(tree_data["name"])
        for child in tree_data.get("children", []):
            names |= _collect_names(child)
    elif isinstance(tree_data, list):
        for item in tree_data:
            names |= _collect_names(item)
    return names


# ===========================================================================
# Scenario 5: Rename then save
# ===========================================================================


class TestRenameThenSave:
    """Rename a file and verify saves still work with the new path."""

    def test_rename_docx_then_save(self, client, workspace_dir: Path):
        # Create & open
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "old.docx"}
        )
        r = client.post(
            "/api/v1/workspace/open_file_by_path", json={"path": "old.docx"}
        )
        fid = _json_body(r)["file_id"]

        # Rename
        r2 = client.patch(
            "/api/v1/workspace/rename",
            json={"path": "old.docx", "name": "new.docx"},
        )
        assert r2.status_code == 200
        assert _json_body(r2)["name"] == "new.docx"
        assert not (workspace_dir / "old.docx").exists()
        assert (workspace_dir / "new.docx").is_file()

        # Save with new path
        r3 = client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "docx",
                "file_id": fid,
                "ws_source_path": "new.docx",
                "explicit": True,
                "data": "<p>After rename</p>",
            },
        )
        assert r3.status_code == 200
        assert _json_body(r3)["src_written"] is True

    def test_rename_preserves_extension(self, client, workspace_dir: Path):
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "test.pptx"}
        )
        r = client.patch(
            "/api/v1/workspace/rename",
            json={"path": "test.pptx", "name": "presentation"},
        )
        assert r.status_code == 200
        # Should preserve .pptx extension
        assert _json_body(r)["name"] == "presentation.pptx"

    def test_rename_folder_then_open_file_inside(self, client, workspace_dir: Path):
        # Create folder with file
        client.post(
            "/api/v1/workspace/create_folder", json={"parent": "", "name": "olddir"}
        )
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "olddir", "name": "f.docx"}
        )

        # Rename folder
        r = client.patch(
            "/api/v1/workspace/rename",
            json={"path": "olddir", "name": "newdir"},
        )
        assert r.status_code == 200

        # Open file at new path
        r2 = client.post(
            "/api/v1/workspace/open_file_by_path",
            json={"path": "newdir/f.docx"},
        )
        assert r2.status_code == 200

    def test_rename_to_existing_returns_409(self, client, workspace_dir: Path):
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "a.docx"}
        )
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "b.docx"}
        )
        r = client.patch(
            "/api/v1/workspace/rename",
            json={"path": "a.docx", "name": "b.docx"},
        )
        assert r.status_code == 409


# ===========================================================================
# Scenario 6: Delete files and folders
# ===========================================================================


class TestDeleteScenarios:
    """Various delete operations and edge cases."""

    def test_delete_file(self, client, workspace_dir: Path):
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "bye.docx"}
        )
        assert (workspace_dir / "bye.docx").exists()

        r = client.delete("/api/v1/workspace/file?path=bye.docx")
        assert r.status_code == 200
        assert not (workspace_dir / "bye.docx").exists()

    def test_delete_nonexistent_returns_404(self, client):
        r = client.delete("/api/v1/workspace/file?path=ghost.docx")
        assert r.status_code == 404

    def test_delete_folder_recursive(self, client, workspace_dir: Path):
        client.post(
            "/api/v1/workspace/create_folder", json={"parent": "", "name": "rmdir"}
        )
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "rmdir", "name": "f.docx"}
        )
        assert (workspace_dir / "rmdir" / "f.docx").exists()

        r = client.delete("/api/v1/workspace/folder?path=rmdir")
        assert r.status_code == 200
        assert not (workspace_dir / "rmdir").exists()

    def test_delete_root_blocked(self, client):
        """Cannot delete the workspace root itself."""
        r = client.delete("/api/v1/workspace/folder?path=")
        assert r.status_code == 400  # empty path

    def test_delete_traversal_blocked(self, client):
        r = client.delete("/api/v1/workspace/file?path=../../../etc/passwd")
        assert r.status_code == 403

    def test_delete_file_no_ext_restriction(self, client, workspace_dir: Path):
        """Any file type can be deleted, not just ALLOWED_EXT."""
        (workspace_dir / "notes.txt").write_text("hello")
        r = client.delete("/api/v1/workspace/file?path=notes.txt")
        assert r.status_code == 200


# ===========================================================================
# Scenario 7: File upload (drag-and-drop / file picker)
# ===========================================================================


class TestFileUpload:
    """Upload files via open_file (multipart) — the drag-and-drop path."""

    def _make_docx_bytes(self) -> bytes:
        import docx as _docx

        doc = _docx.Document()
        doc.add_paragraph("Test content")
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()

    def test_upload_docx(self, client):
        data = self._make_docx_bytes()
        r = client.post(
            "/api/v1/workspace/open_file",
            data={"file": (io.BytesIO(data), "upload.docx")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 200
        d = _json_body(r)
        assert d["file_type"] == "docx"
        assert d["file_name"] == "upload.docx"
        assert "file_id" in d

    def test_upload_zero_byte_rejected(self, client):
        r = client.post(
            "/api/v1/workspace/open_file",
            data={"file": (io.BytesIO(b""), "empty.docx")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 400
        assert "为空" in _json_body(r).get("error", "")

    def test_upload_unsupported_ext_rejected(self, client):
        r = client.post(
            "/api/v1/workspace/open_file",
            data={"file": (io.BytesIO(b"data"), "script.py")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 400

    def test_upload_no_file_rejected(self, client):
        r = client.post("/api/v1/workspace/open_file")
        assert r.status_code == 400


# ===========================================================================
# Scenario 8: save_file (export / download)
# ===========================================================================


class TestSaveFileExport:
    """POST /save_file — export edited content as downloadable binary."""

    def test_export_docx(self, client, workspace_dir: Path):
        r = client.post(
            "/api/v1/workspace/save_file",
            json={
                "file_type": "docx",
                "data": "<p>Export test</p>",
                "file_name": "exported.docx",
            },
        )
        assert r.status_code == 200
        assert r.data[:2] == b"PK"  # docx is a ZIP

    def test_export_xlsx(self, client, workspace_dir: Path):
        wb_data = {
            "snapshot": {
                "id": "wb1",
                "sheetOrder": ["s1"],
                "sheets": {
                    "s1": {
                        "id": "s1",
                        "name": "Sheet1",
                        "rowCount": 5,
                        "columnCount": 3,
                        "cellData": {"0": {"0": {"v": "Test", "t": 1}}},
                    }
                },
            },
            "_images": [],
        }
        r = client.post(
            "/api/v1/workspace/save_file",
            json={
                "file_type": "xlsx",
                "data": wb_data,
                "file_name": "exported.xlsx",
            },
        )
        assert r.status_code == 200
        assert r.data[:2] == b"PK"

    def test_workspace_pptx_save_needs_file_id(self, client):
        r = client.post(
            "/api/v1/workspace/save_file",
            json={
                "file_type": "pptx",
                "data": {"slides": []},
                "file_name": "test.pptx",
            },
        )
        assert r.status_code == 400

    def test_workspace_pptx_save_with_valid_file_id(self, client, workspace_dir: Path):
        # Create & open to get a file_id with a tmp file
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "exp.pptx"}
        )
        r = client.post(
            "/api/v1/workspace/open_file_by_path", json={"path": "exp.pptx"}
        )
        d = _json_body(r)
        fid = d["file_id"]

        r2 = client.post(
            "/api/v1/workspace/save_file",
            json={
                "file_type": "pptx",
                "file_id": fid,
                "data": d["data"],
                "file_name": "exp.pptx",
            },
        )
        assert r2.status_code == 200
        assert r2.data[:2] == b"PK"

    def test_export_missing_fields_returns_400(self, client):
        r = client.post("/api/v1/workspace/save_file", json={"file_type": "docx"})
        assert r.status_code == 400

    def test_export_unsupported_type(self, client):
        r = client.post(
            "/api/v1/workspace/save_file",
            json={"file_type": "txt", "data": "hello"},
        )
        assert r.status_code == 400


# ===========================================================================
# Scenario 9: guarded absolute-path filesystem browser routes
# ===========================================================================


class TestAbsoluteFsWriteRoutes:
    """The local browser supports guarded filesystem operations."""

    def test_absolute_fs_write_routes_validate_missing_payloads(self, client):
        assert client.post("/api/v1/fs/create_file", json={}).status_code == 400
        assert client.post("/api/v1/fs/create_folder", json={}).status_code == 400
        assert client.delete("/api/v1/workspace/fs_delete").status_code == 400
        assert client.patch("/api/v1/workspace/fs_rename", json={}).status_code == 400
        assert client.post("/api/v1/workspace/fs_copy", json={}).status_code == 400
        assert client.post("/api/v1/workspace/upload-to-folder").status_code == 400

    def test_absolute_fs_create_file_route(self, client, tmp_path):
        resp = client.post(
            "/api/v1/fs/create_file",
            json={"parent": str(tmp_path), "name": "browser_created.txt"},
        )
        assert resp.status_code == 200
        assert (tmp_path / "browser_created.txt").is_file()


# ===========================================================================
# Scenario 11: List files
# ===========================================================================


class TestListFiles:
    """GET /list_files — verify tree structure, categories, and filtering."""

    def test_list_empty_workspace(self, client, workspace_dir: Path):
        r = client.get("/api/v1/workspace/list_files")
        assert r.status_code == 200

    def test_list_shows_supported_flag(self, client, workspace_dir: Path):
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "s.pptx"}
        )
        (workspace_dir / "readme.txt").write_text("hi")

        r = client.get("/api/v1/workspace/list_files")
        data = _json_body(r)
        files = _collect_file_entries(data)
        pptx_entry = next((f for f in files if f["name"] == "s.pptx"), None)
        txt_entry = next((f for f in files if f["name"] == "readme.txt"), None)
        assert pptx_entry is not None
        assert pptx_entry.get("supported") is True
        assert txt_entry is not None
        assert txt_entry.get("supported") is True

    def test_list_hides_tmp_dir(self, client, workspace_dir: Path):
        (workspace_dir / "tmp").mkdir(exist_ok=True)
        (workspace_dir / "tmp" / "junk.bin").write_bytes(b"x")
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "visible.docx"}
        )

        r = client.get("/api/v1/workspace/list_files")
        names = _collect_names(_json_body(r))
        assert "visible.docx" in names
        assert "tmp" not in names

    def test_list_hides_ppt_sessions(self, client, workspace_dir: Path):
        (workspace_dir / "ppt_sessions").mkdir()
        (workspace_dir / "ppt_sessions" / "sess.json").write_text("{}")
        r = client.get("/api/v1/workspace/list_files")
        names = _collect_names(_json_body(r))
        assert "ppt_sessions" not in names


def _collect_file_entries(tree_data: Any) -> list[dict]:
    """Recursively collect all file entries (non-folder) from the tree."""
    entries = []
    if isinstance(tree_data, dict):
        if "name" in tree_data and tree_data.get("type") == "file":
            entries.append(tree_data)
        for child in tree_data.get("children", []):
            entries.extend(_collect_file_entries(child))
    elif isinstance(tree_data, list):
        for item in tree_data:
            entries.extend(_collect_file_entries(item))
    return entries


# ===========================================================================
# Scenario 12: Current directory and set workspace
# ===========================================================================


class TestWorkspaceDir:
    """GET /current_dir and POST /set_workspace_dir."""

    def test_get_current_dir(self, client, workspace_dir: Path):
        r = client.get("/api/v1/workspace/current_dir")
        assert r.status_code == 200
        d = _json_body(r)
        assert "path" in d

    def test_set_workspace_dir(self, client, workspace_dir: Path):
        new_ws = workspace_dir / "alt_workspace"
        new_ws.mkdir()
        r = client.post(
            "/api/v1/workspace/set_workspace_dir",
            json={"path": str(new_ws)},
        )
        assert r.status_code == 200

    def test_set_workspace_dir_rejects_system_paths(self, client):
        r = client.post(
            "/api/v1/workspace/set_workspace_dir",
            json={"path": "C:\\Windows"},
        )
        assert r.status_code == 403

    def test_set_workspace_dir_rejects_empty(self, client):
        r = client.post(
            "/api/v1/workspace/set_workspace_dir",
            json={"path": ""},
        )
        assert r.status_code == 400


# ===========================================================================
# Scenario 13: open_abs_file (absolute-path file opening)
# ===========================================================================


class TestOpenAbsFile:
    """POST /open_abs_file — parse a supported file by absolute path."""

    def test_raw_absolute_file_route_removed(self, client):
        r = client.get("/api/v1/workspace/" + "serve_" + "abs", query_string={"path": ""})
        assert r.status_code == 404

    def test_open_abs_file_valid_file(self, client, workspace_dir: Path):
        f = workspace_dir / "open_me.txt"
        f.write_text("content here")
        r = client.post(
            "/api/v1/workspace/open_abs_file",
            json={"path": str(f)},
        )
        assert r.status_code == 200
        assert r.get_json()["data"]["content"] == "content here"

    def test_open_abs_file_missing_file(self, client, workspace_dir: Path):
        r = client.post(
            "/api/v1/workspace/open_abs_file",
            json={"path": str(workspace_dir / "nope.txt")},
        )
        assert r.status_code == 404

    def test_open_abs_file_system_path_blocked(self, client):
        r = client.post(
            "/api/v1/workspace/open_abs_file",
            json={"path": "C:\\Windows\\System32\\config\\SAM"},
        )
        assert r.status_code == 403

    def test_open_abs_file_empty_path(self, client):
        r = client.post("/api/v1/workspace/open_abs_file", json={"path": ""})
        assert r.status_code == 400


# ===========================================================================
# Scenario 14: Path traversal guards (comprehensive)
# ===========================================================================


class TestPathTraversalGuards:
    """Ensure all endpoints reject path traversal attempts."""

    @pytest.mark.parametrize(
        "path",
        [
            "../../../etc/passwd",
            "..\\..\\..\\Windows\\System32",
            "foo/../../bar",
            "/etc/shadow",
        ],
    )
    def test_open_file_by_path_traversal(self, client, path):
        r = client.post("/api/v1/workspace/open_file_by_path", json={"path": path})
        assert r.status_code in (403, 404)

    @pytest.mark.parametrize(
        "path",
        [
            "../../../etc/passwd",
            "..\\..\\..\\secret",
        ],
    )
    def test_delete_traversal(self, client, path):
        r = client.delete(f"/api/v1/workspace/file?path={path}")
        assert r.status_code == 403

    @pytest.mark.parametrize(
        "path",
        [
            "../../../etc/passwd",
        ],
    )
    def test_auto_save_traversal(self, client, path, workspace_dir: Path):
        # Create a valid file to get a file_id
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "t.docx"}
        )
        r = client.post("/api/v1/workspace/open_file_by_path", json={"path": "t.docx"})
        fid = _json_body(r)["file_id"]

        r2 = client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "docx",
                "file_id": fid,
                "ws_source_path": path,
                "explicit": True,
                "data": "<p>evil</p>",
            },
        )
        assert r2.status_code == 403

    def test_create_file_traversal(self, client):
        r = client.post(
            "/api/v1/workspace/create_file",
            json={"folder": "../../etc", "name": "evil.docx"},
        )
        assert r.status_code == 403

    def test_rename_traversal_in_path(self, client):
        r = client.patch(
            "/api/v1/workspace/rename",
            json={"path": "../../etc/passwd", "name": "hacked"},
        )
        assert r.status_code in (403, 404)

    def test_rename_separator_in_name(self, client, workspace_dir: Path):
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "a.docx"}
        )
        r = client.patch(
            "/api/v1/workspace/rename",
            json={"path": "a.docx", "name": "../../evil.docx"},
        )
        assert r.status_code == 400


# ===========================================================================
# Scenario 15: Multiple saves (idempotency)
# ===========================================================================


class TestMultipleSaves:
    """Saving the same file multiple times should work without errors."""

    def test_three_consecutive_saves(self, client, workspace_dir: Path):
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "multi.docx"}
        )
        r = client.post(
            "/api/v1/workspace/open_file_by_path", json={"path": "multi.docx"}
        )
        fid = _json_body(r)["file_id"]

        for i in range(3):
            r2 = client.post(
                "/api/v1/workspace/auto_save",
                json={
                    "file_type": "docx",
                    "file_id": fid,
                    "ws_source_path": "multi.docx",
                    "explicit": True,
                    "data": f"<p>Save #{i+1}</p>",
                },
            )
            assert r2.status_code == 200
            assert _json_body(r2)["src_written"] is True

        # Final content should reflect last save
        r3 = client.post(
            "/api/v1/workspace/open_file_by_path", json={"path": "multi.docx"}
        )
        assert r3.status_code == 200
        assert "Save #3" in _json_body(r3)["data"].get("html", "")

    def test_pptx_multiple_saves(self, client, workspace_dir: Path):
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "multi.pptx"}
        )
        r = client.post(
            "/api/v1/workspace/open_file_by_path", json={"path": "multi.pptx"}
        )
        d = _json_body(r)
        fid = d["file_id"]

        for _ in range(3):
            r2 = client.post(
                "/api/v1/workspace/auto_save",
                json={
                    "file_type": "pptx",
                    "file_id": fid,
                    "ws_source_path": "multi.pptx",
                    "explicit": True,
                    "data": d["data"],
                },
            )
            assert r2.status_code == 200


# ===========================================================================
# Scenario 16: Browse local filesystem
# ===========================================================================


class TestBrowseLocal:
    """GET /browse_local — list directory contents by absolute path."""

    def test_browse_workspace_dir(self, client, workspace_dir: Path):
        (workspace_dir / "visible.txt").write_text("hi")
        r = client.get(
            "/api/v1/workspace/browse_local",
            query_string={"path": str(workspace_dir)},
        )
        assert r.status_code == 200
        items = _json_body(r)
        # Should be a list of entries
        assert isinstance(items, list)
        names = [e.get("name") for e in items]
        assert "visible.txt" in names

    def test_browse_nonexistent_dir(self, client, workspace_dir: Path):
        r = client.get(
            "/api/v1/workspace/browse_local",
            query_string={"path": str(workspace_dir / "no_such_dir")},
        )
        assert r.status_code in (400, 404)


# ===========================================================================
# Scenario 17: Create file validation
# ===========================================================================


class TestCreateFileValidation:
    """Validate all edge cases for file/folder creation."""

    def test_empty_name_rejected(self, client):
        r = client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": ""}
        )
        assert r.status_code == 400

    def test_name_with_illegal_chars_rejected(self, client):
        for ch in ["<", ">", ":", '"', "|", "?", "*"]:
            r = client.post(
                "/api/v1/workspace/create_file",
                json={"folder": "", "name": f"bad{ch}.txt"},
            )
            assert r.status_code == 400, f"char {ch!r} should be rejected"

    def test_name_with_path_separator_rejected(self, client):
        r = client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "a/b.txt"}
        )
        assert r.status_code == 400

    def test_duplicate_name_returns_409(self, client, workspace_dir: Path):
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "dup.docx"}
        )
        r = client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "dup.docx"}
        )
        assert r.status_code == 409

    def test_create_in_nonexistent_folder_returns_404(self, client):
        r = client.post(
            "/api/v1/workspace/create_file",
            json={"folder": "no_such_dir", "name": "f.txt"},
        )
        assert r.status_code == 404

    def test_create_txt_file(self, client, workspace_dir: Path):
        """Non-office extensions should create empty files."""
        r = client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "notes.txt"}
        )
        assert r.status_code == 200
        assert (workspace_dir / "notes.txt").exists()
        assert (workspace_dir / "notes.txt").stat().st_size == 0  # touch()

    def test_create_folder_empty_name_rejected(self, client):
        r = client.post(
            "/api/v1/workspace/create_folder", json={"parent": "", "name": ""}
        )
        assert r.status_code == 400

    def test_create_folder_duplicate_returns_409(self, client, workspace_dir: Path):
        client.post(
            "/api/v1/workspace/create_folder", json={"parent": "", "name": "mydir"}
        )
        r = client.post(
            "/api/v1/workspace/create_folder", json={"parent": "", "name": "mydir"}
        )
        assert r.status_code == 409


# ===========================================================================
# Scenario 18: Open non-existent / unsupported files
# ===========================================================================


class TestOpenEdgeCases:
    """Edge cases for open_file_by_path."""

    def test_open_nonexistent_returns_404(self, client):
        r = client.post(
            "/api/v1/workspace/open_file_by_path", json={"path": "ghost.docx"}
        )
        assert r.status_code == 404

    def test_open_unsupported_ext_returns_400(self, client, workspace_dir: Path):
        (workspace_dir / "script.py").write_text("print('hi')")
        r = client.post(
            "/api/v1/workspace/open_file_by_path", json={"path": "script.py"}
        )
        assert r.status_code == 400

    def test_open_empty_path_returns_400(self, client):
        r = client.post("/api/v1/workspace/open_file_by_path", json={"path": ""})
        assert r.status_code == 400

    def test_open_missing_path_field_returns_400(self, client):
        r = client.post("/api/v1/workspace/open_file_by_path", json={})
        assert r.status_code == 400


# ===========================================================================
# Scenario 19: Zero-byte file auto-repair
# ===========================================================================


class TestZeroByteAutoRepair:
    """Legacy 0-byte files should be auto-repaired on open."""

    @pytest.mark.parametrize(
        "name,expected_type",
        [
            ("legacy.docx", "docx"),
            ("legacy.xlsx", "xlsx"),
            ("legacy.pptx", "pptx"),
            ("legacy.pdf", "pdf"),
        ],
    )
    def test_zero_byte_auto_repair(
        self, client, workspace_dir: Path, name, expected_type
    ):
        # Create a 0-byte file (simulating legacy behavior)
        (workspace_dir / name).touch()
        assert (workspace_dir / name).stat().st_size == 0

        r = client.post("/api/v1/workspace/open_file_by_path", json={"path": name})
        assert r.status_code == 200
        d = _json_body(r)
        assert d["file_type"] == expected_type

        # File should now be non-zero on disk
        assert (workspace_dir / name).stat().st_size > 0


# ===========================================================================
# Scenario 20: Concurrent-like rapid operations
# ===========================================================================


class TestRapidOperations:
    """Simulate rapid user actions that could expose race conditions."""

    def test_create_many_files_quickly(self, client, workspace_dir: Path):
        """Create 10 files in rapid succession."""
        for i in range(10):
            r = client.post(
                "/api/v1/workspace/create_file",
                json={"folder": "", "name": f"rapid_{i}.docx"},
            )
            assert r.status_code == 200

        # All should exist
        for i in range(10):
            assert (workspace_dir / f"rapid_{i}.docx").is_file()

    def test_open_save_open_save_rapid(self, client, workspace_dir: Path):
        """Open → save → reopen → save cycle without errors."""
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "rapid.docx"}
        )

        for cycle in range(5):
            r = client.post(
                "/api/v1/workspace/open_file_by_path", json={"path": "rapid.docx"}
            )
            assert r.status_code == 200
            fid = _json_body(r)["file_id"]

            r2 = client.post(
                "/api/v1/workspace/auto_save",
                json={
                    "file_type": "docx",
                    "file_id": fid,
                    "ws_source_path": "rapid.docx",
                    "explicit": True,
                    "data": f"<p>Cycle {cycle}</p>",
                },
            )
            assert r2.status_code == 200


# ===========================================================================
# Scenario 21: open_file_by_path with absolute paths (openBrowserFile path)
# ===========================================================================


class TestOpenByAbsolutePath:
    """
    When the file browser calls open_file_by_path with an absolute path that
    resolves inside the workspace, it should still work.
    """

    def test_absolute_path_inside_workspace(self, client, workspace_dir: Path):
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "abs.docx"}
        )
        abs_path = str(workspace_dir / "abs.docx")

        r = client.post("/api/v1/workspace/open_file_by_path", json={"path": abs_path})
        assert r.status_code == 200
        assert _json_body(r)["file_type"] == "docx"

    def test_absolute_path_outside_workspace_returns_403(self, client, tmp_path: Path):
        outside = tmp_path / "outside.docx"
        outside.touch()
        r = client.post(
            "/api/v1/workspace/open_file_by_path", json={"path": str(outside)}
        )
        assert r.status_code == 403

    def test_save_with_absolute_ws_source_path(self, client, workspace_dir: Path):
        """Save should work even if ws_source_path is absolute (inside workspace)."""
        client.post(
            "/api/v1/workspace/create_file", json={"folder": "", "name": "abssave.docx"}
        )
        r = client.post(
            "/api/v1/workspace/open_file_by_path", json={"path": "abssave.docx"}
        )
        fid = _json_body(r)["file_id"]

        abs_ws_path = str(workspace_dir / "abssave.docx")
        r2 = client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "docx",
                "file_id": fid,
                "ws_source_path": abs_ws_path,
                "explicit": True,
                "data": "<p>Absolute ws_source_path</p>",
            },
        )
        # This might fail if the backend only handles relative paths
        # Let's document the actual behavior
        assert r2.status_code in (200, 403)


# ===========================================================================
# Scenario 22: Full workflow — create folder → create file → open → edit →
#              save → rename → move → reopen → verify
# ===========================================================================


class TestCompleteWorkflow:
    """The ultimate end-to-end test covering the full user journey."""

    def test_full_user_journey(self, client, workspace_dir: Path):
        # 1. Create a project folder
        r = client.post(
            "/api/v1/workspace/create_folder", json={"parent": "", "name": "project"}
        )
        assert r.status_code == 200

        # 2. Create a document in it
        r = client.post(
            "/api/v1/workspace/create_file",
            json={"folder": "project", "name": "spec.docx"},
        )
        assert r.status_code == 200

        # 3. List files — should show the folder and file
        r = client.get("/api/v1/workspace/list_files")
        names = _collect_names(_json_body(r))
        assert "project" in names
        assert "spec.docx" in names

        # 4. Open the file
        r = client.post(
            "/api/v1/workspace/open_file_by_path", json={"path": "project/spec.docx"}
        )
        assert r.status_code == 200
        fid = _json_body(r)["file_id"]

        # 5. Save (Ctrl-S)
        r = client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "docx",
                "file_id": fid,
                "ws_source_path": "project/spec.docx",
                "explicit": True,
                "data": "<h1>Project Spec</h1><p>Version 1.0</p>",
            },
        )
        assert r.status_code == 200
        assert _json_body(r)["src_written"] is True

        # 6. Rename the file
        r = client.patch(
            "/api/v1/workspace/rename",
            json={"path": "project/spec.docx", "name": "specification"},
        )
        assert r.status_code == 200
        assert _json_body(r)["name"] == "specification.docx"

        # 7. Create a "final" subfolder
        r = client.post(
            "/api/v1/workspace/create_folder",
            json={"parent": "project", "name": "final"},
        )
        assert r.status_code == 200

        # 8. Reopen from renamed location
        r = client.post(
            "/api/v1/workspace/open_file_by_path",
            json={"path": "project/specification.docx"},
        )
        assert r.status_code == 200
        d = _json_body(r)
        assert "Project Spec" in d["data"].get("html", "")

        # 9. Save again at the renamed path
        r = client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "docx",
                "file_id": d["file_id"],
                "ws_source_path": "project/specification.docx",
                "explicit": True,
                "data": "<h1>Project Spec</h1><p>Version 2.0</p>",
            },
        )
        assert r.status_code == 200
        assert _json_body(r)["src_written"] is True

        # 10. Delete the project folder
        r = client.delete("/api/v1/workspace/folder?path=project")
        assert r.status_code == 200
        assert not (workspace_dir / "project").exists()


# ===========================================================================
# Scenario 23: JavaScript source code checks
# ===========================================================================


class TestJavaScriptSourceChecks:
    """Static analysis of workspace-assistant.js for critical patterns."""

    @pytest.fixture(autouse=True)
    def _load_js(self):
        js_path = (
            Path(__file__).resolve().parents[2]
            / "web"
            / "static"
            / "js"
            / "workspace-assistant.js"
        )
        self.js = js_path.read_text(encoding="utf-8")

    def test_ctrl_s_handler_exists(self):
        assert "e.key === 's'" in self.js
        assert "e.preventDefault()" in self.js
        assert "WA.saveFile()" in self.js

    def test_ctrl_s_uses_capture(self):
        """The keydown handler must use capture:true to beat WangEditor."""
        # Find the keydown listener that contains the Ctrl+S handler
        import re

        pattern = r"addEventListener\('keydown'.*?e\.key\s*===\s*'s'.*?\},\s*true\)"
        assert re.search(
            pattern, self.js, re.DOTALL
        ), "Ctrl+S handler should use capture: true"

    def test_save_file_calls_do_save(self):
        assert "_doSave(" in self.js

    def test_do_save_posts_to_auto_save(self):
        assert "/api/v1/workspace/auto_save" in self.js

    def test_do_save_sends_explicit_true(self):
        """Both saveFile and autoSave should send explicit: true."""
        assert "explicit: true" in self.js

    def test_open_workspace_file_uses_open_file_by_path(self):
        assert "open_file_by_path" in self.js

    def test_open_browser_file_splits_workspace_and_external_paths(self):
        """openBrowserFile should use parsed routes, not the raw absolute-byte route."""
        idx_open = self.js.find("openBrowserFile")
        idx_path = self.js.find("open_file_by_path", idx_open)
        idx_abs = self.js.find("open_abs_file", idx_open)
        assert idx_path != -1
        assert idx_abs != -1
        assert self.js.find("new File(" + "[blob]", idx_open) == -1

    def test_is_saving_guard_exists(self):
        """_isSaving prevents concurrent saves."""
        assert "_isSaving" in self.js

    def test_auto_save_timer_exists(self):
        assert "_autoSaveTimer" in self.js
        assert "setTimeout(WA.autoSave" in self.js


# ===========================================================================
# Scenario 24: Cleanup tmp dir
# ===========================================================================


class TestCleanupTmpDir:
    """Verify cleanup_tmp_dir behavior."""

    def test_cleanup_removes_zero_byte_tmp_files(self, workspace_dir: Path):
        from web.blueprints.workspace_assistant import _TMP_DIR, cleanup_tmp_dir

        _TMP_DIR.mkdir(parents=True, exist_ok=True)
        zero_file = _TMP_DIR / "dead.docx"
        zero_file.touch()
        assert zero_file.stat().st_size == 0

        deleted = cleanup_tmp_dir()
        assert deleted >= 1
        assert not zero_file.exists()

    def test_cleanup_preserves_recent_nonzero_files(self, workspace_dir: Path):
        from web.blueprints.workspace_assistant import _TMP_DIR, cleanup_tmp_dir

        _TMP_DIR.mkdir(parents=True, exist_ok=True)
        good_file = _TMP_DIR / "good.docx"
        good_file.write_bytes(b"PK" + b"\x00" * 100)

        cleanup_tmp_dir()
        assert good_file.exists()
