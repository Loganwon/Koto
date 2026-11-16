"""Recover a copied draft's immutable baseline, distinct from factual sources."""

from pathlib import Path

from companion.contracts import CompanionError
from companion.file_actions import FileActions
from companion.file_readers import parse_file


def generated_baseline(broker, name, events, aliases):
    """Use the saved artifact before the latest human content request.

    Empty Continue controls are absent from user_requests, so stopping halfway
    through a multi-file revision cannot replace its baseline with a half edit.
    """
    state = broker.store.get(broker.task)
    turn = max(
        (r["turn"] for r in state.get("user_requests", []) if r.get("mode") != "read"),
        default=0,
    )
    boundary = next(
        (
            e["seq"]
            for e in events
            if e["kind"] == "user_message" and e["body"].get("turn") == turn
        ),
        None,
    )
    if boundary is None:
        return None
    receipts = [
        e["body"].get("result", {})
        for e in events
        if e["kind"] == "action_verified"
        and e["seq"] < boundary
        and e["body"].get("result", {}).get("name") in aliases
    ]
    if not receipts:
        return None
    receipt = receipts[-1]
    if receipt.get("sha256") == state.get("artifacts", {}).get(name, {}).get("sha256"):
        return None
    digest = receipt["sha256"]
    value = {
        "role": "editing_baseline_not_fact_source",
        "file_id": receipt["name"],
        "sha256": digest,
        "request_turn": turn,
    }
    path = (
        broker.outputs.parent
        / "artifact_versions"
        / (digest + Path(receipt["name"]).suffix)
    )
    if (
        not path.is_file()
        or path.is_symlink()
        or FileActions.receipt(path, "verify")["sha256"] != digest
    ):
        return {
            **value,
            "unavailable": True,
            "reason": "本次修改前的已生成文件版本不可用，不能用改后文件替代。",
        }
    snapshot = parse_file(path)
    if FileActions.receipt(path, "verify")["sha256"] != digest:
        raise CompanionError("编辑基稿在读取期间发生变化。")
    return {
        **value,
        "text": snapshot.text[:20000],
        "characters": len(snapshot.text),
        "truncated": len(snapshot.text) > 20000,
    }


def collect(broker, name):
    events = broker.store.events(broker.task)
    cursor, seen = name, set()
    receipt = None
    while cursor not in seen and len(seen) < 16:
        seen.add(cursor)
        matches = [
            e["body"].get("result", {})
            for e in events
            if e["kind"] == "action_verified"
            and e["body"].get("result", {}).get("name") == cursor
            and e["body"].get("result", {}).get("action")
            in {"copy_reference", "copy_artifact", "rename_artifact"}
        ]
        if not matches:
            return generated_baseline(broker, name, events, seen)
        receipt = matches[0]
        if receipt["action"] in {"copy_reference", "copy_artifact"}:
            break
        cursor = receipt["copied_from"]
    if not receipt or receipt["action"] not in {"copy_reference", "copy_artifact"}:
        return None
    digest = receipt["sha256"]
    paths = [
        broker.outputs.parent / "artifact_versions" / (digest + Path(name).suffix),
        broker.outputs / name,
    ]
    try:
        if receipt["action"] == "copy_reference":
            paths.append(broker.workspace._path(receipt["copied_from"]))
        else:
            from .file_operations import output_path

            paths.append(output_path(broker, receipt["copied_from"]))
    except (CompanionError, OSError):
        # A moved reference must not invalidate an available archived version.
        pass
    for path in paths:
        if not path.is_file() or path.is_symlink():
            continue
        if FileActions.receipt(path, "verify")["sha256"] != digest:
            continue
        snapshot = parse_file(path)
        if FileActions.receipt(path, "verify")["sha256"] != digest:
            continue
        return {
            "role": "editing_baseline_not_fact_source",
            "file_id": receipt["copied_from"],
            "sha256": digest,
            "text": snapshot.text[:20000],
            "truncated": len(snapshot.text) > 20000,
            "characters": len(snapshot.text),
        }
    return {
        "role": "editing_baseline_not_fact_source",
        "file_id": receipt["copied_from"],
        "sha256": digest,
        "unavailable": True,
        "reason": "复制时的原稿版本字节不可用，不能把新版本当作旧基稿。",
    }
