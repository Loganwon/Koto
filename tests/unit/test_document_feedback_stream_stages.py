"""Contracts for the extracted document-feedback stream boundary stages."""

from __future__ import annotations

from web.document_feedback_stream_stages import (
    build_complete_event,
    read_document_stage,
)


class _SuccessfulReader:
    def read_document(self, _file_path: str) -> dict:
        return {
            "success": True,
            "paragraphs": [{"text": "第一段"}, {"text": "second"}],
        }


class _FailedReader:
    def read_document(self, _file_path: str) -> dict:
        return {"success": False, "error": "损坏的文档"}


def test_read_document_stage_keeps_reading_progress_contract() -> None:
    document, paragraph_count, character_count, events = read_document_stage(
        _SuccessfulReader(),
        r"C:\\tmp\\draft.docx",
    )

    assert document is not None
    assert paragraph_count == 2
    assert character_count == len("第一段second")
    assert events == [
        {
            "stage": "reading",
            "progress": 5,
            "message": "📖 正在读取文档: draft.docx",
            "detail": "解析Word文件结构",
        },
        {
            "stage": "reading_complete",
            "progress": 10,
            "message": "✅ 文档读取完成",
            "detail": "2 段，9 字",
        },
    ]


def test_read_document_stage_converts_reader_failure_to_error_event() -> None:
    document, paragraph_count, character_count, events = read_document_stage(
        _FailedReader(),
        "draft.docx",
    )

    assert document is None
    assert (paragraph_count, character_count) == (0, 0)
    assert events[-1] == {
        "stage": "error",
        "progress": 0,
        "message": "❌ 读取失败: 损坏的文档",
        "detail": "",
    }


def test_build_complete_event_preserves_result_and_fallback_fields() -> None:
    event = build_complete_event(
        file_path="original.docx",
        revised_file="revised.docx",
        annotations=[{"id": 1}, {"id": 2}],
        applied=1,
        failed=1,
        edit_result={"success": True},
        analysis_result={
            "summary": "已处理",
            "partial_fallback": True,
            "fallback_chunk_count": 1,
        },
    )

    assert event["stage"] == "complete"
    assert event["detail"] == "修改位置: 1，定位失败: 1"
    assert event["result"] == {
        "success": True,
        "original_file": "original.docx",
        "revised_file": "revised.docx",
        "updated_in_place": True,
        "applied": 1,
        "failed": 1,
        "total": 2,
        "analysis_summary": "已处理",
        "fallback_used": False,
        "partial_fallback": True,
        "last_api_error": "",
        "fallback_chunk_count": 1,
        "ai_chunk_count": 0,
        "empty_result_fallback_chunk_count": 0,
    }
