import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Schema } from '../../tiptap-editor/node_modules/prosemirror-model';
import { EditorState } from '../../tiptap-editor/node_modules/prosemirror-state';
import '../mcp/frontend-observer-document-actions';
import { getFeatureRegistry } from '../shared/feature-registry';
import { createWorkspaceAiResultsRuntime } from './results';
import { applyProposalSafely, undoReviewReceipt, locateReviewReceipt } from './document-review-actions';
import { renderDocumentDiff } from './document-review-diff';

const features = getFeatureRegistry();
const semanticApi = Object.fromEntries(['getDocumentReviewContext', 'applyDocumentReviewEdit', 'undoDocumentReviewEdit', 'locateDocumentReviewEdit'].map((name) => [name, features[name]]));
let state: any;
let pm: any;
let save: ReturnType<typeof vi.fn>;
beforeEach(() => {
  for (const key of Object.keys(features)) delete features[key];
  Object.assign(features, semanticApi);
  document.body.innerHTML = '<div id="wa-ai-messages"></div>';
  const schema = new Schema({
    nodes: { doc: { content: 'paragraph+' }, paragraph: { content: 'text*', group: 'block' }, text: { group: 'inline' } }, marks: { strong: {} },
  });
  const doc = schema.node('doc', null, [
    schema.node('paragraph', null, [schema.text('Old first', [schema.mark('strong')])]),
    schema.node('paragraph', null, [schema.text('Second paragraph')]),
  ]);
  pm = { state: EditorState.create({ doc }), view: { focus: vi.fn(), dispatch: vi.fn((transaction) => { pm.state = pm.state.apply(transaction); }) } };
  const editor = { editor: pm, serialize: () => pm.state.doc.toJSON(), getContent: () => pm.state.doc.toJSON(), applyToolCall: vi.fn(() => { throw new Error('unsafe legacy editor must not be called'); }) };
  state = { fileType: 'docx', fileId: 'docx-one', activeTabPath: 'report.docx', wsSourcePath: 'report.docx', activeEditor: editor,
    openTabs: [{ path: 'report.docx', modified: false, sourceSha256: '0'.repeat(64) }] };
  features._inspectWorkspaceRuntime = () => ({ state, activeEditor: editor });
  features.scheduleAutoSave = vi.fn();
  features.documentReviewRuntime = { applyProposalSafely, undoReviewReceipt, locateReviewReceipt, renderDocumentDiff };
  save = vi.fn();
});

describe('proposal UI uses the actual protected DOCX edit bridge', () => {
  it('applies multiple paragraphs in one native transaction, preserves formatting and undoes by protected token', async () => {
    const runtime = createWorkspaceAiResultsRuntime({ state, scheduleAutoSave: save });
    runtime.handleProposals({ proposals: [{ id: 'multi', original_text: 'Old first\nSecond paragraph', proposed_text: 'New first\nUpdated paragraph' }] });
    const card = document.querySelector<HTMLElement>('.wa-proposal-card')!;
    await runtime.acceptProposal('multi', card.querySelector('.accept'));
    expect(card.dataset.status).toBe('applied'); expect(card.classList.contains('accepted')).toBe(true);
    expect(pm.state.doc.childCount).toBe(2); expect(pm.view.dispatch).toHaveBeenCalledTimes(1);
    expect(pm.state.doc.firstChild.textContent).toBe('New first');
    expect(pm.state.doc.firstChild.firstChild.marks[0].type.name).toBe('strong');
    const receipt = state._activeProposals[0].execution_receipt;
    expect(receipt.undo_token).toBeTruthy(); expect(receipt.persisted).toBe(false);
    const reverted = await undoReviewReceipt(state, receipt);
    expect(reverted.status).toBe('applied'); expect(pm.state.doc.firstChild.textContent).toBe('Old first');
    expect(pm.state.doc.child(1).textContent).toBe('Second paragraph');
    expect(pm.state.doc.firstChild.firstChild.marks[0].type.name).toBe('strong');
    expect(state.activeEditor.applyToolCall).not.toHaveBeenCalled();
  });

  it('preserves later author edits and refuses stale receipt undo', async () => {
    const runtime = createWorkspaceAiResultsRuntime({ state, scheduleAutoSave: save });
    runtime.handleProposals({ proposals: [{ id: 'one', original_text: 'Old first', proposed_text: 'New first' }] });
    await runtime.acceptProposal('one', document.querySelector('.wa-proposal-card .accept'));
    const receipt = state._activeProposals[0].execution_receipt;
    pm.state = pm.state.apply(pm.state.tr.insertText('Author note ', 1));
    const result = await undoReviewReceipt(state, receipt);
    expect(result.status).toBe('failed'); expect(pm.state.doc.firstChild.textContent).toBe('Author note New first');
  });
});
