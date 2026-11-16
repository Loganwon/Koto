"""Bound source claims by actual body windows, never by dropping obligations."""

from companion.contracts import OperationCancelled
from .fact_ledger import blocks


def windows(body, *, max_blocks=10, max_characters=2500):
    current, characters = {}, 0
    for bid, text in body.items():
        if current and (
            len(current) >= max_blocks or characters + len(text) > max_characters
        ):
            yield current
            current, characters = {}, 0
        current[bid] = text
        characters += len(text)
    if current:
        yield current


def review(client, turn, payload, reviewer, *, record=None):
    """Claim ledger windows use global ids and keep table/header context intact."""
    body = blocks(payload["actual_content"])
    check = next(
        c for c in payload["fixed_checks"] if c["id"] == "quality:source_fidelity"
    )
    machine = payload.get("workbook_evidence", {}).get("verified_blocks", {})
    unproved = {bid: text for bid, text in body.items() if bid not in machine}
    chunks = list(windows(unproved))
    decisions = []
    for index, window in enumerate(chunks):
        if turn.cancelled.is_set():
            raise OperationCancelled("来源核验已停止，未完成窗口仍待验收。")
        if record:
            record(
                {
                    "event": "source_claim_window",
                    "file_name": payload["file_name"],
                    "window": index,
                    "windows": len(chunks),
                    "block_ids": list(window),
                }
            )
        decision = reviewer(
            client,
            turn,
            {
                **payload,
                "fixed_checks": [check],
                "_evidence_blocks": window,
                "_claim_window": True,
            },
            record=record,
        )
        decisions.extend(decision["checks"])
        if not decision["allowed"]:
            return {
                **decision["checks"][0],
                "pending_body_blocks": [
                    b for later in chunks[index + 1 :] for b in later
                ],
            }
    claims = [claim for decision in decisions for claim in decision.get("claims", [])]
    for bid, proof in machine.items():
        if bid not in body:
            raise ValueError("查询导出凭据未对应实际正文块。")
        claims.append(
            {
                "id": "query:" + bid,
                "kind": "analysis",
                "issue": "",
                "body": [{"id": bid, "quote": body[bid]}],
                "sources": [],
                "user": {"turn": 0, "quote": ""},
                "derivation": proof,
            }
        )
    covered = {b["id"] for claim in claims for b in claim["body"]}
    if covered != set(body):
        raise ValueError("来源窗口未完整覆盖正文，不能确认通过。")
    return {
        **check,
        "status": "satisfied",
        "issue": "",
        "reason": "全部来源窗口已核对。",
        "scope_kind": "document",
        "claims": claims,
        "evidence": [{"id": bid, "quote": text} for bid, text in body.items()],
        "claim_windows": len(chunks),
    }
