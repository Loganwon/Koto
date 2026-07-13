/**
 * AI Conversation & Review — proposal acceptance/rejection, batch ops,
 * patched file download, AI action bar, sendMessage pipeline.
 * Workspace AI review entry points.
 */

import {
  resizeWorkspaceAiComposer,
  setWorkspaceAiComposerValue,
} from './ai-composer';
import { getWorkspaceApi, publishWorkspaceApi } from '../shared/workspace-api';

const workspaceApi = getWorkspaceApi();

declare function $(id: string): HTMLElement | null;
declare let state: any;
declare let _LIGHTBULB_SVG: string;
declare let _CLIPBOARD_SVG: string;
declare let _PIN_SVG: string;
declare let _CHAT_SVG: string;
declare let _PENCIL_SVG: string;
declare let _PAUSE_SVG: string;
declare let _SEND_SVG: string;

declare function _escHtml(s: any): string;
declare function showToast(message: string, kind?: string, duration?: number): void;
declare function _csrfFetch(url: string, init?: RequestInit): Promise<Response>;
declare function _expandWAPanel(): void;
declare function _findProposalEntry(id: string): { proposal: any; tab?: any };
declare function _switchToTab(path: string): Promise<void>;
declare function _setProposalReviewStatus(id: string, status: string): void;
declare function _syncProposalDomState(id: string, status: string): void;
declare function _syncReviewStateForActiveFile(): Promise<void>;
declare function _ensureTabReviewState(tab: any): any;
declare function _visibleReviewProposals(state: any): any[];
declare function _renderMyWorkspace(): void;
declare function _cloneSerializable(val: any, fallback: any): any;
declare function _relayoutDocxReviewRailAndScrollNode(node: HTMLElement, opts: any): void;

function _runtimeRef(name: string): any {
  return (window as any)[name] || null;
}

function _sanitizeRenderedHtml(html: string): string {
  const template = document.createElement('template');
  template.innerHTML = String(html || '');
  template.content.querySelectorAll('script, style, iframe, object, embed, link, meta, base').forEach((node) => node.remove());
  template.content.querySelectorAll('*').forEach((node) => {
    Array.from((node as Element).attributes || []).forEach((attr) => {
      const name = String(attr.name || '').toLowerCase();
      const value = String(attr.value || '').trim().toLowerCase();
      if (name.startsWith('on')) {
        (node as Element).removeAttribute(attr.name);
        return;
      }
      if ((name === 'href' || name === 'src') && value && !/^(https?:|mailto:|\/|#|data:image\/)/i.test(value)) {
        (node as Element).removeAttribute(attr.name);
      }
    });
  });
  return template.innerHTML;
}

export function _getPinnedSelectionSourceMeta(): any {
  const sourcePath = String(state.wsSourcePath || state.filePath || '').trim();
  const sourceName = String(state.fileName || (sourcePath ? sourcePath.split(/[\\/]/).pop() : '') || '').trim();
  return {
    sourcePath,
    sourceName,
    sourceType: String(state.fileType || '').trim(),
  };
}

export function _selectionContextText(selectionContext: any): string {
  if (!selectionContext) return '';
  if (typeof selectionContext === 'string') return selectionContext.trim();
  return String(selectionContext.text || '').trim();
}

export function _selectionContextSourceLabel(selectionContext: any): string {
  if (!selectionContext || typeof selectionContext === 'string') return '';
  const sourceName = String(selectionContext.sourceName || '').trim();
  if (sourceName) return sourceName;
  const sourcePath = String(selectionContext.sourcePath || '').trim();
  return sourcePath ? sourcePath.split(/[\\/]/).pop() || sourcePath : '';
}

export function _createPinnedSelectionContext(text: any, sourceMeta?: any): any {
  if (text && typeof text === 'object') {
    const normalizedText = _selectionContextText(text);
    if (!normalizedText) return null;
    const previewText = String(text.previewText || text.preview_text || '').trim();
    const sourcePath = String(text.sourcePath || text.source_path || '').trim();
    const sourceName = String(text.sourceName || text.source_name || '').trim();
    const sourceType = String(text.sourceType || text.source_type || '').trim();
    return {
      text: normalizedText,
      previewText,
      sourcePath,
      sourceName: sourceName || (sourcePath ? sourcePath.split(/[\\/]/).pop() || sourcePath : ''),
      sourceType,
    };
  }

  const normalizedText = String(text || '').trim();
  if (!normalizedText) return null;
  const meta = sourceMeta || _getPinnedSelectionSourceMeta();
  const previewText = String(meta.previewText || meta.preview_text || '').trim();
  const sourcePath = String(meta.sourcePath || meta.source_path || '').trim();
  const sourceName = String(meta.sourceName || meta.source_name || '').trim();
  return {
    text: normalizedText,
    previewText,
    sourcePath,
    sourceName: sourceName || (sourcePath ? sourcePath.split(/[\\/]/).pop() || sourcePath : ''),
    sourceType: String(meta.sourceType || meta.source_type || '').trim(),
  };
}

function _getLiveEditorSelectionForAI(): any {
  const live = workspaceApi._getLiveEditorSelectionForAI;
  if (typeof live === 'function') {
    try { return live(); } catch (_) { return null; }
  }
  return null;
}

function _saveEditorRange(): void {
  const saveRange = workspaceApi._saveEditorRange;
  if (typeof saveRange === 'function') {
    try { saveRange(); } catch (_) { /* noop */ }
  }
}

export function _setStreamBtn(streaming: boolean): void {
  const sendBtn = $('wa-send-btn') as HTMLButtonElement | null;
  if (!sendBtn) return;
  sendBtn.classList.toggle('is-streaming', !!streaming);
  sendBtn.title = streaming ? '停止当前任务' : '发送';
  sendBtn.setAttribute('aria-label', streaming ? '停止当前任务' : '发送');
  sendBtn.innerHTML = streaming ? _PAUSE_SVG : _SEND_SVG;
  sendBtn.onclick = streaming
    ? () => workspaceApi.stopStream?.()
    : () => workspaceApi.sendMessage?.();
}

export function stopStream(): boolean {
  const ctrl = state._streamAbortCtrl;
  if (ctrl && typeof ctrl.abort === 'function' && !(ctrl.signal && ctrl.signal.aborted)) {
    ctrl.abort();
    showToast('正在停止当前任务...', 'info');
    return true;
  }
  if (state.isLoading) {
    state.isLoading = false;
    state._streamAbortCtrl = null;
    _setStreamBtn(false);
    showToast('当前任务已停止', 'info');
    return true;
  }
  return false;
}

export interface ProposalData {
  id: string;
  review_id?: string;
  original_text: string;
  proposed_text: string;
  rationale?: string;
  tool_call?: any;
  action?: string;
  action_type?: string;
  source?: string;
  read_only?: boolean;
  apply_disabled?: boolean;
  _reviewStatus?: string;
  kind?: string;
  revision?: string;
}

export interface ReviewResult {
  proposalId: string;
  status: 'accepted' | 'rejected';
}

export interface SendMessageOptions {
  content?: string;
  text?: string;
  files?: Array<{ name?: string; path?: string }>;
  attachments?: Array<{ name?: string; path?: string }>;
  quoteText?: string;
  quoteSource?: string;
  task_kind?: string;
}

export interface ActionBarSnapshot {
  pinnedSel?: any;
  toolCall?: any;
  outputMode?: string;
}

export interface ArtifactResumePayload {
  taskPayload?: any;
  options?: {
    followup_context?: any;
  };
  actionLabel?: string;
  title?: string;
  taskId?: string;
  comment?: string;
  loadingEl?: HTMLElement;
}

export interface ArtifactResumeResult {
  valid: boolean;
  taskPayload?: any;
  followupContext?: any;
  isStepwise?: boolean;
  skipPersistedApi?: boolean;
  usesFeedback?: boolean;
}

// ── Proposal diff display ──
export function _computeInlineDiff(original: string, proposed: string): string {
  const stripHtml = (s: string) => s.replace(/<[^>]+>/g, '').trim();
  const origText = stripHtml(original);
  const propText = stripHtml(proposed);
  if (origText === propText) return '<span class="wa-diff-same">' + _escHtml(propText) + '</span>';

  if (origText.length < 500 && propText.length < 500) {
    return '<div class="wa-diff-block del"><span class="wa-diff-label">\u539f\u6587</span>' + _escHtml(origText) + '</div>' +
           '<div class="wa-diff-block add"><span class="wa-diff-label">\u4fee\u6539</span>' + _escHtml(propText) + '</div>';
  }

  const truncOrig = origText.length > 300 ? origText.substring(0, 300) + '\u2026' : origText;
  const truncProp = propText.length > 300 ? propText.substring(0, 300) + '\u2026' : propText;
  return '<div class="wa-diff-block del"><span class="wa-diff-label">\u539f\u6587</span>' + _escHtml(truncOrig) + '</div>' +
         '<div class="wa-diff-block add"><span class="wa-diff-label">\u4fee\u6539</span>' + _escHtml(truncProp) + '</div>';
}

export function _normalizeProposalText(text: string): string {
  return String(text || '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/^(?:\u4ee5\u4e0b|\u4e0b\u9762|\u8fd9\u662f|\u5982\u4e0b)(?:\u662f|\u4e3a)?.{0,20}(?:\u6da6\u8272|\u7ffb\u8bd1|\u6539\u5199|\u4fee\u6539|\u4fee\u6b63|\u4f18\u5316|\u7248\u672c|\u7ed3\u679c|\u6587\u672c|\u5185\u5bb9).{0,10}[\uff1a:]\s*/i, '')
    .replace(/\s+/g, '')
    .trim()
    .toLowerCase();
}

export function _getProposalRationaleText(proposal: ProposalData): string {
  const runtime = _runtimeRef('_waAiResultsRuntime');
  if (runtime && typeof runtime.getProposalRationaleText === 'function') {
    return runtime.getProposalRationaleText(proposal);
  }
  const raw = (proposal?.rationale || '').replace(/<[^>]+>/g, '').trim();
  if (!raw) return '';
  const rationaleKey = _normalizeProposalText(raw);
  const originalKey = _normalizeProposalText(proposal?.original_text || '');
  const proposedKey = _normalizeProposalText(proposal?.proposed_text || '');
  if (!rationaleKey || rationaleKey === originalKey || rationaleKey === proposedKey) return '';
  return raw;
}

export function _isImportedDocxRevisionProposal(proposal: ProposalData): boolean {
  if (!proposal) return false;
  const source = String(proposal.source || '').trim();
  const actionType = String(proposal.action || proposal.action_type || '').trim();
  return source === 'docx_revision' && ['replace', 'delete', 'insert'].includes(actionType);
}

export function _proposalCanApply(proposal: ProposalData): boolean {
  if (!proposal) return false;
  const importedDocxRevision = _isImportedDocxRevisionProposal(proposal);
  if (!importedDocxRevision && (proposal.read_only || proposal.apply_disabled)) return false;
  if (importedDocxRevision) return !!String(proposal.id || proposal.review_id || '').trim();
  const rationale = (proposal.rationale || '').replace(/<[^>]+>/g, '').trim();
  const actionType = String(proposal.action || proposal.action_type || '').trim();
  if (/\u7ffb\u8bd1/.test(rationale) || /translate/i.test(actionType)) return false;
  return !!(proposal.tool_call || (proposal.original_text && proposal.proposed_text));
}

export function _makeProposalCard(proposal: ProposalData, index: number, total: number): HTMLElement {
  const card = document.createElement('div');
  card.className = 'wa-proposal-card';
  card.dataset.proposalId = proposal.id;
  card.dataset.index = String(index);
  const canApply = _proposalCanApply(proposal);
  card.dataset.canApply = canApply ? '1' : '0';

  const header = document.createElement('div');
  header.className = 'wa-proposal-header';
  header.innerHTML = `<span class="wa-proposal-badge">\u4fee\u6539\u5efa\u8bae ${index + 1}${total > 1 ? '/' + total : ''}</span>`;

  const diffView = document.createElement('div');
  diffView.className = 'wa-proposal-diff';
  diffView.innerHTML = _computeInlineDiff(proposal.original_text, proposal.proposed_text);

  const rationale = document.createElement('div');
  rationale.className = 'wa-proposal-rationale';
  const rText = _getProposalRationaleText(proposal);
  if (rText && rText.length > 5) {
    rationale.innerHTML = `${_LIGHTBULB_SVG} ` + _escHtml(rText.length > 150 ? rText.substring(0, 150) + '\u2026' : rText);
  }

  const actions = document.createElement('div');
  actions.className = 'wa-proposal-actions';
  actions.innerHTML = canApply
    ? `<button type="button" class="wa-proposal-btn accept" data-wa-review-action="accept" data-proposal-id="${_escHtml(proposal.id)}">\u63a5\u53d7</button>` +
      `<button type="button" class="wa-proposal-btn reject" data-wa-review-action="reject" data-proposal-id="${_escHtml(proposal.id)}">\u62d2\u7edd</button>`
    : `<button type="button" class="wa-proposal-btn reject" data-wa-review-action="reject" data-proposal-id="${_escHtml(proposal.id)}">\u5173\u95ed</button>`;

  card.appendChild(header);
  card.appendChild(diffView);
  if (rText && rText.length > 5) card.appendChild(rationale);
  card.appendChild(actions);
  return card;
}

export function _makeProposalBatchBar(proposals: ProposalData[]): HTMLElement {
  const bar = document.createElement('div');
  bar.className = 'wa-proposal-batch-bar';
  const actionableCount = proposals.filter(_proposalCanApply).length;
  const tIdx = state._aiTargetFileIdx;
  const targetFile = (tIdx >= 0 && tIdx < state._aiFileContext.length) ? state._aiFileContext[tIdx] : null;
  const canDownload = actionableCount > 0 && targetFile && /\.(docx|txt|md)$/i.test(targetFile.name);
  const downloadBtn = canDownload
    ? `<button type="button" class="wa-proposal-btn download small" data-wa-review-action="download" title="\u5c06\u5168\u90e8\u4fee\u6539\u5e94\u7528\u5230\u76ee\u6807\u6587\u4ef6\u5e76\u4e0b\u8f7d">\u5e94\u7528\u5e76\u4e0b\u8f7d ${_escHtml(targetFile.name)}</button>`
    : '';
  bar.innerHTML =
    `<span class="wa-proposal-batch-label">\u5171 ${proposals.length} \u6761\u4fee\u6539\u5efa\u8bae</span>` +
    '<span class="wa-proposal-batch-counter" id="wa-proposal-counter">0/' + actionableCount + ' \u5df2\u5904\u7406</span>' +
    (actionableCount > 0 ? '<button type="button" class="wa-proposal-btn accept small" data-wa-review-action="batch-accept">\u5168\u90e8\u63a5\u53d7</button>' : '') +
    '<button type="button" class="wa-proposal-btn reject small" data-wa-review-action="batch-reject">\u5168\u90e8\u62d2\u7edd</button>' +
    downloadBtn;
  return bar;
}

export function _updateProposalCounter(): void {
  const counter = document.getElementById('wa-proposal-counter');
  if (!counter) return;
  const all = document.querySelectorAll('.wa-proposal-card[data-can-apply="1"]');
  const done = document.querySelectorAll('.wa-proposal-card[data-can-apply="1"].accepted, .wa-proposal-card[data-can-apply="1"].rejected');
  counter.textContent = `${done.length}/${all.length} \u5df2\u5904\u7406`;
}

// ── Public WA proposal operations ──

export async function acceptProposal(proposalId: string, btn?: HTMLElement): Promise<void> {
  const entry = _findProposalEntry(proposalId);
  const proposal = entry.proposal;
  if (!proposal) return;
  if (proposal._reviewStatus === 'accepted' || proposal._reviewStatus === 'rejected') return;
  if (!_proposalCanApply(proposal)) {
    showToast('\u8be5\u7ed3\u679c\u4ec5\u4f9b\u67e5\u770b\uff0c\u4e0d\u652f\u6301\u76f4\u63a5\u5199\u5165\u6587\u6863', 'info');
    return;
  }

  if (entry.tab && entry.tab.path && entry.tab.path !== state.activeTabPath) {
    await _switchToTab(entry.tab.path);
  }

  if (state.activeEditor) {
    try {
      if (_isImportedDocxRevisionProposal(proposal) && typeof state.activeEditor.applyImportedReviewDecision === 'function') {
        state.activeEditor.applyImportedReviewDecision(proposal, 'accept');
      } else if (proposal.tool_call) {
        const handled = workspaceApi.applyStructuredDocToolCall?.(proposal.tool_call, { notify: false });
        if (!handled) state.activeEditor.applyToolCall(proposal.tool_call);
      } else if (proposal.original_text && proposal.proposed_text) {
        const proposedPlain = (proposal.proposed_text || '').replace(/<[^>]+>/g, '').trim();
        state.activeEditor.applyToolCall({
          type: 'replace_text',
          original: proposal.original_text,
          value: proposedPlain || proposal.proposed_text,
        });
      }
    } catch(e) {
      console.warn('acceptProposal applyToolCall failed:', e);
    }
  }

  _setProposalReviewStatus(proposalId, 'accepted');
  _syncProposalDomState(proposalId, 'accepted');
  showToast('\u5df2\u63a5\u53d7\u4fee\u6539', 'success');
  workspaceApi.scheduleAutoSave?.();
  _updateProposalCounter();
  _syncReviewStateForActiveFile().catch(() => {});
}

export function rejectProposal(proposalId: string, btn?: HTMLElement): void {
  const entry = _findProposalEntry(proposalId);
  if (!entry.proposal) return;
  if (entry.proposal._reviewStatus === 'accepted' || entry.proposal._reviewStatus === 'rejected') return;
  if (_isImportedDocxRevisionProposal(entry.proposal) && state.activeEditor && typeof state.activeEditor.applyImportedReviewDecision === 'function') {
    try {
      state.activeEditor.applyImportedReviewDecision(entry.proposal, 'reject');
    } catch (e) {
      console.warn('rejectProposal imported revision failed:', e);
    }
  }
  _setProposalReviewStatus(proposalId, 'rejected');
  _syncProposalDomState(proposalId, 'rejected');
  showToast('\u5df2\u62d2\u7edd\u4fee\u6539', 'info');
  _updateProposalCounter();
  _syncReviewStateForActiveFile().catch(() => {});
}

export async function modifyProposal(proposalId: string, btn?: HTMLElement): Promise<void> {
  const entry = _findProposalEntry(proposalId);
  const proposal = entry.proposal;
  if (!proposal) return;
  if (entry.tab && entry.tab.path && entry.tab.path !== state.activeTabPath) {
    await _switchToTab(entry.tab.path);
  }
  const card = btn && (btn as HTMLElement).closest
    ? (btn as HTMLElement).closest('.wa-proposal-card') as HTMLElement
    : (document.querySelector(`[data-proposal-id="${CSS.escape(String(proposalId || ''))}"]`) as HTMLElement || null);
  if (!card) return;
  const existingInput = card.querySelector('.wa-proposal-modify-input');
  if (existingInput) {
    const textarea = existingInput.querySelector('.wa-proposal-modify-textarea') as HTMLTextAreaElement;
    if (textarea && typeof textarea.focus === 'function') {
      try { textarea.focus({ preventScroll: true }); } catch (_) { textarea.focus(); }
    }
    _relayoutDocxReviewRailAndScrollNode(existingInput as HTMLElement, { behavior: 'auto', topMargin: 12, bottomMargin: 16 });
    return;
  }

  if (!_proposalCanApply(proposal)) {
    showToast('\u8be5\u7ed3\u679c\u4ec5\u4f9b\u67e5\u770b\uff0c\u4e0d\u652f\u6301\u7ee7\u7eed\u4fee\u6539\u5e76\u5199\u56de\u6587\u6863', 'info');
    return;
  }

  const inputWrap = document.createElement('div');
  inputWrap.className = 'wa-proposal-modify-input';
  inputWrap.innerHTML =
    '<textarea class="wa-proposal-modify-textarea" placeholder="\u8f93\u5165\u4fee\u6539\u610f\u89c1\uff0c\u5982\uff1a\u8bed\u6c14\u518d\u6b63\u5f0f\u4e00\u4e9b\u2026" rows="2"></textarea>' +
    '<div class="wa-proposal-modify-actions">' +
    `<button type="button" class="wa-proposal-btn accept small" data-wa-review-action="submit-modify" data-proposal-id="${_escHtml(proposalId)}">\u53d1\u9001</button>` +
    `<button type="button" class="wa-proposal-btn reject small" data-wa-review-action="cancel-modify" data-proposal-id="${_escHtml(proposalId)}">\u53d6\u6d88</button>` +
    '</div>';
  card.appendChild(inputWrap);
  const textarea = inputWrap.querySelector('textarea') as HTMLTextAreaElement;
  if (textarea && typeof textarea.focus === 'function') {
    try { textarea.focus({ preventScroll: true }); } catch (_) { textarea.focus(); }
  }
  _relayoutDocxReviewRailAndScrollNode(inputWrap, { behavior: 'auto', topMargin: 12, bottomMargin: 16 });
}

export function cancelModifyProposal(proposalId: string, btn?: HTMLElement): void {
  const card = btn && (btn as HTMLElement).closest
    ? (btn as HTMLElement).closest('.wa-proposal-card') as HTMLElement
    : (document.querySelector(`[data-proposal-id="${CSS.escape(String(proposalId || ''))}"]`) as HTMLElement || null);
  const inputWrap = btn && (btn as HTMLElement).closest
    ? (btn as HTMLElement).closest('.wa-proposal-modify-input') as HTMLElement
    : (card ? card.querySelector('.wa-proposal-modify-input') as HTMLElement : null);
  if (inputWrap) inputWrap.remove();
  if (card) {
    _relayoutDocxReviewRailAndScrollNode(card, { behavior: 'auto', topMargin: 12, bottomMargin: 16 });
  }
}

export function _submitModify(proposalId: string, btn: HTMLElement): void {
  const card = btn.closest('.wa-proposal-card');
  if (!card) return;
  const textarea = card.querySelector('.wa-proposal-modify-textarea') as HTMLTextAreaElement;
  const feedback = textarea ? textarea.value.trim() : '';
  if (!feedback) return;

  const entry = _findProposalEntry(proposalId);
  const proposal = entry.proposal;
  if (!proposal) return;

  const inputWrap = card.querySelector('.wa-proposal-modify-input');
  if (inputWrap) inputWrap.remove();
  _relayoutDocxReviewRailAndScrollNode(card as HTMLElement, { behavior: 'auto', topMargin: 12, bottomMargin: 16 });
  _setProposalReviewStatus(proposalId, 'rejected');
  _syncProposalDomState(proposalId, 'rejected');
  _updateProposalCounter();
  _syncReviewStateForActiveFile().catch(() => {});

  const input = $('wa-user-input') as HTMLTextAreaElement;
  if (!input) return;
  const modifyPrompt = `\u8bf7\u91cd\u65b0\u4fee\u6539\u4ee5\u4e0b\u5185\u5bb9\u3002\n\u539f\u6587\uff1a\u300c${proposal.original_text.substring(0, 200)}\u300d\n\u4e0a\u6b21\u4fee\u6539\u4e3a\uff1a\u300c${(proposal.proposed_text || '').replace(/<[^>]+>/g, '').substring(0, 200)}\u300d\n\u7528\u6237\u53cd\u9988\uff1a${feedback}`;
  input.value = modifyPrompt;

  state.pinnedSelection = _createPinnedSelectionContext(proposal.original_text);
  workspaceApi.sendMessage?.();
}

export function batchAcceptAll(): void {
  const reviewState = _ensureTabReviewState(_activeReviewTab());
  const proposalIds = _visibleReviewProposals(reviewState)
    .filter(_proposalCanApply)
    .map((proposal: any) => String((proposal && (proposal.id || proposal.review_id)) || '').replace(/^proposal:/, '').trim())
    .filter(Boolean);
  proposalIds.reduce((chain: Promise<any>, proposalId: string) => {
    return chain.then(() => acceptProposal(proposalId));
  }, Promise.resolve()).catch((error: any) => {
    console.warn('batchAcceptAll failed:', error);
  });
}

function _activeReviewTab(): any {
  return state.openTabs.find((t: any) => t.path === state.activeTabPath) || null;
}

export function batchRejectAll(): void {
  const reviewState = _ensureTabReviewState(_activeReviewTab());
  const proposalIds = _visibleReviewProposals(reviewState)
    .map((proposal: any) => String((proposal && (proposal.id || proposal.review_id)) || '').replace(/^proposal:/, '').trim())
    .filter(Boolean);
  proposalIds.forEach((proposalId: string) => {
    rejectProposal(proposalId);
  });
}

let reviewActionDelegationInstalled = false;

function _installReviewActionDelegation(): void {
  if (reviewActionDelegationInstalled) return;
  reviewActionDelegationInstalled = true;
  document.addEventListener('click', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const button = target?.closest<HTMLElement>('[data-wa-review-action]');
    if (!button) return;
    const action = String(button.dataset.waReviewAction || '').trim();
    const proposalId = String(button.dataset.proposalId || '').trim();
    event.preventDefault();
    event.stopPropagation();
    try {
      if (action === 'accept' && proposalId) void acceptProposal(proposalId, button);
      else if (action === 'reject' && proposalId) rejectProposal(proposalId, button);
      else if (action === 'download') void downloadPatchedFile();
      else if (action === 'batch-accept') batchAcceptAll();
      else if (action === 'batch-reject') batchRejectAll();
      else if (action === 'submit-modify' && proposalId) _submitModify(proposalId, button);
      else if (action === 'cancel-modify' && proposalId) cancelModifyProposal(proposalId, button);
    } catch (error) {
      console.warn('[WA] review action failed:', error);
    }
  }, true);
}

export async function downloadPatchedFile(specificProposals?: ProposalData[]): Promise<void> {
  const tIdx = state._aiTargetFileIdx;
  const targetFile = (tIdx >= 0 && tIdx < state._aiFileContext.length) ? state._aiFileContext[tIdx] : null;
  if (!targetFile) {
    showToast('\u8bf7\u5148\u8bbe\u7f6e\u76ee\u6807\u6587\u4ef6\uff08\u70b9\u51fb\u6587\u4ef6\u65c1\u7684 Pin \u56fe\u6807\uff09', 'warn');
    return;
  }
  const proposals = (specificProposals || state._activeProposalBatch || state._activeProposals || []).filter(_proposalCanApply);
  if (!proposals.length) {
    showToast('\u6ca1\u6709\u53ef\u5e94\u7528\u7684\u4fee\u6539\u5efa\u8bae', 'warn');
    return;
  }
  showToast('\u6b63\u5728\u751f\u6210\u4fee\u6539\u540e\u7684\u6587\u4ef6\u2026', 'info');
  try {
    const res = await _csrfFetch('/api/v1/workspace/patch_file', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: targetFile.path,
        proposals: proposals.map((p: ProposalData) => ({
          original_text: p.original_text,
          proposed_text: p.proposed_text,
        })),
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const cdHeader = res.headers.get('Content-Disposition') || '';
    const fnMatch = cdHeader.match(/filename\*?=(?:UTF-8'')?([^;]+)/i);
    const dlName = fnMatch ? decodeURIComponent(fnMatch[1].replace(/"/g, '')) : `\u4fee\u6539\u540e_${targetFile.name}`;
    const arrayBuf = await blob.arrayBuffer();
    const uint8 = new Uint8Array(arrayBuf);
    let b64 = '';
    const chunkSize = 8192;
    for (let i = 0; i < uint8.length; i += chunkSize) {
      b64 += String.fromCharCode.apply(null, Array.from(uint8.subarray(i, i + chunkSize)));
    }
    b64 = btoa(b64);
    const saveRes = await _csrfFetch('/api/v1/workspace/save_to_workspace', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'file', data: b64, filename: dlName }),
    });
    if (!saveRes.ok) {
      const err = await saveRes.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${saveRes.status}`);
    }
    const saveData = await saveRes.json();
    _renderMyWorkspace();
    showToast(`\u5df2\u5b58\u5165\u5de5\u4f5c\u533a: ${saveData.ws_path}`, 'success');
  } catch (e: any) {
    showToast(`\u4e0b\u8f7d\u5931\u8d25: ${e.message}`, 'error');
  }
}

// ── AI Response Action Bar ──
export function _makeAIActionBar(snapshot: ActionBarSnapshot): HTMLElement {
  const runtime = _runtimeRef('_waAiResultsRuntime');
  if (runtime && typeof runtime.makeAIActionBar === 'function') {
    return runtime.makeAIActionBar(snapshot);
  }
  const bar = document.createElement('div');
  bar.className = 'wa-ai-action-bar';

  const label = document.createElement('span');
  label.className = 'wa-ai-action-label';
  label.textContent = 'AI \u56de\u590d\u4e86\uff0c\u5982\u4f55\u5904\u7406\uff1f';
  bar.appendChild(label);

  const _btn = (text: string, extraCls: string, mode: string): HTMLButtonElement => {
    const b = document.createElement('button');
    b.className = 'wa-ai-action-btn' + (extraCls ? ' ' + extraCls : '');
    b.textContent = text;
    b.addEventListener('click', () => _execWriteToDoc(mode, snapshot, bar));
    return b;
  };

  if (snapshot.pinnedSel) {
    bar.appendChild(_btn('\u66ff\u6362\u9009\u533a', 'primary', 'replace'));
    bar.appendChild(_btn('\u63d2\u5165\u5230\u540e\u9762', '', 'append'));
  } else if (snapshot.toolCall) {
    bar.appendChild(_btn('\u5e94\u7528\u5230\u6587\u6863', 'primary', 'replace'));
    bar.appendChild(_btn('\u63d2\u5165\u5230\u672b\u5c3e', '', 'append'));
  } else if (snapshot.outputMode && snapshot.outputMode !== 'chat') {
    bar.appendChild(_btn('\u5199\u5165\u6587\u6863', 'primary', 'replace'));
    bar.appendChild(_btn('\u63d2\u5165\u5230\u672b\u5c3e', '', 'append'));
  } else {
    bar.appendChild(_btn('\u63d2\u5165\u5230\u6587\u6863\u672b\u5c3e', 'primary', 'append'));
  }
  bar.appendChild(_btn('\u4ec5\u67e5\u770b', 'muted', 'view'));
  return bar;
}

function _execWriteToDoc(mode: string, snapshot: ActionBarSnapshot, bar: HTMLElement): void {
  if (mode !== 'view') {
    let msgEl = bar.previousElementSibling as HTMLElement;
    while (msgEl && !msgEl.classList.contains('wa-msg')) {
      msgEl = msgEl.previousElementSibling as HTMLElement;
    }
    const rawText = (msgEl && msgEl.dataset.rawText) ? msgEl.dataset.rawText
                  : (msgEl ? msgEl.textContent : '');

    const editor = state.activeEditor;
    const tc = snapshot.toolCall;
    const sel = _selectionContextText(snapshot.pinnedSel);

    if (tc && editor) {
      if (mode === 'replace') {
        editor.applyToolCall(tc);
      } else if (mode === 'append') {
        if (editor.appendToolCall) {
          editor.appendToolCall(tc);
        } else {
          editor.applyToolCall(tc);
        }
      }
    } else if (sel && editor && typeof editor.replaceSelectionWith === 'function') {
      editor.replaceSelectionWith(mode, sel, rawText);
    } else if (sel) {
      showToast('\u65e0\u6cd5\u5b9a\u4f4d\u539f\u59cb\u9009\u533a\uff0c\u5df2\u590d\u5236\u5230\u526a\u8d34\u677f', 'info');
      navigator.clipboard && navigator.clipboard.writeText(rawText).catch(() => {});
    } else if (editor) {
      if (mode === 'replace') {
        const htmlVal = (window as any).marked ? _sanitizeRenderedHtml((window as any).marked.parse(rawText)) : ('<p>' + _escHtml(rawText).replace(/\n/g, '</p><p>') + '</p>');
        editor.applyToolCall({ type: 'replace_all', value: htmlVal });
      } else {
        editor.applyToolCall({ type: 'insert_text', value: '\n' + rawText });
      }
      workspaceApi.scheduleAutoSave?.();
    }
  }
  bar.remove();
}

// ── Hide welcome card on first message ──
export function _hideWelcome(): void {
  const w = $('wa-ai-welcome');
  if (w && w.style.display !== 'none') w.style.display = 'none';
}

// ── Scenario card click ──
export function useScenario(text: string): void {
  _hideWelcome();
  setWorkspaceAiComposerValue('chat', text, { focus: true, dispatchInput: true });
}

function autoResize(ta: HTMLTextAreaElement): void {
  resizeWorkspaceAiComposer(ta);
}

export function handleInputKeydown(event: KeyboardEvent): void {
  const target = event.target as HTMLTextAreaElement | null;
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    if (typeof workspaceApi.sendMessage === 'function') {
      workspaceApi.sendMessage();
    }
    return;
  }
  if (target && target.tagName === 'TEXTAREA') {
    window.setTimeout(() => autoResize(target), 0);
  }
}

function _syncReviewModeButtons(): void {
  document.querySelectorAll('#wa-review-mode-group .wa-review-mode-btn').forEach((button) => {
    (button as HTMLElement).classList.toggle('is-active', (button as HTMLElement).dataset.mode === state._reviewMode);
  });
}

function _refreshReviewShell(): void {
  const renderReviewShell = (window as any)._renderReviewShell;
  if (typeof renderReviewShell === 'function') {
    try { renderReviewShell(); } catch (e) { console.warn("[Koto]", e) }
  }
  const layoutReviewRail = (window as any)._positionDocxReviewRail || (window as any)._layoutReviewShellInDocx;
  if (typeof layoutReviewRail === 'function') {
    try { layoutReviewRail(); } catch (e) { console.warn("[Koto]", e) }
  }
}

export function closeReviewCenter(): void {
  state._reviewCenterOpen = false;
  try { localStorage.setItem('wa_review_center_open', '0'); } catch (_) { /* allowed to fail */ }
  const shell = $('wa-review-shell');
  if (shell) shell.style.display = 'none';
  const host = $('wa-docx-editor');
  if (host) host.classList.remove('has-review-shell');
  _refreshReviewShell();
}

export function setReviewMode(mode: string): void {
  state._reviewMode = ['all', 'comments', 'proposals'].includes(mode) ? mode : 'all';
  state._reviewCenterOpen = true;
  try {
    localStorage.setItem('wa_review_mode', state._reviewMode);
    localStorage.setItem('wa_review_center_open', '1');
  } catch (e) { console.warn("[Koto]", e) }
  _syncReviewModeButtons();
  const shell = $('wa-review-shell');
  if (shell) shell.style.display = '';
  _syncReviewStateForActiveFile().catch(() => {});
  _refreshReviewShell();
}

// ── Task artifact resume ──
export function _resolveTaskArtifactResume(payload: ArtifactResumePayload): ArtifactResumeResult {
  const taskPayload = payload.taskPayload && typeof payload.taskPayload === 'object'
    ? JSON.parse(JSON.stringify(payload.taskPayload))
    : null;
  if (!taskPayload) return { valid: false };

  let followupContext = null;
  if (taskPayload.options && typeof taskPayload.options === 'object'
      && taskPayload.options.followup_context && typeof taskPayload.options.followup_context === 'object') {
    followupContext = JSON.parse(JSON.stringify(taskPayload.options.followup_context));
  }

  const isStepwise = followupContext && followupContext.kind === 'stepwise_task_resume';

  return {
    valid: true,
    taskPayload,
    followupContext,
    isStepwise,
    skipPersistedApi: isStepwise,
    usesFeedback: followupContext && !isStepwise,
  };
}

export function _shouldBindTaskFollowup(text: string, followupContext: any, defaultPrompt?: string): boolean {
  if (!followupContext || typeof followupContext !== 'object') return false;
  if (followupContext.kind === 'stepwise_task_resume') return true;
  const source = String(text || '').trim();
  if (!source) return false;
  const prompt = String(defaultPrompt || '').trim();
  if (prompt && (source === prompt || source.includes(prompt))) return true;
  return _looksLikeShortTaskResultFollowup(source, String(followupContext.followup_action || '').trim().toLowerCase());
}

export function _looksLikeTaskResultFollowupReference(text: string): boolean {
  const source = String(text || '').trim();
  if (!source) return false;
  return /(?:\u4e0a\u4e00\u8f6e|\u4e0a\u4e00\u7248|\u4e0a\u4e00\u6b21|\u4e0a\u6b21|\u524d\u4e00\u8f6e|\u521a\u624d|\u8fd9\u6b21|\u8fd9\u4e2a\u4efb\u52a1|\u8fd9\u6b21\u4efb\u52a1|\u8fd9\u4e2a\u7ed3\u679c|\u8fd9\u6b21\u7ed3\u679c|\u4e0a\u4e00\u8f6e\u7ed3\u679c|\u4e0a\u4e00\u8f6e\u5efa\u8bae|\u4e0a\u4e00\u8f6e\u5904\u7406|\u5f53\u524d\u7ed3\u679c|\u5f53\u524d\u65b9\u6848|\u8fd9\u4e2a\u65b9\u6848|\u4f60\u7684\u5efa\u8bae|\u524d\u9762\u7684\u5efa\u8bae|\u521a\u624d\u7684\u7ed3\u679c|\u524d\u4e00\u4e2a\u7ed3\u679c)/i.test(source);
}

export function _looksLikeShortTaskResultFollowup(text: string, action?: string): boolean {
  const source = String(text || '').trim();
  const followupAction = String(action || '').trim().toLowerCase();
  if (!source || source.length > 240) return false;
  if (_looksLikeTaskResultFollowupReference(source)) return true;
  if (followupAction === 'apply') {
    return /(?:\u76f4\u63a5\u5e94\u7528|\u5e94\u7528\u5efa\u8bae|\u6309\u4e0a\u4e00\u8f6e|\u6309\u5efa\u8bae|\u6309\u65b9\u6848|apply)/i.test(source);
  }
  if (followupAction === 'improve') {
    return /(?:\u7ee7\u7eed\u5206\u6790|\u7ee7\u7eed\u4f18\u5316|\u7ee7\u7eed\u4fee\u590d|\u7ee7\u7eed\u5904\u7406|\u7ee7\u7eed\u6539|\u7ec6\u5316|\u8865\u5145|\u5b8c\u5584|\u6539\u8fdb|\u4f18\u5316)/i.test(source);
  }
  return /(?:\u4e3a\u4ec0\u4e48\u8fd9\u6b21|\u4e3a\u4ec0\u4e48\u8fd9\u4e2a\u7ed3\u679c|\u89e3\u91ca\u4e00\u4e0b|\u8bf4\u660e\u4e00\u4e0b|\u8ffd\u95ee\u7ed3\u679c|\u7ee7\u7eed\u5206\u6790|\u7ee7\u7eed\u5904\u7406)/i.test(source);
}

export function _shouldKeepPendingTaskResultFollowup(text: string, followupContext: any, defaultPrompt?: string): boolean {
  return _shouldBindTaskFollowup(text, followupContext, defaultPrompt);
}

export function _clearPendingTaskResultFollowupBinding(noticeText?: string): void {
  state._pendingTaskFollowupPrompt = null;
  state._pendingTaskFollowupContext = null;
  state._pendingTaskPayload = null;
  state._pendingTaskPayloadUsesFeedback = false;
  if (noticeText) showToast(noticeText, 'info');
}

export function beginTaskResultFollowup(details: any): void {
  const payload = details || {};
  const action = String(payload.action || '').trim().toLowerCase();
  const completedTask = payload.completed_task === true;
  const rawTaskPayload = payload.taskPayload && typeof payload.taskPayload === 'object'
    ? JSON.parse(JSON.stringify(payload.taskPayload))
    : null;
  const pendingTaskPayload = payload.pendingTaskPayload && typeof payload.pendingTaskPayload === 'object'
    ? JSON.parse(JSON.stringify(payload.pendingTaskPayload))
    : null;
  const taskPayload = (!completedTask && pendingTaskPayload) ? pendingTaskPayload : rawTaskPayload;
  const shouldUseFeedbackTask = !!(taskPayload && taskPayload !== pendingTaskPayload);
  let previousTaskFileChanges: any[] = [];
  if (Array.isArray(payload.file_changes) && payload.file_changes.length) {
    try {
      previousTaskFileChanges = JSON.parse(JSON.stringify(payload.file_changes.slice(-8)));
    } catch (_) {
      previousTaskFileChanges = payload.file_changes
        .slice(-8)
        .filter((item: any) => item && typeof item === 'object')
        .map((item: any) => Object.assign({}, item));
    }
  }
  const previousTaskContract = typeof workspaceApi.compactTaskContract === 'function'
    ? workspaceApi.compactTaskContract(payload.task_contract)
    : null;
  const previousTaskContext = typeof workspaceApi.compactTaskContext === 'function'
    ? workspaceApi.compactTaskContext(payload.task_context)
    : null;
  const followupContext: Record<string, any> = {
    kind: 'review_last_task',
    source: 'task_result_action',
    followup_action: action || 'question',
    user_feedback: '',
    previous_run_id: String(payload.run_id || '').trim(),
    previous_task_summary: String(payload.summary || '').trim(),
    previous_task_status: String(payload.terminal_status || '').trim() || (completedTask ? 'completed' : 'failed'),
    previous_task_request: String(payload.task || '').trim(),
    previous_task_mode: String(payload.mode || '').trim(),
    previous_task_request_kind: String(payload.request_kind || '').trim(),
    previous_task_family: String(payload.task_family || '').trim(),
    previous_task_operation_kind: String(payload.operation_kind || '').trim(),
    previous_task_execution_mode: String(payload.execution_mode || '').trim(),
    previous_task_selected_recipe: String(payload.selected_recipe || payload.task_selected_recipe || '').trim(),
    previous_task_output_mode: String(payload.output_mode || '').trim(),
    previous_task_intent_strategy: String(payload.intent_strategy || '').trim(),
    previous_task_intent_can_apply: Object.prototype.hasOwnProperty.call(payload, 'intent_can_apply')
      ? (payload.intent_can_apply ? 'true' : 'false')
      : '',
    previous_task_intent_requires_confirmation: Object.prototype.hasOwnProperty.call(payload, 'intent_requires_confirmation')
      ? (payload.intent_requires_confirmation ? 'true' : 'false')
      : '',
    previous_task_target_file_type: String(payload.target_file_type || '').trim(),
    previous_completed_task: completedTask ? 'true' : 'false',
  };
  if (previousTaskContract && previousTaskContract.contract_id) {
    followupContext.previous_task_contract_id = previousTaskContract.contract_id;
  }
  if (previousTaskContract) followupContext.previous_task_contract = previousTaskContract;
  if (previousTaskContext) followupContext.previous_task_context = previousTaskContext;
  if (previousTaskFileChanges.length) followupContext.previous_task_file_changes = previousTaskFileChanges;

  const defaultPrompt = action === 'apply'
    ? '\u8bf7\u628a\u4e0a\u4e00\u8f6e\u5df2\u7ecf\u7ed9\u51fa\u7684\u5efa\u8bae\u76f4\u63a5\u5e94\u7528\u5230\u76ee\u6807\u6587\u4ef6\uff1b\u6cbf\u7528\u540c\u4e00\u4efb\u52a1\u4e0a\u4e0b\u6587\u7ee7\u7eed\u5199\u56de\uff0c\u4e0d\u8981\u91cd\u65b0\u4ece\u5934\u5206\u6790\u3002'
    : action === 'improve'
    ? (completedTask
        ? '\u8bf7\u7ee7\u7eed\u4f18\u5316\u4e0a\u4e00\u8f6e\u4efb\u52a1\u7ed3\u679c\uff0c\u6307\u51fa\u5f53\u524d\u4e0d\u8db3\uff0c\u5e76\u5728\u540c\u4e00\u4efb\u52a1\u91cc\u7ee7\u7eed\u5904\u7406\u3002'
        : '\u8bf7\u7ee7\u7eed\u4fee\u590d\u4e0a\u4e00\u8f6e\u4efb\u52a1\uff0c\u89e3\u91ca\u5931\u8d25\u539f\u56e0\u5e76\u7ee7\u7eed\u5904\u7406\uff0c\u76f4\u5230\u7ed9\u51fa\u66f4\u597d\u7684\u7ed3\u679c\u3002')
    : (completedTask
        ? '\u4e3a\u4ec0\u4e48\u8fd9\u6b21\u7ed3\u679c\u4f1a\u8fd9\u6837\uff1f\u8bf7\u89e3\u91ca\u4f60\u7684\u5904\u7406\u4f9d\u636e\u3001\u5f53\u524d\u53ef\u80fd\u7684\u4e0d\u8db3\uff0c\u4ee5\u53ca\u5982\u679c\u8981\u7ee7\u7eed\u4f18\u5316\u5e94\u8be5\u600e\u4e48\u505a\u3002'
        : '\u4e3a\u4ec0\u4e48\u8fd9\u6b21\u4efb\u52a1\u6ca1\u6709\u505a\u597d\uff1f\u8bf7\u89e3\u91ca\u5361\u5728\u54ea\u4e00\u6b65\u3001\u5931\u8d25\u539f\u56e0\u662f\u4ec0\u4e48\uff0c\u4ee5\u53ca\u4e0b\u4e00\u6b65\u5e94\u8be5\u600e\u4e48\u4fee\u3002');

  const input = $('wa-user-input') as HTMLTextAreaElement;
  state._pendingTaskFollowupContext = followupContext;
  state._pendingTaskFollowupPrompt = defaultPrompt;
  state._pendingTaskPayload = taskPayload;
  state._pendingTaskPayloadUsesFeedback = shouldUseFeedbackTask;
  _hideWelcome();
  if (input) {
    const existing = String(input.value || '').trim();
    if (!existing) {
      input.value = defaultPrompt;
    } else if (!existing.includes(defaultPrompt)) {
      input.value = `${existing}\n${defaultPrompt}`;
    }
    input.focus();
    autoResize(input);
  }
  showToast(
    action === 'apply'
      ? '\u5df2\u7ed1\u5b9a\u4e0a\u4e00\u4efb\u52a1\uff0c\u53d1\u9001\u540e\u4f1a\u6cbf\u4e0a\u4e00\u8f6e\u5efa\u8bae\u7ee7\u7eed\u5199\u56de\u3002'
      : (action === 'improve'
          ? '\u5df2\u7ed1\u5b9a\u4e0a\u4e00\u4efb\u52a1\uff0c\u53d1\u9001\u540e\u4f1a\u5728\u540c\u4e00\u4efb\u52a1\u91cc\u7ee7\u7eed\u4f18\u5316\u3002'
          : '\u5df2\u7ed1\u5b9a\u4e0a\u4e00\u4efb\u52a1\uff0c\u53d1\u9001\u540e\u4f1a\u56f4\u7ed5\u4e0a\u4e00\u7ed3\u679c\u7ee7\u7eed\u8ffd\u95ee\u3002'),
    'info'
  );
}

export function resumeTaskArtifact(details: ArtifactResumePayload): boolean {
  const resolved = _resolveTaskArtifactResume(details || {});
  if (!resolved.valid) {
    showToast('\u4efb\u52a1\u4fe1\u606f\u65e0\u6548', 'warning');
    return false;
  }
  if (state.isLoading) {
    showToast('\u8bf7\u5148\u7b49\u5f85\u5f53\u524d\u4efb\u52a1\u5b8c\u6210', 'warning');
    return false;
  }

  const actionLabel = String(details.actionLabel || details.title || resolved.taskPayload.task || '\u4efb\u52a1').trim() || '\u4efb\u52a1';
  state._pendingTaskFollowupContext = resolved.followupContext;
  state._pendingTaskFollowupPrompt = resolved.followupContext ? null : null;
  state._pendingTaskPayload = resolved.taskPayload;
  state._pendingTaskPayloadUsesFeedback = resolved.usesFeedback;
  _hideWelcome();
  const input = $('wa-user-input') as HTMLTextAreaElement;
  if (input) {
    input.value = actionLabel;
    autoResize(input);
  }
  workspaceApi.sendMessage?.();
  return true;
}

export async function resumePersistedTaskArtifact(details: ArtifactResumePayload): Promise<boolean> {
  const resolved = _resolveTaskArtifactResume(details || {});
  if (!resolved.valid) return workspaceApi.resumeTaskArtifact(details);

  const taskId = String(details.taskId || (resolved.taskPayload && resolved.taskPayload.task_id) || '').trim();
  if (!taskId || resolved.skipPersistedApi) {
    return workspaceApi.resumeTaskArtifact(details);
  }

  let response: Response | null = null;
  let responsePayload: any = null;
  try {
    response = await _csrfFetch('/api/tasks/' + encodeURIComponent(taskId) + '/resume', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        approved: true,
        comment: String(details.comment || '').trim() || undefined,
      }),
    });
    responsePayload = await response.json().catch((): any => null);
    if (!response.ok || !responsePayload || responsePayload.ok === false) {
      throw new Error(responsePayload && responsePayload.error ? responsePayload.error : '\u4efb\u52a1\u6062\u590d\u5931\u8d25');
    }
  } catch (error) {
    console.debug('[WA] persisted task resume request unavailable; falling back to local resume payload:', error);
    return workspaceApi.resumeTaskArtifact(details);
  }

  if (typeof workspaceApi.resumePersistedFileTask === 'function') {
    Promise.resolve(workspaceApi.resumePersistedFileTask({
      taskId,
      loadingEl: details.loadingEl,
      replay: false,
      initialStatus: 'running',
    })).catch((error: any) => {
      console.warn('[WA] persisted task stream reattach failed:', error);
      showToast('\u4efb\u52a1\u6d41\u6062\u590d\u5931\u8d25', 'warning');
    });
  }
  return true;
}

// ── Send Message pipeline ──
export function sendMessage(): void {
  const input = $('wa-user-input') as HTMLTextAreaElement;
  const text = input.value.trim();
  if (state.isLoading) return;

  if (!text) return;

  if (state._aiFileContext && state._aiFileContext.some((f: any) => f.loading)) {
    const loadingNames = state._aiFileContext.filter((f: any) => f.loading).map((f: any) => f.name).join(', ');
    showToast(`\u8bf7\u7b49\u5f85\u6587\u4ef6\u8bfb\u53d6\u5b8c\u6210\uff1a${loadingNames}`, 'warning');
    return;
  }
  if (state._aiFileContext && state._aiFileContext.some((f: any) => f.error)) {
    const failedNames = state._aiFileContext.filter((f: any) => f.error).map((f: any) => f.name).join(', ');
    showToast(`\u8bf7\u5148\u91cd\u8bd5\u6216\u79fb\u9664\u8bfb\u53d6\u5931\u8d25\u7684\u6587\u4ef6\uff1a${failedNames}`, 'warning');
    return;
  }

  const pinnedSel = state.pinnedSelection;
  const liveSelection = (!pinnedSel && !state._selectionDismissed) ? _getLiveEditorSelectionForAI() : null;
  const liveSelectionContext = !pinnedSel && liveSelection
    ? _createPinnedSelectionContext(
        typeof liveSelection === 'object'
          ? Object.assign({}, _getPinnedSelectionSourceMeta(), liveSelection)
          : liveSelection,
        typeof liveSelection === 'string' ? _getPinnedSelectionSourceMeta() : undefined,
      )
    : null;
  const explicitSelection = pinnedSel || liveSelectionContext;
  const pinnedSelText = _selectionContextText(explicitSelection);
  const pinnedSelSource = _selectionContextSourceLabel(explicitSelection);
  state.lastPinnedSel = explicitSelection || null;
  state.pendingToolCall = null;
  if (pinnedSelText) workspaceApi.clearSelection?.();

  function _readyAIFileContext(): any[] {
    return (state._aiFileContext || []).filter((f: any) => !f.error && !f.loading);
  }

  const conversationRuntime = _runtimeRef('_waConversationRuntime');
  const turnUi = conversationRuntime && typeof conversationRuntime.appendUserMessageWithLoading === 'function'
    ? conversationRuntime.appendUserMessageWithLoading({
        content: text,
        files: _readyAIFileContext(),
        quoteText: pinnedSelText,
        quoteSource: pinnedSelSource,
        task_kind: 'message',
      })
    : null;
  const msgs = turnUi && turnUi.msgs ? turnUi.msgs : $('wa-ai-messages');
  const loadingEl = turnUi && turnUi.loadingEl ? turnUi.loadingEl : document.createElement('div');
  if (!turnUi) {
    _hideWelcome();
    const uMsg = document.createElement('div');
    uMsg.className = 'wa-msg user';
    uMsg.textContent = text;
    msgs.appendChild(uMsg);
    loadingEl.className = 'wa-msg ai streaming';
    msgs.appendChild(loadingEl);
    msgs.scrollTop = msgs.scrollHeight;
    (state.conversation || []).push({ role: 'user', content: text });
  }

  input.value = '';
  autoResize(input);

  state.isLoading = true;
  let pendingTaskPayload = state._pendingTaskPayload && typeof state._pendingTaskPayload === 'object'
    ? JSON.parse(JSON.stringify(state._pendingTaskPayload))
    : null;
  let pendingTaskFollowupContext = state._pendingTaskFollowupContext && typeof state._pendingTaskFollowupContext === 'object'
    ? Object.assign({}, state._pendingTaskFollowupContext, { user_feedback: text })
    : null;
  if (pendingTaskFollowupContext && !_shouldKeepPendingTaskResultFollowup(text, pendingTaskFollowupContext, state._pendingTaskFollowupPrompt)) {
    pendingTaskPayload = null;
    pendingTaskFollowupContext = null;
    _clearPendingTaskResultFollowupBinding('\u5df2\u6e05\u9664\u4e0a\u4e00\u4efb\u52a1\u7ed1\u5b9a\uff0c\u5f53\u524d\u6d88\u606f\u5c06\u6309\u65b0\u4efb\u52a1\u5904\u7406\u3002');
  }
  if (pendingTaskPayload && pendingTaskFollowupContext && state._pendingTaskPayloadUsesFeedback) {
    pendingTaskPayload.task = text;
  }

  if (typeof workspaceApi._initWorkspaceAiRuntimes === 'function') {
    workspaceApi._initWorkspaceAiRuntimes();
  }
  const taskDispatcher = _runtimeRef('_waTaskDispatcher');
  if (!taskDispatcher || typeof taskDispatcher.dispatchMessage !== 'function') {
    loadingEl.classList.remove('streaming');
    loadingEl.textContent = '\u6587\u4ef6\u4efb\u52a1\u8fd0\u884c\u65f6\u672a\u52a0\u8f7d\uff0c\u8bf7\u5237\u65b0\u540e\u91cd\u8bd5\u3002';
    state.isLoading = false;
    return;
  }

  taskDispatcher.dispatchMessage({
    text,
    pinnedSelText,
    pinnedSelSource,
    selectionContext: explicitSelection || null,
    msgs,
    loadingEl,
    taskPayload: pendingTaskPayload,
    options: pendingTaskFollowupContext ? { followup_context: pendingTaskFollowupContext } : {},
  }).catch((error: any) => {
    loadingEl.classList.remove('streaming');
    loadingEl.textContent = `\u7f51\u7edc\u9519\u8bef\uff1a${error && error.message ? error.message : error}`;
    state.isLoading = false;
    _setStreamBtn(false);
  });
  _clearPendingTaskResultFollowupBinding();
}

export function sendCustomMessage(text: string): void {
  const input = $('wa-user-input') as HTMLTextAreaElement | null;
  if (!input) {
    showToast('AI 输入框未加载，请刷新后重试。', 'warning');
    return;
  }
  input.value = String(text || '').trim();
  input.focus();
  autoResize(input);
  sendMessage();
}

// ── Quick action dispatcher ──
export function sendQuickAction(action: string): void {
  if (state.isLoading) {
    showToast('\u8bf7\u5148\u7b49\u5f85\u5f53\u524d\u4efb\u52a1\u5b8c\u6210\uff0c\u6216\u70b9\u51fb\u53f3\u4e0b\u89d2\u6682\u505c', 'info');
    return;
  }

  const liveSelection = _getLiveEditorSelectionForAI();
  const docxSelection = liveSelection && typeof liveSelection === 'object' ? liveSelection : null;
  let sel = typeof liveSelection === 'string'
    ? liveSelection
    : (docxSelection ? String(docxSelection.text || '') : '');
  let hasSelection = !!sel;
  let fullDocText = state.activeEditor ? (state.activeEditor.getContent() || '') : '';

  if (state.fileType === 'xlsx' && state.activeEditor) {
    const rangeText = state.activeEditor.getContent();
    if (rangeText && !rangeText.includes('\u672a\u9009\u4e2d\u533a\u57df')) {
      sel = rangeText;
      hasSelection = true;
    } else {
      const csv = (state.activeEditor.getCSV && state.activeEditor.getCSV()) || '';
      if (csv.trim()) fullDocText = '[\u8868\u683c\u5168\u90e8\u6570\u636e]:\n' + csv;
    }
  }
  if (!hasSelection && state.fileType === 'docx') {
    sel = workspaceApi._getDocxSelectionTextForAI ? workspaceApi._getDocxSelectionTextForAI() : '';
    hasSelection = !!sel;
  }

  const WA_FULL_DOC_QUICK_ACTIONS = new Set(['\u6da6\u8272', '\u7ffb\u8bd1', '\u603b\u7ed3', '\u7eed\u5199', '\u68c0\u67e5']);
  const quickActionRuntime = _runtimeRef('_waQuickActionRuntime');
  const canUseFullDocument = (quickActionRuntime && typeof quickActionRuntime.canUseFullDocument === 'function')
    ? quickActionRuntime.canUseFullDocument(action, state.fileType)
    : (WA_FULL_DOC_QUICK_ACTIONS.has(action) || (action === '\u53ef\u89c6\u5316' && state.fileType === 'xlsx'));
  if (!hasSelection && canUseFullDocument && fullDocText.trim()) {
    sel = fullDocText;
  }

  if (!sel) {
    showToast(canUseFullDocument ? '\u5f53\u524d\u6587\u6863\u4e3a\u7a7a\uff0c\u6682\u65e0\u53ef\u5904\u7406\u5185\u5bb9' : '\u8bf7\u5148\u9009\u4e2d\u6587\u5b57', 'info');
    return;
  }

  _hideWelcome();
  const tt = $('wa-pdf-tooltip');
  if (tt) tt.style.display = 'none';
  if (hasSelection) {
    _saveEditorRange();
    state.pinnedSelection = docxSelection
      ? _createPinnedSelectionContext(docxSelection)
      : _createPinnedSelectionContext(sel);
  } else {
    state.pinnedSelection = null;
  }
  (window as any).lastSelectionText = '';
  try { window.getSelection()?.removeAllRanges(); } catch (_) { /* allowed to fail */ }

  const msgs = $('wa-ai-messages');
  if (!msgs) return;
  const preview = hasSelection
    ? ((docxSelection && docxSelection.previewText)
      ? docxSelection.previewText
        : (sel.length > 60 ? sel.substring(0, 60) + '\u2026' : sel))
    : (action === '\u53ef\u89c6\u5316' ? '\u5f53\u524d\u8868\u683c\u6570\u636e' : '\u5168\u6587');
  const userText = `${action}\uff1a${preview}`;
  const conversationRuntime = _runtimeRef('_waConversationRuntime');
  const turnUi = conversationRuntime && typeof conversationRuntime.appendUserMessageWithLoading === 'function'
    ? conversationRuntime.appendUserMessageWithLoading({
        content: userText,
        task_kind: 'quick_action',
        loadingHtml: '<span class="wa-progress-text">\u23f3 \u5904\u7406\u4e2d\u2026</span>',
      })
    : null;
  const loadingEl = turnUi && turnUi.loadingEl ? turnUi.loadingEl : document.createElement('div');
  if (!turnUi) {
    const uMsg = document.createElement('div');
    uMsg.className = 'wa-msg user';
    uMsg.textContent = userText;
    msgs.appendChild(uMsg);
    loadingEl.className = 'wa-msg ai streaming';
    loadingEl.innerHTML = '<span class="wa-progress-text">\u23f3 \u5904\u7406\u4e2d\u2026</span>';
    msgs.appendChild(loadingEl);
    msgs.scrollTop = msgs.scrollHeight;
  }

  state.lastPinnedSel = hasSelection ? state.pinnedSelection : null;
  state.pendingToolCall = null;

  if (typeof workspaceApi._initWorkspaceAiRuntimes === 'function') {
    workspaceApi._initWorkspaceAiRuntimes();
  }
  const taskDispatcher = _runtimeRef('_waTaskDispatcher');
  if (!taskDispatcher || typeof taskDispatcher.dispatchQuickAction !== 'function') {
    loadingEl.classList.remove('streaming');
    loadingEl.textContent = '\u5feb\u6377\u52a8\u4f5c\u8fd0\u884c\u65f6\u672a\u52a0\u8f7d\uff0c\u8bf7\u5237\u65b0\u540e\u91cd\u8bd5\u3002';
    msgs.scrollTop = msgs.scrollHeight;
    return;
  }

  _clearPendingTaskResultFollowupBinding();

  taskDispatcher.dispatchQuickAction(action, {
    selectionText: sel,
    selectionSource: _selectionContextSourceLabel(state.pinnedSelection),
    pinnedSelSource: _selectionContextSourceLabel(state.pinnedSelection),
    selectionContext: state.pinnedSelection || null,
    fullDocText,
    hasSelection,
    loadingEl,
    msgs,
    csv_data: action === '\u53ef\u89c6\u5316' ? sel : '',
    prompt: action === '\u53ef\u89c6\u5316'
      ? '\u8bf7\u57fa\u4e8e\u5f53\u524d\u6570\u636e\u751f\u6210\u6700\u5408\u9002\u3001\u6700\u6e05\u6670\u7684\u56fe\u8868\uff0c\u5e76\u5728\u5fc5\u8981\u65f6\u81ea\u52a8\u6e05\u6d17\u5217\u540d\u4e0e\u7a7a\u503c\u3002'
      : '',
    language: action === '\u53ef\u89c6\u5316' ? 'python' : '',
  }).catch((err: any) => {
    loadingEl.classList.remove('streaming');
    loadingEl.textContent = `\u7f51\u7edc\u9519\u8bef\uff1a${err.message}`;
    msgs.scrollTop = msgs.scrollHeight;
    state.isLoading = false;
    state._streamAbortCtrl = null;
    _setStreamBtn(false);
  });
}

_installReviewActionDelegation();

publishWorkspaceApi({
  acceptProposal,
  rejectProposal,
  modifyProposal,
  cancelModifyProposal,
  _submitModify,
  batchAcceptAll,
  batchRejectAll,
  downloadPatchedFile,
  useScenario,
  resumeTaskArtifact,
  resumePersistedTaskArtifact,
  sendMessage,
  sendCustomMessage,
  stopStream,
  handleInputKeydown,
  closeReviewCenter,
  setReviewMode,
  sendQuickAction,
  beginTaskResultFollowup,
  _makeAIActionBar,
  _hideWelcome,
});

// Kept as short-lived compatibility hooks for review extensions that are not
// part of the Workspace API contract yet.
if (typeof window !== 'undefined') {
  (window as any)._sanitizeRenderedHtml = _sanitizeRenderedHtml;
  (window as any)._getPinnedSelectionSourceMeta = _getPinnedSelectionSourceMeta;
  (window as any)._selectionContextText = _selectionContextText;
  (window as any)._selectionContextSourceLabel = _selectionContextSourceLabel;
  (window as any)._createPinnedSelectionContext = _createPinnedSelectionContext;
  (window as any)._setStreamBtn = _setStreamBtn;
}
