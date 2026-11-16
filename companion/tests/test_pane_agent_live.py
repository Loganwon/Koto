"""Real model + pane/HTTP; Word/WPS SDKs are simulated, no native apps open."""

import json
from pathlib import Path
import threading
import time

import pytest

from companion.config import config_from_key_file
from companion.embedded import EmbeddedAPI, PaneServer


@pytest.mark.parametrize("host", ["word", "wps"])
def test_real_agent_shows_each_verified_edit_before_feedback(request, tmp_path, host):
    if not request.config.getoption("--live-model"):
        pytest.skip("explicit --live-model required")
    key_file = request.config.getoption("--api-key-file")
    if not key_file:
        pytest.skip("explicit credential file required")
    playwright = pytest.importorskip("playwright.sync_api")
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if not edge.exists():
        pytest.skip("Edge required")
    original = [
        "本季度营收达到240万元，同比增长20%，但还需要继续分析原因。",
        "下一季度我们会改进客户转化流程，并加强线索质量检查，提升团队工作效率。",
        "这段保持不变。",
    ]
    config = config_from_key_file(key_file)
    server = PaneServer(EmbeddedAPI(host, config=config))
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
            fixture = (
                Path(__file__)
                .with_name(host + "_sdk_fixture.js")
                .read_text(encoding="utf-8")
            )
            page.add_init_script(
                fixture
                + "\nwindow.fixtureText="
                + json.dumps("\r".join(original) + "\r", ensure_ascii=False)
                + ";"
            )
            page.goto(server.origin + "/ui/?host=" + host)
            page.wait_for_function("() => !document.querySelector('#start').disabled")
            page.evaluate("""() => {
              window.editEvents=[];window.visibleEdits=[];const scheduled=new Set();
              let writes=window.fixtureWrites;
              Object.defineProperty(window,'fixtureWrites',{get:()=>writes,set:value=>{writes=value;editEvents.push({number:value,at:performance.now()});}});
              new MutationObserver(()=>{
                const latest=editEvents.at(-1),pane=document.querySelector('#after-visible');
                if(latest&&pane.textContent&&!document.querySelector('#review').hidden
                  &&document.querySelector('#progress').textContent.includes(latest.number+' / 2')
                  &&!scheduled.has(latest.at)){
                  scheduled.add(latest.at);
                  requestAnimationFrame(()=>requestAnimationFrame(()=>
                    visibleEdits.push({...latest,text:pane.textContent,visible_ms:performance.now()-latest.at})));
                }
              }).observe(document.querySelector('#conversation'),{childList:true,subtree:true,characterData:true});
            }""")
            started = time.perf_counter()
            page.locator("#instruction").fill(
                "逐段精简选中两段，保留所有数字和事实，每改一段等我检查。"
            )
            page.locator("#instruction").press("Enter")
            page.wait_for_function(
                "() => document.querySelector('#task-status').dataset.phase==='review' && document.querySelector('#progress').textContent.includes('1 / 2')",
                timeout=150000,
            )
            first_seconds = time.perf_counter() - started
            first = page.evaluate("fixtureText.split('\\r')")
            assert first[1:] == original[1:] + [""]
            assert "240" in first[0] and "20%" in first[0]
            assert page.locator("#after-visible").inner_text() == first[0]
            assert page.evaluate("fixtureWrites") == 1
            if host == "wps":
                # A moving caret must not retarget the two pinned edit ranges.
                page.evaluate("() => {const start=fixtureText.indexOf('这段保持不变。');fixtureSelection=new fixtureSelection.constructor(start,start);}")
            page.locator("#instruction").fill(
                "只解释第一段做了什么修改，不要再次修改。"
            )
            page.locator("#instruction").press("Enter")
            page.wait_for_function(
                "() => document.querySelector('#answer').textContent.length>0 && document.querySelector('#task-status').dataset.phase==='review' && !document.querySelector('#continue').disabled",
                timeout=150000,
            )
            assert page.evaluate("fixtureWrites") == 1
            answer = page.locator("#answer").inner_text()
            page.locator("#instruction").fill(
                "下一段先说结论，以“提升工作效率是重点。”开头，再写客户转化和线索检查两项措施。"
            )
            started = time.perf_counter()
            page.locator("#continue").click()
            page.wait_for_function(
                "() => document.querySelector('#task-status').dataset.phase==='review' && document.querySelector('#progress').textContent.includes('2 / 2')",
                timeout=150000,
            )
            second_seconds = time.perf_counter() - started
            second = page.evaluate("fixtureText.split('\\r')")
            assert second[0] == first[0] and second[2:] == original[2:] + [""]
            assert (
                second[1].startswith("提升工作效率是重点。")
                and "转化" in second[1]
                and "线索" in second[1]
            )
            assert page.locator("#after-visible").inner_text() == second[1]
            assert page.evaluate("fixtureWrites") == 2 and not errors, errors
            page.wait_for_function("() => visibleEdits.length===2", timeout=2000)
            events = page.evaluate("visibleEdits")
            assert len(events) == 2 and all(
                0 <= event["visible_ms"] < 750 for event in events
            )
            report = {
                "case": "真实模型侧栏逐段可见与反馈",
                "passed": True,
                "native_editor": False,
                "host": host,
                "editor_sdk": "simulated",
                "model": config.model,
                "checks": {
                    "首段单独显示": True,
                    "追问未重复写入": True,
                    "反馈改变第二段": True,
                    "另外内容未变": True,
                    "每次读回后750毫秒内侧栏可见": True,
                },
                "outputs": [first[0], answer, second[1]],
                "timing": {
                    "first_edit_seconds": round(first_seconds, 3),
                    "second_edit_seconds": round(second_seconds, 3),
                    "pane_visible_ms": [
                        round(event["visible_ms"], 1) for event in events
                    ],
                },
            }
            (tmp_path / "pane-evaluation.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            page.screenshot(path=str(tmp_path / "pane-evaluation.png"))
            browser.close()
    finally:
        for api in list(server.sessions.values()):
            api._close()
        server.shutdown()
        server.server_close()
