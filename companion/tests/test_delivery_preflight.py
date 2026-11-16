"""The preflight is an untrusted proposal, never a write authority or receipt."""

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from companion.agent_lab.preflight import (
    DeliveryPreflight,
    fingerprint,
    is_current,
    snapshot,
    validate_estimate,
)
from companion.contracts import CompanionError


def context():
    return snapshot(
        "精简报告并整理预算明细表",
        [
            {
                "id": "a",
                "name": "项目.json",
                "revision": "sha-a",
                "excerpt": "金额123.45",
            }
        ],
        {"id": "doc", "name": "报告.docx", "revision": "v1"},
        {
            "revision": "lab-v1",
            "create_formats": ["docx", "xlsx", "pptx"],
            "edit_bound_target": True,
        },
    )


def proposal():
    return {
        "summary": "精简报告并整理预算表",
        "deliveries": [
            {
                "kind": "create",
                "name": "预算.xlsx",
                "format": "xlsx",
                "target_id": "",
                "source_ids": ["a"],
                "reason": "结构化明细适合表格",
            }
        ],
        "questions": [],
        "warnings": [],
    }


def test_create_can_omit_empty_target_but_edit_cannot():
    raw = proposal()
    del raw["deliveries"][0]["target_id"]
    result = validate_estimate(raw, context())
    assert result["deliveries"][0]["target_id"] == ""
    raw["deliveries"][0].update(kind="edit", name="报告.docx", format="docx")
    with pytest.raises(ValueError):
        validate_estimate(raw, context())


@pytest.mark.parametrize("part", ["request", "sources", "bound_target", "capabilities"])
def test_input_request_source_target_or_capability_change_invalidates_estimate(part):
    value = context()
    estimate = validate_estimate(proposal(), value)
    assert is_current(estimate, value)
    changed = deepcopy(value)
    if part == "request":
        changed[part] += "再生成摘要"
    elif part == "sources":
        changed[part][0]["revision"] = "sha-new"
    else:
        changed[part]["revision"] = "v2"
    assert not is_current(estimate, changed)
    assert not estimate["execution_authorized"] and estimate["status"] == "estimate"


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "../预算.xlsx"),
        ("name", "CON.xlsx"),
        ("name", "预算.docx"),
        ("source_ids", ["unknown"]),
        ("target_id", "other-document"),
        ("kind", "delete"),
        ("format", "xlsx.exe"),
    ],
)
def test_malformed_model_outputs_are_not_rendered_as_valid_deliveries(field, value):
    raw = proposal()
    raw["deliveries"][0][field] = value
    with pytest.raises(ValueError):
        validate_estimate(raw, context())


def test_cannot_rebind_overwrite_or_duplicate_write_target():
    raw = proposal()
    raw["deliveries"][0].update(
        kind="edit", name="资料.docx", format="docx", target_id="other"
    )
    with pytest.raises(ValueError):
        validate_estimate(raw, context())
    raw["deliveries"][0].update(kind="create", name="报告.docx", target_id="")
    with pytest.raises(ValueError):
        validate_estimate(raw, context())
    raw = proposal()
    raw["deliveries"].append(deepcopy(raw["deliveries"][0]))
    with pytest.raises(ValueError):
        validate_estimate(raw, context())


def test_unsupported_format_and_missing_information_block_preparation():
    raw = proposal()
    raw["deliveries"][0].update(name="预算.pdf", format="pdf")
    result = validate_estimate(raw, context())
    assert not result["can_prepare"]
    assert result["deliveries"][0]["status"] == "unsupported"
    raw = proposal()
    raw["questions"] = ["预算采用哪一种币种？"]
    assert not validate_estimate(raw, context())["can_prepare"]


def test_readonly_question_can_have_no_file_and_source_order_does_not_invalidate():
    raw = proposal()
    raw["deliveries"] = []
    assert validate_estimate(raw, context())["deliveries"] == []
    value = context()
    value["sources"].append(
        {"id": "b", "name": "访谈.docx", "revision": "sha-b", "excerpt": "访谈"}
    )
    flipped = deepcopy(value)
    flipped["sources"].reverse()
    assert fingerprint(snapshot(**value)) == fingerprint(snapshot(**flipped))


@pytest.mark.parametrize("finish_reason", ["length", "tool_calls", "content_filter"])
def test_incomplete_model_response_fails_closed_without_tool_execution(finish_reason):
    class Client:
        config = SimpleNamespace(model="test-only")

        def _request(self, payload, cancelled):
            assert "tools" not in payload and "tool_choice" not in payload
            return {
                "choices": [
                    {
                        "finish_reason": finish_reason,
                        "message": {"content": json.dumps(proposal())},
                    }
                ]
            }

    with pytest.raises(CompanionError):
        DeliveryPreflight(None, client=Client()).predict(context())


def test_invalid_structure_gets_one_readonly_repair_with_same_inventory():
    class Client:
        config = SimpleNamespace(model="test-only")
        calls = 0

        def _request(self, payload, cancelled):
            self.calls += 1
            assert "tools" not in payload
            assert json.loads(payload["messages"][1]["content"]) == context()
            raw = proposal()
            if self.calls == 1:
                raw["deliveries"].append(deepcopy(raw["deliveries"][0]))
            return {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": json.dumps(raw)}}
                ]
            }

    client = Client()
    result = DeliveryPreflight(None, client=client).predict(context())
    assert client.calls == 2 and result["schema_repaired"]
    assert len(result["deliveries"]) == 1 and not result["execution_authorized"]


def test_stop_between_preflight_and_repair_does_not_start_second_model_call():
    import threading

    cancelled = threading.Event()

    class Client:
        config = SimpleNamespace(model="test-only")
        calls = 0

        def _request(self, payload, event):
            self.calls += 1
            event.set()
            return {
                "choices": [{"finish_reason": "length", "message": {"content": "{"}}]
            }

    client = Client()
    with pytest.raises(CompanionError):
        DeliveryPreflight(None, client=client).predict(context(), cancelled=cancelled)
    assert client.calls == 1
