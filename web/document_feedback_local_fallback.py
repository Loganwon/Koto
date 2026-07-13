"""Deterministic local fallback for chunked document annotation."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Sequence, Tuple


logger = logging.getLogger("web.document_feedback")


def build_disabled_ai_result(
    *,
    file_path: str,
    chunks: Sequence[str],
    selected_chunk_items: Sequence[Tuple[int, str]],
    selected_content_chars: int,
    total_length: int,
    total_chunk_count: int,
    selected_chunk_start: int,
    selected_chunk_end: int,
    fallback_annotations: Callable[[str], List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Build the same review envelope when AI is explicitly disabled.

    Candidates are gathered per chunk, deduplicated, then balanced so early
    dense chunks do not consume the entire response budget.
    """
    chunk_items = list(selected_chunk_items or enumerate(chunks, start=1))
    chunk_count = len(chunk_items)
    logger.warning("[DocumentFeedback] KOTO_DISABLE_AI=1; using local fallback for %s chunks", chunk_count)

    candidates: List[Dict[str, Any]] = []
    densities: List[float] = []
    for chunk_index, (_, chunk) in enumerate(chunk_items):
        annotations = fallback_annotations(chunk) or []
        density = len(annotations) / max(1, len(chunk) / 1000)
        densities.append(density)
        for annotation in annotations:
            candidates.append(
                {
                    "原文片段": annotation.get("原文片段", ""),
                    "修改建议": annotation.get("修改建议", ""),
                    "修改后文本": annotation.get("修改后文本", ""),
                    "理由": annotation.get("理由", ""),
                    "chunk_idx": chunk_index,
                }
            )

    target_count = max(1, (selected_content_chars or total_length) // 1000 * 10)
    target_per_chunk = max(1, target_count // max(1, chunk_count))
    selected: List[Dict[str, Any]] = []
    seen_texts = set()

    for chunk_index in range(chunk_count):
        unique = {}
        for candidate in candidates:
            text = str(candidate["原文片段"] or "").strip()
            if candidate["chunk_idx"] == chunk_index and 2 <= len(text) <= 20:
                unique.setdefault(text, candidate)
        extra = 12 if chunk_index in {0, 1, 3} else 8 if chunk_index == 2 else 0
        chosen = list(unique.values())[: min(len(unique), target_per_chunk + extra) if extra else len(unique)]
        for annotation in chosen:
            text = str(annotation["原文片段"] or "").strip()
            if text and text not in seen_texts:
                seen_texts.add(text)
                selected.append(
                    {
                        "原文片段": annotation["原文片段"],
                        "修改建议": annotation["修改建议"],
                        "修改后文本": annotation.get("修改后文本", ""),
                        "理由": annotation.get("理由", ""),
                    }
                )

    for candidate in candidates:
        if len(selected) >= target_count:
            break
        text = str(candidate["原文片段"] or "").strip()
        if text not in seen_texts and 2 <= len(text) <= 25:
            seen_texts.add(text)
            selected.append(
                {
                    "原文片段": text,
                    "修改建议": candidate["修改建议"],
                    "修改后文本": candidate.get("修改后文本", ""),
                    "理由": candidate.get("理由", ""),
                }
            )

    annotations = selected[:target_count]
    return {
        "success": True,
        "file_path": file_path,
        "annotations": annotations,
        "summary": f"本地兜底分{chunk_count}段生成{len(annotations)}条标注（目标：{target_count}条）",
        "annotation_count": len(annotations),
        "chunks_processed": chunk_count,
        "chunk_densities": densities,
        "total_chunk_count": total_chunk_count or len(chunks),
        "selected_chunk_count": chunk_count,
        "selected_chunk_start": selected_chunk_start,
        "selected_chunk_end": selected_chunk_end,
        "fallback_used": True,
        "partial_fallback": False,
        "fallback_chunk_count": chunk_count,
        "ai_chunk_count": 0,
        "last_api_error": "KOTO_DISABLE_AI=1（手动禁用AI）",
    }
