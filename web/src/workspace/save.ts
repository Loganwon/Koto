import { getFeatureRegistry, registerFeatures } from '../shared/feature-registry';
/**
 * Workspace save runtime for the unified Koto shell.
 * Workspace save contract and shortcuts.
 */

import { _csrfFetch, $, showToast } from './infrastructure';
import { _fsHandleMap, _renderTabs, loadRecentFiles, state, type TabInfo } from './state';
import { _serializeEditorForTab, _stableWorkspaceSnapshot } from './file-open';
import { normalizeWorkspaceFilePath } from './docx-review-runtime';

const _MIME: Record<string, string> = {
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  txt: 'text/plain',
  md: 'text/markdown',
  csv: 'text/csv',
  json: 'application/json',
};

let _isSaving = false;
let _autoSaveTimer: ReturnType<typeof setTimeout> | null = null;
let _autoSaveEnabled = localStorage.getItem('wa_autosave') === 'on';
const _externallyChangedPaths = new Set<string>();

async function _safeJson(res: Response): Promise<any> {
  try {
    return await res.json();
  } catch (_) {
    throw new Error(`HTTP ${res.status}: 服务器返回非 JSON 响应`);
  }
}

function _activeTab(): TabInfo | null {
  return state.openTabs.find((tab) => tab.path === state.activeTabPath) || null;
}

function _normalizeWorkspaceSavePath(path: string): string {
  const raw = String(path || '').trim().replace(/\\/g, '/').replace(/^\/+/, '');
  if (!raw) return '';
  return String(normalizeWorkspaceFilePath(raw) || raw)
    .trim()
    .replace(/\\/g, '/')
    .replace(/^\/+/, '');
}

function markExternalFileChange(path: string): void {
  const normalized = _normalizeWorkspaceSavePath(path);
  if (!normalized) return;
  _externallyChangedPaths.add(normalized.toLowerCase());
  const tab = state.openTabs.find((item) => _normalizeWorkspaceSavePath(item.path || '').toLowerCase() === normalized.toLowerCase());
  if (tab) (tab as any).externalFileChangePending = true;
}

function clearExternalFileChange(path: string): void {
  const normalized = _normalizeWorkspaceSavePath(path);
  if (!normalized) return;
  _externallyChangedPaths.delete(normalized.toLowerCase());
  const tab = state.openTabs.find((item) => _normalizeWorkspaceSavePath(item.path || '').toLowerCase() === normalized.toLowerCase());
  if (tab) delete (tab as any).externalFileChangePending;
}

function _hasPendingExternalFileChange(tab: TabInfo | null): boolean {
  const path = _normalizeWorkspaceSavePath((tab && tab.path) || state.wsSourcePath || '');
  if (!path) return false;
  return !!(tab as any)?.externalFileChangePending || _externallyChangedPaths.has(path.toLowerCase());
}

function _isReadonlyType(): boolean {
  return !state.fileType || state.fileType === 'pdf' || state.fileType === 'image';
}

export function _notifyPyModified(tab: TabInfo | null, modified: boolean): void {
  if (!tab) return;
  try {
    const api = (window as any).pywebview?.api;
    if (api && typeof api.mark_file_modified === 'function') {
      api.mark_file_modified(tab.path || '', tab.name || '', modified);
    }
  } catch (_) {
    /* non-fatal desktop bridge */
  }
}

function _ensureCanSave(tab: TabInfo | null, notify: boolean): boolean {
  const progressive = tab && (tab as any).progressive;
  if (tab?.fileType === 'docx' && progressive && progressive.loading && !progressive.complete) {
    if (notify) showToast('DOCX 仍在后台加载，请稍后再保存。', 'warning');
    return false;
  }
  if (!state.activeEditor || !state.fileId || _isReadonlyType()) {
    if (notify) showToast('当前文件不支持保存', 'info');
    return false;
  }
  return true;
}

async function _writeToFileHandle(handle: any, bytes: ArrayBuffer): Promise<void> {
  const writable = await handle.createWritable();
  await writable.write(bytes);
  await writable.close();
}

function _setSaveButtonsBusy(busy: boolean): void {
  const saveBtn = $('wa-save-btn') as HTMLButtonElement | null;
  const saveAsBtn = $('wa-saveas-btn') as HTMLButtonElement | null;
  const readonly = _isReadonlyType();
  if (saveBtn) saveBtn.disabled = busy || readonly;
  if (saveAsBtn) saveAsBtn.disabled = busy || readonly;
}

export interface SaveReceiptOptions { expected_source_sha256?: string; silent?: boolean }

async function _postAutoSave(tab: TabInfo | null, explicit: boolean, options: SaveReceiptOptions = {}, deferSourceUpdate = false): Promise<any> {
  if (explicit && _hasPendingExternalFileChange(tab)) {
    throw new Error('文件已被任务更新，请重新打开后再保存，避免覆盖任务结果。');
  }
  const fileId = state.fileId;
  const data = _serializeEditorForTab(tab, state.activeEditor);
  const res = await _csrfFetch('/api/v1/workspace/auto_save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      file_type: state.fileType,
      file_id: state.fileId,
      ws_source_path: state.wsSourcePath || null,
      explicit,
      expected_source_sha256: options.expected_source_sha256 || tab?.sourceSha256 || undefined,
      data,
    }),
  });
  const json = await _safeJson(res);
  if (!res.ok || json.ok !== true) throw new Error(json.error || '保存失败');
  if (tab) {
    const savedSnapshot = _stableWorkspaceSnapshot(data);
    // A user may edit while the network write is in progress. Keep that edit dirty.
    const currentSnapshot = state.fileId === fileId
      ? _stableWorkspaceSnapshot(_serializeEditorForTab(tab, state.activeEditor)) : null;
    tab.modified = currentSnapshot === null || currentSnapshot !== savedSnapshot;
    tab.savedSnapshot = savedSnapshot;
    if (json.source_sha256 && !deferSourceUpdate) {
      tab.sourceSha256 = String(json.source_sha256);
      if (state.fileId === fileId) state.sourceSha256 = tab.sourceSha256;
    }
    if (tab.fileType !== 'docx') tab.cache = data;
    _notifyPyModified(tab, tab.modified);
    _renderTabs();
  }
  return json;
}

async function sha256(bytes: ArrayBuffer): Promise<string> {
  if (!globalThis.crypto?.subtle) throw new Error('当前环境无法核验原文件版本，未执行写入');
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest)).map((value) => value.toString(16).padStart(2, '0')).join('');
}

async function fileHandleHash(handle: any): Promise<string> {
  if (typeof handle.getFile !== 'function') throw new Error('无法读取原文件版本，未执行写入');
  return sha256(await (await handle.getFile()).arrayBuffer());
}

function _assertActiveSaveDocument(tab: TabInfo | null, fileId: string | null, editor: any): void {
  if (state.fileId === fileId && state.activeEditor === editor && _activeTab() === tab) return;
  if (tab) { tab.modified = true; _notifyPyModified(tab, true); _renderTabs(); }
  throw new Error('保存期间已切换文档，编辑稿已保留；请返回原文档重新保存');
}

async function _doSave(fsHandle?: any, options: SaveReceiptOptions = {}): Promise<Record<string, any>> {
  const tab = _activeTab();
  if (!_ensureCanSave(tab, true)) throw new Error('当前文档尚不可保存');
  const fileId = state.fileId;
  const editor = state.activeEditor;
  const path = state.wsSourcePath || tab?.path || '';
  const baseline = options.expected_source_sha256 || tab?.sourceSha256 || '';
  const savedSnapshotBefore = tab?.savedSnapshot;
  if (fsHandle && (!baseline || await fileHandleHash(fsHandle) !== baseline)) {
    if (tab) tab.modified = true;
    throw new Error('原文件已被外部修改，未覆盖；请重新打开并合并修改');
  }
  _assertActiveSaveDocument(tab, fileId, editor);
  const receipt = await _postAutoSave(tab, true, options, !!fsHandle);
  let fileHandleWritten = false;
  let sourceHash = String(receipt.source_sha256 || '');
  if (fsHandle && fileId) {
    try {
      const rawRes = await fetch(`/api/v1/workspace/raw/${encodeURIComponent(fileId)}?_=${Date.now()}`);
      if (!rawRes.ok) throw new Error('已保存工作区副本，但无法写回原始文件');
      const bytes = await rawRes.arrayBuffer();
      const newHash = await sha256(bytes);
      const currentHash = await fileHandleHash(fsHandle);
      if (currentHash !== baseline && currentHash !== newHash) {
        throw new Error('原文件在保存期间被修改，未覆盖；请重新打开并合并修改');
      }
      if (currentHash !== newHash) await _writeToFileHandle(fsHandle, bytes);
      sourceHash = await fileHandleHash(fsHandle);
      if (sourceHash !== newHash) throw new Error('原文件写回后核验失败');
      fileHandleWritten = true;
    } catch (error) {
      if (tab) { tab.modified = true; tab.savedSnapshot = savedSnapshotBefore; }
      throw error;
    }
  }
  const persisted = receipt.persisted === true || receipt.src_written === true || fileHandleWritten;
  if (!persisted) {
    if (tab) {
      tab.modified = true;
      tab.savedSnapshot = savedSnapshotBefore;
      tab.sourceSha256 = baseline;
      if (state.fileId === fileId) state.sourceSha256 = baseline;
      _notifyPyModified(tab, true);
      _renderTabs();
    }
    throw new Error('编辑稿已保留，源文件未保存；请检查原文件路径或另存副本');
  }
  if (sourceHash && tab) {
    tab.sourceSha256 = sourceHash;
    if (state.fileId === fileId) state.sourceSha256 = sourceHash;
  }
  if (!options.silent) showToast('已保存', 'success');
  setTimeout(() => { loadRecentFiles().catch(() => {}); }, 500);
  return {
    ...receipt, file_id: fileId, path,
    source_sha256: sourceHash,
    file_handle_written: fileHandleWritten,
    persisted,
    unsaved_changes: tab?.modified === true,
  };
}

/** Strict save boundary for Agent tools. Errors must reach the calling model. */
export async function saveFileWithReceipt(options: SaveReceiptOptions = {}): Promise<Record<string, any>> {
  if (_isSaving) throw new Error('文档正在保存，请等待当前保存结束');
  const tab = _activeTab();
  if (!_ensureCanSave(tab, false)) throw new Error('当前文档不支持保存或尚未加载完成');
  _isSaving = true;
  _setSaveButtonsBusy(true);
  try {
    const fsHandle = (tab && tab.fsHandle) || _fsHandleMap.get(state.wsSourcePath || '') || null;
    return await _doSave(fsHandle, options);
  } finally {
    _isSaving = false;
    _setSaveButtonsBusy(false);
  }
}

async function saveFile(): Promise<void> {
  try { await saveFileWithReceipt(); }
  catch (error: any) { showToast(error?.message || '保存失败', 'error'); }
}

/** Export a copy to the explicitly selected destination without saving over the source. */
export async function saveFileCopyWithReceipt(fsHandle: any, expectedTargetSha256: string): Promise<Record<string, any>> {
  if (_isSaving) throw new Error('文档正在保存，请等待当前保存结束');
  const tab = _activeTab();
  const fileId = state.fileId;
  const editor = state.activeEditor;
  if (!_ensureCanSave(tab, false)) throw new Error('当前文档尚不可导出');
  _isSaving = true;
  _setSaveButtonsBusy(true);
  try {
    if (!expectedTargetSha256 || await fileHandleHash(fsHandle) !== expectedTargetSha256) {
      throw new Error('另存目标已发生变化，未覆盖');
    }
    _assertActiveSaveDocument(tab, fileId, editor);
    const data = _serializeEditorForTab(tab, state.activeEditor);
    const response = await _csrfFetch('/api/v1/workspace/save_file', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_type: state.fileType, file_id: state.fileId,
        file_name: fsHandle.name || tab?.name || 'document', data }),
    });
    if (!response.ok) {
      const error = await _safeJson(response);
      throw new Error(error.error || '导出副本失败');
    }
    const bytes = await response.arrayBuffer();
    const digest = await sha256(bytes);
    const currentHash = await fileHandleHash(fsHandle);
    if (currentHash !== expectedTargetSha256 && currentHash !== digest) {
      throw new Error('另存目标在导出期间被修改，未覆盖');
    }
    if (currentHash !== digest) await _writeToFileHandle(fsHandle, bytes);
    if (await fileHandleHash(fsHandle) !== digest) throw new Error('另存副本写入后核验失败');
    showToast('副本已另存为，原文件未覆盖', 'success');
    return { ok: true, persisted: true, verified: true, source_sha256: digest,
      path: fsHandle.name || '', copy: true, original_unchanged: true };
  } finally {
    _isSaving = false;
    _setSaveButtonsBusy(false);
  }
}

async function saveAs(): Promise<void> {
  if (_isSaving) return;
  const tab = _activeTab();
  if (!_ensureCanSave(tab, true)) return;
  if (!(window as any).showSaveFilePicker) {
    showToast('当前环境不支持另存为，请使用保存。', 'error');
    return;
  }
  const ext = String(state.wsSourcePath || state.fileName || 'file.docx').split('.').pop()?.toLowerCase() || 'docx';
  let fsHandle: any = null;
  try {
    fsHandle = await (window as any).showSaveFilePicker({
      suggestedName: state.fileName || `document.${ext}`,
      types: [{ description: '文档', accept: { [_MIME[ext] || 'application/octet-stream']: [`.${ext}`] } }],
      excludeAcceptAllOption: false,
    });
  } catch (error: any) {
    if (error && error.name === 'AbortError') return;
    showToast(`无法打开保存对话框：${error && error.message ? error.message : error}`, 'error');
    return;
  }
  try {
    const targetBaseline = await fileHandleHash(fsHandle);
    await saveFileCopyWithReceipt(fsHandle, targetBaseline);
  } catch (error: any) {
    showToast(error && error.message ? error.message : '另存为失败', 'error');
  } finally {
    _isSaving = false;
    _setSaveButtonsBusy(false);
  }
}

export function scheduleAutoSave(options?: { skipDiskWrite?: boolean }): void {
  if (!state.fileId || _isReadonlyType()) return;
  const tab = _activeTab();
  if (tab && !tab.modified) {
    tab.modified = true;
    _notifyPyModified(tab, true);
    _renderTabs();
  }
  if (options && options.skipDiskWrite) {
    if (_autoSaveTimer) clearTimeout(_autoSaveTimer);
    _autoSaveTimer = null;
    return;
  }
  if (!_autoSaveEnabled) return;
  if (_autoSaveTimer) clearTimeout(_autoSaveTimer);
  _autoSaveTimer = setTimeout(() => {
    _autoSaveTimer = null;
    autoSave().catch(() => {});
  }, 2000);
}

async function autoSave(): Promise<void> {
  _autoSaveTimer = null;
  const tab = _activeTab();
  if (!_ensureCanSave(tab, false)) return;
  try {
    await saveFileWithReceipt({ silent: true });
  } catch (error) {
    console.warn('[WA autoSave]', error);
  }
}

function _renderAutoSaveToggle(): void {
  const toggle = $('wa-autosave-toggle') as HTMLButtonElement | null;
  const status = $('wa-autosave-status');
  if (toggle) {
    toggle.classList.toggle('active', _autoSaveEnabled);
    toggle.classList.toggle('toggle-on', _autoSaveEnabled);
    toggle.setAttribute('aria-pressed', _autoSaveEnabled ? 'true' : 'false');
    toggle.title = `自动保存：${_autoSaveEnabled ? '开' : '关'}`;
  }
  if (status) {
    status.textContent = _autoSaveEnabled ? '自动保存开' : '自动保存';
  }
}

function toggleAutoSave(force?: boolean): boolean {
  _autoSaveEnabled = typeof force === 'boolean' ? force : !_autoSaveEnabled;
  localStorage.setItem('wa_autosave', _autoSaveEnabled ? 'on' : 'off');
  if (!_autoSaveEnabled && _autoSaveTimer) {
    clearTimeout(_autoSaveTimer);
    _autoSaveTimer = null;
  }
  _renderAutoSaveToggle();
  showToast(_autoSaveEnabled ? '已开启自动保存' : '已关闭自动保存', 'info', 1600);
  if (_autoSaveEnabled) scheduleAutoSave();
  return _autoSaveEnabled;
}

function _installSaveShortcuts(): void {
  if (getFeatureRegistry().__waSaveShortcutsInstalled) return;
  getFeatureRegistry().__waSaveShortcutsInstalled = true;
  document.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && String(event.key || '').toLowerCase() === 's') {
      if (!state.activeEditor || _isReadonlyType()) return;
      event.preventDefault();
      saveFile();
    }
  }, true);
}

registerFeatures({
  saveFile,
  saveFileWithReceipt,
  isDocumentSaveInProgress: () => _isSaving,
  saveFileCopyWithReceipt,
  saveAs,
  autoSave,
  scheduleAutoSave,
  _notifyPyModified,
  markExternalFileChange,
  clearExternalFileChange,
  toggleAutoSave,
  renderAutoSaveToggle: _renderAutoSaveToggle,
});

_installSaveShortcuts();
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _renderAutoSaveToggle);
} else {
  _renderAutoSaveToggle();
}
