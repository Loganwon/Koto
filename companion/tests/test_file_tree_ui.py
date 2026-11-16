"""The actual minimal UI: nested local tree, reference, edit, and same-box feedback."""

from pathlib import Path

import pytest

from companion.desktop import CompanionAPI
from companion.model import EditProposal, ModelConfig
from companion.workspace import LocalWorkspace
from companion.tests.test_ui import MemoryDocument


def test_nested_tree_reference_and_single_composer(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if not edge.is_file():
        pytest.skip("Edge required")
    folder = tmp_path / "资料"
    folder.mkdir()
    (folder / "预算.md").write_text("研发预算9876万元", encoding="utf-8")
    workspace = LocalWorkspace()
    workspace.open(tmp_path)
    docs = MemoryDocument()
    api = CompanionAPI(
        ModelConfig("https://example.test", "test", "secret"), docs, workspace
    )
    opened = []
    api.open_workspace_file = lambda name: opened.append(name) or {"ok": True}

    class ReferencingModel:
        def step(self, **kwargs):
            text = kwargs["references"].read("资料/预算.md")["text"]
            return EditProposal(kwargs["current"] + " " + text, "已核对预算.md")

    api._get_session()._model_factory = ReferencingModel
    errors = []
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(edge), headless=True)
        page = browser.new_page(viewport={"width": 720, "height": 760})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.expose_function(
            "companionCall", lambda name, args: getattr(api, name)(*args)
        )
        page.add_init_script(
            "window.pywebview={api:Object.fromEntries(['status','watch','workspace_tree','choose_folder','open_workspace_file','submit','connect','advance','revise','stop','locate','configure'].map(name=>[name,(...args)=>window.companionCall(name,args)]))};"
        )
        page.goto((Path(__file__).resolve().parents[1] / "ui" / "legacy" / "index.html").as_uri())
        playwright.expect(page.locator("#api-status")).to_have_text("test")
        assert page.locator("textarea:visible").count() == 1
        page.locator("#files-toggle").click()
        page.locator("#file-tree summary").click()
        file = page.get_by_role("treeitem", name="▤ 预算.md")
        file.click()
        playwright.expect(page.locator("#reference-chips")).to_have_text("预算.md×")
        playwright.expect(page.locator(".assistant")).to_be_visible()
        playwright.expect(page.locator("#instruction")).to_have_value("")
        page.locator("#instruction").fill('把 @"资料/预算.md" 的研发预算补进这里')
        page.locator("#start").click()
        playwright.expect(page.locator("#phase-label")).to_have_text("等你检查")
        assert "9876" in docs.content["a"] and docs.content["b"] == "原始第二段。"
        playwright.expect(page.locator("#after-visible")).to_have_text(
            docs.content["a"]
        )
        playwright.expect(page.locator("#sources")).to_contain_text("资料/预算.md")
        playwright.expect(page.locator("#files-pane")).to_be_visible()
        playwright.expect(page.locator("#file-tree .file-state")).to_have_text("已读取")
        page.get_by_role("button", name="在默认应用中打开 预算.md").click()
        assert opened == ["资料/预算.md"]
        page.locator("#files-close").click()
        page.locator("#instruction").fill("后面按同样格式")
        page.locator("#continue").click()
        playwright.expect(page.locator("#progress")).to_have_text("已显示 2 / 2 段")
        assert "9876" in docs.content["b"]
        page.screenshot(path=str(tmp_path / "workspace-ui-light.png"))
        page.emulate_media(color_scheme="dark")
        page.screenshot(path=str(tmp_path / "workspace-ui-dark.png"))
        for width in (350, 410, 720):
            page.set_viewport_size({"width": width, "height": 480})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            bounds = page.locator("#start").bounding_box()
            assert bounds["y"] + bounds["height"] <= 480
        assert not errors
        browser.close()
    api._close()
