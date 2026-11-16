"""Real pane HTML + JS native adapter + HTTP RPC + editing checkpoints.

The editor object is simulated; this test is not native WPS acceptance.
"""

from pathlib import Path
import threading

import pytest

from companion.embedded import EmbeddedAPI, PaneServer
from companion.model import EditProposal, ModelConfig

FAKE_WPS = r"""
window.fixtureText='原始第一段。\r原始第二段。\r';
window.fixtureWrites=0;
class Range {
  constructor(start,end){this.Start=start;this.End=end;this.StoryType=1;this.Font={Bold:0,Italic:0,Underline:0,Size:12,Color:0,Hidden:0,StrikeThrough:0,NameAscii:'Arial',NameFarEast:'宋体',NameOther:'Arial',NameBi:'Arial'};for(const key of ['Fields','InlineShapes','Hyperlinks','ContentControls'])this[key]={Count:0};}
  get Text(){return fixtureText.slice(this.Start,this.End);}
  set Text(text){fixtureWrites++;fixtureText=fixtureText.slice(0,this.Start)+text+fixtureText.slice(this.End);this.End=this.Start+text.length;}
  get Duplicate(){return new Range(this.Start,this.End);}
  get Paragraphs(){return {Count:1,Item:()=>({Range:new Range(0,fixtureText.indexOf('\r')+1)})};}
  Select(){window.fixtureSelection=this;}
}
window.fixtureSelection=new Range(0,6);
window.wps={get Selection(){return {Range:fixtureSelection};},ActiveDocument:{Name:'测试.docx',FullName:'C:/synthetic/测试.docx',Saved:false,ReadOnly:false,ProtectionType:-1,Range:(a,b)=>new Range(a,b),get Content(){return new Range(0,fixtureText.length);}}};
"""


@pytest.mark.parametrize(
    "fault",
    [
        "normal",
        "lost_reply",
        "lost_submit",
        "lost_poll",
        "lost_begin",
        "lost_reply_ack",
        "restart",
    ],
)
def test_real_embedded_transport_writes_one_fragment_and_keeps_manual_edits(
    tmp_path, fault
):
    playwright = pytest.importorskip("playwright.sync_api")
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if not edge.exists():
        pytest.skip("Edge required")

    class Model:
        def step(self, **kwargs):
            return EditProposal(kwargs["current"] + " 已改。", "更简洁")

    class API(EmbeddedAPI):
        def _model(self):
            return Model()

        def fork(self, host, documents):
            return API(host, config=self._config, documents=documents)

    server = PaneServer(
        API("wps", config=ModelConfig("https://example.test", "test", "not-a-real-key"))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(executable_path=str(edge), headless=True)
            page = browser.new_page(viewport={"width": 380, "height": 760})
            page.add_init_script(FAKE_WPS)
            injected = []
            path = {
                "lost_reply": "/host/reply",
                "lost_submit": "/api/submit",
                "lost_poll": "/host/poll",
                "lost_begin": "/host/begin",
                "lost_reply_ack": "/host/reply",
            }.get(fault)
            if path:

                def interrupt(route):
                    if injected:
                        return route.continue_()
                    if fault == "lost_poll":
                        response = route.fetch()
                        if not response.json():
                            return route.fulfill(response=response)
                    elif fault in ("lost_submit", "lost_begin", "lost_reply_ack"):
                        route.fetch()
                    injected.append(True)
                    route.abort()

                page.route("**" + path, interrupt)
            page.goto(server.origin + "/ui/?host=wps")
            page.wait_for_function(
                "() => document.querySelector('#selection-hint').textContent.includes('已选')"
            )
            page.locator("#instruction").fill("润色选中文字")
            page.locator("#start").click()
            page.wait_for_function("() => !document.querySelector('#review').hidden")
            assert page.evaluate("fixtureText") == "原始第一段。 已改。\r原始第二段。\r"
            assert page.evaluate("fixtureWrites") == 1
            assert fault in ("normal", "restart") or injected
            assert (
                page.locator("#instruction").bounding_box()["y"]
                - page.locator("#conversation").bounding_box()["y"]
                - page.locator("#conversation").bounding_box()["height"]
                < 25
            )
            if fault == "restart":
                import secrets

                page.locator("#instruction").fill("保留这条未发送的反馈")
                for api in list(server.sessions.values()):
                    api._close()
                with server.session_lock:
                    server.sessions.clear()
                    server.instances.clear()
                    server.token = secrets.token_urlsafe(32)
                    server.generation = secrets.token_hex(12)
                page.wait_for_function(
                    "() => document.querySelector('#connection-notice').textContent.includes('旧任务不会重放')"
                )
                assert (
                    page.locator("#instruction").input_value() == "保留这条未发送的反馈"
                )
                page.wait_for_function(
                    "() => document.querySelector('#recent-turns .past-turn')!==null"
                )
                assert page.evaluate("fixtureWrites") == 1
                browser.close()
                return
            assert page.locator("#after-visible").inner_text() == "原始第一段。 已改。"
            page.evaluate(
                "fixtureText='用户刚改。'+fixtureText.slice(fixtureText.indexOf('\\r'))"
            )
            page.locator("#instruction").fill("更短")
            page.locator("#start").click()
            page.wait_for_function(
                "() => document.querySelector('#task-status').dataset.phase==='conflict'"
            )
            assert page.evaluate("fixtureText").startswith("用户刚改。")
            page.screenshot(path=str(tmp_path / "embedded-pane.png"))
            browser.close()
    finally:
        for api in list(server.sessions.values()):
            api._close()
        server.shutdown()
        server.server_close()
