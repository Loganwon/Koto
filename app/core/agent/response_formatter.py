"""Proposal-building helpers for document agent executors."""

from __future__ import annotations

import re
from typing import Any


_PROPOSAL_NOTE_PREAMBLE_RE = re.compile(
    r"^(?:以下|下面|这是|如下)(?:是|为)?.{0,20}(?:润色|翻译|改写|修改|修正|优化|版本|结果|文本|内容).{0,10}[：:]\s*",
    re.IGNORECASE,
)


def _normalize_proposal_note_text(text: Any) -> str:
    plain = re.sub(r"<[^>]+>", " ", str(text or ""))
    plain = _PROPOSAL_NOTE_PREAMBLE_RE.sub("", plain).strip()
    return re.sub(r"\s+", "", plain).lower()


class ResponseFormatter:
    """Turn document tool calls into frontend proposal records."""

    @staticmethod
    def build_proposals(
        selection: str,
        tool_calls: list[dict[str, Any]],
        clean_text: str,
    ) -> list[dict[str, Any]]:
        proposed_values = [
            tool_call.get("value", "")
            for tool_call in tool_calls
            if tool_call.get("value", "")
        ]
        rationale = ResponseFormatter.clean_proposal_note(
            clean_text,
            selection,
            proposed_values,
        )
        return [
            {
                "id": f"p_{index}",
                "original_text": selection,
                "proposed_text": tool_call.get("value", ""),
                "rationale": rationale,
                "tool_call": tool_call,
            }
            for index, tool_call in enumerate(tool_calls)
            if tool_call.get("value", "")
        ]

    @staticmethod
    def clean_proposal_note(
        note: str,
        selection: str,
        proposed_values: list[str],
    ) -> str:
        note = str(note or "").strip()
        note_key = _normalize_proposal_note_text(note)
        if not note_key:
            return ""
        if any(
            _normalize_proposal_note_text(candidate) == note_key
            for candidate in [selection, *proposed_values]
        ):
            return ""
        return note
