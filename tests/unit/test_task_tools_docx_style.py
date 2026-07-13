# -*- coding: utf-8 -*-
from __future__ import annotations

import json


def test_apply_docx_style_returns_user_visible_fallback_warning():
    from app.core.agent.task_tools_docx_style import apply_docx_style

    class MissingStyleTarget:
        @property
        def style(self):
            return "Normal"

        @style.setter
        def style(self, _value):
            raise KeyError("style is not defined")

    warning = apply_docx_style(MissingStyleTarget(), "Caption")

    assert "Caption" in warning
    assert "KeyError" in warning


def test_write_docx_content_reports_unknown_style_without_losing_content(tmp_path):
    from docx import Document

    from app.core.agent.task_tools import write_docx_content

    target = tmp_path / "styled.docx"
    result = json.loads(
        write_docx_content(
            str(target),
            [{"text": "保留正文", "style": "Missing Koto Style"}],
        )
    )

    assert result["paragraphs_written"] == 1
    assert "Missing Koto Style" in result["warning"]
    assert Document(target).paragraphs[-1].text == "保留正文"
