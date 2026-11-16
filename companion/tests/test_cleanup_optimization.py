"""Failures found by the code audit: real boundaries and files, no Office UI."""

import hashlib
import json
from pathlib import Path
import threading

import pytest

from companion.agent_lab.tools import Turn
from companion.agent_lab.completion import CompletionSupervisor
from companion.agent_lab.query_units import infer_units
from companion.agent_lab.task_requirements import validate, install
from companion.tests.test_agent_lab import make_lab
from companion.tests.test_native_query_sources import setup, query, bind_fact
from companion.tests.test_pane_task_session import (
    native,
    accept,
    wait,
    FixtureRequirements,
)


def test_explicit_continue_rearms_completion_but_question_does_not(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("摘要.docx",))
    n, e = store.begin_turn(task, "继续", "auto", True)
    broker.bind_turn(
        Turn(task, n, e, "继续", "auto", threading.Event(), interaction="continue")
    )
    assert CompletionSupervisor(broker).inspect_final()["missing_outputs"] == [
        "摘要.docx"
    ]
    n, e = store.begin_turn(task, "解释目前进度", "auto")
    broker.bind_turn(Turn(task, n, e, "解释目前进度", "auto", threading.Event()))
    assert CompletionSupervisor(broker).inspect_final() is None


def test_cents_cannot_be_redeclared_as_yuan_even_when_verifier_allows(tmp_path):
    broker, host, _ = setup(tmp_path)
    result = query(broker)
    assert result["column_units"] == {"cents": "分"}
    wrong = broker.invoke(
        "set_native_content_checks",
        {
            "fragment_id": "p1",
            "query_facts": [
                {
                    "id": "total",
                    "result_id": result["result_id"],
                    "row": 0,
                    "column": "cents",
                    "label": "采购合计",
                    "from_unit": "元",
                    "to_unit": "元",
                    "decimals": 2,
                }
            ],
        },
    )
    assert not wrong["ok"] and "实际单位为分" in wrong["error"]
    assert not host.writes


def test_omitted_source_ids_do_not_remove_real_query_dependencies(tmp_path):
    broker, host, _ = setup(tmp_path)
    result = query(broker)
    args = {
        "action_id": "omit",
        "fragment_id": "p1",
        "expected": "第一段原文。",
        "text": "采购合计：5400元。",
        "reason": "按真实采购查询修改",
    }
    assert not broker.invoke("apply_edit", args)["ok"] and not host.writes
    assert bind_fact(broker, result)["ok"]
    args.update(text="采购合计：54.00元。")
    written = broker.invoke("apply_edit", args)
    assert (
        written["ok"]
        and written["receipt"]["declared_sources"][0]["file_id"] == "采购.csv"
    )


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("SELECT SUM(money_product_cents(q,p)) AS total FROM s", "分"),
        (
            "WITH c AS (SELECT money_product_cents(q,p) AS x FROM s) SELECT SUM(x)/100 AS total FROM c",
            "元",
        ),
        (
            "SELECT money_cents(p) AS total FROM s UNION ALL SELECT SUM(money_cents(p)) FROM s",
            "分",
        ),
        ("SELECT 5400 AS total FROM s", "number"),
        ("SELECT SUM(q) AS total FROM s", None),
        (
            "SELECT SUM(CASE WHEN q>0 THEN money_product_cents(q,p) ELSE 0 END) AS total FROM s",
            "分",
        ),
        ("SELECT money_cents(p) AS total FROM s ORDER BY s.rowid", "分"),
        (
            "WITH c AS (SELECT money_cents(p) AS v FROM s) SELECT SUM(v) AS total FROM c UNION ALL SELECT (SELECT MAX(v) FROM c)",
            "分",
        ),
        (
            "SELECT CASE WHEN q>0 THEN money_cents(p) ELSE '未知' END AS total FROM s",
            None,
        ),
    ],
)
def test_query_units_follow_actual_expressions_not_output_aliases(sql, expected):
    assert (
        infer_units(sql, [{"name": "s", "columns": ["q", "p"]}], ["total"])["total"]
        == expected
    )


def test_replan_archives_old_acceptance_and_installs_fresh_contract(
    native, monkeypatch
):
    session, host, workspace = native
    monkeypatch.setattr(
        "companion.pane_task_session.WriteVerifier",
        lambda *a: lambda *a: {"allowed": True},
    )
    session.execute(accept(session))
    wait(session)
    session.store.change(
        session.task,
        output_limits={"摘要.docx": {"max_body_characters": 3}},
        content_checks={"摘要.docx": {"sources": ["obsolete"]}},
        workbook_schemas={"预算.xlsx": {"obsolete": True}},
    )
    session.prepare("新版本摘要100字以内", [], session.prepared["id"])
    state = wait(session)
    session.execute(state["workflow"]["prepared"]["id"])
    wait(session)
    saved = session.store.get(session.task)
    assert session.plan_revision == 2 and saved["output_limits"] == {}
    assert saved["content_checks"] == {} and saved["workbook_schemas"] == {}
    assert (
        saved["acceptance_history"][-1]["output_limits"]["摘要.docx"][
            "max_body_characters"
        ]
        == 3
    )
    assert saved["task_contract"]["revision"] == 2


def test_current_embedded_api_rejects_old_methods_with_specific_upgrade_code(tmp_path):
    from companion.embedded import EmbeddedAPI
    from companion.journal import EventJournal

    api = EmbeddedAPI(
        "word",
        workflow_enabled=True,
        journal=EventJournal(tmp_path / "journal.sqlite3"),
    )
    for call in (
        lambda: api.submit("修改首段"),
        lambda: api.advance(),
        lambda: api.start("修改"),
        lambda: api.retry(),
    ):
        result = call()
        assert not result["ok"] and result["code"] == "client_upgrade_required"
    assert api._session is None
    api._journal.close()


def test_tsv_works_in_file_tree_preflight_read_and_query(tmp_path):
    store, task, broker, _ = make_lab(tmp_path)
    (broker.workspace._root / "资料.tsv").write_text(
        "项目\t数量\n设备\t3", encoding="utf-8"
    )
    assert "资料.tsv" in [e["id"] for e in broker.workspace.tree()["entries"]]
    assert "设备" in broker.references.read("资料.tsv")["text"]
    assert broker.invoke(
        "query_data",
        {"sources": [{"name": "s", "file_id": "资料.tsv"}], "sql": "SELECT * FROM s"},
    )["ok"]


def contract_context():
    return {
        "request": "生成三页简报，每页不超过60字并列明来源",
        "sources": [
            {
                "id": "source",
                "name": "说明.txt",
                "revision": "v1",
                "excerpt": "真实内容",
            }
        ],
        "bound_target": None,
        "capabilities": {
            "revision": "test",
            "create_formats": ["pptx"],
            "edit_bound_target": False,
        },
    }


def contract_raw():
    return {
        "deliverables": [
            {
                "kind": "create",
                "name": "简报.pptx",
                "criteria": ["三页完整呈现资料事实"],
                "limits": {"exact_slide_count": 3, "max_slide_body_characters": 60},
                "required_sources": ["source"],
                "workbook_schema": None,
            }
        ]
    }


def test_compiled_contract_gates_output_without_model_registering_checks(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("简报.pptx",))
    (broker.workspace._root / "说明.txt").write_text("真实内容", encoding="utf-8")
    contract = validate(
        contract_raw(),
        contract_context(),
        {"deliveries": [{"kind": "create", "name": "简报.pptx"}]},
    )
    install(
        store,
        task,
        contract,
        [{"id": "source", "file_id": "说明.txt"}],
        1,
        broker.workspace,
    )
    wrong = broker.invoke(
        "create_presentation",
        {
            "action_id": "one-page",
            "file_name": "简报.pptx",
            "title": "简报",
            "sections": [{"heading": "概述", "text": "只有一页，未列来源。"}],
        },
    )
    assert not wrong["ok"] and not list(broker.outputs.iterdir())
    assert store.get(task)["output_limits"]["简报.pptx"]["exact_slide_count"] == 3
    assert not broker.invoke("complete_task", {"summary": "完成"})["ok"]


def test_independent_requirement_inventory_detects_missing_preflight_deliveries():
    with pytest.raises(ValueError, match="不一致"):
        validate(contract_raw(), contract_context(), {"deliveries": []})


def test_repaired_draft_is_saved_and_old_measurement_cannot_resurrect_it(tmp_path):
    class Verifier:
        def __call__(self, *args):
            return {"allowed": True}

        def repair_draft(self, turn, args, state, validation):
            return {**args, "sections": [{"heading": "", "text": "短稿"}]}

    store, task, broker, _ = make_lab(tmp_path, Verifier(), outputs=("结果.docx",))
    broker.invoke(
        "set_output_limits",
        {"limits": [{"file_name": "结果.docx", "max_body_characters": 4}]},
    )
    args = {
        "format": "docx",
        "file_name": "结果.docx",
        "sections": [{"heading": "", "text": "旧草稿仍然超限"}],
    }
    for step in (1, 2, 3):
        broker.turn.model_step = step
        result = broker.invoke("measure_content", args)
    accepted = result["draft_id"]
    broker.turn.model_step = 4
    result = broker.invoke("measure_content", args)
    assert (
        result["draft_id"] == accepted
        and result["metrics"]["paragraph_characters"] == 2
    )
    stale = broker.invoke(
        "create_word",
        {
            "action_id": "stale",
            "file_name": "结果.docx",
            "title": "结果",
            "sections": args["sections"],
        },
    )
    assert not stale["ok"] and stale["recovery"]["code"] == "stale_draft"
    assert broker.invoke(result["next_tool"]["name"], result["next_tool"]["arguments"])[
        "ok"
    ]


@pytest.mark.parametrize("format", ["docx", "pptx"])
def test_generated_office_text_can_be_revised_with_hash_old_value_and_backup(
    tmp_path, format
):
    store, task, broker, _ = make_lab(tmp_path, outputs=("结果." + format,))
    name = "结果." + format
    tool = "create_word" if format == "docx" else "create_presentation"
    original = broker.invoke(
        tool,
        {
            "action_id": "create",
            "file_name": name,
            "title": "结果",
            "sections": [
                {"heading": "第一部分", "text": "负责人Bob。"},
                {"heading": "第二部分", "text": "保留这一部分。"},
            ],
        },
    )["receipt"]
    read = broker.invoke("read_artifact", {"file_name": name})
    target = next(
        b for b in read["editable_blocks"]["blocks"] if b["text"] == "负责人Bob。"
    )
    args = {
        "action_id": "fix",
        "file_name": name,
        "expected_sha256": original["sha256"],
        "changes": [
            {
                "block_id": target["id"],
                "expected": "负责人Bob。",
                "text": "负责人Alice。",
            }
        ],
    }
    revised = broker.invoke("revise_office_text", args)
    assert revised["ok"] and revised["receipt"]["previous_sha256"] == original["sha256"]
    final = broker.invoke("read_artifact", {"file_name": name})
    texts = [b["text"] for b in final["editable_blocks"]["blocks"]]
    assert "负责人Alice。" in texts and "保留这一部分。" in texts
    assert (
        hashlib.sha256(
            (
                tmp_path / "artifact_versions" / (original["sha256"] + "." + format)
            ).read_bytes()
        ).hexdigest()
        == original["sha256"]
    )
    assert broker.invoke("revise_office_text", args)["replayed_receipt"]
    assert not broker.invoke("revise_office_text", {**args, "action_id": "outdated"})[
        "ok"
    ]
    n, e = store.begin_turn(task, "只解释", "read")
    broker.bind_turn(Turn(task, n, e, "只解释", "read", threading.Event()))
    assert "revise_office_text" not in [s["name"] for s in broker.definitions()]


def test_office_revision_cannot_publish_a_new_quality_violation(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("结果.docx",))
    receipt = broker.invoke(
        "create_word",
        {
            "action_id": "create",
            "file_name": "结果.docx",
            "title": "结果",
            "sections": [{"heading": "", "text": "短稿"}],
        },
    )["receipt"]
    broker.invoke(
        "set_output_limits",
        {"limits": [{"file_name": "结果.docx", "max_body_characters": 3}]},
    )
    target = next(
        b
        for b in broker.invoke("read_artifact", {"file_name": "结果.docx"})[
            "editable_blocks"
        ]["blocks"]
        if b["text"] == "短稿"
    )
    result = broker.invoke(
        "revise_office_text",
        {
            "action_id": "long",
            "file_name": "结果.docx",
            "expected_sha256": receipt["sha256"],
            "changes": [
                {"block_id": target["id"], "expected": "短稿", "text": "新文本超过要求"}
            ],
        },
    )
    assert (
        not result["ok"]
        and hashlib.sha256((broker.outputs / "结果.docx").read_bytes()).hexdigest()
        == receipt["sha256"]
    )


@pytest.mark.parametrize("format", ["docx", "pptx"])
def test_generated_office_paragraph_merge_can_clear_redundant_text(tmp_path, format):
    from companion.contracts import CompanionError, validate_replacement

    name = "结果." + format
    store, task, broker, _ = make_lab(tmp_path, outputs=(name,))
    receipt = broker.invoke(
        "create_word" if format == "docx" else "create_presentation",
        {
            "action_id": "create",
            "file_name": name,
            "title": "结果",
            "sections": [
                {"heading": "进度", "text": "先核查线索。"},
                {"heading": "下一步", "text": "再优化转化。"},
            ],
        },
    )["receipt"]
    blocks = broker.invoke("read_artifact", {"file_name": name})["editable_blocks"][
        "blocks"
    ]
    one, two = [
        next(b for b in blocks if b["text"] == value)
        for value in ["先核查线索。", "再优化转化。"]
    ]
    merged = broker.invoke(
        "revise_office_text",
        {
            "action_id": "merge",
            "file_name": name,
            "expected_sha256": receipt["sha256"],
            "changes": [
                {
                    "block_id": one["id"],
                    "expected": one["text"],
                    "text": "先核查线索，再优化转化。",
                },
                {"block_id": two["id"], "expected": two["text"], "text": ""},
            ],
        },
    )
    assert merged["ok"]
    final = {
        b["id"]: b["text"]
        for b in broker.invoke("read_artifact", {"file_name": name})["editable_blocks"][
            "blocks"
        ]
    }
    assert final[two["id"]] == "" and final[one["id"]] == "先核查线索，再优化转化。"
    assert all(final[b["id"]] == b["text"] for b in blocks if b not in [one, two])
    with pytest.raises(CompanionError):
        validate_replacement("")  # The native single-fragment rule is unchanged.


def test_budgeted_slide_layout_preserves_atomic_facts_and_citations():
    from companion.agent_lab.draft_composer import pack

    atoms = [
        "客户进展待分析",
        "收入240万元",
        "同比20%",
        "未经审计",
        "先核查线索质量，再改进转化",
        "2026-11-15内部评审",
        "负责人Alice",
        "采购总额：54.00元",
        "人民币",
        "项目说明.docx",
        "采购明细.xlsx",
        "实施安排.pptx",
        "联系人.pdf",
        "补充.csv",
    ]
    pages = pack(atoms, 3, 60)
    assert pages and len(pages) == 3
    assert all(len(p["text"].replace("\n", "")) <= 60 for p in pages)
    assert sorted("\n".join(p["text"] for p in pages).splitlines()) == sorted(atoms)
    assert "\n".join(p["text"] for p in pages).splitlines() == atoms
    citations = atoms[-5:]
    pages = pack(atoms, 3, 60, movable=citations)
    assert [
        line
        for page in pages
        for line in page["text"].splitlines()
        if line not in citations
    ] == atoms[:-5]
    assert pack(["不能删除的用户引文" * 20], 3, 10) is None


def test_slide_repair_uses_existing_body_before_another_model_request(tmp_path):
    from companion.agent_lab.runtime import WriteVerifier
    from collections import Counter

    store, task, broker, _ = make_lab(tmp_path, outputs=("简报.pptx",))
    sources = [
        "项目说明.docx",
        "采购明细.xlsx",
        "实施安排.pptx",
        "联系人.pdf",
        "补充.csv",
    ]
    state = store.get(task)
    state["output_limits"] = {
        "简报.pptx": {"exact_slide_count": 3, "max_slide_body_characters": 60}
    }
    state["content_checks"] = {
        "简报.pptx": {"sources": [{"file_id": v} for v in sources]}
    }
    args = {
        "file_name": "简报.pptx",
        "format": "pptx",
        "sections": [
            {
                "heading": "现状",
                "text": "金杉本季度营收240万元，同比增长20%；销售主要来自老客户，新客户转化仍需分析；未经审计。来源：补充.csv。",
            },
            {
                "heading": "安排",
                "text": "以提高工作效率为目标：先检查线索质量，再改进客户转化流程；内部评审2026-11-15完成，负责人Alice。",
            },
            {
                "heading": "预算",
                "text": "预算200万元；采购总额：54.00元人民币。来源：实施安排.pptx、联系人.pdf、采购明细.xlsx、项目说明.docx",
            },
        ],
    }
    verifier = WriteVerifier.__new__(WriteVerifier)
    verifier.store, verifier.task = store, task
    revised = verifier.repair_draft(broker.turn, args, state, {"passed": False})
    original = "".join(s["text"] for s in args["sections"])
    actual = "".join(s["text"].replace("\n", "") for s in revised["sections"])
    assert Counter(actual) == Counter(
        original
    )  # No dropped facts, units or punctuation.
    assert all(len(s["text"].replace("\n", "")) <= 60 for s in revised["sections"])
    assert actual.index("先检查线索质量") < actual.index("再改进客户转化流程")
    assert all(source in actual for source in sources)


def test_repair_supersedes_all_previously_failed_candidates(tmp_path):
    from companion.agent_lab.drafts import remember, replacement

    store, task, broker, _ = make_lab(tmp_path, outputs=("结果.docx",))
    drafts = [
        {
            "file_name": "结果.docx",
            "format": "docx",
            "sections": [{"heading": "", "text": text}],
        }
        for text in ["第一份超限候选", "第二份超限候选", "最终短稿"]
    ]
    for args in drafts[:2]:
        remember(broker, args, {"validation": {"passed": False}})
    final = remember(
        broker, drafts[2], {"validation": {"passed": True}}, supersedes=drafts[0]
    )
    for stale in drafts[:2]:
        assert replacement(broker, stale)["result"]["draft_id"] == final["draft_id"]


def test_optional_verified_detail_does_not_become_an_extra_required_claim(tmp_path):
    broker, host, _ = setup(tmp_path)
    result = query(broker)
    broker.store.change(broker.task, expected_outputs=["简报.docx"])
    broker.verifier = lambda *a: {"allowed": True, "required_fact_ids": []}
    declared = broker.invoke(
        "set_content_checks",
        {
            "file_name": "简报.docx",
            "query_facts": [
                {
                    "id": "optional",
                    "result_id": result["result_id"],
                    "row": 0,
                    "column": "cents",
                    "label": "可选采购明细",
                    "from_unit": "分",
                    "to_unit": "元",
                    "decimals": 2,
                }
            ],
        },
    )
    assert declared["required_phrases"] == [] and declared["verified_phrases"] == [
        "可选采购明细：54.00元"
    ]
    from companion.agent_lab.content_checks import violations

    assert not violations(broker, "简报.docx", "不展示额外明细。采购.csv")
    assert violations(broker, "简报.docx", "可选采购明细：5400元。采购.csv")


def test_plan_file_step_uses_real_receipt_and_cannot_be_marked_done_early(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("结果.docx",))
    broker.invoke(
        "update_work",
        {
            "steps": [
                {
                    "id": "file",
                    "description": "交付文档",
                    "artifact_name": "结果.docx",
                    "status": "completed",
                }
            ]
        },
    )
    assert store.get(task)["plan"][0]["status"] == "pending"
    assert broker.invoke(
        "create_word",
        {
            "action_id": "create",
            "file_name": "结果.docx",
            "title": "结果",
            "sections": [{"heading": "", "text": "真实内容"}],
        },
    )["ok"]
    assert store.get(task)["plan"][0]["status"] == "completed"


def test_unexpected_error_diagnostics_do_not_log_exception_payload(caplog):
    from companion.diagnostics import record_error

    try:
        raise ValueError("credential-or-document-body-must-not-be-logged")
    except ValueError as error:
        identity = record_error(error)
        assert record_error(error) == identity
    assert identity in caplog.text and "ValueError" in caplog.text
    assert "credential-or-document-body-must-not-be-logged" not in caplog.text


def test_item_count_and_total_row_are_unambiguous_and_numeric_totals_are_checked(
    tmp_path,
):
    from companion.agent_lab.workbook_contracts import merge_schema, violations
    from openpyxl import Workbook

    schema = merge_schema(
        {"expected_outputs": ["结果.xlsx"]},
        {
            "file_name": "结果.xlsx",
            "allow_extra_sheets": False,
            "sheets": [
                {
                    "name": "明细",
                    "columns": ["项目", "数量", "金额"],
                    "exact_item_rows": 2,
                    "totals": {
                        "label_column": "项目",
                        "label": "合计",
                        "sum_columns": ["数量", "金额"],
                    },
                }
            ],
        },
    )["结果.xlsx"]
    assert schema["sheets"][0]["exact_data_rows"] == 3
    book = Workbook()
    book.active.title = "明细"
    for row in [
        ["项目", "数量", "金额"],
        ["A", 3, 37.5],
        ["B", 2, 16.5],
        ["合计", None, 54],
    ]:
        book.active.append(row)
    assert any("合计不能留空" in error for error in violations(book, schema))
    book.active["B4"] = 5
    assert not violations(book, schema)
    book.close()


def test_currency_terms_do_not_require_one_concatenated_surface_form():
    raw = contract_raw()
    raw["deliverables"][0]["required_terms"] = ["54.00元人民币"]
    compiled = validate(
        raw,
        contract_context(),
        {"deliveries": [{"kind": "create", "name": "简报.pptx"}]},
    )
    assert compiled["deliverables"][0]["required_terms"] == ["54.00元", "人民币"]
