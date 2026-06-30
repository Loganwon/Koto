"""
response_formatter.py — Proposal building and note cleaning helpers
extracted from KotoAgentLoop.

Provides a stateless ResponseFormatter class so that KotoAgentLoop._build_proposals
becomes a thin delegator.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

# ── Regex helpers (mirrors agent_loop.py module-level definitions) ──────────

_PROPOSAL_NOTE_PREAMBLE_RE = re.compile(
    r"^(?:以下|下面|这是|如下)(?:是|为)?.{0,20}(?:润色|翻译|改写|修改|修正|优化|版本|结果|文本|内容).{0,10}[：:]\s*",
    re.IGNORECASE,
)


def _normalize_proposal_note_text(text: Any) -> str:
    plain = re.sub(r"<[^>]+>", " ", str(text or ""))
    plain = _PROPOSAL_NOTE_PREAMBLE_RE.sub("", plain).strip()
    return re.sub(r"\s+", "", plain).lower()


class ResponseFormatter:
    """
    Stateless helpers for turning LLM output + tool calls into proposal
    structures suitable for the frontend.
    KotoAgentLoop methods delegate to these static methods.
    """

    @staticmethod
    def build_proposals(
        selection: str,
        tool_calls: List[Dict[str, Any]],
        clean_text: str,
    ) -> List[Dict[str, Any]]:
        """Build proposal dicts from tool calls + selection.

        Mirrors KotoAgentLoop._build_proposals.

        Parameters
        ----------
        selection:
            The text the user currently has selected in the document.
        tool_calls:
            Parsed tool-call dicts from the LLM response.
        clean_text:
            The LLM response text (after stripping tool-call tags) used to
            derive the proposal rationale note.
        """
        proposals: List[Dict[str, Any]] = []
        proposed_values = [
            tc.get("value", "") for tc in tool_calls if tc.get("value", "")
        ]
        proposal_note = ResponseFormatter.clean_proposal_note(
            clean_text, selection, proposed_values
        )
        for idx, tc in enumerate(tool_calls):
            proposed = tc.get("value", "")
            if proposed:
                proposals.append(
                    {
                        "id": f"p_{idx}",
                        "original_text": selection,
                        "proposed_text": proposed,
                        "rationale": proposal_note,
                        "tool_call": tc,
                    }
                )
        return proposals

    @staticmethod
    def clean_proposal_note(
        note: str, selection: str, proposed_values: List[str]
    ) -> str:
        """Return the note text, or empty string if it is redundant.

        Mirrors the module-level _proposal_note_or_empty function in
        agent_loop.py.  A note is considered redundant when its normalised
        form matches either the current selection or any of the proposed
        replacement values.
        """
        note = str(note or "").strip()
        note_key = _normalize_proposal_note_text(note)
        if not note_key:
            return ""
        for candidate in [selection, *proposed_values]:
            if _normalize_proposal_note_text(candidate) == note_key:
                return ""
        return note
