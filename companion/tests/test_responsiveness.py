"""Latency and cancellation contracts, without relying on model timing."""

import json
from types import SimpleNamespace
import threading
import time

import httpx
import pytest

from companion.agent import WorkspaceAgent
from companion.contracts import CompanionError
from companion.model import ModelConfig
from companion.session import EditingSession
from companion.streaming import answer_prefix
from companion.tests.test_session import Documents, settled
from companion.window_layout import FileDrawer


def packet(delta, finish=None):
    return (
        "data: "
        + json.dumps(
            {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]},
            ensure_ascii=False,
        )
        + "\n\n"
    ).encode("utf-8")


@pytest.mark.parametrize("stop", [False, True])
def test_streaming_answer_is_visible_before_completion_and_stop_rejects_late_answer(
    stop,
):
    started, release = threading.Event(), threading.Event()

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield packet(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "answer1",
                            "function": {
                                "name": "answer_user",
                                "arguments": '{"text":"已看到的部分',
                            },
                        }
                    ]
                }
            )
            started.set()
            assert release.wait(5)
            yield packet(
                {
                    "tool_calls": [
                        {"index": 0, "function": {"arguments": '，完整回答。"}'}}
                    ]
                }
            )
            yield packet({}, "tool_calls")
            yield b"data: [DONE]\n\n"

    model = WorkspaceAgent(
        ModelConfig("https://example.test", "test", "secret"),
        httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=Stream()
            )
        ),
    )
    documents = Documents()
    session = EditingSession(documents, lambda: model)
    session.connect("word")
    session.start("总结选中的内容", agent=True)
    assert started.wait(2)
    assert session.snapshot()["answer"] == "已看到的部分"
    assert session.snapshot()["busy"] and not documents.writes
    if stop:
        session.stop()
    release.set()
    state = settled(session)
    assert state["phase"] == ("stopped" if stop else "answered"), state["message"]
    if not stop:
        assert state["answer"] == "已看到的部分，完整回答。"
    assert not documents.writes


def test_interrupted_stream_cannot_apply_even_complete_looking_edit_arguments():
    raw = packet(
        {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "write1",
                    "function": {
                        "name": "replace_current_text",
                        "arguments": '{"text":"不可写入","note":"连接中断"}',
                    },
                }
            ]
        }
    )
    model = WorkspaceAgent(
        ModelConfig("https://example.test", "test", "secret"),
        httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=raw
            )
        ),
    )
    docs = Documents()
    session = EditingSession(docs, lambda: model)
    session.connect("word")
    session.start("改一下", agent=True)
    state = settled(session)
    assert state["phase"] == "error" and "中断" in state["message"]
    assert not docs.writes


def test_submit_returns_immediately_while_native_binding_waits_and_can_be_stopped():
    started, release = threading.Event(), threading.Event()

    class SlowDocument(Documents):
        def bind_current(self, host):
            started.set()
            assert release.wait(5)
            return self.connect("word")

    class NeverCalled:
        def step(self, **kwargs):
            raise AssertionError("cancelled binding must not call the model")

    docs = SlowDocument()
    session = EditingSession(docs, NeverCalled)
    before = time.perf_counter()
    state = session.submit("总结我选中的内容")
    assert time.perf_counter() - before < 0.1
    assert started.wait(1) and state["busy"] and state["phase"] == "connecting"
    session.stop()
    release.set()
    assert settled(session)["phase"] == "stopped" and not docs.writes


def test_selected_question_does_not_eagerly_read_full_document():
    class SelectedDocument(Documents):
        def text_snapshot(self, target):
            raise AssertionError("full text must be lazy")

        def agent_context(self, target):
            return {"selection": {"text": "我选中的文字"}}

    def handler(request):
        user = json.loads(json.loads(request.content)["messages"][-1]["content"])
        assert user["current_document"]["loaded"] is False
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "选中文字的摘要。"},
                    }
                ]
            },
        )

    model = WorkspaceAgent(
        ModelConfig("https://example.test", "test", "secret"),
        httpx.MockTransport(handler),
    )
    docs = SelectedDocument()
    session = EditingSession(docs, lambda: model)
    session.connect("word")
    session.start("总结选中内容", agent=True)
    assert settled(session)["phase"] == "answered" and not docs.writes


def test_file_drawer_expands_left_and_keeps_chat_width_and_right_edge(monkeypatch):
    import webview

    monkeypatch.setattr(
        webview, "screens", [SimpleNamespace(x=0, y=0, width=1920, height=1080)]
    )

    class Window:
        x, y, width, height = 800, 100, 430, 700

        def restore(self):
            pass

        def resize(self, width, height, fix_point):
            self.x += self.width - width
            self.width, self.height = width, height

        def move(self, x, y):
            self.x, self.y = x, y

    drawer, window = FileDrawer(), Window()
    drawer.set_open(window, True)
    assert window.width == 654 and window.x == 576
    assert window.x + drawer.width == 800 and window.width - drawer.width == 430
    drawer.set_open(window, True)
    assert window.width == 654
    drawer.set_open(window, False)
    assert (window.x, window.width) == (800, 430)


def test_streaming_json_prefix_handles_escaped_characters():
    assert answer_prefix('{"text":"第一句\\n第二句') == "第一句\n第二句"
    assert answer_prefix('{"text":"中文\\u4') == "中文"
    assert answer_prefix('{"text":"含有\\"引用') == '含有"引用'
    assert answer_prefix('{"text":"完整"}') == "完整"
