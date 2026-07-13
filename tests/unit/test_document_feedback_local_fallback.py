from web.document_feedback_local_fallback import build_disabled_ai_result


def test_local_fallback_count_matches_capped_annotation_payload() -> None:
    result = build_disabled_ai_result(
        file_path="/tmp/example.docx",
        chunks=["x" * 100],
        selected_chunk_items=[(1, "x" * 100)],
        selected_content_chars=100,
        total_length=100,
        total_chunk_count=1,
        selected_chunk_start=1,
        selected_chunk_end=1,
        fallback_annotations=lambda _chunk: [
            {"原文片段": "第一处", "修改建议": "修改一"},
            {"原文片段": "第二处", "修改建议": "修改二"},
        ],
    )

    assert len(result["annotations"]) == 1
    assert result["annotation_count"] == len(result["annotations"])
    assert result["fallback_used"] is True
