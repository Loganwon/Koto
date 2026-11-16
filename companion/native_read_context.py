"""Reuse observed source content across turns only after live version checks."""

from .contracts import CompanionError


def restore(broker, references, reads, analyses):
    if references.workspace is not broker.workspace:
        return
    references.ensure_current()
    changed = set()
    wanted = {r["file_id"] for r in reads}
    for file_id in wanted:
        previous = references._reads.get(file_id)
        if previous is None:
            continue
        try:
            current = broker.references._load(file_id)
        except (OSError, CompanionError):
            changed.add(file_id)
            continue
        if previous[1].version != current[1].version:
            changed.add(file_id)
            continue
        broker.references._reads[file_id] = current
    versions = {r["file_id"]: r["version"] for r in broker.references.evidence()}
    broker.verification_reads = [
        r for r in reads if versions.get(r["file_id"]) == r["version"]
    ][-12:]
    for observation in analyses[-10:]:
        try:
            broker.data.result(observation["result_id"])
        except (OSError, CompanionError):
            changed.update(s["file_id"] for s in observation["sources"])
            continue
        broker.analysis_evidence.append(observation)
    broker.invalidated_source_ids = sorted(changed)
    if broker.verification_reads or broker.analysis_evidence or changed:
        broker.store.event(
            broker.task,
            "source_context_verified",
            {
                "turn": broker.turn.number,
                "text_source_ids": sorted(versions),
                "result_ids": [a["result_id"] for a in broker.analysis_evidence],
                "invalidated_source_ids": sorted(changed),
            },
        )


def context(broker):
    return {
        "verified_reference_reads": broker.verification_reads,
        "verified_analyses": broker.analysis_evidence,
        "invalidated_source_ids": getattr(broker, "invalidated_source_ids", []),
    }
