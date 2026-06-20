/**
 * File Utilities & Version History — close-warning, archive, version restore,
 * recoverable task persistence, chart image wrapping, auto-save.
 * Converted from workspace-assistant.js lines 15878-16569 + task recovery.
 */

declare function $(id: string): HTMLElement | null;
declare var state: any;
declare var WA: any;
declare var _autoSaveEnabled: boolean;
declare var _autoSaveTimer: any;
declare var _isSaving: boolean;
declare var _fsHandleMap: Map<string, any>;
declare var _MIME: Record<string, string>;
declare var _DOWNLOAD_SVG: string;
declare var _EXT_ICON: Record<string, string>;
declare var _DEFAULT_FILE_SVG: string;
declare var _FOLDER_PICK_SVG: string;
declare var _waConversationRuntime: any;
declare var _waTaskDispatcher: any;
declare var Router: any;

declare function _escHtml(s: any): string;
declare function showToast(message: string, kind?: string, duration?: number): void;
declare function _csrfFetch(url: string, init?: RequestInit): Promise<Response>;
declare function _renderTabs(): void;
declare function _renderMyWorkspace(): void;
declare function _notifyPyModified(tab: any, modified: boolean): void;
declare function _initWorkspaceAiRuntimes(): void;
declare function _waSession(): string;
declare function _parseTaskMetadata(raw: any): any;
declare function _conversationTaskTurn(taskId: string): any;
declare function _findRenderedTaskCard(taskId: string): HTMLElement | null;
declare function _replaceActiveTaskReconnector(taskId: string, reconnector: any): void;
declare function _serializeEditorForTab(tab: any, editor: any): any;
declare function _ensureDocxCanSave(tab: any, throwOnError: boolean): boolean;
declare function _switchToTab(path: string): Promise<void>;
declare function _writeToFileHandle(handle: any, bytes: ArrayBuffer): Promise<void>;
declare function loadRecentFiles(): void;

export interface HistoryEntry {
  snap_path: string;
  saved_at: string;
  name?: string;
  size_bytes: number;
}

export interface RecoveryTask {
  task_id: string;
  status: string;
  metadata?: any;
  source?: string;
}

export interface ChartImageConfig {
  imgSrc: string;
  fileName: string;
  serverUrl?: string;
}

export interface UnsavedTab {
  path: string;
  name: string;
}

// ── Safe JSON ──────────────────────────────────────────────────────
export async function _safeJson(res: Response): Promise<any> {
  try {
    return await res.json();
  } catch (_) {
    throw new Error(`HTTP ${res.status}: \u670d\u52a1\u5668\u8fd4\u56de\u975e JSON \u54cd\u5e94\uff08\u670d\u52a1\u662f\u5426\u6b63\u5728\u8fd0\u884c\uff1f\uff09`);
  }
}

// ── Auto-save ──────────────────────────────────────────────────────

export function scheduleAutoSave(options?: { skipDiskWrite?: boolean }): void {
  const skipDiskWrite = !!(options && options.skipDiskWrite);
  if (!state.fileId || !state.fileType || state.fileType === 'pdf' || state.fileType === 'image') return;
  const tab = state.openTabs.find((t: any) => t.path === state.activeTabPath);
  if (tab && !tab.modified) { tab.modified = true; _notifyPyModified(tab, true); _renderTabs(); }
  if (skipDiskWrite) return;
  if (_autoSaveEnabled) {
    clearTimeout(_autoSaveTimer);
    const status = $('wa-autosave-status');
    if (status) { status.className = 'saving'; status.textContent = '\u4fdd\u5b58\u4e2d\u2026'; }
    _autoSaveTimer = setTimeout(() => {
      _autoSaveTimer = null;
      autoSave();
    }, 2000);
  }
}

export async function autoSave(): Promise<void> {
  _autoSaveTimer = null;
  if (!state.activeEditor || !state.fileId || !state.fileType || state.fileType === 'pdf' || state.fileType === 'image') return;
  const status = $('wa-autosave-status');
  try {
    const tab = state.openTabs.find((t: any) => t.path === state.activeTabPath);
    if (!_ensureDocxCanSave(tab, false)) {
      if (status) { status.className = ''; status.textContent = ''; }
      return;
    }
    const data = _serializeEditorForTab(tab, state.activeEditor);
    if (tab && data && state.fileType !== 'docx') {
      tab.cache = data;
    }
    const res = await _csrfFetch('/api/v1/workspace/auto_save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        file_type: state.fileType,
        file_id: state.fileId,
        ws_source_path: state.wsSourcePath || null,
        explicit: true,
        data,
      }),
    });
    const json = await _safeJson(res);
    if (!res.ok) throw new Error(json.error || '\u81ea\u52a8\u4fdd\u5b58\u5931\u8d25');
    if (tab) { tab.modified = false; _notifyPyModified(tab, false); _renderTabs(); }
    if (status) {
      status.className = 'saved';
      status.textContent = `\u5df2\u81ea\u52a8\u4fdd\u5b58 ${json.saved_at}`;
      setTimeout(() => { if (status) { status.className = ''; status.textContent = ''; } }, 4000);
    }
  } catch (e: any) {
    if (status) { status.className = ''; status.textContent = ''; }
    console.warn('[AutoSave]', e.message);
  }
}

// ── Save to disk / Save As ────────────────────────────────────────

async function _doSave(fsHandle: any): Promise<void> {
  const _saveTab = state.openTabs.find((t: any) => t.path === state.activeTabPath);
  const _saveFileId = state.fileId;
  const _saveFileType = state.fileType;
  const _saveWsPath = state.wsSourcePath;

  if (!_ensureDocxCanSave(_saveTab, true)) return;

  const data = _serializeEditorForTab(_saveTab, state.activeEditor);
  const res = await _csrfFetch('/api/v1/workspace/auto_save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      file_type: _saveFileType,
      file_id: _saveFileId,
      ws_source_path: _saveWsPath || null,
      explicit: true,
      data,
    }),
  });
  const saveJson = await _safeJson(res);
  if (!res.ok) throw new Error(saveJson.error || '\u4fdd\u5b58\u5931\u8d25');
  if (_saveTab) {
    _saveTab.modified = false;
    _notifyPyModified(_saveTab, false);
    if (_saveFileType !== 'docx') _saveTab.cache = data;
    _renderTabs();
  }
  setTimeout(() => { try { loadRecentFiles(); } catch(e) {} }, 800);
  if (fsHandle) {
    const rawRes = await fetch(`/api/v1/workspace/raw/${_saveFileId}?_=${Date.now()}`);
    if (rawRes.ok) {
      const bytes = await rawRes.arrayBuffer();
      await _writeToFileHandle(fsHandle, bytes);
    } else {
      showToast('\u5df2\u4fdd\u5b58\u5230\u5de5\u4f5c\u533a (\u65e0\u6cd5\u5199\u56de\u539f\u59cb\u4f4d\u7f6e)', 'success');
      return;
    }
  }
  showToast('\u5df2\u4fdd\u5b58', 'success');
}

export async function saveFile(): Promise<void> {
  if (!state.activeEditor || !state.fileType || state.fileType === 'pdf' || state.fileType === 'image') return;
  if (_isSaving) return;
  _isSaving = true;
  const btn = $('wa-save-btn') as HTMLButtonElement;
  const btnAs = $('wa-saveas-btn') as HTMLButtonElement;
  btn.disabled = true;
  if (btnAs) btnAs.disabled = true;
  try {
    const _saveTab = state.openTabs.find((t: any) => t.path === state.activeTabPath);
    const _saveWsPath = state.wsSourcePath;
    const _saveFsHandle = (_saveTab && _saveTab.fsHandle) || _fsHandleMap.get(_saveWsPath) || null;
    await _doSave(_saveFsHandle);
  } catch(e: any) {
    showToast(e.message, 'error');
  } finally {
    _isSaving = false;
    const isPdf = (state.fileType === 'pdf' || state.fileType === 'image');
    btn.disabled = isPdf;
    if (btnAs) btnAs.disabled = isPdf;
  }
}

export async function saveAs(): Promise<void> {
  if (!state.activeEditor || !state.fileType || state.fileType === 'pdf' || state.fileType === 'image') return;
  if (_isSaving) return;
  if (!(window as any).showSaveFilePicker) {
    showToast('\u5f53\u524d\u73af\u5883\u4e0d\u652f\u6301\u6587\u4ef6\u4fdd\u5b58\u5bf9\u8bdd\u6846\uff0c\u8bf7\u4f7f\u7528\u201c\u4fdd\u5b58\u201d', 'error');
    return;
  }
  const ext = (state.wsSourcePath || state.fileName || 'file.docx').split('.').pop()!.toLowerCase();
  const mime = _MIME[ext] || 'application/octet-stream';
  let _saveFsHandle: any;
  try {
    _saveFsHandle = await (window as any).showSaveFilePicker({
      suggestedName: state.fileName || state.wsSourcePath || `document.${ext}`,
      types: [{ description: '\u6587\u6863', accept: { [mime]: ['.' + ext] } }],
      excludeAcceptAllOption: false,
    });
  } catch(pickerErr: any) {
    if (pickerErr.name === 'AbortError') return;
    showToast('\u65e0\u6cd5\u6253\u5f00\u4fdd\u5b58\u5bf9\u8bdd\u6846: ' + pickerErr.message, 'error');
    return;
  }
  _isSaving = true;
  const btn = $('wa-save-btn') as HTMLButtonElement;
  const btnAs = $('wa-saveas-btn') as HTMLButtonElement;
  btn.disabled = true;
  if (btnAs) btnAs.disabled = true;
  const _saveTab = state.openTabs.find((t: any) => t.path === state.activeTabPath);
  const _saveWsPath = state.wsSourcePath;
  if (_saveTab) _saveTab.fsHandle = _saveFsHandle;
  _fsHandleMap.set(_saveWsPath, _saveFsHandle);
  try {
    await _doSave(_saveFsHandle);
  } catch(e: any) {
    showToast(e.message, 'error');
  } finally {
    _isSaving = false;
    const isPdf = (state.fileType === 'pdf' || state.fileType === 'image');
    btn.disabled = isPdf;
    if (btnAs) btnAs.disabled = isPdf;
  }
}

// ── Before unload warning ──────────────────────────────────────────
window.addEventListener('beforeunload', (e) => {
  if (state.openTabs.some((t: any) => t.modified)) {
    e.preventDefault();
    (e as any).returnValue = '';
  }
});

// ── Close-warning API ─────────────────────────────────────────────

export function getUnsavedTabs(): UnsavedTab[] {
  return state.openTabs.filter((t: any) => t.modified).map((t: any) => ({ path: t.path, name: t.name }));
}

export function showCloseWarning(unsavedTabs: UnsavedTab[]): Promise<string> {
  return new Promise((resolve) => {
    const overlay = $('wa-close-warn-overlay');
    const dialogEl = $('wa-close-warn-dialog');
    const listEl = $('wa-close-warn-list');
    const countEl = $('wa-close-warn-count');
    if (!overlay || !dialogEl || !listEl) { resolve('discard'); return; }
    if (overlay.parentElement !== document.body) {
      document.body.appendChild(overlay);
    }
    if (!dialogEl.dataset.closeWarnBound) {
      dialogEl.dataset.closeWarnBound = '1';
      dialogEl.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          _closeWarnCancel();
        }
      });
    }
    if (countEl) countEl.textContent = `${unsavedTabs.length} \u4e2a\u672a\u4fdd\u5b58\u6587\u4ef6`;
    listEl.innerHTML = unsavedTabs.map(_renderCloseWarnItem).join('');
    (overlay as any)._lastFocus = document.activeElement || null;
    overlay.style.display = 'flex';
    (overlay as any)._resolve = resolve;
    requestAnimationFrame(() => dialogEl.focus());
  });
}

function _renderCloseWarnItem(tab: UnsavedTab): string {
  const fileName = _escHtml(tab && tab.name ? tab.name : '\u672a\u547d\u540d\u6587\u4ef6');
  const rawPath = tab && tab.path ? String(tab.path).replace(/\\/g, '/') : '\u5de5\u4f5c\u533a\u4e34\u65f6\u6587\u4ef6';
  const filePath = _escHtml(rawPath);
  return [
    '<div class="wa-close-warn-item">',
    '<span class="wa-close-warn-item-indicator" aria-hidden="true"></span>',
    '<div class="wa-close-warn-item-body">',
    `<div class="wa-close-warn-item-name">${fileName}</div>`,
    `<div class="wa-close-warn-item-path">${filePath}</div>`,
    '</div>',
    '</div>',
  ].join('');
}

function _settleCloseWarn(decision: string): void {
  const overlay = $('wa-close-warn-overlay') as any;
  if (overlay) overlay.style.display = 'none';
  const resolver = overlay ? overlay._resolve : null;
  if (overlay) overlay._resolve = null;
  const lastFocus = overlay ? overlay._lastFocus : null;
  if (overlay) overlay._lastFocus = null;
  if (lastFocus && typeof lastFocus.focus === 'function') {
    try { lastFocus.focus(); } catch (_) {}
  }
  if (resolver) resolver(decision);
}

function _setCloseWarnBusy(busy: boolean): void {
  const overlay = $('wa-close-warn-overlay') as HTMLElement;
  if (!overlay) return;
  overlay.dataset.busy = busy ? 'true' : 'false';
  overlay.querySelectorAll('button').forEach((button: HTMLButtonElement) => {
    button.disabled = !!busy;
  });
  const saveBtn = overlay.querySelector('.wa-close-warn-save') as HTMLButtonElement;
  if (saveBtn) {
    if (!saveBtn.dataset.defaultText) saveBtn.dataset.defaultText = saveBtn.textContent || '\u4fdd\u5b58\u5168\u90e8\u5e76\u9000\u51fa';
    saveBtn.textContent = busy ? '\u4fdd\u5b58\u4e2d...' : saveBtn.dataset.defaultText;
  }
}

export function _closeWarnCancel(): void { _settleCloseWarn('cancel'); }
export function _closeWarnDiscard(): void { _settleCloseWarn('discard'); }

export async function _closeWarnSaveAll(): Promise<void> {
  _setCloseWarnBusy(true);
  const modifiedTabs = state.openTabs.filter((t: any) => t.modified);
  try {
    for (const tab of modifiedTabs) {
      await _switchToTab(tab.path);
      if (state.activeEditor) {
        const data = _serializeEditorForTab(tab, state.activeEditor);
        const res = await _csrfFetch('/api/v1/workspace/auto_save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            file_type: tab.fileType,
            file_id: tab.fileId,
            ws_source_path: tab.path || null,
            explicit: true,
            data,
          }),
        });
        const json = await _safeJson(res);
        if (!res.ok) throw new Error(json.error || `${tab.name || tab.path || '\u6587\u4ef6'} \u4fdd\u5b58\u5931\u8d25`);
        tab.modified = false;
        _notifyPyModified(tab, false);
      }
    }
    _renderTabs();
    _settleCloseWarn('save');
  } catch (e: any) {
    console.warn('[CloseWarn] Save failed:', e);
    showToast(e && e.message ? e.message : '\u4fdd\u5b58\u5931\u8d25\uff0c\u8bf7\u91cd\u8bd5', 'error');
    _setCloseWarnBusy(false);
  }
}

// ── Archive current file ──────────────────────────────────────────
let _archivePopoverHandler: ((e: Event) => void) | null = null;

export function toggleArchivePopover(): void {
  const pop = document.getElementById('wa-archive-popover');
  if (!pop) return;
  const visible = pop.style.display !== 'none';
  pop.style.display = visible ? 'none' : 'block';
  if (!visible) {
    const handler = (e: Event) => {
      if (!pop.contains(e.target as Node) && !document.getElementById('wa-archive-btn')!.contains(e.target as Node)) {
        pop.style.display = 'none';
        document.removeEventListener('click', handler, true);
        _archivePopoverHandler = null;
      }
    };
    _archivePopoverHandler = handler;
    setTimeout(() => document.addEventListener('click', handler, true), 10);
  }
}

export async function archiveCurrent(category: string): Promise<void> {
  const pop = document.getElementById('wa-archive-popover');
  if (pop) pop.style.display = 'none';
  if (!state.wsSourcePath) { showToast('\u5f53\u524d\u6ca1\u6709\u6253\u5f00\u6587\u4ef6', 'error'); return; }
  const ext = (state.wsSourcePath || '').split('.').pop()!.toLowerCase();
  try {
    const res = await _csrfFetch('/api/files/archive', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode: 'custom',
        rules: [{ pattern: `*.${ext}`, target: category }],
        files: [state.wsSourcePath],
      }),
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.error || '\u5f52\u6863\u5931\u8d25');
    const moved = d.report?.find?.((r: any) => r.moved > 0);
    if (moved) {
      showToast(`\u5df2\u5f52\u6863\u5230\u300c${category}\u300d\u6587\u4ef6\u5939`, 'success');
      setTimeout(() => { try { if ((window as any).WA && WA.refreshRecent) WA.refreshRecent(); } catch(e) {} }, 600);
    } else {
      showToast(d.message || '\u5f52\u6863\u5b8c\u6210', 'success');
    }
  } catch (e: any) {
    showToast('\u5f52\u6863\u5931\u8d25: ' + e.message, 'error');
  }
}

// ── Version History ───────────────────────────────────────────────
let _versionHistoryHandler: ((e: Event) => void) | null = null;

export function toggleHistoryPopover(): void {
  const pop = document.getElementById('wa-history-popover');
  if (!pop) return;
  const visible = pop.style.display !== 'none';
  pop.style.display = visible ? 'none' : 'block';
  if (!visible) {
    _loadVersionHistory();
    const handler = (e: Event) => {
      if (!pop.contains(e.target as Node) && !document.getElementById('wa-history-btn')!.contains(e.target as Node)) {
        pop.style.display = 'none';
        document.removeEventListener('click', handler, true);
        _versionHistoryHandler = null;
      }
    };
    _versionHistoryHandler = handler;
    setTimeout(() => document.addEventListener('click', handler, true), 10);
  }
}

async function _loadVersionHistory(): Promise<void> {
  const listEl = document.getElementById('wa-history-list');
  if (!listEl) return;
  if (!state.wsSourcePath) { listEl.innerHTML = '<span style="color:var(--text-muted);">\u5f53\u524d\u6ca1\u6709\u6253\u5f00\u7684\u6587\u4ef6</span>'; return; }
  listEl.innerHTML = '<span style="color:var(--text-muted);">\u52a0\u8f7d\u4e2d\u2026</span>';
  try {
    const r = await fetch('/api/v1/workspace/versions?path=' + encodeURIComponent(state.wsSourcePath));
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    const versions: HistoryEntry[] = d.versions || [];
    if (!versions.length) { listEl.innerHTML = '<span style="color:var(--text-muted);">\u6682\u65e0\u5386\u53f2\u7248\u672c\uff0c\u4fdd\u5b58\u6587\u4ef6\u540e\u4f1a\u81ea\u52a8\u521b\u5efa\u5feb\u7167</span>'; return; }
    const _fmtSize = (b: number) => b > 1048576 ? (b/1048576).toFixed(1)+' MB' : Math.round(b/1024)+' KB';
    listEl.innerHTML = versions.map(v => {
      const snapArg = JSON.stringify(v.snap_path).replace(/"/g, '&quot;');
      const targetArg = JSON.stringify(state.wsSourcePath).replace(/"/g, '&quot;');
      return `<div style="display:flex;align-items:center;justify-content:space-between;padding:7px 6px;border-radius:7px;transition:background 0.1s;cursor:default;"
            onmouseover="this.style.background='var(--bg-secondary)'" onmouseout="this.style.background=''">
          <div>
            <div style="font-size:13px;font-weight:500;color:var(--text-primary);">${v.saved_at || v.name}</div>
            <div style="font-size:11px;color:var(--text-muted);">${_fmtSize(v.size_bytes||0)}</div>
          </div>
          <button onclick="_waRestoreVersion(${snapArg}, ${targetArg})"
            style="font-size:11px;padding:3px 8px;border-radius:6px;border:1px solid var(--border-color);background:var(--bg-primary);color:var(--text-secondary);cursor:pointer;transition:all 0.12s;"
            onmouseover="this.style.background='var(--accent-primary)';this.style.color='#fff';this.style.borderColor='var(--accent-primary)'"
            onmouseout="this.style.background='var(--bg-primary)';this.style.color='var(--text-secondary)';this.style.borderColor='var(--border-color)'">
            \u6062\u590d
          </button>
        </div>`;
    }).join('');
  } catch (e: any) {
    listEl.innerHTML = `<span style="color:var(--text-muted);">\u52a0\u8f7d\u5931\u8d25: ${e.message}</span>`;
  }
}

export async function _waRestoreVersion(snapPath: string, targetPath: string): Promise<void> {
  if (!confirm('\u5c06\u6587\u4ef6\u6062\u590d\u5230\u8be5\u7248\u672c\uff1f\u5f53\u524d\u672a\u4fdd\u5b58\u7684\u66f4\u6539\u4f1a\u4e22\u5931\u3002')) return;
  try {
    const r = await _csrfFetch('/api/v1/workspace/restore-version', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ snap_path: snapPath, target_path: targetPath }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || '\u6062\u590d\u5931\u8d25');
    const pop = document.getElementById('wa-history-popover');
    if (pop) pop.style.display = 'none';
    showToast('\u5df2\u6062\u590d\uff0c\u6b63\u5728\u91cd\u65b0\u52a0\u8f7d\u2026', 'success');
    setTimeout(async () => {
      if (state.wsSourcePath) {
        const currentPath = state.wsSourcePath;
        await Router.load({ name: currentPath.split(/[\\/]/).pop(), _waPath: currentPath });
      }
    }, 800);
  } catch (e: any) {
    showToast('\u6062\u590d\u5931\u8d25: ' + e.message, 'error');
  }
}

// ── Recoverable file tasks ────────────────────────────────────────

export async function _listRecoverableFileTasks(status: string): Promise<RecoveryTask[]> {
  const normalizedStatus = String(status || '').trim().toLowerCase();
  if (!normalizedStatus) return [];
  const sources = ['file_task'];
  const batches = await Promise.all(sources.map(async (source) => {
    const query = new URLSearchParams({
      session_id: _waSession(),
      source,
      status: normalizedStatus,
      limit: '20',
    });
    const resp = await fetch(`/api/tasks?${query.toString()}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const payload = await resp.json();
    return payload && Array.isArray(payload.data) ? payload.data : [];
  }));
  const seen = new Set<string>();
  const tasks: RecoveryTask[] = [];
  batches.flat().forEach((task: any) => {
    const taskId = String(task && task.task_id || '').trim();
    if (!taskId || seen.has(taskId)) return;
    seen.add(taskId);
    tasks.push(task);
  });
  return tasks;
}

export async function _restoreActiveFileTasks(force: boolean = false): Promise<string[]> {
  _initWorkspaceAiRuntimes();
  if (!_waConversationRuntime || typeof _waConversationRuntime.beginAssistantTaskTurn !== 'function') return [];
  if (typeof _waConversationRuntime.syncAssistantTaskTurn !== 'function') return [];
  if (!(window as any).WA || typeof (window as any).WA.resumePersistedFileTask !== 'function') return [];

  const msgs = $('wa-ai-messages');
  if (!msgs) return [];

  const taskGroups = await Promise.all([
    _listRecoverableFileTasks('running').catch(() => []),
    _listRecoverableFileTasks('waiting').catch(() => []),
  ]);
  const candidates: any[] = [];
  const seen = new Set<string>();
  taskGroups.flat().forEach((task: any) => {
    const taskId = String(task && task.task_id || '').trim();
    if (!taskId || seen.has(taskId)) return;
    seen.add(taskId);
    candidates.push(task);
  });

  const activeIds = new Set(candidates.map((task: any) => String(task && task.task_id || '').trim()).filter(Boolean));
  Array.from(state._activeTaskReconnectors.entries()).forEach(([taskId, reconnector]: [string, any]) => {
    if (activeIds.has(taskId)) return;
    if (reconnector && typeof reconnector.close === 'function') {
      try { reconnector.close(); } catch (_) {}
    }
    state._activeTaskReconnectors.delete(taskId);
  });

  const restored: string[] = [];
  for (const task of candidates) {
    const taskId = String(task && task.task_id || '').trim();
    if (!taskId) continue;
    if (!force && state._activeTaskReconnectors.has(taskId)) continue;

    const metadata = _parseTaskMetadata(task.metadata);
    const existingTurn = _conversationTaskTurn(taskId);
    const turn = existingTurn || _waConversationRuntime.beginAssistantTaskTurn({
      content: task.status === 'waiting' ? '\u5df2\u6062\u590d\u7b49\u5f85\u786e\u8ba4\u7684\u540e\u53f0\u4efb\u52a1\u3002' : '\u5df2\u6062\u590d\u540e\u53f0\u4efb\u52a1\u3002',
      task_kind: 'file_task',
      status: task.status === 'waiting' ? 'pending' : 'streaming',
      skip_model_context: true,
      render: false,
      task_id: taskId,
      run_id: String(metadata.run_id || '').trim(),
    });
    const turnId = turn && turn.id ? turn.id : '';
    if (!turnId) continue;

    const renderedCard = _findRenderedTaskCard(taskId);
    const reconnector = (window as any).WA.resumePersistedFileTask({
      taskId,
      runId: String(metadata.run_id || '').trim(),
      initialStatus: String(task.status || '').trim().toLowerCase(),
      msgs,
      loadingEl: renderedCard,
      replay: true,
      onTaskCardSnapshot: (card: any) => {
        const terminalStatus = String(card && card.dataset && card.dataset.taskTerminalStatus || '').trim().toLowerCase();
        _waConversationRuntime.syncAssistantTaskTurn(turnId, {
          loadingEl: card,
          task_kind: 'file_task',
          status: terminalStatus === 'awaiting_confirmation' ? 'pending' : 'streaming',
          skip_model_context: true,
          task_id: taskId,
          run_id: String(card && card.dataset && card.dataset.taskRunId || metadata.run_id || '').trim(),
        });
      },
    });

    _replaceActiveTaskReconnector(taskId, reconnector);
    reconnector.then((result: any) => {
      if (state._activeTaskReconnectors.get(taskId) === reconnector) {
        state._activeTaskReconnectors.delete(taskId);
      }
      _waConversationRuntime.syncAssistantTaskTurn(turnId, {
        content: String(result && result.summary || '\u6587\u4ef6\u4efb\u52a1\u6d41\u5df2\u5b8c\u6210\u3002').trim() || '\u6587\u4ef6\u4efb\u52a1\u6d41\u5df2\u5b8c\u6210\u3002',
        loadingEl: result && result.loadingEl ? result.loadingEl : _findRenderedTaskCard(taskId),
        task_kind: 'file_task',
        status: String(result && result.status || 'done').trim() || 'done',
        skip_model_context: true,
        task_id: taskId,
        run_id: String(result && result.run_id || metadata.run_id || '').trim(),
      });
    }).catch((error: any) => {
      if (state._activeTaskReconnectors.get(taskId) === reconnector) {
        state._activeTaskReconnectors.delete(taskId);
      }
      _waConversationRuntime.syncAssistantTaskTurn(turnId, {
        content: `\u4efb\u52a1\u6d41\u5931\u8d25\uff1a${error && error.message ? error.message : error}`,
        loadingEl: _findRenderedTaskCard(taskId),
        task_kind: 'file_task',
        status: 'error',
        skip_model_context: true,
        task_id: taskId,
        run_id: String(metadata.run_id || '').trim(),
      });
    });
    restored.push(taskId);
  }

  return restored;
}

// ── Chart image wrapping ──────────────────────────────────────────
export function _makeWAChartImageWrap(imgSrc: string, fileName: string): HTMLElement {
  const imgWrap = document.createElement('div');
  imgWrap.className = 'wa-msg ai wa-chart-img-wrap';
  const img = document.createElement('img');
  img.className = 'wa-chart-img';
  img.src = imgSrc;
  img.alt = fileName || 'chart.png';
  img.draggable = false;
  _preUploadChartImage(imgSrc, img);
  imgWrap.appendChild(img);
  const bar = document.createElement('div');
  bar.className = 'wa-chart-img-bar';
  const openBtn = document.createElement('button');
  openBtn.className = 'wa-action-btn secondary';
  openBtn.textContent = '\u67e5\u770b';
  openBtn.title = '\u5728\u65b0\u6807\u7b7e\u9875\u6253\u5f00\uff08\u53ef\u76f4\u63a5\u53f3\u952e\u590d\u5236\uff09';
  openBtn.addEventListener('click', () => {
    const src = img.dataset.serverUrl || imgSrc;
    if (src.startsWith('data:')) {
      try {
        const [head, b64] = src.split(',');
        const mimeType = head.split(':')[1].split(';')[0];
        const binary = atob(b64);
        const arr = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) arr[i] = binary.charCodeAt(i);
        const blob = new Blob([arr], { type: mimeType });
        const blobUrl = URL.createObjectURL(blob);
        window.open(blobUrl, '_blank');
        setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
      } catch (_) { window.open(src, '_blank'); }
    } else {
      window.open(src, '_blank');
    }
  });
  const dlBtn = document.createElement('button');
  dlBtn.className = 'wa-action-btn';
  dlBtn.innerHTML = _DOWNLOAD_SVG + ' \u5b58\u5165\u5de5\u4f5c\u533a';
  dlBtn.title = '\u4fdd\u5b58\u5230\u5de5\u4f5c\u533a images/ \u6587\u4ef6\u5939';
  dlBtn.addEventListener('click', () => {
    const serverUrl = img.dataset.serverUrl;
    if (!serverUrl) {
      dlBtn.textContent = '\u23f3 \u4e0a\u4f20\u4e2d\u2026';
      dlBtn.disabled = true;
      _csrfFetch('/api/v1/workspace/upload_image', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: imgSrc }),
      })
        .then(r => r.ok ? r.json() : Promise.reject(r.status))
        .then(res => {
          if (res && res.url) img.dataset.serverUrl = res.url;
          return _csrfFetch('/api/v1/workspace/save_to_workspace', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: 'image', src_url: res.url, filename: fileName || 'chart.png' }),
          });
        })
        .then(r => r.ok ? r.json() : Promise.reject(r.status))
        .then(res => {
          showToast(`\u5df2\u5b58\u5165\u5de5\u4f5c\u533a: ${res.ws_path}`, 'success');
          _renderMyWorkspace();
        })
        .catch(() => showToast('\u4fdd\u5b58\u5931\u8d25\uff0c\u8bf7\u91cd\u8bd5', 'error'))
        .finally(() => { dlBtn.innerHTML = _DOWNLOAD_SVG + ' \u5b58\u5165\u5de5\u4f5c\u533a'; dlBtn.disabled = false; });
      return;
    }
    dlBtn.textContent = '\u23f3 \u4fdd\u5b58\u4e2d\u2026';
    dlBtn.disabled = true;
    _csrfFetch('/api/v1/workspace/save_to_workspace', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'image', src_url: serverUrl, filename: fileName || 'chart.png' }),
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(res => {
        showToast(`\u5df2\u5b58\u5165\u5de5\u4f5c\u533a: ${res.ws_path}`, 'success');
        _renderMyWorkspace();
      })
      .catch(() => showToast('\u4fdd\u5b58\u5931\u8d25\uff0c\u8bf7\u91cd\u8bd5', 'error'))
      .finally(() => { dlBtn.innerHTML = _DOWNLOAD_SVG + ' \u5b58\u5165\u5de5\u4f5c\u533a'; dlBtn.disabled = false; });
  });
  bar.appendChild(openBtn);
  bar.appendChild(dlBtn);
  imgWrap.appendChild(bar);
  return imgWrap;
}

function _preUploadChartImage(imgSrc: string, imgEl: HTMLImageElement): void {
  if (!imgSrc || !imgSrc.startsWith('data:image/')) return;
  _csrfFetch('/api/v1/workspace/upload_image', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ data: imgSrc }),
  })
    .then(r => r.ok ? r.json() : null)
    .then(res => {
      if (res && res.url && imgEl) {
        imgEl.dataset.serverUrl = res.url;
      }
    })
    .catch(() => {});
}

// ── Code result handling ──────────────────────────────────────────
export function _handleCodeResult(result: any): void {
  const msgs = $('wa-ai-messages');
  const last = msgs!.lastElementChild as HTMLElement;
  if (last && last.classList.contains('streaming')) {
    last.classList.remove('streaming');
    if (!last.textContent!.trim()) last.remove();
  }
  if (result.error) {
    const errDiv = document.createElement('div');
    errDiv.className = 'wa-msg ai';
    errDiv.textContent = `\u6267\u884c\u9519\u8bef\uff1a${result.error}`;
    if (result.stderr) errDiv.textContent += `\n\n${result.stderr}`;
    msgs!.appendChild(errDiv);
  } else if (result.stdout) {
    const outDiv = document.createElement('div');
    outDiv.className = 'wa-msg-code';
    outDiv.textContent = result.stdout;
    msgs!.appendChild(outDiv);
  }
  const files = result.files || {};
  const fileNames = Object.keys(files);
  if (fileNames.length > 0) {
    fileNames.forEach(fname => {
      msgs!.appendChild(_makeWAChartImageWrap(files[fname], fname));
    });
  } else if (!result.error) {
    const okDiv = document.createElement('div');
    okDiv.className = 'wa-msg ai';
    okDiv.textContent = '\u4ee3\u7801\u6267\u884c\u5b8c\u6210\uff0c\u4f46\u672a\u751f\u6210\u56fe\u7247\u6587\u4ef6\u3002\u8bf7\u786e\u4fdd\u4ee3\u7801\u4e2d\u6709 plt.savefig("chart.png") \u6216 ggsave("chart.png")\u3002';
    msgs!.appendChild(okDiv);
  }
  msgs!.scrollTop = msgs!.scrollHeight;
}

// ── Backward compat ──
if (typeof window !== 'undefined') {
  (window as any).WA = (window as any).WA || {};
  (window as any).WA.getUnsavedTabs = getUnsavedTabs;
  (window as any).WA.showCloseWarning = showCloseWarning;
  (window as any).WA._closeWarnCancel = _closeWarnCancel;
  (window as any).WA._closeWarnDiscard = _closeWarnDiscard;
  (window as any).WA._closeWarnSaveAll = _closeWarnSaveAll;
  (window as any).WA.toggleArchivePopover = toggleArchivePopover;
  (window as any).WA.archiveCurrent = archiveCurrent;
  (window as any).WA.toggleHistoryPopover = toggleHistoryPopover;
  (window as any)._waRestoreVersion = _waRestoreVersion;
  (window as any).WA.scheduleAutoSave = scheduleAutoSave;
  (window as any).WA.autoSave = autoSave;
  (window as any).WA.saveFile = saveFile;
  (window as any).WA.saveAs = saveAs;
  (window as any).WA.makeChartImageWrap = _makeWAChartImageWrap;
}
