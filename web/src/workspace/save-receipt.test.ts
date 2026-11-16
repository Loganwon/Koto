import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';

const mocks = vi.hoisted(() => {
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => null, setItem: () => {} } });
  return {
  state: { openTabs: [] as any[], activeTabPath: 'report.docx', activeEditor: {}, fileId: 'f1', fileType: 'docx', wsSourcePath: 'report.docx', sourceSha256: 'old' },
  fetch: vi.fn(), content: { text: '初稿' }, toast: vi.fn(),
  };
});
vi.mock('./infrastructure', () => ({ _csrfFetch: mocks.fetch, $: () => null, showToast: mocks.toast }));
vi.mock('./state', () => ({ state: mocks.state, _fsHandleMap: new Map(), _renderTabs: vi.fn(), loadRecentFiles: vi.fn(async () => {}) }));
vi.mock('./file-open', () => ({
  _serializeEditorForTab: () => ({ ...mocks.content }),
  _stableWorkspaceSnapshot: (data: any) => JSON.stringify(data),
}));
vi.mock('./docx-review-runtime', () => ({ normalizeWorkspaceFilePath: (path: string) => path }));

import { saveFileWithReceipt, saveFileCopyWithReceipt, scheduleAutoSave } from './save';
import { getFeatureRegistry } from '../shared/feature-registry';

beforeEach(() => {
  vi.clearAllMocks();
  mocks.state.openTabs = [{ path: 'report.docx', name: 'report.docx', fileType: 'docx', modified: true, sourceSha256: 'old' }];
  mocks.content.text = '初稿';
});
afterEach(() => vi.unstubAllGlobals());

describe('strict document save receipt', () => {
  it.each([false, true])('does not serialize a different tab while checking the save target (copy=%s)', async (copy) => {
    vi.stubGlobal('crypto', webcrypto);
    const bytes = new TextEncoder().encode('原始文件');
    const baseline = Array.from(new Uint8Array(await webcrypto.subtle.digest('SHA-256', bytes)))
      .map((value) => value.toString(16).padStart(2, '0')).join('');
    const tab = mocks.state.openTabs[0]; tab.sourceSha256 = baseline;
    let read!: (_file: any) => void;
    const handle = { getFile: () => new Promise((resolve) => { read = resolve; }), createWritable: vi.fn() };
    if (!copy) tab.fsHandle = handle;
    const originalEditor = mocks.state.activeEditor;
    const pending = copy ? saveFileCopyWithReceipt(handle, baseline) : saveFileWithReceipt();
    mocks.state.fileId = 'different-document'; mocks.state.activeEditor = { different: true };
    read({ arrayBuffer: async () => bytes.buffer });
    try {
      await expect(pending).rejects.toThrow('已切换文档');
      expect(mocks.fetch).not.toHaveBeenCalled();
      expect(handle.createWritable).not.toHaveBeenCalled();
      expect(tab.modified).toBe(true);
    } finally { mocks.state.fileId = 'f1'; mocks.state.activeEditor = originalEditor; }
  });

  it('keeps an unconfirmed AI edit dirty and cancels a previously queued autosave', async () => {
    vi.useFakeTimers();
    const api = getFeatureRegistry();
    try {
      api.toggleAutoSave(true);
      scheduleAutoSave();
      mocks.content.text = '尚未核验的 AI 草稿';
      scheduleAutoSave({ skipDiskWrite: true });
      await vi.advanceTimersByTimeAsync(2500);
      expect(mocks.fetch).not.toHaveBeenCalled();
      expect(mocks.state.openTabs[0].modified).toBe(true);
      expect(api.isDocumentSaveInProgress()).toBe(false);
      mocks.fetch.mockResolvedValue({ ok: true, json: async () => ({ ok: true, src_written: true, source_sha256: 'saved' }) });
      mocks.content.text = '用户继续输入后的版本';
      scheduleAutoSave();
      await vi.advanceTimersByTimeAsync(2500);
      expect(mocks.fetch).toHaveBeenCalledTimes(1);
      expect(mocks.state.openTabs[0].modified).toBe(false);
    } finally { api.toggleAutoSave(false); vi.useRealTimers(); }
  });

  it('exposes in-flight persistence so semantic edits can refuse a serialization race', async () => {
    let complete!: (_response: any) => void;
    mocks.fetch.mockImplementation(() => new Promise((resolve) => { complete = resolve; }));
    const pending = saveFileWithReceipt();
    expect(getFeatureRegistry().isDocumentSaveInProgress()).toBe(true);
    complete({ ok: true, json: async () => ({ ok: true, src_written: true, source_sha256: 'saved' }) });
    await pending;
    expect(getFeatureRegistry().isDocumentSaveInProgress()).toBe(false);
  });

  it('sends the opened source version and returns the actual server receipt', async () => {
    mocks.fetch.mockResolvedValue({ ok: true, json: async () => ({ ok: true, persisted: true, verified: true, src_written: true, source_sha256: 'new' }) });
    const receipt = await saveFileWithReceipt({ expected_source_sha256: 'old' });
    expect(JSON.parse(mocks.fetch.mock.calls[0][1].body)).toMatchObject({ expected_source_sha256: 'old', file_id: 'f1' });
    expect(receipt).toMatchObject({ persisted: true, verified: true, source_sha256: 'new', unsaved_changes: false });
    expect(mocks.state.openTabs[0].sourceSha256).toBe('new');
  });

  it('preserves unsaved edits and propagates a version conflict', async () => {
    mocks.fetch.mockResolvedValue({ ok: false, status: 409, json: async () => ({ error: '文件版本冲突' }) });
    await expect(saveFileWithReceipt()).rejects.toThrow('文件版本冲突');
    expect(mocks.state.openTabs[0].modified).toBe(true);
    expect(mocks.state.openTabs[0].sourceSha256).toBe('old');
  });

  it('keeps edits made during an in-flight save dirty', async () => {
    mocks.fetch.mockImplementation(async () => {
      mocks.content.text = '用户在保存时继续修改';
      return { ok: true, json: async () => ({ ok: true, src_written: true, source_sha256: 'saved' }) };
    });
    const receipt = await saveFileWithReceipt();
    expect(receipt.unsaved_changes).toBe(true);
    expect(mocks.state.openTabs[0].modified).toBe(true);
  });

  it('does not report a cached draft as a saved source file', async () => {
    mocks.fetch.mockResolvedValue({ ok: true, json: async () => ({ ok: true, src_written: false, persisted: false, source_sha256: 'draft' }) });
    await expect(saveFileWithReceipt()).rejects.toThrow('源文件未保存');
    expect(mocks.state.openTabs[0].modified).toBe(true);
    expect(mocks.state.openTabs[0].sourceSha256).toBe('old');
    expect(mocks.toast).not.toHaveBeenCalledWith('已保存', 'success');
  });

  it('checks the original file before any save and never overwrites an external edit', async () => {
    vi.stubGlobal('crypto', webcrypto);
    const writable = vi.fn();
    mocks.state.openTabs[0].fsHandle = {
      getFile: async () => ({ arrayBuffer: async () => new TextEncoder().encode('外部改动').buffer }),
      createWritable: writable,
    };
    await expect(saveFileWithReceipt()).rejects.toThrow('原文件已被外部修改');
    expect(mocks.fetch).not.toHaveBeenCalled();
    expect(writable).not.toHaveBeenCalled();
    expect(mocks.state.openTabs[0].sourceSha256).toBe('old');
    expect(mocks.state.openTabs[0].modified).toBe(true);
  });

  it('preserves the source baseline if the original changes while the copy is saving', async () => {
    vi.stubGlobal('crypto', webcrypto);
    const original = new TextEncoder().encode('原稿');
    const digest = await webcrypto.subtle.digest('SHA-256', original);
    const baseline = Array.from(new Uint8Array(digest)).map((value) => value.toString(16).padStart(2, '0')).join('');
    let source = original;
    const writable = vi.fn();
    const tab = mocks.state.openTabs[0];
    tab.sourceSha256 = baseline;
    tab.fsHandle = {
      getFile: async () => ({ arrayBuffer: async () => source.buffer }),
      createWritable: writable,
    };
    mocks.fetch.mockImplementation(async () => {
      source = new TextEncoder().encode('保存期间外部修改');
      return { ok: true, json: async () => ({ ok: true, source_sha256: 'copy-hash', src_written: false }) };
    });
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, arrayBuffer: async () => new TextEncoder().encode('新稿').buffer })));
    await expect(saveFileWithReceipt()).rejects.toThrow('原文件在保存期间被修改');
    expect(writable).not.toHaveBeenCalled();
    expect(tab.sourceSha256).toBe(baseline);
    expect(tab.modified).toBe(true);
  });

  it('saves a new copy to an empty target while preserving the original source and dirty state', async () => {
    vi.stubGlobal('crypto', webcrypto);
    let target = new Uint8Array();
    const getHash = async () => Array.from(new Uint8Array(await webcrypto.subtle.digest('SHA-256', target)))
      .map((byte) => byte.toString(16).padStart(2, '0')).join('');
    const handle = { name: 'copy.docx', getFile: async () => ({ arrayBuffer: async () => target.buffer }),
      createWritable: async () => ({ write: async (bytes: ArrayBuffer) => { target = new Uint8Array(bytes); }, close: async () => {} }) };
    mocks.fetch.mockResolvedValue({ ok: true, arrayBuffer: async () => new TextEncoder().encode('导出的完整文档').buffer });
    const receipt = await saveFileCopyWithReceipt(handle, await getHash());
    expect(receipt).toMatchObject({ persisted: true, verified: true, copy: true, original_unchanged: true });
    expect(new TextDecoder().decode(target)).toBe('导出的完整文档');
    expect(mocks.fetch.mock.calls[0][0]).toBe('/api/v1/workspace/save_file');
    expect(JSON.parse(mocks.fetch.mock.calls[0][1].body)).not.toHaveProperty('ws_source_path');
    expect(mocks.state.openTabs[0].sourceSha256).toBe('old');
    expect(mocks.state.openTabs[0].modified).toBe(true);
    expect(mocks.state.openTabs[0].fsHandle).toBeUndefined();
  });

  it('refuses to overwrite a save-as target changed during export', async () => {
    vi.stubGlobal('crypto', webcrypto);
    let target = new TextEncoder().encode('原目标');
    const baseline = Array.from(new Uint8Array(await webcrypto.subtle.digest('SHA-256', target)))
      .map((byte) => byte.toString(16).padStart(2, '0')).join('');
    const write = vi.fn();
    const handle = { name: 'existing.docx', getFile: async () => ({ arrayBuffer: async () => target.buffer }), createWritable: write };
    mocks.fetch.mockImplementation(async () => {
      target = new TextEncoder().encode('其他程序更新目标');
      return { ok: true, arrayBuffer: async () => new TextEncoder().encode('导出内容').buffer };
    });
    await expect(saveFileCopyWithReceipt(handle, baseline)).rejects.toThrow('另存目标在导出期间被修改');
    expect(write).not.toHaveBeenCalled();
    expect(new TextDecoder().decode(target)).toBe('其他程序更新目标');
    expect(mocks.state.openTabs[0].sourceSha256).toBe('old');
  });
});
