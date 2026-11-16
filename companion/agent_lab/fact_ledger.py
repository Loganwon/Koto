"""Host-anchored claim records shared by final review and incremental checks."""

import hashlib
import json


def artifact_context(path):
    """Context that can change the meaning of an otherwise untouched block."""
    if path.suffix.lower() == ".docx":
        from docx import Document

        doc = Document(path)
        return {
            "titles": [
                p.text
                for p in doc.paragraphs
                if p.style.name == "Title"
                or p.style.name.startswith(("Heading", "标题"))
            ]
        }
    if path.suffix.lower() == ".pptx":
        from pptx import Presentation

        return {
            "titles": [
                slide.shapes.title.text if slide.shapes.title is not None else ""
                for slide in Presentation(path).slides
            ]
        }
    return {}


def blocks(text):
    result = {}
    for line in text.splitlines(keepends=True):
        for offset in range(0, len(line), 1000):
            part = line[offset : offset + 1000]
            if part.strip():
                result[f"b{len(result)}"] = part
    return result


def source_blocks(evidence):
    result = {}
    for ref in evidence.get("references", []):
        offset = ref.get("start", 0)
        for line in ref["text"].splitlines(keepends=True):
            for start in range(0, len(line), 1000):
                text = line[start : start + 1000]
                if text.strip():
                    result[f"s{len(result)}"] = {
                        "file_id": ref["file_id"],
                        "sha256": ref.get("sha256"),
                        "snapshot_version": ref.get("snapshot_version"),
                        "role": ref.get("role", "reference"),
                        "start": offset + start,
                        "end": offset + start + len(text),
                        "quote": text,
                    }
            offset += len(line)
    return result


INSTRUCTION = """
本批次还需返回claims数组，建立实际主张与依据账本，不是让作者把账本写进文稿。每项：{"blocks":["b0"],"kind":"source_fact|analysis|user_supplied|context|uncertain","sources":["s0"],"request_turn":0,"request_quote":"","issue":""}。
按独立主张拆项，复合段可有多项；所有正文块至少覆盖一次，不能漏表格单元格。source_blocks是宿主生成的来源定位；sources只能引用其id，禁止自己抄引文。source_fact须有实际支持的来源；copied_input不是事实权威。资料没说明的推断用analysis并核对已明确标注。无法核实的已有断言须写issue，不能改标context逃避；标题/表头/纯格式用context。用户明确新增事实用user_supplied，必须给真实用户的request_turn及连续request_quote。context/analysis/uncertain不强制来源，仍须保持正文实际确定性。
computed_facts中的真实计算可以用kind=analysis，不能要求原资料写出加总。普通业务原话允许转述，不机械要求逐字引用；文稿明确称为引文或表列原文时则核对连续原句。
顶层此时且仅含checks与claims；checks仍必须完整覆盖本批所有review_dimensions。"""


def validate(raw, body, references, requests):
    if not isinstance(raw, list) or len(raw) > 600:
        raise ValueError("来源账本claims必须为不超过600项的数组。")
    covered, result = set(), []
    for claim in raw:
        if (
            not isinstance(claim, dict)
            or set(claim)
            != {"blocks", "kind", "sources", "request_turn", "request_quote", "issue"}
            or claim["kind"]
            not in {"source_fact", "analysis", "user_supplied", "context", "uncertain"}
            or not isinstance(claim["blocks"], list)
            or not claim["blocks"]
            or any(not isinstance(i, str) or i not in body for i in claim["blocks"])
            or len(set(claim["blocks"])) != len(claim["blocks"])
            or not isinstance(claim["sources"], list)
            or any(
                not isinstance(i, str) or i not in references for i in claim["sources"]
            )
            or len(set(claim["sources"])) != len(claim["sources"])
            or type(claim["request_turn"]) is not int
            or not isinstance(claim["request_quote"], str)
            or not isinstance(claim["issue"], str)
            or len(claim["issue"]) > 1000
        ):
            raise ValueError("来源账本字段、正文块或来源块编号无效。")
        issue = claim["issue"]
        if claim["kind"] == "source_fact" and not any(
            references[i]["role"] != "copied_input" for i in claim["sources"]
        ):
            issue = issue or "该来源事实没有绑定实际事实资料。"
        if claim["kind"] == "user_supplied" and not any(
            r["turn"] == claim["request_turn"]
            and claim["request_quote"].strip()
            and claim["request_quote"] in r["message"]
            for r in requests
        ):
            raise ValueError("用户新增事实没有真实用户原句依据。")
        covered.update(claim["blocks"])
        value = {
            "kind": claim["kind"],
            "issue": issue,
            "body": [{"id": i, "quote": body[i]} for i in claim["blocks"]],
            "sources": [references[i] for i in claim["sources"]],
            "user": {"turn": claim["request_turn"], "quote": claim["request_quote"]},
        }
        value["id"] = (
            "f:"
            + hashlib.sha256(
                json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest()[:24]
        )
        result.append(value)
    if covered != set(body):
        raise ValueError(
            "来源账本遗漏实际正文块：" + ",".join(sorted(set(body) - covered))
        )
    return result


def persist(store, task, turn, payload, decision, sha256):
    if not payload.get("claim_ledger_required"):
        return
    claims = [
        claim
        for check in decision.get("checks", [])
        for claim in check.get("claims", [])
    ]
    if not claims and blocks(payload["actual_content"]):
        raise ValueError("来源验收没有可回溯的主张账本，不能确认完成。")
    if turn.cancelled.is_set() or store.get(task)["epoch"] != turn.epoch:
        return
    ledger = dict(store.get(task).get("fact_ledger", {}))
    ledger[payload["file_name"]] = {
        "version": 1,
        "sha256": sha256,
        "turn": turn.number,
        "allowed": decision.get("allowed") is True,
        "claims": claims,
    }
    store.change(task, fact_ledger=ledger)
