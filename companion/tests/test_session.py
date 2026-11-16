import threading
import time

import pytest

from companion.contracts import (
    CompanionError,
    DocumentConflict,
    DocumentTarget,
    Fragment,
    OperationCancelled,
    ResultUncertain,
)
from companion.model import EditProposal
from companion.session import EditingSession


class Documents:
    def __init__(self):
        self.text = {"one": "first original", "two": "second original"}
        self.other_text = "manual input outside the selection"
        self.writes = []

    def connect(self, host):
        return DocumentTarget(
            "pinned-document",
            host,
            "test.docx",
            "selected",
            tuple(Fragment(k, v) for k, v in self.text.items()),
        )

    def read(self, target_id, fragment_id):
        assert target_id == "pinned-document"
        return self.text[fragment_id]

    def replace(self, target_id, fragment_id, expected, replacement, permitted):
        assert target_id == "pinned-document"
        if self.text[fragment_id] != expected:
            raise DocumentConflict("manual edit conflict")
        if not permitted():
            raise OperationCancelled("cancelled before write")
        self.text[fragment_id] = replacement
        self.writes.append(fragment_id)
        return replacement

    def locate(self, *args):
        pass

    def close(self):
        pass


class Model:
    def __init__(self, gated=False):
        self.started = threading.Event()
        self.release = threading.Event()
        if not gated:
            self.release.set()
        self.calls = []

    def propose(self, **kwargs):
        self.calls.append(kwargs)
        self.started.set()
        assert self.release.wait(5)
        return EditProposal(kwargs["current"] + " edited", "shorter wording")


def settled(session):
    deadline = time.monotonic() + 5
    while session.snapshot()["busy"] and time.monotonic() < deadline:
        time.sleep(0.005)
    assert not session.snapshot()["busy"]
    return session.snapshot()


def make_session(gated=False):
    documents, model = Documents(), Model(gated)
    session = EditingSession(documents, lambda: model)
    session.connect("word")
    return session, documents, model


def test_one_visible_fragment_per_feedback_checkpoint():
    session, documents, model = make_session()
    session.start("polish paragraph by paragraph")
    state = settled(session)
    assert state["phase"] == "review"
    assert documents.writes == ["one"]
    assert documents.text["two"] == "second original"
    assert state["latest"]["after"] == documents.text["one"]
    first = documents.text["one"]
    session.advance("Put the conclusion first")
    assert settled(session)["phase"] == "review"
    assert documents.writes == ["one", "two"]
    assert documents.text["one"] == first
    assert model.calls[-1]["feedback"] == ("Put the conclusion first",)
    assert session.advance()["phase"] == "complete"


def test_explicit_read_mode_preserves_existing_edit_checkpoint():
    session, docs, model = make_session()
    session.start("逐段修改")
    before = settled(session)
    model.answer = lambda **kwargs: "这是只读说明。"
    session.ask("解释一下", {"current_text": "最新只读内容"})
    state = settled(session)
    assert state["phase"] == "review" and state["answer"] == "这是只读说明。"
    assert state["target"] == before["target"] and state["latest"] == before["latest"]
    assert state["instruction"] == "逐段修改" and state["shown"] == 1
    session.advance("后面先说结论")
    assert settled(session)["shown"] == 2 and docs.writes == ["one", "two"]
    assert len(model.calls) == 2


def test_other_manual_input_survives_while_model_is_pending():
    session, documents, model = make_session(gated=True)
    session.start("polish")
    assert model.started.wait(2)
    documents.other_text = "new manual text"
    model.release.set()
    assert settled(session)["phase"] == "review"
    assert documents.other_text == "new manual text"


def test_same_range_manual_edit_is_not_overwritten():
    session, documents, model = make_session(gated=True)
    session.start("polish")
    assert model.started.wait(2)
    documents.text["one"] = "user typed this while the model was pending"
    model.release.set()
    assert settled(session)["phase"] == "conflict"
    assert documents.writes == []
    assert documents.text["one"].startswith("user typed")
    with pytest.raises(CompanionError):
        session.advance()


def test_stop_rejects_late_model_proposal_and_can_resume():
    session, documents, model = make_session(gated=True)
    session.start("polish")
    assert model.started.wait(2)
    assert session.stop()["phase"] == "stopping"
    model.release.set()
    assert settled(session)["phase"] == "stopped"
    assert documents.writes == []
    session.advance()
    assert settled(session)["phase"] == "review"
    assert documents.writes == ["one"]


def test_stop_at_review_preserves_current_and_does_not_advance():
    session, documents, _ = make_session()
    session.start("polish")
    settled(session)
    session.stop()
    assert documents.writes == ["one"]
    assert documents.text["two"] == "second original"
    session.advance()
    settled(session)
    assert documents.writes == ["one", "two"]


def test_revise_changes_current_fragment_only():
    session, documents, model = make_session()
    session.start("polish")
    settled(session)
    session.revise("make it more concise")
    assert settled(session)["phase"] == "review"
    assert documents.writes == ["one", "one"]
    assert model.calls[-1]["current"] == "first original edited"
    assert documents.text["two"] == "second original"


def test_invalid_configuration_does_not_consume_review_checkpoint():
    session, documents, _ = make_session()
    session.start("polish")
    settled(session)
    before = session.snapshot()

    def invalid():
        raise CompanionError("configure API")

    session._model_factory = invalid
    with pytest.raises(CompanionError):
        session.advance("next direction")
    assert session.snapshot() == before
    with pytest.raises(CompanionError):
        session.revise("retry current")
    assert session.snapshot() == before
    assert documents.writes == ["one"]


def test_native_unknown_result_blocks_retry():
    session, documents, _ = make_session()

    def unknown(*args):
        raise ResultUncertain("native result unknown")

    documents.replace = unknown
    session.start("polish")
    assert settled(session)["phase"] == "uncertain"
    with pytest.raises(CompanionError):
        session.advance()


def test_rebind_and_double_start_are_rejected_while_running():
    session, documents, model = make_session(gated=True)
    session.start("polish")
    assert model.started.wait(2)
    with pytest.raises(CompanionError):
        session.connect("wps")
    with pytest.raises(CompanionError):
        session.start("second request")
    model.release.set()
    settled(session)
    assert documents.writes == ["one"]


def test_document_changed_before_start_is_checked_without_a_model_call():
    session, documents, model = make_session()
    documents.text["one"] = "newer content"
    session.start("polish")
    assert settled(session)["phase"] == "conflict"
    assert model.calls == []
