"""Sequential AI chunk execution for document feedback.

The coordinator owns retries, re-splitting and model switches; the feedback
system stays the source of reader, model and annotation operations.
"""

from __future__ import annotations

from collections import deque
import logging
import os
import time
from typing import Any, Callable, Dict, Iterable, List, Sequence, Tuple


logger = logging.getLogger("web.document_feedback")


def _preview(item: Dict[str, Any], *, chunk_index: int, global_chunk_index: int) -> Dict[str, Any] | None:
    original = str(item.get("原文片段") or item.get("原文") or item.get("original") or "").strip()
    proposed = str(item.get("修改建议") or item.get("改为") or item.get("修改后文本") or item.get("modified") or "").strip()
    if not original or not proposed:
        return None
    result = {
        "original_text": original,
        "proposed_text": proposed,
        "anchor_text": original,
        "chunk_index": chunk_index,
        "global_chunk_index": global_chunk_index,
        "source": "doc_review_stream",
        "preview_only": True,
    }
    reason = str(item.get("修改原因") or item.get("原因") or item.get("reason") or "").strip()
    if reason:
        result.update({"rationale": reason, "reason": reason})
    return result


def run_ai_chunk_queue(
    *,
    feedback_system: Any,
    file_path: str,
    doc_type: str,
    user_requirement: str,
    effective_model_id: str,
    formatted_content: str,
    reference_context: Any,
    chunks: Sequence[str],
    selected_chunk_items: Sequence[Tuple[int, str]],
    selected_content_chars: int,
    total_length: int,
    total_chunk_count: int,
    selected_chunk_start: int,
    selected_chunk_end: int,
    analyze_chunk: Callable[..., List[Dict[str, Any]] | None],
    emit_progress: Callable[..., None],
) -> Dict[str, Any]:
    """Run selected chunks serially, keeping a stable progress/result contract."""
    selected_model, available_models = feedback_system._select_best_model(effective_model_id)
    model_note = f"模型: {selected_model}"
    if selected_model != effective_model_id:
        model_note += f"（首选: {effective_model_id}，已自动降级）"
    model_table = feedback_system._format_model_table(available_models)

    if feedback_system.client and os.getenv("KOTO_DISABLE_AI") != "1":
        probed = feedback_system._probe_working_model(selected_model)
        if probed and probed != selected_model:
            logger.info("[DocumentFeedback] probe switch: %s -> %s", selected_model, probed)
            selected_model = probed
            model_note = f"模型: {selected_model}（首选 {effective_model_id} 不可用，已自动降级）"
        elif probed is None:
            logger.warning("[DocumentFeedback] no model passed the preflight probe")

    queue = deque(selected_chunk_items or enumerate(chunks, start=1))
    initial_count = len(queue)
    all_annotations: List[Dict[str, Any]] = []
    seen_texts = set()
    processed = fallback_chunk_count = ai_chunk_count = empty_result_fallback_chunk_count = 0
    last_api_error = ""
    model_switched = False
    start_time = time.time()

    while queue:
        global_chunk_index, chunk = queue.popleft()
        processed += 1
        current_total = processed + len(queue)

        def chunk_status(detail: str) -> None:
            if detail:
                emit_progress(max(0.05, processed - 0.95), initial_count, detail)

        annotations = analyze_chunk(
            chunk=chunk,
            doc_type=doc_type,
            user_requirement=user_requirement,
            model_id=selected_model,
            chunk_index=global_chunk_index,
            total_chunks=total_chunk_count or current_total,
            full_doc_context=formatted_content,
            reference_context=reference_context,
            max_retries=2,
            status_callback=chunk_status,
        )
        if annotations is None:
            if len(chunk) <= 800:
                return {"success": False, "error": f"分段内容过小仍失败（{len(chunk)}字符），请检查网络或API配置后重试", "file_path": file_path}
            sub_chunks = feedback_system._split_into_chunks_by_paragraphs(chunk, max(800, len(chunk) // 2))
            if len(sub_chunks) <= 1:
                return {"success": False, "error": f"分段拆分失败，无法继续处理（{len(chunk)}字符）", "file_path": file_path}
            for sub_chunk in reversed(sub_chunks):
                queue.appendleft((global_chunk_index, sub_chunk))
            continue

        empty_result_fallback = False
        if not annotations:
            annotations = feedback_system._fallback_annotations_from_chunk(chunk)
            if annotations:
                empty_result_fallback = True
                empty_result_fallback_chunk_count += 1

        fallback_items = [item for item in annotations if item.get("_koto_fallback_error")]
        if fallback_items:
            api_error = str(fallback_items[0].get("_koto_fallback_error") or "")
            last_api_error = last_api_error or api_error
            fallback_chunk_count += 1
            if not model_switched and any(item.get("_koto_503") for item in annotations):
                probed = feedback_system._probe_working_model(selected_model)
                if probed and probed != selected_model:
                    selected_model = probed
                    model_note = f"模型: {selected_model}（运行中自动从503过载模型切换）"
                    queue.appendleft((global_chunk_index, chunk))
                    processed -= 1
                    fallback_chunk_count -= 1
                    model_switched = True
                    continue
                model_switched = True
        elif annotations and not empty_result_fallback:
            ai_chunk_count += 1

        new_count = 0
        previews = []
        for item in annotations:
            item.pop("_koto_503", None)
            if item.pop("_koto_fallback_error", None):
                continue
            text = str(item.get("原文片段") or "").strip()
            if text and text not in seen_texts:
                seen_texts.add(text)
                all_annotations.append(item)
                new_count += 1
                preview = _preview(item, chunk_index=processed, global_chunk_index=global_chunk_index)
                if preview:
                    previews.append(preview)

        message = (
            f"已完成本批 {processed}/{initial_count} 段（全局 {global_chunk_index}/{total_chunk_count}，本段+{new_count}条，累计{len(all_annotations)}条）"
            if initial_count != (total_chunk_count or initial_count)
            else f"已完成 {processed}/{current_total} 段 (本段+{new_count}条，累计{len(all_annotations)}条)"
        )
        emit_progress(
            processed, initial_count, message,
            chunk_status="completed", chunk_index=processed, chunk_total=initial_count,
            global_chunk_index=global_chunk_index, global_chunk_total=total_chunk_count or current_total,
            added_count=new_count, total_annotations=len(all_annotations),
            partial_proposals=previews[:3], target_path=file_path,
        )

    elapsed = time.time() - start_time
    return {
        "success": True, "file_path": file_path, "annotations": all_annotations,
        "summary": (
            f"分段顺序处理（本批 {initial_count} 段，全局 {total_chunk_count or initial_count} 段），共生成{len(all_annotations)}条标注（耗时{elapsed:.1f}s）。"
            f"{' 其中 ' + str(empty_result_fallback_chunk_count) + ' 段在 AI 未给出修改时由本地规则补充。' if empty_result_fallback_chunk_count else ''}"
            f"{model_note}\n\n可用模型：\n{model_table}"
        ),
        "annotation_count": len(all_annotations), "chunks_processed": processed,
        "target_count": max(1, (selected_content_chars or total_length) // 1000 * 10),
        "total_chunk_count": total_chunk_count or initial_count, "selected_chunk_count": initial_count,
        "selected_chunk_start": selected_chunk_start, "selected_chunk_end": selected_chunk_end,
        "fallback_chunk_count": fallback_chunk_count, "ai_chunk_count": ai_chunk_count,
        "fallback_used": fallback_chunk_count > 0 and ai_chunk_count == 0,
        "partial_fallback": fallback_chunk_count > 0 and ai_chunk_count > 0,
        "empty_result_fallback_chunk_count": empty_result_fallback_chunk_count,
        "last_api_error": last_api_error,
    }
