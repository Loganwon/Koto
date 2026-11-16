"""Read-only source tools and bounded verifier evidence."""

import json

from companion.contracts import CompanionError


def run(self, name, args):
    if name == "list_query_results":
        values = [
            v
            for v in self.store.get(self.task).get("analyses", [])
            if v["row_count"] >= args.get("minimum_rows", 0)
        ]
        values.reverse()
        start, limit = args.get("start", 0), args.get("limit", 10)
        page = []
        for value in values[start : start + limit]:
            entry = {
                "result_id": value["result_id"],
                "row_count": value["row_count"],
                "columns": value["columns"][:16],
                "column_count": len(value["columns"]),
                "sql": value.get("sql", "")[:600],
                "sql_truncated": len(value.get("sql", "")) > 600,
                "sources": [
                    {k: s[k] for k in ("file_id", "sha256")} for s in value["sources"]
                ],
            }
            if len(json.dumps([*page, entry], ensure_ascii=False)) > 12000:
                break
            page.append(entry)
        return {
            "results": page,
            "total": len(values),
            "next_start": (
                start + len(page) if start + len(page) < len(values) else None
            ),
            "scope": "持久结果索引；使用前仍须校验结果与来源版本，不代表已重新查询。",
        }
    if name == "read_query_result":
        result = self.data.result(args["result_id"])
        start, limit = args.get("start", 0), args.get("limit", 10)
        columns = args.get("columns", result["columns"])
        if len(set(columns)) != len(columns) or any(
            c not in result["columns"] for c in columns
        ):
            raise CompanionError(
                "读取列必须是不重复的真实查询列：" + "、".join(result["columns"])
            )
        indices = [result["columns"].index(c) for c in columns]
        rows = []
        for index in range(start, min(start + limit, len(result["rows"]))):
            row = {"row": index, "values": [result["rows"][index][i] for i in indices]}
            if len(json.dumps([*rows, row], ensure_ascii=False)) > 6000:
                break
            rows.append(row)
        evidence = {
            "result_id": args["result_id"],
            "columns": columns,
            "row_count": len(result["rows"]),
            "sources": result["sources"],
            "column_units": result.get("column_units", {}),
            "sql": result["sql"][:1500],
            "preview": [],
            "preview_truncated": True,
        }
        for row in rows[:5]:
            if (
                len(
                    json.dumps(
                        [*evidence["preview"], row["values"]], ensure_ascii=False
                    )
                )
                > 2400
            ):
                break
            evidence["preview"].append(row["values"])
        self.analysis_evidence = [*self.analysis_evidence, evidence][-10:]
        return {
            "result_id": args["result_id"],
            "columns": columns,
            "column_units": result.get("column_units", {}),
            "row_count": len(result["rows"]),
            "row_index_base": 0,
            "rows": rows,
            "next_start": start + len(rows),
            "truncated": start + len(rows) < len(result["rows"]),
            "sources": result["sources"],
            "guidance": "单行超出读取预算时用columns选择更少的真实列；完整导出仍直接用result_id，无需逐页抄写。",
        }
    if name == "list_files":
        return self.references.list(**args)
    if name == "read_reference":
        result = self.references.read(**args)
        from .source_observations import observe

        observe(self, result, "read")
        self.verification_reads.append(
            {key: result[key] for key in ("file_id", "version", "start", "end", "text")}
        )
        self.verification_reads = self.verification_reads[-12:]
        self.verification_reads[-1]["text"] = result["text"][:2000]
        self.verification_reads[-1]["truncated"] = len(result["text"]) > 2000
        self.store.event(
            self.task,
            "source_read",
            {
                "file_id": args["file_id"],
                "version": result["version"],
                "start": result["start"],
                "end": result["end"],
            },
        )
        return result
    if name == "search_reference":
        result = self.references.search(**args)
        from .source_observations import observe

        observe(self, result, "search")
        return result
    if name == "query_data":
        result = self.data.query(**args)
        evidence = {
            k: result[k] for k in ("result_id", "columns", "row_count", "sources")
        }
        evidence["sql"] = args["sql"][:1500]
        evidence["column_units"] = result.get("column_units", {})
        evidence["preview"] = []
        for row in result["preview"][:5]:
            if len(json.dumps([*evidence["preview"], row], ensure_ascii=False)) > 2400:
                break
            evidence["preview"].append(row)
        evidence["preview_truncated"] = len(evidence["preview"]) < result["row_count"]
        self.analysis_evidence = [*self.analysis_evidence, evidence][-10:]
        state = self.store.get(self.task)
        analyses = [
            v
            for v in state.get("analyses", [])
            if v["result_id"] != result["result_id"]
        ]
        analyses.append(
            {
                **{
                    k: result[k]
                    for k in ("result_id", "columns", "row_count", "sources")
                },
                "sql": args["sql"][:1500],
                "column_units": result.get("column_units", {}),
            }
        )
        self.store.change(self.task, analyses=analyses)
        self.store.event(
            self.task,
            "data_query",
            {
                "result_id": result["result_id"],
                "rows": result["row_count"],
                "sources": result["sources"],
            },
        )
        return result
