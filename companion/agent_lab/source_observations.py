"""Durable observations shared by source reads, searches and contract previews."""


def observe(broker, result, method):
    if method == "search":
        ranges = [
            {"start": hit["start"], "end": hit["end"]}
            for hit in result.get("matches", [])
        ]
    else:
        ranges = [{"start": result["start"], "end": result["end"]}]
    value = {
        "file_id": result["file_id"],
        "version": result["version"],
        "method": method,
        "ranges": ranges,
    }
    broker.store.event(broker.task, "source_observed", value)
    return value


def observed(events):
    """Replay old read events too, preserving the latest observed version."""
    result = {}
    for event in events:
        if event["kind"] not in {"source_read", "source_observed"}:
            continue
        body = event["body"]
        file_id, version = body["file_id"], body["version"]
        value = result.get(file_id)
        if value is None or value["version"] != version:
            value = {"version": version, "ranges": [], "methods": []}
            result[file_id] = value
        method = body.get("method", "read")
        if method not in value["methods"]:
            value["methods"].append(method)
        ranges = body.get("ranges", [])
        if "start" in body and "end" in body:
            ranges = [*ranges, {"start": body["start"], "end": body["end"]}]
        for extent in ranges:
            if extent in value["ranges"]:
                value["ranges"].remove(extent)
            value["ranges"].append(extent)
        value["ranges"] = value["ranges"][-64:]
    return result
