"""Time windows can continue verified work without a new user turn or authority."""

import time

import pytest

from companion.agent_lab.runtime import LabSession
from companion.tests.test_agent_lab import make_lab


@pytest.mark.parametrize(
    "block",
    [None, "no_progress", "stopped", "uncertain", "permission", "second_timeout"],
)
def test_bounded_progress_window_keeps_same_request_and_preserves_stops(
    tmp_path, block
):
    store, task, broker, _ = make_lab(tmp_path, outputs=("摘要.docx",))

    class Engine:
        supports_progress_windows = True
        max_models = 60
        calls = 0

        def run(self, current, prompt, message):
            self.calls += 1
            if self.calls == 1:
                if block != "no_progress":
                    assert current.invoke(
                        "create_word",
                        {
                            "action_id": "make",
                            "file_name": "摘要.docx",
                            "title": "摘要",
                            "sections": [{"heading": "", "text": "真实结果"}],
                        },
                    )["ok"]
                current.turn.deadline = time.monotonic() - 1
                if block == "stopped":
                    session.stop()
                elif block == "uncertain":
                    store.change(task, phase="uncertain")
                elif block == "permission":
                    current.turn.write_denied = True
                raise TimeoutError("执行窗口到限")
            assert (
                current.turn.reset_model_context and current.turn.progress_windows == 2
            )
            assert current.turn.number == expected_turn
            assert current.turn.writes == 1
            assert "真实结果" not in message  # No fabricated follow-up user input.
            if block == "second_timeout":
                current.turn.deadline = time.monotonic() - 1
                raise TimeoutError("第二窗口到限")
            assert current.invoke("complete_task", {"summary": "实际交付完成"})["ok"]
            return "已核对交付"

        def close(self):
            pass

    engine = Engine()
    session = LabSession(store, task, broker, engine)
    expected_turn = broker.turn.number + 1
    if block is None:
        result = session.send("生成摘要文件，不修改原文")
        assert result["state"]["phase"] == "complete" and engine.calls == 2
    else:
        with pytest.raises(TimeoutError):
            session.send("生成摘要文件，不修改原文")
        assert engine.calls == (2 if block == "second_timeout" else 1)
    events = store.events(task)
    requests = [e for e in events if e["kind"] == "user_message"]
    assert len(requests) == 2  # Existing setup turn plus exactly one true send.
    extensions = [e for e in events if e["kind"] == "execution_window_extended"]
    assert len(extensions) == (1 if block in (None, "second_timeout") else 0)
