# -*- coding: utf-8 -*-
"""
Integration tests for filesystem workspace endpoints, plus additional
rename/set_workspace_dir/open_abs_file coverage.

Bugs fixed (regression-guarded here):
  1. The unsafe absolute-byte file endpoint was retired; absolute files are
     opened through POST /api/v1/workspace/open_abs_file, which parses supported
     files and keeps the same filesystem guards.
  2. POST /api/v1/workspace/set_workspace_dir accepted system directories
     (e.g. C:\\Windows, C:\\Program Files) as the workspace root, which would
     let subsequent delete/rename/list_files operations target OS directories.
     Now rejects any path whose parts overlap with _FS_PROTECTED.

Additional coverage:
  - PATCH /api/v1/workspace/rename  file branch (extension preserved, empty
    stem rejected, missing-param, traversal)
  - POST /api/v1/workspace/open_abs_file (happy path, missing param, missing
    file, system-path blocked)
  - POST /api/v1/workspace/set_workspace_dir (happy path, persists in module,
    missing path, system path blocked, file-not-dir)
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

# ── Shared fixture ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def _bundle(tmp_path_factory):
    """
    Isolated Flask app with workspace_assistant_bp only.
    Provides: client, tmp_dir, workspace_dir.
    """
    os.environ.setdefault("KOTO_AUTH_ENABLED", "false")

    tmp_root = tmp_path_factory.mktemp("serveabs_root")
    tmp_dir = tmp_root / "tmp"
    workspace_dir = tmp_root / "workspace"
    settings_path = tmp_root / "user_settings.json"
    tmp_dir.mkdir(parents=True)
    workspace_dir.mkdir(parents=True)
    settings_path.write_text(
        json.dumps({"storage": {"workspace_dir": str(workspace_dir)}}),
        encoding="utf-8",
    )

    import web.blueprints.workspace_assistant as _wa
    import web.shared as _shared

    _orig_tmp = _wa._TMP_DIR
    _orig_ws = getattr(_shared, "WORKSPACE_DIR", None)
    _orig_settings_path = os.environ.get("KOTO_USER_SETTINGS_PATH")
    os.environ["KOTO_USER_SETTINGS_PATH"] = str(settings_path)
    _wa._TMP_DIR = tmp_dir
    _shared.clear_user_settings_cache()
    _shared.WORKSPACE_DIR = str(workspace_dir)

    from flask import Flask

    from web.blueprints.workspace_assistant import workspace_assistant_bp

    app = Flask(__name__)
    app.register_blueprint(workspace_assistant_bp)
    app.config["TESTING"] = True

    with app.test_client() as client:
        yield client, tmp_dir, workspace_dir

    _wa._TMP_DIR = _orig_tmp
    _shared.clear_user_settings_cache()
    if _orig_ws is not None:
        _shared.WORKSPACE_DIR = _orig_ws
    if _orig_settings_path is None:
        os.environ.pop("KOTO_USER_SETTINGS_PATH", None)
    else:
        os.environ["KOTO_USER_SETTINGS_PATH"] = _orig_settings_path


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/open_abs_file — security guard (Bug 1 regression)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestOpenAbsFileSecurity:
    """open_abs_file must block system paths and require a valid file."""

    def test_raw_absolute_file_route_is_removed(self, _bundle):
        client, _, _ = _bundle
        resp = client.get("/api/v1/workspace/" + "serve_" + "abs")
        assert resp.status_code == 404

    def test_open_abs_file_missing_param_returns_400(self, _bundle):
        client, _, _ = _bundle
        resp = client.post("/api/v1/workspace/open_abs_file", json={})
        assert resp.status_code == 400

    def test_open_abs_file_missing_file_returns_404(self, _bundle, tmp_path):
        client, _, _ = _bundle
        nonexistent = str(tmp_path / "ghost.txt")
        resp = client.post(
            "/api/v1/workspace/open_abs_file", json={"path": nonexistent}
        )
        assert resp.status_code == 404

    def test_open_abs_file_system_path_blocked_windows(self, _bundle):
        """Paths containing 'windows' or 'program files' must return 403.
        This is the Bug-1 regression guard."""
        client, _, _ = _bundle
        # Forge a path whose parts include a protected directory name.
        # We use a fake path (no need to exist) — the guard runs before is_file().
        fake = r"C:\windows\system.ini"
        resp = client.post("/api/v1/workspace/open_abs_file", json={"path": fake})
        assert resp.status_code == 403

    def test_open_abs_file_program_files_blocked(self, _bundle):
        client, _, _ = _bundle
        fake = r"C:\Program Files\some_app\config.ini"
        resp = client.post("/api/v1/workspace/open_abs_file", json={"path": fake})
        assert resp.status_code == 403

    def test_open_abs_file_programdata_blocked(self, _bundle):
        client, _, _ = _bundle
        fake = r"C:\ProgramData\secret.key"
        resp = client.post("/api/v1/workspace/open_abs_file", json={"path": fake})
        assert resp.status_code == 403

    def test_open_abs_file_system_volume_information_blocked(self, _bundle):
        client, _, _ = _bundle
        fake = r"C:\System Volume Information\data"
        resp = client.post("/api/v1/workspace/open_abs_file", json={"path": fake})
        assert resp.status_code == 403

    def test_open_abs_file_safe_tmp_text_file_returns_200(self, _bundle):
        """A real supported file in tmp should be parsed successfully."""
        client, tmp_dir, _ = _bundle
        safe_file = tmp_dir / f"safe_{uuid.uuid4().hex[:8]}.txt"
        safe_file.write_text("hello open_abs_file", encoding="utf-8")
        resp = client.post(
            "/api/v1/workspace/open_abs_file", json={"path": str(safe_file)}
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["file_type"] == "text"
        assert body["data"]["content"] == "hello open_abs_file"

    def test_open_abs_file_workspace_file_parsed(self, _bundle):
        """Files in the workspace dir (safe path) are parsed."""
        client, _, workspace_dir = _bundle
        ws_file = workspace_dir / f"ws_open_{uuid.uuid4().hex[:8]}.txt"
        ws_file.write_text("workspace content", encoding="utf-8")
        resp = client.post(
            "/api/v1/workspace/open_abs_file", json={"path": str(ws_file)}
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["content"] == "workspace content"


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/set_workspace_dir — Bug 2 regression + happy path
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestSetWorkspaceDir:
    """set_workspace_dir must reject system paths and persist valid ones."""

    def test_missing_path_returns_400(self, _bundle):
        client, _, _ = _bundle
        resp = client.post("/api/v1/workspace/set_workspace_dir", json={})
        assert resp.status_code == 400

    def test_empty_path_returns_400(self, _bundle):
        client, _, _ = _bundle
        resp = client.post("/api/v1/workspace/set_workspace_dir", json={"path": ""})
        assert resp.status_code == 400

    def test_system_windows_path_rejected(self, _bundle):
        """Bug-2 regression: C:\\Windows must return 403."""
        client, _, _ = _bundle
        resp = client.post(
            "/api/v1/workspace/set_workspace_dir",
            json={"path": r"C:\Windows"},
        )
        assert resp.status_code == 403

    def test_program_files_rejected(self, _bundle):
        client, _, _ = _bundle
        resp = client.post(
            "/api/v1/workspace/set_workspace_dir",
            json={"path": r"C:\Program Files"},
        )
        assert resp.status_code == 403

    def test_programdata_rejected(self, _bundle):
        client, _, _ = _bundle
        resp = client.post(
            "/api/v1/workspace/set_workspace_dir",
            json={"path": r"C:\ProgramData"},
        )
        assert resp.status_code == 403

    def test_file_path_rejected_as_not_dir(self, _bundle, tmp_path):
        """A path pointing to a file (not directory) must be rejected."""
        client, _, _ = _bundle
        f = tmp_path / "notadir.txt"
        f.write_text("x")
        resp = client.post(
            "/api/v1/workspace/set_workspace_dir",
            json={"path": str(f)},
        )
        assert resp.status_code == 400

    def test_valid_existing_dir_returns_200(self, _bundle, tmp_path):
        """An existing safe directory must succeed."""
        client, _, _ = _bundle
        safe_dir = tmp_path / "new_ws_existing"
        safe_dir.mkdir()
        resp = client.post(
            "/api/v1/workspace/set_workspace_dir",
            json={"path": str(safe_dir)},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

    def test_valid_returns_path_and_name(self, _bundle, tmp_path):
        """Response must include 'path' and 'name' fields."""
        client, _, _ = _bundle
        safe_dir = tmp_path / "new_ws_pathname"
        safe_dir.mkdir()
        data = client.post(
            "/api/v1/workspace/set_workspace_dir",
            json={"path": str(safe_dir)},
        ).get_json()
        assert "path" in data
        assert "name" in data
        assert data["name"] == safe_dir.name

    def test_creates_nonexistent_dir(self, _bundle, tmp_path):
        """A path that doesn't exist yet should be created and succeed."""
        client, _, _ = _bundle
        new_dir = tmp_path / "brand_new_workspace"
        assert not new_dir.exists()
        resp = client.post(
            "/api/v1/workspace/set_workspace_dir",
            json={"path": str(new_dir)},
        )
        assert resp.status_code == 200
        assert new_dir.exists()

    def test_persists_to_shared_workspace_dir(self, _bundle, tmp_path):
        """After setting, web.shared.WORKSPACE_DIR should reflect the new path."""
        import web.shared as _shared

        client, _, _ = _bundle
        new_dir = tmp_path / "live_switch_ws"
        new_dir.mkdir()
        client.post(
            "/api/v1/workspace/set_workspace_dir",
            json={"path": str(new_dir)},
        )
        assert Path(_shared.WORKSPACE_DIR).resolve() == new_dir.resolve()

    def test_persists_to_settings_json(self, _bundle, tmp_path):
        """set_workspace_dir must write the path to user_settings.json."""
        from pathlib import Path as _Path

        import web.shared as _shared

        client, _, _ = _bundle
        new_dir = tmp_path / "settings_json_ws"
        new_dir.mkdir()

        settings_path = _Path(_shared.get_user_settings_path())
        client.post(
            "/api/v1/workspace/set_workspace_dir",
            json={"path": str(new_dir)},
        )
        # The settings file should now contain the new path
        with open(settings_path, encoding="utf-8") as f:
            saved = json.load(f)
        assert saved.get("storage", {}).get("workspace_dir") == str(new_dir.resolve())


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /api/v1/workspace/rename — file branch (additional coverage)
# Uses its own fixture so set_workspace_dir tests don't pollute WORKSPACE_DIR.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def _rename_bundle(tmp_path_factory):
    """Isolated bundle exclusively for rename-file tests."""
    os.environ.setdefault("KOTO_AUTH_ENABLED", "false")

    tmp_root = tmp_path_factory.mktemp("rename_root")
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


@pytest.mark.integration
class TestRenameFileBranch:
    """Test the file-rename branch of rename_workspace_file."""

    def test_rename_file_preserves_extension(self, _rename_bundle):
        """Extension must stay the same even if user omits it."""
        client, _, workspace_dir = _rename_bundle
        src = workspace_dir / f"orig_{uuid.uuid4().hex[:6]}.docx"
        src.write_bytes(b"fake docx")
        resp = client.patch(
            "/api/v1/workspace/rename",
            json={
                "path": src.relative_to(workspace_dir).as_posix(),
                "name": "renamed_no_ext",
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        # Extension must still be .docx
        assert data["name"].endswith(".docx")

    def test_rename_file_returns_path_and_name(self, _rename_bundle):
        """Response must include 'path' and 'name' keys."""
        client, _, workspace_dir = _rename_bundle
        src = workspace_dir / f"rname_{uuid.uuid4().hex[:6]}.txt"
        src.write_text("hello")
        resp = client.patch(
            "/api/v1/workspace/rename",
            json={"path": src.relative_to(workspace_dir).as_posix(), "name": "newname"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "path" in data
        assert "name" in data

    def test_rename_file_missing_path_returns_400(self, _rename_bundle):
        client, _, _ = _rename_bundle
        resp = client.patch("/api/v1/workspace/rename", json={"name": "newname"})
        assert resp.status_code == 400

    def test_rename_file_missing_name_returns_400(self, _rename_bundle):
        client, _, workspace_dir = _rename_bundle
        src = workspace_dir / f"missname_{uuid.uuid4().hex[:6]}.txt"
        src.write_text("x")
        resp = client.patch(
            "/api/v1/workspace/rename",
            json={"path": src.relative_to(workspace_dir).as_posix()},
        )
        assert resp.status_code == 400

    def test_rename_file_traversal_rejected(self, _rename_bundle):
        client, _, _ = _rename_bundle
        resp = client.patch(
            "/api/v1/workspace/rename",
            json={"path": "../../etc/passwd", "name": "evil"},
        )
        assert resp.status_code == 403

    def test_rename_file_slash_in_name_rejected(self, _rename_bundle):
        client, _, workspace_dir = _rename_bundle
        src = workspace_dir / f"slashtest_{uuid.uuid4().hex[:6]}.txt"
        src.write_text("x")
        resp = client.patch(
            "/api/v1/workspace/rename",
            json={
                "path": src.relative_to(workspace_dir).as_posix(),
                "name": "sub/evil",
            },
        )
        assert resp.status_code == 400

    def test_rename_nonexistent_file_returns_404(self, _rename_bundle):
        client, _, _ = _rename_bundle
        resp = client.patch(
            "/api/v1/workspace/rename",
            json={"path": "ghost_xyz_doesnt_exist.txt", "name": "newname"},
        )
        assert resp.status_code == 404

    def test_rename_file_duplicate_returns_409(self, _rename_bundle):
        client, _, workspace_dir = _rename_bundle
        src = workspace_dir / f"dup_src_{uuid.uuid4().hex[:6]}.txt"
        dst = workspace_dir / f"dup_dst_{uuid.uuid4().hex[:6]}.txt"
        src.write_text("a")
        dst.write_text("b")
        resp = client.patch(
            "/api/v1/workspace/rename",
            json={
                "path": src.relative_to(workspace_dir).as_posix(),
                "name": dst.stem,  # same stem → same final_name (stem + .txt)
            },
        )
        assert resp.status_code == 409

    def test_rename_file_moves_on_disk(self, _rename_bundle):
        """After rename the old path should be gone and the new one should exist."""
        client, _, workspace_dir = _rename_bundle
        hex_id = uuid.uuid4().hex[:6]
        src = workspace_dir / f"disk_before_{hex_id}.txt"
        src.write_text("content")
        resp = client.patch(
            "/api/v1/workspace/rename",
            json={
                "path": src.relative_to(workspace_dir).as_posix(),
                "name": f"disk_after_{hex_id}",
            },
        )
        assert resp.status_code == 200
        new_name = resp.get_json()["name"]
        assert not src.exists()
        assert (workspace_dir / new_name).exists()

    def test_rename_file_empty_stem_rejected(self, _rename_bundle):
        """Passing a name that resolves to an empty stem (e.g. '.ext') returns 400."""
        client, _, workspace_dir = _rename_bundle
        src = workspace_dir / f"empty_stem_{uuid.uuid4().hex[:6]}.txt"
        src.write_text("x")
        resp = client.patch(
            "/api/v1/workspace/rename",
            json={"path": src.relative_to(workspace_dir).as_posix(), "name": "."},
        )
        # stem of "." is "" → 400
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/workspace/set_workspace_dir — additional edge cases
# Uses its own fixture to avoid polluting the module-scoped _bundle state.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def _ws_client(monkeypatch, tmp_path):
    """Function-scoped bundle for set_workspace_dir edge-case tests."""
    os.environ.setdefault("KOTO_AUTH_ENABLED", "false")

    tmp_dir = tmp_path / "tmp"
    workspace_dir = tmp_path / "workspace"
    settings_path = tmp_path / "user_settings.json"
    tmp_dir.mkdir(parents=True)
    workspace_dir.mkdir(parents=True)
    settings_path.write_text(
        json.dumps({"storage": {"workspace_dir": str(workspace_dir)}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("KOTO_USER_SETTINGS_PATH", str(settings_path))

    import web.blueprints.workspace_assistant as _wa
    import web.shared as _shared

    _orig_tmp = _wa._TMP_DIR
    _orig_ws = getattr(_shared, "WORKSPACE_DIR", None)
    _wa._TMP_DIR = tmp_dir
    _shared.clear_user_settings_cache()
    _shared.WORKSPACE_DIR = str(workspace_dir)

    from flask import Flask

    from web.blueprints.workspace_assistant import workspace_assistant_bp

    app = Flask(__name__)
    app.register_blueprint(workspace_assistant_bp)
    app.config["TESTING"] = True

    with app.test_client() as client:
        yield client, workspace_dir

    _wa._TMP_DIR = _orig_tmp
    _shared.clear_user_settings_cache()
    if _orig_ws is not None:
        _shared.WORKSPACE_DIR = _orig_ws


@pytest.mark.integration
class TestSetWorkspaceDirEdgeCases:
    """Additional edge cases for set_workspace_dir."""

    def test_nested_nonexistent_path_created(self, _ws_client):
        """A deeply nested non-existent path should be created."""
        client, workspace_dir = _ws_client
        deep = workspace_dir / "a" / "b" / "c" / "deep_ws"
        assert not deep.exists()
        resp = client.post(
            "/api/v1/workspace/set_workspace_dir",
            json={"path": str(deep)},
        )
        assert resp.status_code == 200
        assert deep.exists()

    def test_current_dir_reflects_set_workspace(self, _ws_client):
        """After set_workspace_dir, GET /current_dir should return the new path."""
        client, workspace_dir = _ws_client
        new_dir = workspace_dir / "cur_dir_ws"
        new_dir.mkdir()
        client.post(
            "/api/v1/workspace/set_workspace_dir",
            json={"path": str(new_dir)},
        )
        resp = client.get("/api/v1/workspace/current_dir")
        assert resp.status_code == 200
        data = resp.get_json()
        assert Path(data["path"]).resolve() == new_dir.resolve()
        assert data["name"] == new_dir.name
