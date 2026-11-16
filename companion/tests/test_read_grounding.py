"""Read-only follow-ups observe current saved values, not old model prose."""

import threading

from companion.agent_lab.read_grounding import build
from companion.agent_lab.tools import Turn
from companion.tests.test_agent_lab import make_lab


def prepared(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("核对.xlsx",))
    result = broker.invoke(
        "create_workbook",
        {
            "action_id": "real-table",
            "file_name": "核对.xlsx",
            "sheets": [{"name": "季度", "rows": [["差额"], [0], [0]]}],
        },
    )
    assert result["ok"]
    n, e = store.begin_turn(task, "目前有差额么？只回答", "read")
    broker.bind_turn(
        Turn(task, n, e, "目前有差额么？只回答", "read", threading.Event())
    )
    return store, task, broker


def test_fresh_observations_preserve_numeric_zero_and_do_not_change_task(tmp_path):
    store, task, broker = prepared(tmp_path)
    before = store.get(task)
    value = build(broker)
    saved = value["files"][0]
    assert "A2\t0" in saved["content"]["text"]
    assert saved["sha256"] == before["artifacts"]["核对.xlsx"]["sha256"]
    assert not saved["content"]["truncated"] and not value["unread_files"]
    assert store.get(task) == before and broker.turn.writes == 0


def test_external_change_is_reported_without_passing_old_file_text(tmp_path):
    _, _, broker = prepared(tmp_path)
    (broker.outputs / "核对.xlsx").write_bytes(b"changed externally")
    value = build(broker)["files"][0]
    assert "error" in value and "content" not in value and "sha256" not in value


def test_partial_file_retains_valid_pagination_and_explicit_truncation(tmp_path):
    store, task, broker = make_lab(tmp_path, outputs=("长稿.docx",))[:3]
    assert broker.invoke(
        "create_word",
        {
            "action_id": "long",
            "file_name": "长稿.docx",
            "title": "资料",
            "sections": [{"heading": "", "text": "甲" * 800} for _ in range(10)],
        },
    )["ok"]
    n, e = store.begin_turn(task, "只回答", "read")
    broker.bind_turn(Turn(task, n, e, "只回答", "read", threading.Event()))
    content = build(broker)["files"][0]["content"]
    assert len(content["text"]) == 6000 and content["truncated"]
    assert content["end"] == content["next"] == 6000
