"""
Unit tests for web modules batch 2:
  - FileConverter  (web.file_converter)
  - LocalExecutor  (web.local_executor)
  - FileProcessor  (web.file_processor)
  - Removed microphone STT module
  - ImageGenerator (web.image_generator)

All external services (APIs, file I/O, audio libs, COM) are mocked.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, Mock, PropertyMock, mock_open, patch

import pytest

try:
    import google.genai._api_client  # noqa: F401

    HAS_GENAI = True
except (ImportError, ModuleNotFoundError):
    HAS_GENAI = False

# ═══════════════════════════════════════════════════════════════════════════════
# 1. FileConverter
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestFileConverterConstants:
    """Tests for module-level constants and mappings."""

    def test_conversion_matrix_has_expected_source_formats(self):
        from web.file_converter import CONVERSION_MATRIX

        expected_keys = {
            ".docx",
            ".doc",
            ".pdf",
            ".txt",
            ".md",
            ".xlsx",
            ".xls",
            ".csv",
            ".pptx",
            ".ppt",
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
            ".bmp",
            ".gif",
            ".markdown",
        }
        assert expected_keys.issubset(set(CONVERSION_MATRIX.keys()))

    def test_format_aliases_maps_common_names(self):
        from web.file_converter import FORMAT_ALIASES

        assert FORMAT_ALIASES["word"] == ".docx"
        assert FORMAT_ALIASES["pdf"] == ".pdf"
        assert FORMAT_ALIASES["excel"] == ".xlsx"
        assert FORMAT_ALIASES["csv"] == ".csv"

    def test_image_exts_contains_common_types(self):
        from web.file_converter import IMAGE_EXTS

        assert ".jpg" in IMAGE_EXTS
        assert ".png" in IMAGE_EXTS
        assert ".webp" in IMAGE_EXTS

    def test_cn_format_patterns_compiled(self):
        from web.file_converter import CN_FORMAT_PATTERNS

        assert len(CN_FORMAT_PATTERNS) > 0
        for pat, ext in CN_FORMAT_PATTERNS:
            assert hasattr(pat, "search")
            assert ext.startswith(".")


@pytest.mark.unit
class TestGetSupportedConversions:

    def test_returns_dict_of_lists(self):
        from web.file_converter import get_supported_conversions

        result = get_supported_conversions()
        assert isinstance(result, dict)
        for key, val in result.items():
            assert isinstance(val, list)

    def test_returns_copy_not_reference(self):
        from web.file_converter import CONVERSION_MATRIX, get_supported_conversions

        result = get_supported_conversions()
        result[".docx"].append(".fake")
        assert ".fake" not in CONVERSION_MATRIX[".docx"]


@pytest.mark.unit
class TestConvertFunction:

    def test_file_not_exists_returns_error(self):
        from web.file_converter import convert

        result = convert("/nonexistent/file.docx", "pdf")
        assert result["success"] is False
        assert "不存在" in result["error"]

    def test_same_format_returns_error(self, tmp_path):
        from web.file_converter import convert

        f = tmp_path / "test.pdf"
        f.write_text("hello")
        result = convert(str(f), "pdf")
        assert result["success"] is False
        assert "相同" in result["error"]

    def test_unsupported_source_format(self, tmp_path):
        from web.file_converter import convert

        f = tmp_path / "test.xyz"
        f.write_text("hello")
        result = convert(str(f), "pdf")
        assert result["success"] is False
        assert "不支持" in result["error"]

    def test_unsupported_target_format(self, tmp_path):
        from web.file_converter import convert

        f = tmp_path / "test.docx"
        f.write_bytes(b"fake docx")
        result = convert(str(f), "mp3")
        assert result["success"] is False
        assert "不支持" in result["error"]

    def test_successful_dispatch(self, tmp_path):
        from web.file_converter import convert

        f = tmp_path / "test.txt"
        f.write_text("Hello World", encoding="utf-8")
        with patch("web.file_converter._dispatch") as mock_dispatch:
            out_path = str(tmp_path / "test.md")
            mock_dispatch.return_value = (out_path, "")
            result = convert(str(f), "md", output_dir=str(tmp_path))
        assert result["success"] is True
        assert result["from_format"] == "txt"
        assert result["to_format"] == "md"

    def test_dispatch_exception_returns_error(self, tmp_path):
        from web.file_converter import convert

        f = tmp_path / "test.txt"
        f.write_text("x")
        with patch("web.file_converter._dispatch", side_effect=RuntimeError("boom")):
            result = convert(str(f), "pdf", output_dir=str(tmp_path))
        assert result["success"] is False
        assert "boom" in result["error"]

    def test_format_alias_resolution(self, tmp_path):
        from web.file_converter import convert

        f = tmp_path / "test.txt"
        f.write_text("x")
        with patch("web.file_converter._dispatch") as mock_dispatch:
            out_path = str(tmp_path / "test.docx")
            mock_dispatch.return_value = (out_path, "")
            result = convert(str(f), "word", output_dir=str(tmp_path))
        assert result["success"] is True
        assert result["to_format"] == "docx"

    def test_convert_with_explicit_output_path(self, tmp_path):
        from web.file_converter import convert

        f = tmp_path / "test.txt"
        f.write_text("x")
        out = str(tmp_path / "custom_output.docx")
        with patch("web.file_converter._dispatch") as mock_dispatch:
            mock_dispatch.return_value = (out, "")
            result = convert(str(f), "docx", output_path=out)
        assert result["success"] is True
        assert result["output_path"] == out

    def test_warning_passed_through(self, tmp_path):
        from web.file_converter import convert

        f = tmp_path / "test.txt"
        f.write_text("x")
        with patch("web.file_converter._dispatch") as mock_dispatch:
            out = str(tmp_path / "test.pdf")
            mock_dispatch.return_value = (out, "⚠️ some warning")
            result = convert(str(f), "pdf", output_dir=str(tmp_path))
        assert result["warning"] == "⚠️ some warning"


@pytest.mark.unit
class TestSkillEntry:

    def test_missing_file_path_returns_error(self):
        from web.file_converter import skill_entry

        result = skill_entry("转换成pdf", {})
        assert result["success"] is False
        assert "file_path" in result["message"]

    def test_unrecognised_format_returns_error(self, tmp_path):
        from web.file_converter import skill_entry

        f = tmp_path / "test.txt"
        f.write_text("x")
        result = skill_entry("做点什么", {"file_path": str(f)})
        assert result["success"] is False
        assert "格式" in result["message"]

    def test_valid_call_delegates_to_convert(self, tmp_path):
        from web.file_converter import skill_entry

        f = tmp_path / "test.txt"
        f.write_text("x")
        with patch("web.file_converter.convert") as mock_convert:
            mock_convert.return_value = {"success": True, "output_path": "/x.pdf"}
            skill_entry("转换成pdf", {"file_path": str(f)})
            mock_convert.assert_called_once()


@pytest.mark.unit
class TestDispatch:

    def test_image_to_image_route(self):
        from web.file_converter import _dispatch

        with patch(
            "web.file_converter._img_to_img", return_value=("/out.png", "")
        ) as m:
            _dispatch("/in.jpg", ".jpg", ".png", "/out.png")
            m.assert_called_once()

    def test_unknown_key_raises(self):
        from web.file_converter import _dispatch

        with pytest.raises(NotImplementedError):
            _dispatch("/in.foo", ".foo", ".bar", "/out.bar")


@pytest.mark.unit
class TestImgToImg:

    def test_converts_jpeg_rgba(self):
        mock_img = MagicMock()
        mock_img.mode = "RGBA"
        mock_img.convert.return_value = mock_img
        mock_img.__enter__ = Mock(return_value=mock_img)
        mock_img.__exit__ = Mock(return_value=False)

        mock_image_mod = MagicMock()
        mock_image_mod.open.return_value = mock_img
        mock_pil_pkg = MagicMock()
        mock_pil_pkg.Image = mock_image_mod

        with patch.dict(
            "sys.modules", {"PIL": mock_pil_pkg, "PIL.Image": mock_image_mod}
        ):
            from web.file_converter import _img_to_img

            out, warning = _img_to_img("/in.png", "/out.jpg", ".jpg")
        assert out == "/out.jpg"
        mock_img.convert.assert_called_with("RGB")

    def test_converts_png_no_convert(self):
        mock_img = MagicMock()
        mock_img.mode = "RGB"
        mock_img.__enter__ = Mock(return_value=mock_img)
        mock_img.__exit__ = Mock(return_value=False)

        mock_image_mod = MagicMock()
        mock_image_mod.open.return_value = mock_img
        mock_pil_pkg = MagicMock()
        mock_pil_pkg.Image = mock_image_mod

        with patch.dict(
            "sys.modules", {"PIL": mock_pil_pkg, "PIL.Image": mock_image_mod}
        ):
            from web.file_converter import _img_to_img

            out, _ = _img_to_img("/in.jpg", "/out.png", ".png")
        mock_img.convert.assert_not_called()
        mock_img.save.assert_called_once_with("/out.png", "PNG")


@pytest.mark.unit
class TestExtractTargetFormat:

    def test_chinese_keyword_pdf(self):
        from web.file_converter import _extract_target_format

        assert _extract_target_format("请转换为PDF文件") is not None

    def test_english_alias(self):
        from web.file_converter import _extract_target_format

        result = _extract_target_format("convert to pdf")
        assert result is not None

    def test_no_match_returns_none(self):
        from web.file_converter import _extract_target_format

        assert _extract_target_format("请帮我做晚饭") is None

    def test_word_alias(self):
        from web.file_converter import _extract_target_format

        result = _extract_target_format("转换成word文档")
        assert result is not None


@pytest.mark.unit
class TestErrHelper:

    def test_err_structure(self):
        from web.file_converter import _err

        result = _err("something wrong")
        assert result["success"] is False
        assert result["error"] == "something wrong"
        assert "❌" in result["message"]
        assert result["output_path"] == ""


@pytest.mark.unit
class TestTextCopy:

    def test_copies_file(self, tmp_path):
        src = tmp_path / "a.txt"
        dst = tmp_path / "b.md"
        src.write_text("hello")
        from web.file_converter import _text_copy

        out, warning = _text_copy(str(src), str(dst))
        assert Path(out).read_text() == "hello"
        assert warning == ""


@pytest.mark.unit
class TestSafeRl:

    def test_escapes_html_chars(self):
        from web.file_converter import _safe_rl

        assert _safe_rl("<b>foo & bar</b>") == "&lt;b&gt;foo &amp; bar&lt;/b&gt;"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. LocalExecutor
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestLocalExecutorIsSystemCommand:

    def _cls(self):
        from web.local_executor import LocalExecutor

        return LocalExecutor

    def test_open_app_not_detected(self):
        assert self._cls().is_system_command("打开微信") is False

    def test_english_open_not_detected(self):
        assert self._cls().is_system_command("open chrome") is False

    def test_question_not_detected(self):
        assert self._cls().is_system_command("怎么打开微信") is False

    def test_long_text_not_detected(self):
        assert self._cls().is_system_command("a" * 50) is False

    def test_standalone_screenshot_not_detected(self):
        assert self._cls().is_system_command("截图") is False

    def test_standalone_time(self):
        assert self._cls().is_system_command("时间") is True

    def test_shutdown_not_detected(self):
        assert self._cls().is_system_command("关机") is False

    def test_no_keyword_returns_false(self):
        assert self._cls().is_system_command("你好") is False

    def test_action_command_start_pattern_not_detected(self):
        assert self._cls().is_system_command("打开记事本") is False

    def test_metaphor_excluded(self):
        assert self._cls().is_system_command("打开网页") is False

    def test_system_status(self):
        assert self._cls().is_system_command("系统状态") is True

    def test_cpu_info(self):
        assert self._cls().is_system_command("cpu") is True


@pytest.mark.unit
class TestLocalExecutorRetiredSystemAppHelpers:

    def _cls(self):
        from web.local_executor import LocalExecutor

        return LocalExecutor

    def test_app_launch_helpers_removed(self):
        cls = self._cls()
        assert not hasattr(cls, "APP_ALIASES")
        assert not hasattr(cls, "SYSTEM_KEYWORDS")
        assert not hasattr(cls, "extract_app_name")
        assert not hasattr(cls, "find_app_in_start_menu")
        assert not hasattr(cls, "find_app_smart")


@pytest.mark.unit
class TestLocalExecutorExecute:

    def _cls(self):
        from web.local_executor import LocalExecutor

        return LocalExecutor

    @pytest.mark.parametrize(
        "command",
        [
            "打开记事本",
            "打开设置",
            "打开myapp",
            "关闭记事本",
            "截图",
            "搜索Python教程",
            "关机",
        ],
    )
    def test_side_effect_system_actions_removed(self, command):
        with patch("subprocess.Popen") as mock_popen, patch(
            "subprocess.run"
        ) as mock_run, patch("webbrowser.open") as mock_browser:
            result = self._cls().execute(command)
        assert result["success"] is False
        assert result["action"] == ""
        assert "无法识别" in result["message"]
        mock_popen.assert_not_called()
        mock_run.assert_not_called()
        mock_browser.assert_not_called()

    def test_get_time(self):
        result = self._cls().execute("几点了")
        assert result["success"] is True
        assert result["action"] == "get_time"
        assert "时间" in result["message"]

    def test_get_date(self):
        result = self._cls().execute("今天日期")
        assert result["success"] is True
        assert "日期" in result["message"] or "📅" in result["message"]

    def test_system_info(self):
        mock_info = {
            "success": True,
            "system": "Windows",
            "platform": "win32",
            "processor": "Intel",
            "cpu_percent": 10,
            "memory": {"total": "16 GB", "available": "8 GB", "percent": 50},
            "disk": {"total": "500 GB", "free": "200 GB", "percent": 60},
        }
        with patch.object(self._cls(), "get_system_info", return_value=mock_info):
            result = self._cls().execute("系统状态")
        assert result["success"] is True
        assert result["action"] == "get_system_info"

    def test_unrecognized_command(self):
        result = self._cls().execute("xyzzy_unknown_command_abc")
        assert result["success"] is False
        assert "无法识别" in result["message"]

    def test_open_without_target_is_not_system_action(self):
        result = self._cls().execute("打开")
        assert result["success"] is False

    def test_open_wechat_stays_outside_local_executor(self):
        with patch("subprocess.Popen") as mock_popen, patch(
            "os.startfile", create=True
        ) as mock_startfile:
            result = self._cls().execute("打开微信")
        assert result["success"] is False
        assert result["action"] == ""
        assert "无法识别" in result["message"]
        mock_popen.assert_not_called()
        mock_startfile.assert_not_called()

    def test_arbitrary_open_app_stays_blocked(self):
        with patch("subprocess.Popen") as mock_popen, patch(
            "os.startfile", create=True
        ) as mock_startfile:
            result = self._cls().execute("打开myapp")
        assert result["success"] is False
        assert result["action"] == ""
        mock_popen.assert_not_called()
        mock_startfile.assert_not_called()


@pytest.mark.unit
class TestLocalExecutorClipboard:

    def _cls(self):
        from web.local_executor import LocalExecutor

        return LocalExecutor

    def test_get_clipboard_success(self):
        mock_pyperclip = MagicMock()
        mock_pyperclip.paste.return_value = "hello"
        with patch.dict("sys.modules", {"pyperclip": mock_pyperclip}):
            result = self._cls().get_clipboard()
        assert result["success"] is True
        assert result["content"] == "hello"

    def test_get_clipboard_failure(self):
        mock_pyperclip = MagicMock()
        mock_pyperclip.paste.side_effect = Exception("fail")
        with patch.dict("sys.modules", {"pyperclip": mock_pyperclip}):
            result = self._cls().get_clipboard()
        assert result["success"] is False

    def test_set_clipboard_success(self):
        mock_pyperclip = MagicMock()
        with patch.dict("sys.modules", {"pyperclip": mock_pyperclip}):
            result = self._cls().set_clipboard("test")
        assert result["success"] is True

    def test_set_clipboard_failure(self):
        mock_pyperclip = MagicMock()
        mock_pyperclip.copy.side_effect = Exception("fail")
        with patch.dict("sys.modules", {"pyperclip": mock_pyperclip}):
            result = self._cls().set_clipboard("test")
        assert result["success"] is False


@pytest.mark.unit
class TestLocalExecutorSystemInfo:

    def _cls(self):
        from web.local_executor import LocalExecutor

        return LocalExecutor

    def test_get_system_info_success(self):
        mock_psutil = MagicMock()
        mock_psutil.cpu_count.return_value = 8
        mock_psutil.cpu_percent.return_value = 25.0
        mock_vm = MagicMock(total=16e9, available=8e9, percent=50.0)
        mock_psutil.virtual_memory.return_value = mock_vm
        mock_du = MagicMock(total=500e9, free=200e9, percent=60.0)
        mock_psutil.disk_usage.return_value = mock_du

        with patch.dict("sys.modules", {"psutil": mock_psutil}), patch(
            "platform.system", return_value="Windows"
        ), patch("platform.platform", return_value="Windows-10"), patch(
            "platform.processor", return_value="Intel"
        ):
            result = self._cls().get_system_info()
        assert result["success"] is True
        assert result["system"] == "Windows"

    def test_get_system_info_failure(self):
        with patch.dict("sys.modules", {"psutil": None}):
            # When psutil is None, import will fail
            result = self._cls().get_system_info()
        assert result["success"] is False


@pytest.mark.unit
class TestLocalExecutorListRunningApps:

    def _cls(self):
        from web.local_executor import LocalExecutor

        return LocalExecutor

    def test_list_running_apps_success(self):
        mock_proc = MagicMock()
        mock_proc.info = {"name": "python.exe", "pid": 1234}
        mock_psutil = MagicMock()
        mock_psutil.process_iter.return_value = [mock_proc]

        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            result = self._cls().list_running_apps()
        assert result["success"] is True
        assert result["count"] == 1

    def test_list_running_apps_failure(self):
        with patch.dict(
            "sys.modules",
            {
                "psutil": MagicMock(
                    process_iter=MagicMock(side_effect=Exception("boom"))
                )
            },
        ):
            result = self._cls().list_running_apps()
        assert result["success"] is False


@pytest.mark.unit
class TestLocalExecutorOpenFileOrDirectory:

    def _cls(self):
        from web.local_executor import LocalExecutor

        return LocalExecutor

    def test_open_file_or_directory_removed(self):
        assert not hasattr(self._cls(), "open_file_or_directory")


@pytest.mark.unit
class TestLocalExecutorSendKeystroke:

    def _cls(self):
        from web.local_executor import LocalExecutor

        return LocalExecutor

    def test_send_keystroke_removed(self):
        assert not hasattr(self._cls(), "send_keystroke")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. FileProcessor
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestFileProcessorProcessFile:

    def test_text_file(self, tmp_path):
        from web.file_processor import FileProcessor

        f = tmp_path / "hello.txt"
        f.write_text("Hello World", encoding="utf-8")
        result = FileProcessor.process_file(str(f))
        assert result["success"] is True
        assert result["text_content"] == "Hello World"
        assert result["metadata"]["encoding"] == "utf-8"

    def test_unknown_mime_type_fallback_to_text(self, tmp_path):
        from web.file_processor import FileProcessor

        f = tmp_path / "data.xyz"
        f.write_text("some data", encoding="utf-8")
        result = FileProcessor.process_file(str(f))
        assert result["success"] is True
        assert "some data" in result["text_content"]

    def test_image_file(self, tmp_path):
        from web.file_processor import FileProcessor

        f = tmp_path / "photo.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        mock_pil_image = MagicMock()
        mock_img = MagicMock()
        mock_img.width = 800
        mock_img.height = 600
        mock_img.format = "PNG"
        mock_img.__enter__ = Mock(return_value=mock_img)
        mock_img.__exit__ = Mock(return_value=False)
        mock_pil_image.open.return_value = mock_img

        with patch.dict(
            "sys.modules", {"PIL": MagicMock(), "PIL.Image": mock_pil_image}
        ):
            result = FileProcessor.process_file(str(f))
        assert result["success"] is True
        assert result["binary_data"] is not None

    def test_image_without_pil(self, tmp_path):
        from web.file_processor import FileProcessor

        f = tmp_path / "photo.jpg"
        f.write_bytes(b"\xff\xd8\xff" + b"\x00" * 50)
        with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None}):
            result = FileProcessor.process_file(str(f))
        assert result["success"] is True
        assert result["binary_data"] is not None

    def test_pdf_file_binary(self, tmp_path):
        from web.file_processor import FileProcessor

        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4 fake content")
        # Mock PyPDF2 as unavailable
        with patch.dict("sys.modules", {"PyPDF2": None}):
            result = FileProcessor.process_file(str(f))
        assert result["success"] is True
        assert result["binary_data"] is not None
        assert result["mime_type"] == "application/pdf"

    def test_pdf_with_good_text(self, tmp_path):
        from web.file_processor import FileProcessor

        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4 fake content")

        mock_pypdf2 = MagicMock()
        mock_reader = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = (
            "这是一段正常的中文文本内容用于测试质量评估功能"
        )
        mock_reader.pages = [mock_page]
        mock_pypdf2.PdfReader.return_value = mock_reader

        # Need to patch the import inside _process_pdf which uses `import PyPDF2`
        with patch.dict("sys.modules", {"PyPDF2": mock_pypdf2}):
            result = FileProcessor.process_file(str(f))
        assert result["success"] is True
        # Text quality check depends on heuristic; at minimum it should succeed

    def test_pdf_with_garbled_text(self, tmp_path):
        from web.file_processor import FileProcessor

        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4 content")

        mock_pypdf2 = MagicMock()
        mock_reader = MagicMock()
        mock_page = MagicMock()
        # Garbled text: lots of Latin extended chars, few CJK
        garbled = "".join(chr(c) for c in range(0x00C0, 0x00FF)) * 5
        mock_page.extract_text.return_value = garbled
        mock_reader.pages = [mock_page]
        mock_pypdf2.PdfReader.return_value = mock_reader

        with patch.dict("sys.modules", {"PyPDF2": mock_pypdf2}):
            result = FileProcessor.process_file(str(f))
        assert result["success"] is True
        assert result["metadata"].get("text_quality") == "garbled"

    def test_word_file_with_docx(self, tmp_path):
        from web.file_processor import FileProcessor

        f = tmp_path / "report.docx"
        f.write_bytes(b"fake docx")

        mock_docx = MagicMock()
        mock_doc = MagicMock()
        mock_para = MagicMock()
        mock_para.text = "Paragraph text"
        mock_doc.paragraphs = [mock_para]
        mock_doc.tables = []
        mock_docx.Document.return_value = mock_doc

        with patch.dict("sys.modules", {"docx": mock_docx}):
            result = FileProcessor.process_file(str(f))
        assert result["success"] is True
        assert "Paragraph text" in result["text_content"]

    def test_word_file_without_docx_lib(self, tmp_path):
        from web.file_processor import FileProcessor

        f = tmp_path / "report.docx"
        f.write_bytes(b"fake")

        with patch.dict("sys.modules", {"docx": None}):
            result = FileProcessor.process_file(str(f))
        assert result["success"] is False
        assert "python-docx" in result["error"]

    def test_word_file_with_tables(self, tmp_path):
        from web.file_processor import FileProcessor

        f = tmp_path / "data.docx"
        f.write_bytes(b"fake")

        mock_docx = MagicMock()
        mock_doc = MagicMock()
        mock_doc.paragraphs = []

        mock_cell = MagicMock()
        mock_cell.text = "cell1"
        mock_row = MagicMock()
        mock_row.cells = [mock_cell]
        mock_table = MagicMock()
        mock_table.rows = [mock_row]
        mock_doc.tables = [mock_table]
        mock_docx.Document.return_value = mock_doc

        with patch.dict("sys.modules", {"docx": mock_docx}):
            result = FileProcessor.process_file(str(f))
        assert result["success"] is True
        assert "cell1" in result["text_content"]

    def test_powerpoint_file(self, tmp_path):
        from web.file_processor import FileProcessor

        f = tmp_path / "slides.pptx"
        f.write_bytes(b"fake pptx")

        mock_pptx = MagicMock()
        mock_pres = MagicMock()
        mock_shape = MagicMock()
        mock_shape.text = "Slide title"
        mock_slide = MagicMock()
        mock_slide.shapes = [mock_shape]
        mock_pres.slides = [mock_slide]
        mock_pptx.Presentation.return_value = mock_pres

        with patch.dict("sys.modules", {"pptx": mock_pptx}):
            result = FileProcessor.process_file(str(f))
        assert result["success"] is True
        assert "Slide title" in result["text_content"]

    def test_powerpoint_empty_text(self, tmp_path):
        from web.file_processor import FileProcessor

        f = tmp_path / "empty.pptx"
        f.write_bytes(b"fake")

        mock_pptx = MagicMock()
        mock_pres = MagicMock()
        mock_shape = MagicMock()
        mock_shape.text = ""
        mock_slide = MagicMock()
        mock_slide.shapes = [mock_shape]
        mock_pres.slides = [mock_slide]
        mock_pptx.Presentation.return_value = mock_pres

        with patch.dict("sys.modules", {"pptx": mock_pptx}):
            result = FileProcessor.process_file(str(f))
        assert result["success"] is True

    def test_excel_file(self, tmp_path):
        from web.file_processor import FileProcessor

        f = tmp_path / "data.xlsx"
        f.write_bytes(b"fake xlsx")

        mock_pd = MagicMock()
        mock_xls = MagicMock()
        mock_xls.sheet_names = ["Sheet1"]
        mock_pd.ExcelFile.return_value = mock_xls
        mock_df = MagicMock()
        mock_df.to_string.return_value = "col1 col2\n1 2"
        mock_pd.read_excel.return_value = mock_df

        with patch.dict("sys.modules", {"pandas": mock_pd}):
            result = FileProcessor.process_file(str(f))
        assert result["success"] is True
        assert "Sheet1" in result["text_content"]

    def test_excel_without_pandas(self, tmp_path):
        from web.file_processor import FileProcessor

        f = tmp_path / "data.xlsx"
        f.write_bytes(b"fake")

        with patch.dict("sys.modules", {"pandas": None}):
            result = FileProcessor.process_file(str(f))
        assert result["success"] is False
        assert "pandas" in result["error"]

    def test_text_file_fallback_encoding(self, tmp_path):
        from web.file_processor import FileProcessor

        f = tmp_path / "encoded.txt"
        content = "你好世界"
        f.write_bytes(content.encode("gbk"))
        result = FileProcessor.process_file(str(f))
        assert result["success"] is True

    def test_process_file_general_exception(self, tmp_path):
        from web.file_processor import FileProcessor

        f = tmp_path / "bad.txt"
        f.write_text("x")
        with patch.object(
            FileProcessor, "_process_text", side_effect=RuntimeError("unexpected")
        ):
            result = FileProcessor.process_file(str(f))
        assert result["success"] is False
        assert "处理文件失败" in result["error"]

    def test_image_read_failure(self, tmp_path):
        from web.file_processor import FileProcessor

        f = tmp_path / "bad.png"
        f.write_bytes(b"\x89PNG")
        with patch("builtins.open", side_effect=PermissionError("no access")):
            result = FileProcessor._process_image(
                str(f),
                {
                    "success": False,
                    "mime_type": "image/png",
                    "filename": "bad.png",
                    "text_content": "",
                    "binary_data": None,
                    "error": "",
                    "metadata": {},
                },
            )
        assert "读取图片失败" in result["error"]

    def test_pdf_read_failure(self, tmp_path):
        from web.file_processor import FileProcessor

        f = tmp_path / "bad.pdf"
        f.write_bytes(b"%PDF")
        with patch("builtins.open", side_effect=PermissionError("denied")):
            result = FileProcessor._process_pdf(
                str(f),
                {
                    "success": False,
                    "mime_type": "application/pdf",
                    "filename": "bad.pdf",
                    "text_content": "",
                    "binary_data": None,
                    "error": "",
                    "metadata": {},
                },
            )
        assert "读取PDF失败" in result["error"]


@pytest.mark.unit
class TestFileProcessorFormatResultForChat:

    def _fp(self):
        from web.file_processor import FileProcessor

        return FileProcessor

    def test_failed_result(self):
        result = {
            "success": False,
            "error": "bad file",
            "text_content": "",
            "binary_data": None,
            "mime_type": "",
            "filename": "test.txt",
            "metadata": {},
        }
        msg, data = self._fp().format_result_for_chat(result, "hello")
        assert "❌" in msg
        assert data is None

    def test_binary_result(self):
        result = {
            "success": True,
            "error": "",
            "text_content": "",
            "binary_data": b"\x89PNG",
            "mime_type": "image/png",
            "filename": "img.png",
            "metadata": {},
        }
        msg, data = self._fp().format_result_for_chat(result, "see this")
        assert data is not None
        assert data["mime_type"] == "image/png"
        assert msg == "see this"

    def test_text_result(self):
        result = {
            "success": True,
            "error": "",
            "text_content": "Hello",
            "binary_data": None,
            "mime_type": "text/plain",
            "filename": "test.txt",
            "metadata": {"encoding": "utf-8"},
        }
        msg, data = self._fp().format_result_for_chat(result, "check this")
        assert "Hello" in msg
        assert "📄" in msg
        assert data is None

    def test_text_result_with_metadata(self):
        result = {
            "success": True,
            "error": "",
            "text_content": "Data",
            "binary_data": None,
            "mime_type": "text/plain",
            "filename": "test.txt",
            "metadata": {"lines": 5, "chars": 100},
        }
        msg, data = self._fp().format_result_for_chat(result)
        assert "lines: 5" in msg

    def test_empty_content_result(self):
        result = {
            "success": True,
            "error": "",
            "text_content": "",
            "binary_data": None,
            "mime_type": "text/plain",
            "filename": "empty.txt",
            "metadata": {},
        }
        msg, data = self._fp().format_result_for_chat(result, "msg")
        assert "⚠️" in msg
        assert data is None


@pytest.mark.unit
class TestProcessUploadedFile:

    def test_delegates_to_processor(self, tmp_path):
        from web.file_processor import process_uploaded_file

        f = tmp_path / "test.txt"
        f.write_text("Hello", encoding="utf-8")
        msg, data = process_uploaded_file(str(f), "my message")
        assert "Hello" in msg
        assert data is None


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Removed microphone STT module
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestRemovedMicrophoneSttModule:
    def test_removed_module_absent(self):
        assert not Path("web", "voice_" + "engine.py").exists()


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ImageGenerator
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestImageGeneratorInit:

    def test_init_with_api_key(self):
        with patch("web.image_generator.genai") as mock_genai:
            mock_genai.Client.return_value = MagicMock()
            from web.image_generator import ImageGenerator

            gen = ImageGenerator(api_key="test-key")
        assert gen.client is not None
        assert gen.image_model == "imagen-4.0-generate-001"

    def test_init_without_key_uses_env(self):
        with patch("web.image_generator.genai") as mock_genai, patch.dict(
            os.environ, {"GEMINI_API_KEY": "env-key"}
        ):
            mock_genai.Client.return_value = MagicMock()
            from web.image_generator import ImageGenerator

            gen = ImageGenerator()
        assert gen.client is not None

    def test_init_no_key_no_env(self):
        with patch("web.image_generator.genai"), patch.dict(os.environ, {}, clear=True):
            # Remove GEMINI_API_KEY if present
            os.environ.pop("GEMINI_API_KEY", None)
            from web.image_generator import ImageGenerator

            gen = ImageGenerator()
        assert gen.client is None


@pytest.mark.unit
class TestImageGeneratorGenerate:

    def _make_gen(self):
        from web.image_generator import ImageGenerator

        gen = ImageGenerator.__new__(ImageGenerator)
        gen.client = MagicMock()
        gen.image_model = "imagen-4.0-generate-001"
        return gen

    def test_no_client_returns_false(self):
        from web.image_generator import ImageGenerator

        gen = ImageGenerator.__new__(ImageGenerator)
        gen.client = None
        gen.image_model = "test"
        assert gen.generate_image("a cat", "/out.png") is False

    @pytest.mark.skipif(not HAS_GENAI, reason="google.genai not properly installed")
    def test_generate_images_success(self, tmp_path):
        gen = self._make_gen()
        out = str(tmp_path / "out.png")

        mock_img = MagicMock()
        mock_img.image.image_bytes = b"PNG_DATA"
        mock_response = MagicMock()
        mock_response.generated_images = [mock_img]
        gen.client.models.generate_images.return_value = mock_response

        result = gen.generate_image("a cat", out)
        assert result is True
        assert Path(out).read_bytes() == b"PNG_DATA"

    @pytest.mark.skipif(not HAS_GENAI, reason="google.genai not properly installed")
    def test_generate_images_empty_no_fallback(self, tmp_path):
        gen = self._make_gen()
        out = str(tmp_path / "out.png")

        # generate_images returns empty - no exception, so except block is NOT entered
        mock_response = MagicMock()
        mock_response.generated_images = []
        gen.client.models.generate_images.return_value = mock_response

        # When generated_images is empty and no exception, function falls through
        # returning None (implicit) - this matches the actual source behavior
        result = gen.generate_image("a cat", out)
        assert result is None

    def test_generate_images_exception_falls_back_to_content(self, tmp_path):
        gen = self._make_gen()
        out = str(tmp_path / "out.png")

        gen.client.models.generate_images.side_effect = Exception("API error")

        # Fallback generate_content with inline image
        import base64

        img_b64 = base64.b64encode(b"IMG_BYTES").decode()
        mock_part = MagicMock()
        mock_part.inline_data = MagicMock(data=img_b64)
        mock_content_part = MagicMock()
        mock_content_part.parts = [mock_part]
        mock_candidate = MagicMock()
        mock_candidate.content = mock_content_part
        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        gen.client.models.generate_content.return_value = mock_response

        result = gen.generate_image("a cat", out)
        assert result is True
        assert Path(out).read_bytes() == b"IMG_BYTES"

    def test_generate_content_no_inline_data(self, tmp_path):
        gen = self._make_gen()
        out = str(tmp_path / "out.png")

        gen.client.models.generate_images.side_effect = Exception("fail")

        mock_part = MagicMock()
        mock_part.inline_data = None
        mock_content = MagicMock()
        mock_content.parts = [mock_part]
        mock_candidate = MagicMock()
        mock_candidate.content = mock_content
        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        gen.client.models.generate_content.return_value = mock_response

        result = gen.generate_image("a cat", out)
        assert result is False

    def test_critical_exception(self, tmp_path):
        gen = self._make_gen()
        out = str(tmp_path / "out.png")

        gen.client.models.generate_images.side_effect = Exception("fail1")
        gen.client.models.generate_content.side_effect = Exception("fail2")

        result = gen.generate_image("a cat", out)
        assert result is False


@pytest.mark.unit
class TestImageGeneratorPlaceholder:

    def _make_gen(self):
        from web.image_generator import ImageGenerator

        gen = ImageGenerator.__new__(ImageGenerator)
        gen.client = None
        gen.image_model = "test"
        return gen

    def test_placeholder_with_pillow(self, tmp_path):
        gen = self._make_gen()
        out = str(tmp_path / "placeholder.png")

        mock_img = MagicMock()
        mock_draw = MagicMock()
        mock_pil_image = MagicMock()
        mock_pil_image.new.return_value = mock_img
        mock_pil_draw = MagicMock()
        mock_pil_draw.Draw.return_value = mock_draw
        mock_pil_font = MagicMock()

        mock_pil_pkg = MagicMock()
        mock_pil_pkg.Image = mock_pil_image
        mock_pil_pkg.ImageDraw = mock_pil_draw
        mock_pil_pkg.ImageFont = mock_pil_font

        with patch.dict(
            "sys.modules",
            {
                "PIL": mock_pil_pkg,
                "PIL.Image": mock_pil_image,
                "PIL.ImageDraw": mock_pil_draw,
                "PIL.ImageFont": mock_pil_font,
            },
        ):
            gen.generate_placeholder("test prompt", out)
        mock_img.save.assert_called_once_with(out)

    def test_placeholder_without_pillow(self, tmp_path):
        gen = self._make_gen()
        out = str(tmp_path / "placeholder.png")

        with patch.dict(
            "sys.modules",
            {
                "PIL": None,
                "PIL.Image": None,
                "PIL.ImageDraw": None,
                "PIL.ImageFont": None,
            },
        ):
            # Force ImportError path
            original_import = (
                __builtins__.__import__
                if hasattr(__builtins__, "__import__")
                else __import__
            )

            def mock_import(name, *args, **kwargs):
                if name == "PIL" or name.startswith("PIL."):
                    raise ImportError("no PIL")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                gen.generate_placeholder("test prompt", out)
        assert Path(out).exists()
        assert Path(out).read_bytes() == b""
