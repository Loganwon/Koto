/**
 * DOCX review runtime for the unified workspace.
 * Comment/revision entry points for the workspace bundle.
 */

import { $, _PENCIL_SVG, _PIN_SVG, _TRASH_SVG, _escHtml, showToast } from './infrastructure';
import { _switchToTab, state } from './state';
import { getWorkspaceApi } from '../shared/workspace-api';

type ReviewItem = Record<string, any>;
type DocxReviewEngineModule = {
  createDocxReviewLayout: (_deps: Record<string, any>) => any;
  createReviewState: (_deps: Record<string, any>) => any;
};

let reviewLayoutRuntime: any = null;
let reviewEngineModule: DocxReviewEngineModule | null = null;
let reviewStateRuntime: any = null;
// The review module intentionally consumes only a narrow structural subset of
// WorkspaceState; keep that adapter at this boundary instead of widening both
// state models to each other's internal fields.
export function installDocxReviewEngine(engine: DocxReviewEngineModule): void {
  if (
    !engine
    || typeof engine.createReviewState !== 'function'
    || typeof engine.createDocxReviewLayout !== 'function'
  ) {
    throw new Error('Invalid DOCX review engine module');
  }
  if (reviewEngineModule === engine && reviewStateRuntime) return;
  reviewEngineModule = engine;
  reviewStateRuntime = engine.createReviewState({ state: state as any });
  reviewLayoutRuntime = null;
}

function _clean(value: any): string {
  return String(value == null ? '' : value).trim();
}

function _activeReviewTab(): any {
  return reviewStateRuntime?.activeReviewTab?.() || null;
}

function _ensureTabReviewState(tab: any = _activeReviewTab()): any {
  return reviewStateRuntime?.ensureTabReviewState?.(tab) || null;
}

function _clone(value: any, fallback: any = null): any {
  try { return JSON.parse(JSON.stringify(value)); } catch (_) { return fallback; }
}

function _normalizeReviewComment(comment: any, index = 0): any {
  return reviewStateRuntime?.normalizeReviewComment?.(comment, index) || comment || {};
}

function _normalizeReviewProposal(proposal: any, index = 0): any {
  return reviewStateRuntime?.normalizeReviewProposal?.(proposal, index) || proposal || {};
}

function _mergeReviewProposals(existing: any[], incoming: any[]): any[] {
  return reviewStateRuntime?.mergeReviewProposals?.(existing, incoming)
    || [...(Array.isArray(existing) ? existing : []), ...(Array.isArray(incoming) ? incoming : [])];
}

function _syncReviewProposalServerData(tab: any, reviewState: any): void {
  if (!tab || !reviewState || !Array.isArray(reviewState.proposals)) return;
  tab.serverData = tab.serverData && typeof tab.serverData === 'object' ? tab.serverData : {};
  tab.serverData.proposals = reviewState.proposals.map((proposal: any) => _clone(proposal, {}) || {});
}

function _syncDocCommentServerData(tab: any, reviewState: any): void {
  if (!tab || !reviewState || !Array.isArray(reviewState.comments)) return;
  tab.serverData = tab.serverData && typeof tab.serverData === 'object' ? tab.serverData : {};
  tab.serverData.comments = reviewState.comments.map((comment: any) => {
    const out = _clone(comment, {}) || {};
    delete out.review_id;
    return out;
  });
}

function _visibleProposals(reviewState: any): ReviewItem[] {
  if (reviewStateRuntime?.visibleReviewProposals) {
    return reviewStateRuntime.visibleReviewProposals(reviewState);
  }
  return Array.isArray(reviewState?.proposals) ? reviewState.proposals : [];
}

function _allReviewEntries(tab: any = _activeReviewTab()): Array<{ id: string; item: ReviewItem; kind: 'comment' | 'proposal'; tab: any }> {
  const reviewState = _ensureTabReviewState(tab);
  const comments = Array.isArray(reviewState?.comments) ? reviewState.comments : [];
  const proposals = _visibleProposals(reviewState);
  return [
    ...comments.map((item: ReviewItem) => ({ id: _clean(item.review_id || item.id), item, kind: 'comment' as const, tab })),
    ...proposals.map((item: ReviewItem) => ({ id: _clean(item.review_id || item.id), item, kind: 'proposal' as const, tab })),
  ].filter((entry) => entry.id);
}

function _findReviewEntry(reviewId: string): { id: string; item: ReviewItem; kind: string; tab?: any } | null {
  const raw = _clean(reviewId);
  const normalized = raw.replace(/^(comment|proposal):/, '');
  const tabs = Array.isArray(state.openTabs) ? state.openTabs : [];
  for (const tab of tabs) {
    const found = _allReviewEntries(tab).find((entry) => entry.id === raw || entry.id.replace(/^(comment|proposal):/, '') === normalized);
    if (found) return found;
  }
  return _allReviewEntries().find((entry) => entry.id === raw || entry.id.replace(/^(comment|proposal):/, '') === normalized) || null;
}

function _previewReviewText(text: string, maxLength = 84): string {
  const value = _clean(text).replace(/\s+/g, ' ');
  return value.length > maxLength ? `${value.slice(0, Math.max(0, maxLength - 1))}…` : value;
}

const _CHECK_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 4 4 10-10"/></svg>';

function _reviewActionButton(action: string, label: string, icon: string, extraClass = ''): string {
  const classes = `koto-docx-comment-inline-action${extraClass ? ' ' + extraClass : ''}`;
  return `<button type="button" class="${classes}" data-review-action="${_escHtml(action)}" title="${_escHtml(label)}" aria-label="${_escHtml(label)}">${icon}</button>`;
}

function _reviewTimeLabel(value: any): string {
  const raw = _clean(value);
  if (!raw) return '';
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  const now = new Date();
  const sameDay = date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate();
  const pad = (part: number) => String(part).padStart(2, '0');
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  if (sameDay) return time;
  return `${date.getMonth() + 1}/${date.getDate()} ${time}`;
}

function _findTextInDocxRoot(text: string): HTMLElement | null {
  const needle = _clean(text);
  const root = document.querySelector('#wa-docx-editor .ProseMirror');
  if (!needle || !root) return null;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      return _clean(node.textContent) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
    },
  });
  let node: Node | null = null;
  while ((node = walker.nextNode())) {
    if (String(node.textContent || '').includes(needle)) return (node.parentElement || null) as HTMLElement | null;
  }
  return null;
}

function _findDocxReviewAnchorElement(item: ReviewItem): HTMLElement | null {
  return _findTextInDocxRoot(item?.anchor_text || item?.original_text || item?.text || '');
}

function _setDocxReviewRailWidth(host: HTMLElement, width: number): void {
  if (!host) return;
  host.style.setProperty('--wa-review-rail-width', `${Math.max(132, Math.round(width || 0))}px`);
}

function _getSelectionViewportBounds(): DOMRect | null {
  const selection = window.getSelection();
  if (!selection || !selection.rangeCount) return null;
  const rects = Array.from(selection.getRangeAt(0).getClientRects()).filter((rect) => rect.width || rect.height);
  return rects[rects.length - 1] || selection.getRangeAt(0).getBoundingClientRect();
}

function _isReviewEditorFocused(): boolean {
  const active = document.activeElement as HTMLElement | null;
  return !!active && !!active.closest('#wa-review-shell');
}

function _isReviewCommentModeEnabled(): boolean {
  return state.fileType === 'docx' && state._reviewCenterOpen !== false && state._reviewMode === 'comments';
}

function _getReviewCommentSelectionState(): any {
  const snapshot = state._reviewSelectionSnapshot || null;
  const selection = window.getSelection();
  if (snapshot && _clean(snapshot.rawText || snapshot.text)) {
    return { ...snapshot, supported: true, selection };
  }
  const rawText = selection ? _clean(selection.toString()) : '';
  if (!rawText) return { valid: false, supported: false, selection: null, message: '请先选中文档正文' };
  return {
    valid: true,
    supported: true,
    selection,
    rawText,
    previewText: _previewReviewText(rawText, 80),
  };
}

function _getReviewLayout(): any {
  if (reviewLayoutRuntime) return reviewLayoutRuntime;
  if (!reviewEngineModule) return null;
  reviewLayoutRuntime = reviewEngineModule.createDocxReviewLayout({
    state: state as any,
    $,
    _findReviewEntry,
    _findDocxReviewAnchorElement,
    _setDocxReviewRailWidth,
    _getReviewCommentSelectionState,
    _isReviewCommentModeEnabled,
    _isReviewEditorFocused,
    _getSelectionViewportBounds,
    _previewReviewText,
    captureReviewSelection: _captureReviewSelection,
    createReviewComment: _createReviewComment,
    createReviewRevision: _createReviewRevision,
  });
  return reviewLayoutRuntime;
}

function _ensureReviewShellHost(): HTMLElement | null {
  const layout = _getReviewLayout();
  if (layout && typeof layout.ensureReviewShellHost === 'function') return layout.ensureReviewShellHost();
  return $('wa-review-shell');
}

function _scheduleReviewLayout(): void {
  const layout = _getReviewLayout();
  if (layout && typeof layout.ensureReviewShellViewportSync === 'function') layout.ensureReviewShellViewportSync();
  if (layout && typeof layout.layoutReviewShellInDocx === 'function') layout.layoutReviewShellInDocx();
  if (layout && typeof layout.scheduleReviewShellLayout === 'function') layout.scheduleReviewShellLayout();
  if (layout && typeof layout.renderReviewSelectionLauncher === 'function') layout.renderReviewSelectionLauncher();
}

function _setStoredReviewMode(mode: string): void {
  const normalized = ['all', 'comments', 'proposals'].includes(mode) ? mode : 'all';
  state._reviewMode = normalized;
  try { localStorage.setItem('wa_review_mode', normalized); } catch (_) { /* allowed to fail */ }
}

function _syncReviewModeButtons(): void {
  document.querySelectorAll<HTMLElement>('.wa-review-mode-btn[data-mode]').forEach((button) => {
    button.classList.toggle('is-active', button.dataset.mode === state._reviewMode);
  });
}

function _setReviewCenterOpen(open: boolean): void {
  state._reviewCenterOpen = !!open;
  try { localStorage.setItem('wa_review_center_open', open ? '1' : '0'); } catch (_) { /* allowed to fail */ }
}

function _reviewCounts(reviewState = _ensureTabReviewState()): { comments: number; proposals: number; total: number } {
  const comments = Array.isArray(reviewState?.comments) ? reviewState.comments.length : 0;
  const proposals = _visibleProposals(reviewState).length;
  return { comments, proposals, total: comments + proposals };
}

function _summaryText(reviewState = _ensureTabReviewState()): string {
  const counts = _reviewCounts(reviewState);
  if (!counts.total) return '无批注或建议';
  const parts = [];
  if (counts.comments) parts.push(`${counts.comments}条批注`);
  if (counts.proposals) parts.push(`${counts.proposals}条修订`);
  return parts.join(' / ');
}

function _syncDocxReviewToolbar(): void {
  if (state.fileType !== 'docx') return;
  const ribbon = document.querySelector('#wa-docx-editor .koto-tt-toolbar') as HTMLElement | null;
  if (!ribbon) return;
  let group = ribbon.querySelector('.wa-docx-review-group') as HTMLElement | null;
  if (!group) {
    group = document.createElement('span');
    group.className = 'wa-docx-review-group';
    group.innerHTML = ''
      + '<button type="button" class="tt-btn wa-docx-review-mode wa-docx-review-comment-mode" data-review-toolbar-action="comment" title="开启批注模式后，选中文本会出现批注入口">批注</button>'
      + '<button type="button" class="tt-btn wa-docx-review-revision-mode" data-review-toolbar-action="revision" title="选中文本后可添加修订">修订</button>'
      + '<div class="wa-docx-review-nav">'
      + '  <button type="button" class="tt-btn wa-docx-review-summary" data-review-toolbar-action="summary" aria-haspopup="menu" aria-expanded="false">无批注或建议</button>'
      + '  <div class="wa-docx-review-nav-menu" role="menu"></div>'
      + '</div>';
    ribbon.appendChild(group);
  }

  const reviewState = _ensureTabReviewState();
  const counts = _reviewCounts(reviewState);
  const commentBtn = group.querySelector('.wa-docx-review-comment-mode') as HTMLButtonElement | null;
  const revisionBtn = group.querySelector('.wa-docx-review-revision-mode') as HTMLButtonElement | null;
  const summaryBtn = group.querySelector('.wa-docx-review-summary') as HTMLButtonElement | null;
  if (commentBtn) {
    const active = state._reviewCenterOpen !== false && state._reviewMode === 'comments';
    commentBtn.classList.toggle('is-active', active);
    commentBtn.setAttribute('aria-pressed', active ? 'true' : 'false');
  }
  if (revisionBtn) {
    const active = state._reviewCenterOpen !== false && state._reviewMode === 'proposals';
    revisionBtn.classList.toggle('is-active', active);
    revisionBtn.setAttribute('aria-pressed', active ? 'true' : 'false');
  }
  if (summaryBtn) {
    summaryBtn.textContent = _summaryText(reviewState);
    summaryBtn.disabled = counts.total === 0;
  }
}

function _cardHtml(entry: { id: string; item: ReviewItem; kind: string }, index: number): string {
  const item = entry.item;
  const isEditing = state._editingReviewCommentId === entry.id;
  const body = _clean(item.text || item.rationale || item.comment || item.proposed_text);
  const anchor = _clean(item.anchor_text || item.original_text || body);
  const title = anchor ? `定位：${anchor}` : '定位批注';
  const badge = entry.kind === 'proposal' ? '修订' : '批注';
  const authorRaw = _clean(item.author || item.user || item.initials) || (entry.kind === 'proposal' ? 'Koto AI' : '批注');
  const author = authorRaw.toUpperCase() === 'AI' ? 'Koto AI' : authorRaw;
  const timeLabel = _reviewTimeLabel(item.date || item.created_at || item.createdAt || item.time);
  const anchorPreview = anchor
    ? `<button type="button" class="wa-review-anchor-inline" data-review-action="focus" title="${_escHtml(title)}"><span>原文</span>${_escHtml(_previewReviewText(anchor, 72))}</button>`
    : '';
  const headActions = isEditing
    ? _reviewActionButton('save', '保存批注', _CHECK_SVG) + _reviewActionButton('delete', '删除批注', _TRASH_SVG, 'danger')
    : _reviewActionButton('focus', '定位原文', _PIN_SVG) + _reviewActionButton('edit', '编辑批注', _PENCIL_SVG) + _reviewActionButton('delete', '删除批注', _TRASH_SVG, 'danger');
  return `
    <article class="koto-docx-comment-card${entry.id === _ensureTabReviewState()?.focusedId ? ' is-focused' : ''}${entry.kind === 'proposal' ? ' is-proposal' : ''}" data-review-id="${_escHtml(entry.id)}" tabindex="0">
      <div class="koto-docx-comment-head">
        <div class="koto-docx-comment-title-group">
        <span class="wa-proposal-badge">${badge}</span>
          <span class="koto-docx-comment-author">${_escHtml(author)}</span>
          ${timeLabel ? `<span class="koto-docx-comment-meta">${_escHtml(timeLabel)}</span>` : ''}
        </div>
        <div class="koto-docx-comment-head-end">${headActions}</div>
      </div>
      ${isEditing
        ? `<textarea class="koto-docx-comment-edit">${_escHtml(body)}</textarea>${anchorPreview}`
        : `<div class="koto-docx-comment-body" title="${_escHtml(body || '新批注')}">${_escHtml(body || '新批注')}</div>
           ${anchorPreview}`}
    </article>`;
}

function _renderReviewNavMenu(): void {
  const nav = document.querySelector('#wa-docx-editor .wa-docx-review-nav') as HTMLElement | null;
  const menu = nav?.querySelector('.wa-docx-review-nav-menu') as HTMLElement | null;
  const summary = nav?.querySelector('.wa-docx-review-summary') as HTMLButtonElement | null;
  if (!nav || !menu || !summary) return;
  const open = summary.getAttribute('aria-expanded') === 'true';
  menu.innerHTML = open
    ? _allReviewEntries().map((entry) => `<button type="button" class="wa-docx-review-nav-item" data-review-nav-id="${_escHtml(entry.id)}">${_escHtml(_previewReviewText(entry.item.anchor_text || entry.item.text || entry.id, 40))}</button>`).join('')
    : '';
  nav.classList.toggle('is-open', open);
}

function _renderReviewShell(): void {
  if (state.fileType !== 'docx') return;
  const shell = _ensureReviewShellHost();
  if (!shell) return;
  const list = shell.querySelector('#wa-review-list') as HTMLElement | null;
  const entries = _allReviewEntries();
  const hasEntries = entries.length > 0;
  if (list) {
    if (hasEntries) {
      list.innerHTML = entries.map(_cardHtml).join('');
    } else {
      // The DOCX shell is an absolutely positioned review rail. Rendering its
      // empty-state copy as a comment card makes the layout engine treat the
      // helper text as an anchored review and float it over the document.
      list.replaceChildren();
    }
  }
  shell.style.display = state._reviewCenterOpen === false || !hasEntries ? 'none' : 'flex';
  _syncDocxReviewToolbar();
  _scheduleReviewLayout();
}

function _syncReviewStateForActiveFile(): Promise<any> {
  if (state.fileType !== 'docx') {
    const shell = $('wa-review-shell');
    if (shell) shell.style.display = 'none';
    return Promise.resolve(null);
  }
  const tab = _activeReviewTab();
  const reviewState = _ensureTabReviewState(tab);
  _syncDocxReviewToolbar();
  if (state._reviewCenterOpen !== false && _reviewCounts(reviewState).total) _renderReviewShell();
  _scheduleReviewLayout();
  return Promise.resolve(reviewState);
}

function _syncDocCommentStateForActiveFile(nextComments?: any[], targetTab: any = _activeReviewTab()): any[] {
  const activeTab = _activeReviewTab();
  const runtime = reviewStateRuntime;
  if (targetTab && targetTab === activeTab && runtime && typeof runtime.syncDocCommentStateForActiveFile === 'function') {
    const comments = runtime.syncDocCommentStateForActiveFile(nextComments);
    const reviewState = _ensureTabReviewState(targetTab);
    if (reviewState) _syncDocCommentServerData(targetTab, reviewState);
    return Array.isArray(comments) ? comments : [];
  }
  const reviewState = _ensureTabReviewState(targetTab);
  if (!targetTab || !reviewState) return [];
  if (Array.isArray(nextComments)) {
    reviewState.comments = nextComments.map(_normalizeReviewComment);
  } else if (targetTab.serverData && Array.isArray(targetTab.serverData.comments)) {
    reviewState.comments = targetTab.serverData.comments.map(_normalizeReviewComment);
  }
  _syncDocCommentServerData(targetTab, reviewState);
  return reviewState.comments || [];
}

function _normalizeWorkspaceFilePath(path: any): string {
  const rawPath = _clean(path);
  if (!rawPath) return '';
  const normalizedPath = rawPath.replace(/\\/g, '/');
  const workspacePath = _clean(state._workspacePath).replace(/\\/g, '/');
  const looksAbsolute = /^(?:[a-zA-Z]:\/|\/|\/\/)/.test(normalizedPath);
  if (workspacePath && looksAbsolute && (normalizedPath === workspacePath || normalizedPath.startsWith(workspacePath + '/'))) {
    return normalizedPath.slice(workspacePath.length).replace(/^\//, '');
  }
  if (looksAbsolute) {
    const marker = '/workspace/';
    const markerIndex = normalizedPath.toLowerCase().lastIndexOf(marker);
    if (markerIndex >= 0) return normalizedPath.slice(markerIndex + marker.length).replace(/^\//, '');
  }
  return normalizedPath.replace(/^\//, '').replace(/^workspace\//i, '');
}

function _reviewPathsMatch(lhs: any, rhs: any): boolean {
  const left = _normalizeWorkspaceFilePath(lhs).toLowerCase();
  const right = _normalizeWorkspaceFilePath(rhs).toLowerCase();
  if (!left || !right) return false;
  return left === right || left.endsWith('/' + right) || right.endsWith('/' + left);
}

function _resolveStructuredReviewTargetTab(payload: any): any {
  const activeTab = _activeReviewTab();
  if (!activeTab || activeTab.fileType !== 'docx') return null;
  const args = payload?.tool_args && typeof payload.tool_args === 'object'
    ? payload.tool_args
    : (payload?.args && typeof payload.args === 'object' ? payload.args : {});
  const payloadPath = _normalizeWorkspaceFilePath(payload?.path || payload?.file_path || payload?.source_path || args.path || '');
  if (!payloadPath) return activeTab;
  return (
    _reviewPathsMatch(payloadPath, activeTab.path)
    || _reviewPathsMatch(payloadPath, state.filePath)
    || _reviewPathsMatch(payloadPath, state.wsSourcePath)
  ) ? activeTab : null;
}

function _activeDocxPlainText(): string {
  const doc = (state.activeEditor as any)?.editor?.state?.doc;
  if (doc && typeof doc.textBetween === 'function') {
    try { return _clean(doc.textBetween(0, doc.content.size, '\n', '\n')).replace(/\u00a0/g, ' '); } catch (e) { console.warn("[Koto]", e) }
  }
  const root = document.querySelector('#wa-docx-editor .ProseMirror');
  return _clean(root?.textContent || '').replace(/\u00a0/g, ' ');
}

function _coerceStructuredReviewItems(raw: any): any[] {
  if (Array.isArray(raw)) return raw;
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (_) {
      return [];
    }
  }
  return [];
}

function _sliceStructuredReviewAnchor(fullText: string, start: any, end: any): string {
  const source = String(fullText || '');
  if (!source) return '';
  const safeStart = Math.max(0, Math.min(source.length, Math.round(Number(start) || 0)));
  const safeEnd = Math.max(safeStart, Math.min(source.length, Math.round(Number(end) || 0)));
  const slice = safeEnd > safeStart
    ? source.slice(safeStart, safeEnd)
    : source.slice(safeStart, Math.min(source.length, safeStart + 48));
  return _clean(slice).replace(/\u00a0/g, ' ');
}

function _collectStructuredReviewItems(payload: any): any[] {
  const root = payload && typeof payload === 'object' ? payload : {};
  const args = root.tool_args && typeof root.tool_args === 'object'
    ? root.tool_args
    : (root.args && typeof root.args === 'object' ? root.args : {});
  const fromComments = _coerceStructuredReviewItems(root.comments || args.comments);
  if (fromComments.length) return fromComments;
  const fromAnnotations = _coerceStructuredReviewItems(root.annotations || args.annotations);
  if (fromAnnotations.length) return fromAnnotations;
  if (Array.isArray(root.changes)) return root.changes;
  const kind = _clean(root.tool_name || root.name || root.type).toLowerCase();
  if (['comment', 'review_comment', 'add_comment', 'create_comment', 'annotate', 'annotation', 'annotate_file'].includes(kind)) {
    return [{ ...args, ...root }];
  }
  return [];
}

function _buildStructuredReviewComment(item: any, index: number, options: { author?: string; fullText?: string; fallbackSelection?: any } = {}): any | null {
  const raw = item && typeof item === 'object' ? item : {};
  const range = Array.isArray(raw.range) ? raw.range : [];
  const rangeStart = Number.isFinite(Number(raw.range_start))
    ? Number(raw.range_start)
    : (range.length > 0 && Number.isFinite(Number(range[0])) ? Number(range[0]) : Number.NaN);
  const rangeEnd = Number.isFinite(Number(raw.range_end))
    ? Number(raw.range_end)
    : (range.length > 1 && Number.isFinite(Number(range[1])) ? Number(range[1]) : Number.NaN);
  const text = _clean(raw.comment || raw.text || raw.modified || raw.note || raw.message || raw.value || raw.rationale);
  if (!text) return null;
  let anchorText = _clean(raw.anchor_text || raw.original_text || raw.original || raw.selection || raw.quoted_text || raw.target_text);
  if (!anchorText && Number.isFinite(rangeStart) && Number.isFinite(rangeEnd)) {
    anchorText = _sliceStructuredReviewAnchor(options.fullText || '', rangeStart, rangeEnd);
  }
  if (!anchorText && options.fallbackSelection && index === 0) anchorText = _clean(options.fallbackSelection.rawText || options.fallbackSelection.text);
  if (!anchorText) return null;
  const comment = {
    id: `ai-${Date.now().toString(36)}-${index}-${Math.random().toString(36).slice(2, 7)}`,
    author: _clean(raw.author || options.author) || 'AI',
    date: new Date().toISOString(),
    text,
    anchor_text: anchorText,
  } as any;
  const anchorStartOffset = Number.isFinite(Number(raw.anchor_start_offset ?? raw.anchorStartOffset))
    ? Number(raw.anchor_start_offset ?? raw.anchorStartOffset)
    : (Number.isFinite(rangeStart) ? rangeStart : Number.NaN);
  const anchorEndOffset = Number.isFinite(Number(raw.anchor_end_offset ?? raw.anchorEndOffset))
    ? Number(raw.anchor_end_offset ?? raw.anchorEndOffset)
    : (Number.isFinite(rangeEnd) ? rangeEnd : Number.NaN);
  const anchorOccurrence = Number(raw.anchor_occurrence ?? raw.anchorOccurrence ?? options.fallbackSelection?.anchor_occurrence ?? options.fallbackSelection?.anchorOccurrence);
  if (Number.isFinite(anchorStartOffset)) comment.anchor_start_offset = anchorStartOffset;
  if (Number.isFinite(anchorEndOffset)) comment.anchor_end_offset = anchorEndOffset;
  if (Number.isFinite(anchorOccurrence) && anchorOccurrence >= 0) comment.anchor_occurrence = Math.max(0, Math.floor(anchorOccurrence));
  const before = _clean(raw.anchor_context_before || raw.anchorContextBefore || options.fallbackSelection?.anchor_context_before || options.fallbackSelection?.anchorContextBefore);
  const after = _clean(raw.anchor_context_after || raw.anchorContextAfter || options.fallbackSelection?.anchor_context_after || options.fallbackSelection?.anchorContextAfter);
  if (before) comment.anchor_context_before = before;
  if (after) comment.anchor_context_after = after;
  return _normalizeReviewComment(comment, index);
}

function _coerceReviewModeForVisibleContent(reviewState: any, preferredKind = ''): void {
  const runtime = reviewStateRuntime;
  if (runtime && typeof runtime.coerceReviewModeForVisibleContent === 'function') {
    runtime.coerceReviewModeForVisibleContent(reviewState, preferredKind);
    return;
  }
  const comments = Array.isArray(reviewState?.comments) ? reviewState.comments.length : 0;
  const proposals = _visibleProposals(reviewState).length;
  if ((preferredKind === 'comment' || preferredKind === 'comments') && comments) _setStoredReviewMode(proposals ? 'all' : 'comments');
  else if ((preferredKind === 'proposal' || preferredKind === 'proposals') && proposals) _setStoredReviewMode(comments ? 'all' : 'proposals');
  else if (comments && proposals) _setStoredReviewMode('all');
  else if (comments) _setStoredReviewMode('comments');
  else if (proposals) _setStoredReviewMode('proposals');
}

function _scrollReviewCardIntoView(reviewId: string): void {
  const key = _clean(reviewId);
  if (!key || !(window as any).CSS?.escape) return;
  const card = document.querySelector(`.koto-docx-comment-card[data-review-id="${CSS.escape(key)}"]`) as HTMLElement | null;
  if (!card) return;
  card.classList.add('is-focused');
}

function _scrollProposalCardIntoView(proposalId: string): void {
  const key = _clean(proposalId).replace(/^proposal:/, '');
  if (!key || !(window as any).CSS?.escape) return;
  const card = document.querySelector(`.wa-proposal-card[data-proposal-id="${CSS.escape(key)}"]`) as HTMLElement | null;
  if (!card) return;
  card.classList.add('focused');
}

function _scheduleAutoSave(): void {
  const fn = getWorkspaceApi().scheduleAutoSave;
  if (typeof fn === 'function') fn();
}

function _appendStructuredReviewComments(payload: any, options: any = {}): boolean {
  const targetTab = _resolveStructuredReviewTargetTab(payload);
  if (!targetTab || targetTab.path !== state.activeTabPath || state.fileType !== 'docx') return false;
  const reviewState = _ensureTabReviewState(targetTab);
  if (!reviewState) return false;
  const items = _collectStructuredReviewItems(payload);
  if (!items.length) return false;
  const seen = new Set((reviewState.comments || []).map((item: any) => `${_clean(item.anchor_text)}\u0000${_clean(item.text)}`));
  const args = payload?.tool_args || payload?.args || {};
  const author = _clean(options.author || payload?.author || args.author) || 'AI';
  const fullText = _activeDocxPlainText();
  const fallbackSelection = state._reviewSelectionSnapshot || null;
  const additions: any[] = [];
  items.forEach((item, index) => {
    const nextComment = _buildStructuredReviewComment(item, index, { author, fullText, fallbackSelection });
    if (!nextComment) return;
    const key = `${_clean(nextComment.anchor_text)}\u0000${_clean(nextComment.text)}`;
    if (seen.has(key)) return;
    seen.add(key);
    additions.push(nextComment);
  });
  if (!additions.length) return false;
  reviewState.comments = (reviewState.comments || []).concat(additions).map(_normalizeReviewComment);
  _syncDocCommentServerData(targetTab, reviewState);
  const focusId = additions[additions.length - 1].review_id || `comment:${additions[additions.length - 1].id}`;
  reviewState.focusedId = focusId;
  _coerceReviewModeForVisibleContent(reviewState, 'comment');
  _setReviewCenterOpen(true);
  _renderReviewShell();
  requestAnimationFrame(() => {
    _scrollReviewCardIntoView(focusId);
    const layout = _getReviewLayout();
    if (layout && typeof layout.scrollReviewAnchorIntoView === 'function') layout.scrollReviewAnchorIntoView(additions[additions.length - 1]);
  });
  _scheduleAutoSave();
  if (options.notify !== false) showToast(options.toastText || `AI 已添加 ${additions.length} 条批注`, 'success');
  return true;
}

async function _applyStructuredReviewProgressPayload(payload: any, options: any = {}): Promise<boolean> {
  const proposals = Array.isArray(payload?.partial_proposals) ? payload.partial_proposals : [];
  if (!proposals.length) return false;
  const targetPath = _clean(payload?.target_path || payload?.path || payload?.file_path);
  const activeTab = _activeReviewTab();
  const activePath = _clean(activeTab?.path || activeTab?.wsSourcePath);
  if (targetPath && (!_reviewPathsMatch(targetPath, activePath))) {
    const reload = getWorkspaceApi().reloadFileByPath;
    if (typeof reload !== 'function') return false;
    try { await reload(targetPath, true); } catch (error) { console.warn('[WA review progress] target open failed:', error); }
  }
  const targetTab = _activeReviewTab();
  if (!targetTab || state.fileType !== 'docx') return false;
  const reviewState = _ensureTabReviewState(targetTab);
  if (!reviewState) return false;
  reviewState.proposals = _mergeReviewProposals(reviewState.proposals || [], proposals);
  _syncReviewProposalServerData(targetTab, reviewState);
  const latest = reviewState.proposals[reviewState.proposals.length - 1] || null;
  if (latest) {
    reviewState.focusedId = _clean(latest.review_id || `proposal:${latest.id}`);
    reviewState.expandedId = reviewState.focusedId;
  }
  _coerceReviewModeForVisibleContent(reviewState, reviewState.comments?.length ? 'all' : 'proposal');
  _setReviewCenterOpen(true);
  state._activeProposals = reviewState.proposals.slice();
  _renderReviewShell();
  if (reviewState.focusedId) requestAnimationFrame(() => {
    _scrollReviewCardIntoView(reviewState.focusedId);
    _scrollProposalCardIntoView(reviewState.focusedId);
  });
  if (options.notify !== false) showToast(options.toastText || `AI 已同步 ${proposals.length} 条修订建议`, 'success');
  return true;
}

function _captureReviewSelection(): any {
  const selection = window.getSelection();
  const rawText = selection ? _clean(selection.toString()) : '';
  if (!rawText || !selection || !selection.rangeCount) return null;
  state._reviewSelectionSnapshot = {
    valid: true,
    rawText,
    previewText: _previewReviewText(rawText, 80),
    capturedAt: Date.now(),
  };
  _scheduleReviewLayout();
  return state._reviewSelectionSnapshot;
}

function _createReviewComment(): void {
  const selection = state._reviewSelectionSnapshot || _captureReviewSelection();
  if (!selection || !_clean(selection.rawText || selection.text)) {
    showToast('请先选中文档正文', 'info');
    return;
  }
  const tab = _activeReviewTab();
  const reviewState = _ensureTabReviewState(tab);
  if (!reviewState) return;
  const id = `comment-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
  const comment = {
    id,
    review_id: id,
    author: '批注',
    text: '',
    anchor_text: _clean(selection.rawText || selection.text),
    date: new Date().toISOString(),
  };
  reviewState.comments.push(comment);
  reviewState.focusedId = id;
  state._editingReviewCommentId = id;
  _setReviewCenterOpen(true);
  _setStoredReviewMode('comments');
  _renderReviewShell();
}

function _buildReviewProposalFromSelection(selection: any): any | null {
  const rawText = _clean(selection?.rawText || selection?.text);
  if (!rawText) return null;
  const id = `user-revision-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
  const proposal: any = {
    id,
    review_id: `proposal:${id}`,
    source: 'user_revision',
    author: '我',
    date: new Date().toISOString(),
    action: 'replace',
    action_type: 'replace',
    original_text: rawText,
    anchor_text: rawText,
    proposed_text: '',
    rationale: '用户手动添加修订',
    _draft: true,
  };
  for (const [fromKey, toKey] of [
    ['anchor_start_offset', 'anchor_start_offset'],
    ['anchorStartOffset', 'anchor_start_offset'],
    ['anchor_end_offset', 'anchor_end_offset'],
    ['anchorEndOffset', 'anchor_end_offset'],
    ['anchor_occurrence', 'anchor_occurrence'],
    ['anchorOccurrence', 'anchor_occurrence'],
    ['anchor_context_before', 'anchor_context_before'],
    ['anchorContextBefore', 'anchor_context_before'],
    ['anchor_context_after', 'anchor_context_after'],
    ['anchorContextAfter', 'anchor_context_after'],
  ]) {
    if (selection && selection[fromKey] != null && _clean(selection[fromKey])) proposal[toKey] = selection[fromKey];
  }
  return _normalizeReviewProposal(proposal, 0);
}

function _createReviewRevision(): void {
  if (state.fileType !== 'docx') {
    showToast('当前仅 DOCX 文档支持修订', 'info');
    return;
  }
  const selection = state._reviewSelectionSnapshot || _captureReviewSelection();
  if (!selection || !_clean(selection.rawText || selection.text)) {
    showToast('请先选中文档正文', 'info');
    return;
  }
  const tab = _activeReviewTab();
  const reviewState = _ensureTabReviewState(tab);
  const proposal = _buildReviewProposalFromSelection(selection);
  if (!tab || !reviewState || !proposal) return;
  reviewState.proposals = _mergeReviewProposals(reviewState.proposals || [], [proposal]);
  _syncReviewProposalServerData(tab, reviewState);
  const reviewId = _clean(proposal.review_id || `proposal:${proposal.id}`);
  reviewState.focusedId = reviewId;
  reviewState.expandedId = reviewId;
  state._editingReviewCommentId = '';
  state._editingReviewProposalId = reviewId;
  _setStoredReviewMode('proposals');
  _setReviewCenterOpen(true);
  _renderReviewShell();
  requestAnimationFrame(() => {
    _scrollReviewCardIntoView(reviewId);
    _scrollProposalCardIntoView(reviewId);
  });
}

function _handleReviewShellClick(event: Event): void {
  const target = event.target as HTMLElement | null;
  const actionEl = target?.closest('[data-review-action]') as HTMLElement | null;
  const card = target?.closest('.koto-docx-comment-card') as HTMLElement | null;
  if (!actionEl && card) {
    const id = _clean(card.dataset.reviewId);
    const entry = id ? _findReviewEntry(id) : null;
    const reviewState = _ensureTabReviewState();
    if (!entry || !reviewState) return;
    reviewState.focusedId = entry.id;
    _renderReviewShell();
    requestAnimationFrame(() => {
      const layout = _getReviewLayout();
      if (layout && typeof layout.scrollReviewAnchorIntoView === 'function') layout.scrollReviewAnchorIntoView(entry.item);
    });
    return;
  }
  if (!actionEl) return;
  event.preventDefault();
  const actionCard = actionEl.closest('.koto-docx-comment-card') as HTMLElement | null;
  const id = _clean(actionCard?.dataset.reviewId);
  const entry = id ? _findReviewEntry(id) : null;
  const reviewState = _ensureTabReviewState();
  const action = _clean(actionEl.dataset.reviewAction);
  if (!entry || !reviewState) return;
  reviewState.focusedId = entry.id;
  if (action === 'focus') {
    const layout = _getReviewLayout();
    if (layout && typeof layout.scrollReviewAnchorIntoView === 'function') layout.scrollReviewAnchorIntoView(entry.item);
  } else if (action === 'edit') {
    state._editingReviewCommentId = entry.id;
  } else if (action === 'save') {
    const textarea = actionCard?.querySelector('.koto-docx-comment-edit') as HTMLTextAreaElement | null;
    if (entry.kind === 'proposal') {
      entry.item.proposed_text = _clean(textarea?.value);
      entry.item.value = entry.item.proposed_text;
      entry.item._draft = false;
      _syncReviewProposalServerData(entry.tab, reviewState);
    } else {
      entry.item.text = _clean(textarea?.value);
      _syncDocCommentServerData(entry.tab, reviewState);
    }
    state._editingReviewCommentId = '';
  } else if (action === 'delete') {
    reviewState.comments = (reviewState.comments || []).filter((item: ReviewItem) => _clean(item.review_id || item.id) !== entry.id);
    reviewState.proposals = (reviewState.proposals || []).filter((item: ReviewItem) => _clean(item.review_id || item.id) !== entry.id);
    _syncDocCommentServerData(entry.tab, reviewState);
    _syncReviewProposalServerData(entry.tab, reviewState);
    state._editingReviewCommentId = '';
  }
  _renderReviewShell();
  _scheduleAutoSave();
}

document.addEventListener('click', (event) => {
  const target = event.target as HTMLElement | null;
  const toolbarAction = target?.closest('[data-review-toolbar-action]') as HTMLElement | null;
  if (toolbarAction) {
    const action = _clean(toolbarAction.dataset.reviewToolbarAction);
    if (action === 'comment') toggleReviewCommentMode();
    if (action === 'revision') {
      _setReviewCenterOpen(true);
      _setStoredReviewMode('proposals');
      _renderReviewShell();
    }
    if (action === 'summary') {
      const button = toolbarAction as HTMLButtonElement;
      button.setAttribute('aria-expanded', button.getAttribute('aria-expanded') === 'true' ? 'false' : 'true');
      _renderReviewNavMenu();
    }
  }

  const navItem = target?.closest('.wa-docx-review-nav-item') as HTMLElement | null;
  if (navItem) {
    const id = _clean(navItem.dataset.reviewNavId);
    const reviewState = _ensureTabReviewState();
    if (reviewState) reviewState.focusedId = id;
    const summary = document.querySelector('.wa-docx-review-summary') as HTMLElement | null;
    if (summary) summary.setAttribute('aria-expanded', 'false');
    _renderReviewShell();
  }

  if (target?.closest('#wa-review-shell')) _handleReviewShellClick(event);
});

document.addEventListener('selectionchange', () => {
  if (state.fileType !== 'docx') return;
  const layout = _getReviewLayout();
  if (layout && typeof layout.renderReviewSelectionLauncher === 'function') layout.renderReviewSelectionLauncher();
});

export const ensureTabReviewState = _ensureTabReviewState;
export const syncReviewStateForActiveFile = _syncReviewStateForActiveFile;
export const syncDocCommentStateForActiveFile = _syncDocCommentStateForActiveFile;
export const syncDocxReviewToolbar = _syncDocxReviewToolbar;
export const renderReviewShell = _renderReviewShell;
export const captureReviewSelection = _captureReviewSelection;
export const createReviewComment = _createReviewComment;
export const createReviewRevision = _createReviewRevision;
export const isReviewCommentModeEnabled = _isReviewCommentModeEnabled;
export const isReviewEditorFocused = _isReviewEditorFocused;
export const isReviewShellFocused = (): boolean => !!document.activeElement?.closest?.('#wa-review-shell');
export const renderReviewSelectionLauncher = (): void => _getReviewLayout()?.renderReviewSelectionLauncher?.();
export const hideReviewSelectionLauncher = (): void => _getReviewLayout()?.hideReviewSelectionLauncher?.();
export const normalizeWorkspaceFilePath = _normalizeWorkspaceFilePath;
export const applyStructuredDocToolCall = (toolCall: any, options: any = {}): boolean => _appendStructuredReviewComments(toolCall, options);
export const applyStructuredReviewChangePayload = (payload: any, options: any = {}): boolean => {
  const operation = _clean(payload?.operation || payload?.change_type).toLowerCase();
  const annotationsAdded = Number(payload?.annotations_added || 0);
  if (!Array.isArray(payload?.changes) && operation !== 'annotate_file' && operation !== 'annotate' && !annotationsAdded) return false;
  return _appendStructuredReviewComments(payload, options);
};
export const applyStructuredReviewProgressPayload = (payload: any, options: any = {}): Promise<boolean> => _applyStructuredReviewProgressPayload(payload, options);

export function toggleReviewCommentMode(forceOpen?: boolean): void {
  if (state.fileType !== 'docx') {
    showToast('当前仅 DOCX 文档支持批注模式', 'info');
    return;
  }
  const nextOpen = typeof forceOpen === 'boolean' ? forceOpen : !(state._reviewCenterOpen !== false && state._reviewMode === 'comments');
  _setReviewCenterOpen(nextOpen);
  _setStoredReviewMode('comments');
  _renderReviewShell();
}

export function openRevisionReviewCenter(): void {
  if (state.fileType !== 'docx') {
    showToast('修订栏当前仅支持 DOCX 文档', 'info');
    return;
  }
  const tab = _activeReviewTab();
  const reviewState = _ensureTabReviewState(tab);
  if (!reviewState) return;
  if (!_visibleProposals(reviewState).length) {
    _createReviewRevision();
    return;
  }
  _coerceReviewModeForVisibleContent(reviewState, 'proposal');
  _setReviewCenterOpen(true);
  if (!reviewState.focusedId) {
    const first = _visibleProposals(reviewState)[0];
    reviewState.focusedId = _clean(first.review_id || `proposal:${first.id}`);
    reviewState.expandedId = reviewState.focusedId;
  }
  _renderReviewShell();
  requestAnimationFrame(() => {
    _scrollReviewCardIntoView(reviewState.focusedId);
    _scrollProposalCardIntoView(reviewState.focusedId);
  });
}

export async function focusReviewThread(reviewId: string): Promise<void> {
  const entry = _findReviewEntry(reviewId);
  if (!entry || !entry.item) return;
  if (entry.tab && entry.tab.path && entry.tab.path !== state.activeTabPath) {
    await _switchToTab(entry.tab.path);
  }
  const reviewState = _ensureTabReviewState(entry.tab || _activeReviewTab());
  if (!reviewState) return;
  reviewState.focusedId = _clean(entry.item.review_id || entry.item.id);
  if (entry.kind === 'proposal') reviewState.expandedId = reviewState.focusedId;
  _coerceReviewModeForVisibleContent(reviewState, entry.kind === 'proposal' ? 'proposal' : 'comment');
  _setReviewCenterOpen(true);
  _renderReviewShell();
  requestAnimationFrame(() => {
    _scrollReviewCardIntoView(reviewState.focusedId);
    if (entry.kind === 'proposal') _scrollProposalCardIntoView(reviewState.focusedId);
    const layout = _getReviewLayout();
    if (layout && typeof layout.scrollReviewAnchorIntoView === 'function') layout.scrollReviewAnchorIntoView(entry.item);
  });
}

export function onDocxCommentsChanged(comments: any[], tabPath?: string): void {
  const targetTab = tabPath
    ? (Array.isArray(state.openTabs) ? state.openTabs.find((tab: any) => tab && tab.path === tabPath) : null)
    : _activeReviewTab();
  const reviewState = _ensureTabReviewState(targetTab);
  if (!targetTab || !reviewState) return;
  _syncDocCommentStateForActiveFile(Array.isArray(comments) ? comments : [], targetTab);
  if (targetTab.path === state.activeTabPath) _syncReviewStateForActiveFile().catch(() => {});
}

export function relayoutDocxReviewRail(): void {
  _getReviewLayout()?.scheduleReviewShellLayout?.();
}
