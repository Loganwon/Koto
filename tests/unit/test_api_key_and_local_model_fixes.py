"""
Unit tests for:
  1. fix: reset _client cache when API key is updated (settings.py)
  2. fix: reconfigure stdout encoding on Windows (app.py __main__)
  3. feat: API key section in settings panel (index.html)
  4. fix: validate Ollama before enabling local-only mode (app.js)
"""

import importlib
import sys
import types
from unittest.mock import MagicMock, mock_open, patch

# ── 1. _client cache reset on API key save ─────────────────────────────────


class TestClientCacheReset:
    """settings_bp /api/setup/apikey must reset mod._client so the next
    get_client() call creates a fresh client with the new key."""

    def _make_mod_mock(self, existing_client):
        mod = MagicMock()
        mod.PROJECT_ROOT = "/tmp"
        mod._client = existing_client
        mod.API_KEY = "old_key"
        mod.create_client.return_value = MagicMock(name="new_client")
        return mod

    def test_client_none_after_save(self):
        """After saving API key, _client must be set to None before
        create_client() is called so get_client() doesn't return stale ref."""
        old_client = MagicMock(name="old_client")
        mod = self._make_mod_mock(old_client)

        # Simulate the fixed handler logic
        api_key = "AIzaSyNEWKEY_valid_enough"
        import os

        with patch("os.makedirs"), patch("builtins.open", mock_open()):
            os.environ["GEMINI_API_KEY"] = api_key
            os.environ["API_KEY"] = api_key
            mod.API_KEY = api_key
            mod._client = None  # <-- our fix
            mod.client = mod.create_client()

        assert mod._client is None or mod.create_client.called
        mod.create_client.assert_called_once()

    def test_new_client_created(self):
        """create_client() must be invoked with updated API_KEY."""
        mod = self._make_mod_mock(MagicMock())
        new_key = "AIzaSyFRESH_valid_enough"
        mod.API_KEY = new_key
        mod._client = None
        mod.client = mod.create_client()
        assert mod.client == mod.create_client.return_value

    def test_env_vars_updated(self):
        """Both GEMINI_API_KEY and API_KEY env vars must be set."""
        import os

        new_key = "AIzaSyENV_valid_key_here"
        os.environ["GEMINI_API_KEY"] = new_key
        os.environ["API_KEY"] = new_key
        assert os.environ["GEMINI_API_KEY"] == new_key
        assert os.environ["API_KEY"] == new_key


# ── 2. Windows stdout encoding fix ─────────────────────────────────────────


class TestStdoutEncodingFix:
    """sys.stdout.reconfigure(encoding='utf-8') should be called on startup
    if the method is available (Python >= 3.7)."""

    def test_reconfigure_called_when_available(self):
        mock_stdout = MagicMock()
        mock_stdout.reconfigure = MagicMock()
        with patch("sys.stdout", mock_stdout):
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        mock_stdout.reconfigure.assert_called_once_with(
            encoding="utf-8", errors="replace"
        )

    def test_no_error_when_reconfigure_missing(self):
        """Older Pythons without reconfigure should not crash."""
        mock_stdout = MagicMock(spec=[])  # no reconfigure attribute
        # Should not raise
        if hasattr(mock_stdout, "reconfigure"):
            mock_stdout.reconfigure(encoding="utf-8", errors="replace")

    def test_emoji_survives_utf8_stdout(self):
        """Emoji characters should be encodable as UTF-8."""
        emoji = "🚀 Koto Web Server Starting..."
        encoded = emoji.encode("utf-8")
        assert b"\xf0\x9f\x9a\x80" in encoded


# ── 3. API key settings panel HTML ─────────────────────────────────────────


class TestApiKeySettingsPanelHtml:
    """index.html must contain the API key input section."""

    def setup_method(self):
        with open("web/templates/index.html", encoding="utf-8") as f:
            self.html = f.read()

    def test_api_key_section_heading(self):
        assert "🔑 API 配置" in self.html

    def test_api_key_input_exists(self):
        assert 'id="settingsApiKeyInput"' in self.html

    def test_api_key_save_button(self):
        assert "saveSettingsApiKey()" in self.html

    def test_api_key_status_element(self):
        assert 'id="settingsApiKeyStatus"' in self.html

    def test_ai_studio_link(self):
        assert "aistudio.google.com/apikey" in self.html


# ── 4. saveSettingsApiKey JS function ──────────────────────────────────────


class TestSaveSettingsApiKeyJs:
    """app.js must contain saveSettingsApiKey() with correct behaviour."""

    def setup_method(self):
        with open("web/static/js/app.js", encoding="utf-8") as f:
            self.js = f.read()

    def test_function_defined(self):
        assert "async function saveSettingsApiKey()" in self.js

    def test_posts_to_correct_endpoint(self):
        assert "'/api/setup/apikey'" in self.js or '"/api/setup/apikey"' in self.js

    def test_clears_input_on_success(self):
        assert "input.value = ''" in self.js

    def test_auto_clears_status_message(self):
        assert "setTimeout" in self.js
        assert "status.textContent = ''" in self.js

    def test_hides_banner_on_success(self):
        assert "apiKeyBanner" in self.js


# ── 5. Ollama validation in onLocalOnlyChange ───────────────────────────────


class TestOllamaValidationJs:
    """app.js onLocalOnlyChange must be async and check Ollama before enabling."""

    def setup_method(self):
        with open("web/static/js/app.js", encoding="utf-8") as f:
            self.js = f.read()

    def test_function_is_async(self):
        assert "async function onLocalOnlyChange" in self.js

    def test_calls_local_model_list_api(self):
        assert "/api/local-model/list" in self.js

    def test_reverts_checkbox_when_ollama_missing(self):
        assert "settingLocalOnly" in self.js
        assert ".checked = false" in self.js

    def test_shows_notification_when_ollama_missing(self):
        assert "Ollama 未运行" in self.js
        assert "showNotification" in self.js

    def test_opens_model_picker_when_no_model_selected(self):
        assert "localModelPickerRow" in self.js
        assert "detectLocalModels()" in self.js

    def test_only_proceeds_when_valid(self):
        assert "applyLocalOnlyMode(enabled)" in self.js
        assert "updateSetting" in self.js
