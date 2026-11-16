"""Production WPS adapter/RPC with fake SDK and real isolated disk results."""

from pathlib import Path
import json
import threading

import pytest

from companion.embedded import EmbeddedAPI, PaneServer
from companion.file_actions import FileActionProposal
from companion.model import ModelConfig
from companion.workspace import LocalWorkspace


@pytest.mark.parametrize("action", ["save_current_document", "export_current_pdf"])
def test_native_file_rpc_receipt_survives_lost_reply_without_duplicate_action(
    tmp_path, action
):
    playwright = pytest.importorskip("playwright.sync_api")
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if not edge.exists():
        pytest.skip("Edge required")
    from docx import Document

    source = tmp_path / "source.docx"
    doc = Document()
    doc.add_paragraph("disk original")
    doc.save(source)
    workspace = LocalWorkspace()
    workspace.open(tmp_path)
    calls = []

    def save(text):
        calls.append("save")
        doc = Document()
        for part in text.split("\r"):
            if part:
                doc.add_paragraph(part)
        doc.save(source)

    def export(path):
        calls.append("export")
        from reportlab.pdfgen import canvas

        pdf = canvas.Canvas(path)
        pdf.drawString(30, 700, "Synthetic SDK PDF")
        pdf.save()

    class Model:
        def step(self, **kwargs):
            return FileActionProposal(
                action,
                {"file_name": "result.pdf"} if action == "export_current_pdf" else {},
            )

    class API(EmbeddedAPI):
        def _model(self):
            return Model()

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
            config=ModelConfig("https://example.test", "test", "synthetic"),
            workspace=workspace,
        )
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(executable_path=str(edge), headless=True)
            page = browser.new_page(viewport={"width": 380, "height": 760})
            page.expose_function("fixtureSave", save)
            page.expose_function("fixtureExport", export)
            fixture = (
                Path(__file__)
                .with_name("wps_sdk_fixture.js")
                .read_text(encoding="utf-8")
            )
            fixture += (
                "\nwps.ActiveDocument.FullName="
                + json.dumps(str(source))
                + ";wps.ActiveDocument.Path="
                + json.dumps(str(tmp_path))
                + ";wps.ActiveDocument.Save=async()=>{await fixtureSave(fixtureText);wps.ActiveDocument.Saved=true;};wps.ActiveDocument.ExportAsFixedFormat=async path=>fixtureExport(path);"
            )
            page.add_init_script(fixture)
            dropped = []

            def lost_reply(route):
                data = route.request.post_data_json
                result = data[1] if len(data) > 1 else None
                if (
                    not dropped
                    and isinstance(result, dict)
                    and (
                        result.get("saved")
                        or str(result.get("path", "")).endswith(".pdf")
                    )
                ):
                    dropped.append(True)
                    route.fetch()
                    return route.abort()
                route.continue_()

            page.route("**/host/reply", lost_reply)
            page.goto(server.origin + "/ui/?host=wps")
            page.wait_for_function("() => !document.querySelector('#start').disabled")
            page.locator("#instruction").fill(
                "保存文档" if action == "save_current_document" else "导出 PDF"
            )
            page.locator("#start").click()
            page.wait_for_function(
                "() => !document.querySelector('#artifact-receipt').hidden"
            )
            assert dropped and len(calls) == 1
            assert (
                page.locator("#answer")
                .inner_text()
                .startswith("已保存" if action == "save_current_document" else "已导出")
            )
            assert (
                (tmp_path / "result.pdf").is_file()
                if action == "export_current_pdf"
                else "本季度" in Document(source).paragraphs[0].text
            )
            page.screenshot(path=str(tmp_path / (action + ".png")))
            browser.close()
    finally:
        for api in server.sessions.values():
            api._close()
        server.shutdown()
        server.server_close()
