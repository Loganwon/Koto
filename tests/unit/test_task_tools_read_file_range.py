# -*- coding: utf-8 -*-
# Copyright (C) 2024-2026 Koto AI. All rights reserved.
from __future__ import annotations


def test_read_file_range_accepts_string_line_numbers(tmp_path, monkeypatch):
    from app.core.agent import task_tools

    source = tmp_path / "sample.txt"
    source.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    monkeypatch.setattr(task_tools, "_resolve_path", lambda _path: str(source))

    assert task_tools.read_file_range("sample.txt", "2", "3") == "two\nthree\n"


def test_read_file_range_normalizes_invalid_or_reversed_bounds(tmp_path, monkeypatch):
    from app.core.agent import task_tools

    source = tmp_path / "sample.txt"
    source.write_text("one\ntwo\nthree\n", encoding="utf-8")
    monkeypatch.setattr(task_tools, "_resolve_path", lambda _path: str(source))

    assert task_tools.read_file_range("sample.txt", "bad", "1") == "one\n"
    assert task_tools.read_file_range("sample.txt", "3", "2") == "three\n"
