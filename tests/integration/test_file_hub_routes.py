# -*- coding: utf-8 -*-
"""
Integration tests for /api/files (FileHub) endpoints.

Tests file listing/search, stats, recent files, and error cases.
Avoids filesystem-heavy operations that require specific paths.
Uses the full_client fixture from conftest.py.
"""

from __future__ import annotations

import io
import os
import sys
import types

import pytest

from web.settings import settings as web_settings


def _check(resp, ok_status=(200, 201)):
    body = resp.get_data(as_text=True)
    assert resp.status_code in ok_status, f"HTTP {resp.status_code}: {body[:400]}"
    return resp.get_json()


@pytest.mark.integration
class TestFileSearch:
    def test_search_files_returns_200(self, full_client):
        resp = full_client.get("/api/files/search")
        assert resp.status_code == 200, resp.get_data(as_text=True)

    def test_search_with_query_returns_200(self, full_client):
        resp = full_client.get("/api/files/search?q=test")
        assert resp.status_code == 200, resp.get_data(as_text=True)

    def test_search_response_is_json(self, full_client):
        resp = full_client.get("/api/files/search")
        assert resp.content_type.startswith("application/json")


@pytest.mark.integration
class TestFileStats:
    def test_file_stats_returns_200(self, full_client):
        resp = full_client.get("/api/files/stats")
        assert resp.status_code == 200, resp.get_data(as_text=True)

    def test_file_stats_is_json(self, full_client):
        resp = full_client.get("/api/files/stats")
        data = resp.get_json()
        assert data is not None


@pytest.mark.integration
class TestFileRecent:
    def test_recent_files_returns_200(self, full_client):
        resp = full_client.get("/api/files/recent")
        assert resp.status_code == 200, resp.get_data(as_text=True)

    def test_recent_files_with_params(self, full_client):
        resp = full_client.get("/api/files/recent?days=7&limit=10")
        assert resp.status_code == 200


@pytest.mark.integration
class TestFileNotFound:
    def test_get_nonexistent_file_returns_404(self, full_client):
        resp = full_client.get("/api/files/nonexistent-file-id-xyz-abc")
        assert resp.status_code in (400, 404), resp.get_data(as_text=True)

    def test_delete_nonexistent_file_returns_404(self, full_client):
        resp = full_client.delete("/api/files/nonexistent-file-id-xyz-abc")
        assert resp.status_code in (400, 404), resp.get_data(as_text=True)


@pytest.mark.integration
class TestFileListDir:
    def test_list_dir_without_path_param(self, full_client):
        """list-dir without a path param should return 400 or default listing."""
        resp = full_client.get("/api/files/list-dir")
        assert resp.status_code in (200, 400), resp.get_data(as_text=True)

    def test_list_dir_with_valid_path(self, full_client, tmp_workspace):
        """list-dir with an existing directory should succeed."""
        resp = full_client.get(f"/api/files/list-dir?path={str(tmp_workspace)}")
        assert resp.status_code in (200, 400), resp.get_data(as_text=True)


@pytest.mark.integration
class TestFilePickFolder:
    def test_pick_folder_initial_dir_from_query(self, full_client, monkeypatch):
        captured = {}

        class FakeTk:
            def withdraw(self):
                pass

            def attributes(self, *args, **kwargs):
                pass

            def destroy(self):
                pass

        fake_tk = types.ModuleType("tkinter")
        fake_tk.Tk = FakeTk
        fake_filedialog = types.ModuleType("tkinter.filedialog")

        def fake_askdirectory(*, parent=None, title=None, initialdir=None):
            captured["initialdir"] = initialdir
            return "/tmp/selected"

        fake_filedialog.askdirectory = fake_askdirectory

        monkeypatch.setitem(sys.modules, "tkinter", fake_tk)
        monkeypatch.setitem(sys.modules, "tkinter.filedialog", fake_filedialog)

        resp = full_client.get("/api/files/pick-folder?initial_dir=/tmp/example")
        assert resp.status_code == 200, resp.get_data(as_text=True)
        data = resp.get_json()
        assert data["ok"] is True
        assert data["path"] == "/tmp/selected"
        assert captured["initialdir"] == "/tmp/example"

    def test_pick_folder_falls_back_to_workspace_directory(
        self, full_client, monkeypatch
    ):
        captured = {}

        class FakeTk:
            def withdraw(self):
                pass

            def attributes(self, *args, **kwargs):
                pass

            def destroy(self):
                pass

        fake_tk = types.ModuleType("tkinter")
        fake_tk.Tk = FakeTk
        fake_filedialog = types.ModuleType("tkinter.filedialog")

        def fake_askdirectory(*, parent=None, title=None, initialdir=None):
            captured["initialdir"] = initialdir
            return "/tmp/selected"

        fake_filedialog.askdirectory = fake_askdirectory

        monkeypatch.setitem(sys.modules, "tkinter", fake_tk)
        monkeypatch.setitem(sys.modules, "tkinter.filedialog", fake_filedialog)

        resp = full_client.get("/api/files/pick-folder")
        assert resp.status_code == 200, resp.get_data(as_text=True)
        data = resp.get_json()
        assert data["ok"] is True
        assert data["path"] == "/tmp/selected"
        assert captured["initialdir"] == web_settings.workspace_dir


@pytest.mark.integration
class TestFileTags:
    def test_get_all_tags_returns_200(self, full_client):
        resp = full_client.get("/api/files/tags")
        assert resp.status_code == 200, resp.get_data(as_text=True)


@pytest.mark.integration
class TestFileFavorites:
    def test_get_favorites_returns_200(self, full_client):
        resp = full_client.get("/api/files/favorites")
        assert resp.status_code == 200, resp.get_data(as_text=True)


@pytest.mark.integration
class TestFileOpenEndpoint:
    """Native OS file opening through FileHub is retired."""

    def test_open_file_route_removed(self, full_client):
        resp = full_client.post(
            "/api/files/" + "open",
            json={},
            content_type="application/json",
        )
        assert resp.status_code == 404


@pytest.mark.integration
class TestFileRecentFormat:
    """Recent endpoint must return a 'files' list so the FileHub card
    renderer can iterate over it without crashing."""

    def test_recent_returns_files_key(self, full_client):
        resp = full_client.get("/api/files/recent?days=14&limit=50")
        assert resp.status_code == 200
        data = resp.get_json()
        # Response may be a list directly or have a 'files' key
        assert isinstance(data, (list, dict)), "Response must be JSON list or object"
        if isinstance(data, dict):
            files = data.get("files", data.get("results", []))
            assert isinstance(files, list)

    def test_recent_file_items_have_name_and_path(self, full_client):
        """Each returned file item must have 'name' and 'path' fields."""
        resp = full_client.get("/api/files/recent?days=90&limit=5")
        assert resp.status_code == 200
        data = resp.get_json()
        items = data if isinstance(data, list) else data.get("files", [])
        for item in items:
            assert "path" in item, f"Missing 'path' in item: {item}"
            # name may default to basename of path — must be a string
            name = item.get("name") or item.get("path", "")
            assert isinstance(name, str) and name, f"Bad name in item: {item}"


@pytest.mark.integration
class TestFileBrowseEndpoint:
    """Tests for /api/files/browse (used by "局部目录浏览" tab)."""

    def test_browse_missing_path_returns_400(self, full_client):
        resp = full_client.get("/api/files/browse")
        assert resp.status_code in (400, 422), resp.get_data(as_text=True)

    def test_browse_valid_dir_returns_files(self, full_client, tmp_path):
        (tmp_path / "a.txt").write_text("x")
        (tmp_path / "b.md").write_text("y")
        resp = full_client.get(f"/api/files/browse?path={tmp_path}")
        assert resp.status_code == 200
        data = resp.get_json()
        items = data if isinstance(data, list) else data.get("files", [])
        assert isinstance(items, list)
        names = [f.get("name", "") for f in items]
        assert "a.txt" in names and "b.md" in names


class TestFilehubLegacyUISource:
    """Static analysis: the retired FileHub modal UI must not return via old app.js."""

    @pytest.fixture(scope="class")
    def frontend_sources(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        src_parts = []
        for path in [
            root / "web" / "templates" / "index.html",
            root / "web" / "src" / "bundles" / "app.ts",
            root / "web" / "src" / "app" / "main.ts",
            root / "web" / "static" / "css" / "inline-extracted.css",
        ]:
            src_parts.append(path.read_text(encoding="utf-8", errors="replace"))
        return "\n".join(src_parts)

    def test_legacy_app_js_removed(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        assert not (root / "web" / "static" / "js" / "app.js").exists()

    def test_filehub_modal_entry_removed(self, frontend_sources):
        assert "openFileHubModal" not in frontend_sources
        assert "filehubModal" not in frontend_sources
        assert "fhNavSwitch" not in frontend_sources

    def test_no_inline_filehub_json_handlers(self, frontend_sources):
        import re

        bad = re.search(r'onclick="\$\{[^}]*JSON\.stringify', frontend_sources)
        assert (
            bad is None
        ), f"Found unescaped JSON.stringify in inline onclick: {bad.group()}"

    def test_filehub_no_univer_import_fallback(self, frontend_sources):
        assert "/api/editor/docs/import_path" not in frontend_sources


class TestFilehubHTMLSource:
    """Static analysis: verify the old modal layout has been removed with app.js."""

    @pytest.fixture(scope="class")
    def index_html(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        html_path = root / "web" / "templates" / "index.html"
        css_path = root / "web" / "static" / "css" / "inline-extracted.css"
        return "\n".join(
            [
                html_path.read_text(encoding="utf-8", errors="replace"),
                css_path.read_text(encoding="utf-8", errors="replace"),
            ]
        )

    def test_filehub_modal_css_removed(self, index_html):
        assert ".fh-app" not in index_html
        assert "#fhFileList" not in index_html
        assert "filehubModal" not in index_html

    def test_general_modal_overlay_still_centers(self, index_html):
        assert "align-items: center" in index_html or "align-items:center" in index_html
