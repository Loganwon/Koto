from pathlib import Path
from companion.agent_lab.draft_publication import recover_publication
from companion.tests.test_agent_lab import make_lab


def proposal(broker):
    broker.invoke(
        "set_output_limits",
        {"limits": [{"file_name": "摘要.docx", "max_body_characters": 40}]},
    )
    args = {
        "file_name": "摘要.docx",
        "format": "docx",
        "sections": [{"heading": "", "text": "正确短稿。"}],
    }
    return {
        "tool": "measure_content",
        "arguments": args,
        "result": broker.invoke("measure_content", args),
    }


def test_recovery_publishes_only_expected_new_file_through_write_verifier(tmp_path):
    calls = []

    def verifier(turn, name, args, state):
        calls.append(name)
        return {"allowed": True}

    store, task, broker, doc = make_lab(tmp_path, verifier, outputs=("摘要.docx",))
    observation = proposal(broker)
    assert not list(broker.outputs.iterdir())
    result = recover_publication(broker, observation)
    assert result["result"]["ok"] and "create_word" in calls
    assert store.get(task)["artifacts"]["摘要.docx"]["verified"]
    assert doc.read("0") == "甲方验收后付款。"
    writes = broker.turn.writes
    assert recover_publication(broker, observation) == observation
    assert broker.turn.writes == writes


def test_recovery_honors_latest_permission_denial_and_never_publishes(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("摘要.docx",))
    observation = proposal(broker)
    broker.verifier = lambda *a: {
        "allowed": False,
        "reason": "本轮只回答",
        "kind": "permission",
    }
    assert not recover_publication(broker, observation)["result"]["ok"]
    assert not list(broker.outputs.iterdir())


def test_recovery_does_not_cross_native_review_or_stopped_turn(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("摘要.docx",))
    observation = proposal(broker)
    store.change(task, review={"fragment": "0"})
    assert recover_publication(broker, observation) == observation
    store.change(task, review=None)
    broker.turn.cancelled.set()
    assert recover_publication(broker, observation) == observation
    assert not list(broker.outputs.iterdir())


def test_measurement_rejects_short_draft_missing_registered_sources(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("摘要.docx",))
    (Path(broker.workspace.tree()["root"]) / "source.txt").write_text(
        "真实资料", encoding="utf-8"
    )
    assert broker.invoke(
        "set_content_checks",
        {"file_name": "摘要.docx", "required_sources": ["source.txt"]},
    )["ok"]
    observation = proposal(broker)
    result = observation["result"]
    assert not result["validation"]["passed"]
    assert "next_tool" not in result
    assert "source.txt" in " ".join(result["validation"]["violations"])
