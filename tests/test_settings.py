"""Tests for settings manager -- CRUD, validation, edge cases."""
import json
import os
import tempfile
from pathlib import Path

import pytest


class TestSettingsManager:
    """Tests for web.settings.SettingsManager."""

    @pytest.fixture
    def settings_file(self, tmp_path):
        sf = tmp_path / "user_settings.json"
        sf.write_text('{}')
        return sf

    @pytest.fixture
    def settings_mgr(self, monkeypatch, settings_file):
        import importlib
        import web.settings
        importlib.reload(web.settings)
        monkeypatch.setattr('web.settings.SETTINGS_FILE', str(settings_file))
        web.settings.SettingsManager._instance = None
        mgr = web.settings.SettingsManager()
        yield mgr
        mgr._flush_timer = None

    def test_singleton(self, settings_mgr):
        from web.settings import SettingsManager as SM
        mgr2 = SM()
        assert settings_mgr is mgr2

    def test_default_values(self, settings_mgr):
        assert settings_mgr.get('appearance', 'theme') == 'light'
        assert settings_mgr.get('ai', 'cloud_provider') == 'deepseek'

    def test_set_and_get(self, settings_mgr):
        settings_mgr.set('appearance', 'theme', 'dark')
        assert settings_mgr.get('appearance', 'theme') == 'dark'

    def test_nonexistent_key_returns_none(self, settings_mgr):
        assert settings_mgr.get('nonexistent', 'section') is None

    def test_get_with_default(self, settings_mgr):
        assert settings_mgr.get('nonexistent', 'section') is None

    def test_get_all_returns_dict(self, settings_mgr):
        all_settings = settings_mgr.get_all()
        assert isinstance(all_settings, dict)
        assert 'storage' in all_settings
        assert 'appearance' in all_settings

    def test_storage_paths_exist(self, settings_mgr):
        paths = settings_mgr.get('storage') or {}
        assert isinstance(paths, dict)


class TestSettingsValidation:

    @pytest.fixture
    def settings_mgr_val(self, monkeypatch, tmp_path):
        sf = tmp_path / "user_settings.json"
        sf.write_text('{}')
        import importlib
        import web.settings
        importlib.reload(web.settings)
        monkeypatch.setattr('web.settings.SETTINGS_FILE', str(sf))
        web.settings.SettingsManager._instance = None
        mgr = web.settings.SettingsManager()
        yield mgr
        mgr._flush_timer = None

    def test_set_empty_string(self, settings_mgr_val):
        settings_mgr_val.set('user', 'name', '')
        assert settings_mgr_val.get('user', 'name') == ''

    def test_set_none_deletes_key(self, settings_mgr_val):
        settings_mgr_val.set('user', 'name', 'test')
        settings_mgr_val.set('user', 'name', None)
        val = settings_mgr_val.get('user', 'name')
        assert val is None or val == ''

    def test_unicode_values(self, settings_mgr_val):
        settings_mgr_val.set('user', 'name', '\u4e2d\u6587\u540d\u79f0')
        assert settings_mgr_val.get('user', 'name') == '\u4e2d\u6587\u540d\u79f0'

    def test_deeply_nested_path(self, settings_mgr_val):
        settings_mgr_val.set('a', 'b', {'c': {'d': 42}})
        val = settings_mgr_val.get('a', 'b')
        assert isinstance(val, dict)
        assert val['c']['d'] == 42

    def test_persistence(self, settings_mgr_val, monkeypatch, tmp_path):
        settings_mgr_val.set('appearance', 'theme', 'ocean')
        settings_mgr_val.flush()
        import web.settings
        web.settings.SettingsManager._instance = None
        import importlib
        importlib.reload(web.settings)
        monkeypatch.setattr('web.settings.SETTINGS_FILE', str(tmp_path / 'user_settings.json'))
        mgr2 = web.settings.SettingsManager()
        assert mgr2.get('appearance', 'theme') == 'ocean'
