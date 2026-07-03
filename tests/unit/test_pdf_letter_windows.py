# -*- coding: utf-8 -*-
from __future__ import annotations


def test_pdf_letter_window_overrides_conflicting_page_hint():
    from app.core.agent.file_task_contract import FileTaskFile, FileTaskRequest
    from app.core.agent.file_task_workflow_state import (
        large_file_windows,
        window_read_args_for_file,
    )

    files = [FileTaskFile(path="schiller.pdf", name="schiller.pdf", type="pdf")]
    request = FileTaskRequest.from_mapping(
        {
            "task": "Read Letter XI-XV, especially Letter XV; OpenSpace PDF pages 19-21.",
            "files": [{"path": "schiller.pdf", "name": "schiller.pdf", "type": "pdf"}],
        }
    )

    windows = large_file_windows(request, files, {})
    args = window_read_args_for_file(
        {"large_file_windows": windows},
        files[0],
        default_max_chars=12000,
    )

    assert windows[0]["unit"] == "pdf_letter"
    assert windows[0]["strategy"] == "letter_window"
    assert windows[0]["current"] == {"start": 11, "end": 15}
    assert args["window_unit"] == "pdf_letter"
    assert args["start"] == 11
    assert args["end"] == 15
    assert "start_page" not in args
    assert "end_page" not in args


def test_parse_file_to_text_pdf_letter_window_skips_table_of_contents(
    tmp_path, monkeypatch
):
    from app.core.agent import task_tools

    pdf_path = tmp_path / "schiller.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% fake test pdf\n")

    def fake_pdf_excerpt(
        path,
        *,
        max_chars,
        start_page=1,
        end_page=0,
        allow_full_fallback=True,
    ):
        if start_page == 6 and end_page == 6:
            return (
                "[Page 6]\n目 录\n"
                "第十一封信\n"
                "第十二封信\n"
                "第十三封信\n"
                "第十四封信\n"
                "第十五封信\n"
                "第十六封信"
            )
        if start_page == 63 and end_page == 63:
            return "[Page 63]\n第十一封信\n人格与状态。"
        if start_page == 87 and end_page == 87:
            return "[Page 87]\n第十六封信\n后续章节。"
        if start_page == 63 and end_page == 86:
            return (
                "[Page 63]\n第十一封信\n人格与状态。\n"
                "[Page 81]\n第十五封信\n"
                "游戏冲动的对象是活的形象。"
            )
        return ""

    monkeypatch.setattr(task_tools, "_read_pdf_excerpt", fake_pdf_excerpt)

    text = task_tools.parse_file_to_text(
        str(pdf_path),
        window_unit="pdf_letter",
        start=11,
        end=15,
        max_chars=4000,
    )

    assert "[PDF letter window: 11-15; resolved pages 63-86]" in text
    assert "第十一封信" in text
    assert "第十五封信" in text
    assert "游戏冲动" in text
