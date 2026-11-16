import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { getFeatureRegistry } from '../shared/feature-registry';
import { JSDOM } from 'jsdom';
import { _readScopedDocument, _applyScopedDocumentEdit, _saveScopedDocument } from './frontend-observer-document-actions';
import { _executeFrontendActionOnce, type FrontendAction } from './frontend-observer';
import { Schema } from '../../tiptap-editor/node_modules/prosemirror-model';
import { EditorState } from '../../tiptap-editor/node_modules/prosemirror-state';

let state: Record<string, any>;
const sourceHash = '0'.repeat(64);
let serial = 0;

function action(name: FrontendAction['action'], options: Record<string, unknown> = {}): FrontendAction {
  serial += 1;
  return { id: `test-action-${serial}`, action: name, options: { document_path: 'report.txt', file_id: 'file123', ...options } };
}

beforeEach(() => {
  vi.stubGlobal('localStorage', new JSDOM('', { url: 'http://localhost' }).window.localStorage);
  document.body.innerHTML = '<textarea id="wa-text-content">Old paragraph</textarea>';
  state = {
    fileId: 'file123', fileType: 'text', activeTabPath: 'report.txt', wsSourcePath: 'report.txt', sourceSha256: sourceHash,
    openTabs: [{ path: 'report.txt', fileId: 'file123', modified: false, sourceSha256: sourceHash }],
  };
  const features = getFeatureRegistry();
  features._inspectWorkspaceRuntime = () => ({ state, activeEditor: { getContent: () => (document.getElementById('wa-text-content') as HTMLTextAreaElement).value } });
  features.scheduleAutoSave = vi.fn(() => { state.openTabs[0].modified = true; });
  features.saveFileWithReceipt = vi.fn(async () => ({ file_id: 'file123', persisted: true, src_written: true, verified: true, source_sha256: '07'.repeat(32), unsaved_changes: false }));
  vi.stubGlobal('crypto', { subtle: { digest: vi.fn(async () => new Uint8Array(32).fill(7).buffer) } });
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer })));
});

afterEach(() => vi.unstubAllGlobals());

describe('scoped semantic document actions', () => {
  it('reads the live document and edits only an exact current revision', () => {
    const context = _readScopedDocument(action('ui_read_context'));
    expect((context.content as any).text).toBe('Old paragraph');
    expect(context.source_sha256).toBe(sourceHash);
    const edited = _applyScopedDocumentEdit(action('ui_apply_edit', { expected_revision: context.revision, anchor_text: 'Old', replacement: 'New' }));
    expect(edited.applied).toBe(true);
    expect(edited.persisted).toBe(false);
    expect(edited.revision_after).not.toBe(context.revision);
    expect((document.getElementById('wa-text-content') as HTMLTextAreaElement).value).toBe('New paragraph');
  });

  it('does not overwrite a user edit made after the model read', () => {
    const context = _readScopedDocument(action('ui_read_context'));
    (document.getElementById('wa-text-content') as HTMLTextAreaElement).value = 'User changed it';
    expect(() => _applyScopedDocumentEdit(action('ui_apply_edit', { expected_revision: context.revision, anchor_text: 'Old', replacement: 'New' }))).toThrow('revision conflict');
    expect((document.getElementById('wa-text-content') as HTMLTextAreaElement).value).toBe('User changed it');
  });

  it('refuses switched documents and ambiguous anchors', () => {
    state.activeTabPath = 'different.txt';
    expect(() => _readScopedDocument(action('ui_read_context'))).toThrow('identity conflict');
    state.activeTabPath = 'report.txt';
    (document.getElementById('wa-text-content') as HTMLTextAreaElement).value = 'Old Old';
    const context = _readScopedDocument(action('ui_read_context'));
    expect(() => _applyScopedDocumentEdit(action('ui_apply_edit', { expected_revision: context.revision, anchor_text: 'Old', replacement: 'New' }))).toThrow('ambiguous');
    _applyScopedDocumentEdit(action('ui_apply_edit', { expected_revision: context.revision, anchor_text: 'Old', replacement: 'New', anchor_occurrence: 2 }));
    expect((document.getElementById('wa-text-content') as HTMLTextAreaElement).value).toBe('Old New');
  });

  it('executes a duplicate action only once', async () => {
    const context = _readScopedDocument(action('ui_read_context'));
    const edit = action('ui_apply_edit', { expected_revision: context.revision, anchor_text: 'Old', replacement: 'New' });
    const [first, duplicate] = await Promise.all([_executeFrontendActionOnce(edit), _executeFrontendActionOnce(edit)]);
    expect(first.ok).toBe(true);
    expect(duplicate).toEqual(first);
    expect(getFeatureRegistry().scheduleAutoSave).toHaveBeenCalledTimes(1);
  });

  it('never executes an expired edit', async () => {
    const context = _readScopedDocument(action('ui_read_context'));
    const edit = { ...action('ui_apply_edit', { expected_revision: context.revision, anchor_text: 'Old', replacement: 'New' }), expires_at: Date.now() / 1000 - 1 };
    expect((await _executeFrontendActionOnce(edit)).ok).toBe(false);
    expect(getFeatureRegistry().scheduleAutoSave).not.toHaveBeenCalled();
  });

  it('applies a DOCX edit through a real ProseMirror transaction and preserves formatting', () => {
    const schema = new Schema({
      nodes: { doc: { content: 'paragraph+' }, paragraph: { content: 'text*', group: 'block' }, text: { group: 'inline' } },
      marks: { strong: {} },
    });
    const doc = schema.node('doc', null, [schema.node('paragraph', null, [schema.text('Old Old', [schema.mark('strong')])])]);
    const pm: any = { state: EditorState.create({ doc }), view: { focus: vi.fn(), dispatch: vi.fn((transaction) => { pm.state = pm.state.apply(transaction); }) } };
    state.fileType = 'docx';
    getFeatureRegistry()._inspectWorkspaceRuntime = () => ({ state, activeEditor: { editor: pm } });
    const context = _readScopedDocument(action('ui_read_context'));
    const receipt = _applyScopedDocumentEdit(action('ui_apply_edit', { expected_revision: context.revision, anchor_text: 'Old', replacement: 'New', anchor_occurrence: 2 }));
    expect(pm.state.doc.textContent).toBe('Old New');
    expect(pm.state.doc.firstChild.firstChild.marks[0].type.name).toBe('strong');
    expect(receipt.revision_after).not.toBe(context.revision);
  });

  it('detects DOCX formatting changes even when text stays the same', () => {
    const schema = new Schema({ nodes: { doc: { content: 'paragraph+' }, paragraph: { content: 'text*' }, text: {} }, marks: { strong: {} } });
    const doc = schema.node('doc', null, [schema.node('paragraph', null, [schema.text('Old paragraph')])]);
    const pm: any = { state: EditorState.create({ doc }), view: { focus: vi.fn(), dispatch: vi.fn() } };
    state.fileType = 'docx';
    getFeatureRegistry()._inspectWorkspaceRuntime = () => ({ state, activeEditor: { editor: pm } });
    const context = _readScopedDocument(action('ui_read_context'));
    pm.state = pm.state.apply(pm.state.tr.addMark(1, 4, schema.mark('strong')));
    expect(() => _applyScopedDocumentEdit(action('ui_apply_edit', { expected_revision: context.revision, anchor_text: 'Old', replacement: 'New' }))).toThrow('revision conflict');
    expect(pm.state.doc.textContent).toBe('Old paragraph');
  });

  it('requires a strict save receipt and reads back actual saved bytes', async () => {
    const context = _readScopedDocument(action('ui_read_context'));
    const receipt = await _saveScopedDocument(action('ui_save', { expected_revision: context.revision, expected_source_sha256: sourceHash }));
    expect(receipt.raw_sha256).toBe('07'.repeat(32));
    expect(getFeatureRegistry().saveFileWithReceipt).toHaveBeenCalledWith({ expected_source_sha256: sourceHash });
  });

  it('does not attempt save when an original browser file changed externally', async () => {
    state.openTabs[0].fsHandle = { getFile: async () => ({ arrayBuffer: async () => new Uint8Array([9]).buffer }) };
    const context = _readScopedDocument(action('ui_read_context'));
    await expect(_saveScopedDocument(action('ui_save', { expected_revision: context.revision, expected_source_sha256: sourceHash }))).rejects.toThrow('changed externally');
    expect(getFeatureRegistry().saveFileWithReceipt).not.toHaveBeenCalled();
  });

  it('rejects save errors, unchanged dirty state, or unavailable readback', async () => {
    const context = _readScopedDocument(action('ui_read_context'));
    const save = action('ui_save', { expected_revision: context.revision, expected_source_sha256: sourceHash });
    getFeatureRegistry().saveFileWithReceipt = vi.fn(async () => { throw new Error('source conflict'); });
    await expect(_saveScopedDocument(save)).rejects.toThrow('source conflict');
    getFeatureRegistry().saveFileWithReceipt = vi.fn(async () => ({ file_id: 'file123', persisted: true, unsaved_changes: true }));
    await expect(_saveScopedDocument(save)).rejects.toThrow('not persisted');
    getFeatureRegistry().saveFileWithReceipt = vi.fn(async () => ({ file_id: 'file123', persisted: true, unsaved_changes: false }));
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500 })));
    await expect(_saveScopedDocument(save)).rejects.toThrow('read back');
  });
});
