"""Production panes, HTTP, agent harness and simulated Office SDK objects."""

import json
from pathlib import Path
import threading

import httpx
import pytest

from companion.agent import WorkspaceAgent
from companion.embedded import EmbeddedAPI, PaneServer
from companion.model import ModelConfig
from companion.tests.test_workspace_agent import response


@pytest.mark.parametrize(
    "host,mode",
    [
        ("excel", "normal"),
        ("excel", "conflict"),
        ("excel", "protected"),
        ("excel", "merged"),
        ("excel", "spill"),
        ("excel", "readonly"),
        ("powerpoint", "normal"),
        ("powerpoint", "partial"),
        ("powerpoint", "conflict"),
        ("powerpoint", "mixed"),
        ("powerpoint", "links"),
        ("powerpoint", "readonly"),
    ],
)
def test_native_adapter_contract_and_incremental_feedback(tmp_path, host, mode):
    playwright = pytest.importorskip("playwright.sync_api")
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if not edge.exists():
        pytest.skip("Edge required")
    calls = []

    def send(request):
        payload = json.loads(request.content)
        task = json.loads(
            [
                message["content"]
                for message in payload["messages"]
                if message["role"] == "user"
            ][-1]
        )
        calls.append(task)
        offered = {item["function"]["name"] for item in payload["tools"]}
        if not task["editable"]:
            return response(("answer_user", {"text": "当前选区只读，请选择普通内容。"}))
        if "declare_task_goal" in offered:
            return response(("declare_task_goal", {
                "target": "current_fragment", "operation": "edit", "summary": "逐处处理当前选区",
            }))
        if host == "excel":
            assert (
                "set_current_cell" in offered and "replace_current_text" not in offered
            )
            value = "132.11" if task["fragment"] == 1 else "87.89"
            return response(
                (
                    "set_current_cell",
                    {
                        "value_type": "number",
                        "value": value,
                        "note": "保持数值类型与格式",
                    },
                )
            )
        assert "replace_current_text" in offered and "set_current_cell" not in offered
        return response(
            (
                "replace_current_text",
                {
                    "text": ("先说结论。" if task["feedback"] else "")
                    + task["current_text"]
                    + "精简。",
                    "note": "保持原版式",
                },
            )
        )

    config = ModelConfig("https://example.test", "test", "synthetic")

    class API(EmbeddedAPI):
        def _model(self):
            return WorkspaceAgent(self._config, httpx.MockTransport(send))

        def fork(self, host, documents):
            return API(host, config=self._config, documents=documents)

    server = PaneServer(API(host, config=config))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(executable_path=str(edge), headless=True)
            page = browser.new_page(viewport={"width": 380, "height": 760})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route(
                "https://appsforoffice.microsoft.com/**",
                lambda route: route.fulfill(
                    body="", content_type="application/javascript"
                ),
            )
            script = (
                Path(__file__)
                .with_name(host + "_sdk_fixture.js")
                .read_text(encoding="utf-8")
            )
            script += "\n" + {
                "protected": "window.fixtureProtection=true;",
                "merged": "window.fixtureMerged=true;",
                "spill": "window.fixtureSpill=true;",
                "mixed": "window.fixtureMixed=true;",
                "links": "window.fixtureLinks=true;",
                "partial": "window.fixturePartial={id:'body',start:5,length:6};",
                "readonly": "Office.context.document.mode='readOnly';",
            }.get(mode, "")
            page.add_init_script(script)
            page.goto(server.origin + "/ui/?host=" + host)
            page.wait_for_function("() => !document.querySelector('#start').disabled")
            page.locator("#instruction").fill("处理选区，每次只改一个，等我检查。")
            page.locator("#start").click()
            if mode in ("protected", "merged", "spill", "mixed", "links", "readonly"):
                page.wait_for_function(
                    "() => document.querySelector('#answer').textContent.includes('只读')"
                )
                assert page.evaluate("fixtureWrites") == 0
            else:
                page.wait_for_function(
                    "() => document.querySelector('#task-status').dataset.phase==='review'"
                )
                assert page.evaluate("fixtureWrites") == 1
                if host == "excel":
                    assert page.evaluate("fixtureGrid[1][1]") == 132.11
                    assert page.evaluate("fixtureGrid[2][1]") == 79.9
                    assert page.evaluate("fixtureFormulas['3,1']") == "=SUM(B2:B3)"
                    assert "预算!B2" in page.locator("#review-title").inner_text()
                elif mode == "partial":
                    assert page.evaluate("fixtureShapes.title.text") == "项目季度总结"
                    assert (
                        page.evaluate("fixtureShapes.body.text")
                        == "下一季度将改进转化流程精简。并加强线索检查。"
                    )
                else:
                    assert (
                        page.evaluate("fixtureShapes.title.text")
                        == "项目季度总结精简。"
                    )
                    assert (
                        page.evaluate("fixtureShapes.body.text")
                        == "下一季度将改进转化流程并加强线索检查。"
                    )
                if mode == "conflict":
                    page.evaluate(
                        "fixtureGrid[1][1]=777"
                        if host == "excel"
                        else "fixtureShapes.title.text='用户刚写入。'"
                    )
                    page.locator("#instruction").fill("再调整")
                    page.locator("#start").click()
                    page.wait_for_function(
                        "() => document.querySelector('#task-status').dataset.phase==='conflict'"
                    )
                    assert page.evaluate("fixtureWrites") == 1
                elif mode != "partial":
                    page.locator("#instruction").fill("下一处先说结论")
                    page.locator("#continue").click()
                    page.wait_for_function(
                        "() => document.querySelector('#progress').textContent.includes('2 / 2')"
                    )
                    assert page.evaluate("fixtureWrites") == 2
                    if host == "excel":
                        assert page.evaluate("fixtureGrid[2][1]") == 87.89
                        assert page.evaluate("typeof fixtureGrid[2][1]") == "number"
                        assert page.evaluate("fixtureGrid[4][2]") == "保持不变"
                    else:
                        assert page.evaluate("fixtureShapes.body.text").startswith(
                            "先说结论。"
                        )
                        assert (
                            page.evaluate("fixtureShapes.other.text")
                            == "这段保持不变。"
                        )
                    assert calls[-1]["feedback"][-1] == "下一处先说结论"
            assert not errors, errors
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            page.screenshot(path=str(tmp_path / (host + "-" + mode + ".png")))
            browser.close()
    finally:
        for api in list(server.sessions.values()):
            api._close()
        server.shutdown()
        server.server_close()
