"""Content failures never become a permission grant or a spurious turn lock."""

import json
from types import SimpleNamespace

import pytest

from companion.agent_lab.runtime import WriteVerifier
from companion.tests.test_agent_lab import make_lab


@pytest.mark.parametrize("authorized", [True, False])
def test_recheck_has_no_prose_and_keeps_original_rejection(tmp_path, authorized):
    store, task, broker, _ = make_lab(tmp_path, outputs=("简报.pptx",))
    created = broker.invoke(
        "create_presentation",
        {
            "action_id": "create",
            "file_name": "简报.pptx",
            "title": "简报",
            "sections": [{"heading": "页", "text": "原稿"}],
        },
    )
    actual = broker.invoke("read_artifact", {"file_name": "简报.pptx"})
    block = next(b for b in actual["editable_blocks"]["blocks"] if b["text"] == "原稿")
    calls = []

    class Client:
        config = SimpleNamespace(model="test")

        def _request(self, payload, cancelled):
            calls.append(payload)
            value = (
                {"allowed": False, "kind": "permission", "reason": "正文不合格"}
                if len(calls) == 1
                else {"authorized": authorized, "reason": "对象范围核对"}
            )
            return {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": json.dumps(value)}}
                ]
            }

    verifier = WriteVerifier.__new__(WriteVerifier)
    verifier.client, verifier.store, verifier.task = Client(), store, task
    # This test exercises only intent/authority, not the independent compiler.
    broker.verifier = lambda turn, tool, args, state: verifier(turn, tool, args, state)
    result = broker.invoke(
        "revise_office_text",
        {
            "action_id": "rejected",
            "file_name": "简报.pptx",
            "expected_sha256": created["receipt"]["sha256"],
            "changes": [
                {"block_id": block["id"], "expected": "原稿", "text": "特定拟稿正文"}
            ],
        },
    )
    assert not result["ok"] and broker.turn.write_denied is (not authorized)
    assert (
        store.get(task)["artifacts"]["简报.pptx"]["sha256"]
        == created["receipt"]["sha256"]
    )
    assert len(calls) == 2
    scope = json.loads(calls[1]["messages"][1]["content"])
    assert scope["object"] == {"file_name": "简报.pptx"}
    assert "特定拟稿正文" not in json.dumps(calls[1], ensure_ascii=False)
