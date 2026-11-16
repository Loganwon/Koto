"""Verbatim user text is distinct from subjects, exclusions and layout commands."""

import copy
import json
import threading
from types import SimpleNamespace

import pytest

from companion.agent_lab.literal_intent import audit
from companion.contracts import CompanionError


def test_layout_and_count_are_not_body_literals_but_explicit_owner_is():
    message = "正文加入准确文字负责人=Alice。保留原有章节和布局，Word正文最多300字。"
    candidates = ["负责人=Alice", "保留原有章节和布局", "Word正文最多300字"]
    files = {
        "目标.docx": {
            "checks": [{"id": "content:0", "requirement": "保留原意"}]
            + [
                {"id": f"literal:{i}", "literal": text, "request_turn": 1}
                for i, text in enumerate(candidates)
            ]
        }
    }
    events = []

    class Client:
        config = SimpleNamespace(model="test")

        def _request(self, request, cancelled):
            payload = json.loads(request["messages"][1]["content"])
            assert payload["requests"] == [{"turn": 1, "message": message}]
            decisions = [
                {
                    "id": f"l{i}",
                    "required": i == 0,
                    "instruction_quote": (
                        "正文加入准确文字负责人=Alice" if i == 0 else ""
                    ),
                    "reason": "明确写入" if i == 0 else "执行约束，非正文文字",
                }
                for i in range(3)
            ]
            return response(decisions)

    audit(
        Client(),
        SimpleNamespace(number=1, cancelled=threading.Event()),
        SimpleNamespace(event=lambda *args: events.append(args)),
        "task",
        {"requests": [{"turn": 1, "message": message}]},
        files,
    )
    assert [c["id"] for c in files["目标.docx"]["checks"]] == ["content:0", "literal:0"]
    assert events[0][1] == "literal_intent_checked"


def response(decisions):
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": json.dumps({"decisions": decisions})},
            }
        ]
    }


@pytest.mark.parametrize(
    "bad",
    [
        [],
        [
            {
                "id": "l0",
                "required": True,
                "instruction_quote": "并不存在的指令负责人=Alice",
                "reason": "伪证",
            }
        ],
    ],
)
def test_missing_or_forged_intent_cannot_mutate_the_plan(bad):
    files = {
        "目标.docx": {
            "checks": [
                {"id": "literal:0", "literal": "负责人=Alice", "request_turn": 1}
            ]
        }
    }
    before = copy.deepcopy(files)
    client = SimpleNamespace(
        config=SimpleNamespace(model="test"), _request=lambda *args: response(bad)
    )
    with pytest.raises(CompanionError):
        audit(
            client,
            SimpleNamespace(number=1, cancelled=threading.Event()),
            SimpleNamespace(event=lambda *args: None),
            "task",
            {"requests": [{"turn": 1, "message": "正文加入负责人=Alice"}]},
            files,
        )
    assert files == before
