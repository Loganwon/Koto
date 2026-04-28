"""
Shared tool-call parsing utilities.

Single canonical implementation used by agent_loop, task_agent, and
socket_handler – replaces three near-identical local copies.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

# Tool types the agent is allowed to emit as structured calls.
# Keeping this as a module-level constant lets callers extend it if needed.
KNOWN_TOOL_TYPES: frozenset[str] = frozenset(
    {"set_html", "set_cell", "set_cells", "set_pptx_text"}
)


def parse_tool_calls(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Parse embedded tool-call blocks from AI response text.

    Recognises three formats (tried in order):
      1. Explicit ``<TOOL>…</TOOL>`` wrapper (preferred)
      2. Code-fenced JSON: ```json {...} ``` or ``` {...} ```
      3. Bare JSON line whose ``"type"`` value is a known tool type

    Returns
    -------
    (clean_text, tool_calls)
        ``clean_text`` – original text with all tool-call blocks removed.
        ``tool_calls``  – list of parsed tool-call dicts.
    """
    tool_calls: List[Dict[str, Any]] = []

    def _try_parse(raw: str) -> bool:
        raw = raw.strip()
        try:
            tc = json.loads(raw)
            if isinstance(tc, dict) and tc.get("type") in KNOWN_TOOL_TYPES:
                tool_calls.append(tc)
                return True
        except Exception:
            pass
        return False

    # Pass 1 – explicit <TOOL>…</TOOL>
    _tag_pat = re.compile(r"<TOOL>(.*?)<\s*/\s*TOOL>", re.DOTALL | re.IGNORECASE)

    def _replace_tag(m: re.Match) -> str:
        _try_parse(m.group(1))
        return ""

    text = _tag_pat.sub(_replace_tag, text).strip()
    # Strip orphaned / malformed TOOL tags
    text = re.sub(r"<\s*/?\s*TOOL\s*>", "", text, flags=re.IGNORECASE).strip()

    # Pass 2 – code-fenced JSON
    _fence_pat = re.compile(r"```(?:json)?\s*(\{[^`]+\})\s*```", re.DOTALL)

    def _replace_fence(m: re.Match) -> str:
        if _try_parse(m.group(1)):
            return ""
        return m.group(0)

    text = _fence_pat.sub(_replace_fence, text).strip()

    # Pass 3 – bare JSON line with a known tool type
    # Build the alternation from KNOWN_TOOL_TYPES so the set is the single source of truth.
    _types_re = "|".join(re.escape(t) for t in sorted(KNOWN_TOOL_TYPES))
    _bare_pat = re.compile(
        rf'(?:^|\n)\s*(\{{"type":\s*"(?:{_types_re})".*?\}})\s*(?=\n|$)',
        re.DOTALL,
    )

    def _replace_bare(m: re.Match) -> str:
        if _try_parse(m.group(1)):
            return ""
        return m.group(0)

    text = _bare_pat.sub(_replace_bare, text).strip()

    return text, tool_calls


def stringify_tool_result(result: Any) -> str:
    """Render arbitrary tool output into a compact, conversation-safe string."""
    if result is None:
        return "(no output)"
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False)
    except Exception:
        return str(result)
