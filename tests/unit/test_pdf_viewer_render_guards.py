from pathlib import Path

from tests.source_graph import read_frontend_partitions


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_pdf_viewer_forces_initial_visible_page_render_passes():
    src = read_frontend_partitions("web/src/editors/pdf-viewer.ts")

    assert (
        "import { getFeatureRegistry, registerFeatures } from '../shared/feature-registry';"
        in src
    )
    assert "const _updatePdfZoomUI" in src
    assert "declare function _updatePdfZoomUI" not in src
    assert "_scheduleVisiblePageRenderPasses()" in src
    assert "requestAnimationFrame(() => this._renderVisiblePagesNow())" in src
    assert "setTimeout(() => this._renderVisiblePagesNow()" not in src
    assert "if (!renderedAny && !this._renderedPgs.has(1))" in src
    assert "this._renderPage(1)" in src
    assert "const workspaceApi = getFeatureRegistry();" in src
    assert "registerFeatures({" in src
    assert "(window as any).WA" not in src
    assert 'onclick="WA._pdfPageMgr' not in src
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
    src = read_frontend_partitions("web/src/workspace/state.ts")

    assert "'wa-pdf-editor'" in src
    assert "fileType === 'pdf'" in src
    assert "document.getElementById('wa-pdf-viewer')?.classList.add('active')" in src


def test_pdf_annotation_tools_preserve_page_geometry_for_backend_conversion():
    src = read_frontend_partitions("web/src/editors/pdf-viewer.ts")

    assert "getElementLogicalSize" in src
    assert "viewportPointToElement" in src
    assert "viewportRectToElement" in src
    assert "pageWidth: pageSize.width" in src
    assert "pageHeight: pageSize.height" in src
    assert "pageWidth: this._drawPageWidth" in src
    assert "pageHeight: this._drawPageHeight" in src
    assert "pageWidth: this._shapePageWidth" in src
    assert "pageHeight: this._shapePageHeight" in src
    assert "const width = Math.max(80, box.offsetWidth);" in src
    assert "const height = Math.max(22, box.offsetHeight);" in src
    assert src.index("const width = Math.max(80, box.offsetWidth);") < src.index(
        "box.remove();", src.index("const width = Math.max(80, box.offsetWidth);")
    )


def test_pdf_download_waits_for_webview_to_consume_blob_url():
    src = read_frontend_partitions("web/src/editors/pdf-viewer.ts")
    download_helper = (
        _repo_root() / "web" / "src" / "editors" / "pdf-download.ts"
    ).read_text(encoding="utf-8")

    assert "document.body.appendChild(anchor)" in download_helper
    assert (
        "window.setTimeout(() => URL.revokeObjectURL(url), 60_000)" in download_helper
    )
    assert "URL.revokeObjectURL(url);" not in download_helper
    assert "downloadPdfBlob as _downloadPdfBlob" in src
    assert "_downloadPdfBlob(blob, name)" in src


def test_pdf_loaded_annotations_are_mapped_back_to_current_viewport():
    src = read_frontend_partitions("web/src/editors/pdf-viewer.ts")

    hydration = src.split("async _annotationFromPdfSpace", 1)[1].split(
        "async _loadAnnotationsFromServer", 1
    )[0]
    assert "viewport.convertToViewportRectangle" in hydration
    assert "viewport.convertToViewportPoint" in hydration
    assert "normalized.points = firstStroke.map" in hydration
    assert (
        "json.annotations.map(annotation => this._annotationFromPdfSpace(annotation))"
        in src
    )
    assert "if (annot.flattened) return;" in src


def test_pdf_annotations_rescale_with_current_zoom_viewport():
    src = read_frontend_partitions("web/src/editors/pdf-viewer.ts")

    scaler = src.split("_annotationForViewport(annotation", 1)[1].split(
        "// ─── Eraser", 1
    )[0]
    assert "viewportWidth / sourceWidth" in scaler
    assert "viewportHeight / sourceHeight" in scaler
    assert "scaled.rects = annotation.rects.map(scaleRect)" in scaler
    assert "scaled.points = annotation.points.map" in scaler
    assert (
        ".map(annotation => this._annotationForViewport(annotation, viewportWidth, viewportHeight))"
        in src
    )


def test_pdf_text_location_tolerates_ai_punctuation_and_full_width_differences():
    src = read_frontend_partitions("web/src/editors/pdf-viewer.ts")
    normalizer = src.split("_normalizeTextWithMap(text)", 1)[1].split(
        "_extractAiAnnotationSuggestions", 1
    )[0]

    assert ".normalize('NFKC').toLowerCase()" in normalizer
    assert r"/[\s\p{P}\p{S}]/u" in normalizer
    assert "map.push(idx)" in normalizer
    assert "请在同一 PDF 页面内选择" in src


def test_pdf_annotation_mode_reclaims_compact_overlay_space_and_restores_it():
    src = read_frontend_partitions("web/src/editors/pdf-viewer.ts")

    assert "document.body.classList.contains('koto-layout-compact')" in src
    assert "this._restoreAiPanelAfterAnnot = true" in src
    assert "aiPanel?.classList.contains('wa-ai-collapsed')" in src
    assert "workspaceApi.toggleAiPanel()" in src


def test_pdf_watermark_noop_is_explicit_and_not_downloadable():
    src = read_frontend_partitions("web/src/editors/pdf-viewer.ts")
    route = (
        _repo_root() / "web" / "blueprints" / "workspace_document_routes.py"
    ).read_text(encoding="utf-8")

    assert "X-Koto-Reason" in src
    assert "原文件未改变" in src
    assert "dlLink.removeAttribute('href')" in src
    assert "no-supported-watermark-detected" in route
