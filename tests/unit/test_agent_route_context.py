# -*- coding: utf-8 -*-
from __future__ import annotations


def test_chat_system_context_preserves_explicit_selection_metadata() -> None:
    from app.api.agent_routes import _build_chat_system_context

    result = _build_chat_system_context(
        message="只总结选区",
        history=[],
        session_id="session-1",
        context_files=[],
        file_context={
            "active_file": "workspace/report.xlsx",
            "selection": "产品\t销量\nA\t10",
            "selection_kind": "xlsx-range",
            "selection_source": "report.xlsx",
            "selection_meta": {
                "sheetName": "Q1",
                "rangeA1": "A1:B2",
                "rows": 2,
                "cols": 2,
            },
        },
    )
    context = result[1]

    assert "优先使用用户明确提供的选区和附加文件" in context
    assert "选区类型: xlsx-range" in context
    assert "选区来源: report.xlsx" in context
    assert "选区元信息: sheetName=Q1, rangeA1=A1:B2, rows=2, cols=2" in context
    assert "用户明确选中的内容:\n产品\t销量\nA\t10" in context
    assert "用户选中的文本" not in context
