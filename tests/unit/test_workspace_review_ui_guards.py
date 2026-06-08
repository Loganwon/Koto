from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def test_review_shell_entry_is_present_without_ai_comment_entrypoints():
    embedded_html = _read("web/templates/index.html")
    standalone_html = _read("web/templates/workspace_assistant.html")
    asset_partial = _read("web/templates/_workspace_asset_scripts.html")

    for html in (embedded_html, standalone_html):
        assert "{% include '_workspace_asset_scripts.html' %}" in html
        assert 'id="wa-review-shell"' in html
        assert 'id="wa-review-mode-group"' in html
        assert '>批注模式<' in html
        assert 'id="wa-review-toggle-btn"' not in html
        assert "onclick=\"WA.sendQuickAction('批注')\"" not in html
        assert "onclick=\"WA.addSelectionComment()\"" not in html
        assert '>AI 批注<' not in html

    assert "docx-review-layout.js" in asset_partial


def test_workspace_hydrates_native_docx_review_state_and_exposes_visible_review_entry():
    js = _read("web/static/js/workspace-assistant.js")
    layout_js = _read("web/static/js/docx-review-layout.js")
    css = _read("web/static/css/workspace.css")

    assert "function _syncReviewStateForActiveFile" in js
    assert "function _syncDocCommentStateForActiveFile" in js
    assert "function _isImportedDocxRevisionProposal" in js
    assert "raw.source = String(raw.source || '').trim() || 'ai';" in js
    assert "tab.serverData.proposals = reviewState.proposals.map((proposal) => _serializeReviewProposal(proposal));" in js
    assert "function _isReviewCommentModeEnabled" in js
    assert "function _focusFirstReviewEntry" in js
    assert "function _coerceReviewModeForVisibleContent" in js
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
    assert "const showRail = !!state._reviewCenterOpen;" in js
    assert "shell.style.display = showRail ? '' : 'none';" in js
    assert "shell.dataset.commentUi = state.fileType === 'docx' ? 'wps' : '';" in js
    assert "function _getDocxReviewRailMetrics" in js
    assert "const DEFAULT_REVIEW_RAIL_LEFT_SHIFT = 200;" in layout_js
    assert "function _shiftReviewRailLeft(value, host)" in layout_js
    assert "const minRailWidth  = 132;" in layout_js
    assert "parseFloat(hostStyles.getPropertyValue('--wa-review-rail-width'))" in layout_js
    assert "host.style.setProperty('--wa-review-rail-width', `${Math.round(railWidth)}px`);" not in layout_js
    assert "_setDocxReviewRailWidth(host, railWidth);" in layout_js
    assert "const pagePaddingRight = Math.max(0, parseFloat(window.getComputedStyle(pageEl).paddingRight) || 0);" in layout_js
    assert "const laneLeft         = Math.round(textColRight + anchorGap);" in layout_js
    assert "railWidth," in layout_js
    assert "laneLeft," in layout_js
    assert "const shiftedCardColLeft = Math.max(12, _shiftReviewRailLeft(rawCardColLeft, host));" in layout_js
    assert "const maxCardColLeft = Math.max(" in layout_js
    assert "const cardColLeft = Math.max(12, Math.min(shiftedCardColLeft, maxCardColLeft));" in layout_js
    assert "function _resolveReviewPageBoundsForScreenY" in layout_js
    assert "function _collectReviewVisualPageBounds" in layout_js
    assert "pageRoot.querySelectorAll('.koto-page-break')" in layout_js
    assert "upperBottom: _screenYToReviewContentY(endRect.bottom, layoutState)" in layout_js
    assert "nextTop: _screenYToReviewContentY(startRect.top, layoutState)" in layout_js
    assert "pageTop: pageBounds ? pageBounds.top : null" in layout_js
    assert "pageBottom: pageBounds ? pageBounds.bottom : null" in layout_js
    assert "function _reviewAnchorHeight(anchorGeometry)" in layout_js
    assert "function _clampReviewConnectorOffsetY(anchorGeometry, cardHeight)" in layout_js
    assert "function _reviewLayoutEntryBottom(entry)" in layout_js
    assert "entry.collisionHeight || 0" in layout_js
    assert "function _resolveNonOverlappingCardTop(layoutEntries, desiredTop, desiredLeft, cardWidth, cardHeight, bounds, cardCollisionHeight)" in layout_js
    assert "const effectiveCardHeight = Math.max(" in layout_js
    assert "let resolvedByCollision = false;" in layout_js
    assert "resolvedByCollision = true;" in layout_js
    assert "const driftMaxTop = Number.isFinite(maxAnchorDrift) && Number.isFinite(desiredTop)" in layout_js
    assert "const measuredCards = cards.map((card, index) =>" in layout_js
    assert "card.style.removeProperty('--wa-review-card-anchor-min-height');" in layout_js
    assert "const anchorHeight = _reviewAnchorHeight(anchorGeometry);" in layout_js
    assert "card.style.setProperty('--wa-review-card-anchor-min-height'" in layout_js
    assert "const cardCollisionHeight = Math.max(cardHeight, anchorHeight);" in layout_js
    assert "Math.round(anchorGeometry.top - 2)" in layout_js
    assert "}).sort((a, b) =>" in layout_js
    assert "const peerEntries = item.pageBounds" in layout_js
    assert "entry.pageTop === item.pageBounds.minTop" in layout_js
    assert "item.cardCollisionHeight," in layout_js
    assert "collisionHeight: item.cardCollisionHeight" in layout_js
    assert "Math.max(...layoutEntries.map((entry) => _reviewLayoutEntryBottom(entry))) + 24" in layout_js
    assert "card.classList.add('is-page-bounded');" in layout_js
    assert "card.style.setProperty('--wa-review-card-page-max-height'" in layout_js
    assert "min-height: var(--wa-review-card-anchor-min-height, 20px);" in css
    assert "min-height: var(--wa-review-card-anchor-min-height, 42px);" in css
    assert "function _layoutReviewShellInDocx" in js
    assert "function _ensureReviewSelectionLauncher" in js
    assert "const selectionRight = Number.isFinite(cursorRight)" in layout_js
    assert "const launcherLeft = Math.min(selectionRight, maxLauncherLeft);" in layout_js
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
    assert ">添加到选区<" not in layout_js
    assert ">添加批注或修订<" in layout_js
    assert "wa-review-selection-kicker" in layout_js
    assert "wa-review-selection-copy" in layout_js
    assert "wa-review-btn-icon" in js


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
    assert "--wa-review-rail-left-shift: 200px;" in css
    assert ".wa-review-composer-card" in css
    assert ".wa-review-selection-box" in css
    assert ".wa-review-selection-kicker" in css
    assert ".wa-review-selection-copy" in css
    assert "#wa-docx-editor.has-review-shell #wa-editor-content" in css
    assert "#wa-docx-editor > #wa-review-shell.wa-review-shell-docx" in css
    assert "#wa-review-selection-launcher" in css
    assert ".wa-review-selection-add" in css
    assert ".wa-review-selection-subtitle" in css
    assert "font-size: 12px;" in css
    assert "text-overflow: ellipsis;" in css
    assert "writing-mode: horizontal-tb;" in css
    assert "border-radius: 8px;" in css
    assert "border-left: 3px solid var(--accent);" in css
    assert "border-left: 3px solid #0f766e;" in css
    assert "max-width: calc(var(--wa-review-rail-width, 220px) - 52px);" in css
    assert ".wa-review-anchor-link" in css
    assert ".wa-docx-review-mode" in css
    assert ".wa-docx-review-summary" in css
    assert ".wa-docx-review-nav" in css
    assert ".wa-docx-review-nav-menu" in css
    assert ".is-page-bounded" in css
    assert "--wa-review-card-page-max-height" in css
    assert "overflow: auto !important;" in css
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
