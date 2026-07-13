from web.document_feedback_result import collect_annotation_loop_result


def test_collect_result_returns_complete_payload() -> None:
    result = collect_annotation_loop_result(
        [{"stage": "complete", "result": {"success": True, "applied": 2}}],
        file_path="/tmp/source.docx",
    )

    assert result == {"success": True, "applied": 2}


def test_collect_result_preserves_cancelled_contract() -> None:
    result = collect_annotation_loop_result(
        [{"stage": "cancelled", "message": "用户取消"}],
        file_path="/tmp/source.docx",
    )

    assert result["cancelled"] is True
    assert result["original_file"] == "/tmp/source.docx"
