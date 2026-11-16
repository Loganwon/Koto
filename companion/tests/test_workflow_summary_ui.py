"""Compact workflow and draft reconciliation at actual sidebar width (browser fixture)."""

import json
from pathlib import Path
import pytest


@pytest.mark.parametrize("edited", [False, True])
def test_external_task_sources_and_local_reference_draft(tmp_path, edited):
    playwright = pytest.importorskip("playwright.sync_api")
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if not edge.exists():
        pytest.skip("Edge required")
    files = [f"资料{i}.docx" for i in range(5)]
    state = {
        "observation": {
            "connected": True,
            "host": "wps",
            "path": "C:/fixture.docx",
            "name": "fixture.docx",
            "current_text": "很长的选区" * 300,
            "selection": {"active": True, "text": "很长的选区" * 300},
        },
        "settings": {"configured": True},
        "session": {
            "phase": "complete",
            "busy": False,
            "message": "已完成。",
            "conversation": {"task_id": "external"},
            "answer": "| 项目 | 值 |\n|---|---|\n| 核对 | <img src=x onerror=alert(1)> |",
            "workflow": {
                "plan_revision": 1,
                "source_ids": files,
                "resources": [
                    {"id": f"s{i}", "file_id": f, "name": f, "revision": "v1"}
                    for i, f in enumerate(files)
                ],
                "prepared": {
                    "id": "plan-external",
                    "summary": "核对资料并生成两份交付",
                    "deliveries": [
                        {
                            "kind": "create",
                            "name": f,
                            "format": f.split(".")[-1],
                            "source_ids": [f"s{i}" for i in range(5)],
                        }
                        for f in ["核对.docx", "核对.xlsx"]
                    ],
                },
                "expected_outputs": ["核对.docx", "核对.xlsx"],
                "artifacts": [
                    {
                        "name": f,
                        "verified": True,
                        "declared_sources": [{"file_id": s} for s in files],
                    }
                    for f in ["核对.docx", "核对.xlsx"]
                ],
            },
        },
    }
    draft = {
        "text": "保留未发送的要求",
        "references": [["本地.txt", {"name": "本地.txt"}]] if edited else [],
        "referencesEdited": edited,
        "fresh": False,
    }
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path=str(edge), headless=True)
        page = browser.new_page(viewport={"width": 320, "height": 900})
        page.add_init_script(
            "window.testState="
            + json.dumps(state, ensure_ascii=False)
            + '; window.pywebview={api:{watch:async()=>({}),status:async()=>testState,workspace_tree:async()=>({entries:[]}),task_turn:async(...args)=>{window.sentTurn=args;return {ok:true};}}};sessionStorage.setItem(\'koto-native-v2:["wps","C:/fixture.docx"]\','
            + json.dumps(json.dumps(draft, ensure_ascii=False))
            + ");"
        )
        page.goto((Path(__file__).parents[1] / "ui/workflow.html").as_uri())
        page.wait_for_function(
            "() => document.querySelector('#summary-inputs').textContent!=='0个文件'"
        )
        assert page.locator("#summary-inputs").inner_text() == (
            "1个文件" if edited else "5个文件"
        )
        assert page.locator("#start").inner_text() == ("更新方案" if edited else "发送")
        assert page.locator("#instruction").input_value() == "保留未发送的要求"
        assert page.locator("#selection-preview").is_hidden()
        assert page.locator("#task-map").is_hidden()
        page.locator("#task-summary").click()
        assert page.locator("#graph svg").count() == 0
        assert page.locator('#graph [data-kind="process"]').count() == 1
        assert (
            page.locator('#graph [data-group="outputs"]').inner_text().count("已生成")
            == 2
        )
        page.locator('#graph [data-group="outputs"] button').first.click()
        assert "来源：" in page.locator("#node-detail").inner_text()
        assert (
            page.locator("#answer table td").last.inner_text()
            == "<img src=x onerror=alert(1)>"
        )
        assert page.locator("#answer img").count() == 0
        assert page.evaluate("document.body.scrollWidth") == 320
        if not edited:
            page.locator("#instruction").fill("只解释刚才的数据来源")
            page.locator("#start").click()
            page.wait_for_function("() => !!window.sentTurn")
            assert page.evaluate("sentTurn") == ["只解释刚才的数据来源", "message"]
            assert page.evaluate("testState.session.conversation.task_id") == "external"
        page.screenshot(path=str(tmp_path / f"compact-{edited}.png"))
        browser.close()
