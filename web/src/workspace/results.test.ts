import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getFeatureRegistry } from '../shared/feature-registry';
import { createWorkspaceAiResultsRuntime } from './results';
import { applyProposalSafely, undoReviewReceipt, locateReviewReceipt } from './document-review-actions';
import { renderDocumentDiff } from './document-review-diff';

let content: string;
let state: any;
let save: ReturnType<typeof vi.fn>;
let toast: ReturnType<typeof vi.fn>;
let runtime: ReturnType<typeof createWorkspaceAiResultsRuntime>;
beforeEach(() => {
  for (const key of Object.keys(getFeatureRegistry())) delete getFeatureRegistry()[key];
  getFeatureRegistry().documentReviewRuntime = { applyProposalSafely, undoReviewReceipt, locateReviewReceipt, renderDocumentDiff };
  document.body.innerHTML = '<div id="wa-ai-messages"></div>';
  content = 'Original paragraph';
  state = { fileId: 'file-one', fileType: 'text', activeTabPath: 'report.txt', activeEditor: {
    getContent: () => content, serialize: () => content,
    applyToolCall: vi.fn((command) => { content = content.replace(command.original, command.value); }),
  } };
  save = vi.fn(); toast = vi.fn();
  runtime = createWorkspaceAiResultsRuntime({ state, scheduleAutoSave: save, showToast: toast });
});
function proposals(list: any[] = [{ id: 'one', original_text: 'Original', proposed_text: 'Updated' }]): HTMLElement {
  runtime.handleProposals({ proposals: list }); return document.querySelector('.wa-proposal-card')!;
}

describe('proposal acceptance uses actual editing receipts', () => {
  it('accepts once only after exact editor changes, and never labels it saved', async () => {
    const card = proposals(); await runtime.acceptProposal('one', card.querySelector('.accept'));
    expect(card.classList.contains('accepted')).toBe(true); expect(card.dataset.status).toBe('applied');
    expect(card.textContent).toContain('尚未保存'); expect(save).toHaveBeenCalledTimes(1);
    await runtime.acceptProposal('one', card.querySelector('.accept')); expect(state.activeEditor.applyToolCall).toHaveBeenCalledTimes(1);
  });
  it.each(['missing', 'throw', 'false', 'no-change'])('keeps the proposal and does not save on %s', async (kind) => {
    if (kind === 'missing') state.activeEditor = null;
    else state.activeEditor.applyToolCall = vi.fn(async () => { if (kind === 'throw') throw new Error('editor rejected'); return kind === 'false' ? false : undefined; });
    const card = proposals(); await runtime.acceptProposal('one', card.querySelector('.accept'));
    expect(card.isConnected).toBe(true); expect(card.classList.contains('accepted')).toBe(false); expect(save).not.toHaveBeenCalled();
    expect(card.dataset.status).toBe(kind === 'no-change' ? 'unconfirmed' : 'failed');
  });
  it('awaits async apply and coalesces repeated accept clicks', async () => {
    let finish!: () => void;
    state.activeEditor.applyToolCall = vi.fn(() => new Promise<void>((resolve) => { finish = () => { content = 'Updated paragraph'; resolve(); }; }));
    const card = proposals(); const first = runtime.acceptProposal('one', card.querySelector('.accept'));
    await Promise.resolve(); await Promise.resolve();
    const second = runtime.acceptProposal('one', card.querySelector('.accept'));
    expect(card.dataset.status).toBe('applying'); expect(card.classList.contains('accepted')).toBe(false); expect(save).not.toHaveBeenCalled();
    finish(); await Promise.all([first, second]); expect(state.activeEditor.applyToolCall).toHaveBeenCalledTimes(1); expect(save).toHaveBeenCalledTimes(1);
  });
  it('sequences batches, ignores duplicate entries and concurrent batch clicks', async () => {
    content = 'Original paragraph';
    proposals([{ id: 'one', original_text: 'Original', proposed_text: 'Updated' }, { id: 'one', original_text: 'Original', proposed_text: 'Updated' }, { id: 'two', original_text: 'paragraph', proposed_text: 'section' }]);
    await Promise.all([runtime.batchAcceptAll(), runtime.batchAcceptAll()]);
    expect(content).toBe('Updated section'); expect(document.querySelectorAll('.wa-proposal-card')).toHaveLength(2);
    expect(state.activeEditor.applyToolCall).toHaveBeenCalledTimes(2); expect(save).toHaveBeenCalledTimes(2);
  });
  it('never offers an already applied tool receipt as a fresh candidate', async () => {
    const card = proposals([{ id: 'done', original_text: 'Old', proposed_text: 'New', receipt: { applied: true, revision_before: 'v1', revision_after: 'v2' } }]);
    expect(card.querySelector('.accept')).toBeNull(); await runtime.batchAcceptAll(); expect(save).not.toHaveBeenCalled();
    expect(state.activeEditor.applyToolCall).not.toHaveBeenCalled();
  });
  it('retains the applied receipt when proposals are rendered again from owned state', async () => {
    const card = proposals(); await runtime.acceptProposal('one', card.querySelector('.accept'));
    const retained = state._activeProposals;
    expect(retained[0].applied).toBe(true); expect(retained[0].execution_receipt.revision_after).toBeTruthy();
    document.getElementById('wa-ai-messages')!.replaceChildren(); runtime.handleProposals({ proposals: retained });
    await runtime.batchAcceptAll(); expect(state.activeEditor.applyToolCall).toHaveBeenCalledTimes(1);
    expect(document.querySelector('.wa-proposal-card .accept')).toBeNull();
  });
  it('keeps inline results actionable when an async write is rejected', async () => {
    state.activeEditor.applyToolCall = vi.fn(async () => false);
    const message = document.createElement('div'); message.className = 'wa-msg'; message.dataset.rawText = 'Updated';
    const bar = runtime.makeAIActionBar({ pinnedSel: 'Original' }); document.body.append(message, bar);
    await runtime.execWriteToDoc('replace', { pinnedSel: 'Original' }, bar);
    expect(bar.isConnected).toBe(true); expect(bar.dataset.status).toBe('failed'); expect(save).not.toHaveBeenCalled();
  });
});
