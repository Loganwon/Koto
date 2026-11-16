"""Provenance shared by native text reads and structured data observations."""

from pathlib import Path

from .agent_lab.execution_errors import ToolDiagnosticError


def verified_sources(broker, declared):
    evidence = {v["file_id"]: v for v in broker.references.evidence()}
    wanted = set(declared)
    # query_data is a real read, with durable results and pinned source hashes.
    # Reopen the result and revalidate saved sources immediately before a write;
    # task history or a model's source_ids declaration alone are never enough.
    for observation in broker.analysis_evidence:
        if not wanted.intersection(v["file_id"] for v in observation["sources"]):
            continue
        result = broker.data.result(observation["result_id"])
        for source in result["sources"]:
            if source["file_id"] not in wanted:
                continue
            evidence.setdefault(
                source["file_id"],
                {
                    "file_id": source["file_id"],
                    "name": Path(source["file_id"]).name,
                    "version": source["sha256"],
                    "coverage": [source.get("sheet") or "结构化资料"],
                    "limitations": ["仅覆盖本次查询的投影与结果，不代表全文阅读"],
                    "verification": "query_source_sha256",
                    "result_id": observation["result_id"],
                },
            )
    missing = sorted(wanted - evidence.keys())
    if missing:
        raise ToolDiagnosticError(
            "操作声明的来源本轮尚未读取：" + "、".join(missing),
            {
                "code": "unread_native_sources",
                "missing_source_ids": missing,
                "next_tools": [
                    {"name": "read_reference", "arguments": {"file_id": key}}
                    for key in missing
                ],
                "guidance": "先读取缺少的实际资料，或只声明本次实际使用的来源；不要重复相同写入。",
            },
        )
    return [evidence[key] for key in declared]
