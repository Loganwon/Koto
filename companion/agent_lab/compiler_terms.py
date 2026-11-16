"""Compiled topic words cannot bypass the explicit verbatim-intent audit."""


def candidates(state, spec, files):
    proposed = spec.get("compiler_terms", {})
    for name, terms in proposed.items():
        for position, term in enumerate(terms):
            requests = [r for r in spec["requests"] if term in r["message"]]
            if not requests:
                # A source-only word is still checked semantically against the
                # real source; it cannot become an invented exact-output rule.
                continue
            files[name]["checks"].append(
                {
                    "id": f"compiler_literal:{position}",
                    "requirement": "正文必须逐字包含：" + term,
                    "literal": term,
                    "request_turn": requests[-1]["turn"],
                    "compiler_term": True,
                }
            )


def effective(state, spec, files):
    checks = {n: dict(v) for n, v in state.get("content_checks", {}).items()}
    decisions = {}
    for name, proposed in spec.get("compiler_terms", {}).items():
        accepted = list(
            dict.fromkeys(
                c["literal"] for c in files[name]["checks"] if c.get("compiler_term")
            )
        )
        decisions[name] = {"proposed": proposed, "accepted": accepted}
        if name in checks:
            checks[name]["terms"] = list(
                dict.fromkeys(
                    [
                        *[
                            t
                            for t in checks[name].get("terms", [])
                            if t not in proposed
                        ],
                        *accepted,
                    ]
                )
            )
    return checks, decisions
