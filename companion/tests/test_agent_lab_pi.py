"""Actual Pi core against a local API fault server; not a model quality test."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import threading

import pytest

from companion.agent_lab.pi_engine import PiEngine
from companion.agent_lab.runtime import LabSession
from companion.agent_lab.store import TaskStore
from companion.agent_lab.tools import JsonDocument, ToolBroker
from companion.model import ModelConfig


def test_pi_awaits_host_budget_before_any_model_http(tmp_path):
    from companion.tests.test_agent_lab import make_lab
    from companion.contracts import CompanionError

    package = (
        Path(__file__).parents[1]
        / "agent_lab/pi/node_modules/@earendil-works/pi-agent-core"
    )
    if not shutil.which("node") or not package.exists():
        pytest.skip("Opt-in local Pi dependency required")
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            calls.append(True)
            self.send_response(500)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    store, task, broker, _ = make_lab(tmp_path)
    broker.turn.max_model_requests = 0
    engine = PiEngine(
        ModelConfig(
            f"http://127.0.0.1:{server.server_port}", "deepseek-chat", "synthetic-only"
        ),
        timeout=10,
    )
    try:
        with pytest.raises(CompanionError, match="总预算"):
            engine.run(broker, "Only answer", "Test")
        assert not calls
        assert not any(e["kind"] == "model_requested" for e in store.events(task))
    finally:
        store.close()
        server.shutdown()
        server.server_close()


def test_pi_recovers_model_network_failure_without_recreating_verified_file(tmp_path):
    package = (
        Path(__file__).parents[1]
        / "agent_lab/pi/node_modules/@earendil-works/pi-agent-core"
    )
    if not shutil.which("node") or not package.exists():
        pytest.skip("Opt-in local Pi dependency required")
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body)
            index = len(calls)
            if index == 2:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":{"message":"temporary network failure"}}')
                return
            if index in (1, 3):
                name = "create_spreadsheet" if index == 1 else "complete_task"
                arguments = (
                    {
                        "action_id": "one-output",
                        "file_name": "预算.xlsx",
                        "title": "预算",
                        "rows": [["合计", 191.34]],
                    }
                    if index == 1
                    else {"summary": "完成"}
                )
                delta = {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": f"call-{index}",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments, ensure_ascii=False),
                            },
                        }
                    ],
                }
                reason = "tool_calls"
            else:
                delta = {"role": "assistant", "content": "完成"}
                reason = "stop"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for item in [
                {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": reason}]},
            ]:
                self.wfile.write(
                    ("data: " + json.dumps(item, ensure_ascii=False) + "\n\n").encode()
                )
            self.wfile.write(b"data: [DONE]\n\n")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    store = TaskStore(tmp_path / "tasks.sqlite3")
    task = store.create("生成预算.xlsx", expected_outputs=["预算.xlsx"])
    refs = tmp_path / "refs"
    refs.mkdir()
    document = JsonDocument(tmp_path / "document.json", ["original"])
    broker = ToolBroker(
        store, task, refs, tmp_path / "outputs", document, lambda *a: {"allowed": True}
    )
    config = ModelConfig(
        f"http://127.0.0.1:{server.server_port}",
        "deepseek-chat",
        "synthetic-not-a-real-secret",
    )
    session = LabSession(store, task, broker, PiEngine(config, timeout=30))
    try:
        result = session.send("生成预算.xlsx")
        assert result["state"]["phase"] == "complete"
        assert len(list((tmp_path / "outputs").glob("*.xlsx"))) == 1
        assert sum(e["kind"] == "action_verified" for e in store.events(task)) == 1
        assert len(calls) == 4
        assert any(e["kind"] == "model_retry" for e in store.events(task))
    finally:
        session.close()
        store.close()
        server.shutdown()
        server.server_close()
