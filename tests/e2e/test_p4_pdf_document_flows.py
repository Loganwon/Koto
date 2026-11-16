"""P4 real-browser corpus gates for PDF editing and document operations."""

from __future__ import annotations

from pathlib import Path

import pytest

PDF_READY_TIMEOUT = 60_000
pytestmark = pytest.mark.e2e


def _make_pdf(path: Path, *, watermarked: bool = False) -> str:
    reportlab = pytest.importorskip("reportlab.pdfgen.canvas")
    colors = pytest.importorskip("reportlab.lib.colors")
    canvas = reportlab.Canvas(str(path), pagesize=(612, 792))
    page_names = ("PAGE ONE", "PAGE TWO", "PAGE THREE")
    for page_number, page_name in enumerate(page_names, start=1):
        canvas.setFillColor(colors.black)
        canvas.setFont("Helvetica-Bold", 18)
        canvas.drawString(72, 700, f"P4 PDF {page_name}")
        canvas.setFont("Helvetica", 12)
        canvas.drawString(72, 660, f"P4 DIRECT TEXT ANCHOR {page_number:03d}")
        canvas.drawString(
            72, 630, f"Semantic content for {page_name.lower()} conversion."
        )
        if watermarked:
            canvas.saveState()
            canvas.setFillColorRGB(0.82, 0.82, 0.82)
            canvas.setFont("Helvetica-Bold", 32)
            canvas.translate(118, 360)
            canvas.rotate(28)
            canvas.drawString(0, 0, "CONFIDENTIAL WATERMARK")
            canvas.restoreState()
        canvas.showPage()
    canvas.save()
    return str(path)


@pytest.fixture()
def pdf_corpus_path(tmp_path):
    return _make_pdf(tmp_path / "p4_pdf_corpus.pdf")


@pytest.fixture()
def pdf_watermark_path(tmp_path):
    return _make_pdf(tmp_path / "p4_pdf_watermark.pdf", watermarked=True)


def _open_pdf(page, base_url: str, path: str) -> None:
    page.goto(f"{base_url}/", timeout=15_000, wait_until="domcontentloaded")
    page.wait_for_function(
        "() => document.getElementById('wa-file-input')?._waLocalPickerBound === true",
        timeout=PDF_READY_TIMEOUT,
    )
    page.locator("#wa-file-input").set_input_files(path)
    page.wait_for_function(
        """() => {
            const wrap = document.querySelector('#pdf-page-1');
            const canvas = wrap?.querySelector('canvas');
            const span = wrap?.querySelector('.wa-pdf-text-layer span');
            return !!wrap && !!canvas && canvas.width > 1 && canvas.height > 1 && !!span;
        }""",
        timeout=PDF_READY_TIMEOUT,
    )


def _select_pdf_text(page, target: str) -> dict:
    result = page.evaluate(
        """(target) => {
            const spans = Array.from(document.querySelectorAll(
                '#pdf-page-1 .wa-pdf-text-layer span'
            ));
            for (const span of spans) {
                const text = String(span.textContent || '');
                const index = text.indexOf(target);
                if (index < 0 || !span.firstChild) continue;
                const range = document.createRange();
                range.setStart(span.firstChild, index);
                range.setEnd(span.firstChild, index + target.length);
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
                const rect = range.getBoundingClientRect();
                return { text: selection.toString(), left: rect.left, top: rect.top };
            }
            return null;
        }""",
        target,
    )
    assert result and result["text"] == target
    return result


def _annotation_geometry(page) -> dict:
    return page.evaluate("""() => {
            const svg = document.querySelector('#pdf-page-1 .wa-pdf-annot-layer');
            const hi = svg?.querySelector('.wa-annot-hi');
            const box = svg?.querySelector('foreignObject');
            const width = Number(svg?.getAttribute('width') || 0);
            const height = Number(svg?.getAttribute('height') || 0);
            const normalized = (node) => node ? {
                x: Number(node.getAttribute('x')) / width,
                y: Number(node.getAttribute('y')) / height,
                w: Number(node.getAttribute('width')) / width,
                h: Number(node.getAttribute('height')) / height,
            } : null;
            return { width, height, highlight: normalized(hi), textbox: normalized(box) };
        }""")


def test_pdf_annotation_position_survives_zoom_save_render_and_reload(
    e2e_page,
    e2e_base_url,
    pdf_corpus_path,
    tmp_path,
    console_errors,
):
    fitz = pytest.importorskip("pymupdf")
    _open_pdf(e2e_page, e2e_base_url, pdf_corpus_path)

    e2e_page.locator('[title="批注工具"]').click()
    _select_pdf_text(e2e_page, "DIRECT TEXT ANCHOR 001")
    created = e2e_page.evaluate("""() => {
            const fn = document.__kotoFeatureRegistry__?.pdfAnnotateSelection;
            if (typeof fn !== 'function') return false;
            fn('highlight');
            return true;
        }""")
    assert created
    e2e_page.wait_for_selector("#pdf-page-1 .wa-annot-hi")

    e2e_page.locator("#wa-pdf-abt-textbox").click()
    wrap = e2e_page.locator("#pdf-page-1")
    bounds = wrap.bounding_box()
    assert bounds
    click_x = bounds["x"] + bounds["width"] * 0.28
    click_y = bounds["y"] + bounds["height"] * 0.38
    e2e_page.mouse.click(click_x, click_y)
    editor = e2e_page.locator("#pdf-page-1 .wa-pdf-textbox-edit")
    editor.wait_for(state="visible")
    editor.fill("P4 TEXTBOX 001")
    editor.press("Enter")
    e2e_page.wait_for_selector("#pdf-page-1 foreignObject.wa-annot-shape")

    before_zoom = _annotation_geometry(e2e_page)
    assert before_zoom["highlight"] and before_zoom["textbox"]
    e2e_page.evaluate("() => document.__kotoFeatureRegistry__.pdfZoom(150)")
    e2e_page.wait_for_function(
        """(oldWidth) => {
            const svg = document.querySelector('#pdf-page-1 .wa-pdf-annot-layer');
            return Number(svg?.getAttribute('width') || 0) > oldWidth * 1.4
                && !!svg?.querySelector('.wa-annot-hi')
                && !!svg?.querySelector('foreignObject');
        }""",
        arg=before_zoom["width"],
        timeout=PDF_READY_TIMEOUT,
    )
    after_zoom = _annotation_geometry(e2e_page)
    for kind in ("highlight", "textbox"):
        for axis in ("x", "y", "w", "h"):
            assert after_zoom[kind][axis] == pytest.approx(
                before_zoom[kind][axis], abs=0.004
            )

    annotated_path = tmp_path / "p4_annotated.pdf"
    with e2e_page.expect_download(timeout=PDF_READY_TIMEOUT) as download_info:
        e2e_page.locator('[title="保存批注到 PDF"]').click()
    download_info.value.save_as(annotated_path)

    document = fitz.open(annotated_path)
    annotated_page = document[0]
    annotations = list(annotated_page.annots() or [])
    type_names = {annotation.type[1] for annotation in annotations}
    assert "Highlight" in type_names
    assert "FreeText" in type_names
    textbox = next(
        annotation for annotation in annotations if annotation.type[1] == "FreeText"
    )
    assert textbox.info.get("content") == "P4 TEXTBOX 001"
    assert textbox.rect.x0 > 0 and textbox.rect.y0 > 0

    render_dir = tmp_path / "pdfs"
    render_dir.mkdir()
    base_doc = fitz.open(pdf_corpus_path)
    base_pixmap = base_doc[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), annots=True)
    annotated_pixmap = annotated_page.get_pixmap(
        matrix=fitz.Matrix(1.5, 1.5), annots=True
    )
    base_pixmap.save(render_dir / "p4_before.png")
    annotated_pixmap.save(render_dir / "p4_after.png")
    assert base_pixmap.samples != annotated_pixmap.samples
    base_doc.close()
    document.close()

    e2e_page.locator("#wa-file-input").set_input_files(str(annotated_path))
    e2e_page.wait_for_function(
        """() => !!document.querySelector('#pdf-page-1 .wa-annot-hi')""",
        timeout=PDF_READY_TIMEOUT,
    )
    reloaded = _annotation_geometry(e2e_page)
    assert reloaded["highlight"]["x"] == pytest.approx(
        before_zoom["highlight"]["x"], abs=0.01
    )
    assert console_errors == [], f"JS errors: {console_errors}"


def test_pdf_page_operations_download_requested_sequence_and_reopen(
    e2e_page,
    e2e_base_url,
    pdf_corpus_path,
    tmp_path,
    console_errors,
):
    pypdf = pytest.importorskip("pypdf")
    _open_pdf(e2e_page, e2e_base_url, pdf_corpus_path)
    e2e_page.locator('[title="页面管理（旋转/删除/重排/拆分）"]').click()
    e2e_page.wait_for_selector("#wa-pdf-pagemgr", state="visible")
    assert e2e_page.locator("#wa-pdf-pagemgr-grid .wa-pmgr-card").count() == 3

    order = e2e_page.evaluate("""() => {
        const grid = document.querySelector('#wa-pdf-pagemgr-grid');
        const cards = Array.from(grid.querySelectorAll('.wa-pmgr-card'));
        const transfer = new DataTransfer();
        cards[2].dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer: transfer }));
        cards[0].dispatchEvent(new DragEvent('drop', { bubbles: true, dataTransfer: transfer }));
        cards[2].dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: transfer }));
        return Array.from(grid.querySelectorAll('.wa-pmgr-card')).map(card => card.dataset.origPage);
    }""")
    assert order == ["3", "1", "2"]
    e2e_page.locator(
        '.wa-pmgr-card[data-orig-page="3"] [title="顺时针旋转 90°"]'
    ).click()
    e2e_page.locator('.wa-pmgr-card[data-orig-page="2"] [title="删除此页"]').click()

    output_path = tmp_path / "p4_page_ops.pdf"
    with e2e_page.expect_download(timeout=PDF_READY_TIMEOUT) as download_info:
        e2e_page.locator('[title="应用页面排列、旋转与删除"]').click()
    download_info.value.save_as(output_path)

    reader = pypdf.PdfReader(str(output_path))
    assert len(reader.pages) == 2
    assert "PAGE THREE" in (reader.pages[0].extract_text() or "")
    assert "PAGE ONE" in (reader.pages[1].extract_text() or "")
    assert int(reader.pages[0].get("/Rotate", 0)) % 360 == 90

    e2e_page.locator("#wa-file-input").set_input_files(str(output_path))
    e2e_page.wait_for_function(
        """() => String(document.querySelector('#wa-pdf-page-counter')?.textContent || '')
            .includes('共 2 页')""",
        timeout=PDF_READY_TIMEOUT,
    )
    assert console_errors == [], f"JS errors: {console_errors}"


def test_pdf_conversion_downloads_reopenable_office_packages(
    e2e_page,
    e2e_base_url,
    pdf_corpus_path,
    tmp_path,
    console_errors,
):
    _open_pdf(e2e_page, e2e_base_url, pdf_corpus_path)
    outputs = {}
    for extension, label in (
        ("docx", "转为 Word (.docx)"),
        ("xlsx", "转为 Excel (.xlsx)"),
        ("pptx", "转为 PPT (.pptx)"),
    ):
        e2e_page.locator('[title="格式转换"]').click()
        with e2e_page.expect_download(timeout=PDF_READY_TIMEOUT) as download_info:
            e2e_page.get_by_text(label, exact=True).click()
        path = tmp_path / f"p4_converted.{extension}"
        download_info.value.save_as(path)
        outputs[extension] = path

    docx = pytest.importorskip("docx").Document(outputs["docx"])
    docx_text = "\n".join(paragraph.text for paragraph in docx.paragraphs)
    assert "P4 PDF PAGE ONE" in docx_text and "P4 PDF PAGE THREE" in docx_text

    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.load_workbook(outputs["xlsx"])
    assert len(workbook.worksheets) == 3
    workbook_text = " ".join(
        str(cell.value or "")
        for sheet in workbook.worksheets
        for row in sheet.iter_rows()
        for cell in row
    )
    assert "P4 PDF PAGE TWO" in workbook_text

    presentation = pytest.importorskip("pptx").Presentation(outputs["pptx"])
    assert len(presentation.slides) == 3
    assert all(
        any(shape.shape_type == 13 for shape in slide.shapes)
        for slide in presentation.slides
    )
    assert console_errors == [], f"JS errors: {console_errors}"


def test_pdf_watermark_cleanup_reports_effect_and_safe_noop(
    e2e_page,
    e2e_base_url,
    pdf_watermark_path,
    pdf_corpus_path,
    tmp_path,
    console_errors,
):
    fitz = pytest.importorskip("pymupdf")
    _open_pdf(e2e_page, e2e_base_url, pdf_watermark_path)
    cleaned_path = tmp_path / "p4_watermark_cleaned.pdf"
    with e2e_page.expect_download(timeout=PDF_READY_TIMEOUT) as download_info:
        e2e_page.locator('[title="清理自有文档水印"]').click()
    download_info.value.save_as(cleaned_path)
    e2e_page.wait_for_function(
        """() => String(document.querySelector('#wa-pwm-status')?.textContent || '')
            .includes('共处理 3 处')""",
        timeout=PDF_READY_TIMEOUT,
    )
    cleaned = fitz.open(cleaned_path)
    cleaned_text = "\n".join(page.get_text() for page in cleaned)
    assert "CONFIDENTIAL WATERMARK" not in cleaned_text
    assert cleaned_text.count("P4 PDF PAGE") == 3
    render_dir = tmp_path / "pdfs"
    render_dir.mkdir(exist_ok=True)
    cleaned[0].get_pixmap().save(render_dir / "p4_watermark_cleaned.png")
    cleaned.close()

    e2e_page.locator('[data-koto-event-click="h_4fc75aa028d2"]').last.click()
    e2e_page.locator("#wa-file-input").set_input_files(pdf_corpus_path)
    e2e_page.wait_for_selector("#pdf-page-1 .wa-pdf-text-layer span")
    e2e_page.locator('[title="清理自有文档水印"]').click()
    e2e_page.wait_for_function(
        """() => String(document.querySelector('#wa-pwm-status')?.textContent || '')
            .includes('原文件未改变')""",
        timeout=PDF_READY_TIMEOUT,
    )
    no_op = e2e_page.evaluate("""() => ({
        result: document.querySelector('#wa-pwm-result')?.textContent || '',
        downloadVisible: getComputedStyle(document.querySelector('#wa-pwm-download')).display !== 'none',
    })""")
    assert "no-supported-watermark-detected" in no_op["result"]
    assert no_op["downloadVisible"] is False
    assert console_errors == [], f"JS errors: {console_errors}"
