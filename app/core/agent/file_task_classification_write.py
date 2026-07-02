from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FileTaskWriteIntentReasons:
    reason_codes: list[str] = field(default_factory=list)


def apply_write_intent_reason_codes(
    *,
    write_intent: bool,
    explicit_output_mode: str,
    diagnostic_request: bool,
    reason_codes: list[str],
) -> FileTaskWriteIntentReasons:
    reasons = list(reason_codes or [])
    if write_intent:
        reasons.append("write_intent")
        if str(explicit_output_mode or "").strip().lower() == "answer" and not diagnostic_request:
            reasons.append("answer_mode_overridden_by_write_intent")
    return FileTaskWriteIntentReasons(reason_codes=reasons)
