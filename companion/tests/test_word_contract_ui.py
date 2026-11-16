"""Official Word batch/range contract exercised through the real pane transport."""

from pathlib import Path
import threading

import pytest

from companion.agent import AnswerProposal
from companion.embedded import EmbeddedAPI, PaneServer
from companion.model import EditProposal, ModelConfig


def test_word_batches_keep_ranges_and_feedback_across_turns(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if not edge.exists():
        pytest.skip("Edge required")
    calls = []
    entered = threading.Event()
    release = threading.Event()

    class Model:
        def step(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                entered.set()
                assert release.wait(8)
            if len(calls) == 2:
                return AnswerProposal("这段是概述，已完成的修改保留。")
            return EditProposal(
                ("先说结论。" if kwargs["feedback"] else "")
                + kwargs["current"]
                + "精简。",
                "精简",
            )

    class API(EmbeddedAPI):
        def _model(self):
            return Model()

        def fork(self, host, documents):
            return API(host, config=self._config, documents=documents)

    server = PaneServer(
        API("word", config=ModelConfig("https://example.test", "test", "synthetic"))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(executable_path=str(edge), headless=True)
            page = browser.new_page(viewport={"width": 380, "height": 1200})
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
            page.wait_for_function(
                "() => document.querySelector('#selection-hint').textContent.includes('已选')"
            )
            assert page.locator("#target-name").inner_text() == "Word.docx"
            assert page.locator("#instruction").bounding_box()["y"] < 180
            page.locator("#instruction").fill("逐段精简")
            page.locator("#start").click()
            assert entered.wait(4)
            page.locator("#instruction").fill("这段什么意思？")
            release.set()
            page.wait_for_function("() => !document.querySelector('#review').hidden")
            assert page.locator("#instruction").input_value() == "这段什么意思？"
            first = page.evaluate("fixtureText")
            assert first == "第一段原文。精简。\r第二段原文。\r第三段保留。\r"
            page.locator("#start").click()
            page.wait_for_function(
                "() => document.querySelector('#answer').textContent.includes('概述')"
            )
            assert page.evaluate("fixtureWrites") == 1
            page.locator("#instruction").fill("后面先说结论")
            page.locator("#continue").click()
            page.wait_for_function(
                "() => document.querySelector('#after-visible').textContent.startsWith('先说结论')"
            )
            assert (
                page.evaluate("fixtureText")
                == "第一段原文。精简。\r先说结论。第二段原文。精简。\r第三段保留。\r"
            )
            assert calls[-1]["feedback"][-1] == "后面先说结论"
            assert page.locator("#recent-turns .past-turn").count() >= 2
            page.screenshot(path=str(tmp_path / "compact-word-pane.png"))
            browser.close()
    finally:
        release.set()
        for api in list(server.sessions.values()):
            api._close()
        server.shutdown()
        server.server_close()
