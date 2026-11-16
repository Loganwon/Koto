/**
 * Results renderer for workspace AI — proposals, diffs, artifacts, tool calls.
 */

import { fileTaskStatusLabel } from './file-task-status';
import { _escHtml } from './infrastructure';
import { getFeatureRegistry, registerFeatures } from '../shared/feature-registry';
import type { EditorInstance } from './state';
import { captureDocumentReviewContext, sameReviewContext, type ReviewContext } from './document-review-context';
import { loadDocumentReviewRuntime } from './document-review-loader';
import { appendDocumentReceipt, documentReceiptRecord } from './task-document-receipt';

interface Proposal {
  id?: string;
  action?: string;
  action_type?: string;
  read_only?: boolean;
  apply_disabled?: boolean;
  original_text?: string;
  proposed_text?: string;
  rationale?: string;
  tool_call?: ToolCall;
  status?: string;
  applied?: boolean;
  receipt?: any;
  execution_receipt?: any;
  expected_revision?: string;
  [key: string]: any;
}
interface ToolCall {
  type: string;
  original?: string;
  value?: string;
  [key: string]: any;
}

interface ArtifactResult {
  task_id: string;
  title: string;
  status: string;
  summary: string;
  artifacts: Artifact[];
  changes: Change[];
  sources: Source[];
  logs: LogEntry[];
  actions: any[];
}

interface Artifact {
  path?: string;
  type?: string;
  title?: string;
  preview_url?: string;
}

interface Change {
  kind?: string;
  file?: string;
  summary?: string;
  status?: string;
  after_preview?: string;
}

interface Source {
  title?: string;
  file?: string;
  url?: string;
  locator?: string;
  snippet?: string;
}

interface LogEntry {
  level?: string;
  message?: string;
}

interface AiActionSnapshot {
  pinnedSel?: any;
  toolCall?: ToolCall;
  outputMode?: string;
}

interface ResultsState {
  _activeProposals?: Proposal[];
  _aiTargetFileIdx?: number;
  _aiFileContext?: Array<{ name: string }>;
  activeEditor?: EditorInstance | null;
  pinnedSelection?: any;
  lastPinnedSel?: any;
  pendingToolCall?: ToolCall | null;
  [key: string]: any;
}

interface ResultsDeps {
  state?: ResultsState;
  getMessagesElement?: () => HTMLElement | null;
  selectionContextText?: (ctx: any) => string;
  createPinnedSelectionContext?: (text: string) => any;
  showToast?: (
    message: string,
    type?: 'success' | 'error' | 'info' | 'warning',
  ) => void;
  scheduleAutoSave?: (_options?: { skipDiskWrite?: boolean }) => void;
  getUserInputElement?: () => HTMLInputElement | HTMLTextAreaElement | null;
  sendMessage?: () => void;
  computeInlineDiff?: (original: string, proposed: string) => string;
  lightbulbIcon?: string;
  pencilIcon?: string;
}

interface ResultsApi {
  getProposalRationaleText: (proposal: Proposal) => string;
  proposalCanApply: (proposal: Proposal) => boolean;
  makeProposalCard: (proposal: Proposal, index: number, total: number) => HTMLElement;
  makeProposalBatchBar: (proposals: Proposal[]) => HTMLElement;
  updateProposalCounter: () => void;
  handleProposals: (data: { proposals?: Proposal[] }) => void;
  acceptProposal: (proposalId: string, btn: HTMLElement | null) => Promise<void>;
  rejectProposal: (proposalId: string, btn: HTMLElement | null) => void;
  modifyProposal: (proposalId: string, btn: HTMLElement | null) => void;
  submitModify: (proposalId: string, btn: HTMLElement | null) => void;
  batchAcceptAll: () => Promise<void>;
  batchRejectAll: () => void;
  makeAIActionBar: (snapshot: AiActionSnapshot) => HTMLElement;
  execWriteToDoc: (mode: string, snapshot: AiActionSnapshot, bar: HTMLElement | null) => Promise<void>;
  applyAIResponse: (mode: string, btn: HTMLElement | null) => Promise<void>;
  renderArtifactResult: (raw: any, renderOptions?: { activeTab?: string }) => HTMLElement | null;
}

declare global {
  interface Window {
    WA: any;
    marked?: { parse: (text: string) => string };
  }
}


function normalizeProposalText(text: unknown): string {
  return String(text || '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/^(?:以下|下面|这是|如下)(?:是|为)?.{0,20}(?:润色|翻译|改写|修改|修正|优化|版本|结果|文本|内容).{0,10}[：:]\s*/i, '')
    .replace(/\s+/g, '')
    .trim()
    .toLowerCase();
}

function basename(path: unknown): string {
  const parts = String(path || '').replace(/\\/g, '/').split('/');
  return parts[parts.length - 1] || '';
}

function receiptApplied(raw: any): boolean {
  const value = raw?.value || raw;
  return value?.applied === true || value?.persisted === true;
}

function safeWebUrl(raw: unknown): string {
  const value = String(raw || '').trim(); if (!value) return '';
  try { const url = new URL(value, window.location.href); return ['http:', 'https:'].includes(url.protocol) ? url.href : ''; }
  catch (_) { return ''; }
}

export function createWorkspaceAiResultsRuntime(deps: ResultsDeps = {}): ResultsApi {
  const options = deps || {};
  const state = options.state || {};
  const getMessagesElement = typeof options.getMessagesElement === 'function'
    ? options.getMessagesElement
    : () => document.getElementById('wa-ai-messages');
  const selectionContextText = typeof options.selectionContextText === 'function'
    ? options.selectionContextText
    : (selectionContext: any) => {
        if (selectionContext && typeof selectionContext === 'object') {
          return String(selectionContext.text || selectionContext.value || '');
        }
        return String(selectionContext || '');
      };
  const createPinnedSelectionContext = typeof options.createPinnedSelectionContext === 'function'
    ? options.createPinnedSelectionContext
    : (text: string) => text;
  const showToast = typeof options.showToast === 'function'
    ? options.showToast
    : (_message: string, _type?: string) => {};
  const scheduleAutoSave = typeof options.scheduleAutoSave === 'function'
    ? options.scheduleAutoSave
    : () => {};
  const getUserInputElement = typeof options.getUserInputElement === 'function'
    ? options.getUserInputElement
    : () => document.getElementById('wa-user-input') as HTMLInputElement | null;
  const sendMessage = typeof options.sendMessage === 'function'
    ? options.sendMessage
    : () => {};
  const lightbulbIcon = options.lightbulbIcon || '';
  type ProposalState = 'candidate' | 'applying' | 'applied' | 'saved' | 'failed' | 'unconfirmed' | 'rejected';
  type ProposalEntry = { proposal: Proposal; card: HTMLElement; baseline: ReviewContext | null; phase: ProposalState; batch: number; receipt?: any; inFlight?: Promise<void> };
  const proposalEntries = new Map<string, ProposalEntry>();
  const actionBaselines = new WeakMap<HTMLElement, ReviewContext | null>();
  let proposalSequence = 0;
  const reviewInstance = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  let proposalBatch = 0;
  let batchInFlight: Promise<void> | null = null;

  function setProposalState(entry: ProposalEntry, phase: ProposalState, reason = ''): void {
    entry.phase = phase; entry.proposal.status = phase; entry.card.dataset.status = phase;
    entry.card.classList.toggle('accepted', phase === 'applied' || phase === 'saved');
    entry.card.classList.toggle('rejected', phase === 'rejected');
    const status = entry.card.querySelector<HTMLElement>('.wa-proposal-state');
    if (status) status.textContent = reason || ({ candidate: '候选修改 · 尚未应用', applying: '正在应用并核对文档…', applied: '已应用到编辑器 · 尚未保存', saved: '已保存并核验', failed: '应用失败 · 建议已保留', unconfirmed: '结果未知 · 请先核对文档', rejected: '已拒绝此建议' }[phase]);
    entry.card.querySelectorAll<HTMLButtonElement>('.wa-proposal-actions button').forEach((button) => {
      if (button.classList.contains('accept') || button.classList.contains('reject')) button.disabled = !['candidate', 'failed'].includes(phase);
    });
  }

  function proposalEntry(proposalId: string, btn: HTMLElement | null): ProposalEntry | undefined {
    const card = findProposalCard(proposalId, btn);
    return card ? proposalEntries.get(card.dataset.reviewKey || '') : undefined;
  }

  function getProposalRationaleText(proposal: Proposal): string {
    const raw = String(proposal?.rationale || '').replace(/<[^>]+>/g, '').trim();
    if (!raw) return '';
    const rationaleKey = normalizeProposalText(raw);
    const originalKey = normalizeProposalText(proposal && proposal.original_text ? proposal.original_text : '');
    const proposedKey = normalizeProposalText(proposal && proposal.proposed_text ? proposal.proposed_text : '');
    if (!rationaleKey || rationaleKey === originalKey || rationaleKey === proposedKey) return '';
    return raw;
  }

  function proposalCanApply(proposal: Proposal): boolean {
    if (!proposal) return false;
    if (proposal.read_only || proposal.apply_disabled) return false;
    if (proposal.applied === true || proposal.persisted === true || ['accepted', 'applied', 'saved', 'unconfirmed', 'applying', 'rejected'].includes(String(proposal.status || ''))) return false;
    if (receiptApplied(proposal.receipt) || receiptApplied(proposal.execution_receipt)) return false;
    const rationale = String(proposal.rationale || '').replace(/<[^>]+>/g, '').trim();
    const actionType = String(proposal.action || proposal.action_type || '').trim();
    if (/翻译/.test(rationale) || /translate/i.test(actionType)) return false;
    return !!(proposal.tool_call || (proposal.original_text && proposal.proposed_text !== undefined));
  }

  function updateProposalCounter(): void {
    document.querySelectorAll<HTMLElement>('.wa-proposal-batch-counter').forEach((counter) => {
      const batch = counter.closest<HTMLElement>('.wa-proposal-batch-bar')?.dataset.reviewBatch;
      const all = Array.from(document.querySelectorAll<HTMLElement>('.wa-proposal-card[data-can-apply="1"]')).filter((card) => !batch || card.dataset.reviewBatch === batch);
      counter.textContent = `${all.filter((card) => card.classList.contains('accepted') || card.classList.contains('rejected')).length}/${all.length} 已处理`;
    });
  }

  function makeProposalButton(text: string, className: string, onClick: () => void): HTMLButtonElement {
    const button = document.createElement('button');
    button.className = `wa-proposal-btn ${className}`.trim();
    button.textContent = text;
    button.addEventListener('click', onClick);
    return button;
  }

  function makeProposalCard(proposal: Proposal, index: number, total: number): HTMLElement {
    if (!proposal.id) proposal = { ...proposal, id: `proposal-${proposalBatch}-${++proposalSequence}` };
    const card = document.createElement('div');
    card.className = 'wa-proposal-card';
    card.dataset.proposalId = proposal.id;
    card.dataset.index = String(index);
    card.dataset.reviewKey = `review-${reviewInstance}-${proposalBatch}-${++proposalSequence}`;
    card.dataset.reviewBatch = String(proposalBatch);
    const entry: ProposalEntry = { proposal, card, baseline: captureDocumentReviewContext(state), phase: 'candidate', batch: proposalBatch };
    proposalEntries.set(card.dataset.reviewKey, entry);
    const canApply = proposalCanApply(proposal);
    card.dataset.canApply = canApply ? '1' : '0';

    const header = document.createElement('div');
    header.className = 'wa-proposal-header';
    header.innerHTML = `<span class="wa-proposal-badge">修改建议 ${index + 1}${total > 1 ? '/' + total : ''}</span>`;

    const diffView = document.createElement('div');
    diffView.className = 'wa-proposal-diff';
    diffView.textContent = `${proposal.original_text || ''}\n→\n${proposal.proposed_text || ''}`;
    void loadDocumentReviewRuntime().then((review) => diffView.replaceChildren(review.renderDocumentDiff(proposal.original_text || '', proposal.proposed_text || ''))).catch(() => {});

    const rationaleText = getProposalRationaleText(proposal);
    const rationale = document.createElement('div');
    rationale.className = 'wa-proposal-rationale';
    if (rationaleText && rationaleText.length > 5) {
      rationale.innerHTML = `${lightbulbIcon} ${_escHtml(rationaleText.length > 150 ? rationaleText.substring(0, 150) + '…' : rationaleText)}`;
    }

    const actions = document.createElement('div');
    actions.className = 'wa-proposal-actions';
    if (proposal.original_text) {
      const locate = makeProposalButton('定位原文', 'locate', async () => {
        locate.disabled = true;
        try {
          const review = await loadDocumentReviewRuntime();
          const found = await review.locateReviewReceipt({ document_path: entry.baseline?.path, file_id: entry.baseline?.fileId,
            revision_before: entry.baseline?.revision, before_text: proposal.original_text, scope: proposal.scope });
          if (!found) showToast('当前版本无法可靠定位原文，请重新核对。', 'warning');
        } catch (error) { showToast(error instanceof Error ? error.message : String(error), 'error'); }
        finally { locate.disabled = false; }
      });
      actions.appendChild(locate);
    }

    if (canApply) {
      const acceptBtn = makeProposalButton('接受', 'accept', () => acceptProposal(proposal.id || '', acceptBtn));
      const rejectBtn = makeProposalButton('拒绝', 'reject', () => rejectProposal(proposal.id || '', rejectBtn));
      actions.appendChild(acceptBtn);
      actions.appendChild(rejectBtn);
    } else {
      const closeBtn = makeProposalButton('关闭', 'reject', () => rejectProposal(proposal.id || '', closeBtn));
      actions.appendChild(closeBtn);
    }

    card.appendChild(header);
    card.appendChild(diffView);
    const status = document.createElement('p'); status.className = 'wa-proposal-state'; status.setAttribute('role', 'status'); card.appendChild(status);
    if (rationaleText && rationaleText.length > 5) card.appendChild(rationale);
    card.appendChild(actions);
    const appliedHint = proposal.applied === true || ['accepted', 'applied', 'saved'].includes(String(proposal.status || '')) || receiptApplied(proposal.execution_receipt || proposal.receipt);
    const rawReceipt = proposal.execution_receipt || proposal.receipt || proposal;
    const receipt = documentReceiptRecord((rawReceipt?.value || rawReceipt)?.persisted === true ? 'ui_save' : 'ui_apply_edit', rawReceipt);
    if (appliedHint) {
      entry.receipt = proposal.execution_receipt || proposal.receipt || proposal;
      setProposalState(entry, receipt?.status === 'applied' || receipt?.status === 'saved' ? receipt.status : 'unconfirmed');
      if (receipt) appendDocumentReceipt(card, receipt);
    } else if (['unconfirmed', 'applying'].includes(String(proposal.status || ''))) setProposalState(entry, 'unconfirmed');
    else if (proposal.status === 'rejected') setProposalState(entry, 'rejected');
    else setProposalState(entry, proposal.status === 'failed' ? 'failed' : 'candidate');
    return card;
  }

  function makeProposalBatchBar(proposals: Proposal[]): HTMLElement {
    const bar = document.createElement('div');
    bar.className = 'wa-proposal-batch-bar';
    bar.dataset.reviewBatch = String(proposalBatch);
    const barBatch = proposalBatch;
    const actionableCount = proposals.filter(proposalCanApply).length;
    const targetIndex = state._aiTargetFileIdx;
    const targetFile = (targetIndex !== undefined && targetIndex >= 0 && targetIndex < (state._aiFileContext || []).length)
      ? state._aiFileContext![targetIndex]
      : null;
    const canDownload = actionableCount > 0 && targetFile && /\.(docx|txt|md)$/i.test(targetFile.name);

    const label = document.createElement('span');
    label.className = 'wa-proposal-batch-label';
    label.textContent = `共 ${proposals.length} 条修改建议`;
    bar.appendChild(label);

    const counter = document.createElement('span');
    counter.className = 'wa-proposal-batch-counter';
    counter.id = document.getElementById('wa-proposal-counter') ? `wa-proposal-counter-${proposalBatch}` : 'wa-proposal-counter';
    counter.textContent = `0/${actionableCount} 已处理`;
    bar.appendChild(counter);

    if (actionableCount > 0) {
      const acceptAllBtn = makeProposalButton('全部接受', 'accept small', () => batchAcceptAll(barBatch));
      bar.appendChild(acceptAllBtn);
    }

    const rejectAllBtn = makeProposalButton('全部拒绝', 'reject small', () => batchRejectAll(barBatch));
    bar.appendChild(rejectAllBtn);

    if (canDownload) {
      const downloadBtn = makeProposalButton(`应用并下载 ${targetFile!.name}`, 'download small', async () => {
        const entries = Array.from(proposalEntries.values()).filter((entry) => entry.batch === barBatch);
        if (entries.some((entry) => ['applying', 'applied', 'saved', 'unconfirmed'].includes(entry.phase))) {
          showToast('部分修改已经应用或状态未确认，请通过文档保存与下载，避免重复应用。', 'warning'); return;
        }
        const pending = entries.filter((entry) => ['candidate', 'failed'].includes(entry.phase) && proposalCanApply(entry.proposal)).map((entry) => entry.proposal);
        if (!pending.length) return;
        try { await getFeatureRegistry().downloadPatchedFile?.(pending); }
        catch (error) { showToast(error instanceof Error ? error.message : String(error), 'error'); }
      });
      downloadBtn.title = `将全部修改应用到目标文件并下载 ${targetFile!.name}`;
      bar.appendChild(downloadBtn);
    }

    return bar;
  }

  function handleProposals(data: { proposals?: Proposal[] }): void {
    const msgs = getMessagesElement();
    if (!msgs) return;
    const seen = new Set<string>();
    const proposals = (data && Array.isArray(data.proposals) ? data.proposals : []).filter((proposal) => {
      const key = proposal.id || JSON.stringify([proposal.original_text, proposal.proposed_text, proposal.tool_call, proposal.scope]);
      if (seen.has(key)) return false;
      seen.add(key); return true;
    }).map((proposal) => ({ ...proposal, id: proposal.id || `proposal-${proposalBatch + 1}-${++proposalSequence}` }));
    if (!proposals.length) return;
    state._activeProposals = proposals;
    proposalBatch += 1;
    for (const [key, entry] of proposalEntries) if (!entry.card.isConnected && !entry.inFlight) proposalEntries.delete(key);
    if (proposals.length > 1) msgs.appendChild(makeProposalBatchBar(proposals));
    proposals.forEach((proposal, index) => msgs.appendChild(makeProposalCard(proposal, index, proposals.length)));
    requestAnimationFrame(() => { msgs.scrollTop = msgs.scrollHeight; });
  }

  function findProposalCard(proposalId: string, btn: HTMLElement | null): HTMLElement | null {
    if (btn && typeof (btn as any).closest === 'function') {
      const nearest = (btn as any).closest('.wa-proposal-card');
      if (nearest) return nearest.dataset.proposalId === proposalId ? nearest : null;
    }
    return Array.from(document.querySelectorAll<HTMLElement>('.wa-proposal-card')).find((card) => card.dataset.proposalId === proposalId) || null;
  }

  async function acceptProposal(proposalId: string, btn: HTMLElement | null): Promise<void> {
    const entry = proposalEntry(proposalId, btn);
    if (!entry) return;
    if (entry.inFlight) return entry.inFlight;
    if (!['candidate', 'failed'].includes(entry.phase)) return;
    if (!proposalCanApply(entry.proposal)) {
      showToast('该结果仅供查看，不支持直接写入文档', 'info');
      return;
    }
    setProposalState(entry, 'applying');
    entry.inFlight = (async () => {
      try {
        const review = await loadDocumentReviewRuntime();
        const before = entry.baseline;
        const result = await review.applyProposalSafely({ state, proposal: entry.proposal, baseline: before, operationId: entry.card.dataset.reviewKey });
        const confirmed = result.status === 'applied' && result.receipt?.applied === true && result.receipt?.revision_before && result.receipt?.revision_after;
        setProposalState(entry, result.status === 'applied' && !confirmed ? 'unconfirmed' : result.status, confirmed ? result.reason : result.reason || '尚未收到完整应用回执。');
        if (confirmed) {
          entry.receipt = result.receipt; entry.proposal.execution_receipt = result.receipt; entry.proposal.applied = true;
          const receipt = documentReceiptRecord('ui_apply_edit', result.receipt); if (receipt) appendDocumentReceipt(entry.card, receipt);
          scheduleAutoSave({ skipDiskWrite: true });
          showToast('已应用修改，尚未保存', 'success');
          const after = captureDocumentReviewContext(state);
          if (sameReviewContext(after, result.context)) {
            for (const pending of proposalEntries.values()) {
              if (pending !== entry && pending.batch === entry.batch && ['candidate', 'failed'].includes(pending.phase) && sameReviewContext(pending.baseline, before)) {
                pending.baseline = after;
                if (pending.proposal.expected_revision && pending.proposal.expected_revision === before?.revision) pending.proposal.expected_revision = after?.revision;
              }
            }
          }
        } else {
          showToast(result.reason || '修改尚未得到确认，建议已保留', result.status === 'failed' ? 'error' : 'warning');
        }
      } catch (error) {
        const reason = error instanceof Error ? error.message : String(error);
        setProposalState(entry, 'failed', reason); showToast(reason, 'error');
      } finally { entry.inFlight = undefined; updateProposalCounter(); }
    })();
    return entry.inFlight;
  }

  function rejectProposal(proposalId: string, btn: HTMLElement | null): void {
    const entry = proposalEntry(proposalId, btn);
    if (!entry || !['candidate', 'failed'].includes(entry.phase)) return;
    setProposalState(entry, 'rejected');
    showToast('已拒绝修改', 'info');
    updateProposalCounter();
  }

  function modifyProposal(proposalId: string, btn: HTMLElement | null): void {
    const card = findProposalCard(proposalId, btn);
    if (!card) return;
    if (card.querySelector('.wa-proposal-modify-input')) return;

    const proposals = state._activeProposals || [];
    const proposal = proposals.find((entry) => entry.id === proposalId);
    if (!proposal) return;
    if (!proposalCanApply(proposal)) {
      showToast('该结果仅供查看，不支持继续修改并写回文档', 'info');
      return;
    }

    const inputWrap = document.createElement('div');
    inputWrap.className = 'wa-proposal-modify-input';

    const textarea = document.createElement('textarea');
    textarea.className = 'wa-proposal-modify-textarea';
    textarea.placeholder = '输入修改意见，如：语气再正式一些…';
    textarea.rows = 2;
    inputWrap.appendChild(textarea);

    const actions = document.createElement('div');
    actions.className = 'wa-proposal-modify-actions';
    const sendBtn = makeProposalButton('发送', 'accept small', () => submitModify(proposalId, sendBtn));
    const cancelBtn = makeProposalButton('取消', 'reject small', () => inputWrap.remove());
    actions.appendChild(sendBtn);
    actions.appendChild(cancelBtn);
    inputWrap.appendChild(actions);

    card.appendChild(inputWrap);
    textarea.focus();
  }

  function submitModify(proposalId: string, btn: HTMLElement | null): void {
    const card = btn && (btn as any).closest ? (btn as any).closest('.wa-proposal-card') : findProposalCard(proposalId, null);
    if (!card) return;
    const textarea = card.querySelector('.wa-proposal-modify-textarea') as HTMLTextAreaElement | null;
    const feedback = textarea ? textarea.value.trim() : '';
    if (!feedback) return;

    const entry = proposalEntry(proposalId, btn);
    if (!entry || !['candidate', 'failed'].includes(entry.phase)) return;
    const proposal = entry.proposal;
    const input = getUserInputElement();
    if (!input) return;

    const inputWrap = card.querySelector('.wa-proposal-modify-input');
    if (inputWrap) inputWrap.remove();
    setProposalState(entry, 'rejected');
    updateProposalCounter();

    const modifyPrompt = `请重新修改以下内容。\n原文：「${String(proposal.original_text || '')}」\n上次修改为：「${String(proposal.proposed_text || '')}」\n用户反馈：${feedback}`;
    input.value = modifyPrompt;

    state.pinnedSelection = createPinnedSelectionContext(proposal.original_text || '');
    sendMessage();
  }

  async function batchAcceptAll(batch = proposalBatch): Promise<void> {
    if (batchInFlight) return batchInFlight;
    batchInFlight = (async () => {
      for (const entry of proposalEntries.values()) {
        if (entry.batch === batch && ['candidate', 'failed'].includes(entry.phase) && entry.card.isConnected && proposalCanApply(entry.proposal)) await acceptProposal(entry.proposal.id || '', entry.card.querySelector('.wa-proposal-btn.accept'));
      }
    })();
    try { await batchInFlight; } finally { batchInFlight = null; }
  }

  function batchRejectAll(batch = proposalBatch): void {
    for (const entry of proposalEntries.values()) if (entry.batch === batch) rejectProposal(entry.proposal.id || '', entry.card.querySelector('.wa-proposal-btn.reject'));
  }

  function makeAIActionBar(snapshot: AiActionSnapshot): HTMLElement {
    const bar = document.createElement('div');
    bar.className = 'wa-ai-action-bar';
    bar.dataset.reviewOperation = `inline-${reviewInstance}-${++proposalSequence}`;
    actionBaselines.set(bar, captureDocumentReviewContext(state));

    const label = document.createElement('span');
    label.className = 'wa-ai-action-label';
    label.textContent = 'AI 回复了，如何处理？';
    bar.appendChild(label);

    const makeButton = (text: string, extraCls: string, mode: string) => {
      const button = document.createElement('button');
      button.className = 'wa-ai-action-btn' + (extraCls ? ' ' + extraCls : '');
      button.textContent = text;
      button.addEventListener('click', () => execWriteToDoc(mode, snapshot, bar));
      return button;
    };

    if (snapshot.pinnedSel) {
      bar.appendChild(makeButton('替换选区', 'primary', 'replace'));
      bar.appendChild(makeButton('插入到后面', '', 'append'));
    } else if (snapshot.toolCall) {
      bar.appendChild(makeButton('应用到文档', 'primary', 'replace'));
      bar.appendChild(makeButton('插入到末尾', '', 'append'));
    } else if (snapshot.outputMode && snapshot.outputMode !== 'chat') {
      bar.appendChild(makeButton('写入文档', 'primary', 'replace'));
      bar.appendChild(makeButton('插入到末尾', '', 'append'));
    } else {
      bar.appendChild(makeButton('插入到文档末尾', 'primary', 'append'));
    }
    bar.appendChild(makeButton('仅查看', 'muted', 'view'));
    return bar;
  }

  async function execWriteToDoc(mode: string, snapshot: AiActionSnapshot, bar: HTMLElement | null): Promise<void> {
    if (mode === 'view') { bar?.remove(); return; }
    if (bar && ['applying', 'applied', 'saved', 'unconfirmed'].includes(bar.dataset.status || '')) return;
    if (bar) { bar.dataset.status = 'applying'; bar.querySelectorAll<HTMLButtonElement>('button').forEach((button) => { button.disabled = true; }); }
    try {
      let msgEl: HTMLElement | null = bar ? (bar.previousElementSibling as HTMLElement | null) : null;
      while (msgEl && !msgEl.classList.contains('wa-msg')) {
        msgEl = msgEl.previousElementSibling as HTMLElement | null;
      }
      const rawText = (msgEl && msgEl.dataset.rawText) ? msgEl.dataset.rawText : (msgEl ? msgEl.textContent || '' : '');
      const toolCall = snapshot.toolCall;
      const selection = selectionContextText(snapshot.pinnedSel);
      const original = selection || toolCall?.original || '';
      const proposal: Proposal = toolCall ? { tool_call: { ...toolCall }, original_text: toolCall.original, proposed_text: toolCall.value }
        : original ? { original_text: original, proposed_text: mode === 'append' ? original + rawText : rawText }
          : { tool_call: { type: mode === 'append' ? 'insert_text' : 'replace_all', value: mode === 'append' ? '\n' + rawText : rawText } };
      if (toolCall?.original && mode === 'append') { proposal.tool_call!.value = toolCall.original + (toolCall.value || ''); proposal.proposed_text = proposal.tool_call!.value; }
      const review = await loadDocumentReviewRuntime();
      const result = await review.applyProposalSafely({ state, proposal, baseline: bar ? actionBaselines.get(bar) || null : captureDocumentReviewContext(state), operationId: bar?.dataset.reviewOperation || `inline-${Date.now()}` });
      if (bar) bar.dataset.status = result.status;
      if (result.status === 'applied' && result.receipt?.applied === true) {
        scheduleAutoSave({ skipDiskWrite: true }); showToast('已应用到编辑器，尚未保存', 'success');
        if (bar) { bar.replaceChildren(); const record = documentReceiptRecord('ui_apply_edit', result.receipt); if (record) appendDocumentReceipt(bar, record); }
      } else {
        if (bar) {
          const message = bar.querySelector('.wa-ai-action-error') || document.createElement('p'); message.className = 'wa-ai-action-error'; message.textContent = result.reason; bar.appendChild(message);
          bar.querySelectorAll<HTMLButtonElement>('button').forEach((button) => { button.disabled = result.status === 'unconfirmed'; });
        }
        showToast(result.reason || '尚未确认写入，结果已保留', 'error');
      }
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error); showToast(reason, 'error');
      if (bar) { bar.dataset.status = 'failed'; bar.querySelectorAll<HTMLButtonElement>('button').forEach((button) => { button.disabled = false; }); }
    }
  }

  async function applyAIResponse(mode: string, btn: HTMLElement | null): Promise<void> {
    const bar = btn && typeof (btn as any).closest === 'function' ? (btn as any).closest('.wa-ai-action-bar') : null;
    if (!bar) return;
    await execWriteToDoc(mode, {
      pinnedSel: state.lastPinnedSel,
      toolCall: state.pendingToolCall || undefined,
      outputMode: 'inline',
    }, bar);
    if (mode === 'view' || ['applied', 'saved'].includes(bar.dataset.status || '')) { state.pendingToolCall = null; state.lastPinnedSel = null; }
  }

  function normalizeArtifactResult(raw: any): ArtifactResult | null {
    const source = raw && raw.data && raw.data.artifact_result ? raw.data.artifact_result
      : (raw && raw.artifact_result ? raw.artifact_result : raw);
    if (!source || typeof source !== 'object') return null;
    return {
      task_id: String(source.task_id || '').trim(),
      title: String(source.title || '任务结果').trim(),
      status: String(source.status || 'running').trim(),
      summary: String(source.summary || '').trim(),
      artifacts: Array.isArray(source.artifacts) ? source.artifacts : [],
      changes: Array.isArray(source.changes) ? source.changes : [],
      sources: Array.isArray(source.sources) ? source.sources : [],
      logs: Array.isArray(source.logs) ? source.logs : [],
      actions: Array.isArray(source.actions) ? source.actions : [],
    };
  }

  function statusLabel(status: string): string {
    return fileTaskStatusLabel(status, '进行中');
  }

  function artifactTypeLabel(type: string): string {
    const value = String(type || '').toLowerCase();
    const labels: Record<string, string> = {
      docx: 'Word',
      pptx: 'PPT',
      xlsx: '表格',
      pdf: 'PDF',
      image: '图片',
      markdown: 'Markdown',
      text: '文本',
      data: '数据',
      diff: '变更',
    };
    return labels[value] || '文件';
  }

  function ensureArtifactPanel(): HTMLElement | null {
    let panel = document.getElementById('wa-artifact-panel');
    if (panel) return panel;
    panel = document.createElement('section');
    panel.id = 'wa-artifact-panel';
    panel.className = 'wa-artifact-panel';
    panel.hidden = true;
    const anchor = document.getElementById('wa-ai-messages');
    if (anchor && anchor.parentElement) {
      anchor.parentElement.insertBefore(panel, anchor);
    }
    return panel;
  }

  function tabButton(label: string, key: string, count: number, active: boolean): HTMLButtonElement {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = active ? 'is-active' : '';
    btn.dataset.artifactTab = key;
    btn.textContent = count > 0 ? `${label} ${count}` : label;
    return btn;
  }

  function renderArtifactFile(item: any): HTMLElement {
    const artifact = item && typeof item === 'object' ? item : {};
    const row = document.createElement('div');
    row.className = 'wa-artifact-row';

    const main = document.createElement('div');
    main.className = 'wa-artifact-row-main';
    const title = artifact.title || basename(artifact.path) || '任务产物';
    main.innerHTML = `
      <div class="wa-artifact-row-title">${_escHtml(title)}</div>
      <div class="wa-artifact-row-meta">${_escHtml(artifactTypeLabel(artifact.type))}${artifact.path ? ' · ' + _escHtml(artifact.path) : ''}</div>
    `;

    const actions = document.createElement('div');
    actions.className = 'wa-artifact-row-actions';
    if (artifact.path) {
      const openBtn = document.createElement('button');
      openBtn.type = 'button';
      openBtn.title = '在工作区打开';
      openBtn.textContent = '打开';
      openBtn.addEventListener('click', async () => {
        openBtn.disabled = true;
        try {
          if (typeof getFeatureRegistry().openRecentFile === 'function') await getFeatureRegistry().openRecentFile(artifact.path);
          else if (typeof getFeatureRegistry().openWorkspaceFile === 'function') await getFeatureRegistry().openWorkspaceFile(artifact.path.replace(/^workspace[\\/]/i, ''));
          else throw new Error('当前无法打开任务产物');
        } catch (error) { showToast(error instanceof Error ? error.message : String(error), 'error'); }
        finally { openBtn.disabled = false; }
      });
      actions.appendChild(openBtn);
    }
    if (artifact.path) {
      const download = document.createElement('a'); download.textContent = '下载'; download.download = basename(artifact.path);
      download.href = `/api/file/raw?path=${encodeURIComponent(artifact.path)}`; actions.appendChild(download);
    }
    const previewUrl = artifact.preview_url ? safeWebUrl(artifact.preview_url) : '';
    if (previewUrl) {
      const link = document.createElement('a');
      link.href = previewUrl;
      link.target = '_blank';
      link.rel = 'noopener';
      link.textContent = '预览';
      actions.appendChild(link);
    }

    row.appendChild(main);
    if (actions.childNodes.length) row.appendChild(actions);
    return row;
  }

  function renderChangeRow(item: any): HTMLElement {
    const change = item && typeof item === 'object' ? item : {};
    const row = document.createElement('div');
    row.className = 'wa-artifact-row';
    const kind = change.kind || 'update';
    row.innerHTML = `
      <div class="wa-artifact-row-main">
        <div class="wa-artifact-row-title">${_escHtml(change.summary || '文件变更')}</div>
        <div class="wa-artifact-row-meta">${_escHtml(kind)}${change.file ? ' · ' + _escHtml(change.file) : ''}${change.status ? ' · ' + _escHtml(change.status) : ''}</div>
        ${change.after_preview ? '<div class="wa-artifact-preview">' + _escHtml(change.after_preview) + '</div>' : ''}
      </div>
    `;
    return row;
  }

  function renderSourceRow(item: any): HTMLElement {
    const source = item && typeof item === 'object' ? item : {};
    const row = document.createElement('div');
    row.className = 'wa-artifact-row';
    const locator = source.locator ? ` · ${source.locator}` : '';
    row.innerHTML = `
      <div class="wa-artifact-row-main">
        <div class="wa-artifact-row-title">${_escHtml(source.title || source.file || source.url || '来源')}</div>
        <div class="wa-artifact-row-meta">${_escHtml((source.file || source.url || '') + locator)}</div>
        ${source.snippet ? '<div class="wa-artifact-preview">' + _escHtml(source.snippet) + '</div>' : ''}
      </div>
    `;
    const actions = document.createElement('div'); actions.className = 'wa-artifact-row-actions';
    if (source.file) {
      const open = document.createElement('button'); open.type = 'button'; open.textContent = '打开来源文件';
      open.addEventListener('click', async () => {
        open.disabled = true;
        try {
          const api = getFeatureRegistry();
          if (typeof api.openRecentFile === 'function') await api.openRecentFile(source.file);
          else if (typeof api.openWorkspaceFile === 'function') await api.openWorkspaceFile(String(source.file).replace(/^workspace[\\/]/i, ''));
          else throw new Error('当前无法打开来源文件');
          if (source.locator && typeof api.locateDocumentSource === 'function') await api.locateDocumentSource({ path: source.file, locator: source.locator, text: source.snippet || '' });
          else if (source.locator) showToast(`文件已打开；来源位置：${source.locator}`, 'info');
        } catch (error) { showToast(error instanceof Error ? error.message : String(error), 'error'); }
        finally { open.disabled = false; }
      });
      actions.appendChild(open);
    }
    const sourceUrl = source.url ? safeWebUrl(source.url) : '';
    if (sourceUrl) { const link = document.createElement('a'); link.href = sourceUrl; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = '查看来源'; actions.appendChild(link); }
    if (actions.childNodes.length) row.appendChild(actions);
    return row;
  }

  function renderLogRow(item: any): HTMLElement {
    const log = item && typeof item === 'object' ? item : {};
    const row = document.createElement('div');
    row.className = 'wa-artifact-log-row';
    (row as any).dataset.level = log.level || 'info';
    row.textContent = log.message || '';
    return row;
  }

  function renderArtifactTabBody(result: ArtifactResult, activeTab: string): HTMLElement {
    const body = document.createElement('div');
    body.className = 'wa-artifact-body';
    const lists: Record<string, any[]> = {
      artifacts: result.artifacts,
      changes: result.changes,
      sources: result.sources,
      logs: result.logs,
    };
    const items = lists[activeTab] || [];
    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'wa-artifact-empty';
      empty.textContent = '暂无内容';
      body.appendChild(empty);
      return body;
    }
    items.forEach((item) => {
      if (activeTab === 'artifacts') body.appendChild(renderArtifactFile(item));
      else if (activeTab === 'changes') body.appendChild(renderChangeRow(item));
      else if (activeTab === 'sources') body.appendChild(renderSourceRow(item));
      else body.appendChild(renderLogRow(item));
    });
    return body;
  }

  function renderArtifactResult(raw: any, renderOptions?: { activeTab?: string }): HTMLElement | null {
    const result = normalizeArtifactResult(raw);
    if (!result) return null;
    const panel = ensureArtifactPanel();
    if (!panel) return null;
    const options = renderOptions && typeof renderOptions === 'object' ? renderOptions : {};
    const allTabItems: Array<[string, string, number]> = [
      ['artifacts', '文件', result.artifacts.length],
      ['changes', '变更', result.changes.length],
      ['sources', '来源', result.sources.length],
      ['logs', '日志', result.logs.length],
    ];
    const tabItems = allTabItems.filter((item) => item[2] > 0);
    const availableTabKeys = tabItems.map((item) => item[0]);
    const requestedTab = String(options.activeTab || panel.dataset.activeTab || availableTabKeys[0] || 'artifacts').trim();
    const activeTab = availableTabKeys.includes(requestedTab) ? requestedTab : (availableTabKeys[0] || 'artifacts');
    panel.hidden = false;
    panel.dataset.status = result.status || 'running';
    panel.dataset.activeTab = activeTab;
    panel.innerHTML = '';

    const header = document.createElement('div');
    header.className = 'wa-artifact-header';
    header.innerHTML = `
      <div class="wa-artifact-title-group">
        <span class="wa-artifact-kicker">结果</span>
        <strong>${_escHtml(result.title)}</strong>
        ${result.summary ? '<span class="wa-artifact-summary">' + _escHtml(result.summary) + '</span>' : ''}
      </div>
      <div class="wa-artifact-head-actions">
        <span class="wa-artifact-status">${_escHtml(statusLabel(result.status))}</span>
        <button type="button" class="wa-artifact-close" title="收起结果面板">收起</button>
      </div>
    `;
    const closeBtn = header.querySelector('.wa-artifact-close');
    if (closeBtn) closeBtn.addEventListener('click', () => { panel.hidden = true; });
    panel.appendChild(header);

    if (tabItems.length > 1) {
      const tabs = document.createElement('div');
      tabs.className = 'wa-artifact-tabs';
      tabItems.forEach(([key, label, count]) => {
        const btn = tabButton(label, key, count, key === activeTab);
        btn.addEventListener('click', () => renderArtifactResult(result, { activeTab: key }));
        tabs.appendChild(btn);
      });
      panel.appendChild(tabs);
    }
    panel.appendChild(renderArtifactTabBody(result, activeTab));
    return panel;
  }

  // Cross-bundle compatibility boundary.
  registerFeatures({ renderArtifactResult });

  return {
    getProposalRationaleText,
    proposalCanApply,
    makeProposalCard,
    makeProposalBatchBar,
    updateProposalCounter,
    handleProposals,
    acceptProposal,
    rejectProposal,
    modifyProposal,
    submitModify,
    batchAcceptAll,
    batchRejectAll,
    makeAIActionBar,
    execWriteToDoc,
    applyAIResponse,
    renderArtifactResult,
  };
}
