/**
 * File Utilities — close-warning, recoverable task persistence, chart image
 * wrapping.
 * Workspace file utilities and task recovery helpers.
 */

import {
  fileTaskTerminalUiStatus,
  isFileTaskAttentionStatus,
  isFileTaskConfirmationStatus,
  normalizeFileTaskTerminalStatus,
} from './file-task-status';

declare function $(id: string): HTMLElement | null;
declare var state: any;
declare var _DOWNLOAD_SVG: string;
declare var _EXT_ICON: Record<string, string>;
declare var _DEFAULT_FILE_SVG: string;
declare var _FOLDER_PICK_SVG: string;
declare var _waConversationRuntime: any;
declare var _waTaskDispatcher: any;

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
declare function _stableWorkspaceSnapshot(value: any): string;
declare function _switchToTab(path: string): Promise<void>;

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

// ── Before unload warning ──────────────────────────────────────────
function _snapshot(value: any): string {
  const helper = (window as any).WA && (window as any).WA._stableWorkspaceSnapshot;
  if (typeof helper === 'function') return helper(value);
  if (typeof _stableWorkspaceSnapshot === 'function') return _stableWorkspaceSnapshot(value);
  if (value === undefined) return 'undefined';
  if (value === null) return 'null';
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value); } catch (_) { return String(value); }
}

function _isWritableUnsavedCandidate(tab: any): boolean {
  if (!tab || !tab.modified) return false;
  const type = String(tab.fileType || '').toLowerCase();
  if (!tab.fileId || type === 'pdf' || type === 'image') return false;
  return true;
}

function _currentSnapshotForTab(tab: any): string {
  const isActive = tab && tab.path === state.activeTabPath && !!state.activeEditor;
  if (isActive) return _snapshot(_serializeEditorForTab(tab, state.activeEditor));
  if (tab && tab.cache !== undefined && tab.cache !== null) return _snapshot(tab.cache);
  return _snapshot(tab ? tab.serverData : null);
}

function _notifyDesktopModified(tab: any, modified: boolean): void {
  const waNotify = (window as any).WA && (window as any).WA._notifyPyModified;
  if (typeof waNotify === 'function') {
    try { waNotify(tab, modified); return; } catch (_) {}
  }
  if (typeof _notifyPyModified === 'function') {
    try { _notifyPyModified(tab, modified); } catch (_) {}
  }
}

export function isTabActuallyUnsaved(tab: any): boolean {
  if (!_isWritableUnsavedCandidate(tab)) return false;
  const currentSnapshot = _currentSnapshotForTab(tab);
  const savedSnapshot = tab.savedSnapshot !== undefined && tab.savedSnapshot !== null
    ? String(tab.savedSnapshot)
    : _snapshot(tab.serverData);
  return currentSnapshot !== savedSnapshot;
}

function _syncFalsePositiveDirtyTabs(): void {
  let changed = false;
  state.openTabs.forEach((tab: any) => {
    if (tab && tab.modified && !isTabActuallyUnsaved(tab)) {
      tab.modified = false;
      _notifyDesktopModified(tab, false);
      changed = true;
    }
  });
  if (changed) _renderTabs();
}

window.addEventListener('beforeunload', (e) => {
  if (getUnsavedTabs().length > 0) {
    e.preventDefault();
    (e as any).returnValue = '';
  }
});

// ── Close-warning API ─────────────────────────────────────────────

export function getUnsavedTabs(): UnsavedTab[] {
  _syncFalsePositiveDirtyTabs();
  return state.openTabs.filter(isTabActuallyUnsaved).map((t: any) => ({ path: t.path, name: t.name }));
}

export function showCloseWarning(unsavedTabs: UnsavedTab[]): Promise<string> {
  return new Promise((resolve) => {
    const actualUnsavedTabs = getUnsavedTabs();
    if (actualUnsavedTabs.length === 0) {
      resolve('discard');
      return;
    }
    const overlay = $('wa-close-warn-overlay');
    const dialogEl = $('wa-close-warn-dialog');
    const listEl = $('wa-close-warn-list');
    const countEl = $('wa-close-warn-count');
    if (!overlay || !dialogEl || !listEl) {
      console.warn('[CloseWarn] Missing close-warning dialog DOM; cancelling close to protect unsaved edits.');
      showToast('关闭确认窗口未准备好，已取消关闭以保护未保存修改。', 'warning');
      resolve('cancel');
      return;
    }
    if (overlay.parentElement !== document.body) {
      document.body.appendChild(overlay);
    }
    if (!dialogEl.dataset.closeWarnBound) {
      dialogEl.dataset.closeWarnBound = '1';
      dialogEl.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          _closeWarnCancel();
          return;
        }
        if (event.key === 'Tab') {
          _trapCloseWarnFocus(event);
        }
      });
    }
    if (countEl) countEl.textContent = `${actualUnsavedTabs.length} \u4e2a\u672a\u4fdd\u5b58\u6587\u4ef6`;
    listEl.innerHTML = actualUnsavedTabs.map(_renderCloseWarnItem).join('');
    (overlay as any)._lastFocus = document.activeElement || null;
    overlay.style.display = 'flex';
    overlay.setAttribute('aria-hidden', 'false');
    (overlay as any)._resolve = resolve;
    requestAnimationFrame(() => dialogEl.focus());
  });
}

function _trapCloseWarnFocus(event: KeyboardEvent): void {
  const dialogEl = $('wa-close-warn-dialog') as HTMLElement | null;
  if (!dialogEl) return;
  const focusable = Array.from(
    dialogEl.querySelectorAll<HTMLElement>('button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'),
  ).filter((el) => !el.hasAttribute('disabled') && el.offsetParent !== null);
  if (focusable.length === 0) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const active = document.activeElement as HTMLElement | null;
  if (event.shiftKey && active === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && active === last) {
    event.preventDefault();
    first.focus();
  }
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
  if (overlay) {
    overlay.style.display = 'none';
    overlay.setAttribute('aria-hidden', 'true');
  }
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
  overlay.setAttribute('aria-busy', busy ? 'true' : 'false');
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
  const modifiedTabs = state.openTabs.filter(isTabActuallyUnsaved);
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
        tab.savedSnapshot = _snapshot(data);
        if (tab.fileType !== 'docx') tab.cache = data;
        _notifyDesktopModified(tab, false);
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
    const taskStatus = normalizeFileTaskTerminalStatus(task.status || '');
    const terminalStatus = normalizeFileTaskTerminalStatus(metadata.task_terminal_status || metadata.terminal_status || metadata.status || taskStatus);
    const awaitingConfirmation = isFileTaskConfirmationStatus(terminalStatus);
    const needsAttention = isFileTaskAttentionStatus(terminalStatus);
    const existingTurn = _conversationTaskTurn(taskId);
    const turn = existingTurn || _waConversationRuntime.beginAssistantTaskTurn({
      content: awaitingConfirmation ? '\u5df2\u6062\u590d\u7b49\u5f85\u786e\u8ba4\u7684\u540e\u53f0\u4efb\u52a1\u3002' : (needsAttention || taskStatus === 'waiting' ? '\u5df2\u6062\u590d\u5f85\u5904\u7406\u7684\u540e\u53f0\u4efb\u52a1\u3002' : '\u5df2\u6062\u590d\u540e\u53f0\u4efb\u52a1\u3002'),
      task_kind: 'file_task',
      status: needsAttention || awaitingConfirmation || taskStatus === 'waiting' ? 'pending' : 'streaming',
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
      initialStatus: terminalStatus || taskStatus,
      msgs,
      loadingEl: renderedCard,
      replay: true,
      onTaskCardSnapshot: (card: any) => {
        const terminalStatus = normalizeFileTaskTerminalStatus(card && card.dataset && card.dataset.taskTerminalStatus || '');
        const completedTask = String(card && card.dataset && card.dataset.taskCompleted || '').trim().toLowerCase() === 'true';
        const uiStatus = fileTaskTerminalUiStatus(terminalStatus, completedTask);
        _waConversationRuntime.syncAssistantTaskTurn(turnId, {
          loadingEl: card,
          task_kind: 'file_task',
          status: uiStatus === 'done' ? 'done' : (uiStatus === 'error' ? 'failed' : (uiStatus === 'cancelled' ? 'cancelled' : 'pending')),
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
        content: String(result && result.summary || '\u6587\u4ef6\u4efb\u52a1\u6d41\u5df2\u7ed3\u675f\u3002').trim() || '\u6587\u4ef6\u4efb\u52a1\u6d41\u5df2\u7ed3\u675f\u3002',
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
  (window as any).WA.isTabActuallyUnsaved = isTabActuallyUnsaved;
  (window as any).WA.showCloseWarning = showCloseWarning;
  (window as any).WA._closeWarnCancel = _closeWarnCancel;
  (window as any).WA._closeWarnDiscard = _closeWarnDiscard;
  (window as any).WA._closeWarnSaveAll = _closeWarnSaveAll;
  (window as any).WA.makeChartImageWrap = _makeWAChartImageWrap;
}
