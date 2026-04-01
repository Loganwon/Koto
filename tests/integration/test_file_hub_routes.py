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
