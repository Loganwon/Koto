import threading
from companion.tests.test_delivery_acceptance import prepared
from companion.agent_lab.editing_baseline import collect
from companion.agent_lab.tools import Turn


def test_generated_revision_preserves_pre_feedback_version_across_empty_continue(
    tmp_path,
):
    store, task, broker = prepared(tmp_path, lambda *args: {"allowed": True})
    initial = store.get(task)["artifacts"]["简报.pptx"]
    n, epoch = store.begin_turn(
        task, "只把负责人改成Noor，保留其他事实", "auto", interaction="continue"
    )
    broker.bind_turn(
        Turn(
            task,
            n,
            epoch,
            "只把负责人改成Noor，保留其他事实",
            "auto",
            threading.Event(),
        )
    )
    assert collect(broker, "简报.pptx") is None
    artifact = broker.invoke("read_artifact", {"file_name": "简报.pptx"})
    block = next(
        b for b in artifact["editable_blocks"]["blocks"] if "线索" in b["text"]
    )
    changed = broker.invoke(
        "revise_office_text",
        {
            "action_id": "feedback",
            "file_name": "简报.pptx",
            "expected_sha256": initial["sha256"],
            "changes": [
                {
                    "block_id": block["id"],
                    "expected": block["text"],
                    "text": block["text"] + "负责人=Noor。",
                }
            ],
        },
    )
    assert changed["ok"], changed
    before = collect(broker, "简报.pptx")
    assert before["sha256"] == initial["sha256"] and "负责人=Noor" not in before["text"]
    assert "先核查线索" in before["text"]
    store.begin_turn(
        task,
        "Host generated Continue control",
        "auto",
        interaction="continue",
        record_request=False,
    )
    assert collect(broker, "简报.pptx") == before
    store.close()
