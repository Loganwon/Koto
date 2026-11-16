"""One check per exact obligation, retaining every original provenance link."""

import hashlib
import json


def key(check):
    # Never guess semantic equivalence, normalize punctuation, or weaken a
    # literal. Different wording remains independent unless compiled identically.
    return hashlib.sha256(
        json.dumps(
            {"requirement": check["requirement"], "literal": check.get("literal")},
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def consolidate(checks):
    result, seen = [], {}
    for check in checks:
        identity = key(check)
        origins = check.get("origins") or [
            {k: check[k] for k in ("id", "criterion", "request_turn") if k in check}
        ]
        if identity not in seen:
            value = {**check, "requirement_key": identity, "origins": []}
            seen[identity] = value
            result.append(value)
        value = seen[identity]
        for origin in origins:
            if origin not in value["origins"]:
                value["origins"].append(dict(origin))
    return result
