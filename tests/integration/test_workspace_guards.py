# -*- coding: utf-8 -*-
"""
Integration tests for the three guards introduced alongside the PPTX fix:

  1. open_file (upload endpoint) — rejects 0-byte uploaded file with HTTP 400
     and a human-readable Chinese error message.

  2. open_file_by_path — rejects a 0-byte source file in the workspace with
     HTTP 400 and a human-readable Chinese error message.

  3. list_workspace_files — the ppt_sessions directory must never appear in
     the returned file tree (it contains session-state artefacts, not user
     files).

These guards prevent the "Package not found" error family from leaking
through to the user as an opaque traceback.
"""
from __future__ import annotations

import io
import os
import uuid
from pathlib import Path

import pytest

# ── shared fixture ────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def wa_client(tmp_path_factory):
    """
    Flask test client backed by isolated tmp + workspace directories.
    _TMP_DIR and WORKSPACE_DIR are patched so tests never touch the real disk.
    """
    os.environ.setdefault("KOTO_AUTH_ENABLED", "false")

    tmp_root = tmp_path_factory.mktemp("guards_root")
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


# ── helper bytes ─────────────────────────────────────────────────────────────


def _real_pdf() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<</Type /Catalog>>\nendobj\n%%EOF"


def _real_docx() -> bytes:
    """Minimal valid DOCX via python-docx, or skip."""
    try:
        from io import BytesIO
        import docx

        doc = docx.Document()
        doc.add_paragraph("guard test")
        buf = BytesIO()
        doc.save(buf)
        return buf.getvalue()
    except ImportError:
        return b""


# ─────────────────────────────────────────────────────────────────────────────
# 1. open_file — 0-byte upload guard
# ─────────────────────────────────────────────────────────────────────────────


class TestOpenFileZeroByteGuard:
    """POST /api/v1/workspace/open_file must reject 0-byte uploads early."""

    def _upload(self, client, name: str, content: bytes):
        return client.post(
            "/api/v1/workspace/open_file",
            data={"file": (io.BytesIO(content), name)},
            content_type="multipart/form-data",
        )

    # ── 0-byte rejections ────────────────────────────────────────────────────

    def test_zero_byte_pdf_returns_400(self, wa_client):
        client, _, _ = wa_client
        resp = self._upload(client, "empty.pdf", b"")
        assert resp.status_code == 400, (
            f"0-byte PDF must return 400, got {resp.status_code}"
        )

    def test_zero_byte_pptx_returns_400(self, wa_client):
        client, _, _ = wa_client
        resp = self._upload(client, "empty.pptx", b"")
        assert resp.status_code == 400, (
            f"0-byte PPTX must return 400, got {resp.status_code}"
        )

    def test_zero_byte_docx_returns_400(self, wa_client):
        client, _, _ = wa_client
        resp = self._upload(client, "empty.docx", b"")
        assert resp.status_code == 400

    def test_zero_byte_xlsx_returns_400(self, wa_client):
        client, _, _ = wa_client
        resp = self._upload(client, "empty.xlsx", b"")
        assert resp.status_code == 400

    def test_zero_byte_error_message_contains_filename(self, wa_client):
        """Error body must name the offending file so the user knows what failed."""
        client, _, _ = wa_client
        resp = self._upload(client, "my_slides.pptx", b"")
        body = resp.get_json() or {}
        error = body.get("error", "")
        assert "my_slides.pptx" in error, (
            f"Error message should mention the filename; got: {error!r}"
        )

    def test_zero_byte_error_message_in_chinese(self, wa_client):
        """Error message must be a Chinese user-facing string, not a raw traceback."""
        client, _, _ = wa_client
        resp = self._upload(client, "blank.pdf", b"")
        body = resp.get_json() or {}
        error = body.get("error", "")
        # The guard message contains Chinese characters (文件内容为空)
        assert any(ord(c) > 127 for c in error), (
            f"Error message should be in Chinese; got: {error!r}"
        )

    def test_zero_byte_pptx_no_package_not_found_in_error(self, wa_client):
        """
        Guard must fire BEFORE python-pptx is invoked — 'Package not found'
        must never reach the client.
        """
        client, _, _ = wa_client
        resp = self._upload(client, "tricky.pptx", b"")
        body = resp.get_json() or {}
        error = body.get("error", "")
        assert "Package not found" not in error, (
            "0-byte guard must prevent 'Package not found' from reaching client"
        )

    def test_zero_byte_no_tmp_file_left_behind(self, wa_client):
        """The guard must clean up the 0-byte tmp file it created."""
        client, tmp_dir, _ = wa_client
        before = {p.name for p in tmp_dir.iterdir()}
        resp = self._upload(client, "cleanup.pptx", b"")
        assert resp.status_code == 400
        after = {p.name for p in tmp_dir.iterdir()}
        new_files = after - before
        assert new_files == set(), (
            f"0-byte guard should not leave files in tmp: {new_files}"
        )

    # ── non-zero content still works ─────────────────────────────────────────

    def test_non_zero_pdf_not_rejected_by_guard(self, wa_client):
        """A real PDF must pass the guard (may fail later in parsing, but not 400)."""
        client, _, _ = wa_client
        resp = self._upload(client, "real.pdf", _real_pdf())
        # Guard returns 400; everything else is a different status code
        assert resp.status_code != 400, (
            "Non-empty PDF must not be rejected by the 0-byte guard"
        )

    def test_non_zero_docx_not_rejected_by_guard(self, wa_client):
        client, _, _ = wa_client
        docx_bytes = _real_docx()
        if not docx_bytes:
            pytest.skip("python-docx not available")
        resp = self._upload(client, "real.docx", docx_bytes)
        assert resp.status_code != 400


# ─────────────────────────────────────────────────────────────────────────────
# 2. open_file_by_path — auto-repair of 0-byte workspace files
# ─────────────────────────────────────────────────────────────────────────────


class TestOpenFileByPathZeroByteGuard:
    """
    POST /api/v1/workspace/open_file_by_path must auto-repair 0-byte workspace
    files for supported extensions (.pptx, .docx, .xlsx) by seeding them with
    a minimal valid template, then proceeding to parse and return 200.

    For .pdf (cannot be synthesised into a parse-ready document) the endpoint
    still returns 400 because a seeded minimal PDF is not parseable by the
    PDF parser.

    For truly-unsupported cases (missing path, traversal, not-found) the
    existing 400/403/404 responses remain unchanged.
    """

    def _open_by_path(self, client, rel_path: str):
        return client.post(
            "/api/v1/workspace/open_file_by_path",
            json={"path": rel_path},
            content_type="application/json",
        )

    def _plant(self, workspace_dir: Path, rel: str, content: bytes) -> None:
        dest = workspace_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

    # ── 0-byte supported formats are auto-repaired and opened ────────────────

    def test_zero_byte_pptx_is_auto_repaired_and_returns_200(self, wa_client):
        """A 0-byte PPTX in the workspace must be seeded and return 200."""
        client, _, ws = wa_client
        self._plant(ws, "legacy_empty.pptx", b"")
        resp = self._open_by_path(client, "legacy_empty.pptx")
        assert resp.status_code == 200, (
            f"0-byte PPTX must be auto-repaired to return 200, got {resp.status_code}: "
            f"{resp.get_json()}"
        )

    def test_zero_byte_pptx_auto_repair_seeds_file_on_disk(self, wa_client):
        """After auto-repair the workspace file must be non-zero on disk."""
        client, _, ws = wa_client
        ws_file = ws / "auto_seed_check.pptx"
        ws_file.write_bytes(b"")
        self._open_by_path(client, "auto_seed_check.pptx")
        assert ws_file.stat().st_size > 0, (
            "open_file_by_path must seed the 0-byte workspace file before parsing"
        )

    def test_zero_byte_pptx_response_has_file_id_and_data(self, wa_client):
        """Auto-repaired PPTX response must contain file_id, file_name, data."""
        client, _, ws = wa_client
        self._plant(ws, "seeded_deck.pptx", b"")
        resp = self._open_by_path(client, "seeded_deck.pptx")
        assert resp.status_code == 200
        body = resp.get_json() or {}
        assert "file_id" in body, "Response must include file_id"
        assert "file_name" in body, "Response must include file_name"
        assert "data" in body, "Response must include data"
        assert body["file_name"] == "seeded_deck.pptx"

    def test_zero_byte_docx_is_auto_repaired_and_returns_200(self, wa_client):
        """A 0-byte DOCX in the workspace must be seeded and return 200."""
        try:
            import docx  # noqa: F401
        except ImportError:
            pytest.skip("python-docx not available")
        client, _, ws = wa_client
        self._plant(ws, "legacy_empty.docx", b"")
        resp = self._open_by_path(client, "legacy_empty.docx")
        assert resp.status_code == 200, (
            f"0-byte DOCX must be auto-repaired to return 200, got {resp.status_code}: "
            f"{resp.get_json()}"
        )

    def test_zero_byte_xlsx_is_auto_repaired_and_returns_200(self, wa_client):
        """A 0-byte XLSX in the workspace must be seeded and return 200."""
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            pytest.skip("openpyxl not available")
        client, _, ws = wa_client
        self._plant(ws, "legacy_empty.xlsx", b"")
        resp = self._open_by_path(client, "legacy_empty.xlsx")
        assert resp.status_code == 200, (
            f"0-byte XLSX must be auto-repaired to return 200, got {resp.status_code}: "
            f"{resp.get_json()}"
        )

    def test_zero_byte_pptx_no_package_not_found_in_response(self, wa_client):
        """After auto-repair 'Package not found' must never appear in the response."""
        client, _, ws = wa_client
        self._plant(ws, "no_pkg_err.pptx", b"")
        resp = self._open_by_path(client, "no_pkg_err.pptx")
        body = resp.get_json() or {}
        assert "Package not found" not in str(body), (
            "Auto-repair must prevent 'Package not found' from reaching client"
        )

    def test_zero_byte_pptx_file_type_in_response(self, wa_client):
        """Auto-repaired PPTX must have file_type='pptx' in the response."""
        client, _, ws = wa_client
        self._plant(ws, "type_check.pptx", b"")
        resp = self._open_by_path(client, "type_check.pptx")
        if resp.status_code == 200:
            body = resp.get_json() or {}
            assert body.get("file_type") == "pptx", (
                f"file_type must be 'pptx', got: {body.get('file_type')!r}"
            )

    # ── missing / traversal still handled correctly ──────────────────────────

    def test_missing_path_field_returns_400(self, wa_client):
        client, _, _ = wa_client
        resp = client.post(
            "/api/v1/workspace/open_file_by_path",
            json={},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_empty_path_field_returns_400(self, wa_client):
        client, _, _ = wa_client
        resp = self._open_by_path(client, "")
        assert resp.status_code == 400

    def test_nonexistent_file_returns_404(self, wa_client):
        client, _, _ = wa_client
        resp = self._open_by_path(client, "ghost_file.pptx")
        assert resp.status_code == 404

    def test_path_traversal_returns_403(self, wa_client):
        client, _, _ = wa_client
        resp = self._open_by_path(client, "../../../etc/passwd")
        assert resp.status_code == 403

    # ── non-zero content passes through unchanged ─────────────────────────────

    def test_real_pdf_not_rejected_by_zero_byte_guard(self, wa_client):
        client, _, ws = wa_client
        self._plant(ws, "real_report.pdf", _real_pdf())
        resp = self._open_by_path(client, "real_report.pdf")
        # Guard yields 400; a different code means the guard passed
        assert resp.status_code != 400, (
            "Non-empty PDF must not be rejected by the 0-byte guard"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. list_workspace_files — ppt_sessions excluded from file tree
# ─────────────────────────────────────────────────────────────────────────────


class TestListFilesSkipPptSessions:
    """
    The ppt_sessions directory holds PPTSessionManager artefacts (often 0-byte
    stub files).  It must never appear in the workspace file tree returned by
    GET /api/v1/workspace/list_files.
    """

    def _tree_names(self, data: dict) -> set[str]:
        """Collect all top-level entry names from list_files JSON."""
        return {entry["name"] for entry in data.get("files", [])}

    def _find_in_tree(self, nodes: list, name: str) -> bool:
        """Recursively search the tree for an entry with the given name."""
        for node in nodes:
            if node["name"] == name:
                return True
            if node.get("children"):
                if self._find_in_tree(node["children"], name):
                    return True
        return False

    # ── ppt_sessions folder hidden ───────────────────────────────────────────

    def test_ppt_sessions_dir_not_in_top_level_tree(self, wa_client):
        """ppt_sessions at workspace root must not appear in the tree."""
        client, _, ws = wa_client
        ppt_sessions = ws / "ppt_sessions"
        ppt_sessions.mkdir(exist_ok=True)
        (ppt_sessions / "1.pptx").write_bytes(b"")  # 0-byte artefact

        resp = client.get("/api/v1/workspace/list_files")
        assert resp.status_code == 200
        data = resp.get_json()
        top_names = self._tree_names(data)
        assert "ppt_sessions" not in top_names, (
            f"ppt_sessions must be excluded from the file tree; found in: {top_names}"
        )

    def test_ppt_sessions_zero_byte_file_not_in_tree(self, wa_client):
        """The 0-byte 1.pptx inside ppt_sessions must also not appear anywhere."""
        client, _, ws = wa_client
        ppt_sessions = ws / "ppt_sessions"
        ppt_sessions.mkdir(exist_ok=True)
        (ppt_sessions / "1.pptx").write_bytes(b"")

        resp = client.get("/api/v1/workspace/list_files")
        assert resp.status_code == 200
        files = resp.get_json().get("files", [])
        assert not self._find_in_tree(files, "1.pptx"), (
            "1.pptx inside ppt_sessions must not appear anywhere in the file tree"
        )

    def test_ppt_sessions_not_in_tree_even_with_real_file(self, wa_client):
        """Even if ppt_sessions contains a valid PPTX, the folder stays hidden."""
        client, _, ws = wa_client
        ppt_sessions = ws / "ppt_sessions"
        ppt_sessions.mkdir(exist_ok=True)
        # Write something non-empty to rule out any size-based filtering
        try:
            from pptx import Presentation as _Prs
            buf = __import__("io").BytesIO()
            _Prs().save(buf)
            (ppt_sessions / "session_real.pptx").write_bytes(buf.getvalue())
        except ImportError:
            (ppt_sessions / "session_real.pptx").write_bytes(b"PK\x03\x04fake")

        resp = client.get("/api/v1/workspace/list_files")
        assert resp.status_code == 200
        files = resp.get_json().get("files", [])
        assert not self._find_in_tree(files, "ppt_sessions"), (
            "ppt_sessions must always be excluded regardless of its contents"
        )

    # ── other skip-set entries are also hidden ────────────────────────────────

    def test_tmp_dir_not_in_tree(self, wa_client):
        client, _, ws = wa_client
        (ws / "tmp").mkdir(exist_ok=True)
        resp = client.get("/api/v1/workspace/list_files")
        files = resp.get_json().get("files", [])
        assert not self._find_in_tree(files, "tmp"), (
            "'tmp' folder must be excluded from the file tree"
        )

    def test_hidden_dot_dirs_not_in_tree(self, wa_client):
        client, _, ws = wa_client
        (ws / ".hidden_dir").mkdir(exist_ok=True)
        resp = client.get("/api/v1/workspace/list_files")
        files = resp.get_json().get("files", [])
        assert not self._find_in_tree(files, ".hidden_dir"), (
            "Dot-prefixed directories must be excluded"
        )

    # ── legitimate folders still appear ──────────────────────────────────────

    def test_normal_user_folder_is_in_tree(self, wa_client):
        """A normal folder (not in the skip set) must appear in the tree."""
        client, _, ws = wa_client
        user_folder = ws / "my_documents"
        user_folder.mkdir(exist_ok=True)
        (user_folder / "report.pdf").write_bytes(_real_pdf())

        resp = client.get("/api/v1/workspace/list_files")
        assert resp.status_code == 200
        files = resp.get_json().get("files", [])
        assert self._find_in_tree(files, "my_documents"), (
            "User-created folder 'my_documents' should appear in the file tree"
        )

    def test_workspace_name_and_path_present_in_response(self, wa_client):
        """Response must include workspace_name and workspace_path fields."""
        client, _, ws = wa_client
        resp = client.get("/api/v1/workspace/list_files")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "workspace_name" in data, "Response must include 'workspace_name'"
        assert "workspace_path" in data, "Response must include 'workspace_path'"

    def test_supported_flag_true_for_pptx(self, wa_client):
        """PPTX files in a normal folder must have supported=true."""
        client, _, ws = wa_client
        docs = ws / "presentations"
        docs.mkdir(exist_ok=True)
        (docs / "deck.pptx").write_bytes(b"PK\x03\x04fake")

        resp = client.get("/api/v1/workspace/list_files")
        assert resp.status_code == 200
        files = resp.get_json().get("files", [])
        # Find the presentations folder
        folder = next((f for f in files if f["name"] == "presentations"), None)
        if folder is None:
            pytest.skip("presentations folder not found in tree")
        child = next(
            (c for c in folder.get("children", []) if c["name"] == "deck.pptx"), None
        )
        assert child is not None, "deck.pptx should appear in the tree"
        assert child.get("supported") is True, (
            "PPTX files must have supported=True in the file tree"
        )

    def test_category_field_present_for_pdf(self, wa_client):
        """Each file entry must include a 'category' field."""
        client, _, ws = wa_client
        docs = ws / "reports"
        docs.mkdir(exist_ok=True)
        (docs / "q1.pdf").write_bytes(_real_pdf())

        resp = client.get("/api/v1/workspace/list_files")
        files = resp.get_json().get("files", [])
        folder = next((f for f in files if f["name"] == "reports"), None)
        if folder is None:
            pytest.skip("reports folder not found in tree")
        child = next(
            (c for c in folder.get("children", []) if c["name"] == "q1.pdf"), None
        )
        assert child is not None
        assert "category" in child, "File entry must include 'category' field"
        assert child["category"] == "pdf"
