"""Crash-window results are verified on disk, never blindly replayed."""

import pytest
from companion.contracts import ResultUncertain
from companion.tests.test_agent_lab import make_lab
from companion.agent_lab.store import TaskStore


def interrupted(tmp_path):
    store, task, broker, _ = make_lab(tmp_path, outputs=("交付.docx",))
    original = store.receipt

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise SystemExit(71)

    store.receipt = crash
    args = {
        "action_id": "once",
        "file_name": "交付.docx",
        "title": "结果",
        "sections": [{"heading": "", "text": "已写入的真实交付"}],
    }
    with pytest.raises(SystemExit):
        broker.invoke("create_word", args)
    store.close()
    broker.store = TaskStore(tmp_path / "tasks.sqlite3")
    return task, broker, args


def test_verified_result_recovered_without_repeating_file_write(tmp_path):
    task, broker, args = interrupted(tmp_path)
    path = broker.outputs / "交付.docx"
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    with broker.store.running(task):
        assert broker.store.recover_file_results(task, broker.outputs) == ["once"]
        broker.store.begin_turn(task, "继续", "auto")
    result = broker.store.replay(task, "once", {**args, "effect": "create_word"})
    assert result["verified"] and before == (path.read_bytes(), path.stat().st_mtime_ns)
    assert (
        len([e for e in broker.store.events(task) if e["kind"] == "action_recovered"])
        == 1
    )


def test_changed_output_or_unknown_write_still_blocks(tmp_path):
    task, broker, args = interrupted(tmp_path)
    (broker.outputs / "交付.docx").write_bytes(b"externally changed")
    with broker.store.running(task):
        assert not broker.store.recover_file_results(task, broker.outputs)
        with pytest.raises(ResultUncertain):
            broker.store.begin_turn(task, "继续", "auto")
    assert (broker.outputs / "交付.docx").read_bytes() == b"externally changed"
