from web.document_feedback_text import (
    select_reference_context,
    split_into_paragraph_chunks,
)


def test_split_into_paragraph_chunks_preserves_paragraph_boundaries() -> None:
    chunks = split_into_paragraph_chunks("first\n\nsecond\n\nthird", 12)

    assert chunks == ["first", "second", "third"]


def test_select_reference_context_tracks_chunk_position() -> None:
    context = select_reference_context(
        ["page-1", "page-2", "page-3", "page-4", "page-5"],
        chunk_index=5,
        total_chunks=5,
    )

    assert "page-5" in context
    assert "page-1" not in context
