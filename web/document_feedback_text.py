"""Text partitioning and reference-window helpers for document feedback."""

from __future__ import annotations

from typing import Any, List


def split_into_paragraph_chunks(formatted_content: str, max_chars: int) -> List[str]:
    """Partition content on paragraph boundaries without cutting paragraphs."""
    paragraphs = [paragraph for paragraph in formatted_content.split("\n\n") if paragraph.strip()]
    chunks: List[str] = []
    current: List[str] = []
    current_length = 0
    for paragraph in paragraphs:
        paragraph_length = len(paragraph) + 2
        if current and current_length + paragraph_length > max_chars:
            chunks.append("\n\n".join(current))
            current, current_length = [paragraph], paragraph_length
        else:
            current.append(paragraph)
            current_length += paragraph_length
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def select_reference_context(
    reference_context: Any, *, chunk_index: int = 1, total_chunks: int = 1
) -> str:
    """Select a nearby PDF reference window for the current document chunk."""
    if not reference_context:
        return ""
    if isinstance(reference_context, str):
        return reference_context.strip()
    if not isinstance(reference_context, list):
        return str(reference_context).strip()

    blocks = [str(item or "").strip() for item in reference_context if str(item or "").strip()]
    if len(blocks) <= 3:
        return "\n\n".join(blocks)
    total = max(1, int(total_chunks or 1))
    if total <= 1:
        return "\n\n".join(blocks[:3])
    index = max(1, int(chunk_index or 1))
    center = int(round(((index - 1) / max(1, total - 1)) * (len(blocks) - 1)))
    return "\n\n".join(blocks[max(0, center - 1) : min(len(blocks), center + 2)])
