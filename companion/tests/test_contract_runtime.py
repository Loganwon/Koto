"""File benchmarks and production tools share the accepted contract lifecycle."""

import json
import threading
from types import SimpleNamespace

import pytest

from companion.agent_lab.runtime import WriteVerifier, LabSession
from companion.agent_lab.tools import Turn
from companion.agent_lab.contract_runtime import revise
from companion.tests.test_agent_lab import make_lab
from companion.contracts import CompanionError


def entry(name, criterion="精简首段"):
    return {
        "name": name,
        "kind": "create",
        "criteria": [criterion],
        "limits": {},
        "required_sources": [],
        "required_terms": [],
        "workbook_schema": None,
    }


class Client:
    config = SimpleNamespace(model="test")

    def __init__(self, values):
        self.values, self.calls = iter(values), 0

    def _request(self, *args):
        self.calls += 1
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(next(self.values))},
                }
            ]
        }


def attach(store, task, broker, values):
    verifier = WriteVerifier.__new__(WriteVerifier)
    verifier.store, verifier.task, verifier.client = store, task, Client(values)
    broker.verifier = verifier
    return verifier


def test_real_file_session_freezes_contract_and_checks_before_any_engine_execution(
    tmp_path,
):
    store, task, broker, _ = make_lab(tmp_path, outputs=("摘要.docx",))
    # The new accepted contract owns current requirements; the old start stays
    # available as background instead of creating requirements for another file.
    frozen = {
        "files": [
            {
                "name": "摘要.docx",
                "literal_checks": [],
                "criteria": [
                    {
                        "index": 0,
                        "kind": "content",
                        "items": ["保留指定事实"],
                        "reason": "",
                    }
                ],
                "requests": [
                    {"index": i, "kind": "host", "items": [], "reason": "原文操作要求"}
                    for i in range(1)
                ],
            }
        ]
    }
    verifier = attach(
        store,
        task,
        broker,
        [{"deliverables": [entry("摘要.docx", "保留指定事实")]}, frozen],
    )

    class Engine:
        def run(self, current, prompt, message):
            state = store.get(task)
            assert (
                state["contract_required"]
                and state["acceptance_plan"]["files"]["摘要.docx"]["checks"]
            )
            return "任务仍待交付"

    result = LabSession(store, task, broker, Engine()).send(
        "生成摘要.docx，保留指定事实", interaction="start"
    )
    assert verifier.client.calls == 2 and not result["state"]["artifacts"]


def test_new_delivery_contract_commits_names_and_acceptance_together(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("摘要.docx",))
    attach(store, task, broker, [{"deliverables": [entry("终稿.docx")]}])
    revise(broker, ["终稿.docx"], {"contract_revision": 1, "phase": "active"})
    state = store.get(task)
    assert state["expected_outputs"] == ["终稿.docx"]
    assert state["task_contract"]["deliverables"][0]["name"] == "终稿.docx"
    assert state["contract_revision"] == 1


def test_failed_contract_compile_cannot_half_commit_a_new_delivery_list(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("摘要.docx",))
    attach(store, task, broker, [{"deliverables": []}] * 3)
    with pytest.raises(CompanionError):
        revise(broker, ["终稿.docx"], {"contract_revision": 1, "phase": "active"})
    state = store.get(task)
    assert (
        state["expected_outputs"] == ["摘要.docx"] and state["contract_revision"] == 0
    )


def test_contract_schema_error_is_repaired_before_execution_instead_of_escaping(
    tmp_path,
):
    from companion.agent_lab.contract_runtime import compile_contract

    store, task, broker, _ = make_lab(tmp_path, outputs=("结果.xlsx",))
    good = entry("结果.xlsx")
    schema = {
        "allow_extra_sheets": False,
        "sheets": [{"name": "明细", "exact_item_rows": 16}],
    }
    good["workbook_schema"] = schema
    bad = {**good, "workbook_schema": {**schema, "exact_item_rows": 16}}
    verifier = attach(
        store, task, broker, [{"deliverables": [bad]}, {"deliverables": [good]}]
    )
    contract, _ = compile_contract(broker, ["结果.xlsx"])
    assert (
        verifier.client.calls == 2
        and contract["deliverables"][0]["workbook_schema"] == schema
    )
    assert not store.get(task)["artifacts"]


def test_readonly_question_does_not_compile_or_mutate_deliverables(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("摘要.docx",))
    verifier = attach(store, task, broker, [])

    class Engine:
        def run(self, *args):
            return "只作解释"

    result = LabSession(store, task, broker, Engine()).send("只回答问题", mode="read")
    assert verifier.client.calls == 0 and not result["state"].get("contract_required")


def test_feedback_can_revise_delivery_scope_before_freezing_old_file_requirements(
    tmp_path,
):
    calls = []

    class Verifier:
        def prepare_acceptance(self, *args):
            calls.append("prepare")

        def __call__(self, *args):
            return {"allowed": True}

    store, task, broker, _ = make_lab(tmp_path, Verifier())

    class Engine:
        def run(self, current, prompt, message):
            assert not calls
            return "先核对新的交付清单"

    LabSession(store, task, broker, Engine()).send(
        "换成短版，旧稿归档", interaction="feedback"
    )
    assert not calls


def test_compiler_cannot_turn_source_details_into_new_user_obligations(tmp_path):
    from companion.agent_lab.contract_runtime import compile_contract

    store, task, broker, _ = make_lab(tmp_path, outputs=("摘要.docx",))
    invented = entry("摘要.docx", "所有判断必须统一标注第5页")
    real = entry("摘要.docx", "精简首段")
    verifier = attach(
        store, task, broker, [{"deliverables": [invented]}, {"deliverables": [real]}]
    )
    contract, _ = compile_contract(broker, ["摘要.docx"])
    assert verifier.client.calls == 2
    assert contract["deliverables"][0]["criteria"] == ["精简首段"]


def test_grounded_clause_can_end_at_user_comma_without_inventing_a_new_condition():
    from companion.agent_lab.task_requirements import validate

    raw = {"deliverables": [entry("摘要.docx", "收入表保持原样。")]}
    context = {
        "request": "收入表保持原样，旧稿归档。",
        "sources": [],
        "criteria_must_quote_requests": True,
    }
    estimate = {"deliveries": [{"kind": "create", "name": "摘要.docx"}]}
    assert validate(raw, context, estimate)["deliverables"][0]["criteria"] == [
        "收入表保持原样"
    ]
    raw["deliverables"][0]["criteria"] = ["收入表已核实全部数据。"]
    with pytest.raises(ValueError, match="真实要求"):
        validate(raw, context, estimate)


def test_new_short_file_cannot_inherit_archived_full_report_chapters():
    from companion.agent_lab.task_requirements import validate

    old = entry("初稿.docx", "列全部能力与各档方案限制")
    context = {
        "request": "新短版只保留收入、年费与示例限定",
        "sources": [],
        "criteria_must_quote_requests": True,
        "previous_contract": {"deliverables": [old]},
    }
    estimate = {"deliveries": [{"kind": "create", "name": "短版.docx"}]}
    with pytest.raises(ValueError, match="真实要求"):
        validate(
            {"deliverables": [entry("短版.docx", old["criteria"][0])]},
            context,
            estimate,
        )
    value = validate(
        {"deliverables": [entry("短版.docx", context["request"])]}, context, estimate
    )
    assert value["deliverables"][0]["criteria"] == [context["request"]]
