# -*- coding: utf-8 -*-
"""Regression coverage for non-fatal PPTX geometry fallbacks."""
from __future__ import annotations

import logging


def test_pptx_geometry_logs_presentation_defaults_fallbacks(monkeypatch, caplog):
    """Visual-fidelity fallbacks must not disappear behind silent exceptions."""
    import pptx

    from app.core.file.parsers.pptx_geometry_parser import parse_pptx_geometry

    class BrokenPresentation:
        slide_width = 9144000
        slide_height = 6858000
        slides = ()

        @property
        def part(self):
            raise RuntimeError("broken theme")

        @property
        def element(self):
            raise RuntimeError("broken default text style")

        @property
        def slide_masters(self):
            raise RuntimeError("broken title text style")

    monkeypatch.setattr(pptx, "Presentation", lambda _path: BrokenPresentation())

    with caplog.at_level(logging.WARNING, logger="app.core.file.parsers.pptx_geometry_parser"):
        result = parse_pptx_geometry("broken-metadata.pptx")

    assert result["default_font_size_pt"] == 18.0
    assert result["default_title_font_size_pt"] == 36.0
    assert result["slides"] == []
    messages = [record.getMessage() for record in caplog.records]
    assert any("presentation theme" in message for message in messages)
    assert any("default font size" in message for message in messages)
    assert any("title font size" in message for message in messages)
