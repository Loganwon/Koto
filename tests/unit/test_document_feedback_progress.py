from web.document_feedback_progress import (
    build_analysis_progress_event,
    build_apply_progress_event,
)


def test_analysis_progress_keeps_partial_proposals_and_chunk_metadata() -> None:
    event = build_analysis_progress_event(
        2,
        4,
        "已完成",
        {"chunk_status": "completed", "chunk_index": 2, "partial_proposals": [{"anchor_text": "原文"}]},
    )

    assert event["progress"] == 32
    assert event["chunk_index"] == 2
    assert event["partial_proposals"] == [{"anchor_text": "原文"}]


def test_apply_progress_exposes_in_place_file_update() -> None:
    event = build_apply_progress_event(
        1, 2, "saved", "已写回", {"file_updated": True, "applied": 1}, revised_file="/tmp/revised.docx"
    )

    assert event["stage"] == "applying"
    assert event["path"] == "/tmp/revised.docx"
    assert event["updated_in_place"] is True
