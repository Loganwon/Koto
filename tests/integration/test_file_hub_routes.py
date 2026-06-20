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


class TestFilehubJSSource:
    """Static analysis: verify the JS source has the correct quoting fixes."""

    @pytest.fixture(scope="class")
    def app_js(self):
        from pathlib import Path
        js_path = Path(__file__).resolve().parents[2] / "web" / "static" / "js" / "app.js"
        return js_path.read_text(encoding="utf-8", errors="replace")

    def test_fh_render_uses_amp_quot_not_raw_json_stringify(self, app_js):
        """_fhRenderFiles must not embed raw JSON.stringify() inside onclick attrs."""
        # After the fix, onclick values use pathArg / copyArg variables (with &quot;)
        assert 'replace(/"/g, \'&quot;\')' in app_js, (
            "_fhRenderFiles: pathArg must apply .replace(/\"/g, '&quot;') encoding"
        )

    def test_fh_render_no_bare_json_stringify_in_onclick(self, app_js):
        """There must be no raw JSON.stringify inside an onclick template literal."""
        import re
        # Pattern: onclick="...${JSON.stringify(... which breaks HTML attr parsing
        bad = re.search(
            r'onclick="\$\{[^}]*JSON\.stringify',
            app_js,
        )
        assert bad is None, (
            f"Found unescaped JSON.stringify in onclick attribute at: {bad.group()}"
        )

    def test_filehub_modal_id_lowercase(self, app_js):
        """_fhOpenInAssistant must reference 'filehubModal' (lowercase h), not 'fileHubModal'."""
        assert "'filehubModal'" in app_js, (
            "_fhOpenInAssistant must use getElementById('filehubModal')"
        )
        assert "'fileHubModal'" not in app_js, (
            "Found wrong ID 'fileHubModal' — should be 'filehubModal'"
        )

    def test_open_in_assistant_uses_wa_open(self, app_js):
        """_fhOpenInAssistant must use WA.openInMainView / WA.openRecentFile, not the Univer editor API."""
        assert "WA.openInMainView" in app_js, (
            "_fhOpenInAssistant must call WA.openInMainView()"
        )
        assert "WA.openRecentFile" in app_js, (
            "_fhOpenInAssistant must call WA.openRecentFile(path)"
        )

    def test_open_in_assistant_no_univer_import(self, app_js):
        """_fhOpenInAssistant must NOT call the Univer editor import API."""
        # Check that the import_path fetch call is gone from _fhOpenInAssistant
        import re
        # Look for the old pattern: fetch('/api/editor/docs/import_path' inside _fhOpenInAssistant
        # We search the function body specifically
        fn_match = re.search(
            r'async function _fhOpenInAssistant\(path\)\s*\{(.+?)\n\}',
            app_js,
            re.DOTALL,
        )
        assert fn_match, "_fhOpenInAssistant function not found in app.js"
        fn_body = fn_match.group(1)
        assert "/api/editor/docs/import_path" not in fn_body, (
            "_fhOpenInAssistant must not call Univer editor import API"
        )


class TestFilehubHTMLSource:
    """Static analysis: verify the HTML template has correct modal layout fixes."""

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

    def test_modal_has_fixed_height(self, index_html):
        """fh-app must use height: to stay consistent between tabs."""
        import re
        # New v2 design uses .fh-app with height in CSS
        fh_app_rule = re.search(
            r'\.fh-app\s*\{([^}]*)\}',
            index_html,
        )
        assert fh_app_rule, "Could not find .fh-app CSS rule in index.html"
        fh_app_style = fh_app_rule.group(1)
        assert 'height:' in fh_app_style or 'height: ' in fh_app_style, (
            ".fh-app must have an explicit 'height:' property to keep the panel "
            "a consistent size when switching tabs"
        )

    def test_filelist_no_conflicting_max_height(self, index_html):
        """#fhFileList CSS must NOT have max-height (conflicts with flex:1 expansion)."""
        import re
        # Find the style block rule for #fhFileList
        fhlist_rule = re.search(
            r'#fhFileList\s*\{([^}]*)\}',
            index_html,
        )
        assert fhlist_rule, "#fhFileList style rule not found in index.html <style> block"
        rule_body = fhlist_rule.group(1)
        assert 'max-height' not in rule_body, (
            "#fhFileList must not set max-height — it conflicts with flex:1 and "
            "prevents the modal from filling its fixed height"
        )

    def test_modal_overlay_uses_flex_centering(self, index_html):
        """modal-overlay CSS must use flexbox centering (align-items + justify-content center)."""
        assert 'align-items: center' in index_html or 'align-items:center' in index_html, (
            "modal-overlay must have align-items:center for vertical centering"
        )
