"""Durable history can be read beside files without replaying edits."""

from pathlib import Path
import threading

import pytest

from companion.embedded import EmbeddedAPI, PaneServer
from companion.journal import EventJournal, document_scope
from companion.model import ModelConfig
from companion.tests.test_embedded_ui import FAKE_WPS
from companion.workspace import LocalWorkspace


def seed(journal, scope, count=45):
    for i in range(count):
        journal.record(
            scope,
            "task",
            str(i),
            "turn_completed",
            {
                "user": f"第{i + 1}条要求" + (" 查找预算" if i == 0 else ""),
                "assistant": f"第{i + 1}条回答，修改已显示。" + "内容说明。" * 12,
            },
        )


def test_history_pagination_search_and_document_isolation(tmp_path):
    journal = EventJournal(tmp_path / "history.sqlite3")
    seed(journal, "document-a")
    seed(journal, "document-b", 2)
    first = journal.history_page("document-a")
    second = journal.history_page("document-a", first["next_before"])
    last = journal.history_page("document-a", second["next_before"])
    assert first["total"] == 45
    assert len(first["items"]) == len(second["items"]) == 20
    assert len(last["items"]) == 5 and last["next_before"] is None
    ids = [row["id"] for page in (first, second, last) for row in page["items"]]
    assert len(set(ids)) == 45
    hit = journal.history_page("document-a", query="预算")
    assert hit["total"] == 1 and hit["items"][0]["turn"] == "0"
    assert journal.history_page("document-b")["total"] == 2
    assert journal.recovery("document-a")["unverified"] == []
    for args in ((0,), (None, "x" * 201), (None, "", 51), ("bad",)):
        with pytest.raises(ValueError):
            journal.history_page("document-a", *args)
    journal.close()


def test_history_files_chat_and_draft_stay_together_on_real_ui(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if not edge.exists():
        pytest.skip("Edge required")
    journal = EventJournal(tmp_path / "history.sqlite3")
    scope = document_scope("wps", "C:/synthetic/测试.docx")
    seed(journal, scope)
    workspace = LocalWorkspace()
    (tmp_path / "预算.txt").write_text("预算120万元", encoding="utf-8")
    workspace.open(tmp_path)

    class API(EmbeddedAPI):
        def _model(self):
            pytest.fail("Reading history must not call a model")

        def fork(self, host, documents):
            return API(
                host,
                config=self._config,
                documents=documents,
                workspace=self._workspace,
                journal=self._journal,
            )

    server = PaneServer(
        API(
            "wps",
            journal=journal,
            workspace=workspace,
            config=ModelConfig("https://example.test", "test", "synthetic"),
        )
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(executable_path=str(edge), headless=True)
            page = browser.new_page(viewport={"width": 380, "height": 760})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script(FAKE_WPS)
            page.goto(server.origin + "/ui/?host=wps")
            page.wait_for_function(
                "() => document.querySelectorAll('.past-turn').length===20"
            )
            assert page.locator("#recent-turns details").count() == 0
            assert "第45条回答" in page.locator(".past-turn").last.inner_text()
            page.locator("#files-toggle").click()
            page.locator("#file-filter").fill("预算")
            page.locator(".reference-file").first.click()
            page.locator("#instruction").fill("未发送的反馈必须保留")
            page.locator("#history-toggle").click()
            assert "45 条" in page.locator("#history-summary").inner_text()
            page.locator("#history-query").fill("查找预算")
            page.wait_for_function(
                "() => document.querySelectorAll('.history-result').length===1"
            )
            page.locator(".history-result").click()
            assert "第1条回答" in page.locator(".history-highlight").inner_text()
            assert page.locator("#files-pane").is_visible()
            assert page.locator(".assistant").is_visible()
            assert page.locator("#instruction").input_value() == "未发送的反馈必须保留"
            assert page.locator("#reference-chips").inner_text().startswith("预算.txt")
            reading = page.locator("#conversation").evaluate("el=>el.scrollTop")
            page.wait_for_timeout(450)
            assert (
                abs(
                    page.locator("#conversation").evaluate("el=>el.scrollTop") - reading
                )
                < 3
            )
            page.screenshot(path=str(tmp_path / "history-and-files.png"))
            page.locator("#history-clear").click()
            page.locator("#history-close").click()
            page.locator("#load-earlier").click()
            page.wait_for_function(
                "() => document.querySelectorAll('.past-turn').length===41"
            )
            for width, height in ((300, 480), (380, 760), (520, 600)):
                page.set_viewport_size({"width": width, "height": height})
                page.locator("#history-toggle").click()
                assert page.locator("#history-tools").is_visible()
                assert page.locator("#files-pane").bounding_box()["width"] >= 112
                assert page.locator(".assistant").bounding_box()["width"] >= 168
                box = page.locator("#start").bounding_box()
                assert box["y"] + box["height"] <= height
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                page.locator("#history-close").click()
            page.set_viewport_size({"width": 520, "height": 760})
            page.locator("#jump-latest").click()
            page.screenshot(path=str(tmp_path / "parallel-history.png"))
            page.locator("#api-status").click()
            page.locator("#reload-interface").click()
            page.wait_for_function(
                "() => document.querySelectorAll('.past-turn').length===20"
            )
            assert page.locator("#files-pane").is_visible()
            assert page.locator("#instruction").input_value() == "未发送的反馈必须保留"
            assert page.locator("#file-filter").input_value() == "预算"
            assert "预算.txt" in page.locator("#reference-chips").inner_text()
            assert page.evaluate("fixtureWrites") == 0
            assert not errors, errors
            browser.close()
    finally:
        for api in list(server.sessions.values()):
            api._close()
        server.shutdown()
        server.server_close()
        journal.close()
