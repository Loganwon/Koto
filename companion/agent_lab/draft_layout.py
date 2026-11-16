"""Rebalance a bounded slide proposal without deleting or inventing body text."""

from functools import lru_cache
import re


def rebalance(args, state):
    limits = state.get("output_limits", {}).get(args.get("file_name"), {})
    sections = args.get("sections", [])
    maximum = limits.get("max_slide_body_characters")
    count = limits.get("exact_slide_count", len(sections))
    if args.get("format") != "pptx" or not maximum or count != len(sections):
        return args
    # Keep all visible characters, including source names, dates and units.
    texts = [s["text"].replace("\r", "").replace("\n", "") for s in sections]
    if all(len(t) <= maximum for t in texts) or sum(map(len, texts)) > count * maximum:
        return args
    tokens = [
        part
        for text in texts
        for part in re.findall(r"[^。；;、，,]+[。；;、，,]?|[。；;、，,]", text)
    ]
    if (
        len(tokens) < count
        or len(tokens) > 500
        or any(len(t) > maximum for t in tokens)
    ):
        return args
    prefix = [0]
    for token in tokens:
        prefix.append(prefix[-1] + len(token))
    original = []
    for text in texts:
        original.append((original[-1] if original else 0) + len(text))

    @lru_cache(None)
    def solve(start, page):
        if page == count:
            return (0, ()) if start == len(tokens) else None
        best = None
        for end in range(start + 1, len(tokens) + 1):
            if prefix[end] - prefix[start] > maximum:
                break
            tail = solve(end, page + 1)
            if tail is None:
                continue
            cost = abs(prefix[end] - original[page]) + tail[0]
            candidate = (cost, (end, *tail[1]))
            if best is None or candidate[0] < best[0]:
                best = candidate
        return best

    solution = solve(0, 0)
    if solution is None:
        # Citation placement is independent of body reading order. Only move
        # explicit, registered filename annotations, never arbitrary sentences.
        from .draft_composer import pack

        sources = (
            state.get("content_checks", {})
            .get(args.get("file_name"), {})
            .get("sources", [])
        )
        annotations = [
            token
            for token in tokens
            if any(
                re.fullmatch(
                    r"(?:来源[:：]\s*)?"
                    + re.escape(source["file_id"])
                    + r"[。；;、，,]?",
                    token.strip(),
                )
                for source in sources
            )
        ]
        pages = (
            pack(tokens, count, maximum, movable=annotations) if annotations else None
        )
        if pages:
            pages = [
                {**p, "heading": sections[i]["heading"]} for i, p in enumerate(pages)
            ]
            return {**args, "sections": pages}
        return args
    revised, start = [], 0
    for page, end in enumerate(solution[1]):
        revised.append(
            {"heading": sections[page]["heading"], "text": "".join(tokens[start:end])}
        )
        start = end
    assert "".join(s["text"] for s in revised) == "".join(texts)
    return {**args, "sections": revised}
