"""Regression for WPS legacy CSS, file overlap and completed-task dead ends."""

from pathlib import Path
import re
import threading

import pytest

from companion.embedded import EmbeddedAPI, PaneServer
from companion.model import EditProposal, ModelConfig
from companion.workspace import LocalWorkspace
from companion.tests.test_embedded_ui import FAKE_WPS


@pytest.fixture
def pane(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if not edge.exists():
        pytest.skip("Edge required")
    root = tmp_path / "工作资料"
    (root / "预算").mkdir(parents=True)
    (root / "预算" / "研发.txt").write_text("研发120万元", encoding="utf-8")
    (root / "预算" / "运营.txt").write_text("运营80万元", encoding="utf-8")
    (root / "说明.md").write_text("另一个文件", encoding="utf-8")
    workspace = LocalWorkspace()
    workspace.open(root)
    instructions = []

    class Model:
        def step(self, **kwargs):
            instructions.append(kwargs)
            return EditProposal(kwargs["current"] + " 更简洁。", "精简表达")

    class API(EmbeddedAPI):
        def _model(self):
            return Model()

        def fork(self, host, documents):
            return API(
                host,
                config=self._config,
                workspace=self._workspace,
                documents=documents,
            )

    server = PaneServer(
        API(
            "wps",
            config=ModelConfig("https://example.test", "test", "synthetic"),
            workspace=workspace,
        )
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(executable_path=str(edge), headless=True)
            page = browser.new_page(viewport={"width": 380, "height": 880})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script(FAKE_WPS)

            # Simulate a renderer which cannot parse the newer CSS color/height
            # features. The production UI must remain opaque and fully bounded.
            def legacy_css(route):
                response = route.fetch()
                css = re.sub(r"\blight-dark\(", "unsupported-color(", response.text())
                css = re.sub(r"(\d+)dvh\b", r"\1unsupported-height", css)
                route.fulfill(response=response, body=css)

            page.route("**/style.css", legacy_css)
            page.goto(server.origin + "/ui/?host=wps")
            page.wait_for_function("() => !document.querySelector('#start').disabled")
            yield page, instructions, tmp_path
            assert not errors, errors
            browser.close()
    finally:
        for api in list(server.sessions.values()):
            api._close()
        server.shutdown()
        server.server_close()


def test_legacy_wps_colors_and_parallel_columns_never_overlap(pane):
    page, _, output = pane
    for scheme in ("light", "dark"):
        page.emulate_media(color_scheme=scheme)
        for width, height in ((300, 480), (380, 880), (520, 650)):
            page.set_viewport_size({"width": width, "height": height})
            page.locator("#files-toggle").click()
            assert page.locator(".assistant").is_visible()
            assert page.locator("#files-pane").is_visible()
            color = page.locator("#files-pane").evaluate(
                "el=>getComputedStyle(el).backgroundColor"
            )
            assert color == (
                "rgb(245, 245, 245)" if scheme == "light" else "rgb(42, 42, 42)"
            )
            files = page.locator("#files-pane").bounding_box()
            assistant = page.locator(".assistant").bounding_box()
            assert 112 <= files["width"] <= 216
            assert files["x"] + files["width"] <= assistant["x"]
            assert assistant["width"] >= 168
            button = page.locator("#start").bounding_box()
            assert button["x"] >= assistant["x"]
            assert button["x"] + button["width"] <= width
            assert button["y"] + button["height"] <= height
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
            page.screenshot(path=str(output / f"columns-{width}-{scheme}.png"))
            page.locator("#files-close").click()
            button = page.locator("#start").bounding_box()
            assert button["y"] + button["height"] <= height
    page.set_viewport_size({"width": 380, "height": 880})
    page.emulate_media(color_scheme="light")
    page.screenshot(path=str(output / "chat.png"))


def test_search_select_multiple_files_and_keep_draft(pane):
    page, instructions, output = pane
    page.locator("#instruction").fill("把资料整理进当前段落")
    page.locator("#attach-files").click()
    page.locator("#file-filter").fill("预算")
    assert page.locator("#file-tree .reference-file").count() == 2
    page.locator("#file-tree .reference-file").nth(0).click()
    page.locator("#file-tree .reference-file").nth(1).click()
    assert page.locator("#file-tree [aria-selected=true]").count() == 2
    assert page.locator("#files-selection-summary").inner_text() == "已引用 2 个"
    page.screenshot(path=str(output / "files.png"))
    assert page.locator(".assistant").is_visible()
    assert page.locator("#instruction").input_value() == "把资料整理进当前段落"
    assert page.locator("#reference-chips .reference-chip").count() == 2
    page.screenshot(path=str(output / "references.png"))
    page.locator("#start").click()
    page.wait_for_function(
        "() => document.querySelector('#task-status').dataset.phase==='review'"
    )
    assert '@"预算/研发.txt"' in instructions[0]["instruction"]
    assert '@"预算/运营.txt"' in instructions[0]["instruction"]
    assert page.locator("#reference-chips").is_hidden()
    assert page.locator("#task-request").inner_text().count("「") == 2
    assert page.locator("#files-pane").is_visible()
    assert page.locator("#file-filter").input_value() == "预算"
    page.screenshot(path=str(output / "review-with-files.png"))
    page.locator("#instruction").fill("换成更直接的表达")
    page.locator("#start").click()
    page.wait_for_function(
        "() => fixtureWrites===2 && !document.querySelector('#continue').disabled"
    )
    assert instructions[-1]["feedback"] == ("换成更直接的表达",)
    assert page.locator("#files-pane").is_visible()


def test_file_action_error_is_visible_on_the_file_page(pane):
    page, _, _ = pane
    page.locator("#files-toggle").click()
    page.route(
        "**/api/choose_folder",
        lambda route: route.fulfill(
            json={"ok": False, "error": "请先等待当前任务完成。"}
        ),
    )
    page.locator("#choose-folder").click()
    page.wait_for_function("() => !document.querySelector('#files-error').hidden")
    assert page.locator("#files-error").is_visible()
    assert page.locator("#files-error").inner_text() == "请先等待当前任务完成。"
    assert page.locator(".assistant").is_visible()


def test_file_width_and_selection_survive_resize_new_task_and_collapse(pane):
    page, _, _ = pane
    page.set_viewport_size({"width": 600, "height": 480})
    page.locator("#instruction").fill("待发送的要求")
    page.locator("#files-toggle").click()
    page.locator("#file-filter").fill("说明")
    page.locator("#file-tree .reference-file").click()
    divider = page.locator("#files-resizer")
    box = divider.bounding_box()
    page.mouse.move(box["x"] + 2, box["y"] + 60)
    page.mouse.down()
    page.mouse.move(280, box["y"] + 60)
    page.mouse.up()
    assert 275 <= page.locator("#files-pane").bounding_box()["width"] <= 281
    divider.press("ArrowLeft")
    assert 259 <= page.locator("#files-pane").bounding_box()["width"] <= 265
    page.set_viewport_size({"width": 300, "height": 480})
    page.wait_for_function(
        "() => document.querySelector('.assistant').clientWidth>=168"
    )
    assert page.locator("#start").bounding_box()["x"] < 300
    page.locator("#new-task").click()
    assert page.locator("#files-pane").is_visible()
    page.locator("#files-close").click()
    assert page.locator("#files-toggle").evaluate("el=>el===document.activeElement")
    page.locator("#files-toggle").click()
    assert page.locator("#file-filter").input_value() == "说明"
    assert page.locator("#reference-chips .reference-chip").count() == 1
    assert page.locator("#instruction").input_value() == "待发送的要求"
    divider.press("Home")
    assert page.locator("#files-pane").bounding_box()["width"] == 114
    page.locator("#clear-files").click()
    assert page.locator("#reference-chips").is_hidden()
    assert page.locator("#file-tree [aria-selected=true]").count() == 0
    assert page.locator("#instruction").input_value() == "待发送的要求"


def test_chat_error_stays_in_chat_with_files_open(pane):
    page, _, _ = pane
    page.locator("#files-toggle").click()
    page.route(
        "**/api/submit",
        lambda route: route.fulfill(
            json={"ok": False, "error": "文档已变化，请重新选择正文。"}
        ),
    )
    page.locator("#instruction").fill("这条要求要保留")
    page.locator("#start").click()
    page.wait_for_function("() => !document.querySelector('#error').hidden")
    assert page.locator("#error").is_visible()
    assert page.locator("#error").inner_text() == "文档已变化，请重新选择正文。"
    assert page.locator("#files-error").is_hidden()
    assert page.locator("#instruction").input_value() == "这条要求要保留"


def test_finished_task_has_one_request_and_can_bind_a_new_selection(pane):
    page, _, output = pane
    page.locator("#instruction").fill("帮我修改")
    page.locator("#start").click()
    page.wait_for_function(
        "() => document.querySelector('#task-status').dataset.phase==='review'"
    )
    first = page.evaluate("fixtureText")
    page.locator("#instruction").fill("这条未发送的要求应当保留")
    page.locator("#continue").click()
    page.wait_for_function(
        "() => document.querySelector('#task-status').dataset.phase==='complete'"
    )
    assert page.locator("#recent-turns summary").count() == 0
    assert page.locator("#instruction").input_value() == "这条未发送的要求应当保留"
    assert page.locator("#new-task").is_visible()
    page.locator("#instruction").fill("修改新的选区")
    page.locator("#new-task").click()
    assert page.locator("#review").is_hidden()
    assert page.locator("#task-request").is_hidden()
    assert page.locator("#instruction").input_value() == "修改新的选区"
    page.evaluate("""() => {
      const FixtureRange=fixtureSelection.constructor;
      Object.defineProperty(FixtureRange.prototype,'Paragraphs',{get(){
        const start=fixtureText.lastIndexOf('\\r',Math.max(0,this.Start-1))+1;
        const end=fixtureText.indexOf('\\r',this.Start)+1;
        return {Count:1,Item:()=>({Range:new FixtureRange(start,end)})};
      }});
      fixtureSelection=new FixtureRange(fixtureText.indexOf('\\r')+1,fixtureText.length-1);
    }""")
    page.locator("#start").click()
    page.wait_for_function(
        "() => fixtureWrites===2 && document.querySelector('#task-status').dataset.phase==='review'"
    )
    after = page.evaluate("fixtureText")
    assert after.split("\r")[0] == first.split("\r")[0]
    assert after.split("\r")[1] == "原始第二段。 更简洁。"
    page.screenshot(path=str(output / "new-selection.png"))


def test_new_accepted_task_is_visible_after_draft_or_connection_recovery(pane):
    page, _, _ = pane
    page.locator("#new-task").click()
    page.locator("#instruction").fill("未发送的草稿")
    accepted = page.evaluate(
        "() => pywebview.api.submit('通过另一个入口开始的任务','auto','wps')"
    )
    assert accepted["ok"]
    page.wait_for_function(
        "() => !document.querySelector('#review').hidden && document.querySelector('#task-status').dataset.phase==='review'"
    )
    assert page.locator("#task-request").inner_text() == "通过另一个入口开始的任务"
    assert page.locator("#instruction").input_value() == "未发送的草稿"
    # Browsing a draft must still hide this *same* task until another is accepted.
    page.locator("#new-task").click()
    page.wait_for_timeout(250)
    assert page.locator("#review").is_hidden()
    assert page.locator("#task-request").is_hidden()
    accepted = page.evaluate(
        "() => pywebview.api.submit('另一个新的任务','auto','wps')"
    )
    assert accepted["ok"]
    page.wait_for_function(
        "() => !document.querySelector('#review').hidden && document.querySelector('#task-status').dataset.phase==='review'"
    )
    assert page.locator("#task-request").inner_text() == "另一个新的任务"
    assert page.locator("#instruction").input_value() == "未发送的草稿"
