from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def test_review_shell_entry_is_present_without_ai_comment_entrypoints():
    embedded_html = _read("web/templates/index.html")
    standalone_html = _read("web/templates/workspace_assistant.html")

    for html in (embedded_html, standalone_html):
        assert "docx-review-layout.js" in html
        assert 'id="wa-review-shell"' in html
        assert 'id="wa-review-mode-group"' in html
        assert '>批注模式<' in html
        assert 'id="wa-review-toggle-btn"' not in html
        assert "onclick=\"WA.sendQuickAction('批注')\"" not in html
        assert "onclick=\"WA.addSelectionComment()\"" not in html
        assert '>AI 批注<' not in html


def test_workspace_hydrates_native_docx_review_state_and_exposes_visible_review_entry():
    js = _read("web/static/js/workspace-assistant.js")
    layout_js = _read("web/static/js/docx-review-layout.js")

    assert "function _syncReviewStateForActiveFile" in js
    assert "function _syncDocCommentStateForActiveFile" in js
    assert "function _isImportedDocxRevisionProposal" in js
    assert "source: String(raw.source || '').trim() || 'ai'" in js
    assert "tab.serverData.proposals = proposals.map((proposal) => _cloneSerializable(proposal, {}) || {});" in js
    assert "function _isReviewCommentModeEnabled" in js
    assert "function _focusFirstReviewEntry" in js
    assert "function _coerceReviewModeForVisibleContent" in js
    assert "function _shouldShowPassiveDocxReviewRail" in js
    assert "function _getReviewCommentSelectionState(options = {})" in js
    assert "includeAnchorMeta = !!(options && options.includeAnchorMeta);" in js
    assert "function _getDocxSelectionPayload({ includeOverlay = true, allowStaleFallback = true, includeAnchorMeta = false } = {})" in js
    assert "function _buildReviewNavItems" in js
    assert "function _renderReviewNavMenuItems" in js
    assert "function _closeDocxReviewNavMenu" in js
    assert "function _setDocxReviewRailWidth" in js
    assert "window.KotoDocxReviewLayout" in layout_js
    assert "window.KotoDocxReviewLayout.create" in js
    assert "function _ensureReviewShellHost" in js
    assert "const showPassiveRail = _shouldShowPassiveDocxReviewRail(reviewState);" in js
    assert "shell.dataset.passiveRail = (!state._reviewCenterOpen && showPassiveRail) ? '1' : '0';" in js
    assert "shell.dataset.commentUi = state.fileType === 'docx' ? 'wps' : '';" in js
    assert "function _getDocxReviewRailMetrics" in js
    assert "const contentRight = Math.round(viewportRect.right - hostRect.left);" in layout_js
    assert "const fallbackLeft = Math.max(0, contentRight - resolvedRailWidth - railGap);" in layout_js
    assert "const preferredRailWidth = Math.round(Math.max(156, Math.min(248, viewportRect.width * 0.18)));" in layout_js
    assert "const availableRailWidth = Math.max(0, Math.round(contentRight - desiredLeft - safeViewportInset));" in layout_js
    assert "host.style.setProperty('--wa-review-rail-width', `${Math.round(railWidth)}px`);" not in layout_js
    assert "_setDocxReviewRailWidth(host, resolvedRailWidth);" in layout_js
    assert "const pagePaddingRight = Math.max(0, parseFloat(window.getComputedStyle(pageEl).paddingRight) || 0);" in layout_js
    assert "const pageScaleX = pageEl.offsetWidth > 0 ? (pageRect.width / pageEl.offsetWidth) : 1;" in layout_js
    assert "const visiblePaddingRight = Math.round(pagePaddingRight * pageScaleX);" in layout_js
    assert "const desiredLeft = textColRightRelHost + railGap;" in layout_js
    assert "railWidth: resolvedRailWidth," in layout_js
    assert "railLeft: Math.max(0, railLeft)," in layout_js
    assert "const maxRailWidth = Math.round(Math.max(188, Math.min(248, viewportRect.width * 0.22)));" in layout_js
    assert "function _layoutReviewShellInDocx" in js
    assert "function _ensureReviewSelectionLauncher" in js
    assert "const selectionRight = Number.isFinite(bounds.right)" in layout_js
    assert "const launcherLeft = Math.max(0, Math.min(selectionRight, maxLauncherLeft));" in layout_js
    assert "function _bindReviewShellInteractions" in js
    assert "if (tab.serverData && Array.isArray(tab.serverData.proposals)) {" in js
    assert "window.WA.openReviewCenter" in js
    assert "window.WA.toggleReviewCommentMode" in js
    assert "window.WA.toggleReviewNavMenu" in js
    assert "window.WA.toggleReviewOverview" in js
    assert "window.WA.createReviewComment" in js
    assert "window.WA.relayoutDocxReviewRail" in js
    assert "window.WA.deleteReviewComment" in js
    assert "window.WA.editReviewComment" in js
    assert "window.WA.handleReviewCommentCardActivate" in js
    assert "window.WA.handleReviewProposalCardActivate" in js
    assert "window.WA.focusReviewThread" in js
    assert "window.WA.onReviewCommentInput" in js
    assert "window.WA.applyStructuredDocToolCall" in js
    assert "window.WA.applyStructuredReviewChangePayload" in js
    assert "function _isReviewEditorFocused" in js
    assert "let minLeft = Infinity, maxRight = -Infinity;" in js
    assert "right: maxRight !== -Infinity ? maxRight : centerX," in js
    assert "state._editingReviewCommentId" in layout_js
    assert "if (!shell || !host || !viewport || !listEl || shell.style.display === 'none')" in layout_js
    assert "|| !_isReviewCommentModeEnabled()" in layout_js
    assert "_syncReviewSelectionSnapshot({ preserveExisting: true });" in js
    assert "_getDocxSelectionPayload({ includeOverlay: true, allowStaleFallback: false, includeAnchorMeta: true });" in js
    assert "_getReviewCommentSelectionState({ includeAnchorMeta: true })" in js
    assert "_coerceReviewModeForVisibleContent(nextReviewState, 'comment')" in js
    assert "_coerceReviewModeForVisibleContent(reviewState);" in js
    assert "const hasAnyVisibleReviewEntries = _reviewModeHasVisibleEntries(reviewState, 'all');" in js
    assert "const preserveCommentModeEmptyState = _isReviewCommentModeEnabled() && !hasAnyVisibleReviewEntries;" in js
    assert "if (!preserveCommentModeEmptyState) {" in js
    assert "const shell = $('wa-review-shell');" in js
    assert "shell && shell.style.display !== 'none'" in js
    assert "return source === 'docx_revision' && ['replace', 'delete', 'insert'].includes(actionType);" in js
    assert "data-koto-review-id" in js
    assert "_syncReviewStateForActiveFile().catch" in js
    assert "window.WA.onDocxCommentsChanged" in js
    assert "wa-review-anchor-link" in js
    assert "launcher.id = 'wa-review-selection-launcher';" in layout_js
    assert "_el.closest('#wa-review-selection-launcher')" in js
    assert "#wa-review-selection-launcher:hover" in js
    assert 'data-review-nav-id="' in js
    assert 'data-review-nav-overview="1"' in js
    assert 'data-review-action="edit"' in js
    assert 'data-review-action="delete"' in js
    assert 'data-review-action="save"' in js
    assert "proposal.original_text || proposal.anchor_text || proposal.proposed_text" in js
    assert "_resizeReviewCommentEditor" in js
    assert "原文定位：" not in js
    assert "window.WA.addSelectionComment" not in js
    assert "'批注': 'comment'" not in js
    assert "wa-review-toggle-btn" not in js
    assert "wa_docx_review_visible" not in js
    assert "function _ensureReviewToggleBtn" not in js
    assert "wa-docx-review-toggle" not in js
    assert "AI 批注当前仅支持 DOCX 文档视图" not in js


def test_workspace_review_css_keeps_native_comment_surfaces():
    css = _read("web/static/css/workspace.css")

    assert ".koto-comment-anchor" in css
    assert ".koto-docx-comment-layer" in css
    assert ".koto-docx-comment-card" in css
    assert ".koto-docx-comment-edit" in css
    assert ".koto-docx-comment-head-end" in css
    assert ".koto-docx-comment-inline-action" in css
    assert "[data-comment-ui=\"wps\"] .koto-docx-comment-card" in css
    assert "[data-comment-ui=\"wps\"] .koto-docx-comment-badge" in css
    assert "--wa-review-rail-gap" in css
    assert "--wa-review-rail-width: clamp(156px, 18vw, 248px);" in css
    assert ".wa-review-composer-card" in css
    assert ".wa-review-selection-box" in css
    assert "#wa-docx-editor.has-review-shell #wa-editor-content" in css
    assert "#wa-docx-editor > #wa-review-shell.wa-review-shell-docx" in css
    assert "#wa-review-selection-launcher" in css
    assert ".wa-review-selection-add" in css
    assert "max-width: calc(var(--wa-review-rail-width, 220px) - 52px);" in css
    assert ".wa-review-anchor-link" in css
    assert ".wa-docx-review-mode" in css
    assert ".wa-docx-review-summary" in css
    assert ".wa-docx-review-nav" in css
    assert ".wa-docx-review-nav-menu" in css
    assert "overflow: visible; /* keep review nav menu dropdown from being clipped */" in css
    assert "overflow-y: auto;" in css
    assert ".koto-docx-track-change" in css
    assert ".koto-docx-track-change-insert" in css
    assert ".koto-docx-track-change-delete" in css
    assert ".koto-docx-review-focus-flash" in css
    assert ".wa-docx-review-nav-item" in css
    assert ".wa-review-toggle-btn" not in css
    assert ".wa-review-toggle-count" not in css
    assert ".wa-docx-review-toggle" not in css


def test_docx_editor_render_preserves_review_shell_and_launcher_on_rerender():
    editor_js = _read("web/tiptap-editor/koto-docx-editor.js")
    ext_js = _read("web/tiptap-editor/docx-extensions.js")

    assert "const _reviewShell = wrap.querySelector('#wa-review-shell');" in editor_js
    assert "const _reviewLauncher = wrap.querySelector('#wa-review-selection-launcher');" in editor_js
    assert "if (_reviewShell) wrap.appendChild(_reviewShell);" in editor_js
    assert "if (_reviewLauncher) wrap.appendChild(_reviewLauncher);" in editor_js
    assert "window.WA.relayoutDocxReviewRail" in editor_js
    assert "applyImportedReviewDecision(proposal, decision = 'accept')" in editor_js
    assert "this._renderReviewProposalAnchors();" in editor_js
    assert "DocxTrackChange" in editor_js
    assert "DocxTrackChangePart" in editor_js
    assert "export const DocxTrackChange = Mark.create" in ext_js
    assert "export const DocxTrackChangePart = Mark.create" in ext_js