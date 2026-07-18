from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (_repo_root() / rel_path).read_text(encoding="utf-8")


def test_review_state_reads_preserve_live_entry_identity():
    source = _read("web/src/review/state.ts")

    assert "Object.assign(comment, normalizeReviewComment(comment, index))" in source
    assert "Object.assign(proposal, normalizeReviewProposal(proposal, index))" in source
    assert "existing.comments = rawComments.map(normalizeReviewComment)" not in source


def test_review_shell_entry_is_present_without_ai_comment_entrypoints():
    embedded_html = _read("web/templates/index.html")
    asset_partial = _read("web/templates/_workspace_asset_scripts.html")

    assert "{% include '_workspace_asset_scripts.html' %}" in embedded_html
    assert 'id="wa-review-shell"' in embedded_html
    assert 'class="wa-review-shell wa-review-shell-docx"' in embedded_html
    assert 'id="wa-review-mode-group"' not in embedded_html
    assert "WA.closeReviewCenter()" not in embedded_html
    assert "WA.setReviewMode(" not in embedded_html
    assert 'id="wa-review-toggle-btn"' not in embedded_html
    assert "onclick=\"WA.sendQuickAction('批注')\"" not in embedded_html
    assert 'onclick="WA.addSelectionComment()"' not in embedded_html
    assert ">AI 批注<" not in embedded_html

    assert "review-bundle.js" not in asset_partial
    assert "docx-review-layout.js" not in asset_partial


def test_workspace_hydrates_native_docx_review_state_and_exposes_visible_review_entry():
    js = "\n".join(
        [
            _read("web/src/workspace/docx-review-runtime.ts"),
            _read("web/src/workspace/docx-review-api.ts"),
            _read("web/src/workspace/file-open.ts"),
            _read("web/src/workspace/ai-review.ts"),
            _read("web/src/ui/selection-toolbar.ts"),
            _read("web/src/ui/docx-pptx-toolbar.ts"),
        ]
    )
    layout_js = "\n".join(
        [
            _read("web/src/review/layout-position.ts"),
            _read("web/src/review/layout-svg.ts"),
        ]
    )
    geometry_js = _read("web/src/review/geometry.ts")
    review_engine_entry = _read("web/src/bundles/docx-review-engine.ts")
    review_loader = _read("web/src/workspace/docx-review-loader.ts")
    workspace_bundle = _read("web/static/js/build/workspace-bundle.js")
    review_engine_bundle = _read("web/static/js/build/docx-review-engine-bundle.js")
    css = _read("web/static/css/workspace.css")

    assert "function _syncReviewStateForActiveFile" in js
    assert "function _syncDocCommentStateForActiveFile" in js
    assert "function _ensureTabReviewState(tab: any = _activeReviewTab()): any" in js
    assert "function _normalizeReviewComment(comment: any, index = 0): any" in js
    assert (
        "function _mergeReviewProposals(existing: any[], incoming: any[]): any[]" in js
    )
    assert "reviewState: existingTab && existingTab.reviewState" in js
    assert "return Promise.resolve(reviewState);" in js
    assert "void syncReviewStateForActiveFile();" in js
    assert "function _isImportedDocxRevisionProposal" in js
    review_state = _read("web/src/review/state.ts")
    assert "source: cleanString(raw.source) || 'ai_proposal'," in review_state
    assert (
        "tab.serverData.proposals = reviewState.proposals.map((proposal: any) => _clone(proposal, {}) || {});"
        in js
    )
    assert "function _isReviewCommentModeEnabled" in js
    assert "function _findReviewEntry" in js
    assert "export async function focusReviewThread" in js
    assert "function _coerceReviewModeForVisibleContent" in js
    assert "function _getReviewCommentSelectionState(): any" in js
    assert "supported: true" in js
    assert "supported: false, selection: null" in js
    assert "selectionState.supported" in layout_js
    assert "selectionState && selectionState.selection" in layout_js
    assert "const includeAnchorMeta = !!opts.includeAnchorMeta;" in js
    assert "function _getDocxSelectionPayload(options?:" in js
    assert "function _renderReviewNavMenu(): void" in js
    assert "function _scrollReviewCardIntoView(reviewId: string): void" in js
    assert "function _createReviewComment(): void" in js
    assert "function _setDocxReviewRailWidth" in js
    assert "from '../review/layout-position';" not in js
    assert "from '../review/state';" not in js
    assert "createDocxReviewLayout," in review_engine_entry
    assert "createReviewState," in review_engine_entry
    assert "KotoDocxReviewEngineModule" in review_engine_entry
    assert "export function installDocxReviewEngine" in js
    assert "reviewEngineModule.createDocxReviewLayout({" in js
    assert "export function loadDocxReviewEngine" in review_loader
    assert "await Promise.all([_ensureTipTap(), loadDocxReviewEngine()]);" in js
    assert "(window as any).KotoDocxReviewLayout" not in layout_js
    assert "function _ensureReviewShellHost" in js
    assert "state._reviewCenterOpen === false || !hasEntries" in js
    assert "ensureReviewShellHost" in js
    assert "const DEFAULT_REVIEW_RAIL_LEFT_SHIFT = 0;" in layout_js
    assert (
        "function _shiftReviewRailLeft(value: number, host: HTMLElement | null): number"
        in layout_js
    )
    assert "const DEFAULT_REVIEW_RAIL_RIGHT_SHIFT = 0;" in layout_js
    assert (
        "function _reviewRailRightShift(host: HTMLElement | null): number" in layout_js
    )
    assert (
        "function _positionReviewRail(value: number, host: HTMLElement | null): number"
        in layout_js
    )
    assert (
        "function _reviewLayoutScale(element: HTMLElement | null, rect: DOMRect | null): LayoutScale"
        in layout_js
    )
    assert (
        "function _screenDeltaToLayout(delta: number, scale: number): number"
        in layout_js
    )
    assert "const minRailWidth  = 220;" in layout_js
    assert "const minRailWidth = 220;" in geometry_js
    assert (
        "parseFloat(hostStyles.getPropertyValue('--wa-review-rail-width'))" in layout_js
    )
    assert (
        "host.style.setProperty('--wa-review-rail-width', `${Math.round(railWidth)}px`);"
        not in layout_js
    )
    assert "_setDocxReviewRailWidth(host, railWidth);" in layout_js
    assert "_setDocxReviewRailWidth(host, geo.railWidth);" in layout_js
    assert "/ (layoutScale.x || 1)" in layout_js
    assert "/ (layoutScale.y || 1)" in layout_js
    assert (
        "if (!textIndex) textIndex = svg._buildReviewTextIndex(contentRoot as HTMLElement);"
        in layout_js
    )
    assert "_buildReviewTextIndex" not in workspace_bundle
    assert "_buildReviewTextIndex" in review_engine_bundle
    assert "function _ensureReviewAnchorHighlightLayer" in layout_js
    assert "function _drawReviewAnchorHighlight" in layout_js
    assert "wa-review-anchor-highlight-layer" not in workspace_bundle
    assert "wa-review-anchor-highlight-rect" not in workspace_bundle
    assert "wa-review-anchor-highlight-layer" in review_engine_bundle
    assert "wa-review-anchor-highlight-rect" in review_engine_bundle
    assert (
        "const pagePaddingRight = Math.max(0, parseFloat(window.getComputedStyle(pageEl!).paddingRight) || 0);"
        in layout_js
    )
    assert (
        "const textColRight     = Math.round(pageContentRight - (pagePaddingRight * (transformScale.x || 1)));"
        in layout_js
    )
    assert "const laneLeft         = Math.round(textColRight + anchorGap);" in layout_js
    assert "railWidth," in layout_js
    assert "laneLeft," in layout_js
    assert (
        "const desiredCardColLeft = Math.max(12, _positionReviewRail(rawCardColLeft, host));"
        in layout_js
    )
    assert (
        "const maxVisibleCardColLeft = Math.round(viewportRight2 - cardColWidth - 12);"
        in layout_js
    )
    assert "minCardColFromText," in layout_js
    assert "Math.min(desiredCardColLeft, maxVisibleCardColLeft)" in layout_js
    assert "shell.style.width = Math.max(0, viewportWidth) + 'px';" in layout_js
    assert "shell.style.overflow = 'hidden';" in layout_js
    assert (
        "function layoutScale(element: HTMLElement | null, rect: DOMRect | null): LayoutScale"
        in geometry_js
    )
    assert "const ls = layoutScale(viewport, viewportRect);" in geometry_js
    assert (
        "textColRight = toContentX(pageRect.right) - Math.round(pagePaddingRight * (zoom.x || 1));"
        in geometry_js
    )
    assert "viewportRight: Math.round(scrollLeft + viewportWidth)" in geometry_js
    assert "function _resolveReviewPageBoundsForScreenY" in layout_js
    assert "function _collectReviewVisualPageBounds" in layout_js
    assert "pageRoot.querySelectorAll('.koto-page-break')" in layout_js
    assert (
        "upperBottom: _screenYToReviewContentY(endRect.bottom, layoutState)"
        in layout_js
    )
    assert "nextTop: _screenYToReviewContentY(startRect.top, layoutState)" in layout_js
    assert "pageTop: pageBounds ? pageBounds.top : null" in layout_js
    assert "pageBottom: pageBounds ? pageBounds.bottom : null" in layout_js
    assert (
        "function _reviewAnchorHeight(anchorGeometry: AnchorGeometry | null): number"
        in layout_js
    )
    assert (
        "function _clampReviewConnectorOffsetY(anchorGeometry: AnchorGeometry | null, cardHeight: number): number"
        in layout_js
    )
    assert (
        "function _reviewLayoutEntryBottom(entry: LayoutEntry | null): number"
        in layout_js
    )
    assert "entry.collisionHeight || 0" in layout_js
    assert "function _resolveNonOverlappingCardTop(" in layout_js
    assert "const effectiveCardHeight = Math.max(" in layout_js
    assert "let resolvedByCollision = false;" in layout_js
    assert "resolvedByCollision = true;" in layout_js
    assert (
        "const driftMaxTop = Number.isFinite(maxAnchorDrift) && Number.isFinite(desiredTop)"
        in layout_js
    )
    assert (
        "const measuredCards: MeasuredCard[] = cards.map((card, index) =>" in layout_js
    )
    assert (
        "(card as HTMLElement).style.removeProperty('--wa-review-card-anchor-min-height');"
        in layout_js
    )
    assert "const anchorHeight = _reviewAnchorHeight(anchorGeometry);" in layout_js
    assert (
        "(card as HTMLElement).style.setProperty('--wa-review-card-anchor-min-height'"
        in layout_js
    )
    assert (
        "const cardCollisionHeight = Math.max(cardHeight, anchorHeight);" in layout_js
    )
    assert "Math.round(anchorGeometry.top - 2)" in layout_js
    assert "}).sort((a, b) =>" in layout_js
    assert "const peerEntries = item.pageBounds" in layout_js
    assert "entry.pageTop === item.pageBounds!.minTop" in layout_js
    assert "item.cardCollisionHeight," in layout_js
    assert "collisionHeight: item.cardCollisionHeight" in layout_js
    assert (
        "Math.max(...layoutEntries.map((entry) => _reviewLayoutEntryBottom(entry))) + 24"
        in layout_js
    )
    assert "card.classList.add('is-page-bounded');" in layout_js
    assert (
        "(card as HTMLElement).style.setProperty('--wa-review-card-page-max-height'"
        in layout_js
    )
    assert "min-height: var(--wa-review-card-anchor-min-height, 54px);" in css
    assert "min-height: var(--wa-review-card-anchor-min-height, 72px);" in css
    assert "scheduleReviewShellLayout" in js
    assert (
        "if (layout && typeof layout.layoutReviewShellInDocx === 'function') layout.layoutReviewShellInDocx();"
        in js
    )
    assert "let reviewShellLayoutFrame = 0;" in layout_js
    assert "if (reviewShellLayoutFrame) return;" in layout_js
    assert "reviewShellLayoutFrame = requestAnimationFrame(() => {" in layout_js
    assert "reviewShellLayoutFrame = 0;" in layout_js
    assert "function ensureReviewSelectionLauncher()" in layout_js
    assert "const selectionRight = Number.isFinite(cursorRight)" in layout_js
    assert (
        "const launcherLeft = Math.min(selectionRight, maxLauncherLeft);" in layout_js
    )
    assert "function _handleReviewShellClick(event: Event): void" in js
    assert "document.addEventListener('click', (event) =>" in js
    assert (
        "if (!tab || !reviewState || !Array.isArray(reviewState.proposals)) return;"
        in js
    )
    assert (
        "tab.serverData = tab.serverData && typeof tab.serverData === 'object' ? tab.serverData : {};"
        in js
    )
    assert "(window as any).WA.openReviewCenter" not in js
    assert "export function toggleReviewCommentMode" in js
    assert "export const createReviewComment = _createReviewComment;" in js
    assert "export const createReviewRevision = _createReviewRevision;" in js
    assert "export const captureReviewSelection = _captureReviewSelection;" in js
    assert "export function openRevisionReviewCenter" in js
    assert 'data-review-toolbar-action="comment"' in js
    assert 'data-review-toolbar-action="revision"' in js
    assert 'data-review-toolbar-action="summary"' in js
    assert "const navItem = target?.closest('.wa-docx-review-nav-item')" in js
    assert "const actionEl = target?.closest('[data-review-action]')" in js
    assert "action === 'edit'" in js
    assert "action === 'delete'" in js
    assert "action === 'save'" in js
    assert "export async function focusReviewThread" in js
    assert "export const applyStructuredDocToolCall" in js
    assert "export const applyStructuredReviewChangePayload" in js
    assert "function _isReviewEditorFocused" in js
    assert "let minLeft = Infinity, maxRight = -Infinity;" in js
    assert "right: maxRight !== -Infinity ? maxRight : centerX," in js
    assert "state._editingReviewCommentId" in layout_js
    assert (
        "if (!shell || !host || !viewport || !listEl || shell.style.display === 'none')"
        in layout_js
    )
    assert "|| !_isReviewCommentModeEnabled()" in layout_js
    assert "captureReviewSelection();" in js
    assert "(window as any)._syncReviewSelectionSnapshot" not in js
    assert "function _getReviewCommentSelectionState(): any" in js
    assert "_getReviewCommentSelectionState()" in layout_js
    assert "_coerceReviewModeForVisibleContent(reviewState, 'comment')" in js
    assert "_coerceReviewModeForVisibleContent(reviewState, 'proposal')" in js
    assert "const shell = $('wa-review-shell');" in js
    assert (
        "return source === 'docx_revision' && ['replace', 'delete', 'insert'].includes(actionType);"
        in js
    )
    assert "data-review-id" in js
    assert "_syncReviewStateForActiveFile().catch" in js
    assert "export function onDocxCommentsChanged" in js
    assert "wa-review-anchor-inline" in js
    assert "launcher.id = 'wa-review-selection-launcher';" in layout_js
    assert 'data-review-create="comment"' in layout_js
    assert 'data-review-create="revision"' in layout_js
    assert "#wa-review-selection-launcher {" in css
    assert "#wa-review-selection-launcher.is-visible" in css
    assert 'data-review-nav-id="' in js
    assert "_reviewActionButton('edit', '编辑批注'" in js
    assert "_reviewActionButton('delete', '删除批注'" in js
    assert "_reviewActionButton('save', '保存批注'" in js
    assert "item?.anchor_text || item?.original_text || item?.text" in js
    assert "koto-docx-comment-edit" in js
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
    assert "wa-review-btn-icon" in css
    assert "const hasEntries = entries.length > 0;" in js
    assert "list.replaceChildren();" in js
    assert "state._reviewCenterOpen === false || !hasEntries" in js
    assert "选中文档正文后添加批注，或让 Koto 生成修订建议。" not in js


def test_workspace_review_css_keeps_native_comment_surfaces():
    css = _read("web/static/css/workspace.css")

    assert ".koto-comment-anchor" in css
    assert ".koto-docx-comment-layer" in css
    assert ".koto-docx-comment-card" in css
    assert ".koto-docx-comment-edit" in css
    assert ".koto-docx-comment-head-end" in css
    assert ".koto-docx-comment-inline-action" in css
    assert '[data-comment-ui="wps"] .koto-docx-comment-card' in css
    assert '[data-comment-ui="wps"] .koto-docx-comment-badge' in css
    assert "--wa-review-rail-gap" in css
    assert "--wa-review-rail-width: clamp(220px, 22vw, 300px);" in css
    assert ".wa-review-anchor-highlight-layer" in css
    assert ".wa-review-anchor-highlight-rect" in css
    assert "--wa-review-rail-left-shift: 0px;" in css
    assert "--wa-review-rail-right-shift: 0px;" in css
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
    assert ".wa-docx-review-nav-search" in css
    assert ".wa-docx-review-nav-search-input" in css
    assert ".wa-docx-review-nav-clear" in css
    assert ".is-page-bounded" in css
    assert "--wa-review-card-page-max-height" in css
    assert "overflow: auto !important;" in css
    assert (
        "overflow: visible; /* keep review nav menu dropdown from being clipped */"
        in css
    )
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
    assert (
        "const _reviewLauncher = wrap.querySelector('#wa-review-selection-launcher');"
        in editor_js
    )
    assert "if (_reviewShell) wrap.appendChild(_reviewShell);" in editor_js
    assert "if (_reviewLauncher) wrap.appendChild(_reviewLauncher);" in editor_js
    assert "window.WA.relayoutDocxReviewRail" in editor_js
    assert "applyImportedReviewDecision(proposal, decision = 'accept')" in editor_js
    assert "this._renderReviewProposalAnchors();" in editor_js
    assert "DocxTrackChange" in editor_js
    assert "DocxTrackChangePart" in editor_js
    assert "export const DocxTrackChange = Mark.create" in ext_js
    assert "export const DocxTrackChangePart = Mark.create" in ext_js
