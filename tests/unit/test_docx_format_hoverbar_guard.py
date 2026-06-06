import re
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_docx_tooltip_buttons_keep_editor_focus():
    html = (_repo_root() / "web" / "templates" / "workspace_assistant.html").read_text(
        encoding="utf-8"
    )
    start_match = re.search(r'<div id="wa-pdf-tooltip" class="[^"]*">', html)
    end_marker = "<!-- Chart Generation Dialog -->"
    assert start_match is not None, "wa-pdf-tooltip block not found"
    start = start_match.start()
    end = html.find(end_marker, start)
    assert end != -1, "wa-pdf-tooltip block end marker not found"
    tooltip_block = html[start:end]
    assert tooltip_block.count('onmousedown="event.preventDefault()"') >= 6


def test_docx_hoverbar_has_font_controls():
    js = (_repo_root() / "web" / "static" / "js" / "workspace-assistant.js").read_text(
        encoding="utf-8"
    )
    assert "fontFamily" in js
    assert "fontSize" in js


def test_docx_font_size_extension_defines_commands_and_stores_point_sizes():
    ext_js = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )

    assert "setFontSize: fontSize => ({ chain }) => {" in ext_js
    assert "unsetFontSize: () => ({ chain }) => {" in ext_js
    assert "return `${formatted}pt`;" in ext_js


def test_docx_paragraph_extension_preserves_block_font_weight_and_style():
    ext_js = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )

    assert "fontWeight:" in ext_js
    assert "fontStyle:" in ext_js
    assert "styles.push(`font-weight:${a.fontWeight}`);" in ext_js
    assert "styles.push(`font-style:${a.fontStyle}`);" in ext_js


def test_docx_toggle_bold_and_italic_can_clear_block_level_text_styles():
    editor_js = (
        _repo_root() / "web" / "tiptap-editor" / "koto-docx-editor.js"
    ).read_text(encoding="utf-8")

    assert "function _isDocxBoldValue(value)" in editor_js
    assert "function _isDocxItalicValue(value)" in editor_js
    assert (
        "this._selectionHasBlockTextStyle('fontWeight', _isDocxBoldValue)" in editor_js
    )
    assert "this._setSelectionBlockTextStyle('fontWeight', null)" in editor_js
    assert (
        "this._selectionHasBlockTextStyle('fontStyle', _isDocxItalicValue)" in editor_js
    )
    assert "this._setSelectionBlockTextStyle('fontStyle', null)" in editor_js
    assert (
        "this._setCellSelectionBlockAttr('fontWeight', null, { defaultValue: null })"
        in editor_js
    )
    assert (
        "this._setCellSelectionBlockAttr('fontStyle', null, { defaultValue: null })"
        in editor_js
    )


def test_docx_workspace_shell_uses_shared_tiptap_mount_and_no_slate_selection_fallback():
    shell_js = (
        _repo_root() / "web" / "static" / "js" / "workspace-assistant.js"
    ).read_text(encoding="utf-8")

    assert "async function _mountDocxEditor(tab, html, docxData, headings)" in shell_js
    assert shell_js.count("new KotoDocxEditorLib.KotoTipTapEditor();") == 1
    assert shell_js.count("await _mountDocxEditor(") >= 3
    assert "state.activeEditor.editor.selection" not in shell_js
    assert "Legacy Slate fallback (unused — kept for safety)" not in shell_js


def test_docx_font_size_toolbars_use_point_units_and_numeric_sync():
    editor_js = (
        _repo_root() / "web" / "tiptap-editor" / "koto-docx-editor.js"
    ).read_text(encoding="utf-8")
    shell_js = (
        _repo_root() / "web" / "static" / "js" / "workspace-assistant.js"
    ).read_text(encoding="utf-8")

    assert '<option value="10pt">10</option>' in editor_js
    assert '<option value="72pt">72</option>' in editor_js
    assert "_getFontSizeOptionValue(fs, fontSizeSel.options" in editor_js
    assert "`${parseFloat(size)}pt`" in shell_js


def test_docx_font_family_toolbars_normalize_aliases_and_heading_styles():
    editor_js = (
        _repo_root() / "web" / "tiptap-editor" / "koto-docx-editor.js"
    ).read_text(encoding="utf-8")
    shell_js = (
        _repo_root() / "web" / "static" / "js" / "workspace-assistant.js"
    ).read_text(encoding="utf-8")
    index_html = (_repo_root() / "web" / "templates" / "index.html").read_text(
        encoding="utf-8"
    )

    assert '<option value="SimSun">宋体</option>' in editor_js
    assert '<option value="DengXian">等线</option>' in editor_js
    assert '<option value="STZhongsong">华文中宋</option>' in editor_js
    assert "function _getDocxBlockTextStyleValue(ed, attrName)" in editor_js
    assert "_getDocxFontFamilyOptionValue(ff, fontFamilySel.options)" in editor_js
    assert (
        "const nextValue = cmd === 'setFontFamily' ? _resolveDocxFontFamily(value)"
        in shell_js
    )
    assert (
        "const fontName  = attrs.fontFamily || _getDocxBlockTextStyleValue(ed, 'fontFamily') || '';"
        in shell_js
    )
    assert "_getDocxFontDisplayName(fontNameValue)" in shell_js
    assert '<option value="SimSun">宋体</option>' in index_html
    assert '<option value="STKaiti">华文楷体</option>' in index_html


def test_docx_hoverbar_reuses_ribbon_for_header_footer_overlay():
    js = (_repo_root() / "web" / "static" / "js" / "workspace-assistant.js").read_text(
        encoding="utf-8"
    )
    assert "_getActiveDocxHdrFtrOverlay" in js
    assert "_syncDocxHoverBarFromRibbon" in js
    assert "_dispatchDocxRibbonClick" in js
    assert "window._ttPickColor" in js


def test_docx_body_selection_prefers_live_native_selection_rects():
    js = (_repo_root() / "web" / "static" / "js" / "workspace-assistant.js").read_text(
        encoding="utf-8"
    )
    assert "function _getDocxNativeSelectionBounds" in js
    assert "range.getClientRects ? range.getClientRects() : []" in js
    assert "const nativeBounds = _getDocxNativeSelectionBounds(pm, pmR.left);" in js
    assert "const anchorY = bounds.bottom > 0" in js


def test_docx_header_footer_overlay_footer_alignment_and_marker_hooks_exist():
    css = (_repo_root() / "web" / "static" / "css" / "workspace.css").read_text(
        encoding="utf-8"
    )
    ext_js = (_repo_root() / "web" / "tiptap-editor" / "docx-extensions.js").read_text(
        encoding="utf-8"
    )
    assert '.koto-hdrftr-overlay[data-slot-type="footer"]' in css
    assert "justify-content: flex-end" in css
    assert "--koto-docx-marker-left" in css
    assert "--koto-docx-marker-left" in ext_js
    assert "_notifyHdrFtrSelectionChanged" in ext_js


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
    editor_js = (
        _repo_root() / "web" / "tiptap-editor" / "koto-docx-editor.js"
    ).read_text(encoding="utf-8")
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
    assert (
        "#wa-docx-editor .koto-page-header-first::before { left: var(--koto-docx-marker-left, 84px); border-right: 1px solid #c8ccd8; border-bottom: 1px solid #c8ccd8; }"
        in css
    )
    assert (
        "#wa-docx-editor .koto-page-header-first::after  { right: var(--koto-docx-marker-right, 84px); border-left: 1px solid #c8ccd8; border-bottom: 1px solid #c8ccd8; }"
        in css
    )
    assert re.search(
        r"dataset\.slotType = 'header';.*?overlay\.style\.cssText = '.*?outline:none;outline-offset:0;",
        editor_js,
        flags=re.S,
    )
    assert "const overlayOutline = type === 'header'" in ext_js
    assert "outline:none;outline-offset:0;" in ext_js


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
        r"#wa-docx-editor \[data-slate-editor\],\s*#wa-docx-editor \[contenteditable=\"true\"\] \{(.*?)\}",
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
    assert "font-family:" in editable_block.group(1) and "!important" not in re.search(
        r"font-family:[^;]+;", editable_block.group(1)
    ).group(0)
    assert "font-family:" in pm_block.group(1) and "!important" not in re.search(
        r"font-family:[^;]+;", pm_block.group(1)
    ).group(0)
    assert "font-size: 12pt !important" not in toc_block.group(1)
    assert "font-weight: 400 !important" not in toc_block.group(1)


def test_docx_sanitizer_removes_forced_imported_table_widths():
    js = (_repo_root() / "web" / "tiptap-editor" / "koto-docx-editor.js").read_text(
        encoding="utf-8"
    )
    assert "table.koto-docx-table" in js
    assert "style.removeProperty('width')" in js
    assert "style.removeProperty('max-width')" in js


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
    assert "TableMap.get(node).width" in ext_js
    assert "tableCols" in ext_js
