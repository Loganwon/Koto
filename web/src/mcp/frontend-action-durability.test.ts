import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BrowserActionJournal } from './frontend-action-journal';
import { getFeatureRegistry } from '../shared/feature-registry';
import { JSDOM } from 'jsdom';
import { webcrypto } from 'node:crypto';
import type { FrontendAction } from './frontend-observer';

let serial = 0;
let state: Record<string, any>;

function action(): FrontendAction {
  serial += 1;
  return {
    id: `durable-edit-${serial}`, action: 'ui_apply_edit', mutation: true,
    request_fingerprint: `sha256-${serial}`, browser_id: 'browser-1', delivery_token: `capability-${serial}`,
    request_id: 'request-1', session_id: 'conversation-1',
    options: { document_path: 'report.txt', file_id: 'file-1', anchor_text: 'old', replacement: 'new' },
  };
}

beforeEach(() => {
  vi.stubGlobal('localStorage', new JSDOM('', { url: 'http://localhost' }).window.localStorage);
  localStorage.clear();
  document.body.innerHTML = '<textarea id="wa-text-content">old document</textarea>';
  state = { fileId: 'file-1', fileType: 'text', activeTabPath: 'report.txt', wsSourcePath: 'report.txt', sourceSha256: '0'.repeat(64), openTabs: [{ fileId: 'file-1', path: 'report.txt', modified: false }] };
  const features = getFeatureRegistry();
  features._inspectWorkspaceRuntime = () => ({ state, activeEditor: { getContent: () => (document.getElementById('wa-text-content') as HTMLTextAreaElement).value } });
  features.scheduleAutoSave = vi.fn(() => { state.openTabs[0].modified = true; });
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ success: true }) })));
});
afterEach(() => vi.unstubAllGlobals());

describe('browser receipt durability', () => {
  it('keeps independent tab writes under separate atomic action keys', () => {
    const first = new BrowserActionJournal(localStorage);
    const second = new BrowserActionJournal(localStorage);
    first.reserve({ id: 'one', fingerprint: 'one', browser_id: 'browser-1', delivery_token: 'cap-1', mutation: true });
    second.reserve({ id: 'two', fingerprint: 'two', browser_id: 'browser-2', delivery_token: 'cap-2', mutation: true });
    second.finish('two', { ok: true, result: { persisted: true }, error: '' });
    first.finish('one', { ok: true, result: { applied: true }, error: '' });
    expect(new BrowserActionJournal(localStorage).pending()).toHaveLength(2);
    expect(first.get('two')?.outcome?.result.persisted).toBe(true);
  });

  it('reloads an actual completed editor receipt and does not mutate twice', async () => {
    const observer = await import('./frontend-observer');
    const docs = await import('./frontend-observer-document-actions');
    const edit = action();
    edit.options!.expected_revision = docs._readScopedDocument({ ...edit, action: 'ui_read_context' }).revision;
    const first = await observer._executeFrontendActionOnce(edit);
    expect(first.ok).toBe(true);
    expect((document.getElementById('wa-text-content') as HTMLTextAreaElement).value).toBe('new document');
    vi.resetModules();
    const restarted = await import('./frontend-observer');
    expect(await restarted._executeFrontendActionOnce(edit)).toEqual(first);
    expect(getFeatureRegistry().scheduleAutoSave).toHaveBeenCalledTimes(1);
    await restarted._flushActionReceipts();
    const sent = JSON.parse((fetch as any).mock.calls.at(-1)[1].body);
    expect(sent).toMatchObject({ id: edit.id, browser_id: edit.browser_id, delivery_token: edit.delivery_token, request_id: 'request-1', session_id: 'conversation-1', ok: true });
    expect(sent.result).toEqual(first.result);
    expect(new BrowserActionJournal(localStorage).pending()).toHaveLength(0);
  });

  it('reports a started marker as unknown after restart without editing', async () => {
    const edit = action();
    new BrowserActionJournal(localStorage).reserve({ id: edit.id, fingerprint: edit.request_fingerprint!, browser_id: edit.browser_id!, delivery_token: edit.delivery_token!, request_id: edit.request_id, session_id: edit.session_id, mutation: true });
    vi.resetModules();
    const observer = await import('./frontend-observer');
    const outcome = await observer._executeFrontendActionOnce(edit);
    expect(outcome.unknown).toBe(true);
    expect(outcome.ok).toBe(false);
    expect((document.getElementById('wa-text-content') as HTMLTextAreaElement).value).toBe('old document');
    expect(getFeatureRegistry().scheduleAutoSave).not.toHaveBeenCalled();
    await observer._flushActionReceipts();
    expect(JSON.parse((fetch as any).mock.calls.at(-1)[1].body)).toMatchObject({ ok: false, unknown: true, result: { execution_unknown: true } });
  });

  it('retries a lost receipt after reload using the complete original result', async () => {
    const journal = new BrowserActionJournal(localStorage);
    const edit = action();
    const text = '完整文档'.repeat(4000);
    journal.reserve({ id: edit.id, fingerprint: edit.request_fingerprint!, browser_id: edit.browser_id!, delivery_token: edit.delivery_token!, mutation: true });
    journal.finish(edit.id, { ok: true, result: { before_text: text, after_text: text, applied: true, persisted: false }, error: '' });
    const observer = await import('./frontend-observer');
    (fetch as any).mockRejectedValueOnce(new Error('connection lost'));
    await expect(observer._flushActionReceipts()).rejects.toThrow('connection lost');
    expect(journal.pending()).toHaveLength(1);
    vi.resetModules();
    await (await import('./frontend-observer'))._flushActionReceipts();
    expect(JSON.parse((fetch as any).mock.calls.at(-1)[1].body).result.before_text).toBe(text);
    expect(journal.pending()).toHaveLength(0);
  });

  it('rejects ID reuse with a different fingerprint before and after reload', async () => {
    const observer = await import('./frontend-observer');
    const edit = action();
    const docs = await import('./frontend-observer-document-actions');
    edit.options!.expected_revision = docs._readScopedDocument({ ...edit, action: 'ui_read_context' }).revision;
    expect((await observer._executeFrontendActionOnce(edit)).ok).toBe(true);
    const changed = { ...edit, request_fingerprint: 'different-fingerprint' };
    expect((await observer._executeFrontendActionOnce(changed)).ok).toBe(false);
    vi.resetModules();
    expect((await (await import('./frontend-observer'))._executeFrontendActionOnce(changed)).ok).toBe(false);
    expect(getFeatureRegistry().scheduleAutoSave).toHaveBeenCalledTimes(1);
  });

  it('does not execute a mutation if its durable marker cannot be stored', async () => {
    const setItem = vi.spyOn(Object.getPrototypeOf(localStorage), 'setItem').mockImplementation(() => { throw new Error('quota exceeded'); });
    const observer = await import('./frontend-observer');
    const outcome = await observer._executeFrontendActionOnce(action());
    expect(outcome.ok).toBe(false);
    expect(outcome.error).toContain('Cannot persist browser execution boundary');
    expect(getFeatureRegistry().scheduleAutoSave).not.toHaveBeenCalled();
    setItem.mockRestore();
  });

  it('returns a verified save receipt after reload without saving over a later source edit', async () => {
    vi.stubGlobal('crypto', webcrypto);
    const digest = async (bytes: Uint8Array) => Array.from(new Uint8Array(await webcrypto.subtle.digest('SHA-256', bytes))).map((n) => n.toString(16).padStart(2, '0')).join('');
    let source = new Uint8Array([111, 108, 100]);
    const originalHash = await digest(source);
    state.sourceSha256 = originalHash;
    state.openTabs[0].sourceSha256 = originalHash;
    state.openTabs[0].fsHandle = { getFile: async () => ({ arrayBuffer: async () => source.slice().buffer }) };
    const save = vi.fn(async () => {
      source = new Uint8Array([110, 101, 119]);
      return { persisted: true, verified: true, src_written: true, file_id: 'file-1', source_sha256: await digest(source), unsaved_changes: false };
    });
    getFeatureRegistry().saveFileWithReceipt = save;
    (fetch as any).mockImplementation(async () => ({ ok: true, status: 200, arrayBuffer: async () => source.slice().buffer, json: async () => ({ success: true }) }));
    const observer = await import('./frontend-observer');
    const docs = await import('./frontend-observer-document-actions');
    const saveAction = { ...action(), action: 'ui_save' as const };
    saveAction.options = { ...saveAction.options, expected_revision: docs._readScopedDocument({ ...saveAction, action: 'ui_read_context' }).revision, expected_source_sha256: originalHash };
    const receipt = await observer._executeFrontendActionOnce(saveAction);
    expect(receipt.ok).toBe(true);
    expect(receipt.result.persisted).toBe(true);
    expect(receipt.result.raw_sha256).toBe(await digest(source));
    source = new Uint8Array([117, 115, 101, 114]);
    vi.resetModules();
    const replay = await (await import('./frontend-observer'))._executeFrontendActionOnce(saveAction);
    expect(replay).toEqual(receipt);
    expect(save).toHaveBeenCalledTimes(1);
    expect([...source]).toEqual([117, 115, 101, 114]);
  });
});
