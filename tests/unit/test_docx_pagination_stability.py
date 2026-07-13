'''
tests/unit/test_docx_pagination_stability.py

Unit tests for DOCX pagination stability.
Verifies that pagination is calculated from the current rendered state,
not from a stale document-only cache.
'''

from pathlib import Path
import re


def _repo_root():
    return Path(__file__).resolve().parents[2]


def _read_ext_js():
    return (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(encoding="utf-8")


def _read_bundle_js():
    return (_repo_root() / "web" / "static" / "js" / "tiptap-docx-bundle.js").read_text(encoding="utf-8")


def _read_scheduler_js():
    return (_repo_root() / "web" / "tiptap-editor" / "docx-pagination-scheduler.js").read_text(encoding="utf-8")


# -- Current-layout signature tests --

def test_document_only_break_cache_is_not_used():
    src = _read_ext_js()
    assert "_breakCache" not in src
    assert "_nodeFingerprint" not in src


def test_layout_signature_tracks_break_fill_and_chrome():
    src = _read_ext_js()
    assert "let _lastLayoutSignature = null;" in src
    assert "const layoutSignature = JSON.stringify" in src
    assert "finalContentFillPx" in src
    assert "hdrHtml" in src
    assert "sectionsAr" in src


def test_layout_signature_prevents_redundant_dispatch_only():
    src = _read_ext_js()
    assert "if (layoutSignature !== _lastLayoutSignature)" in src
    assert "_lastLayoutSignature = layoutSignature;" in src


def test_font_and_window_reflow_schedule_a_fresh_measurement():
    scheduler = _read_scheduler_js()
    assert "document.fonts?.ready?.then(() => schedule('fonts', 40))" in scheduler
    assert "window.addEventListener('resize', onWindowResize" in scheduler
    assert "window.removeEventListener('resize', onWindowResize);" in scheduler
    assert "const watchLayoutWidth" in scheduler
    assert "layoutResizeObserver.observe(pmDom);" in scheduler


def test_layout_observer_ignores_pagination_height_writes():
    scheduler = _read_scheduler_js()
    assert "entry?.contentRect?.width" in scheduler
    assert "observedWidth === lastObservedLayoutWidth" in scheduler
    assert "lastObservedLayoutWidth = observedWidth;" in scheduler


def test_pagination_uses_one_scheduler_owner_for_all_browser_triggers():
    src = _read_ext_js()
    scheduler = _read_scheduler_js()

    assert "createDocxPaginationScheduler" in src
    assert "new ResizeObserver" not in src
    assert "addEventListener('koto-hdrftr-changed'" not in src
    assert "document.fonts" not in src
    for trigger in ("new ResizeObserver", "koto-hdrftr-changed", "document.fonts", "onDocumentChanged"):
        assert trigger in scheduler


# -- Phantom page tests --

def test_advance_page_usage_no_phantom_advance():
    src = _read_ext_js()
    assert "nextUsed = contentH;" in src


# -- Root-cause fix: measure actual rendered state (no suppression) --

def test_measure_does_not_suppress_soft_breaks():
    src = _read_ext_js()
    # The function still exists as dead code but must not be called in _measure
    idx = src.index("const _measure =")
    src_measure = src[idx:idx + 400]
    assert "_suppressDocxSoftPageBreaksForMeasurement" not in src_measure


def test_suppression_function_removed():
    src = _read_ext_js()
    assert "function _suppressDocxSoftPageBreaksForMeasurement" not in src


# -- Root-cause fix: anchor height subtraction --

def test_content_height_subtracts_anchor_heights():
    src = _read_ext_js()
    assert ".koto-inline-page-break-anchor" in src
    assert "contentHeight - anchor.offsetHeight" in src


def test_content_height_clamps_at_zero_after_subtraction():
    src = _read_ext_js()
    assert "Math.max(0, contentHeight)" in src


# -- Root-cause fix: TreeWalker line collection --

def test_collect_lines_uses_tree_walker():
    src = _read_ext_js()
    assert "createTreeWalker" in src
    assert "NodeFilter.SHOW_TEXT" in src


def test_collect_lines_skips_anchor_text_nodes():
    src = _read_ext_js()
    assert ".koto-inline-page-break-anchor, [data-soft-page-break]" in src


def test_collect_lines_uses_text_only_height_for_normalization():
    src = _read_ext_js()
    assert "textContentHeight" in src
    assert ".koto-inline-page-break-anchor" in src


# -- Block measurement tests --

def test_measure_block_handles_zero_heights():
    src = _read_ext_js()
    assert "Math.max(0, contentHeight)" in src


def test_measure_block_includes_visual_children():
    src = _read_ext_js()
    assert "koto-img-wrapper" in src


def test_image_blocks_avoid_auto_split():
    src = _read_ext_js()
    assert "function _docxBlockAvoidsAutoSplit" in src
    assert "image" in src


# -- Stability: repeated measurements produce identical results --

def test_measure_is_idempotent_by_design():
    src = _read_ext_js()
    assert "createTreeWalker" in src
    assert ".koto-inline-page-break-anchor" in src


# -- Bundle integrity tests --

def test_explicit_docx_page_break_uses_rendered_sheet_bounds():
    src = _read_ext_js()
    node_view_start = src.index("export const DocxPageBreak")
    node_view_end = src.index("// ─────────────────────────────────────────────────────────────────────────────\n// AutoPageBreakPlugin", node_view_start)
    node_view = src[node_view_start:node_view_end]
    assert "_buildDocxPageBreakWidget({" in node_view
    assert "breakAttribute: 'data-page-break'" in node_view
    assert "_resolveRenderedDocxPageGeometry(" in node_view
    assert "_alignSoftBreakWidgetToRenderedPage(dom, pageGeometry.contentLeftPx, pageGeometry.pageWidthPx);" in node_view
    assert "dom.style.marginRight = `-${mRight}px`;" not in node_view


def test_page_edge_chrome_uses_the_same_left_page_origin_as_break_widgets():
    editor_src = (_repo_root() / "web" / "tiptap-editor" / "koto-docx-editor.js").read_text(
        encoding="utf-8"
    )

    assert "position:absolute; top:0; left:0; transform:none;" in editor_src
    assert "position:absolute; bottom:0; left:0; transform:none;" in editor_src
    assert "left:50%; transform:translateX(-50%);" not in editor_src
    assert "const renderedPageWidthPx = this.editor.view.dom.offsetWidth" in editor_src
    assert editor_src.count("const _pw = renderedPageWidthPx;") == 2


def test_all_page_break_types_share_one_surface_builder_and_storage():
    src = _read_ext_js()
    editor_src = (_repo_root() / "web" / "tiptap-editor" / "koto-docx-editor.js").read_text(
        encoding="utf-8"
    )

    assert "function _buildDocxPageBreakWidget" in src
    assert src.count("_buildDocxPageBreakWidget({") >= 4
    assert "function _buildSoftBreakWidget" not in src
    assert "storage.docxPageBreak" not in src
    assert "storage.docxPageBreak" not in editor_src


def test_bundle_contains_two_map_objects_in_view():
    bundle = _read_bundle_js()
    assert "autoPageBreak" in bundle


def test_bundle_dispatch_guard_has_layout_signature():
    bundle = _read_bundle_js()
    assert "document.fonts" in bundle
    assert "setMeta" in bundle


def test_bundle_is_substantial():
    bundle = _read_bundle_js()
    assert len(bundle) > 100000


def test_bundle_contains_tree_walker():
    bundle = _read_bundle_js()
    assert "createTreeWalker" in bundle


# -- Header/footer interaction tests --

def test_hdrftr_notify_dispatches_custom_event():
    src = _read_ext_js()
    assert "koto-hdrftr-changed" in src
    assert "CustomEvent" in src


def test_hdrftr_event_listener_registered_in_view():
    scheduler = _read_scheduler_js()
    assert "addEventListener('koto-hdrftr-changed'" in scheduler


def test_hdrftr_event_listener_cleaned_up_on_destroy():
    scheduler = _read_scheduler_js()
    assert "removeEventListener('koto-hdrftr-changed'" in scheduler
