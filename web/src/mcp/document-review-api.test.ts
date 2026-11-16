import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { Schema } from '../../tiptap-editor/node_modules/prosemirror-model';
import { EditorState, TextSelection } from '../../tiptap-editor/node_modules/prosemirror-state';
import { getFeatureRegistry } from '../shared/feature-registry';
import { _applyScopedDocumentEdit, _saveScopedDocument } from './frontend-observer-document-actions';
import { KotoTextEditor } from '../editors/text-editor';

let pm: any; let state: any; let serial = 0;
const hash = '0'.repeat(64);
const schema = new Schema({ nodes: { doc: { content: 'paragraph+' }, paragraph: { content: 'text*' }, text: {} }, marks: { bold: {} } });
const features = () => getFeatureRegistry();
function options(extra: Record<string, any> = {}) {
  return { document_path: 'semantic.docx', file_id: 'file-semantic', operation_id: `review-${++serial}`, ...extra };
}
beforeEach(() => {
  const doc = schema.node('doc', null, [schema.node('paragraph', null, [schema.text('Old ', [schema.mark('bold')]), schema.text('link')]), schema.node('paragraph', null, schema.text('Second 😀'))]);
  pm = { state: EditorState.create({ doc }), view: { dispatch: vi.fn((transaction) => { pm.state = pm.state.apply(transaction); }) }, commands: { setTextSelection: vi.fn(() => true), focus: vi.fn() } };
  pm.commands.setTextSelection = vi.fn(({ from, to }) => { pm.view.dispatch(pm.state.tr.setSelection(TextSelection.create(pm.state.doc, from, to))); return true; });
  state = { fileId: 'file-semantic', fileType: 'docx', activeTabPath: 'semantic.docx', sourceSha256: hash, openTabs: [{ path: 'semantic.docx', sourceSha256: hash }] };
  features()._inspectWorkspaceRuntime = () => ({ state, activeEditor: { editor: pm } });
  features().scheduleAutoSave = vi.fn();
  features().isDocumentSaveInProgress = () => false;
});
afterEach(() => vi.unstubAllGlobals());

describe('document review public receipt boundary', () => {
  it('applies a multi-block edit once and safely undoes its actual transaction', () => {
    const before = pm.state.doc;
    const read = features().getDocumentReviewContext();
    const request = options({ expected_revision: read.revision, anchor_text: 'Old link\nSecond 😀', replacement: 'New link\nNext 😀' });
    const receipt = features().applyDocumentReviewEdit(request);
    expect(receipt).toMatchObject({ applied: true, persisted: false, verified: true, before_text: request.anchor_text, after_text: request.replacement });
    expect(receipt.undo_token).toBeTruthy(); expect(receipt.revision_after).not.toBe(read.revision);
    expect(features().applyDocumentReviewEdit(request)).toEqual(receipt); expect(pm.view.dispatch).toHaveBeenCalledTimes(1);
    const undoRequest = options({ expected_revision: receipt.revision_after, undo_token: receipt.undo_token });
    const undone = features().undoDocumentReviewEdit(undoRequest);
    expect(undone.applied).toBe(true); expect(undone.persisted).toBe(false); expect(pm.state.doc.eq(before)).toBe(true);
    expect(features().undoDocumentReviewEdit(undoRequest)).toEqual(undone); expect(pm.view.dispatch).toHaveBeenCalledTimes(2);
  });

  it('refuses stale undo, absent tokens and operation-ID reuse without dispatch', () => {
    const read = features().getDocumentReviewContext(); const request = options({ expected_revision: read.revision, anchor_text: 'Old', replacement: 'New' });
    const receipt = features().applyDocumentReviewEdit(request);
    expect(() => features().applyDocumentReviewEdit({ ...request, replacement: 'Different' })).toThrow('reused');
    pm.view.dispatch(pm.state.tr.insertText('user', 1)); const before = pm.state.doc;
    expect(() => features().undoDocumentReviewEdit(options({ expected_revision: receipt.revision_after, undo_token: receipt.undo_token }))).toThrow('revision conflict');
    expect(() => features().undoDocumentReviewEdit(options({ expected_revision: features().getDocumentReviewContext().revision, undo_token: 'unknown' }))).toThrow('unavailable');
    expect(pm.state.doc.eq(before)).toBe(true);
  });

  it('requires an actual editor selection API before claiming location', () => {
    const context = features().getDocumentReviewContext(); const request = options({ expected_revision: context.revision, anchor_text: 'Old' });
    expect(features().locateDocumentReviewEdit(request).located).toBe(true);
    delete pm.commands.setTextSelection;
    expect(() => features().locateDocumentReviewEdit(request)).toThrow('cannot locate');
  });

  it('marks preflight failures as unstarted and dispatch failures as potentially applied', () => {
    const context = features().getDocumentReviewContext();
    try { _applyScopedDocumentEdit({ id: 'preflight', action: 'ui_apply_edit', options: options({ expected_revision: 'stale', anchor_text: 'Old', replacement: 'New' }) }); throw new Error('expected failure'); }
    catch (error: any) { expect(error.execution_started).toBe(false); }
    pm.view.dispatch = () => { throw new Error('editor disconnected while dispatching'); };
    try { _applyScopedDocumentEdit({ id: 'started', action: 'ui_apply_edit', options: options({ expected_revision: context.revision, anchor_text: 'Old', replacement: 'New' }) }); throw new Error('expected failure'); }
    catch (error: any) { expect(error.execution_started).toBe(true); }
  });

  it('keeps save failures after submission unknown and refuses switched documents', async () => {
    const context = features().getDocumentReviewContext();
    features().saveFileWithReceipt = vi.fn(async () => { throw new Error('save response lost'); });
    const action: any = { id: 'save', action: 'ui_save', options: options({ expected_revision: context.revision, expected_source_sha256: hash }) };
    await expect(_saveScopedDocument(action)).rejects.toMatchObject({ execution_started: true });
    state.activeTabPath = 'switched.docx';
    await expect(_saveScopedDocument(action)).rejects.toMatchObject({ execution_started: false });
    expect(features().saveFileWithReceipt).toHaveBeenCalledTimes(1);
  });

  it('keeps semantic text input dirty-only while real user input retains autosave', () => {
    document.body.innerHTML = '<div id="wa-text-editor"><textarea id="wa-text-content">Old paragraph</textarea></div>';
    state.fileType = 'text';
    const editor = new KotoTextEditor({} as any, 'text');
    features()._inspectWorkspaceRuntime = () => ({ state, activeEditor: editor });
    const context = features().getDocumentReviewContext();
    features().applyDocumentReviewEdit(options({ expected_revision: context.revision, anchor_text: 'Old', replacement: 'New' }));
    expect(features().scheduleAutoSave.mock.calls.every((call: any[]) => call[0]?.skipDiskWrite === true)).toBe(true);
    features().scheduleAutoSave.mockClear();
    document.getElementById('wa-text-content')!.dispatchEvent(new InputEvent('input', { bubbles: true }));
    expect(features().scheduleAutoSave).toHaveBeenCalledWith();
    editor.destroy();
  });

  it('does not enter a semantic mutation while a prior save is in progress', () => {
    const context = features().getDocumentReviewContext(); const original = pm.state.doc;
    features().isDocumentSaveInProgress = () => true;
    expect(() => features().applyDocumentReviewEdit(options({ expected_revision: context.revision, anchor_text: 'Old', replacement: 'New' }))).toThrow('currently saving');
    expect(pm.state.doc.eq(original)).toBe(true); expect(pm.view.dispatch).not.toHaveBeenCalled();
  });
});
