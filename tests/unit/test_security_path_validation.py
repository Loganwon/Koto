# -*- coding: utf-8 -*-
"""
Unit tests for path-traversal prevention and input-validation sandboxes
across the Koto codebase.

Covers file conversion output roots, URL scheme validation, and skill entry-point
module allowlists.

All tests are isolated: file-system and network operations are mocked so
nothing touches the real disk or opens a real browser.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# 2. file_converter.convert()  —  _allowed_roots sandbox for output_dir
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFileConverterOutputDirSandbox:
    """convert() must confine output_dir to workspace/uploads/dist."""

    def _call_convert(self, source_path, target_format, output_dir=None):
        """Import and call convert() with os.path.exists mocked for source."""
        from app.core.file.exporters.converter import convert

        return convert(
            source_path=source_path,
            target_format=target_format,
            output_dir=output_dir,
        )

    # -- output_dir outside allowed roots --------------------------------------

    def test_output_dir_outside_allowed_roots_blocked(self):
        """output_dir pointing to /tmp or C:\\Temp should be blocked."""
        outside_dir = os.path.abspath(os.sep + "tmp" + os.sep + "evil")
        source = os.path.join(os.path.abspath("workspace"), "file.docx")

        with patch("os.path.exists", return_value=True):
            result = self._call_convert(source, "pdf", output_dir=outside_dir)
        assert result.get("success") is not True or "不在允许的范围内" in result.get(
            "error", ""
        ), "output_dir outside allowed roots should be rejected"

    def test_output_dir_traversal_blocked(self):
        """output_dir using ../ to escape allowed roots should be blocked."""
        traversal_dir = os.path.join(os.path.abspath("workspace"), "..", "..", "tmp")
        source = os.path.join(os.path.abspath("workspace"), "file.docx")

        with patch("os.path.exists", return_value=True):
            result = self._call_convert(source, "pdf", output_dir=traversal_dir)
        # After abspath normalisation the traversal should resolve outside roots
        if os.path.abspath(traversal_dir) != os.path.abspath(os.path.dirname(source)):
            assert (
                result.get("success") is not True
            ), "Path-traversal output_dir should be blocked"

    # -- output_dir inside allowed roots ---------------------------------------

    def test_output_dir_workspace_accepted(self):
        """output_dir under workspace/ should be accepted."""
        workspace_out = os.path.abspath("workspace")
        source = os.path.join(workspace_out, "file.docx")

        with patch("os.path.exists", return_value=True), patch("os.makedirs"), patch(
            "app.core.file.exporters.converter._dispatch"
        ) as mock_dispatch:
            mock_dispatch.return_value = (os.path.join(workspace_out, "file.pdf"), "")
            result = self._call_convert(source, "pdf", output_dir=workspace_out)
        assert (
            result["success"] is True
        ), "output_dir inside workspace should be allowed"

    def test_output_dir_uploads_accepted(self):
        """output_dir under uploads/ should be accepted."""
        uploads_out = os.path.abspath("uploads")
        source = os.path.join(os.path.abspath("workspace"), "file.docx")

        with patch("os.path.exists", return_value=True), patch("os.makedirs"), patch(
            "app.core.file.exporters.converter._dispatch"
        ) as mock_dispatch:
            mock_dispatch.return_value = (os.path.join(uploads_out, "file.pdf"), "")
            result = self._call_convert(source, "pdf", output_dir=uploads_out)
        assert result["success"] is True

    def test_output_dir_dist_accepted(self):
        """output_dir under dist/ should be accepted."""
        dist_out = os.path.abspath("dist")
        source = os.path.join(os.path.abspath("workspace"), "file.docx")

        with patch("os.path.exists", return_value=True), patch("os.makedirs"), patch(
            "app.core.file.exporters.converter._dispatch"
        ) as mock_dispatch:
            mock_dispatch.return_value = (os.path.join(dist_out, "file.pdf"), "")
            result = self._call_convert(source, "pdf", output_dir=dist_out)
        assert result["success"] is True

    # -- fallback: same-directory as source ------------------------------------

    def test_output_dir_same_as_source_parent_allowed(self):
        """When output_dir equals the source file's parent, it's allowed
        even outside the standard roots (fallback logic)."""
        # Create a path that's outside workspace/uploads/dist
        source_parent = os.path.abspath(os.sep + "some" + os.sep + "project")
        source = os.path.join(source_parent, "file.docx")

        with patch("os.path.exists", return_value=True), patch("os.makedirs"), patch(
            "app.core.file.exporters.converter._dispatch"
        ) as mock_dispatch:
            mock_dispatch.return_value = (os.path.join(source_parent, "file.pdf"), "")
            result = self._call_convert(source, "pdf", output_dir=source_parent)
        assert (
            result["success"] is True
        ), "Same-directory-as-source fallback should be allowed"


# ---------------------------------------------------------------------------
# 3. WindowAPI.open_url()  —  URL scheme whitelist
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOpenUrlSchemeValidation:
    """WindowAPI.open_url() must only allow http: and https: schemes."""

    def _make_api(self):
        from src.koto_app import WindowAPI

        window_mock = MagicMock()
        return WindowAPI(window=window_mock, base_url="http://127.0.0.1:5000")

    # -- blocked schemes -------------------------------------------------------

    def test_javascript_scheme_blocked(self):
        api = self._make_api()
        result = api.open_url("javascript:alert(1)")
        assert result["success"] is False, "javascript: scheme must be blocked"

    def test_file_scheme_blocked(self):
        api = self._make_api()
        result = api.open_url("file:///etc/passwd")
        assert result["success"] is False, "file: scheme must be blocked"

    def test_data_scheme_blocked(self):
        api = self._make_api()
        result = api.open_url("data:text/html,<script>alert(1)</script>")
        assert result["success"] is False, "data: scheme must be blocked"

    def test_ftp_scheme_blocked(self):
        api = self._make_api()
        result = api.open_url("ftp://evil.com/malware")
        assert result["success"] is False, "ftp: scheme must be blocked"

    def test_vbscript_scheme_blocked(self):
        api = self._make_api()
        result = api.open_url("vbscript:MsgBox(1)")
        assert result["success"] is False, "vbscript: scheme must be blocked"

    # -- allowed schemes -------------------------------------------------------

    def test_http_scheme_allowed(self):
        api = self._make_api()
        with patch("webbrowser.open") as mock_open:
            result = api.open_url("http://example.com")
        assert result["success"] is True, "http: scheme should be allowed"
        mock_open.assert_called_once_with("http://example.com")

    def test_https_scheme_allowed(self):
        api = self._make_api()
        with patch("webbrowser.open") as mock_open:
            result = api.open_url("https://example.com/page?q=1")
        assert result["success"] is True, "https: scheme should be allowed"
        mock_open.assert_called_once_with("https://example.com/page?q=1")

    # -- edge cases ------------------------------------------------------------

    def test_empty_url_handled_gracefully(self):
        """Empty string URL should not crash; parsed scheme is empty → blocked."""
        api = self._make_api()
        result = api.open_url("")
        assert result["success"] is False

    def test_scheme_only_no_netloc(self):
        """A bare 'http:' with no netloc is not a valid URL and should be rejected."""
        api = self._make_api()
        result = api.open_url("http:")
        # Implementation requires full 'http://' or 'https://' prefix
        assert result["success"] is False
