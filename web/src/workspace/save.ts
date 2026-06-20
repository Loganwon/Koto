/**
 * Workspace save runtime for the unified Koto shell.
 * Restores the old WA save contract without loading workspace-assistant.js.
 */

import { _csrfFetch, $, showToast } from './infrastructure';
import { _fsHandleMap, _renderTabs, loadRecentFiles, state, type TabInfo } from './state';
import { _serializeEditorForTab } from './file-open';

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

function _isReadonlyType(): boolean {
  return !state.fileType || state.fileType === 'pdf' || state.fileType === 'image';
}

function _notifyPyModified(tab: TabInfo | null, modified: boolean): void {
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

async function _postAutoSave(tab: TabInfo | null, explicit: boolean): Promise<any> {
  const data = _serializeEditorForTab(tab, state.activeEditor);
  const res = await _csrfFetch('/api/v1/workspace/auto_save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      file_type: state.fileType,
      file_id: state.fileId,
      ws_source_path: state.wsSourcePath || null,
      explicit,
      data,
    }),
  });
  const json = await _safeJson(res);
  if (!res.ok) throw new Error(json.error || '保存失败');
  if (tab) {
    tab.modified = false;
    if (state.fileType !== 'docx') tab.cache = data;
    _notifyPyModified(tab, false);
    _renderTabs();
  }
  return json;
}

async function _doSave(fsHandle?: any): Promise<void> {
  const tab = _activeTab();
  if (!_ensureCanSave(tab, true)) return;
  await _postAutoSave(tab, true);
  if (fsHandle && state.fileId) {
    const rawRes = await fetch(`/api/v1/workspace/raw/${encodeURIComponent(state.fileId)}?_=${Date.now()}`);
    if (rawRes.ok) {
      await _writeToFileHandle(fsHandle, await rawRes.arrayBuffer());
    } else {
      showToast('已保存到 Koto 工作区，无法写回原始文件', 'success');
      return;
    }
  }
  showToast('已保存', 'success');
  setTimeout(() => { loadRecentFiles().catch(() => {}); }, 500);
}

async function saveFile(): Promise<void> {
  if (_isSaving) return;
  const tab = _activeTab();
  if (!_ensureCanSave(tab, true)) return;
  _isSaving = true;
  _setSaveButtonsBusy(true);
  try {
    const fsHandle = (tab && tab.fsHandle) || _fsHandleMap.get(state.wsSourcePath || '') || null;
    await _doSave(fsHandle);
  } catch (error: any) {
    showToast(error && error.message ? error.message : '保存失败', 'error');
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
  if (tab) tab.fsHandle = fsHandle;
  if (state.wsSourcePath) _fsHandleMap.set(state.wsSourcePath, fsHandle);
  _isSaving = true;
  _setSaveButtonsBusy(true);
  try {
    await _doSave(fsHandle);
  } catch (error: any) {
    showToast(error && error.message ? error.message : '另存为失败', 'error');
  } finally {
    _isSaving = false;
    _setSaveButtonsBusy(false);
  }
}

function scheduleAutoSave(options?: { skipDiskWrite?: boolean }): void {
  if (!state.fileId || _isReadonlyType()) return;
  const tab = _activeTab();
  if (tab && !tab.modified) {
    tab.modified = true;
    _notifyPyModified(tab, true);
    _renderTabs();
  }
  if (options && options.skipDiskWrite) return;
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
    await _postAutoSave(tab, true);
  } catch (error) {
    console.warn('[WA autoSave]', error);
  }
}

function toggleAutoSave(): void {
  _autoSaveEnabled = !_autoSaveEnabled;
  localStorage.setItem('wa_autosave', _autoSaveEnabled ? 'on' : 'off');
  showToast(_autoSaveEnabled ? '自动保存已开启' : '自动保存已关闭', 'info');
}

function _installSaveShortcuts(): void {
  if ((window as any).__waSaveShortcutsInstalled) return;
  (window as any).__waSaveShortcutsInstalled = true;
  document.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && String(event.key || '').toLowerCase() === 's') {
      if (!state.activeEditor || _isReadonlyType()) return;
      event.preventDefault();
      saveFile();
    }
  });
}

(window as any).WA = (window as any).WA || {};
(window as any).WA.saveFile = saveFile;
(window as any).WA.saveAs = saveAs;
(window as any).WA.autoSave = autoSave;
(window as any).WA.scheduleAutoSave = scheduleAutoSave;
(window as any).WA.toggleAutoSave = toggleAutoSave;
(window as any)._safeJson = (window as any)._safeJson || _safeJson;

_installSaveShortcuts();
