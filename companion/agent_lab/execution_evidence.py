"""Version-bound source-access facts for checking workflow requirements."""


def source_reads(evidence):
    result = []
    for ref in evidence.get("references", []):
        ranges = sorted((r["start"], r["end"]) for r in ref.get("observed_ranges", []))
        covered = 0
        for start, end in ranges:
            if start > covered:
                break
            covered = max(covered, end)
        structured = ref.get("binding") == "structured_query"
        if not ref.get("observed_methods") and not structured:
            continue
        total = ref.get("characters", len(ref.get("text", "")))
        complete = covered >= total
        result.append(
            {
                "file_id": ref["file_id"],
                "sha256": ref.get("sha256"),
                "snapshot_version": ref.get("snapshot_version"),
                "fully_observed_text": complete,
                "structured_query_input": structured,
                **(
                    {"text": ref["text"]}
                    if complete and total <= 2000 and not ref.get("truncated")
                    else {}
                ),
            }
        )
    return sorted(result, key=lambda r: r["file_id"])
