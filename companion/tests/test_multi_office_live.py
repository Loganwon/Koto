"""Real DeepSeek and production panes; simulated SDK, no native apps opened."""

import json
from pathlib import Path
import threading
import time

import pytest

from companion.config import config_from_key_file
from companion.embedded import EmbeddedAPI, PaneServer


@pytest.mark.parametrize(
    "host,mode", [("excel", "numbers"), ("excel", "formula"), ("powerpoint", "text")]
)
def test_real_agent_uses_editor_tools_and_applies_feedback(
    request, tmp_path, host, mode
):
    if not request.config.getoption("--live-model"):
        pytest.skip("explicit --live-model required")
    key_file = request.config.getoption("--api-key-file")
    if not key_file:
        pytest.skip("explicit credential file required")
    playwright = pytest.importorskip("playwright.sync_api")
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if not edge.exists():
        pytest.skip("Edge required")
    config = config_from_key_file(key_file)
    server = PaneServer(EmbeddedAPI(host, config=config))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    report = {
        "host": host,
        "mode": mode,
        "native_editor": False,
        "sdk": "simulated",
        "model": config.model,
        "passed": False,
    }
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
            fixture = (
                Path(__file__)
                .with_name(host + "_sdk_fixture.js")
                .read_text(encoding="utf-8")
            )
            if mode == "formula":
                fixture += "\nfixtureSelection={r:3,c:1,rows:1,cols:1};fixtureFormulas['3,1']='=B2+B3';"
            page.add_init_script(fixture)
            page.goto(server.origin + "/ui/?host=" + host)
            page.wait_for_function("() => !document.querySelector('#start').disabled")
            page.evaluate("""() => {
              window.editEvents=[];window.visibleEdits=[];const scheduled=new Set();let writes=fixtureWrites;
              Object.defineProperty(window,'fixtureWrites',{get:()=>writes,set:value=>{writes=value;editEvents.push({number:value,at:performance.now()});}});
              new MutationObserver(()=>{const latest=editEvents.at(-1),pane=document.querySelector('#after-visible');
                if(latest&&pane.textContent&&!document.querySelector('#review').hidden&&!scheduled.has(latest.at)){
                  scheduled.add(latest.at);requestAnimationFrame(()=>requestAnimationFrame(()=>visibleEdits.push({...latest,visible_ms:performance.now()-latest.at})));
                }
              }).observe(document.querySelector('#conversation'),{childList:true,subtree:true,characterData:true});
            }""")
            instruction = {
                "numbers": "将选中的两个预算金额各提高10%，用calculate精确核算，保留两位小数及数值类型。每次只改一个单元格，等我检查。",
                "formula": "把当前单元格公式改为 =SUM(B2:B3) ，必须保留为公式，不能写成计算后的数字。",
                "text": "逐个精简选中的文本框，保留事实，第一个标题改为“季度总结”。每次只改一个文本框，等我检查。",
            }[mode]
            started = time.perf_counter()
            page.locator("#instruction").fill(instruction)
            page.locator("#start").click()
            page.wait_for_function(
                "() => document.querySelector('#task-status').dataset.phase==='review'",
                timeout=150000,
            )
            report["first_seconds"] = round(time.perf_counter() - started, 3)
            assert page.evaluate("fixtureWrites") == 1
            if mode == "numbers":
                assert page.evaluate("fixtureGrid[1][1]") == 132.11
                assert page.evaluate("fixtureGrid[2][1]") == 79.9
                assert page.evaluate("typeof fixtureGrid[1][1]") == "number"
                feedback = "改变方向：下一格改为比原数值提高20%，用calculate计算，保留两位小数。"
            elif mode == "formula":
                assert page.evaluate("fixtureFormulas['3,1']") == "=SUM(B2:B3)"
                assert page.locator("#after-visible").inner_text() == "=SUM(B2:B3)"
                feedback = None
            else:
                assert page.evaluate("fixtureShapes.title.text") == "季度总结"
                assert (
                    page.evaluate("fixtureShapes.body.text")
                    == "下一季度将改进转化流程并加强线索检查。"
                )
                feedback = "下一处以“提升转化效率。”开头，再写改进转化流程和加强线索检查，保持简短。"
            report["first_output"] = page.locator("#after-visible").inner_text()
            if feedback:
                page.locator("#instruction").fill(feedback)
                started = time.perf_counter()
                page.locator("#continue").click()
                page.wait_for_function(
                    "() => document.querySelector('#task-status').dataset.phase==='review' && document.querySelector('#progress').textContent.includes('2 / 2')",
                    timeout=150000,
                )
                report["second_seconds"] = round(time.perf_counter() - started, 3)
                assert page.evaluate("fixtureWrites") == 2
                if mode == "numbers":
                    assert page.evaluate("fixtureGrid[2][1]") == 95.88
                    assert page.evaluate("fixtureGrid[1][1]") == 132.11
                    assert page.evaluate("fixtureFormulas['3,1']") == "=SUM(B2:B3)"
                    assert page.evaluate("fixtureGrid[4][2]") == "保持不变"
                else:
                    text = page.evaluate("fixtureShapes.body.text")
                    assert (
                        text.startswith("提升转化效率。")
                        and "转化流程" in text
                        and "线索" in text
                    )
                    assert page.evaluate("fixtureShapes.title.text") == "季度总结"
                    assert page.evaluate("fixtureShapes.other.text") == "这段保持不变。"
                report["second_output"] = page.locator("#after-visible").inner_text()
            assert not errors, errors
            page.wait_for_function(
                "() => visibleEdits.length===fixtureWrites", timeout=2000
            )
            report["visible_ms"] = [
                round(item["visible_ms"], 1) for item in page.evaluate("visibleEdits")
            ]
            assert all(0 <= value < 750 for value in report["visible_ms"])
            report["writes"] = page.evaluate("fixtureWrites")
            report["passed"] = True
            page.screenshot(path=str(tmp_path / (host + "-" + mode + ".png")))
            browser.close()
    finally:
        (tmp_path / "evaluation.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for api in list(server.sessions.values()):
            api._close()
        server.shutdown()
        server.server_close()
