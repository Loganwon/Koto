import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getFeatureRegistry } from '../shared/feature-registry';
import { captureDocumentReviewContext } from './document-review-context';
import { applyProposalSafely, undoReviewReceipt } from './document-review-actions';
import { documentDiffParts, renderDocumentDiff } from './document-review-diff';

let content: string;
let state: any;
beforeEach(() => {
  for (const key of Object.keys(getFeatureRegistry())) delete getFeatureRegistry()[key];
  content = 'Original paragraph';
  state = { fileId: 'file-one', activeTabPath: 'report.txt', fileType: 'text', activeEditor: {
    getContent: () => content, serialize: () => content,
    applyToolCall: vi.fn((command) => { content = content.replace(command.original, command.value); }),
  } };
});
afterEach(() => vi.restoreAllMocks());
const proposal = { original_text: 'Original', proposed_text: 'Updated' };

describe('verified proposal application', () => {
  it('confirms legacy void-returning editors only after exact content readback', async () => {
    const result = await applyProposalSafely({ state, proposal, baseline: captureDocumentReviewContext(state), operationId: 'edit-one' });
    expect(result.status).toBe('applied'); expect(content).toBe('Updated paragraph');
    expect(result.receipt.persisted).toBe(false); expect(result.receipt.revision_after).not.toBe(result.receipt.revision_before);
    expect(result.receipt.revision_after.length).toBeLessThan(100);
  });
  it.each([false, undefined])('never confirms an editor that returns %s without applying', async (returned) => {
    state.activeEditor.applyToolCall = vi.fn(async () => returned);
    const result = await applyProposalSafely({ state, proposal, baseline: captureDocumentReviewContext(state), operationId: 'no-change' });
    expect(result.status).toBe(returned === false ? 'failed' : 'unconfirmed'); expect(content).toBe('Original paragraph');
  });
  it('retains unknown state when a handler changes content and then fails', async () => {
    state.activeEditor.applyToolCall = vi.fn(async () => { content = 'Updated paragraph'; throw new Error('receipt failed'); });
    const result = await applyProposalSafely({ state, proposal, baseline: captureDocumentReviewContext(state), operationId: 'partial' });
    expect(result.status).toBe('unconfirmed'); expect(result.reason).toBe('receipt failed');
  });
  it('honors a native started-but-unconfirmed failure even without visible changes', async () => {
    state.activeEditor.applyToolCall = vi.fn(async () => { throw Object.assign(new Error('confirmation lost'), { execution_started: true }); });
    const result = await applyProposalSafely({ state, proposal, baseline: captureDocumentReviewContext(state), operationId: 'unknown-started' });
    expect(result.status).toBe('unconfirmed');
  });
  it('does not turn an explicitly unverified mutation into a confirmed application', async () => {
    state.activeEditor.applyToolCall = vi.fn(async () => { content = 'Updated paragraph'; return { applied: true, verified: false, reason: 'format verification failed' }; });
    const result = await applyProposalSafely({ state, proposal, baseline: captureDocumentReviewContext(state), operationId: 'unverified' });
    expect(result.status).toBe('unconfirmed'); expect(result.reason).toBe('format verification failed');
  });
  it('rejects changed versions and ambiguous anchors before execution', async () => {
    const baseline = captureDocumentReviewContext(state); content = 'Author changed it';
    expect((await applyProposalSafely({ state, proposal, baseline, operationId: 'conflict' })).status).toBe('failed');
    content = 'Original Original';
    expect((await applyProposalSafely({ state, proposal, baseline: captureDocumentReviewContext(state), operationId: 'ambiguous' })).status).toBe('failed');
    expect(state.activeEditor.applyToolCall).not.toHaveBeenCalled();
  });
  it('preserves a complete deletion receipt including the empty replacement', async () => {
    const result = await applyProposalSafely({ state, proposal: { original_text: 'Original', proposed_text: '' }, baseline: captureDocumentReviewContext(state), operationId: 'delete' });
    expect(result.status).toBe('applied'); expect(result.receipt.after_text).toBe('');
  });
  it('refuses blind undo without a protected native undo API', async () => {
    const context = captureDocumentReviewContext(state)!;
    const result = await undoReviewReceipt(state, { revision_after: context.revision, document_path: context.path, file_id: context.fileId, inverse_edits: [] });
    expect(result.status).toBe('failed'); expect(content).toBe('Original paragraph');
  });
  it('checks the exact current revision before invoking a native undo token', async () => {
    const features = getFeatureRegistry();
    features.getDocumentReviewContext = () => ({ document_path: 'report.txt', file_id: 'file-one', revision: content });
    features.undoDocumentReviewEdit = vi.fn(async () => { content = 'Original paragraph'; return { applied: true, revision_after: content }; });
    content = 'Updated paragraph';
    const receipt = { document_path: 'report.txt', file_id: 'file-one', revision_after: content, undo_token: 'protected-token' };
    content = 'Later author edit';
    expect((await undoReviewReceipt(state, receipt)).status).toBe('failed');
    expect(features.undoDocumentReviewEdit).not.toHaveBeenCalled();
    content = 'Updated paragraph';
    expect((await undoReviewReceipt(state, receipt)).status).toBe('applied');
    expect(content).toBe('Original paragraph');
  });
});

describe('complete word and character differences', () => {
  it('round-trips complete long content and marks Chinese words/emoji safely', () => {
    const before = '完整'.repeat(5000) + '旧词😀安全'; const after = '完整'.repeat(5000) + '新词😁安全';
    const parts = documentDiffParts(before, after);
    expect(parts.filter((part) => part.kind !== 'add').map((part) => part.text).join('')).toBe(before);
    expect(parts.filter((part) => part.kind !== 'remove').map((part) => part.text).join('')).toBe(after);
    const view = renderDocumentDiff('<script>old</script>', '<img src=x onerror=alert(1)>new');
    expect(view.querySelector('script,img')).toBeNull(); expect(view.querySelector('ins')).not.toBeNull();
  });
});
