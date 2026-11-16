"""Crash recovery, duplicate receipts and concurrent pane write coordination."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import threading
import time

import pytest

from companion.journal import EventJournal, document_scope
from companion.model import EditProposal
from companion.session import EditingSession
from companion.tests.test_session import Documents, settled


class FileDocument(Documents):
    def connect(self, host):
        return replace(super().connect(host), path="C:/synthetic/report.docx")


def test_reopen_restores_verified_history_without_rebinding_or_replaying(tmp_path):
    path = tmp_path / "activity.sqlite3"
    journal = EventJournal(path)
    docs = FileDocument()

    class Model:
        def step(self, **kwargs):
            return EditProposal("首段已修改", "精简")

    session = EditingSession(docs, Model, journal=journal)
    session.submit("精简")
    assert settled(session)["phase"] == "review"
    journal.close()
    reopened = EventJournal(path)
    session2 = EditingSession(docs, Model, journal=reopened)
    session2.restore_history({"host": "word", "path": "C:/synthetic/report.docx"})
    state = session2.snapshot()
    assert state["history"][-1]["content"].startswith("已在")
    assert state["recovery"]["last_verified"]["after"] == "首段已修改"
    assert not state["recovery"]["unverified"]
    assert state["target"] is None and not state["can_continue"]
    assert docs.writes == ["one"]


def test_unacknowledged_write_survives_restart_as_uncertain_not_replayable(tmp_path):
    path = tmp_path / "activity.sqlite3"
    scope = document_scope("wps", "C:/synthetic/report.docx")
    journal = EventJournal(path)
    journal.record(
        scope, "task", "turn", "write_requested", {"index": 0}, "cmd1", event_id="e1"
    )
    journal.record(
        scope, "task", "turn", "write_requested", {"index": 0}, "cmd1", event_id="e1"
    )
    journal.close()
    reopened = EventJournal(path)
    recovery = reopened.recovery(scope)
    assert recovery["unverified"] == [{"index": 0}]
    assert recovery["replay_allowed"] is False
    reopened.record(
        scope, "task", "turn", "write_verified", {"after": "实际读回"}, "cmd1"
    )
    assert reopened.recovery(scope)["unverified"] == []


@pytest.mark.parametrize(
    "failed_kind,expected_phase,writes",
    [
        ("write_requested", "error", []),
        ("write_verified", "uncertain", ["one"]),
        ("turn_completed", "uncertain", ["one"]),
    ],
)
def test_journal_failure_never_turns_a_possible_native_write_into_retry(
    failed_kind, expected_phase, writes
):
    class BrokenJournal(EventJournal):
        def record(self, scope, task, turn, kind, *args, **kwargs):
            if kind == failed_kind:
                raise OSError("synthetic disk failure")
            return super().record(scope, task, turn, kind, *args, **kwargs)

    class Model:
        def step(self, **kwargs):
            return EditProposal("修改", "精简")

    docs = FileDocument()
    session = EditingSession(docs, Model, journal=BrokenJournal())
    session.submit("修改")
    state = settled(session)
    assert state["phase"] == expected_phase, state
    assert docs.writes == writes
    assert state["can_retry"] is (not writes)


def test_two_panes_for_one_document_do_not_overlap_native_writes():
    journal = EventJournal()
    inside = 0
    overlap = []

    def writer():
        nonlocal inside
        with journal.document_lock("same-doc"):
            inside += 1
            overlap.append(inside)
            time.sleep(0.01)
            inside -= 1

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: writer(), range(2)))
    assert overlap == [1, 1]


def test_unsaved_and_other_document_histories_are_never_mixed():
    assert document_scope("wps", "") is None
    assert document_scope("wps", "C:/a.docx") != document_scope("wps", "C:/b.docx")


def test_failed_turn_log_does_not_leave_session_busy():
    class FailsOnTurn(EventJournal):
        def record(self, scope, task, turn, kind, *args, **kwargs):
            if kind == "turn_started":
                raise OSError("synthetic disk failure")
            return super().record(scope, task, turn, kind, *args, **kwargs)

    docs = FileDocument()
    session = EditingSession(docs, lambda: object(), journal=FailsOnTurn())
    session.connect("word")
    from companion.contracts import CompanionError

    with pytest.raises(CompanionError, match="尚未开始"):
        session.start("修改")
    assert not session.snapshot()["busy"] and not docs.writes
