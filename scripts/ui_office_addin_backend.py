"""Drive production HTTP handlers over stdin for browser QA without TCP access.

The model and Office SDK are fixtures. Routing, authenticated bridge, task store,
native host adapters, conflict checks and task-pane UI are production code.
"""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from http.client import HTTPResponse
from io import BytesIO
import json
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from companion.embedded import EmbeddedAPI, PaneHandler, PaneServer
from companion.journal import EventJournal
from companion.model import ModelConfig
from companion.workspace import LocalWorkspace
from companion.pane_task_session import PaneTaskSession
from companion.agent_lab.preflight import validate_estimate
from companion.tests.test_pane_task_session import FixtureRequirements
import companion.pane_task_session as session_module


class Predictor:
    def __init__(self, _config):
        pass

    def predict(self, context, **_kwargs):
        target = context["bound_target"]
        return validate_estimate({
            "summary": "精简当前选区，保留事实和数字，逐处写回原文供检查。",
            "deliveries": [{"kind": "edit", "name": target["name"], "format": "docx",
                "target_id": target["id"], "source_ids": ["selection"], "reason": "润色选区"}],
            "questions": [], "warnings": [],
        }, context)


class Engine:
    def __init__(self, *_args):
        pass

    def run(self, broker, _prompt, _message):
        read = broker.invoke("read_current_document", {"start": 0, "limit": 1200})
        assert read["ok"], read
        fragment = sorted(broker.allowed_fragments)[0]
        old = broker.document.read(fragment)
        text = "本季度营收240万元，同比增长20%；需进一步分析增长原因。"
        if broker.interaction == "feedback":
            text = "本季度营收240万元，同比增长20%。增长原因有待进一步分析。"
        result = broker.invoke("apply_edit", {"action_id": "edit-" + str(broker.turn.number),
            "fragment_id": fragment, "expected": old, "text": text, "reason": "精简表述，保留数字和原意。"})
        assert result["ok"], result
        return "已在原文更新这一段，保留了营收与增长率。请在文档中检查，也可以继续给我反馈。"

    def close(self):
        pass


class MemorySocket:
    def __init__(self, data):
        self.input, self.output = BytesIO(data), BytesIO()

    def makefile(self, *_args, **_kwargs):
        return self.input

    def sendall(self, data):
        self.output.write(data)

    def gettimeout(self):
        return None

    def settimeout(self, _timeout):
        pass


def main():
    state = Path(sys.argv[1])
    state.mkdir(parents=True, exist_ok=True)
    workspace = LocalWorkspace()
    sources = state / "references"
    sources.mkdir(exist_ok=True)
    (sources / "季度参考.txt").write_text("营收240万元，同比增长20%。", encoding="utf-8")
    workspace.open(sources)
    session_module.WriteVerifier = lambda *_: lambda *_: {"allowed": True, "reason": "QA fixture"}
    server = PaneServer(EmbeddedAPI("wps", workflow_enabled=True,
        task_session_factory=partial(PaneTaskSession, engine_factory=Engine,
            predictor_factory=Predictor, requirements_factory=FixtureRequirements),
        workspace=workspace, state_dir=state / "tasks", journal=EventJournal(state / "journal.sqlite3"),
        config=ModelConfig("https://example.test", "fixture-model", "not-a-key")))
    output_lock = threading.Lock()

    def respond(value):
        with output_lock:
            print(json.dumps(value, ensure_ascii=False), flush=True)

    def handle(request):
        try:
            body = request.get("body", "").encode("utf-8")
            headers = {k: v for k, v in request.get("headers", {}).items()
                if k.lower() not in ("host", "content-length", "connection", "accept-encoding")}
            headers["Host"] = server.origin.split("//", 1)[1]
            headers["Content-Length"] = str(len(body))
            raw = (request["method"] + " " + request["path"] + " HTTP/1.0\r\n" +
                "\r\n".join(k + ": " + v for k, v in headers.items()) + "\r\n\r\n").encode("latin-1") + body
            sock = MemorySocket(raw)
            PaneHandler(sock, ("127.0.0.1", 0), server)
            response = HTTPResponse(MemorySocket(sock.output.getvalue()))
            response.begin()
            respond({"id": request["id"], "status": response.status,
                "headers": dict(response.getheaders()), "body": base64.b64encode(response.read()).decode("ascii")})
        except Exception as error:
            respond({"id": request["id"], "error": repr(error)})

    respond({"origin": server.origin})
    with ThreadPoolExecutor(max_workers=16) as pool:
        for line in sys.stdin:
            pool.submit(handle, json.loads(line))
    for api in server.sessions.values():
        api._close()
    server.server_close()


if __name__ == "__main__":
    main()
