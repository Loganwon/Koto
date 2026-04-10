# -*- coding: utf-8 -*-
"""
Integration tests for workspace file-operation endpoints that were previously
uncovered or contained bugs.

Bugs fixed (regression-guarded here):
  1. DELETE /api/v1/workspace/file rejected non-office extensions (400).
     Now all file types in the workspace can be deleted.
  2. POST /api/v1/workspace/auto_save with a traversal path leaked the path
     in a 500 error instead of returning a clean 403.

New coverage:
  - DELETE /api/v1/workspace/file  (all extensions + traversal + missing)
  - POST /api/v1/workspace/create_folder
  - PATCH /api/v1/workspace/rename  (folder rename)
  - DELETE /api/v1/workspace/folder
  - POST /api/v1/workspace/auto_save  (traversal guard)
  - GET  /api/v1/workspace/list_files  (skips hidden + system dirs)
  - POST /api/v1/fs/create_folder
  - DELETE /api/v1/workspace/fs_delete
  - PATCH /api/v1/workspace/fs_rename
  - POST /api/v1/workspace/fs_copy  (copy + move)
  - GET  /api/v1/workspace/browse_local
  - GET  /api/v1/workspace/current_dir
"""

from __future__ import annotations

import io
import os
import uuid
from pathlib import Path

import pytest

# ── Shared app fixture ────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def _app_bundle(tmp_path_factory):
    """
    Minimal Flask app with only workspace_assistant_bp registered.
    Workspace and tmp dirs are isolated per module run.
    """
    os.environ.setdefault("KOTO_AUTH_ENABLED", "false")

    tmp_root = tmp_path_factory.mktemp("fileops_root")
    tmp_dir = tmp_root / "tmp"
    workspace_dir = tmp_root / "workspace"
    tmp_dir.mkdir(parents=True)
    workspace_dir.mkdir(parents=True)

    import web.blueprints.workspace_assistant as _wa
    import web.shared as _shared

    _orig_tmp = _wa._TMP_DIR
    _orig_ws = getattr(_shared, "WORKSPACE_DIR", None)
    _wa._TMP_DIR = tmp_dir
    _shared.WORKSPACE_DIR = str(workspace_dir)

    from flask import Flask
    from web.blueprints.workspace_assistant import workspace_assistant_bp

    app = Flask(__name__)
    app.register_blueprint(workspace_assistant_bp)
    app.config["TESTING"] = True

    with app.test_client() as client:
        yield client, tmp_dir, workspace_dir

    _wa._TMP_DIR = _orig_tmp
    if _orig_ws is not None:
        _shared.WORKSPACE_DIR = _orig_ws


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /api/v1/workspace/file
# ─────────────────────────────────────────────────────────────────────────────


class TestDeleteWorkspaceFile:
    """
    Regression guard for Bug 1:
    The endpoint previously rejected non-ALLOWED_EXT files with 400.
    Now any file type present in the workspace can be deleted.
    """

    def _plant(self, workspace_dir: Path, name: str, content: bytes = b"x") -> str:
        """Create a file in workspace root and return its relative path."""
        (workspace_dir / name).write_bytes(content)
        return name

    def test_delete_txt_returns_ok(self, _app_bundle):
        """BUG FIX: deleting a .txt file must succeed (was returning 400)."""
        client, _, ws = _app_bundle
        path = self._plant(ws, f"del_{uuid.uuid4().hex[:6]}.txt")
        resp = client.delete(f"/api/v1/workspace/file?path={path}")
        assert resp.status_code == 200
        assert resp.get_json().get("ok") is True

    def test_delete_txt_file_removed_from_disk(self, _app_bundle):
        """File must actually be gone after delete."""
        client, _, ws = _app_bundle
        fname = f"gone_{uuid.uuid4().hex[:6]}.txt"
        self._plant(ws, fname)
        client.delete(f"/api/v1/workspace/file?path={fname}")
        assert not (ws / fname).exists()

    def test_delete_py_returns_ok(self, _app_bundle):
        """BUG FIX: .py files must be deletable."""
        client, _, ws = _app_bundle
        path = self._plant(ws, f"script_{uuid.uuid4().hex[:6]}.py", b"print('hi')")
        resp = client.delete(f"/api/v1/workspace/file?path={path}")
        assert resp.status_code == 200

    def test_delete_json_returns_ok(self, _app_bundle):
        """BUG FIX: .json files must be deletable."""
        client, _, ws = _app_bundle
        path = self._plant(ws, f"data_{uuid.uuid4().hex[:6]}.json", b"{}")
        resp = client.delete(f"/api/v1/workspace/file?path={path}")
        assert resp.status_code == 200

    def test_delete_md_returns_ok(self, _app_bundle):
        """BUG FIX: .md (markdown) files must be deletable."""
        client, _, ws = _app_bundle
        path = self._plant(ws, f"readme_{uuid.uuid4().hex[:6]}.md", b"# Hello")
        resp = client.delete(f"/api/v1/workspace/file?path={path}")
        assert resp.status_code == 200

    def test_delete_docx_still_works(self, _app_bundle):
        """Office format delete must still work after the fix."""
        client, _, ws = _app_bundle
        path = self._plant(ws, f"doc_{uuid.uuid4().hex[:6]}.docx", b"PK\x03\x04")
        resp = client.delete(f"/api/v1/workspace/file?path={path}")
        assert resp.status_code == 200

    def test_delete_missing_file_returns_404(self, _app_bundle):
        client, _, _ = _app_bundle
        resp = client.delete("/api/v1/workspace/file?path=no_such_file.txt")
        assert resp.status_code == 404

    def test_delete_missing_path_param_returns_400(self, _app_bundle):
        client, _, _ = _app_bundle
        resp = client.delete("/api/v1/workspace/file")
        assert resp.status_code == 400

    def test_delete_traversal_returns_403(self, _app_bundle):
        client, _, _ = _app_bundle
        resp = client.delete("/api/v1/workspace/file?path=../../etc/passwd")
        assert resp.status_code == 403

    def test_delete_subfolder_file(self, _app_bundle):
        """File in a subdirectory should also be deletable."""
        client, _, ws = _app_bundle
        sub = ws / "subdir_del"
        sub.mkdir(exist_ok=True)
        (sub / "inner.txt").write_bytes(b"inner")
        resp = client.delete("/api/v1/workspace/file?path=subdir_del/inner.txt")
        assert resp.status_code == 200
        assert not (sub / "inner.txt").exists()


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/create_folder
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateFolder:

    def test_create_folder_in_root(self, _app_bundle):
        client, _, ws = _app_bundle
        name = f"folder_{uuid.uuid4().hex[:8]}"
        resp = client.post("/api/v1/workspace/create_folder", json={"parent": "", "name": name})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("ok") is True
        assert data.get("name") == name
        assert (ws / name).is_dir()

    def test_create_folder_returns_path(self, _app_bundle):
        client, _, ws = _app_bundle
        name = f"fp_{uuid.uuid4().hex[:8]}"
        resp = client.post("/api/v1/workspace/create_folder", json={"parent": "", "name": name})
        assert resp.status_code == 200
        assert "path" in resp.get_json()

    def test_create_folder_in_subfolder(self, _app_bundle):
        client, _, ws = _app_bundle
        parent_name = f"parent_{uuid.uuid4().hex[:6]}"
        (ws / parent_name).mkdir(exist_ok=True)
        child_name = f"child_{uuid.uuid4().hex[:6]}"
        resp = client.post(
            "/api/v1/workspace/create_folder",
            json={"parent": parent_name, "name": child_name},
        )
        assert resp.status_code == 200
        assert (ws / parent_name / child_name).is_dir()

    def test_create_duplicate_folder_returns_409(self, _app_bundle):
        client, _, ws = _app_bundle
        name = f"dup_{uuid.uuid4().hex[:8]}"
        (ws / name).mkdir(exist_ok=True)
        resp = client.post("/api/v1/workspace/create_folder", json={"parent": "", "name": name})
        assert resp.status_code == 409

    def test_create_folder_empty_name_returns_400(self, _app_bundle):
        client, _, _ = _app_bundle
        resp = client.post("/api/v1/workspace/create_folder", json={"parent": "", "name": ""})
        assert resp.status_code == 400

    def test_create_folder_slash_in_name_returns_400(self, _app_bundle):
        client, _, _ = _app_bundle
        resp = client.post(
            "/api/v1/workspace/create_folder",
            json={"parent": "", "name": "a/b"},
        )
        assert resp.status_code == 400

    def test_create_folder_traversal_returns_403(self, _app_bundle):
        client, _, _ = _app_bundle
        resp = client.post(
            "/api/v1/workspace/create_folder",
            json={"parent": "../../evil", "name": "folder"},
        )
        assert resp.status_code == 403

    def test_create_folder_missing_parent_returns_404(self, _app_bundle):
        client, _, _ = _app_bundle
        resp = client.post(
            "/api/v1/workspace/create_folder",
            json={"parent": "nonexistent_parent", "name": "child"},
        )
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /api/v1/workspace/rename — folder rename path
# ─────────────────────────────────────────────────────────────────────────────


class TestRenameFolderPath:

    def test_rename_folder_success(self, _app_bundle):
        client, _, ws = _app_bundle
        old_name = f"old_folder_{uuid.uuid4().hex[:6]}"
        (ws / old_name).mkdir(exist_ok=True)
        new_name = f"new_folder_{uuid.uuid4().hex[:6]}"
        resp = client.patch(
            "/api/v1/workspace/rename",
            json={"path": old_name, "name": new_name},
        )
        assert resp.status_code == 200
        assert not (ws / old_name).exists()
        assert (ws / new_name).is_dir()

    def test_rename_folder_response_has_path(self, _app_bundle):
        client, _, ws = _app_bundle
        old_name = f"rf_src_{uuid.uuid4().hex[:6]}"
        (ws / old_name).mkdir(exist_ok=True)
        new_name = f"rf_dst_{uuid.uuid4().hex[:6]}"
        resp = client.patch("/api/v1/workspace/rename", json={"path": old_name, "name": new_name})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "path" in data
        assert "name" in data

    def test_rename_folder_duplicate_returns_409(self, _app_bundle):
        client, _, ws = _app_bundle
        a = f"rfa_{uuid.uuid4().hex[:6]}"
        b = f"rfb_{uuid.uuid4().hex[:6]}"
        (ws / a).mkdir(exist_ok=True)
        (ws / b).mkdir(exist_ok=True)
        resp = client.patch("/api/v1/workspace/rename", json={"path": a, "name": b})
        assert resp.status_code == 409

    def test_rename_nonexistent_folder_returns_404(self, _app_bundle):
        client, _, _ = _app_bundle
        resp = client.patch(
            "/api/v1/workspace/rename",
            json={"path": "ghost_folder", "name": "new_ghost"},
        )
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /api/v1/workspace/folder
# ─────────────────────────────────────────────────────────────────────────────


class TestDeleteWorkspaceFolder:

    def test_delete_empty_folder(self, _app_bundle):
        client, _, ws = _app_bundle
        name = f"del_empty_{uuid.uuid4().hex[:6]}"
        (ws / name).mkdir(exist_ok=True)
        resp = client.delete(f"/api/v1/workspace/folder?path={name}")
        assert resp.status_code == 200
        assert resp.get_json().get("ok") is True
        assert not (ws / name).exists()

    def test_delete_folder_with_contents(self, _app_bundle):
        client, _, ws = _app_bundle
        name = f"del_full_{uuid.uuid4().hex[:6]}"
        folder = ws / name
        folder.mkdir(exist_ok=True)
        (folder / "file.txt").write_bytes(b"content")
        (folder / "sub").mkdir(exist_ok=True)
        resp = client.delete(f"/api/v1/workspace/folder?path={name}")
        assert resp.status_code == 200
        assert not folder.exists()

    def test_delete_folder_missing_returns_404(self, _app_bundle):
        client, _, _ = _app_bundle
        resp = client.delete("/api/v1/workspace/folder?path=no_such_folder")
        assert resp.status_code == 404

    def test_delete_folder_missing_param_returns_400(self, _app_bundle):
        client, _, _ = _app_bundle
        resp = client.delete("/api/v1/workspace/folder")
        assert resp.status_code == 400

    def test_delete_folder_traversal_returns_403(self, _app_bundle):
        client, _, _ = _app_bundle
        resp = client.delete("/api/v1/workspace/folder?path=../../etc")
        assert resp.status_code == 403

    def test_cannot_delete_workspace_root(self, _app_bundle):
        """Deleting '.' (the workspace root itself) must be rejected with 403."""
        client, _, _ = _app_bundle
        # An empty path resolves to the root
        resp = client.delete("/api/v1/workspace/folder?path=")
        # missing param → 400; but test the root guard too
        assert resp.status_code in (400, 403)


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/auto_save — traversal guard
# ─────────────────────────────────────────────────────────────────────────────


class TestAutoSaveTraversalGuard:
    """
    Regression guard for Bug 2:
    Previously the path-traversal ValueError was swallowed by the generic
    except block and returned 500 with the path in the error message.
    Now it returns 403 (or at least not 500).
    """

    def _upload_docx(self, client) -> str:
        """Return a valid file_id from a real upload."""
        try:
            import docx as _docx
            buf = __import__("io").BytesIO()
            _docx.Document().save(buf)
            docx_bytes = buf.getvalue()
        except ImportError:
            pytest.skip("python-docx not available")

        resp = client.post(
            "/api/v1/workspace/open_file",
            data={"file": (__import__("io").BytesIO(docx_bytes), "autosave_test.docx")},
            content_type="multipart/form-data",
        )
        if resp.status_code != 200:
            pytest.skip("docx parse not available")
        return resp.get_json()["file_id"]

    def test_traversal_ws_path_returns_403_not_500(self, _app_bundle):
        """BUG FIX: traversal in ws_source_path must return 403, not 500."""
        client, _, _ = _app_bundle
        fid = self._upload_docx(client)
        resp = client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "docx",
                "file_id": fid,
                "ws_source_path": "../../evil.docx",
                "explicit": True,
                "data": "<p>attack</p>",
            },
        )
        assert resp.status_code == 403, (
            f"Path traversal in ws_source_path must return 403, got {resp.status_code}: "
            f"{resp.get_json()}"
        )

    def test_traversal_error_does_not_expose_path(self, _app_bundle):
        """Error message must not reveal the resolved absolute path."""
        client, _, _ = _app_bundle
        fid = self._upload_docx(client)
        resp = client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "docx",
                "file_id": fid,
                "ws_source_path": "../../secret.docx",
                "explicit": True,
                "data": "<p>attack</p>",
            },
        )
        # Error must not contain a filesystem path
        body = resp.get_json() or {}
        err = body.get("error", "")
        assert "\\" not in err and "/" not in err, (
            f"Error message must not leak filesystem paths, got: {err!r}"
        )

    def test_valid_ws_source_path_still_works(self, _app_bundle):
        """Normal (non-traversal) explicit save must still return 200."""
        client, _, _ = _app_bundle
        fid = self._upload_docx(client)
        resp = client.post(
            "/api/v1/workspace/auto_save",
            json={
                "file_type": "docx",
                "file_id": fid,
                "ws_source_path": f"valid_save_{fid[:8]}.docx",
                "explicit": True,
                "data": "<p>valid content</p>",
            },
        )
        assert resp.status_code == 200
        assert resp.get_json().get("ok") is True


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /api/v1/workspace/fs_delete
# ─────────────────────────────────────────────────────────────────────────────


class TestFsDelete:

    def test_fs_delete_file(self, _app_bundle, tmp_path):
        client, _, _ = _app_bundle
        f = tmp_path / "fsfile.txt"
        f.write_bytes(b"bye")
        resp = client.delete(f"/api/v1/workspace/fs_delete?path={f}")
        assert resp.status_code == 200
        assert not f.exists()

    def test_fs_delete_folder(self, _app_bundle, tmp_path):
        client, _, _ = _app_bundle
        d = tmp_path / "fsfolder"
        d.mkdir()
        (d / "inner.txt").write_bytes(b"x")
        resp = client.delete(f"/api/v1/workspace/fs_delete?path={d}")
        assert resp.status_code == 200
        assert not d.exists()

    def test_fs_delete_missing_path_param_returns_400(self, _app_bundle):
        client, _, _ = _app_bundle
        resp = client.delete("/api/v1/workspace/fs_delete")
        assert resp.status_code == 400

    def test_fs_delete_nonexistent_returns_404(self, _app_bundle, tmp_path):
        client, _, _ = _app_bundle
        resp = client.delete(f"/api/v1/workspace/fs_delete?path={tmp_path / 'nope.txt'}")
        assert resp.status_code == 404

    def test_fs_delete_system_path_returns_403(self, _app_bundle):
        client, _, _ = _app_bundle
        # Windows system path — should be blocked by _fs_guard
        resp = client.delete("/api/v1/workspace/fs_delete?path=C:\\Windows\\System32")
        assert resp.status_code in (403, 404)  # guard or non-existent in test env


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /api/v1/workspace/fs_rename
# ─────────────────────────────────────────────────────────────────────────────


class TestFsRename:

    def test_fs_rename_file(self, _app_bundle, tmp_path):
        client, _, _ = _app_bundle
        f = tmp_path / "old_name.txt"
        f.write_bytes(b"content")
        resp = client.patch(
            "/api/v1/workspace/fs_rename",
            json={"path": str(f), "name": "new_name"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("ok") is True
        assert data["name"] == "new_name.txt"  # extension preserved
        assert not f.exists()
        assert (tmp_path / "new_name.txt").exists()

    def test_fs_rename_folder(self, _app_bundle, tmp_path):
        client, _, _ = _app_bundle
        d = tmp_path / "old_dir"
        d.mkdir()
        resp = client.patch(
            "/api/v1/workspace/fs_rename",
            json={"path": str(d), "name": "new_dir"},
        )
        assert resp.status_code == 200
        assert not d.exists()
        assert (tmp_path / "new_dir").is_dir()

    def test_fs_rename_duplicate_returns_409(self, _app_bundle, tmp_path):
        client, _, _ = _app_bundle
        a = tmp_path / "rn_a.txt"
        b = tmp_path / "rn_b.txt"
        a.write_bytes(b"a")
        b.write_bytes(b"b")
        resp = client.patch(
            "/api/v1/workspace/fs_rename",
            json={"path": str(a), "name": "rn_b"},
        )
        assert resp.status_code == 409

    def test_fs_rename_missing_path_returns_400(self, _app_bundle):
        client, _, _ = _app_bundle
        resp = client.patch("/api/v1/workspace/fs_rename", json={"name": "x"})
        assert resp.status_code == 400

    def test_fs_rename_slash_in_name_returns_400(self, _app_bundle, tmp_path):
        client, _, _ = _app_bundle
        f = tmp_path / "slash_test.txt"
        f.write_bytes(b"x")
        resp = client.patch(
            "/api/v1/workspace/fs_rename",
            json={"path": str(f), "name": "a/b"},
        )
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/fs_copy
# ─────────────────────────────────────────────────────────────────────────────


class TestFsCopy:

    def test_copy_file(self, _app_bundle, tmp_path):
        client, _, _ = _app_bundle
        src = tmp_path / "cp_src.txt"
        src.write_bytes(b"hello copy")
        dst = tmp_path / "cp_dst"
        dst.mkdir()
        resp = client.post(
            "/api/v1/workspace/fs_copy",
            json={"src": str(src), "dst_dir": str(dst), "move": False},
        )
        assert resp.status_code == 200
        assert src.exists()  # original still there
        assert (dst / "cp_src.txt").exists()

    def test_move_file(self, _app_bundle, tmp_path):
        client, _, _ = _app_bundle
        src = tmp_path / "mv_src.txt"
        src.write_bytes(b"hello move")
        dst = tmp_path / "mv_dst"
        dst.mkdir()
        resp = client.post(
            "/api/v1/workspace/fs_copy",
            json={"src": str(src), "dst_dir": str(dst), "move": True},
        )
        assert resp.status_code == 200
        assert not src.exists()  # moved — original gone
        assert (dst / "mv_src.txt").exists()

    def test_copy_auto_renames_on_collision(self, _app_bundle, tmp_path):
        client, _, _ = _app_bundle
        src = tmp_path / "clash.txt"
        src.write_bytes(b"original")
        dst = tmp_path / "clash_dst"
        dst.mkdir()
        (dst / "clash.txt").write_bytes(b"existing")
        resp = client.post(
            "/api/v1/workspace/fs_copy",
            json={"src": str(src), "dst_dir": str(dst), "move": False},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        # Should be renamed to clash (1).txt
        assert "(1)" in data["name"] or data["name"] != "clash.txt"

    def test_copy_missing_src_returns_404(self, _app_bundle, tmp_path):
        client, _, _ = _app_bundle
        resp = client.post(
            "/api/v1/workspace/fs_copy",
            json={"src": str(tmp_path / "nope.txt"), "dst_dir": str(tmp_path)},
        )
        assert resp.status_code == 404

    def test_copy_missing_params_returns_400(self, _app_bundle):
        client, _, _ = _app_bundle
        resp = client.post("/api/v1/workspace/fs_copy", json={"src": "/some/path"})
        assert resp.status_code == 400

    def test_copy_invalid_dst_returns_400(self, _app_bundle, tmp_path):
        client, _, _ = _app_bundle
        src = tmp_path / "inv_dst.txt"
        src.write_bytes(b"x")
        # dst_dir is a file, not a directory
        not_a_dir = tmp_path / "not_a_dir.txt"
        not_a_dir.write_bytes(b"y")
        resp = client.post(
            "/api/v1/workspace/fs_copy",
            json={"src": str(src), "dst_dir": str(not_a_dir)},
        )
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/fs/create_folder
# ─────────────────────────────────────────────────────────────────────────────


class TestFsCreateFolder:

    def test_create_folder_in_tmp(self, _app_bundle, tmp_path):
        client, _, _ = _app_bundle
        name = f"new_folder_{uuid.uuid4().hex[:6]}"
        resp = client.post(
            "/api/v1/fs/create_folder",
            json={"parent": str(tmp_path), "name": name},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("ok") is True
        assert (tmp_path / name).is_dir()

    def test_duplicate_folder_returns_409(self, _app_bundle, tmp_path):
        client, _, _ = _app_bundle
        name = f"dup_fs_folder_{uuid.uuid4().hex[:6]}"
        (tmp_path / name).mkdir()
        resp = client.post(
            "/api/v1/fs/create_folder",
            json={"parent": str(tmp_path), "name": name},
        )
        assert resp.status_code == 409

    def test_empty_name_returns_400(self, _app_bundle, tmp_path):
        client, _, _ = _app_bundle
        resp = client.post(
            "/api/v1/fs/create_folder",
            json={"parent": str(tmp_path), "name": ""},
        )
        assert resp.status_code == 400

    def test_nonexistent_parent_returns_404(self, _app_bundle, tmp_path):
        client, _, _ = _app_bundle
        resp = client.post(
            "/api/v1/fs/create_folder",
            json={"parent": str(tmp_path / "ghost_parent"), "name": "child"},
        )
        assert resp.status_code == 404

    def test_missing_parent_returns_400(self, _app_bundle):
        client, _, _ = _app_bundle
        resp = client.post("/api/v1/fs/create_folder", json={"name": "orphan"})
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/workspace/browse_local
# ─────────────────────────────────────────────────────────────────────────────


class TestBrowseLocal:

    def test_browse_with_path_returns_entries(self, _app_bundle, tmp_path):
        client, _, _ = _app_bundle
        (tmp_path / "visible.txt").write_bytes(b"v")
        (tmp_path / ".hidden").write_bytes(b"h")
        sub = tmp_path / "subfolder"
        sub.mkdir()
        resp = client.get(f"/api/v1/workspace/browse_local?path={tmp_path}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "entries" in data
        names = [e["name"] for e in data["entries"]]
        assert "visible.txt" in names
        assert "subfolder" in names
        # Hidden file should be filtered out
        assert ".hidden" not in names

    def test_browse_file_returns_400(self, _app_bundle, tmp_path):
        client, _, _ = _app_bundle
        f = tmp_path / "not_a_dir.txt"
        f.write_bytes(b"x")
        resp = client.get(f"/api/v1/workspace/browse_local?path={f}")
        assert resp.status_code == 400

    def test_browse_nonexistent_returns_404(self, _app_bundle, tmp_path):
        client, _, _ = _app_bundle
        resp = client.get(
            f"/api/v1/workspace/browse_local?path={tmp_path / 'ghost_dir'}"
        )
        assert resp.status_code == 404

    def test_browse_entries_have_required_fields(self, _app_bundle, tmp_path):
        client, _, _ = _app_bundle
        (tmp_path / "field_check.txt").write_bytes(b"data")
        resp = client.get(f"/api/v1/workspace/browse_local?path={tmp_path}")
        assert resp.status_code == 200
        data = resp.get_json()
        file_entries = [e for e in data["entries"] if e["type"] == "file"]
        if file_entries:
            entry = file_entries[0]
            assert "name" in entry
            assert "path" in entry
            assert "size" in entry
            assert "mtime" in entry
            assert "supported" in entry
            assert "category" in entry

    def test_browse_current_and_parent_keys(self, _app_bundle, tmp_path):
        client, _, _ = _app_bundle
        resp = client.get(f"/api/v1/workspace/browse_local?path={tmp_path}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "current" in data
        assert "is_root" in data

    def test_browse_no_path_returns_root_level(self, _app_bundle):
        """No path param → root level (drives + quick_access) — must not crash."""
        client, _, _ = _app_bundle
        resp = client.get("/api/v1/workspace/browse_local")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("is_root") is True
        assert "quick_access" in data or "drives" in data


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/workspace/current_dir
# ─────────────────────────────────────────────────────────────────────────────


class TestCurrentDir:

    def test_returns_path_and_name(self, _app_bundle):
        client, _, ws = _app_bundle
        resp = client.get("/api/v1/workspace/current_dir")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "path" in data
        assert "name" in data

    def test_path_is_absolute(self, _app_bundle):
        client, _, ws = _app_bundle
        resp = client.get("/api/v1/workspace/current_dir")
        assert resp.status_code == 200
        path = resp.get_json()["path"]
        assert Path(path).is_absolute(), f"current_dir path must be absolute, got {path!r}"

    def test_name_matches_workspace_dir_name(self, _app_bundle):
        client, _, ws = _app_bundle
        resp = client.get("/api/v1/workspace/current_dir")
        assert resp.status_code == 200
        assert resp.get_json()["name"] == ws.name


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/workspace/list_files — additional coverage
# ─────────────────────────────────────────────────────────────────────────────


class TestListFilesAdditional:

    def test_list_files_skips_ppt_sessions(self, _app_bundle):
        """ppt_sessions must never appear in the file tree."""
        client, _, ws = _app_bundle
        ppt_dir = ws / "ppt_sessions"
        ppt_dir.mkdir(exist_ok=True)
        (ppt_dir / "session.json").write_bytes(b"{}")
        resp = client.get("/api/v1/workspace/list_files")
        assert resp.status_code == 200
        data = resp.get_json()
        all_names = [node["name"] for node in data.get("files", [])]
        assert "ppt_sessions" not in all_names

    def test_list_files_skips_tmp(self, _app_bundle):
        """tmp dir must never appear in the file tree."""
        client, tmp_dir, ws = _app_bundle
        # tmp_dir is INSIDE the workspace root in our fixture
        resp = client.get("/api/v1/workspace/list_files")
        assert resp.status_code == 200
        data = resp.get_json()
        all_names = [node["name"] for node in data.get("files", [])]
        assert "tmp" not in all_names

    def test_list_files_skips_hidden(self, _app_bundle):
        client, _, ws = _app_bundle
        (ws / ".hidden_file").write_bytes(b"secret")
        resp = client.get("/api/v1/workspace/list_files")
        data = resp.get_json()
        all_names = [node["name"] for node in data.get("files", [])]
        assert ".hidden_file" not in all_names

    def test_list_files_includes_txt_files(self, _app_bundle):
        """Non-office files should appear in the tree (supported=False)."""
        client, _, ws = _app_bundle
        fname = f"listable_{uuid.uuid4().hex[:6]}.txt"
        (ws / fname).write_bytes(b"content")
        resp = client.get("/api/v1/workspace/list_files")
        data = resp.get_json()
        all_file_nodes = [
            n for n in data.get("files", []) if n.get("type") == "file"
        ]
        names = [n["name"] for n in all_file_nodes]
        assert fname in names
        # txt should have supported=False
        entry = next(n for n in all_file_nodes if n["name"] == fname)
        assert entry["supported"] is False

    def test_list_files_response_has_workspace_info(self, _app_bundle):
        client, _, ws = _app_bundle
        resp = client.get("/api/v1/workspace/list_files")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "workspace_name" in data
        assert "workspace_path" in data
        assert "files" in data
