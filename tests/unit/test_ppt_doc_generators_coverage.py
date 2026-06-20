#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Comprehensive tests for PPT generation, document generation,
speech transcriber, and file service modules.
"""

import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, PropertyMock, patch

import pytest

@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="koto_gen_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


# ===========================================================================
# 1. PPTGenerator
# ===========================================================================


@pytest.mark.unit
class TestPptGenerator:
    """Tests for web.ppt_generator.PPTGenerator"""

    def _make_gen(self, theme="business"):
        with patch("web.ppt_themes.get_theme", return_value=None):
            from web.ppt_generator import PPTGenerator

            return PPTGenerator(theme=theme)

    # -- init / theme -------------------------------------------------

    def test_init_default_theme(self):
        gen = self._make_gen()
        assert gen.theme == "business"
        assert "primary" in gen.colors

    def test_init_tech_theme(self):
        gen = self._make_gen("tech")
        assert gen.theme == "tech"

    def test_init_unknown_theme_falls_back(self):
        gen = self._make_gen("nonexistent")
        # Falls back to business via THEMES dict
        assert "primary" in gen.colors

    # -- _clean_markdown -----------------------------------------------

    def test_clean_markdown_removes_heading_marks(self):
        from web.ppt_generator import PPTGenerator

        assert PPTGenerator._clean_markdown("### Title text") == "Title text"

    def test_clean_markdown_strips_bold_when_requested(self):
        from web.ppt_generator import PPTGenerator

        result = PPTGenerator._clean_markdown("**bold text**", strip_bold=True)
        assert "**" not in result
        assert "bold text" in result

    def test_clean_markdown_preserves_bold_when_not_requested(self):
        from web.ppt_generator import PPTGenerator

        result = PPTGenerator._clean_markdown("**bold text**", strip_bold=False)
        assert "**bold text**" in result

    def test_clean_markdown_removes_bullet_markers(self):
        from web.ppt_generator import PPTGenerator

        assert PPTGenerator._clean_markdown("- list item").strip() == "list item"

    def test_clean_markdown_removes_inline_code(self):
        from web.ppt_generator import PPTGenerator

        assert PPTGenerator._clean_markdown("`code`") == "code"

    def test_clean_markdown_strips_links(self):
        from web.ppt_generator import PPTGenerator

        result = PPTGenerator._clean_markdown("[click](http://example.com)")
        assert "click" in result
        assert "http" not in result

    def test_clean_markdown_removes_strikethrough(self):
        from web.ppt_generator import PPTGenerator

        assert PPTGenerator._clean_markdown("~~old~~") == "old"

    def test_clean_markdown_handles_empty_string(self):
        from web.ppt_generator import PPTGenerator

        assert PPTGenerator._clean_markdown("") == ""

    def test_clean_markdown_handles_none(self):
        from web.ppt_generator import PPTGenerator

        assert PPTGenerator._clean_markdown(None) is None

    def test_clean_markdown_removes_ai_patterns(self):
        from web.ppt_generator import PPTGenerator

        result = PPTGenerator._clean_markdown("Sure! Here is something: real content")
        assert "real content" in result

    # -- generate_from_outline (mocked pptx) ---------------------------

    def test_generate_from_outline_creates_file(self, tmp_dir):
        gen = self._make_gen()
        output = os.path.join(tmp_dir, "test.pptx")
        outline = [
            {"title": "Slide 1", "type": "detail", "points": ["Point A", "Point B"]},
        ]
        result = gen.generate_from_outline(
            title="Test Deck",
            outline=outline,
            output_path=output,
            enable_ai_images=False,
        )
        assert os.path.exists(output)
        assert result["slide_count"] >= 2  # title + 1 content

    def test_generate_from_outline_with_divider(self, tmp_dir):
        gen = self._make_gen()
        output = os.path.join(tmp_dir, "divider.pptx")
        outline = [
            {"title": "Section 1", "type": "divider", "description": "Intro"},
            {"title": "Content", "type": "detail", "points": ["A"]},
        ]
        result = gen.generate_from_outline(
            "Deck", outline, output, enable_ai_images=False
        )
        assert result["slide_count"] >= 3

    def test_generate_from_outline_comparison(self, tmp_dir):
        gen = self._make_gen()
        output = os.path.join(tmp_dir, "compare.pptx")
        outline = [
            {
                "title": "Compare",
                "type": "comparison",
                "left": {"title": "A", "points": ["a1"]},
                "right": {"title": "B", "points": ["b1"]},
            },
        ]
        result = gen.generate_from_outline(
            "Deck", outline, output, enable_ai_images=False
        )
        assert result["slide_count"] >= 2

    def test_generate_from_outline_overview(self, tmp_dir):
        gen = self._make_gen()
        output = os.path.join(tmp_dir, "overview.pptx")
        outline = [
            {
                "title": "Overview",
                "type": "overview",
                "subsections": [
                    {"title": "Sub1", "points": ["p1"]},
                    {"title": "Sub2", "points": ["p2"]},
                ],
            },
        ]
        result = gen.generate_from_outline(
            "Deck", outline, output, enable_ai_images=False
        )
        assert result["slide_count"] >= 2

    def test_generate_from_outline_highlight(self, tmp_dir):
        gen = self._make_gen()
        output = os.path.join(tmp_dir, "highlight.pptx")
        outline = [
            {"title": "Key Fact", "type": "highlight", "points": ["Fact 1"]},
        ]
        result = gen.generate_from_outline(
            "Deck", outline, output, enable_ai_images=False
        )
        assert result["slide_count"] >= 2


# ===========================================================================
# 2. DocumentGenerator (save_docx, helper functions)
# ===========================================================================


@pytest.mark.unit
class TestDocumentGenerator:
    """Tests for web.document_generator module-level functions."""

    # -- helper functions ------------------------------------------------

    def test_split_lines(self):
        from web.document_generator import _split_lines

        lines = _split_lines("line1\nline2  \nline3")
        assert lines == ["line1", "line2", "line3"]

    def test_is_cjk_char_true(self):
        from web.document_generator import _is_cjk_char

        assert _is_cjk_char("中") is True

    def test_is_cjk_char_false(self):
        from web.document_generator import _is_cjk_char

        assert _is_cjk_char("A") is False

    def test_join_text_lines_cjk_no_space(self):
        from web.document_generator import _join_text_lines

        result = _join_text_lines("中文", "内容")
        assert result == "中文内容"

    def test_join_text_lines_latin_has_space(self):
        from web.document_generator import _join_text_lines

        result = _join_text_lines("hello", "world")
        assert result == "hello world"

    def test_join_text_lines_empty_prev(self):
        from web.document_generator import _join_text_lines

        assert _join_text_lines("", "text") == "text"

    def test_join_text_lines_empty_curr(self):
        from web.document_generator import _join_text_lines

        assert _join_text_lines("text", "") == "text"

    def test_normalize_markdown_lines_code_block(self):
        from web.document_generator import _normalize_markdown_lines

        text = "before\n```\ncode here\n```\nafter"
        lines = _normalize_markdown_lines(text)
        assert "```" in lines
        assert "code here" in lines

    def test_normalize_markdown_lines_heading(self):
        from web.document_generator import _normalize_markdown_lines

        text = "# Heading\nparagraph text"
        lines = _normalize_markdown_lines(text)
        assert any("# Heading" in l for l in lines)

    def test_normalize_markdown_collapses_blank_lines(self):
        from web.document_generator import _normalize_markdown_lines

        text = "line1\n\n\n\nline2"
        lines = _normalize_markdown_lines(text)
        # Should have at most one consecutive blank between content
        blank_run = 0
        max_blank = 0
        for l in lines:
            if not l.strip():
                blank_run += 1
                max_blank = max(max_blank, blank_run)
            else:
                blank_run = 0
        assert max_blank <= 1

    def test_extract_title_from_content_h1(self):
        from web.document_generator import _extract_title_from_content

        assert _extract_title_from_content("# My Title\ncontent") == "My Title"

    def test_extract_title_from_content_h2(self):
        from web.document_generator import _extract_title_from_content

        assert _extract_title_from_content("## Sub Title\ncontent") == "Sub Title"

    def test_extract_title_returns_none_for_plain(self):
        from web.document_generator import _extract_title_from_content

        assert _extract_title_from_content("just plain text") is None

    def test_sanitize_filename(self):
        from web.document_generator import _sanitize_filename

        result = _sanitize_filename('My Doc: "Test" / Report')
        assert ":" not in result
        assert '"' not in result
        assert "/" not in result

    def test_sanitize_filename_length_limit(self):
        from web.document_generator import _sanitize_filename

        long_name = "a" * 100
        assert len(_sanitize_filename(long_name)) <= 50

    # -- save_docx -------------------------------------------------------

    def test_save_docx_creates_file(self, tmp_dir):
        from web.document_generator import save_docx

        path = save_docx(
            "# Test\nHello world",
            title="TestDoc",
            output_dir=tmp_dir,
            filename="test_output",
        )
        assert os.path.exists(path)
        assert path.endswith(".docx")

    def test_save_docx_with_bullet_list(self, tmp_dir):
        from web.document_generator import save_docx

        md = "# Title\n- Item 1\n- Item 2\n- Item 3"
        path = save_docx(md, title="Bullets", output_dir=tmp_dir, filename="bullets")
        assert os.path.exists(path)

    def test_save_docx_with_code_block(self, tmp_dir):
        from web.document_generator import save_docx

        md = "# Code\n```python\nprint('hi')\n```\nEnd."
        path = save_docx(md, title="Code", output_dir=tmp_dir, filename="code")
        assert os.path.exists(path)

    def test_save_docx_auto_title_extraction(self, tmp_dir):
        from web.document_generator import save_docx

        md = "# Auto Title\nSome body"
        path = save_docx(md, title=None, output_dir=tmp_dir, filename="auto_title")
        assert os.path.exists(path)

    def test_save_docx_with_bold_italic(self, tmp_dir):
        from web.document_generator import save_docx

        md = "Normal **bold** and *italic* text"
        path = save_docx(md, title="Fmt", output_dir=tmp_dir, filename="fmt")
        assert os.path.exists(path)

    def test_save_docx_with_numbered_list(self, tmp_dir):
        from web.document_generator import save_docx

        md = "# Lists\n1. First\n2. Second"
        path = save_docx(md, title="Nums", output_dir=tmp_dir, filename="nums")
        assert os.path.exists(path)

    def test_save_docx_with_blockquote(self, tmp_dir):
        from web.document_generator import save_docx

        md = "> This is a quote\nNormal text"
        path = save_docx(md, title="Quote", output_dir=tmp_dir, filename="quote")
        assert os.path.exists(path)

    def test_save_docx_with_separator(self, tmp_dir):
        from web.document_generator import save_docx

        md = "Before\n---\nAfter"
        path = save_docx(md, title="Sep", output_dir=tmp_dir, filename="sep")
        assert os.path.exists(path)


        report_path = path.replace(".json", "_report.txt")
        assert os.path.exists(report_path)


# ===========================================================================
# 4. SpeechTranscriber
# ===========================================================================


@pytest.mark.unit
class TestSpeechTranscriber:
    """Retired speech transcriber stays removed."""

    def test_module_removed(self):
        assert not Path("web", "speech_" + "transcriber.py").exists()


# ===========================================================================
# 5. FileService
# ===========================================================================


@pytest.mark.unit
class TestFileService:
    """Tests for app.core.services.file_service.FileService"""

    def _make_svc(self, tmp_dir):
        from app.core.services.file_service import FileService

        return FileService(workspace_dir=tmp_dir, backup_enabled=True)

    # -- is_safe_path --------------------------------------------------

    def test_safe_path_normal(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        assert svc.is_safe_path(os.path.join(tmp_dir, "file.txt")) is True

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
    def test_safe_path_rejects_system32(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        assert svc.is_safe_path(r"C:\Windows\System32\evil.txt") is False

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
    def test_safe_path_rejects_program_files(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        assert svc.is_safe_path(r"C:\Program Files\app\file.dll") is False

    # -- read_file -----------------------------------------------------

    def test_read_file_success(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        fp = os.path.join(tmp_dir, "hello.txt")
        Path(fp).write_text("hello content", encoding="utf-8")
        result = svc.read_file(fp)
        assert result["success"] is True
        assert result["content"] == "hello content"
        assert result["encoding"] == "utf-8"

    def test_read_file_not_found(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        result = svc.read_file(os.path.join(tmp_dir, "nope.txt"))
        assert result["success"] is False

    def test_read_file_max_chars(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        fp = os.path.join(tmp_dir, "long.txt")
        Path(fp).write_text("x" * 500, encoding="utf-8")
        result = svc.read_file(fp, max_chars=100)
        assert result["success"] is True
        assert "已截断" in result["content"]

    # -- write_file ----------------------------------------------------

    def test_write_file_success(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        fp = os.path.join(tmp_dir, "out.txt")
        result = svc.write_file(fp, "data")
        assert result["success"] is True
        assert Path(fp).read_text() == "data"

    def test_write_file_creates_parent_dirs(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        fp = os.path.join(tmp_dir, "sub", "dir", "file.txt")
        result = svc.write_file(fp, "nested")
        assert result["success"] is True
        assert os.path.exists(fp)

    def test_write_file_creates_backup(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        fp = os.path.join(tmp_dir, "bak.txt")
        Path(fp).write_text("original", encoding="utf-8")
        result = svc.write_file(fp, "overwritten")
        assert result["success"] is True
        assert result.get("backup") is not None

    # -- append_text ---------------------------------------------------

    def test_append_text(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        fp = os.path.join(tmp_dir, "append.txt")
        Path(fp).write_text("line1", encoding="utf-8")
        svc.append_text(fp, "line2")
        content = Path(fp).read_text(encoding="utf-8")
        assert "line1" in content
        assert "line2" in content

    # -- replace_text --------------------------------------------------

    def test_replace_text(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        fp = os.path.join(tmp_dir, "rep.txt")
        Path(fp).write_text("foo bar foo", encoding="utf-8")
        result = svc.replace_text(fp, "foo", "baz")
        assert result["success"] is True
        assert result["replacements"] == 2
        assert "baz" in Path(fp).read_text(encoding="utf-8")

    def test_replace_text_not_found(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        fp = os.path.join(tmp_dir, "rep2.txt")
        Path(fp).write_text("hello", encoding="utf-8")
        result = svc.replace_text(fp, "xyz", "abc")
        assert result["success"] is False

    # -- delete_file ---------------------------------------------------

    def test_delete_file(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        fp = os.path.join(tmp_dir, "del.txt")
        Path(fp).write_text("bye", encoding="utf-8")
        result = svc.delete_file(fp)
        assert result["success"] is True
        assert not os.path.exists(fp)

    def test_delete_file_not_found(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        result = svc.delete_file(os.path.join(tmp_dir, "ghost.txt"))
        assert result["success"] is False

    # -- copy_file / move_file -----------------------------------------

    def test_copy_file(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        src = os.path.join(tmp_dir, "src.txt")
        dst = os.path.join(tmp_dir, "dst.txt")
        Path(src).write_text("copy me", encoding="utf-8")
        result = svc.copy_file(src, dst)
        assert result["success"] is True
        assert Path(dst).read_text(encoding="utf-8") == "copy me"

    def test_copy_file_no_overwrite(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        src = os.path.join(tmp_dir, "a.txt")
        dst = os.path.join(tmp_dir, "b.txt")
        Path(src).write_text("a", encoding="utf-8")
        Path(dst).write_text("b", encoding="utf-8")
        result = svc.copy_file(src, dst, overwrite=False)
        assert result["success"] is False

    def test_move_file(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        src = os.path.join(tmp_dir, "mv_src.txt")
        dst = os.path.join(tmp_dir, "mv_dst.txt")
        Path(src).write_text("moving", encoding="utf-8")
        result = svc.move_file(src, dst)
        assert result["success"] is True
        assert not os.path.exists(src)
        assert os.path.exists(dst)

    # -- rename_file ---------------------------------------------------

    def test_rename_file(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        fp = os.path.join(tmp_dir, "old.txt")
        Path(fp).write_text("rename", encoding="utf-8")
        result = svc.rename_file(fp, "new.txt")
        assert result["success"] is True
        assert os.path.exists(os.path.join(tmp_dir, "new.txt"))

    def test_rename_rejects_path_separator(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        fp = os.path.join(tmp_dir, "f.txt")
        Path(fp).write_text("x", encoding="utf-8")
        result = svc.rename_file(fp, "sub/new.txt")
        assert result["success"] is False

    # -- get_file_info -------------------------------------------------

    def test_get_file_info(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        fp = os.path.join(tmp_dir, "info.txt")
        Path(fp).write_text("info", encoding="utf-8")
        result = svc.get_file_info(fp)
        assert result["success"] is True
        assert result["is_file"] is True
        assert result["size"] > 0

    def test_get_file_info_dir(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        result = svc.get_file_info(tmp_dir)
        assert result["success"] is True
        assert result["is_dir"] is True

    def test_get_file_info_not_found(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        result = svc.get_file_info(os.path.join(tmp_dir, "missing"))
        assert result["success"] is False

    # -- list_directory ------------------------------------------------

    def test_list_directory(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        Path(os.path.join(tmp_dir, "a.txt")).write_text("a", encoding="utf-8")
        Path(os.path.join(tmp_dir, "b.txt")).write_text("b", encoding="utf-8")
        result = svc.list_directory(tmp_dir)
        assert result["success"] is True
        assert result["count"] >= 2

    def test_list_directory_not_found(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        result = svc.list_directory(os.path.join(tmp_dir, "nope"))
        assert result["success"] is False

    # -- create_directory ----------------------------------------------

    def test_create_directory(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        new_dir = os.path.join(tmp_dir, "new_sub")
        result = svc.create_directory(new_dir)
        assert result["success"] is True
        assert os.path.isdir(new_dir)

    # -- _human_size ---------------------------------------------------

    def test_human_size_bytes(self, tmp_dir):
        from app.core.services.file_service import FileService

        assert "B" in FileService._human_size(500)

    def test_human_size_kb(self, tmp_dir):
        from app.core.services.file_service import FileService

        assert "KB" in FileService._human_size(2048)

    def test_human_size_mb(self, tmp_dir):
        from app.core.services.file_service import FileService

        assert "MB" in FileService._human_size(2 * 1024 * 1024)

    # -- patch_file ----------------------------------------------------

    def test_patch_file(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        fp = os.path.join(tmp_dir, "patch.txt")
        Path(fp).write_text("alpha beta gamma", encoding="utf-8")
        result = svc.patch_file(
            fp,
            [
                {"old": "alpha", "new": "ALPHA"},
                {"old": "gamma", "new": "GAMMA"},
            ],
        )
        assert result["success"] is True
        assert result["total_replacements"] == 2
        content = Path(fp).read_text(encoding="utf-8")
        assert "ALPHA" in content and "GAMMA" in content

    def test_patch_file_not_found_items(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        fp = os.path.join(tmp_dir, "patch2.txt")
        Path(fp).write_text("hello", encoding="utf-8")
        result = svc.patch_file(fp, [{"old": "zzz", "new": "aaa"}])
        assert result["success"] is False

    # -- insert_line / delete_lines ------------------------------------

    def test_insert_line_after(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        fp = os.path.join(tmp_dir, "ins.txt")
        Path(fp).write_text("line1\nline2\n", encoding="utf-8")
        result = svc.insert_line(fp, 1, "inserted")
        assert result["success"] is True
        lines = Path(fp).read_text(encoding="utf-8").splitlines()
        assert lines[1] == "inserted"

    def test_delete_lines(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        fp = os.path.join(tmp_dir, "del_lines.txt")
        Path(fp).write_text("a\nb\nc\n", encoding="utf-8")
        result = svc.delete_lines(fp, 2, 2)
        assert result["success"] is True
        assert result["deleted_lines"] == 1
        content = Path(fp).read_text(encoding="utf-8")
        assert "b" not in content

    # -- list_backups --------------------------------------------------

    def test_list_backups_empty(self, tmp_dir):
        svc = self._make_svc(tmp_dir)
        result = svc.list_backups()
        assert result["success"] is True
        assert result["count"] == 0
