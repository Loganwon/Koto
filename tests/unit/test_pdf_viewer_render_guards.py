from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_pdf_viewer_forces_initial_visible_page_render_passes():
    src = (_repo_root() / "web" / "src" / "editors" / "pdf-viewer.ts").read_text(
        encoding="utf-8"
    )

    assert "import { _updatePdfZoomUI } from './cdn-loaders';" in src
    assert "declare function _updatePdfZoomUI" not in src
    assert "_scheduleVisiblePageRenderPasses()" in src
    assert "requestAnimationFrame(() => this._renderVisiblePagesNow())" in src
    assert "setTimeout(() => this._renderVisiblePagesNow(), 120)" in src
    assert "setTimeout(() => this._renderVisiblePagesNow(), 500)" in src
    assert "if (!renderedAny && !this._renderedPgs.has(1))" in src
    assert "this._renderPage(1)" in src
    assert "const workspaceApi = getWorkspaceApi();" in src
    assert "publishWorkspaceApi({" in src
    assert "(window as any).WA" not in src
    assert "onclick=\"WA._pdfPageMgr" not in src
    assert "data-wa-pdf-page-action" in src


def test_pdfjs_loader_uses_packaged_runtime_only_and_reports_failures():
    src = (_repo_root() / "web" / "src" / "editors" / "cdn-loaders.ts").read_text(
        encoding="utf-8"
    )

    assert "/static/vendor/pdfjs-dist/3.11.174/build/pdf.min.js" in src
    assert "/static/vendor/pdfjs-dist/3.11.174/build/pdf.worker.min.js" in src
    assert "cdn.jsdelivr.net" not in src
    assert "unpkg.com" not in src
    assert "PDF rendering is a packaged capability" in src
    assert "GlobalWorkerOptions.workerSrc = worker" in src
    assert "Object.assign(window as any" in src
    assert "_updatePdfZoomUI" in src
    assert "_updateDocxZoomUI" in src
    assert "PDF.js 本地运行时未注册" in src


def test_pdf_open_path_surfaces_errors_in_the_viewer():
    src = (_repo_root() / "web" / "src" / "workspace" / "file-open.ts").read_text(
        encoding="utf-8"
    )

    assert "function _showPdfOpenError" in src
    assert "PDF 加载失败" in src
    assert "await _ensurePdfJS()" in src
    assert "await state.activeEditor!.render(data && data.raw_url, data)" in src
    assert "_showPdfOpenError(error)" in src


def test_pdf_layout_is_primed_and_deactivated_as_a_full_editor_surface():
    src = (_repo_root() / "web" / "src" / "workspace" / "state.ts").read_text(
        encoding="utf-8"
    )

    assert "'wa-pdf-editor'" in src
    assert "fileType === 'pdf'" in src
    assert "document.getElementById('wa-pdf-viewer')?.classList.add('active')" in src
