from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from companion.contracts import OperationCancelled, ResultUncertain, DocumentConflict
from companion.host_rpc import PaneDocuments


def test_queued_cancellation_never_reaches_native_editor():
    documents = PaneDocuments("word", timeout=2)
    gate = threading.Event()
    with ThreadPoolExecutor() as pool:
        work = pool.submit(
            documents.call,
            "replace",
            "doc",
            "range",
            "old",
            "new",
            permitted=lambda: not gate.is_set(),
        )
        while documents.queue.empty():
            gate.wait(0.001)
        gate.set()
        assert documents.poll() is None
        with pytest.raises(OperationCancelled):
            work.result()


@pytest.mark.parametrize("method", ["replace", "replace_cell"])
def test_delivered_write_timeout_is_uncertain_and_late_retry_not_permitted(method):
    documents = PaneDocuments("word", timeout=0.08)
    with ThreadPoolExecutor() as pool:
        work = pool.submit(documents.call, method, "doc", permitted=lambda: True)
        command = documents.poll()
        assert documents.begin(command["id"])
        assert documents.permitted(command["id"])
        with pytest.raises(ResultUncertain):
            work.result()
        assert not documents.permitted(command["id"])
        documents.reply(command["id"], "late result")


def test_native_conflict_is_preserved_and_channels_are_isolated():
    first, second = PaneDocuments("word"), PaneDocuments("word")
    with ThreadPoolExecutor() as pool:
        work = pool.submit(first.read, "doc", "f1")
        command = first.poll()
        assert not second.permitted(command["id"])
        second.reply(command["id"], "wrong document")
        assert not work.done()
        first.reply(
            command["id"], error={"kind": "conflict", "message": "new manual text"}
        )
        with pytest.raises(DocumentConflict):
            work.result()


def test_detach_cancels_pending_operations_and_does_not_replay():
    documents = PaneDocuments("wps")
    with ThreadPoolExecutor() as pool:
        work = pool.submit(documents.read, "doc", "f1")
        command = documents.poll()
        documents.close()
        with pytest.raises(OperationCancelled):
            work.result()
        assert not documents.permitted(command["id"])


@pytest.mark.parametrize("method", ["replace", "replace_cell"])
def test_stop_after_poll_but_before_begin_prevents_native_write(method):
    documents = PaneDocuments("word")
    cancelled = threading.Event()
    with ThreadPoolExecutor() as pool:
        work = pool.submit(
            documents.call, method, permitted=lambda: not cancelled.is_set()
        )
        command = documents.poll()
        cancelled.set()
        assert not documents.begin(command["id"])
        with pytest.raises(OperationCancelled):
            work.result()


@pytest.mark.parametrize("method", ["replace", "replace_cell"])
def test_detach_after_begin_marks_write_uncertain_instead_of_retrying(method):
    documents = PaneDocuments("word")
    with ThreadPoolExecutor() as pool:
        work = pool.submit(documents.call, method, permitted=lambda: True)
        command = documents.poll()
        assert documents.begin(command["id"])
        documents.close()
        with pytest.raises(ResultUncertain):
            work.result()
        assert not documents.begin(command["id"])
        assert not documents.permitted(command["id"])
