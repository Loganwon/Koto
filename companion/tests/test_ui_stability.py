"""Long conversations, compact panes, drawers and settings on production HTTP UI."""

from pathlib import Path
import threading

import pytest

from companion.agent import AnswerProposal
from companion.embedded import EmbeddedAPI, PaneServer
from companion.model import EditProposal, ModelConfig


def test_long_conversation_survives_resizes_drawer_settings_and_drafts(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if not edge.exists():
        pytest.skip("Edge required")

    class Model:
        def step(self, **kwargs):
            if kwargs["feedback"]:
                return AnswerProposal("仅回答，已修改的内容保持。" + "内容说明。" * 220)
            return EditProposal("第一段已精简。", "精简")

    class API(EmbeddedAPI):
        def _model(self):
            return Model()

        def fork(self, host, documents):
            return API(host, config=self._config, documents=documents)

    server = PaneServer(
        API("word", config=ModelConfig("https://example.test", "test", "synthetic"))
    )
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
            page.add_init_script(
                path=str(Path(__file__).with_name("word_sdk_fixture.js"))
            )
            page.goto(server.origin + "/ui/?host=word")
            page.wait_for_function("() => !document.querySelector('#start').disabled")
            page.locator("#instruction").fill("精简第一段")
            page.locator("#instruction").press("Enter")
            page.wait_for_function(
                "() => document.querySelector('#after-visible').textContent==='第一段已精简。'"
            )
            for i in range(9):
                question = f"第{i + 1}次追问，只回答"
                page.locator("#instruction").fill(question)
                page.locator("#instruction").press("Enter")
                page.wait_for_function(
                    "text => document.querySelector('#task-request').textContent===text && document.querySelector('#task-status').dataset.phase==='review' && !document.querySelector('#continue').disabled",
                    arg=question,
                )
            assert page.evaluate("fixtureWrites") == 1
            page.wait_for_function(
                "() => document.querySelectorAll('#recent-turns .past-turn').length===9"
            )
            page.wait_for_function(
                "() => {const c=document.querySelector('#conversation');return c.scrollHeight-c.clientHeight-c.scrollTop<4;}"
            )
            draft = "这一条反馈在调整界面时必须保留"
            page.locator("#instruction").fill(draft)
            for mode in ("light", "dark"):
                page.emulate_media(color_scheme=mode)
                for width, height in ((320, 480), (380, 760), (560, 600), (430, 1200)):
                    page.set_viewport_size({"width": width, "height": height})
                    page.wait_for_function(
                        "() => {const c=document.querySelector('#conversation');return c.scrollHeight-c.clientHeight-c.scrollTop<4;}"
                    )
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= innerWidth"
                    )
                    bounds = page.locator("#start").bounding_box()
                    assert bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= height
                    conversation, composer = (
                        page.locator("#conversation").bounding_box(),
                        page.locator(".composer").bounding_box(),
                    )
                    assert (
                        composer["y"] - conversation["y"] - conversation["height"] < 25
                    )
                    page.locator("#files-toggle").click()
                    playwright.expect(page.locator("#files-pane")).to_be_visible()
                    playwright.expect(page.locator("#answer")).to_be_visible()
                    assert page.locator("#instruction").input_value() == draft
                    bounds = page.locator("#start").bounding_box()
                    assert bounds["y"] + bounds["height"] <= height
                    page.locator("#files-close").click()
                    page.locator("#api-status").click()
                    playwright.expect(page.locator("#settings-dialog")).to_be_visible()
                    page.locator("#close-settings").click()
                    assert page.locator("#instruction").input_value() == draft
            assert page.evaluate("fixtureWrites") == 1 and not errors, errors
            page.screenshot(path=str(tmp_path / "stable-compact-pane.png"))
            browser.close()
    finally:
        for api in list(server.sessions.values()):
            api._close()
        server.shutdown()
        server.server_close()
