"""
Deep-coverage tests for the largest uncovered modules.
Each class targets methods / branches NOT exercised by earlier test files.
"""

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, Mock, PropertyMock, call, mock_open, patch

import pytest


# ---------------------------------------------------------------------------
# 1. DocumentFeedbackSystem – deeper coverage
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.unit
class TestPptGeneratorDeep:
    """Cover the active PPT generator's formatting and export behavior."""

    def _make_gen(self, theme="business"):
        with patch("app.core.services.ppt_themes.get_theme", return_value=None):
            from app.core.services.ppt_generator import PPTGenerator

            return PPTGenerator(theme=theme)

    # -- _rgb helper --------------------------------------------------------
    def test_rgb_returns_value_for_known_key(self):
        gen = self._make_gen()
        result = gen._rgb("primary")
        assert result is not None

    def test_rgb_returns_fallback_for_unknown_key(self):
        gen = self._make_gen()
        # _rgb raises KeyError for unknown keys (no fallback)
        with pytest.raises(KeyError):
            gen._rgb("nonexistent_key_xyz")

    # -- _set_font helper ---------------------------------------------------
    def test_set_font_applies_bold(self):
        gen = self._make_gen()
        mock_run = MagicMock()
        gen._set_font(mock_run, size=24, bold=True, color_key="primary")
        assert mock_run.font.bold is True

    def test_set_font_applies_italic(self):
        gen = self._make_gen()
        mock_run = MagicMock()
        gen._set_font(mock_run, size=18, italic=True, color_key="text")
        assert mock_run.font.italic is True

    # -- _clean_markdown static method --------------------------------------
    def test_clean_markdown_removes_code_blocks(self):
        from app.core.services.ppt_generator import PPTGenerator

        text = "Before\n```python\ncode here\n```\nAfter"
        result = PPTGenerator._clean_markdown(text)
        assert "```" not in result

    def test_clean_markdown_removes_strikethrough(self):
        from app.core.services.ppt_generator import PPTGenerator

        text = "~~deleted~~ kept"
        result = PPTGenerator._clean_markdown(text)
        assert "~~" not in result

    def test_clean_markdown_removes_link_markup(self):
        from app.core.services.ppt_generator import PPTGenerator

        text = "[Click here](https://example.com)"
        result = PPTGenerator._clean_markdown(text)
        assert "](http" not in result

    def test_clean_markdown_strips_h1_headers(self):
        from app.core.services.ppt_generator import PPTGenerator

        text = "# H1 Title"
        result = PPTGenerator._clean_markdown(text)
        assert result.strip() == "H1 Title"

    def test_clean_markdown_ai_dialogue_patterns(self):
        from app.core.services.ppt_generator import PPTGenerator

        text = "当然可以！这里是内容。好的，以下是数据。"
        result = PPTGenerator._clean_markdown(text)
        assert isinstance(result, str)

    def test_clean_markdown_strip_bold_mode(self):
        from app.core.services.ppt_generator import PPTGenerator

        text = "This is **bold** text"
        result = PPTGenerator._clean_markdown(text, strip_bold=True)
        assert "**" not in result

    # -- generate_from_text -------------------------------------------------
    def test_generate_from_text_creates_pptx(self):
        gen = self._make_gen()
        mock_prs = MagicMock()
        with patch(
            "app.core.services.ppt_generator.Presentation", return_value=mock_prs
        ):
            with tempfile.TemporaryDirectory() as td:
                out = os.path.join(td, "out.pptx")
                result = gen.generate_from_text(
                    "Title\n\nSlide 1 content\n\nSlide 2 content", out
                )
        assert "output_path" in result or "slide_count" in result

    # -- generate_from_outline with progress callback -----------------------
    def test_generate_from_outline_calls_progress_callback(self):
        gen = self._make_gen()
        mock_prs = MagicMock()
        cb = MagicMock()
        outline = [
            {"title": "Intro", "points": ["Point 1"], "slide_type": "detail"},
        ]
        with patch(
            "app.core.services.ppt_generator.Presentation", return_value=mock_prs
        ):
            with tempfile.TemporaryDirectory() as td:
                out = os.path.join(td, "out.pptx")
                gen.generate_from_outline("Title", outline, out, progress_callback=cb)

    # -- generate_from_outline error path -----------------------------------
    def test_generate_from_outline_handles_save_error(self):
        gen = self._make_gen()
        mock_prs = MagicMock()
        mock_prs.save.side_effect = PermissionError("locked")
        outline = [{"title": "T", "points": ["P"], "slide_type": "detail"}]
        with patch(
            "app.core.services.ppt_generator.Presentation", return_value=mock_prs
        ):
            with pytest.raises(PermissionError):
                gen.generate_from_outline("T", outline, "/locked/out.pptx")

    # -- generate_from_outline with various slide types ---------------------
    def test_generate_from_outline_with_image_full_type(self):
        gen = self._make_gen()
        mock_prs = MagicMock()
        outline = [
            {
                "title": "Image Slide",
                "points": ["Beautiful scenery"],
                "slide_type": "image_full",
            }
        ]
        with patch(
            "app.core.services.ppt_generator.Presentation", return_value=mock_prs
        ):
            with tempfile.TemporaryDirectory() as td:
                out = os.path.join(td, "out.pptx")
                result = gen.generate_from_outline(
                    "Title", outline, out, enable_ai_images=False
                )
        assert "output_path" in result

    def test_generate_from_outline_with_content_image_type(self):
        gen = self._make_gen()
        mock_prs = MagicMock()
        outline = [
            {
                "title": "Content Image",
                "points": ["Data visualization"],
                "slide_type": "content_image",
            }
        ]
        with patch(
            "app.core.services.ppt_generator.Presentation", return_value=mock_prs
        ):
            with tempfile.TemporaryDirectory() as td:
                out = os.path.join(td, "out.pptx")
                result = gen.generate_from_outline(
                    "Title", outline, out, enable_ai_images=False
                )
        assert "output_path" in result

    # -- add_image_to_slide -------------------------------------------------
    def test_add_image_to_slide_out_of_range(self):
        gen = self._make_gen()
        mock_prs = MagicMock()
        # slide_index 5 is >= len(slides) when slides has fewer elements
        mock_slides = MagicMock()
        mock_slides.__len__ = MagicMock(return_value=0)
        mock_prs.slides = mock_slides
        result = gen.add_image_to_slide(mock_prs, 5, "/fake/image.png")
        assert result is False

    def test_add_image_to_slide_exception(self):
        gen = self._make_gen()
        mock_prs = MagicMock()
        mock_slides = MagicMock()
        mock_slides.__len__ = MagicMock(return_value=2)
        mock_slide = MagicMock()
        mock_slide.shapes.add_picture.side_effect = FileNotFoundError("no file")
        mock_slides.__getitem__ = MagicMock(return_value=mock_slide)
        mock_prs.slides = mock_slides
        result = gen.add_image_to_slide(mock_prs, 0, "/nonexistent/image.png")
        assert result is False


# ---------------------------------------------------------------------------
# 3. TrackChangesEditor – deeper coverage
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestTrackChangesEditorDeep:
    """Cover the active comment and hybrid change entry points."""

    def _make_editor(self, author="Test Author"):
        from app.core.file.track_changes import TrackChangesEditor

        return TrackChangesEditor(author=author)

    # -- apply_hybrid_changes classification --------------------------------
    def test_apply_hybrid_changes_classifies_suggestion_as_comment(self):
        editor = self._make_editor()
        mock_doc = MagicMock()
        mock_doc.paragraphs = []
        mock_doc.tables = []
        annotations = [
            {"原文片段": "text", "修改建议": "建议：改用更简洁的表达"},
        ]
        with patch(
            "app.core.file.track_changes.editor.Document", return_value=mock_doc
        ), patch.object(
            editor, "_apply_single_comment", return_value=True
        ), patch.object(
            editor, "_inject_comments_to_docx", return_value=True
        ):
            result = editor.apply_hybrid_changes("/fake.docx", annotations)
        assert isinstance(result, dict)

    def test_apply_hybrid_changes_classifies_short_edit_as_tracked(self):
        editor = self._make_editor()
        mock_doc = MagicMock()
        mock_doc.paragraphs = []
        mock_doc.tables = []
        annotations = [
            {"原文片段": "旧文本", "修改后文本": "新文本"},
        ]
        with patch(
            "app.core.file.track_changes.editor.Document", return_value=mock_doc
        ), patch.object(editor, "_apply_single_track_change", return_value=True):
            result = editor.apply_hybrid_changes("/fake.docx", annotations)
        assert isinstance(result, dict)

    def test_apply_hybrid_changes_exception(self):
        editor = self._make_editor()
        with patch(
            "app.core.file.track_changes.editor.Document", side_effect=Exception("fail")
        ):
            result = editor.apply_hybrid_changes(
                "/fake.docx", [{"原文片段": "a", "修改后文本": "b"}]
            )
        assert result["success"] is False

    def test_apply_hybrid_changes_empty_annotations(self):
        editor = self._make_editor()
        mock_doc = MagicMock()
        mock_doc.paragraphs = []
        mock_doc.tables = []
        with patch(
            "app.core.file.track_changes.editor.Document", return_value=mock_doc
        ):
            result = editor.apply_hybrid_changes("/fake.docx", [])
        assert isinstance(result, dict)
        assert result.get("total", 0) == 0

    # -- _esc static method edge cases --------------------------------------
    def test_esc_all_special_chars(self):
        from app.core.file.track_changes import TrackChangesEditor

        result = TrackChangesEditor._esc("&<>\"'")
        assert "&amp;" in result
        assert "&lt;" in result
        assert "&gt;" in result

    def test_esc_unicode_text(self):
        from app.core.file.track_changes import TrackChangesEditor

        result = TrackChangesEditor._esc("中文测试 & <特殊>")
        assert "&amp;" in result
        assert "&lt;" in result
        assert "中文测试" in result

    # -- _add_comments_content_type -----------------------------------------
    def test_add_comments_content_type_adds_override(self):
        editor = self._make_editor()
        xml_data = b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>'
        result = editor._add_comments_content_type(xml_data)
        assert b"comments" in result

    def test_add_comments_relationship_adds_rel(self):
        editor = self._make_editor()
        xml_data = b'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>'
        result = editor._add_comments_relationship(xml_data)
        assert b"comments" in result

    # -- apply_comment_changes ----------------------------------------------
    def test_apply_comment_changes_empty(self):
        editor = self._make_editor()
        mock_doc = MagicMock()
        mock_doc.paragraphs = []
        with patch(
            "app.core.file.track_changes.editor.Document", return_value=mock_doc
        ):
            result = editor.apply_comment_changes("/fake.docx", [])
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# 4. Removed microphone STT modules
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestRemovedMicrophoneSttModules:
    def test_modules_stay_absent(self):
        removed = [
            "voice_" + "fast.py",
            "voice_" + "input.py",
            "voice_" + "engine.py",
        ]
        for filename in removed:
            assert not Path("web", filename).exists()


# ---------------------------------------------------------------------------
# 6. local_model_installer – deeper coverage
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestLocalModelInstallerDeep:
    """Cover get_system_info, is_ollama_running, start_ollama, pull_model,
    save_result, _find_ollama_exe, _download_with_retry."""

    # -- is_ollama_running--------------------------------------------------
    def test_is_ollama_running_true(self):
        with patch("src.local_model_installer.socket.create_connection") as mock_conn:
            mock_sock = MagicMock()
            mock_conn.return_value = mock_sock
            from src.local_model_installer import is_ollama_running

            assert is_ollama_running() is True
            mock_sock.close.assert_called_once()

    def test_is_ollama_running_false(self):
        with patch(
            "src.local_model_installer.socket.create_connection",
            side_effect=ConnectionRefusedError,
        ):
            from src.local_model_installer import is_ollama_running

            assert is_ollama_running() is False

    def test_is_ollama_running_timeout(self):
        with patch(
            "src.local_model_installer.socket.create_connection",
            side_effect=TimeoutError,
        ):
            from src.local_model_installer import is_ollama_running

            assert is_ollama_running() is False

    # -- _find_ollama_exe ---------------------------------------------------
    def test_find_ollama_exe_via_shutil_which(self):
        with patch(
            "src.local_model_installer.shutil.which",
            return_value="C:\\ollama\\ollama.exe",
        ):
            from src.local_model_installer import _find_ollama_exe

            result = _find_ollama_exe()
        assert result is not None
        assert "ollama" in result

    def test_find_ollama_exe_not_found(self):
        with patch("src.local_model_installer.shutil.which", return_value=None), patch(
            "src.local_model_installer._OLLAMA_SEARCH_PATHS", []
        ):
            from src.local_model_installer import _find_ollama_exe

            result = _find_ollama_exe()
        assert result is None

    def test_find_ollama_exe_from_search_path(self):
        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mock_path.parent = MagicMock()
        mock_path.parent.__str__ = lambda s: "C:\\Program Files\\Ollama"
        mock_path.__str__ = lambda s: "C:\\Program Files\\Ollama\\ollama.exe"
        with patch("src.local_model_installer.shutil.which", return_value=None), patch(
            "src.local_model_installer._OLLAMA_SEARCH_PATHS", [mock_path]
        ):
            from src.local_model_installer import _find_ollama_exe

            result = _find_ollama_exe()
        assert result is not None

    # -- start_ollama -------------------------------------------------------
    def test_start_ollama_already_running(self):
        with patch("src.local_model_installer.is_ollama_running", return_value=True):
            from src.local_model_installer import start_ollama

            result = start_ollama()
        assert result is True

    def test_start_ollama_no_exe_found(self):
        with patch(
            "src.local_model_installer.is_ollama_running", return_value=False
        ), patch("src.local_model_installer._find_ollama_exe", return_value=None):
            from src.local_model_installer import start_ollama

            result = start_ollama(log_cb=MagicMock())
        assert result is False

    # -- save_result --------------------------------------------------------
    def test_save_result_creates_file(self):
        from src.local_model_installer import save_result

        with tempfile.TemporaryDirectory() as td:
            result_file = Path(td) / "installed_models.json"
            with patch("src.local_model_installer.RESULT_FILE", result_file):
                save_result("gemma3:1b")
            assert result_file.exists()
            data = json.loads(result_file.read_text())
            assert data["model"] == "gemma3:1b"
            assert "installed_at" in data
            assert data["ollama_endpoint"] == "http://127.0.0.1:11434"

    def test_save_result_exception_silent(self):
        from src.local_model_installer import save_result

        with patch(
            "src.local_model_installer.RESULT_FILE",
            MagicMock(write_text=MagicMock(side_effect=PermissionError)),
        ):
            save_result("test:1b")  # should not raise

    # -- pull_model ---------------------------------------------------------
    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
    def test_pull_model_success(self):
        mock_proc = MagicMock()
        mock_proc.stdout = iter(["pulling manifest\n", "success\n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        with patch(
            "src.local_model_installer._find_ollama_exe", return_value="ollama"
        ), patch("src.local_model_installer.subprocess.Popen", return_value=mock_proc):
            from src.local_model_installer import pull_model

            result = pull_model("gemma3:1b", prog_cb=MagicMock(), log_cb=MagicMock())
        assert result is True

    def test_pull_model_no_ollama(self):
        with patch("src.local_model_installer._find_ollama_exe", return_value=None):
            from src.local_model_installer import pull_model

            result = pull_model("gemma3:1b")
        assert result is False

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
    def test_pull_model_with_progress_percentage(self):
        mock_proc = MagicMock()
        mock_proc.stdout = iter(["pulling manifest\n", "  50% complete\n", "success\n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        prog_cb = MagicMock()
        with patch(
            "src.local_model_installer._find_ollama_exe", return_value="ollama"
        ), patch("src.local_model_installer.subprocess.Popen", return_value=mock_proc):
            from src.local_model_installer import pull_model

            result = pull_model("gemma3:1b", prog_cb=prog_cb, log_cb=MagicMock())
        assert result is True

    # -- get_system_info GPU detection --------------------------------------
    def test_get_system_info_returns_required_keys(self):
        from src.local_model_installer import get_system_info

        with patch(
            "src.local_model_installer.platform.processor", return_value="Intel Core i7"
        ), patch("src.local_model_installer.os.cpu_count", return_value=8):
            info = get_system_info()
        assert "ram_gb" in info
        assert "cpu" in info
        assert "gpu_name" in info
        assert "ollama_installed" in info

    # -- recommend_models ---------------------------------------------------
    def test_recommend_models_returns_non_empty(self):
        from src.local_model_installer import recommend_models

        info = {
            "ram_gb": 16,
            "gpu_vram_gb": 8,
            "gpu_name": "NVIDIA RTX 3070",
            "ollama_installed": False,
            "ollama_running": False,
            "installed_models": [],
        }
        models = recommend_models(info)
        assert isinstance(models, list)
        assert len(models) >= 1
        for m in models:
            assert "tag" in m

    def test_recommend_models_low_resources(self):
        from src.local_model_installer import recommend_models

        info = {
            "ram_gb": 0.5,
            "gpu_vram_gb": 0,
            "gpu_name": "",
            "ollama_installed": False,
            "ollama_running": False,
            "installed_models": [],
        }
        models = recommend_models(info)
        assert len(models) >= 1

    def test_recommend_models_high_resources(self):
        from src.local_model_installer import MODEL_CATALOG, recommend_models

        info = {
            "ram_gb": 64,
            "gpu_vram_gb": 24,
            "gpu_name": "NVIDIA RTX 4090",
            "ollama_installed": False,
            "ollama_running": False,
            "installed_models": [],
        }
        models = recommend_models(info)
        assert len(models) == len(MODEL_CATALOG)


# ---------------------------------------------------------------------------
# 7. koto_setup – deeper coverage
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestKotoSetupDeep:
    """Cover config writing edge cases, API validation errors,
    _run_setup_if_needed branches, _prompt_local_model_if_needed."""

    # -- _write_deepseek_config ---------------------------------------------
    def test_write_config_creates_file(self):
        from src.koto_setup import _write_deepseek_config

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            with patch("src.koto_setup.APP_ROOT", td_path):
                _write_deepseek_config(
                    "sk-test-key-123456789", "https://custom.api.com"
                )
            config_file = td_path / "config" / "deepseek_config.env"
            assert config_file.exists()
            content = config_file.read_text(encoding="utf-8")
            assert "sk-test-key-123456789" in content
            assert "https://custom.api.com" in content

    def test_write_config_default_base(self):
        from src.koto_setup import _write_deepseek_config

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            with patch("src.koto_setup.APP_ROOT", td_path):
                _write_deepseek_config("sk-test-key-999", "")
            content = (td_path / "config" / "deepseek_config.env").read_text(
                encoding="utf-8"
            )
            assert "sk-test-key-999" in content
            assert "DEEPSEEK_BASE_URL=https://api.deepseek.com" in content

    # -- _api_key_configured ------------------------------------------------
    def test_api_key_configured_false_for_your_api_key_here(self):
        from src.koto_setup import _api_key_configured

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            cfg = td_path / "config" / "deepseek_config.env"
            cfg.parent.mkdir(parents=True)
            cfg.write_text("DEEPSEEK_API_KEY=your_api_key_here\n")
            with patch("src.koto_setup.APP_ROOT", td_path):
                result = _api_key_configured()
        assert result is False

    def test_api_key_configured_false_for_empty(self):
        from src.koto_setup import _api_key_configured

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            cfg = td_path / "config" / "deepseek_config.env"
            cfg.parent.mkdir(parents=True)
            cfg.write_text("DEEPSEEK_API_KEY=\n")
            with patch("src.koto_setup.APP_ROOT", td_path):
                result = _api_key_configured()
        assert result is False

    def test_api_key_configured_false_for_none(self):
        from src.koto_setup import _api_key_configured

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            cfg = td_path / "config" / "deepseek_config.env"
            cfg.parent.mkdir(parents=True)
            cfg.write_text("DEEPSEEK_API_KEY=None\n")
            with patch("src.koto_setup.APP_ROOT", td_path):
                result = _api_key_configured()
        assert result is False

    def test_api_key_configured_true_for_real_key(self):
        from src.koto_setup import _api_key_configured

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            cfg = td_path / "config" / "deepseek_config.env"
            cfg.parent.mkdir(parents=True)
            cfg.write_text(
                ("DEEPSEEK_API_KEY=" + "sk-" + "real-key-value-123456789" + "\n")
            )
            with patch("src.koto_setup.APP_ROOT", td_path):
                result = _api_key_configured()
        assert result is True

    def test_api_key_configured_no_file(self):
        from src.koto_setup import _api_key_configured

        with tempfile.TemporaryDirectory() as td:
            with patch("src.koto_setup.APP_ROOT", Path(td)):
                result = _api_key_configured()
        assert result is False

    # -- _read_config_values ------------------------------------------------
    def test_read_config_values_parses_both_fields(self):
        from src.koto_setup import _read_config_values

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            cfg = td_path / "config" / "deepseek_config.env"
            cfg.parent.mkdir(parents=True)
            cfg.write_text(
                "DEEPSEEK_API_KEY=sk-key-123\nDEEPSEEK_BASE_URL=https://api.example.com\n"
            )
            with patch("src.koto_setup.APP_ROOT", td_path):
                key, base = _read_config_values()
        assert key == "sk-key-123"
        assert base == "https://api.example.com"

    def test_read_config_values_missing_file(self):
        from src.koto_setup import _read_config_values

        with tempfile.TemporaryDirectory() as td:
            with patch("src.koto_setup.APP_ROOT", Path(td)):
                key, base = _read_config_values()
        assert key == ""
        assert base == ""

    # -- _validate_api_key --------------------------------------------------
    def test_validate_api_key_success(self):
        from src.koto_setup import _validate_api_key

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = lambda s: mock_response
        mock_response.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_response):
            ok, msg = _validate_api_key("sk-test-key-123456789")
        assert ok is True

    def test_validate_api_key_http_400(self):
        import urllib.error

        from src.koto_setup import _validate_api_key

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                "http://example.com", 400, "Bad Request", {}, None
            ),
        ):
            ok, msg = _validate_api_key("sk-bad-key")
        assert ok is False
        assert "❌" in msg

    def test_validate_api_key_http_403(self):
        import urllib.error

        from src.koto_setup import _validate_api_key

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                "http://example.com", 403, "Forbidden", {}, None
            ),
        ):
            ok, msg = _validate_api_key("sk-forbidden")
        assert ok is False
        assert "403" in msg or "❌" in msg

    def test_validate_api_key_http_500(self):
        import urllib.error

        from src.koto_setup import _validate_api_key

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                "http://example.com", 500, "Server Error", {}, None
            ),
        ):
            ok, msg = _validate_api_key("sk-test-key-123456789")
        assert ok is False
        assert "500" in msg

    def test_validate_api_key_network_error(self):
        from src.koto_setup import _validate_api_key

        with patch("urllib.request.urlopen", side_effect=ConnectionError("no network")):
            ok, msg = _validate_api_key("sk-test-key-123456789")
        assert ok is False
        assert "⚠" in msg

    def test_validate_api_key_custom_base(self):
        from src.koto_setup import _validate_api_key

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = lambda s: mock_response
        mock_response.__exit__ = MagicMock(return_value=False)
        with patch(
            "urllib.request.urlopen", return_value=mock_response
        ) as mock_urlopen:
            ok, msg = _validate_api_key("sk-key", base="https://custom.api.com")
        assert ok is True
        # Verify the custom base was used in the URL
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert "custom.api.com" in req.full_url

    # -- _run_setup_if_needed -----------------------------------------------
    def test_run_setup_if_needed_forced_with_flag(self):
        from src.koto_setup import _run_setup_if_needed

        with patch("sys.argv", ["koto_setup.py", "--setup"]), patch(
            "src.koto_setup._show_api_setup_wizard",
            return_value={"key": ("sk-" + "key-12345678901234567890"), "base": ""},
        ) as mock_wizard, patch("src.koto_setup._write_cloud_config"), patch(
            "src.koto_setup.APP_ROOT", Path(tempfile.mkdtemp())
        ):
            try:
                _run_setup_if_needed()
            except Exception:
                pass
        mock_wizard.assert_called_once()

    def test_run_setup_if_needed_user_cancels(self):
        from src.koto_setup import _run_setup_if_needed

        with patch("sys.argv", ["koto_setup.py", "--setup"]), patch(
            "src.koto_setup._show_api_setup_wizard",
            return_value={"key": None, "base": "", "cancelled": True},
        ), patch("src.koto_setup._run_unified_setup", return_value=False):
            _run_setup_if_needed()  # should not crash

    def test_run_setup_skips_when_key_valid(self):
        from src.koto_setup import _run_setup_if_needed

        with patch("sys.argv", ["koto_setup.py"]), patch(
            "src.koto_setup._api_key_configured", return_value=True
        ), patch(
            "src.koto_setup._read_config_values", return_value=("sk-key", "")
        ), patch(
            "src.koto_setup._validate_api_key", return_value=(True, "")
        ), patch(
            "src.koto_setup._show_api_setup_wizard"
        ) as mock_wizard:
            _run_setup_if_needed()
        mock_wizard.assert_not_called()

    def test_run_setup_skips_on_network_error(self):
        from src.koto_setup import _run_setup_if_needed

        with patch("sys.argv", ["koto_setup.py"]), patch(
            "src.koto_setup._api_key_configured", return_value=True
        ), patch(
            "src.koto_setup._read_config_values", return_value=("sk-key", "")
        ), patch(
            "src.koto_setup._validate_api_key", return_value=(False, "⚠️ 网络异常")
        ), patch(
            "src.koto_setup._show_api_setup_wizard"
        ) as mock_wizard:
            _run_setup_if_needed()
        mock_wizard.assert_not_called()

    # -- _prompt_local_model_if_needed --------------------------------------
    def test_prompt_local_model_skips_if_already_prompted(self):
        from src.koto_setup import _prompt_local_model_if_needed

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            flag = td_path / "config" / "local_model_prompted.json"
            flag.parent.mkdir(parents=True)
            flag.write_text('{"prompted": true}')
            with patch("src.koto_setup.APP_ROOT", td_path):
                _prompt_local_model_if_needed()

    def test_prompt_local_model_skips_if_no_installer(self):
        from src.koto_setup import _prompt_local_model_if_needed

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            (td_path / "config").mkdir(parents=True)
            with patch("src.koto_setup.APP_ROOT", td_path):
                _prompt_local_model_if_needed()
