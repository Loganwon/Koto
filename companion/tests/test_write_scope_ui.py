"""A correct fragment readback cannot hide corruption outside that fragment."""

from pathlib import Path
import threading

import pytest

from companion.embedded import EmbeddedAPI, PaneServer
from companion.model import ModelConfig, EditProposal


def test_wps_scope_corruption_is_uncertain_even_when_fragment_matches(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if not edge.exists():
        pytest.skip("Edge required")

    class Model:
        def step(self, **kwargs):
            return EditProposal("首段已经修改。", "精简")

    class API(EmbeddedAPI):
        def _model(self):
            return Model()

        def fork(self, host, documents):
            return API(host, config=self._config, documents=documents)

    server = PaneServer(
        API("wps", config=ModelConfig("https://example.test", "test", "synthetic"))
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(executable_path=str(edge), headless=True)
            page = browser.new_page(viewport={"width": 380, "height": 760})
            script = (
                Path(__file__)
                .with_name("wps_sdk_fixture.js")
                .read_text(encoding="utf-8")
            )
            script += "\nconst proto=fixtureSelection.constructor.prototype,original=Object.getOwnPropertyDescriptor(proto,'Text');Object.defineProperty(proto,'Text',{get:original.get,set(value){original.set.call(this,value);fixtureText=fixtureText.slice(0,this.End);}});"
            page.add_init_script(script)
            page.goto(server.origin + "/ui/?host=wps")
            page.wait_for_function("() => !document.querySelector('#start').disabled")
            page.locator("#instruction").fill("只修改第一段")
            page.locator("#start").click()
            page.wait_for_function(
                "() => document.querySelector('#task-status').dataset.phase==='uncertain'"
            )
            assert page.evaluate("fixtureWrites") == 1
            assert page.evaluate("fixtureText") == "首段已经修改。"
            assert page.locator("#continue").is_hidden()
            assert page.locator("#review").is_hidden()
            assert page.locator("#retry").is_hidden()
            browser.close()
    finally:
        for api in server.sessions.values():
            api._close()
        server.shutdown()
        server.server_close()
