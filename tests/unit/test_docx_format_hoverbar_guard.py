from pathlib import Path
import re


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _workspace_runtime_sources() -> str:
    root = _repo_root()
    parts = [
        "web/src/workspace/file-open.ts",
        "web/src/editors/docx-outline.ts",
        "web/src/ui/selection-toolbar.ts",
        "web/src/ui/docx-pptx-toolbar.ts",
        "web/src/workspace/docx-review-runtime.ts",
    ]
    return "\n".join((root / path).read_text(encoding="utf-8") for path in parts)


def test_docx_tooltip_buttons_keep_editor_focus():
    shell_html = (_repo_root() / "web" / "templates" / "index.html").read_text(
        encoding="utf-8"
    )
    tooltip_html = (
        _repo_root() / "web" / "templates" / "_workspace_selection_toolbar.html"
    ).read_text(
        encoding="utf-8"
    )
    assert "{% include '_workspace_selection_toolbar.html' %}" in shell_html
    assert re.search(r'<div\s+id="wa-pdf-tooltip"', tooltip_html)
    assert tooltip_html.count('onmousedown="event.preventDefault()"') >= 6


def test_docx_hoverbar_has_font_controls():
    js = (_repo_root() / "web" / "src" / "ui" / "docx-pptx-toolbar.ts").read_text(encoding="utf-8")
    assert "fontFamily" in js
    assert "fontSize" in js


def test_docx_font_size_extension_defines_commands_and_stores_point_sizes():
    ext_js = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )

    assert "setFontSize: fontSize => ({ chain }) => {" in ext_js
    assert "unsetFontSize: () => ({ chain }) => {" in ext_js
    assert "return `${formatted}pt`;" in ext_js


def test_docx_image_toolbar_uses_word_like_wrap_and_position_groups():
    ext_js = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )
    css = (_repo_root() / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )

    assert 'data-wrap="inline"' in ext_js
    assert 'data-wrap="square"' in ext_js
    assert 'data-wrap="tight"' in ext_js
    assert 'data-wrap="top-bottom"' in ext_js
    assert 'data-align="left"' in ext_js
    assert 'data-align="center"' in ext_js
    assert 'data-align="right"' in ext_js
    assert 'data-role="status"' in ext_js
    assert '表格内仅影响当前单元格中的文本环绕' in ext_js
    assert '.koto-img-layout-card' in css
    assert '.koto-img-position-group' in css
    assert '.koto-img-toolbar-status' in css
    assert '.koto-img-toolbar-note' in css


def test_docx_image_toolbar_pointerdown_keeps_node_selected_and_runtime_bundle_matches():
    ext_js = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )
    bundle_js = (_repo_root() / "web" / "static" / "js" / "tiptap-docx-bundle.js").read_text(
        encoding="utf-8"
    )

    assert "toolbar.addEventListener('pointerdown'" in ext_js
    assert "NodeSelection.create(tr.doc, pos)" in ext_js
    assert "editor.view.focus()" in ext_js
    assert 'data-wrap="inline"' in bundle_js
    assert 'data-align="center"' in bundle_js
    assert 'pointerdown' in bundle_js
    assert 'setSelection(' in bundle_js


def test_docx_image_layout_reads_parent_wrapper_hints_and_clears_top_bottom():
    ext_js = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )
    bundle_js = (_repo_root() / "web" / "static" / "js" / "tiptap-docx-bundle.js").read_text(
        encoding="utf-8"
    )

    assert "function _docxImageLayoutContainer(el)" in ext_js
    assert "container?.getAttribute('data-koto-layout')" in ext_js
    assert "_docxImageStyleValue(container, 'textAlign')" in ext_js
    assert "const looksAnchored = !!container" in ext_js
    assert "'clear:both'" in ext_js
    assert "parentElement" in bundle_js
    assert "clear:both" in bundle_js


def test_docx_image_layout_enables_center_for_square_and_tight_modes():
    ext_js = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )
    bundle_js = (_repo_root() / "web" / "static" / "js" / "tiptap-docx-bundle.js").read_text(
        encoding="utf-8"
    )

    assert "square-center" in ext_js
    assert "tight-center" in ext_js
    assert "align === 'left' || align === 'center' || align === 'right'" in ext_js
    assert "居中为网页近似效果" in ext_js
    assert "square-center" in bundle_js
    assert "tight-center" in bundle_js


def test_docx_image_toolbar_uses_explicit_launcher_and_selection_state():
    ext_js = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )
    css = (_repo_root() / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )

    assert 'koto-img-toolbar-trigger' in ext_js
    assert '_setToolbarOpen(!isToolbarOpen)' in ext_js
    assert 'selectNode()' in ext_js
    assert 'deselectNode()' in ext_js
    assert '.koto-img-toolbar-trigger' in css
    assert '.koto-img-wrapper.is-toolbar-open .koto-img-toolbar' in css
    assert '.koto-img-wrapper:hover .koto-img-toolbar' not in css


def test_docx_paragraph_extension_preserves_block_font_weight_and_style():
    ext_js = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )

    assert "fontWeight:" in ext_js
    assert "fontStyle:" in ext_js
    assert "kotoRole:" in ext_js
    assert "data-koto-role" in ext_js
    assert "styles.push(`font-weight:${a.fontWeight}`);" in ext_js
    assert "styles.push(`font-style:${a.fontStyle}`);" in ext_js


def test_docx_nodes_preserve_parser_role_attributes():
    ext_js = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )

    assert "getAttribute('data-koto-role')" in ext_js
    assert "'data-koto-role': attrs.kotoRole" in ext_js


def test_docx_tiptap_package_defines_runtime_build_script():
    package_json = (_repo_root() / "web" / "tiptap-editor" / "package.json").read_text(
        encoding="utf-8"
    )

    assert '"scripts"' in package_json
    assert '"build": "esbuild koto-docx-editor.js --bundle --outfile=../static/js/tiptap-docx-bundle.js --format=iife --global-name=KotoDocxEditorLib --minify --sourcemap"' in package_json


def test_docx_runtime_bundle_contains_role_and_shared_geometry_contracts():
    bundle_js = (_repo_root() / "web" / "static" / "js" / "tiptap-docx-bundle.js").read_text(
        encoding="utf-8"
    )

    assert "data-koto-role" in bundle_js
    assert "getDocxNavigationAnchorOffset()" in bundle_js
    assert "getDocxTargetScrollTop(" in bundle_js
    assert "scrollTop+this.getDocxNavigationAnchorOffset()" in bundle_js
    assert "this.getDocxTargetScrollTop(" in bundle_js


def test_docx_toggle_bold_and_italic_can_clear_block_level_text_styles():
    editor_js = (_repo_root() / "web" / "tiptap-editor" / "koto-docx-editor.js").read_text(
        encoding="utf-8"
    )

    assert "function _isDocxBoldValue(value)" in editor_js
    assert "function _isDocxItalicValue(value)" in editor_js
    assert "this._selectionHasBlockTextStyle('fontWeight', _isDocxBoldValue)" in editor_js
    assert "this._setSelectionBlockTextStyle('fontWeight', null)" in editor_js
    assert "this._selectionHasBlockTextStyle('fontStyle', _isDocxItalicValue)" in editor_js
    assert "this._setSelectionBlockTextStyle('fontStyle', null)" in editor_js
    assert "this._setCellSelectionBlockAttr('fontWeight', null, { defaultValue: null })" in editor_js
    assert "this._setCellSelectionBlockAttr('fontStyle', null, { defaultValue: null })" in editor_js


def test_docx_workspace_shell_uses_shared_tiptap_mount_and_no_slate_selection_fallback():
    shell_js = _workspace_runtime_sources()

    assert "async function _mountDocx(tab: TabInfo, data: any): Promise<void>" in shell_js
    assert "new (window as any).KotoDocxEditorLib.KotoTipTapEditor()" in shell_js
    assert "await _mountDocx(tab, data);" in shell_js
    assert "state.activeEditor.editor.selection" not in shell_js
    assert "Legacy Slate fallback (unused — kept for safety)" not in shell_js


def test_docx_outline_prefers_manifest_but_has_structural_dom_fallback():
    shell_js = _workspace_runtime_sources()

    assert "function _isValidDocxHeadingEntry(heading:" in shell_js
    assert ".filter(_isValidDocxHeadingEntry)" in shell_js
    assert "function _resolveDocxOutlineTarget(pm:" in shell_js
    assert "function _collectDocxOutlineHeadingsFromDom(pm:" in shell_js
    assert "function _resolveDocxOutlineHeadings(headings:" in shell_js
    assert 'data-koto-role="structural_heading"' in shell_js
    assert 'h1#${escapedId}[data-koto-role="structural_heading"]' in shell_js
    assert "function _filterDocxOutlineHeadingsByDomTargets(headings:" in shell_js
    assert "headings = _resolveDocxOutlineHeadings(headings);" in shell_js
    assert "if (_resolveDocxOutlineTarget(pm, heading)) resolved.push(heading);" in shell_js
    assert "DOCX outline manifest underfilled; falling back to DOM structural headings" in shell_js
    assert "function _bindDocxOutlineScrollSync(outline:" in shell_js
    assert "setTimeout(() => _setupDocOutline((data && data.headings) || []), 0);" in shell_js
    assert "p[class^=\"koto-toc-\"]" not in shell_js
    assert "textContent.trim().startsWith(heading.text)" not in shell_js
    assert "setTimeout(() => _setupDocOutline([]), 300);" not in shell_js
    assert "_setupDocOutline(fullData.headings || []);" not in shell_js


def test_docx_outline_click_and_scroll_sync_share_measured_offset_helpers():
    shell_js = _workspace_runtime_sources()
    editor_js = (_repo_root() / "web" / "tiptap-editor" / "koto-docx-editor.js").read_text(
        encoding="utf-8"
    )

    assert "function _getDocxNavigationAnchorOffset(editorScroll:" in shell_js
    assert "function _getDocxTargetScrollTop(editorScroll:" in shell_js
    assert "state.activeEditor" in shell_js
    assert "editorHost.getDocxNavigationAnchorOffset" in shell_js
    assert "editorHost.getDocxTargetScrollTop" in shell_js
    assert "editorScroll.scrollTop + _getDocxNavigationAnchorOffset(editorScroll, pm)" in shell_js
    assert "const targetTop = _getDocxTargetScrollTop(editorScroll, entry.target!);" in shell_js
    assert "const targetTop = _getDocxTargetScrollTop(editorScroll, target);" in shell_js
    assert "const offset = _getDocxNavigationAnchorOffset(editorScroll, pm);" in shell_js
    assert "getBoundingClientRect().top + 120" not in shell_js
    assert "relativeTop - 80" not in shell_js
    assert "getDocxNavigationAnchorOffset()" in editor_js
    assert "getDocxTargetScrollTop(target)" in editor_js
    assert "this._scrollEl.scrollTop + this.getDocxNavigationAnchorOffset()" in editor_js
    assert "const targetTop = this.getDocxTargetScrollTop(target);" in editor_js
    assert "const resolvedOffset = Number.isFinite(offset) ? offset : this.getDocxNavigationAnchorOffset();" in editor_js


def test_docx_font_size_toolbars_use_point_units_and_numeric_sync():
    editor_js = (_repo_root() / "web" / "tiptap-editor" / "koto-docx-editor.js").read_text(
        encoding="utf-8"
    )
    shell_js = _workspace_runtime_sources()

    assert '<option value="10pt">10</option>' in editor_js
    assert '<option value="72pt">72</option>' in editor_js
    assert "_getFontSizeOptionValue(fs, fontSizeSel.options" in editor_js
    assert "`${parseFloat(size)}pt`" in shell_js


def test_docx_font_family_toolbars_normalize_aliases_and_heading_styles():
    editor_js = (_repo_root() / "web" / "tiptap-editor" / "koto-docx-editor.js").read_text(
        encoding="utf-8"
    )
    shell_js = _workspace_runtime_sources()
    index_html = (_repo_root() / "web" / "templates" / "index.html").read_text(
        encoding="utf-8"
    )

    assert "value: 'SimSun'" in editor_js
    assert "value: 'DengXian'" in editor_js
    assert "value: 'STZhongsong'" in editor_js
    assert "function _getDocxBlockTextStyleValue(ed, attrName)" in editor_js
    assert "_getDocxFontFamilyOptionValue(ff, fontFamilySel.options)" in editor_js
    assert "const nextValue = cmd === 'setFontFamily' ? _resolveDocxFontFamily(value)" in shell_js
    assert "function _ensureDocxHoverBar(): HTMLElement | null" in shell_js
    assert "function _isReviewCommentModeEnabled(): boolean" in shell_js
    assert "declare function _ensureDocxHoverBar" not in shell_js
    assert "declare function _isReviewCommentModeEnabled" not in shell_js
    assert "_getDocxFontDisplayName(fontNameValue)" in shell_js
    assert '<option value="SimSun">' in index_html
    assert '<option value="STKaiti">' in index_html


def test_docx_hoverbar_reuses_ribbon_for_header_footer_overlay():
    js = _workspace_runtime_sources()
    assert "_safeGetDocxHdrFtrSelectionInfo" in js


def test_docx_review_mode_keeps_native_selection_for_comment_launcher():
    js = _workspace_runtime_sources()
    show_start = js.index("export function _showDocxHoverBar(): void")
    show_end = js.index("export function _kotoDocxSelectionChanged", show_start)
    show_fn = js[show_start:show_end]

    assert show_fn.index("if (_isReviewCommentModeEnabled())") < show_fn.index(
        "_getDocxSelectionPayload({ includeOverlay: false, allowStaleFallback: false })"
    )
    assert "_syncDocxHoverBarFromRibbon" in js
    assert "_dispatchDocxRibbonClick" in js
    assert "(window as any)._ttPickColor" in js


def test_docx_body_selection_prefers_live_native_selection_rects():
    js = _workspace_runtime_sources()
    assert "function _getDocxNativeSelectionBounds" in js
    assert "range.getClientRects ? range.getClientRects() : []" in js
    assert "const nativeBounds = _getDocxNativeSelectionBounds(pm, pmRect ? pmRect.left : 0);" in js
    assert "const anchorY = bounds.bottom > 0" in js


def test_docx_ai_selection_prefers_editor_table_payloads_over_native_last_cell_text():
    js = _workspace_runtime_sources()

    assert "function _getDocxSelectionPayload" in js
    assert "editorHost.getWholeTableSelectionInfo" in js
    assert "editorHost.getCellSelectionInfo" in js
    assert "editorHost.getSelectionTextForAI" in js
    assert "aiText: `[" in js and "${wholeTableText}\\n`," in js
    assert "Object.assign({}, docxSelection" in js
    assert "selectionKind: docxSelection.kind" in js
    assert "_updateContextBar({ table: docxSelection.previewText });" in js


def test_docx_header_footer_overlay_footer_alignment_and_marker_hooks_exist():
    css = (_repo_root() / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )
    ext_js = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )
    assert '.koto-hdrftr-overlay[data-slot-type="footer"]' in css
    assert 'justify-content: flex-end' in css
    assert '--koto-docx-marker-left' in css
    assert '--koto-docx-marker-left' in ext_js
    assert '_notifyHdrFtrSelectionChanged' in ext_js


def test_docx_page_break_markers_track_content_edges_and_footer_stays_bottom_aligned():
    css = (_repo_root() / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )

    end_marker = re.search(
        r"#wa-docx-editor \.koto-pb-end::before,\s*#wa-docx-editor \.koto-pb-end::after \{(.*?)\}",
        css,
        flags=re.S,
    )
    start_marker = re.search(
        r"#wa-docx-editor \.koto-pb-start::before,\s*#wa-docx-editor \.koto-pb-start::after \{(.*?)\}",
        css,
        flags=re.S,
    )
    footer_layout = re.search(
        r"#wa-docx-editor \.koto-pb-footer \{\s*top: 12px;\s*bottom: 0;\s*justify-content: flex-end;\s*\}",
        css,
        flags=re.S,
    )
    header_layout = re.search(
        r"#wa-docx-editor \.koto-pb-header \{\s*top: 0;\s*bottom: 12px;\s*justify-content: flex-start;\s*\}",
        css,
        flags=re.S,
    )

    assert end_marker and "top: 12px;" in end_marker.group(1)
    assert start_marker and "bottom: 12px;" in start_marker.group(1)
    assert footer_layout
    assert header_layout


def test_docx_page_break_header_zone_has_no_separator_shadow():
    css = (_repo_root() / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )
    header_zone = re.search(
        r"#wa-docx-editor \.koto-pb-start \{(.*?)\}",
        css,
        flags=re.S,
    )

    assert header_zone, ".koto-pb-start css block not found"
    assert "box-shadow: none" in header_zone.group(1)


def test_docx_first_page_header_markers_visible_and_header_overlay_has_no_outline():
    css = (_repo_root() / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )
    editor_js = (_repo_root() / "web" / "tiptap-editor" / "koto-docx-editor.js").read_text(
        encoding="utf-8"
    )
    ext_js = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )

    header_markers = re.search(
        r"#wa-docx-editor \.koto-page-header-first::before,\s*#wa-docx-editor \.koto-page-header-first::after \{(.*?)\}",
        css,
        flags=re.S,
    )

    assert header_markers and "bottom: 12px;" in header_markers.group(1)
    assert header_markers and "display: block" in header_markers.group(1)
    assert "background: #ffffff;" in css
    assert "#wa-docx-editor .koto-page-header-first::before { left: var(--koto-docx-marker-left, 84px); border-right: 1px solid #c8ccd8; border-bottom: 1px solid #c8ccd8; }" in css
    assert "#wa-docx-editor .koto-page-header-first::after  { right: var(--koto-docx-marker-right, 84px); border-left: 1px solid #c8ccd8; border-bottom: 1px solid #c8ccd8; }" in css
    assert re.search(
        r"dataset\.slotType = 'header';.*?overlay\.style\.cssText = '.*?outline:none;outline-offset:0;",
        editor_js,
        flags=re.S,
    )
    assert "const overlayOutline = type === 'header'" in ext_js
    assert "outline:none;outline-offset:0;" in ext_js

def test_docx_pagination_uses_boundary_markers_without_fixed_overlay_delay():
    editor_js = (_repo_root() / "web" / "tiptap-editor" / "koto-docx-editor.js").read_text(
        encoding="utf-8"
    )
    ext_js = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )
    e2e_test = (_repo_root() / "tests" / "e2e" / "test_docx_render.py").read_text(
        encoding="utf-8"
    )

    assert "requestAnimationFrame(() => this._setupPageFeatures());" in editor_js
    assert "setTimeout(() => this._setupPageFeatures(), 250);" not in editor_js
    assert "_forceRecalc" not in ext_js
    assert 'PAGE_BOUNDARY_SELECTOR = "[data-page-break],[data-soft-page-break]"' in e2e_test
    assert "koto-pb-overlay" not in e2e_test
    assert ".koto-pb-line" not in e2e_test


def test_docx_header_shells_neutralize_legacy_header_footer_separator_rules():
    css = (_repo_root() / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )
    neutralize_block = re.search(
        r"#wa-docx-editor \.koto-page-header-first \.koto-header,.*?#wa-docx-editor \.koto-hdrftr-overlay \.koto-footer \{(.*?)\}",
        css,
        flags=re.S,
    )

    assert neutralize_block, "Legacy header/footer neutralization block not found"
    block = neutralize_block.group(1)
    assert "border: 0;" in block
    assert "box-shadow: none;" in block
    assert "padding: 0;" in block


def test_canvas_body_does_not_clip_hoverbar():
    css = (_repo_root() / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )
    block = re.search(r"#wa-canvas-body\s*\{(.*?)\}", css, flags=re.S)
    assert block, "#wa-canvas-body css block not found"
    body_css = block.group(1)
    assert "overflow: visible" in body_css
    assert "overflow: hidden" not in body_css


def test_docx_tables_do_not_force_full_width_or_clip_right_edge():
    css = (_repo_root() / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )
    wrapper_block = re.search(
        r"#wa-docx-editor \.ProseMirror \.tableWrapper\s*\{(.*?)\}",
        css,
        flags=re.S,
    )
    assert wrapper_block, ".tableWrapper css block not found"
    wrapper_css = wrapper_block.group(1)
    assert "overflow: visible" in wrapper_css
    assert "overflow-x: clip" not in wrapper_css

    table_block = re.search(
        r"#wa-docx-editor \.ProseMirror table\.koto-docx-table\s*\{(.*?)\}",
        css,
        flags=re.S,
    )
    assert table_block, "table.koto-docx-table css block not found"
    table_css = table_block.group(1)
    assert "width: auto" in table_css
    assert "max-width: none" in table_css
    assert "width: 100%" not in table_css


def test_docx_prosemirror_fallback_line_height_matches_word_default():
    css = (_repo_root() / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )
    pm_block = re.search(r"#wa-docx-editor \.ProseMirror\s*\{(.*?)\}", css, flags=re.S)
    assert pm_block, ".ProseMirror css block not found"
    pm_css = pm_block.group(1)
    assert "font-size: 10.5pt" in pm_css
    assert "line-height: 1.15" in pm_css


def test_docx_typography_css_keeps_font_fallbacks_non_forcing():
    css = (_repo_root() / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )

    editable_block = re.search(
        r"#wa-docx-editor \[contenteditable=\"true\"\]\s*\{(.*?)\}",
        css,
        flags=re.S,
    )
    pm_block = re.search(r"#wa-docx-editor \.ProseMirror\s*\{(.*?)\}", css, flags=re.S)
    toc_block = re.search(
        r"#wa-docx-editor \[contenteditable=\"true\"\] p\[class\^=\"koto-toc-\"\],\s*#wa-docx-editor \.ProseMirror p\[class\^=\"koto-toc-\"\] \{(.*?)\}",
        css,
        flags=re.S,
    )

    assert editable_block, "editable DOCX root css block not found"
    assert pm_block, ".ProseMirror css block not found"
    assert toc_block, "DOCX TOC css block not found"
    assert "font-family:" in editable_block.group(1)
    assert "font-family:" in pm_block.group(1)
    assert "font-family:" in editable_block.group(1) and "!important" not in re.search(r"font-family:[^;]+;", editable_block.group(1)).group(0)
    assert "font-family:" in pm_block.group(1) and "!important" not in re.search(r"font-family:[^;]+;", pm_block.group(1)).group(0)
    assert "font-size: 12pt !important" not in toc_block.group(1)
    assert "font-weight: 400 !important" not in toc_block.group(1)


def test_docx_sanitizer_removes_forced_imported_table_widths():
    js = (_repo_root() / "web" / "tiptap-editor" / "koto-docx-editor.js").read_text(
        encoding="utf-8"
    )
    assert "table.koto-docx-table" in js
    assert "style.removeProperty('width')" in js
    assert "style.removeProperty('max-width')" in js


def test_docx_borderless_cell_marker_survives_live_dom_detection():
    css = (_repo_root() / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )
    editor_js = (_repo_root() / "web" / "tiptap-editor" / "koto-docx-editor.js").read_text(
        encoding="utf-8"
    )
    ext_js = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )

    assert "td[data-koto-borderless-cell=\"true\"]" in css
    assert "th[data-koto-borderless-cell=\"true\"]" in css
    assert "td[data-koto-borderless-cell=\"true\"]" in editor_js
    assert "th[data-koto-borderless-cell=\"true\"]" in editor_js
    assert re.search(
        r"kotoBorderlessCell:\s*\{\s*default:\s*false,\s*parseHTML:\s*el => el\.getAttribute\('data-koto-borderless-cell'\) === 'true'",
        ext_js,
        flags=re.S,
    )
    assert re.search(
        r"renderHTML:\s*attrs => attrs\.kotoBorderlessCell \? \{ 'data-koto-borderless-cell': 'true' \} : \{\}",
        ext_js,
    )


def test_docx_tables_paginate_with_row_level_soft_break_widgets():
    css = (_repo_root() / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )
    ext_js = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )

    assert "koto-table-page-break-row" in css
    assert "koto-table-page-break-cell" in css
    assert "_buildSoftBreakTableRow" in ext_js
    assert "_consumeTableRowspanState" in ext_js
    assert "_collectTableRowPaginationGroups" in ext_js
    assert "TableMap.get(node).width" in ext_js
    assert "tableCols" in ext_js


def test_docx_pagination_remeasures_after_media_load_and_visual_overflow():
    ext_js = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )
    scheduler_js = (_repo_root() / "web" / "tiptap-editor" / "docx-pagination-scheduler.js").read_text(
        encoding="utf-8"
    )

    assert "function _measureDocxBlockContentHeightPx(element)" in ext_js
    assert "_measureDocxBlockOuterHeightPx(domEl)" in ext_js
    assert "'img,svg,canvas,video,.koto-img-wrapper'" in scheduler_js
    assert "new ResizeObserver" in scheduler_js
    assert "node.addEventListener('load', onSettled" in scheduler_js
    assert "scheduleAfterMediaSettles" in scheduler_js
