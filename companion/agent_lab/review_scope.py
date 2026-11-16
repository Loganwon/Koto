"""Semantic review dependencies, independent of unrelated transport/history state."""

import hashlib
import json

from .requirement_identity import key


def relevant_requests(state, checks):
    """Only persisted content obligations establish a file's user-fact scope."""
    turns = set()
    for check in checks:
        if "criterion" in check and check.get("introduced_turn"):
            turns.add(check["introduced_turn"])
        if check.get("request_turn"):
            turns.add(check["request_turn"])
        for origin in check.get("origins", []):
            if origin.get("request_turn"):
                turns.add(origin["request_turn"])
    return [
        {k: r[k] for k in ("turn", "message", "mode") if k in r}
        for r in state.get("user_requests", [])
        if r["turn"] in turns and r.get("mode") != "read"
    ]


def source_scope(evidence):
    # New read receipts do not change already verified source content. Hash,
    # live version, role, actual excerpt and computed facts remain authoritative.
    if evidence is not None and not isinstance(evidence, dict):
        return evidence
    return {
        **(evidence or {}),
        "references": sorted(
            [
                {
                    k: v
                    for k, v in ref.items()
                    if k not in {"binding", "observed_methods", "observed_ranges"}
                }
                for ref in (evidence or {}).get("references", [])
            ],
            key=lambda ref: (ref["file_id"], ref.get("start", 0)),
        ),
        "computed_facts": (evidence or {}).get("computed_facts", []),
    }


def dependencies(payload):
    fields = (
        "file_name",
        "actual_content",
        "document_context",
        "native_fragments",
        "editing_baseline",
        "semantic_context",
        "claim_ledger_required",
        "claim_windowed_review",
        "human_requests",
        "workbook_evidence",
        "execution_sources",
    )
    result = {field: payload.get(field) for field in fields}
    result["source_evidence"] = source_scope(payload.get("source_evidence"))
    result["effective_checks"] = sorted(key(c) for c in payload.get("fixed_checks", []))
    if not payload.get("effective_requirements_authoritative"):
        result.update(
            criteria=payload.get("criteria"),
            feedback_requests=payload.get("feedback_requests"),
        )
    return result


def identity(payload):
    return hashlib.sha256(
        json.dumps(
            {"protocol": "review-scope-v2-windowed-claims", **dependencies(payload)},
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()
