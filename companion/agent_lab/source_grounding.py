"""Bounded, version-checked reference text for final source-fidelity review."""

import hashlib

from companion.contracts import DocumentConflict
from companion.file_actions import FileActions
from companion.file_readers import parse_file

CHECK = {
    "id": "quality:source_fidelity",
    "requirement": "逐项检查正文及表格中对来源的事实归属、对象、能力和结论是否得到source_evidence支持。相似概念、需求判断、未来规划不能提升为来源宣称已实现的能力；共同项必须确为各来源共有，不足则如实说明差异。简报自己的分析、推导和建议应明确区别于来源原话。宿主已核对的computed_facts允许作为计算结果；不要求来源原文直接列出其加总。证据截断时不得假定未展示部分支持主张，缺依据须指出具体尚待核实的主张，不把所有写作内容都当作来源事实。references包含宿主实际读取的资料，不因读取就自动成为事实权威；role=copied_input是被复制的编辑对象，必须依真实用户对原始资料/旧稿的角色说明核实，不能拿待审旧稿替自己证明。",
}

RELATIONS = {
    "id": "quality:source_relations",
    "requirement": "分别核对正文归属原资料的每处比较、优劣、因果、否定及观点方向。必须保持原作者判断的主客体和正反方向，不能只因出现原词或出处就算符合；正文前后对同一观点的转述也必须一致。发现任何方向倒置，在issue引出实际错误句与原资料含义。用户直接指定的新增内容不要求原资料中已有，不把简报自己明确提出的建议伪称来源原有结论。",
}
CERTAINTY = {
    "id": "quality:source_certainty",
    "requirement": "逐项区分原资料披露的事实、个人观点、示例、路线图、简报自身推断和未知事项，保留时间与证据边界。未提及不能推出不存在；列入路线图不能单独证明已经实现或尚未实现；宣传不能当实证；推测须明确标明，不能写成来源确认的绝对事实。用户明确指定的负责人等新增信息，以及用户要求保留的待验证判断，不需要在原资料中出现，但不能误归为资料原话。",
}
CHECKS = [CHECK, RELATIONS, CERTAINTY]


def collect(broker, name):
    state = broker.store.get(broker.task)
    checks = state.get("content_checks", {}).get(name, {})
    events = broker.store.events(broker.task)
    from .source_observations import observed

    observations = observed(events)
    proofs = {p["file_id"]: dict(p) for p in checks.get("sources", [])}
    # Required citations control literal filenames in the body. They must not
    # control whether facts are checked against references actually read.
    for file_id, observation in observations.items():
        proofs.setdefault(file_id, {"file_id": file_id})["observed_version"] = (
            observation["version"]
        )
    # Structured queries are real reads too. Use their host-recorded hashes;
    # requiring a second prose read would falsely call a verified table missing.
    for analysis in state.get("analyses", []):
        for source in analysis.get("sources", []):
            file_id = source["file_id"]
            proof = proofs.setdefault(file_id, {"file_id": file_id})
            if proof.get("sha256") and proof["sha256"] != source["sha256"]:
                raise DocumentConflict("来源文字读取与结构化查询的版本不同：" + file_id)
            proof.update(sha256=source["sha256"], structured_query=True)
    copied = {
        e["body"]["result"]["copied_from"]
        for e in events
        if e["kind"] == "action_verified"
        and e["body"].get("result", {}).get("action") == "copy_reference"
    }
    if len(proofs) > 32:
        raise DocumentConflict("来源验收超过32份资料范围，未截断后冒充完整核对。")
    values, budget = [], 60000
    if getattr(broker.document, "native_editor", False):
        for fragment, text in broker.document.contents().items():
            if len(text) > 20000 or len(text) > budget:
                raise DocumentConflict(
                    "原生片段超过来源核对预算，未截断后声称完整核对。"
                )
            values.append(
                {
                    "file_id": "current_selection#" + fragment,
                    "fragment": fragment,
                    "origin": "native_fragment",
                    "role": "native_input",
                    "sha256": None,
                    "snapshot_version": hashlib.sha256(text.encode()).hexdigest(),
                    "start": 0,
                    "end": len(text),
                    "characters": len(text),
                    "text": text,
                    "truncated": False,
                }
            )
            budget -= len(text)
    for proof in proofs.values():
        file_id = proof["file_id"]
        # Table observations carry sheet/cell addresses. They are bounded like
        # other references, with explicit truncation, never a whole-table proof.
        path = broker.workspace._path(file_id)
        before = FileActions.receipt(path, "verify")["sha256"]
        if proof.get("sha256") and before != proof["sha256"]:
            raise DocumentConflict("最终来源核对前资料已变化：" + file_id)
        live_reader = getattr(broker, "live_reader", None)
        live = live_reader(str(path)) if live_reader else None
        snapshot = live if live is not None else parse_file(path)
        if (
            proof.get("observed_version")
            and snapshot.version != proof["observed_version"]
        ):
            raise DocumentConflict(
                "已读参考的当前保存文本与观察版本不同；未以磁盘旧稿代替实时内容，请重新读取："
                + file_id
            )
        # Prefer recently observed ranges for a large document; fresh readback
        # still verifies their current bytes. A later targeted read changes the
        # excerpt and invalidates the cached review, without widening writes.
        start = 0
        if len(snapshot.text) > 20000:
            ranges = observations.get(file_id, {}).get("ranges", [])
            if ranges:
                start = max(0, min(ranges[-1]["start"], len(snapshot.text) - 20000))
        limit = min(20000, budget)
        content = snapshot.text[start : start + limit]
        end = start + len(content)
        budget -= len(content)
        if FileActions.receipt(path, "verify")["sha256"] != before:
            raise DocumentConflict("最终来源读取期间资料已变化：" + file_id)
        values.append(
            {
                "file_id": file_id,
                "sha256": before,
                "origin": "native_live" if live is not None else "saved_file",
                "snapshot_version": snapshot.version,
                "role": "copied_input" if file_id in copied else "reference",
                "binding": (
                    "structured_query"
                    if proof.get("structured_query")
                    else "declared_citation" if proof.get("sha256") else "observed_read"
                ),
                "observed_methods": observations.get(file_id, {}).get("methods", []),
                "observed_ranges": observations.get(file_id, {}).get("ranges", []),
                "start": start,
                "end": end,
                "characters": len(snapshot.text),
                "text": content,
                "truncated": start != 0 or end < len(snapshot.text),
            }
        )
    return {
        "references": values,
        "computed_facts": [
            {"id": f["id"], "phrase": f["phrase"], "sources": f["sources"]}
            for f in checks.get("facts", [])
        ],
    }


def verify(broker, value):
    for proof in value["references"]:
        if proof.get("origin") == "native_fragment":
            if broker.document.read(proof["fragment"]) != proof["text"]:
                raise DocumentConflict("来源验收期间原生选区已变化。")
            continue
        path = broker.workspace._path(proof["file_id"])
        if FileActions.receipt(path, "verify")["sha256"] != proof["sha256"]:
            raise DocumentConflict("最终来源验收期间资料已变化：" + proof["file_id"])
        if proof.get("origin") == "native_live":
            reader = getattr(broker, "live_reader", None)
            current = reader(str(path)) if reader else None
            if current is None or current.version != proof["snapshot_version"]:
                raise DocumentConflict(
                    "来源验收期间实时文档变化或已断开：" + proof["file_id"]
                )
