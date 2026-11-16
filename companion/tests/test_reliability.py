from concurrent.futures import ThreadPoolExecutor
import threading

import httpx
import pytest

from companion.agent import AnswerProposal
from companion.contracts import CompanionError, OperationCancelled
from companion.model import EditProposal
from companion.requests import RequestCache
from companion.session import EditingSession
from companion.tests.test_model import run_model, response
from companion.tests.test_session import Documents, settled


def test_transient_model_failure_retries_proposal_only():
    calls = []

    def send(request):
        calls.append(True)
        return httpx.Response(503 if len(calls) == 1 else 200, json=response())

    assert run_model(send).text == "Edited fragment"
    assert len(calls) == 2


def test_auth_failure_does_not_retry_or_leak_response():
    calls = []

    def send(request):
        calls.append(True)
        return httpx.Response(401, json={"error": "private-api-key"})

    with pytest.raises(CompanionError) as error:
        run_model(send)
    assert len(calls) == 1 and "private-api-key" not in str(error.value)


def test_stop_during_model_backoff_prevents_retry():
    cancelled = threading.Event()

    def send(request):
        cancelled.set()
        return httpx.Response(429, json={})

    with pytest.raises(OperationCancelled):
        run_model(send, cancelled)


def test_duplicate_ui_request_executes_once_even_concurrently():
    cache = RequestCache()
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def action():
        calls.append(True)
        entered.set()
        assert release.wait(2)
        return {"ok": True}

    with ThreadPoolExecutor() as pool:
        first = pool.submit(cache.run, ("pane", "request"), "same", action)
        assert entered.wait(2)
        second = pool.submit(cache.run, ("pane", "request"), "same", action)
        release.set()
        assert first.result() == second.result() == {"ok": True}
    assert len(calls) == 1


def test_late_submit_cannot_override_an_accepted_stop():
    cache = RequestCache()
    calls = []
    cache.ordered("pane", "stop", 5, lambda: calls.append("stop"))
    result = cache.ordered("pane", "submit", 4, lambda: calls.append("late-write"))
    assert not result["ok"] and calls == ["stop"]
    cache.ordered("pane", "submit", 6, lambda: calls.append("new-request"))
    assert calls[-1] == "new-request"


def test_followup_question_keeps_review_and_next_fragment_direction():
    documents = Documents()
    calls = []
    started, release = threading.Event(), threading.Event()

    class Model:
        def step(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 2:
                return AnswerProposal("这段是概述。")
            if len(calls) == 3:
                started.set()
                assert release.wait(4)
            return EditProposal("先说结论。" + kwargs["current"], "精简")

    session = EditingSession(documents, Model)
    session.connect("word")
    session.start("逐段改写", agent=True)
    assert settled(session)["phase"] == "review"
    session.revise("这段是什么意思？")
    state = settled(session)
    assert state["phase"] == "review" and state["can_continue"] and state["shown"] == 1
    assert state["history"][-2]["content"] == "这段是什么意思？"
    session.advance("后面先说结论")
    assert started.wait(2)
    assert session.snapshot()["answer"] == ""
    release.set()
    assert settled(session)["index"] == 1 and documents.writes == ["one", "two"]
    assert calls[-1]["feedback"][-1] == "后面先说结论"


def test_retry_keeps_request_and_does_not_repeat_an_applied_edit():
    documents = Documents()
    calls = []

    class Model:
        def step(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise CompanionError("temporary connection failure")
            return EditProposal("可靠结果。", "完成")

    session = EditingSession(documents, Model)
    session.submit("保留这个要求")
    assert settled(session)["can_retry"] and documents.writes == []
    session.retry()
    assert settled(session)["phase"] == "review"
    assert calls[0]["instruction"] == calls[1]["instruction"] == "保留这个要求"
    assert documents.writes == ["one"]
    with pytest.raises(CompanionError):
        session.retry()
