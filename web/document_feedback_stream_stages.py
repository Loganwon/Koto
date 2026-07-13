"""Pure event-stage helpers for document-feedback streaming."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple


def read_document_stage(
    reader: Any,
    file_path: str,
) -> Tuple[Dict[str, Any] | None, int, int, List[Dict[str, Any]]]:
    events: List[Dict[str, Any]] = [
        {
            "stage": "reading",
            "progress": 5,
            "message": f"📖 正在读取文档: {os.path.basename(file_path)}",
            "detail": "解析Word文件结构",
        }
    ]
    try:
        document = reader.read_document(file_path)
        if not document.get("success"):
            events.append(
                {
                    "stage": "error",
                    "progress": 0,
                    "message": f'❌ 读取失败: {document.get("error")}',
                    "detail": "",
                }
            )
            return None, 0, 0, events
    except Exception as exc:
        events.append(
            {
                "stage": "error",
                "progress": 0,
                "message": f"❌ 读取错误: {str(exc)[:100]}",
                "detail": "",
            }
        )
        return None, 0, 0, events
    paragraphs = list(document.get("paragraphs", []) or [])
    total_chars = sum(
        len(item.get("text", "")) for item in paragraphs if isinstance(item, dict)
    )
    events.append(
        {
            "stage": "reading_complete",
            "progress": 10,
            "message": "✅ 文档读取完成",
            "detail": f"{len(paragraphs)} 段，{total_chars} 字",
        }
    )
    return document, len(paragraphs), total_chars, events


def build_complete_event(
    *,
    file_path: str,
    revised_file: str,
    annotations: List[Dict[str, Any]],
    applied: int,
    failed: int,
    edit_result: Dict[str, Any],
    analysis_result: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "stage": "complete",
        "progress": 100,
        "message": "✅ 文档修改完成！",
        "detail": f"修改位置: {applied}，定位失败: {failed}",
        "result": {
            "success": edit_result.get("success", False),
            "original_file": file_path,
            "revised_file": revised_file,
            "updated_in_place": True,
            "applied": applied,
            "failed": failed,
            "total": len(annotations),
            "analysis_summary": analysis_result.get("summary"),
            "fallback_used": analysis_result.get("fallback_used", False),
            "partial_fallback": analysis_result.get("partial_fallback", False),
            "last_api_error": analysis_result.get("last_api_error", ""),
            "fallback_chunk_count": analysis_result.get("fallback_chunk_count", 0),
            "ai_chunk_count": analysis_result.get("ai_chunk_count", 0),
            "empty_result_fallback_chunk_count": analysis_result.get(
                "empty_result_fallback_chunk_count", 0
            ),
        },
    }
