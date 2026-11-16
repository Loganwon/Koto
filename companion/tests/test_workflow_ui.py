"""Production workflow HTML/RPC and native JS adapters; SDKs are simulated here."""

from functools import partial
from pathlib import Path
import threading

import pytest

from companion.embedded import EmbeddedAPI, PaneServer
from companion.journal import EventJournal
from companion.model import ModelConfig
from companion.workspace import LocalWorkspace
from companion.pane_task_session import PaneTaskSession
from companion.agent_lab.preflight import validate_estimate
from companion.tests.test_pane_task_session import Engine, FixtureRequirements


class Predictor:
    def __init__(self, _config):
        pass

    def predict(self, context, **_kwargs):
        target = context["bound_target"]
        return validate_estimate(
            {
                "summary": "逐段修改，再生成摘要和预算",
                "deliveries": [
                    {
                        "kind": "edit",
                        "name": target["name"],
                        "format": "docx",
                        "target_id": target["id"],
                        "source_ids": ["selection"],
                        "reason": "逐段润色",
                    },
                    {
                        "kind": "create",
                        "name": "摘要.docx",
                        "format": "docx",
                        "target_id": "",
                        "source_ids": ["selection"],
                        "reason": "摘要",
                    },
                    {
                        "kind": "create",
                        "name": "预算.xlsx",
                        "format": "xlsx",
                        "target_id": "",
                        "source_ids": [],
                        "reason": "预算",
                    },
                ],
                "questions": [],
                "warnings": [],
            },
            context,
        )


@pytest.mark.parametrize("host", ["wps", "word"])
@pytest.mark.parametrize("lost_execute", [False, True])
def test_workflow_native_adapter_feedback_and_file_graph(
    tmp_path, monkeypatch, host, lost_execute
):
    playwright = pytest.importorskip("playwright.sync_api")
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if not edge.exists():
        pytest.skip("Edge required")
    monkeypatch.setattr(
        "companion.pane_task_session.WriteVerifier",
        lambda *_: lambda *args: {"allowed": True, "reason": "transport fixture only"},
    )
    workspace = LocalWorkspace()
    root = tmp_path / "sources"
    root.mkdir()
    (root / "资料.txt").write_text("预算191.34", encoding="utf-8")
    workspace.open(root)
    factory = partial(
        PaneTaskSession,
        engine_factory=Engine,
        predictor_factory=Predictor,
        requirements_factory=FixtureRequirements,
    )
    server = PaneServer(
        EmbeddedAPI(
            host,
            workflow_enabled=True,
            task_session_factory=factory,
            state_dir=tmp_path / "state",
            workspace=workspace,
            journal=EventJournal(tmp_path / "journal.db"),
            config=ModelConfig("https://example.test", "test", "fixture-key"),
        )
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(executable_path=str(edge), headless=True)
            page = browser.new_page(viewport={"width": 380, "height": 760})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script(
                (Path(__file__).parent / (host + "_sdk_fixture.js")).read_text(
                    encoding="utf-8"
                )
            )
            if host == "word":
                page.route(
                    "**/office.js", lambda route: route.fulfill(status=200, body="")
                )
            dropped = []
            if lost_execute:

                def drop_reply(route):
                    if dropped:
                        return route.continue_()
                    route.fetch()
                    dropped.append(True)
                    route.abort()

                page.route("**/api/execute_plan", drop_reply)
            page.goto(server.origin + "/ui/?host=" + host)
            page.wait_for_function(
                "() => document.querySelector('#selection-hint').textContent.includes('已选')"
            )
            page.locator("#files-toggle").click()
            source = page.locator('[data-file="资料.txt"]')
            source.wait_for()
            a = source.bounding_box()
            b = page.locator("#task-summary").bounding_box()
            page.mouse.move(a["x"] + 40, a["y"] + 10)
            page.mouse.down()
            page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, steps=10)
            page.mouse.up()
            page.wait_for_function(
                "() => document.querySelector('#summary-inputs').textContent==='1个文件'"
            )
            page.locator("#instruction").fill("精简两段并生成摘要和预算")
            page.locator("#start").click()
            page.wait_for_function(
                "() => document.querySelector('#start').textContent==='开始'"
            )
            assert page.evaluate("fixtureWrites") == 0
            assert page.locator("#task-map").is_hidden()
            page.locator("#task-summary").click()
            assert page.locator('#graph [data-kind="process"]').count() == 1
            assert page.locator("#graph svg").count() == 0
            assert (
                page.locator("#files-pane").is_visible()
                and page.locator("#instruction").is_visible()
            )
            assert page.locator("#selection-preview").is_hidden()
            page.locator("#start").click()
            page.wait_for_function(
                "() => document.querySelector('#review-title').textContent.includes('1 / 2')"
            )
            assert page.evaluate("fixtureWrites") == 1
            page.wait_for_function(
                "() => document.querySelector('#start').textContent==='继续'"
            )
            page.locator("#instruction").fill("更简短，保留数字")
            page.locator("#start").click()
            page.wait_for_function("() => fixtureWrites===2")
            page.wait_for_function(
                "() => document.querySelector('#start').textContent==='继续'"
            )
            page.locator("#start").click()
            page.wait_for_function(
                "() => document.querySelector('#review-title').textContent.includes('2 / 2')"
            )
            assert page.evaluate("fixtureWrites") == 3
            page.locator("#start").click()
            page.wait_for_function(
                "() => document.querySelector('#message').textContent==='已完成。'"
            )
            assert (
                len(list(root.rglob("摘要.docx"))) == 1
                and len(list(root.rglob("预算.xlsx"))) == 1
            )
            assert (
                page.locator('#graph [data-group="outputs"]')
                .inner_text()
                .count("已生成")
                == 2
            )
            page.locator("#history-toggle").click()
            page.locator(".history-row").wait_for()
            assert page.locator(".history-row").count() == 1
            page.locator("#history-close").click()
            page.screenshot(path=str(tmp_path / (host + "-workflow.png")))
            if host == "wps" and not lost_execute:
                import secrets

                page.locator("#instruction").fill("保留未发送的反馈")
                for attached in list(server.sessions.values()):
                    attached._close()
                with server.session_lock:
                    server.sessions.clear()
                    server.instances.clear()
                    server.token = secrets.token_urlsafe(32)
                    server.generation = secrets.token_hex(12)
                page.wait_for_function(
                    "() => document.querySelector('#connection-notice').textContent.includes('旧任务不会重放')"
                )
                assert page.locator("#instruction").input_value() == "保留未发送的反馈"
                assert page.evaluate("fixtureWrites") == 3
            assert not errors, errors
            browser.close()
    finally:
        for api in list(server.sessions.values()):
            api._close()
        server.shutdown()
        server.server_close()
