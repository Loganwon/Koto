"""Topic words in old compiler metadata must not veto a valid paraphrase."""

import json
import threading
from types import SimpleNamespace

from companion.agent_lab.acceptance_plan import prepare
from companion.agent_lab.store import TaskStore


def test_compiler_terms_share_the_real_user_literal_audit(tmp_path):
    store = TaskStore(tmp_path / "tasks.sqlite3")
    task = store.create(
        "列验证建议，正文加入准确文字负责人=Alice。", expected_outputs=["摘要.docx"]
    )
    request = "列验证建议，正文加入准确文字负责人=Alice。"
    store.begin_turn(task, request, "auto")
    proposed = ["验证建议", "负责人=Alice", "来源独有名称"]
    store.change(
        task,
        contract_required=True,
        task_contract={
            "deliverables": [
                {
                    "kind": "create",
                    "name": "摘要.docx",
                    "criteria": ["列验证建议"],
                    "required_terms": proposed,
                }
            ]
        },
        content_checks={
            "摘要.docx": {"facts": [], "quotes": [], "sources": [], "terms": proposed}
        },
    )

    class Client:
        config = SimpleNamespace(model="test")
        calls = 0

        def _request(self, payload, cancelled):
            self.calls += 1
            data = json.loads(payload["messages"][1]["content"])
            if "current" in data:
                value = {
                    "slots": [
                        {"members": [c["id"]], "retain": [], "replaces": []}
                        for c in data["current"]
                    ],
                    "discard": [],
                }
            elif "candidates" in data:
                assert {c["text"] for c in data["candidates"]} == {
                    "验证建议",
                    "负责人=Alice",
                }
                value = {
                    "decisions": [
                        {
                            "id": c["id"],
                            "required": c["text"] == "负责人=Alice",
                            "instruction_quote": (
                                "正文加入准确文字负责人=Alice"
                                if c["text"] == "负责人=Alice"
                                else ""
                            ),
                            "reason": (
                                "逐字写入"
                                if c["text"] == "负责人=Alice"
                                else "普通主题允许转述"
                            ),
                        }
                        for c in data["candidates"]
                    ]
                }
            else:
                value = {
                    "files": [
                        {
                            "name": "摘要.docx",
                            "literal_checks": [],
                            "criteria": [
                                {
                                    "index": 0,
                                    "kind": "content",
                                    "items": ["给出合理验证方法"],
                                    "reason": "",
                                }
                            ],
                            "requests": [
                                {
                                    "index": 0,
                                    "kind": "content",
                                    "items": [
                                        "给出合理验证方法",
                                        "正文准确写入负责人=Alice",
                                    ],
                                    "reason": "",
                                }
                            ],
                        }
                    ]
                }
            return {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": json.dumps(value)}}
                ]
            }

    client = Client()
    prepare(client, SimpleNamespace(number=1, cancelled=threading.Event()), store, task)
    state = store.get(task)
    assert state["content_checks"]["摘要.docx"]["terms"] == ["负责人=Alice"]
    assert state["task_contract"]["deliverables"][0]["required_terms"] == proposed
    checks = state["acceptance_plan"]["files"]["摘要.docx"]["checks"]
    assert [c["literal"] for c in checks if "literal" in c] == ["负责人=Alice"]
    assert any(c["requirement"] == "给出合理验证方法" for c in checks)
    assert client.calls == 3
    store.close()
