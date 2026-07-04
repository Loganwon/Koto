/**
 * Workspace save runtime for the unified Koto shell.
 * Workspace save contract and shortcuts.
 */

import { _csrfFetch, $, showToast } from './infrastructure';
import { _fsHandleMap, _renderTabs, loadRecentFiles, state, type TabInfo } from './state';
import { _serializeEditorForTab, _stableWorkspaceSnapshot } from './file-open';

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
  const sharedNormalizer = (window as any).WA && (window as any).WA.normalizeWorkspaceFilePath;
  if (typeof sharedNormalizer === 'function') {
    try {
      const normalized = String(sharedNormalizer(raw) || '').trim().replace(/\\/g, '/').replace(/^\/+/, '');
      if (normalized) return normalized;
    } catch (_) {
      /* fallback below */
    }
  }
  return raw.replace(/^workspace\//i, '');
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
  if (explicit && _hasPendingExternalFileChange(tab)) {
    throw new Error('文件已被任务更新，请重新打开后再保存，避免覆盖任务结果。');
  }
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
    tab.savedSnapshot = _stableWorkspaceSnapshot(data);
    if (tab.fileType !== 'docx') tab.cache = data;
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
  if ((window as any).__waSaveShortcutsInstalled) return;
  (window as any).__waSaveShortcutsInstalled = true;
  document.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && String(event.key || '').toLowerCase() === 's') {
      if (!state.activeEditor || _isReadonlyType()) return;
      event.preventDefault();
      saveFile();
    }
  }, true);
}

(window as any).WA = (window as any).WA || {};
(window as any).WA.saveFile = saveFile;
(window as any).WA.saveAs = saveAs;
(window as any).WA.autoSave = autoSave;
(window as any).WA.scheduleAutoSave = scheduleAutoSave;
(window as any).WA._notifyPyModified = _notifyPyModified;
(window as any).WA.markExternalFileChange = markExternalFileChange;
(window as any).WA.clearExternalFileChange = clearExternalFileChange;
(window as any).WA.toggleAutoSave = toggleAutoSave;
(window as any).WA.renderAutoSaveToggle = _renderAutoSaveToggle;
(window as any)._safeJson = (window as any)._safeJson || _safeJson;
(window as any)._notifyPyModified = (window as any)._notifyPyModified || _notifyPyModified;

_installSaveShortcuts();
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _renderAutoSaveToggle);
} else {
  _renderAutoSaveToggle();
}
