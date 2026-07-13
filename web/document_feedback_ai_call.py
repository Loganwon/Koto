"""Bounded AI-call and response-validation helpers for document feedback."""

from __future__ import annotations

import logging
import re
import threading
from typing import Any, Callable, Dict, List, Tuple


logger = logging.getLogger("web.document_feedback")


def call_with_timeout(
    call_model: Callable[[str], Any], contents: str, timeout_seconds: int
) -> Tuple[Any | None, Exception | None]:
    """Call a provider without allowing one chunk to block the review forever."""
    result: Dict[str, Any] = {"response": None, "error": None}

    def runner() -> None:
        try:
            result["response"] = call_model(contents)
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    if thread.is_alive():
        return None, TimeoutError(f"Chunk timeout after {timeout_seconds}s")
    return result["response"], result["error"]


def filter_unanchored_annotations(
    chunk: str, annotations: List[Dict[str, str]]
) -> List[Dict[str, str]]:
    """Drop only suggestions whose source anchor is absent from the chunk."""
    try:
        from web.document_validator import DocumentValidator

        validation = DocumentValidator.validate_modifications(chunk, annotations)
        if validation.get("risk_level") != "HIGH":
            return annotations
        rejected = {
            int(match.group(1)) - 1
            for issue in validation.get("issues", [])
            if (match := re.match(r"#(\d+):\s*原文未找到", str(issue)))
        }
        return [item for index, item in enumerate(annotations) if index not in rejected]
    except Exception as exc:
        logger.warning("[DocumentFeedback] annotation anchor validation skipped: %s", exc)
        return annotations
