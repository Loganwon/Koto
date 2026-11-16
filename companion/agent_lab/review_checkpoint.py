"""Reuse local proofs across edits; document-wide checks remain mandatory."""

import hashlib
import json

from .requirement_identity import key
from .fact_ledger import blocks


def context_identity(payload):
    from .review_scope import source_scope

    return hashlib.sha256(
        json.dumps(
            {
                "protocol": "incremental-proof-v1",
                **{
                    k: payload.get(k)
                    for k in (
                        "file_name",
                        "semantic_context",
                        "native_fragments",
                        "editing_baseline",
                        "source_evidence",
                        "workbook_evidence",
                        "execution_sources",
                    )
                },
                "source_evidence": source_scope(payload.get("source_evidence")),
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def neighborhoods(payload, check):
    body = list(blocks(payload["actual_content"]).values())
    evidence = check.get("evidence", [])
    if not evidence:
        return []
    result = []
    for item in evidence:
        quote = item.get("quote")
        positions = [i for i, text in enumerate(body) if text == quote]
        if len(positions) != 1:
            return []
        index = positions[0]
        result.append(body[max(0, index - 1) : index + 2])
    return result


def identity(payload):
    from .review_scope import identity as scope_identity

    return scope_identity(payload)


def restore(store, task, payload):
    saved = (
        store.get(task).get("acceptance_checkpoints", {}).get(payload["file_name"], {})
    )
    identical = saved.get("scope") == identity(payload)
    incremental = (
        payload.get("incremental_review") is True
        and saved.get("context") == context_identity(payload)
        and any(c["id"] == "quality:consistency" for c in payload["fixed_checks"])
    )
    if not identical and not incremental:
        return []
    result = []
    for check in payload["fixed_checks"]:
        previous = saved.get("checks", {}).get(key(check))
        if previous and previous.get("status") == "satisfied":
            if identical and previous.get("proof_scope") == identity(payload):
                result.append({**previous, **check})
            elif (
                previous.get("scope_kind") == "local"
                and not check["id"].startswith("quality:")
                and previous.get("dependencies")
                and (
                    not check.get("literal")
                    or check["literal"] in payload["actual_content"]
                )
            ):
                current = list(blocks(payload["actual_content"]).values())
                if all(
                    sum(
                        current[i : i + len(dependency)] == dependency
                        for i in range(len(current))
                    )
                    == 1
                    for dependency in previous["dependencies"]
                ):
                    # Restore ids from current body rather than stale positions.
                    mapping = blocks(payload["actual_content"])
                    evidence = [
                        {"id": i, "quote": text}
                        for i, text in mapping.items()
                        if any(text == e["quote"] for e in previous.get("evidence", []))
                    ]
                    result.append(
                        {
                            **previous,
                            **check,
                            "evidence": evidence,
                            "reused_incrementally": True,
                        }
                    )
    return result


def save(store, task, turn, payload, checks):
    state = store.get(task)
    if turn.cancelled.is_set() or state["epoch"] != turn.epoch:
        return
    scope = identity(payload)
    cache = dict(state.get("acceptance_checkpoints", {}))
    entry = cache.get(payload["file_name"], {})
    compatible = entry.get("scope") == scope or (
        payload.get("incremental_review") is True
        and entry.get("context") == context_identity(payload)
    )
    accepted = dict(entry.get("checks", {})) if compatible else {}
    # A newly failed proof replaces an old success; never resurrect it later.
    for check in checks:
        accepted.pop(key(check), None)
        if check.get("status") == "satisfied":
            accepted[key(check)] = {
                **check,
                "dependencies": neighborhoods(payload, check),
                "proof_scope": scope,
            }
    cache[payload["file_name"]] = {
        "scope": scope,
        "context": context_identity(payload),
        "checks": accepted,
    }
    store.change(task, acceptance_checkpoints=cache)
