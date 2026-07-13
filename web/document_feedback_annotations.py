"""Small, dependency-free normalization helpers for document AI annotations."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List


logger = logging.getLogger("web.document_feedback")


def _clean_original(text: str) -> str:
    """Remove accidental Markdown from an annotation anchor."""
    text = re.sub(r"^#{1,6}\s+", "", text.strip())
    text = re.sub(r"^[-*]\s+", "", text)
    text = re.sub(r"^>\s*", "", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"\s*←\s*\[此段落有格式变化\]", "", text)
    return re.sub(r"\[(.+?)\]\(颜色:[0-9A-Fa-f]+\)", r"\1", text).strip()


def _normalize_annotation(item: Any) -> Dict[str, str] | None:
    if not isinstance(item, dict):
        return None

    original = item.get("原文片段") or item.get("原文") or item.get("original")
    modified = (
        item.get("修改建议")
        or item.get("改为")
        or item.get("修改后文本")
        or item.get("modified")
    )
    reason = item.get("修改原因") or item.get("原因") or item.get("reason")
    if not original or not modified:
        return None

    cleaned_original = _clean_original(str(original))
    if not cleaned_original:
        return None
    if len(cleaned_original) > 60:
        logger.debug(
            "[DocumentFeedback] 过滤超长原文(%s字): %s...",
            len(cleaned_original),
            cleaned_original[:30],
        )
        shortened = re.split(r"[，。；！？,;!?]", cleaned_original)[0].strip()
        if not 4 <= len(shortened) <= 40:
            return None
        cleaned_original = shortened

    annotation = {"原文片段": cleaned_original, "修改建议": str(modified).strip()}
    if reason:
        annotation["修改原因"] = str(reason).strip()
    return annotation


def parse_annotation_response(ai_response: str) -> List[Dict[str, str]]:
    """Parse supported AI response envelopes into safe, short annotations."""
    try:
        fenced = re.search(r"```json\s*(\[.*?\])\s*```", ai_response, re.DOTALL)
        array = fenced or re.search(r"\[.*\]", ai_response, re.DOTALL)
        data = json.loads(array.group(1) if fenced else array.group(0) if array else ai_response)

        if isinstance(data, list):
            return [annotation for item in data if (annotation := _normalize_annotation(item))]

        if isinstance(data, dict):
            for key in ("annotations", "modifications", "suggestions"):
                items = data.get(key)
                if isinstance(items, list):
                    annotations = [
                        annotation for item in items if (annotation := _normalize_annotation(item))
                    ]
                    if annotations:
                        return annotations
        return []
    except Exception as exc:
        logger.info("[DocumentFeedback] 解析标注失败: %s", exc)
        return []
