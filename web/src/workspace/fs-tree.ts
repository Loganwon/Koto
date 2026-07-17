/**
 * File System Browser — Tree rendering, search, browse, live polling, file loader.
 * Workspace file tree.
 */

import { _fileIcon, _escHtml, showToast, _FOLDER_OPEN_SVG, _FOLDER_PICK_SVG, _FOLDER_SVG } from './infrastructure';
import { state, _forgetRecentPath, _trackUserOpen, loadRecentFiles, BrowserNode } from './state';
import { getWorkspaceApi } from '../shared/workspace-api';

const workspaceApi = getWorkspaceApi();
let fileBrowserLoadPromise: Promise<void> | null = null;


export interface SortConfig {
  sortKey: string;
  order: string[];
}

export interface SearchResult {
  name: string;
  path: string;
  category?: string;
  ext?: string;
  size_bytes?: number;
}

export interface FsTreeOptions {
  workspacePath?: string;
}

// ── More Button SVG ──

const _MORE_BTN_SVG = `<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><circle cx="8" cy="2.5" r="1.5"/><circle cx="8" cy="8" r="1.5"/><circle cx="8" cy="13.5" r="1.5"/></svg>`;
const _SEND_AI_SVG = `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2.2l.9 2.5 2.6.9-2.6.9L8 9l-.9-2.5-2.6-.9 2.6-.9L8 2.2z"/><path d="M12.3 9.7l.45 1.2 1.25.45-1.25.45-.45 1.2-.45-1.2-1.25-.45 1.25-.45.45-1.2z"/></svg>`;

// ── Extension Support ──

function _isSupportedExt(ext: string): boolean {
  const s = new Set([
    'docx', 'xlsx', 'pptx', 'pdf',
    'txt', 'md', 'markdown', 'csv',
    'py', 'js', 'ts', 'json', 'html', 'css', 'xml',
    'sh', 'bash', 'yaml', 'yml',
    'c', 'cpp', 'h', 'hpp', 'java', 'rb', 'go',
    'rs', 'cs', 'php', 'swift', 'kt', 'r', 'sql',
    'toml', 'ini', 'cfg', 'conf',
    'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'svg',
  ]);
  return s.has((ext || '').toLowerCase().replace(/^\./, ''));
}

function _formatSize(bytes: number): string {
  if (!bytes || bytes < 0) return '';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}

// ── CSRF Fetch ──

function _csrfFetch(url: string, options: any = {}): Promise<Response> {
  if (typeof workspaceApi._csrfFetch === 'function') {
    return workspaceApi._csrfFetch(url, options);
  }
  return fetch(url, options);
}

function _safeJson(res: Response): Promise<any> {
  return res.json().catch(() => ({}));
}

// ── Browser Sort ──

export function _applyBrowserSort(entries: BrowserNode[]): BrowserNode[] {
  if (!entries || !Array.isArray(entries)) return entries;
  const isF = (e: BrowserNode) => e.type === 'folder' || e.type === 'drive' || e.type === 'quick';
  const folders = entries.filter(isF);
  const files = entries.filter((e) => !isF(e));
  const sortKey = state._browserSort || 'name';
  const cmp = (a: BrowserNode, b: BrowserNode) => {
    if (sortKey === 'date') return (b.mtime || 0) - (a.mtime || 0);
    if (sortKey === 'type') {
      const ec = (a.ext || '').localeCompare(b.ext || '');
      if (ec !== 0) return ec;
    }
    return a.name.localeCompare(b.name, 'zh');
  };
  return [...folders.sort((a, b) => a.name.localeCompare(b.name, 'zh')), ...files.sort(cmp)];
}

// ── Path Helpers ──

function _joinWorkspacePath(root: string, relPath: string): string {
  const rootText = String(root || '').replace(/[\\/]+$/, '');
  const relText = String(relPath || '').replace(/^[\\/]+/, '');
  if (!rootText) return relText;
  return rootText + '\\' + relText.replace(/\//g, '\\');
}

function _flattenWorkspaceListFiles(nodes: any[], workspacePath: string, out: SearchResult[] = []): SearchResult[] {
  (Array.isArray(nodes) ? nodes : []).forEach((node) => {
    if (!node || typeof node !== 'object') return;
    if (node.type === 'folder') {
      _flattenWorkspaceListFiles(node.children || [], workspacePath, out);
      return;
    }
    if (node.type !== 'file') return;
    const path = _joinWorkspacePath(workspacePath, node.path || node.name || '');
    out.push({
      name: node.name || (path.split(/[\\/]/).pop() || path),
      path,
      category: node.category || '',
      ext: node.ext || '',
      size_bytes: Number(node.size_bytes || 0) || 0,
    });
  });
  return out;
}

export function _isAbsolutePath(rawPath: string): boolean {
  return /^(?:[a-zA-Z]:[\\/]|\/|\\\\)/.test(String(rawPath || '').trim());
}

export function _isInsideWorkspace(rawPath: string): boolean {
  const raw = String(rawPath || '').replace(/\\/g, '/');
  const root = String(state._workspacePath || '').replace(/\\/g, '/').replace(/\/+$/, '');
  return !!root && (raw === root || raw.startsWith(root + '/'));
}

export function _workspaceRelativePath(rawPath: string): string {
  const raw = String(rawPath || '').trim();
  if (!raw) return '';
  const normalized = raw.replace(/\\/g, '/');
  const workspaceRoot = String(state._workspacePath || '').replace(/\\/g, '/').replace(/\/+$/, '');
  if (workspaceRoot && (normalized === workspaceRoot || normalized.startsWith(workspaceRoot + '/'))) {
    return normalized.slice(workspaceRoot.length).replace(/^\/+/, '');
  }
  return normalized.replace(/^\/+/, '').replace(/^workspace\//i, '');
}

function _mergeSearchResults(indexedResults: SearchResult[], liveResults: SearchResult[], limit: number = 60): SearchResult[] {
  const seen = new Set<string>();
  const merged: SearchResult[] = [];
  [...(indexedResults || []), ...(liveResults || [])].forEach((file: any) => {
    const key = String((file && (file.path || file.name)) || '').toLowerCase();
    if (!key || seen.has(key)) return;
    seen.add(key);
    merged.push(file);
  });
  return merged.slice(0, limit);
}

function _entrySearchCategory(entry: Partial<BrowserNode | SearchResult>): string {
  const rawCategory = String(entry.category || '').toLowerCase();
  const ext = String(entry.ext || (entry.name || '').split('.').pop() || '').replace(/^\./, '').toLowerCase();
  if (['doc', 'docx', 'pdf', 'txt', 'md', 'markdown'].includes(ext) || ['docx', 'pdf', 'text', '文档'].includes(rawCategory)) return '文档';
  if (['xls', 'xlsx', 'csv'].includes(ext) || ['xlsx', 'spreadsheet', '表格'].includes(rawCategory)) return '表格';
  if (['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'svg'].includes(ext) || ['image', '图片'].includes(rawCategory)) return '图片';
  if (['py', 'js', 'ts', 'json', 'html', 'css', 'xml', 'yaml', 'yml', 'sql'].includes(ext) || ['code', '代码'].includes(rawCategory)) return '代码';
  return '其他';
}

function _fileDragAttrs(): string {
  return 'draggable="true" data-wa-file-draggable="true"';
}

function _fileOpenHitDragAttrs(): string {
  return 'data-wa-file-action="open"';
}

function _fileActionButtons(supported: boolean): string {
  const isolatedPressAttrs = 'draggable="false"';
  const sendButton = supported
    ? `<button type="button" class="wa-file-send-ai" data-wa-file-action="send-ai" ${isolatedPressAttrs} title="发送给 AI" aria-label="发送给 AI">${_SEND_AI_SVG}</button>`
    : '';
  return (
    `<div class="wa-file-actions">` +
    sendButton +
    `<button type="button" class="wa-file-more" data-wa-file-action="more" ${isolatedPressAttrs} title="更多操作" aria-label="更多操作">${_MORE_BTN_SVG}</button>` +
    `</div>`
  );
}

function _browserFileDragStart(event: DragEvent, el: HTMLElement): void {
  const path = String((el && el.dataset && el.dataset.path) || '').trim();
  if (!path || !event.dataTransfer) return;
  event.dataTransfer.effectAllowed = 'copy';
  event.dataTransfer.setData('application/wa-file-path', path);
  event.dataTransfer.setData('text/plain', path);
  el.classList.add('dragging');
  document.body.classList.add('wa-file-dragging');
}

async function _attachBrowserFileToAI(path: string, source: string): Promise<void> {
  const normalized = String(path || '').trim();
  if (!normalized) return;
  const attachFilesToTask = workspaceApi.attachFilesToTask;
  if (typeof attachFilesToTask !== 'function') {
    showToast('AI 助手未就绪', 'error');
    return;
  }
  await attachFilesToTask([normalized], { source, focusInput: !_isAiSessionListVisible() });
  _focusVisibleAIComposer();
}

async function _sendBrowserFileToAI(path: string): Promise<void> {
  const normalized = String(path || '').trim();
  if (!normalized) return;
  try {
    await _attachBrowserFileToAI(normalized, 'file_tree_inline_action');
  } catch (error: any) {
    console.warn('[WA] send browser file to AI failed:', error);
    showToast(error && error.message ? error.message : '发送给 AI 失败', 'error');
  }
}

let _lastBrowserFileSendPath = '';
let _lastBrowserFileSendAt = 0;

function _sendBrowserFileButtonToAI(event: Event, button: HTMLElement | null): void {
  if (event) {
    event.preventDefault();
    event.stopPropagation();
  }
  const row = button ? button.closest('.wa-file-item') as HTMLElement | null : null;
  const path = String(row && row.dataset ? row.dataset.path || '' : '').trim();
  if (!path) {
    showToast('缺少文件路径，无法发送给 AI', 'error');
    return;
  }
  const now = Date.now();
  if (path === _lastBrowserFileSendPath && now - _lastBrowserFileSendAt < 700) return;
  _lastBrowserFileSendPath = path;
  _lastBrowserFileSendAt = now;
  _sendBrowserFileToAI(path).catch((error) => {
    console.warn('[WA] send browser file button to AI failed:', error);
    showToast(error && error.message ? error.message : '发送给 AI 失败', 'error');
  });
}

let _browserFileActionDelegationInstalled = false;

function _installBrowserFileActionDelegation(): void {
  if (_browserFileActionDelegationInstalled) return;
  _browserFileActionDelegationInstalled = true;
  document.addEventListener('pointerdown', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const row = target ? target.closest('.wa-file-item') as HTMLElement | null : null;
    if (!row) return;
    if (target?.closest('[data-wa-file-action], .wa-file-check')) {
      event.stopPropagation();
      return;
    }
    if (row.classList.contains('file') && typeof workspaceApi._browserFileRowPointerDown === 'function') {
      workspaceApi._browserFileRowPointerDown(event, row);
    }
  }, true);
  document.addEventListener('mousedown', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const row = target ? target.closest('.wa-file-item.file') as HTMLElement | null : null;
    if (!row || target?.closest('[data-wa-file-action], .wa-file-check')) return;
    if (typeof workspaceApi._browserFileRowMouseDown === 'function') {
      workspaceApi._browserFileRowMouseDown(event, row);
    }
  }, true);
  document.addEventListener('dragstart', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const row = target ? target.closest('.wa-file-item.file') as HTMLElement | null : null;
    if (row) _browserFileDragStart(event, row);
  }, true);
  document.addEventListener('dragend', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const row = target ? target.closest('.wa-file-item.file') as HTMLElement | null : null;
    if (row) _browserFileDragEnd(event, row);
  }, true);
  document.addEventListener('contextmenu', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const row = target ? target.closest('.wa-file-item') as HTMLElement | null : null;
    if (!row || typeof workspaceApi._showBrowserCtx !== 'function') return;
    event.preventDefault();
    event.stopPropagation();
    workspaceApi._showBrowserCtx(event, row);
  }, true);
  document.addEventListener('dragover', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const row = target ? target.closest('.wa-file-item.folder') as HTMLElement | null : null;
    if (!row) return;
    event.preventDefault();
    event.stopPropagation();
    row.classList.add('wa-drop-target');
  }, true);
  document.addEventListener('dragleave', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    target?.closest('.wa-file-item.folder')?.classList.remove('wa-drop-target');
  }, true);
  document.addEventListener('drop', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const row = target ? target.closest('.wa-file-item.folder') as HTMLElement | null : null;
    if (!row || typeof workspaceApi._dropOntoFolder !== 'function') return;
    event.preventDefault();
    event.stopPropagation();
    row.classList.remove('wa-drop-target');
    workspaceApi._dropOntoFolder(event, row.dataset.path);
  }, true);
  document.addEventListener('click', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const sendButton = target ? target.closest('.wa-file-send-ai[data-wa-file-action="send-ai"]') as HTMLElement | null : null;
    if (sendButton) {
      _sendBrowserFileButtonToAI(event, sendButton);
      return;
    }
    const actionTarget = target ? target.closest<HTMLElement>('[data-wa-file-action]') : null;
    if (actionTarget) {
      const row = actionTarget.closest('.wa-file-item') as HTMLElement | null;
      const action = actionTarget.dataset.waFileAction;
      event.preventDefault();
      event.stopPropagation();
      if (action === 'more' && row && typeof workspaceApi._showBrowserCtx === 'function') workspaceApi._showBrowserCtx(event, row);
      else if (action === 'open' && row && typeof workspaceApi.openBrowserFile === 'function') workspaceApi.openBrowserFile(row.dataset.path, true);
      else if (action === 'clear-search' && typeof workspaceApi.clearSearch === 'function') workspaceApi.clearSearch();
      return;
    }
    const checkbox = target ? target.closest<HTMLInputElement>('.wa-file-check') : null;
    if (checkbox && typeof workspaceApi._toggleBrowserCheck === 'function') {
      event.stopPropagation();
      // The browser toggles a checkbox after its click handler.  Reflect the
      // selection on the next task so the Set sees the final checked state.
      window.setTimeout(() => workspaceApi._toggleBrowserCheck(checkbox), 0);
      return;
    }
    const row = target ? target.closest('.wa-file-item') as HTMLElement | null : null;
    if (!row) return;
    if (row.classList.contains('folder') && typeof workspaceApi.handleBrowserFolderClick === 'function') {
      workspaceApi.handleBrowserFolderClick(event, row);
    } else if (row.classList.contains('file') && typeof workspaceApi._browserFileRowClick === 'function') {
      workspaceApi._browserFileRowClick(event, row);
    }
  }, true);
}

function _browserFileDragEnd(event: DragEvent, el: HTMLElement): void {
  const path = String((el && el.dataset && el.dataset.path) || '').trim();
  if (el) el.classList.remove('dragging');
  document.body.classList.remove('wa-file-dragging');
  const x = Number(event && event.clientX);
  const y = Number(event && event.clientY);
  if (!path || !Number.isFinite(x) || !Number.isFinite(y) || !_isPointInsideAIPanel(x, y)) return;
  _suppressBrowserRowClickUntil = Date.now() + 450;
  _attachBrowserFileToAI(path, 'file_tree_dragend_drop').catch((error) => {
    console.warn('[WA] file dragend drop failed:', error);
  });
}

let _browserPointerDrag: {
  path: string;
  supported: boolean;
  el: HTMLElement;
  startX: number;
  startY: number;
  active: boolean;
} | null = null;
let _suppressBrowserRowClickUntil = 0;

function _isAiSessionListVisible(): boolean {
  const listView = document.getElementById('wa-ai-session-list-view');
  return !!listView && !listView.hidden;
}

function _focusVisibleAIComposer(): void {
  const input = document.getElementById('wa-user-input') as HTMLInputElement | null;
  if (input) setTimeout(() => input.focus(), 120);
}

function _isPointInsideAIPanel(x: number, y: number): boolean {
  const target = document.elementFromPoint(x, y) as HTMLElement | null;
  if (target && target.closest('#wa-ai, #wa-ai-session-list-composer, #wa-ai-input-area, #wa-ai-file-drop')) return true;
  const aiPanel = document.getElementById('wa-ai');
  if (!aiPanel) return false;
  const rect = aiPanel.getBoundingClientRect();
  return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
}

function _endBrowserPointerDrag(): void {
  if (_browserPointerDrag && _browserPointerDrag.el) _browserPointerDrag.el.classList.remove('dragging');
  _browserPointerDrag = null;
  document.body.classList.remove('wa-file-dragging');
}

function _isBrowserFileActionTarget(target: EventTarget | null): boolean {
  const el = target instanceof Element ? target : null;
  return !!(el && el.closest('.wa-file-actions, .wa-file-check, input, select, textarea, a'));
}

function _startBrowserPointerDrag(event: MouseEvent | PointerEvent, el: HTMLElement): void {
  if (!el || event.button !== 0 || state.selectMode) return;
  if (_isBrowserFileActionTarget(event.target)) return;
  const path = String(el.dataset.path || '').trim();
  if (!path) return;
  _browserPointerDrag = {
    path,
    supported: el.dataset.supported !== 'false',
    el,
    startX: event.clientX,
    startY: event.clientY,
    active: false,
  };
}

function _onBrowserPointerMove(event: MouseEvent | PointerEvent): void {
  const drag = _browserPointerDrag;
  if (!drag) return;
  if (!drag.active) {
    const dx = event.clientX - drag.startX;
    const dy = event.clientY - drag.startY;
    if (Math.sqrt(dx * dx + dy * dy) < 8) return;
    drag.active = true;
    drag.el.classList.add('dragging');
    document.body.classList.add('wa-file-dragging');
  }
}

async function _onBrowserPointerUp(event: MouseEvent | PointerEvent): Promise<void> {
  const drag = _browserPointerDrag;
  if (!drag) return;
  const shouldAttach = drag.active && drag.supported && _isPointInsideAIPanel(event.clientX, event.clientY);
  _endBrowserPointerDrag();
  if (!shouldAttach) return;
  event.preventDefault();
  event.stopPropagation();
  _suppressBrowserRowClickUntil = Date.now() + 450;
  await _attachBrowserFileToAI(drag.path, 'file_tree_pointer_drop');
}

function _installBrowserPointerDragFallback(): void {
  if ((window as any)._waBrowserPointerDragFallbackInstalled) return;
  (window as any)._waBrowserPointerDragFallbackInstalled = true;
  document.addEventListener('mousemove', (event) => _onBrowserPointerMove(event));
  document.addEventListener('pointermove', (event) => _onBrowserPointerMove(event));
  document.addEventListener('mouseup', (event) => {
    _onBrowserPointerUp(event).catch((error) => {
      console.warn('[WA] file pointer drop failed:', error);
      _endBrowserPointerDrag();
    });
  }, true);
  document.addEventListener('pointerup', (event) => {
    _onBrowserPointerUp(event).catch((error) => {
      console.warn('[WA] file pointer drop failed:', error);
      _endBrowserPointerDrag();
    });
  }, true);
}

function _searchCachedBrowserEntries(query: string, category: string, limit: number = 60): SearchResult[] {
  const q = String(query || '').trim().toLowerCase();
  const cat = String(category || '').trim();
  if (!q && !cat) return [];
  const seen = new Set<string>();
  const out: SearchResult[] = [];
  const visit = (entry: BrowserNode | null | undefined) => {
    if (!entry || out.length >= limit) return;
    const isFolder = entry.type === 'folder' || entry.type === 'drive' || entry.type === 'quick';
    if (isFolder) {
      (entry.children || []).forEach(visit);
      const cached = state._browserCache[_browserPathKey(entry.path)];
      if (Array.isArray(cached)) cached.forEach(visit);
      return;
    }
    if (entry.type !== 'file') return;
    const rawPath = String(entry.path || '').trim();
    const path = rawPath && !_isAbsolutePath(rawPath) ? _joinWorkspacePath(state._workspacePath || '', rawPath) : rawPath;
    const name = String(entry.name || path.split(/[\\/]/).pop() || '').trim();
    const haystack = `${name} ${path}`.toLowerCase();
    if (q && !haystack.includes(q)) return;
    const normalizedCategory = _entrySearchCategory(entry);
    if (cat && normalizedCategory !== cat) return;
    const key = (path || name).toLowerCase();
    if (!key || seen.has(key)) return;
    seen.add(key);
    out.push({
      name,
      path,
      category: normalizedCategory,
      ext: entry.ext || (name.includes('.') ? name.split('.').pop() : ''),
      size_bytes: Number((entry as any).size_bytes || 0) || 0,
    });
  };
  const roots = state._browserRoots;
  (roots?.quick_access || []).forEach(visit);
  (roots?.drives || []).forEach(visit);
  return out.slice(0, limit);
}

export function _displayFileName(rawPath: string, fallback: string = '文件'): string {
  return String(rawPath || fallback).split(/[\\/]/).pop() || fallback;
}

function _browserPathKey(rawPath: string): string {
  return String(rawPath || '').trim().replace(/[\\/]+$/, '');
}

async function _loadBrowserFolderEntries(absPath: string): Promise<any[]> {
  const path = String(absPath || '').trim();
  const key = _browserPathKey(path);
  if (!path || !key) return [];
  state._browserLoading = state._browserLoading || {};
  if (state._browserLoading[key] !== undefined) return state._browserLoading[key];
  state._browserLoading[key] = fetch('/api/v1/workspace/browse_local?path=' + encodeURIComponent(path), { cache: 'no-store' })
    .then(async (res) => {
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || '无法读取文件夹');
      return data.entries || [];
    })
    .finally(() => {
      delete state._browserLoading[key];
    });
  return state._browserLoading[key];
}

// ── Live Search ──

async function _searchLiveWorkspaceFiles(query: string, category: string, limit?: number): Promise<SearchResult[]> {
  const q = String(query || '').trim().toLowerCase();
  if (!q) return [];
  try {
    const res = await fetch('/api/v1/workspace/list_files', { cache: 'no-store' });
    if (!res.ok) return [];
    const data = await res.json();
    const files = _flattenWorkspaceListFiles(data.files || [], data.workspace_path || state._workspacePath || '');
    const matches = files.filter((file) => {
      const haystack = `${file.name || ''} ${file.path || ''}`.toLowerCase();
      if (!haystack.includes(q)) return false;
      if (!category) return true;
      return String(file.category || '').toLowerCase() === String(category || '').toLowerCase();
    });
    return matches.slice(0, limit || 60);
  } catch (_) {
    return [];
  }
}

// ── Search ──

async function _doSearch(): Promise<void> {
  state._searchActive = true;
  const q = state.searchQuery;
  const cat = state._searchFilter !== 'all' ? state._searchFilter : '';
  const list = document.getElementById('wa-files-list');
  if (!list) return;
  list.innerHTML =
    '<div class="wa-loading-row" style="padding:12px 8px;display:flex;align-items:center;gap:8px">' +
    '<span class="wa-spinner"></span>搜索中…</div>';
  const cachedResults = _searchCachedBrowserEntries(q, cat, 60);
  if (cachedResults.length) _renderSearchResults(cachedResults, q);
  try {
    const params = new URLSearchParams({ limit: '60' });
    if (q) params.set('q', q);
    if (cat) params.set('category', cat);
    const res = await fetch('/api/files/search?' + params);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const d = await res.json();
    const indexedResults = d.results || [];
    const searchToken = `${q}\u0000${cat}`;
    _renderSearchResults(_mergeSearchResults(cachedResults, indexedResults, 60), q);
    _searchLiveWorkspaceFiles(q, cat, 60).then((liveResults) => {
      if (!state._searchActive || `${state.searchQuery}\u0000${state._searchFilter !== 'all' ? state._searchFilter : ''}` !== searchToken) return;
      _renderSearchResults(_mergeSearchResults(_mergeSearchResults(cachedResults, indexedResults, 60), liveResults, 60), q);
    }).catch(() => {
      // Indexed results are already visible; live search is only a freshness supplement.
    });
  } catch (e: any) {
    if (list) list.innerHTML = `<div class="wa-empty-row" style="padding:12px 8px">搜索失败: ${_escHtml(e.message)}</div>`;
  }
}

function _renderSearchResults(results: SearchResult[], query: string): void {
  const list = document.getElementById('wa-files-list');
  if (!list) return;
  const header =
    '<div class="wa-search-header">' +
    `<span>找到 ${results.length} 个文件${query ? ' &middot; "' + _escHtml(query) + '"' : ''}</span>` +
    '<button type="button" data-wa-file-action="clear-search">&#8592; 返回浏览</button>' +
    '</div>';
  if (!results.length) {
    list.innerHTML =
      header +
      '<div style="padding:20px 12px;text-align:center;color:var(--text-muted);font-size:12px">' +
      '未找到匹配的文件<br><span style="font-size:11px;margin-top:4px;display:block">尝试其他关键词或调整类型过滤</span></div>';
    return;
  }
  const rows = results.map((f) => {
    const name = f.name || (f.path || '').split(/[\\/]/).pop() || '';
    const ext = (name.includes('.') ? (name.split('.').pop() || '') : '').toLowerCase();
    const path = f.path || '';
    const dir = path.replace(/[\\/][^\\/]+$/, '');
    const cat = f.category || '';
    const size = f.size_bytes ? _formatSize(f.size_bytes) : '';
    const supported = _isSupportedExt(ext);
    const unsupported = supported ? '' : ' wa-unsupported';
    const checkHtml = state.selectMode
      ? '<input type="checkbox" class="wa-file-check">'
      : '';
    return (
      `<div class="wa-file-item file${unsupported}" style="padding-left:8px"` +
      ` data-path="${_escHtml(path)}" data-supported="${supported}"` +
      ` ${_fileDragAttrs()}` +
      ` title="${_escHtml(path)}">` +
      `<button type="button" class="wa-file-open-hit" ${_fileOpenHitDragAttrs()} aria-label="打开 ${_escHtml(name)}"></button>` +
      `${checkHtml}${_fileIcon(ext, cat)}` +
      `<span class="wa-file-label">${_escHtml(name)}</span>` +
      `<span class="wa-search-dir" title="${_escHtml(dir)}">${_escHtml(dir)}</span>` +
      `${size ? `<span class="wa-recent-date">${size}</span>` : ''}` +
      _fileActionButtons(supported) +
      '</div>'
    );
  });
  list.innerHTML = header + rows.join('');
}

// ── File Browser ──

export async function loadFileBrowser(): Promise<void> {
  const list = document.getElementById('wa-files-list');
  if (list) list.innerHTML = '<div class="wa-loading-row">正在读取文件系统…</div>';
  try {
    const wsMeta = await fetch('/api/v1/workspace/current_dir')
      .then((r) => (r.ok ? r.json() : null))
      .catch((): any => null);
    if (wsMeta) {
      state._workspaceName = wsMeta.name || 'workspace';
      state._workspacePath = wsMeta.path || '';
      // render workspace root label
      const rootLabel = document.getElementById('wa-ws-root-label');
      if (rootLabel) {
        rootLabel.textContent = (state._workspaceName || 'workspace').toUpperCase();
        rootLabel.title = state._workspacePath || '';
      }
    }
    const res = await fetch('/api/v1/workspace/browse_local');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    state._browserRoots = data;
    const wsEntry = (data.quick_access || []).find((q: any) => q.name === 'Koto 工作区');
    const wsKey = wsEntry ? _browserPathKey(wsEntry.path) : '';
    if (wsEntry && !state._browserExpanded.has(wsKey)) {
      state._browserExpanded.add(wsKey);
      state._browserCache[wsKey] = 'loading';
    }
    _renderBrowserTree();
    if (wsEntry && state._browserCache[wsKey] === 'loading') {
      state._browserCache[wsKey] = await _loadBrowserFolderEntries(wsEntry.path);
      _renderBrowserTree();
    }
  } catch (e: any) {
    const l = document.getElementById('wa-files-list');
    if (l) l.innerHTML = `<div class="wa-empty-row">加载失败: ${e.message}</div>`;
  }
}

async function _loadPickedFiles(files: FileList | File[] | null | undefined): Promise<void> {
  const selected = Array.from(files || []);
  for (const file of selected) {
    await _requireWorkspaceFileLoader().load(file);
  }
  if (selected.length) {
    await loadRecentFiles();
    if (typeof workspaceApi.loadFileBrowser === 'function') {
      await workspaceApi.loadFileBrowser();
    }
  }
}

async function _openFilePicker(options?: { multiple?: boolean; fallbackInputId?: string }): Promise<void> {
  const opts = options || {};
  const fallbackInput = document.getElementById(opts.fallbackInputId || 'wa-file-input') as HTMLInputElement | null;
  if ((window as any).showOpenFilePicker) {
    try {
      const handles = await (window as any).showOpenFilePicker({
        multiple: !!opts.multiple,
        types: [
          {
            description: 'Documents',
            accept: {
              'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
              'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
              'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx'],
              'application/pdf': ['.pdf'],
              'text/plain': ['.txt', '.md', '.markdown', '.csv'],
              'application/json': ['.json'],
            },
          },
          {
            description: 'Images',
            accept: {
              'image/*': ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg'],
            },
          },
        ],
      });
      if (!handles.length) return;
      const files: File[] = [];
      for (const handle of handles) {
        const file = await handle.getFile();
        (file as any)._fsHandle = handle;
        files.push(file);
      }
      await _loadPickedFiles(files);
    } catch (error: any) {
      if (error && error.name === 'AbortError') {
        showToast('已取消选择文件', 'info');
      } else if (error) {
        showToast('无法打开文件: ' + error.message, 'error');
      }
    }
    return;
  }
  if (!fallbackInput) {
    showToast('文件选择器不可用，请刷新页面后重试', 'error');
    return;
  }
  let selectionChanged = false;
  const markSelection = () => { selectionChanged = true; };
  const reportCancelledSelection = () => {
    window.setTimeout(() => {
      if (!selectionChanged) showToast('未选择文件', 'info');
    }, 180);
  };
  fallbackInput.addEventListener('change', markSelection, { once: true });
  window.addEventListener('focus', reportCancelledSelection, { once: true });
  fallbackInput.click();
}

function _supportedFolderFiles(files: FileList | File[]): File[] {
  return Array.from(files || []).filter((file) => {
    const ext = (file.name.split('.').pop() || '').toLowerCase();
    return _isSupportedExt(ext);
  });
}

function _showFolderFilePicker(files: File[]): void {
  if (!files.length) {
    showToast('未找到支持的文件格式', 'error');
    return;
  }
  const overlay = document.createElement('div');
  overlay.className = 'wa-local-folder-picker';
  overlay.innerHTML = [
    '<div class="wa-local-folder-dialog">',
    `  <div class="wa-local-folder-title">${_FOLDER_PICK_SVG}<span>选择要打开的文件</span></div>`,
    '  <div class="wa-local-folder-list"></div>',
    '  <div class="wa-local-folder-actions">',
    '    <button type="button" data-action="open-all">全部打开</button>',
    '    <button type="button" data-action="cancel">取消</button>',
    '  </div>',
    '</div>',
  ].join('');
  const list = overlay.querySelector('.wa-local-folder-list') as HTMLElement | null;
  if (list) {
    files.slice(0, 120).forEach((file, index) => {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'wa-local-folder-file';
      row.dataset.index = String(index);
      const ext = (file.name.split('.').pop() || '').toLowerCase();
      row.innerHTML = `${_fileIcon(ext)}<span>${_escHtml((file as any).webkitRelativePath || file.name)}</span>`;
      list.appendChild(row);
    });
  }
  overlay.addEventListener('click', (event) => {
    if (event.target === overlay) overlay.remove();
  });
  overlay.querySelector('[data-action="cancel"]')?.addEventListener('click', () => overlay.remove());
  overlay.querySelector('[data-action="open-all"]')?.addEventListener('click', () => {
    overlay.remove();
    void _loadPickedFiles(files);
  });
  overlay.querySelectorAll('.wa-local-folder-file').forEach((button) => {
    button.addEventListener('click', () => {
      const index = Number((button as HTMLElement).dataset.index || -1);
      const file = files[index];
      overlay.remove();
      if (file) void _loadPickedFiles([file]);
    });
  });
  document.body.appendChild(overlay);
}

function _bindLocalFilePickers(): void {
  const bindInput = (id: string, handler: (files: FileList) => void | Promise<void>) => {
    const input = document.getElementById(id) as HTMLInputElement | null;
    if (!input || (input as any)._waLocalPickerBound) return;
    (input as any)._waLocalPickerBound = true;
    input.addEventListener('change', (event) => {
      const target = event.target as HTMLInputElement;
      if (target.files && target.files.length) void handler(target.files);
      target.value = '';
    });
  };
  bindInput('wa-file-input', (files) => _loadPickedFiles(files));
  bindInput('wa-file-input-left', (files) => _loadPickedFiles(files));
  bindInput('wa-local-file-input', (files) => _loadPickedFiles(files));
  bindInput('wa-local-folder-input', (files) => _showFolderFilePicker(_supportedFolderFiles(files)));

  const localFileBtn = document.getElementById('wa-pick-local-file-btn');
  if (localFileBtn && !(localFileBtn as any)._waLocalPickerBound) {
    (localFileBtn as any)._waLocalPickerBound = true;
    localFileBtn.addEventListener('click', () => void _openFilePicker({ multiple: true, fallbackInputId: 'wa-local-file-input' }));
  }
  const localFolderBtn = document.getElementById('wa-pick-local-folder-btn');
  if (localFolderBtn && !(localFolderBtn as any)._waLocalPickerBound) {
    (localFolderBtn as any)._waLocalPickerBound = true;
    localFolderBtn.addEventListener('click', () => {
      const input = document.getElementById('wa-local-folder-input') as HTMLInputElement | null;
      if (input) input.click();
    });
  }

  const dropTargets = ['wa-drop-inner', 'wa-left-drop', 'wa-canvas'];
  dropTargets.forEach((id) => {
    const target = document.getElementById(id);
    if (!target || (target as any)._waLocalDropBound) return;
    (target as any)._waLocalDropBound = true;
    target.addEventListener('dragover', (event) => {
      event.preventDefault();
      target.classList.add('drag-over');
    });
    target.addEventListener('dragleave', () => target.classList.remove('drag-over'));
    target.addEventListener('drop', (event) => {
      event.preventDefault();
      target.classList.remove('drag-over');
      const files = (event as DragEvent).dataTransfer?.files;
      if (files && files.length) void _loadPickedFiles(files);
    });
  });
}

export function ensureFileBrowserLoaded(): Promise<void> {
  if (!fileBrowserLoadPromise) {
    fileBrowserLoadPromise = Promise.all([loadFileBrowser(), loadRecentFiles()])
      .then(() => undefined)
      .catch((error) => {
        fileBrowserLoadPromise = null;
        throw error;
      });
  }
  return fileBrowserLoadPromise;
}

function _autoLoadStandaloneFileBrowser(): void {
  if (!document.getElementById('wa-files-list')) return;
  const embeddedWorkspace = document.getElementById('workspaceView');
  if (embeddedWorkspace && getComputedStyle(embeddedWorkspace).display === 'none') return;
  void ensureFileBrowserLoaded();
}

async function _softRefreshBrowser(): Promise<void> {
  const list = document.getElementById('wa-files-list');
  const savedScroll = list ? list.scrollTop : 0;
  const expanded = Array.from(state._browserExpanded);
  for (const p of expanded) state._browserCache[p] = 'loading';
  _renderBrowserTree();
  await Promise.all(
    expanded.map(async (pathKey) => {
      try {
        state._browserCache[pathKey] = await _loadBrowserFolderEntries(pathKey);
      } catch (_) {
        state._browserCache[pathKey] = [];
      }
    })
  );
  _renderBrowserTree();
  if (list)
    requestAnimationFrame(() => {
      list.scrollTop = savedScroll;
    });
}

let _externalFileBrowserRefreshTimer: number | null = null;

function requestFileBrowserRefreshAfterExternalChange(): void {
  if (_externalFileBrowserRefreshTimer !== null) {
    window.clearTimeout(_externalFileBrowserRefreshTimer);
  }
  _externalFileBrowserRefreshTimer = window.setTimeout(() => {
    _externalFileBrowserRefreshTimer = null;
    void _softRefreshBrowser();
  }, 160);
}

// ── Live Polling ──

let _livePollRunning = false;

async function _livePollTick(): Promise<void> {
  if (_livePollRunning || state._searchActive || document.hidden) return;
  const expanded = Array.from(state._browserExpanded);
  if (!expanded.length) return;
  _livePollRunning = true;
  try {
    let changed = false;
    await Promise.all(
      expanded.map(async (pathKey) => {
        try {
          const fresh = await _loadBrowserFolderEntries(pathKey);
          const prev = state._browserCache[pathKey];
          if (prev === 'loading') return;
          const key = (e: any) => e.name + ':' + (e.mtime || 0);
          const prevKey = Array.isArray(prev) ? prev.map(key).join('|') : '';
          const freshKey = fresh.map(key).join('|');
          if (prevKey !== freshKey) {
            state._browserCache[pathKey] = fresh;
            changed = true;
          }
        } catch (_) {
          /* ignore */
        }
      })
    );
    if (changed) _renderBrowserTree();
  } finally {
    _livePollRunning = false;
  }
}

function _startLivePoll(): void {
  if (state._livePollTimer) return;
  state._livePollTimer = setInterval(_livePollTick, 10000);
}

function _stopLivePoll(): void {
  if (!state._livePollTimer) return;
  clearInterval(state._livePollTimer);
  state._livePollTimer = null;
}

// ── Render Browser Tree ──

export function _renderBrowserTree(): void {
  const list = document.getElementById('wa-files-list');
  if (!list) return;
  if (!state._browserRoots) {
    list.innerHTML = '<div class="wa-loading-row">正在读取文件系统…</div>';
    return;
  }
  const r = state._browserRoots;
  const rows: string[] = [];
  if (r.quick_access?.length) {
    rows.push(`<div class="wa-browser-group-label">快速访问</div>`);
    r.quick_access.forEach((qa: BrowserNode) => _renderBrowserEntry(qa, 0, rows));
  }
  if (r.drives?.length) {
    rows.push(`<div class="wa-browser-group-label">此电脑</div>`);
    r.drives.forEach((d: BrowserNode) => _renderBrowserEntry(d, 0, rows));
  }
  const _savedScroll = list.scrollTop;
  list.innerHTML = rows.join('');
  list.scrollTop = _savedScroll;
  requestAnimationFrame(() => {
    list.scrollTop = _savedScroll;
  });
  if (state.activeTabPath) {
    const el = list.querySelector(`[data-path="${CSS.escape(state.activeTabPath)}"]`);
    if (el) el.classList.add('active');
  }
}

// ── Render Browser Entry ──

function _renderBrowserEntry(entry: BrowserNode, depth: number, rows: string[]): void {
  const pad = depth * 16 + 8;
  const absPath = entry.path;
  const pathKey = _browserPathKey(absPath);
  const isFolder = entry.type === 'folder' || entry.type === 'drive' || entry.type === 'quick';

  if (isFolder) {
    const isExpanded = state._browserExpanded.has(pathKey);
    const folderSvg = isExpanded ? _FOLDER_OPEN_SVG : _FOLDER_SVG;
    rows.push(
      `<div class="wa-file-item folder" style="padding-left:${pad}px" ` +
        `data-path="${_escHtml(absPath)}" ` +
        `data-wa-file-kind="folder">` +
        `<span class="wa-folder-arrow${isExpanded ? ' open' : ''}">›</span>` +
        `<span class="wa-file-icon">${folderSvg}</span>` +
        `<span class="wa-file-label">${_escHtml(entry.name)}</span>` +
        `<div class="wa-file-actions"><button type="button" class="wa-file-more" data-wa-file-action="more" draggable="false" title="更多操作" aria-label="更多操作">${_MORE_BTN_SVG}</button></div>` +
        `</div>`
    );
    if (isExpanded) {
      const ch = state._browserCache[pathKey];
      if (ch === 'loading') {
        rows.push(`<div class="wa-loading-row" style="padding-left:${pad + 24}px">加载中…</div>`);
      } else if (!ch || ch.length === 0) {
        rows.push(`<div class="wa-empty-row" style="padding-left:${pad + 24}px">（空文件夹）</div>`);
      } else {
        ch.forEach((c: BrowserNode) => _renderBrowserEntry(c, depth + 1, rows));
      }
    }
  } else {
    const ext = entry.ext || '';
    const supported = entry.supported !== false;
    const unsupported = !supported ? ' wa-unsupported' : '';
    const isActive = state.activeTabPath === absPath ? ' active' : '';
    const checkHtml = state.selectMode
      ? '<input type="checkbox" class="wa-file-check">'
      : '';
    rows.push(
      `<div class="wa-file-item file${isActive}${unsupported}" style="padding-left:${pad}px" ` +
        `data-path="${_escHtml(absPath)}" data-supported="${supported}" ` +
        `${_fileDragAttrs()} data-wa-file-kind="file" ` +
        `title="${_escHtml(entry.name)}">` +
        `<button type="button" class="wa-file-open-hit" ${_fileOpenHitDragAttrs()} aria-label="打开 ${_escHtml(entry.name)}"></button>` +
        `${checkHtml}${_fileIcon(ext, entry.category || '')}` +
        `<span class="wa-file-label">${_escHtml(entry.name)}</span>` +
        _fileActionButtons(supported) +
        `</div>`
    );
  }
}

// ── Toggle Browser Folder ──

async function toggleBrowserFolder(absPath: string): Promise<void> {
  const path = String(absPath || '').trim();
  const pathKey = _browserPathKey(path);
  if (!path || !pathKey) return;
  if (state._browserExpanded.has(pathKey)) {
    state._browserExpanded.delete(pathKey);
    _renderBrowserTree();
    if (!state._browserExpanded.size) _stopLivePoll();
    return;
  }
  state._browserExpanded.add(pathKey);
  _startLivePoll();
  if (!state._browserCache[pathKey] || state._browserCache[pathKey] === 'loading') {
    state._browserCache[pathKey] = 'loading';
    _renderBrowserTree();
    try {
      state._browserCache[pathKey] = await _loadBrowserFolderEntries(path);
    } catch (e: any) {
      state._browserCache[pathKey] = [];
      showToast(e.message, 'error');
    }
  }
  if (state._browserExpanded.has(pathKey)) _renderBrowserTree();
}

function handleBrowserFolderClick(event: MouseEvent, el: HTMLElement): void {
  if (event) {
    event.preventDefault();
    event.stopPropagation();
  }
  const path = String(el && el.dataset ? el.dataset.path || '' : '').trim();
  void toggleBrowserFolder(path);
}

// ── Drop Onto Folder ──

async function _dropOntoFolder(event: DragEvent, destPath: string): Promise<void> {
  if (!event.dataTransfer) return;
  const srcPath = event.dataTransfer.getData('application/wa-file-path');
  if (srcPath) {
    try {
      const r = await _csrfFetch('/api/v1/workspace/fs_copy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ src: srcPath, dst_dir: destPath, move: false }),
      });
      const d = await r.json();
      if (!r.ok) {
        showToast(d.error || '复制失败', 'error');
        return;
      }
      showToast(`已复制到 ${destPath.split(/[\\/]/).pop()}`, 'success');
    } catch (e: any) {
      showToast('复制出错: ' + e.message, 'error');
      return;
    }
  } else if (event.dataTransfer.files && event.dataTransfer.files.length) {
    const fd = new FormData();
    fd.append('dest_dir', destPath);
    for (let i = 0; i < event.dataTransfer.files.length; i++) {
      fd.append('file', event.dataTransfer.files[i]);
    }
    try {
      const r = await _csrfFetch('/api/v1/workspace/upload-to-folder', { method: 'POST', body: fd });
      const d = await r.json();
      if (!r.ok) {
        showToast(d.error || '上传失败', 'error');
        return;
      }
      const names = (d.saved || []).map((s: any) => s.name).join(', ');
      showToast(`已加入：${names}`, 'success');
    } catch (e: any) {
      showToast('上传出错: ' + e.message, 'error');
      return;
    }
  } else {
    return;
  }

  const destKey = _browserPathKey(destPath);
  delete state._browserCache[destKey];
  state._browserExpanded.add(destKey);
  await _softRefreshBrowser();
}

// ── Workspace File Loader (fallback) ──

function _createFallbackWorkspaceFileLoader(): any {
  const _switchToTab = async (path: string): Promise<void> => {
    if (typeof workspaceApi._tabClick === 'function') {
      await workspaceApi._tabClick(path);
    }
  };

  const setLoadingFn = (show: boolean, msg?: string): void => {
    const overlay = document.getElementById('wa-canvas-loading');
    if (show) {
      if (overlay) {
        const text = overlay.querySelector('.wa-loading-text');
        if (text) text.textContent = msg || '加载中...';
        overlay.style.display = 'flex';
      }
    } else {
      if (overlay) overlay.style.display = 'none';
    }
  };

  async function openParsedFile(json: any, wsPath: string | null, _fsHandle: any = null): Promise<any> {
    const resolvedPath = wsPath || json.ws_source_path || json.source_path || json.temp_path || json.file_name;
    if (typeof workspaceApi._applyFileJson === 'function') {
      await workspaceApi._applyFileJson(json, resolvedPath, _fsHandle);
    }
    if (resolvedPath) _trackUserOpen(resolvedPath);
    return json;
  }

  async function openWorkspaceFile(path: string, supported: boolean = true): Promise<any> {
    const requestPath = _workspaceRelativePath(path);
    if (!requestPath) return null;
    if (!supported) {
      showToast('此格式暂不支持在线编辑：' + _displayFileName(requestPath), 'info');
      return null;
    }
    setLoadingFn(true, '正在打开文件...');
    let missingWorkspaceFile = false;
    try {
      const res = await _csrfFetch('/api/v1/workspace/open_file_by_path', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: requestPath }),
      });
      const data = await _safeJson(res);
      if (!res.ok) {
        missingWorkspaceFile = res.status === 404;
        if (missingWorkspaceFile) {
          _forgetRecentPath(path);
          _forgetRecentPath(requestPath);
          await loadRecentFiles().catch(() => {});
        }
        throw new Error(data.error || '打开文件失败');
      }
      return await openParsedFile(data, requestPath, null);
    } catch (error: any) {
      if (!missingWorkspaceFile) console.error('[WA] openWorkspaceFile failed:', error);
      showToast(
        missingWorkspaceFile ? '文件已不存在，已从最近文件移除' : (error.message || '打开文件失败'),
        missingWorkspaceFile ? 'info' : 'error',
      );
      return null;
    } finally {
      setLoadingFn(false);
    }
  }

  async function openBrowserFile(absPath: string, supported: boolean = true): Promise<any> {
    if (!supported) {
      showToast('此格式暂不支持在线编辑：' + _displayFileName(absPath), 'info');
      return null;
    }
    if (_isAbsolutePath(absPath) && !_isInsideWorkspace(absPath)) {
      setLoadingFn(true, '正在打开文件...');
      let missingExternalFile = false;
      try {
        const res = await _csrfFetch('/api/v1/workspace/open_abs_file', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: absPath }),
        });
        const data = await _safeJson(res);
        if (!res.ok) {
          missingExternalFile = res.status === 404;
          if (missingExternalFile) {
            _forgetRecentPath(absPath);
            await loadRecentFiles().catch(() => {});
          }
          throw new Error(data.error || '打开文件失败');
        }
        return await openParsedFile(data, absPath, null);
      } catch (error: any) {
        if (!missingExternalFile) console.error('[WA] openBrowserFile failed:', error);
        showToast(
          missingExternalFile ? '文件已不存在，已从最近文件移除' : (error.message || '打开文件失败'),
          missingExternalFile ? 'info' : 'error',
        );
        return null;
      } finally {
        setLoadingFn(false);
      }
    }
    return openWorkspaceFile(absPath, supported);
  }

  async function reloadFileByPath(filePath: string, supported: boolean = true): Promise<any> {
    if (_isAbsolutePath(filePath) && !_isInsideWorkspace(filePath)) {
      return openBrowserFile(filePath, supported);
    }
    return openWorkspaceFile(filePath, supported);
  }

  async function load(file: any): Promise<any> {
    if (!file) return null;
    if (file._waPath) return openWorkspaceFile(file._waPath, true);
    setLoadingFn(true, '正在解析文件...');
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await _csrfFetch('/api/v1/workspace/open_file', {
        method: 'POST',
        body: formData,
      });
      const data = await _safeJson(res);
      if (!res.ok) throw new Error(data.error || '打开文件失败');
        return await openParsedFile(data, data.ws_source_path || file.name, file._fsHandle || null);
    } catch (error: any) {
      console.error('[WA] load file failed:', error);
      showToast(error.message || '打开文件失败', 'error');
      return null;
    } finally {
      setLoadingFn(false);
    }
  }

  return { openBrowserFile, openWorkspaceFile, reloadFileByPath, openParsedFile, fromParsed: openParsedFile, load };
}

export const _waSharedFileLoader: any = typeof workspaceApi.createWorkspaceFileLoader === 'function'
  ? workspaceApi.createWorkspaceFileLoader({
      state,
      getElement: (id: string) => document.getElementById(id),
      showToast,
      setLoading,
      trackUserOpen: _trackUserOpen,
      switchToTab: undefined, // filled by actual _switchToTab
      safeJson: _safeJson,
      applyFileJson: undefined, // filled by actual _applyFileJson
      loadRecentFiles: undefined, // placeholder
      renderBrowserTree: _renderBrowserTree,
      maybeAutoOpenReviewCenterForImportedItems: undefined,
      ensureTabReviewState: undefined,
      activeReviewTab: undefined,
    })
  : _createFallbackWorkspaceFileLoader();

function _requireWorkspaceFileLoader(): any {
  if (_waSharedFileLoader) return _waSharedFileLoader;
  throw new Error('workspace file loader unavailable');
}

// ── Backward compatibility ──

const wa = workspaceApi;

wa._renderBrowserTree = _renderBrowserTree;
wa._softRefreshBrowser = _softRefreshBrowser;
wa.requestFileBrowserRefreshAfterExternalChange = requestFileBrowserRefreshAfterExternalChange;
wa._doSearch = _doSearch;
wa.toggleBrowserFolder = toggleBrowserFolder;
wa.handleBrowserFolderClick = handleBrowserFolderClick;
wa._dropOntoFolder = _dropOntoFolder;
wa._browserFileDragStart = _browserFileDragStart;
wa._browserFileDragEnd = _browserFileDragEnd;
wa._browserFileRowPointerDown = (event: PointerEvent, el: HTMLElement): void => {
  _startBrowserPointerDrag(event, el);
};
wa.sendBrowserFileToAI = _sendBrowserFileToAI;
wa._sendBrowserFileButton = _sendBrowserFileButtonToAI;
wa._browserFileRowMouseDown = (event: MouseEvent, el: HTMLElement): void => {
  if (!el) return;
  _startBrowserPointerDrag(event, el);
  if (!state.selectMode) return;
  if (event && event.button !== 0) return;
  if (event && event.target && (event.target as HTMLElement).closest('.wa-file-check')) return;
  el.dataset.selectMouseHandled = '1';
  wa._browserFileRowClick(event, el);
};
wa._browserFileRowClick = (event: MouseEvent, el: HTMLElement): void => {
  if (!el) return;
  if (Date.now() < _suppressBrowserRowClickUntil) {
    event.preventDefault();
    event.stopPropagation();
    return;
  }
  if (event && event.target && (event.target as HTMLElement).closest('.wa-file-check')) return;
  if (el.dataset.selectMouseHandled === '1' && event && event.type === 'click') {
    delete el.dataset.selectMouseHandled;
    event.preventDefault();
    event.stopPropagation();
    return;
  }
  if (state.selectMode) {
    event.preventDefault();
    event.stopPropagation();
    const cb = el.querySelector('.wa-file-check') as HTMLInputElement | null;
    if (cb) {
      cb.checked = !cb.checked;
      if (typeof wa._toggleBrowserCheck === 'function') wa._toggleBrowserCheck(cb);
    }
    return;
  }
  if (el.dataset.supported !== 'false') {
    wa.openBrowserFile(el.dataset.path, true);
  } else {
    showToast('此格式暂不支持在线编辑：' + (el.dataset.path || '').split(/[\\/]/).pop(), 'info');
  }
};
wa.loadFileBrowser = loadFileBrowser;
wa._openLocalFile = () => _openFilePicker({ multiple: true, fallbackInputId: 'wa-local-file-input' });
wa._openLocalFolder = () => {
  const input = document.getElementById('wa-local-folder-input') as HTMLInputElement | null;
  if (input) input.click();
};
wa.openSystemFileList = () => _openFilePicker({ multiple: true, fallbackInputId: 'wa-file-input-left' });
wa.cycleBrowserSort = () => {
  const order = ['name', 'date', 'type'];
  const labels: Record<string, string> = { name: '名称', date: '日期', type: '类型' };
  const idx = order.indexOf(state._browserSort);
  state._browserSort = order[(idx + 1) % order.length];
  localStorage.setItem('wa_browser_sort', state._browserSort);
  const btn = document.getElementById('wa-browser-sort-btn');
  if (btn) btn.textContent = '\u21d5 ' + labels[state._browserSort];
  for (const p in state._browserCache) {
    if (Array.isArray(state._browserCache[p]))
      state._browserCache[p] = _applyBrowserSort(state._browserCache[p]);
  }
  _renderBrowserTree();
};
wa.openBrowserFile = async (absPath: string, supported: boolean = true) => {
  return _requireWorkspaceFileLoader().openBrowserFile(absPath, supported);
};
wa.openWorkspaceFile = async (path: string) => {
  return _requireWorkspaceFileLoader().openWorkspaceFile(path);
};
wa.reloadFileByPath = async (filePath: string, supported: boolean = true) => {
  return _requireWorkspaceFileLoader().reloadFileByPath(filePath, supported);
};
wa._openParsedFile = async (d: any, wsPath: string) => {
  return _requireWorkspaceFileLoader().openParsedFile(d, wsPath);
};
wa.openRecentFile = async (filePath: string) => {
  if (!filePath) return;
  const rawPath = String(filePath);
  const normalizedPath = rawPath.replace(/\\/g, '/');
  const workspacePath = (state._workspacePath || '').replace(/\\/g, '/');
  const ext = normalizedPath.includes('.') ? normalizedPath.split('.').pop()!.toLowerCase() : '';
  const supported = _isSupportedExt(ext);
  const looksAbsolute = /^(?:[a-zA-Z]:\/|\/|\/\/)/.test(normalizedPath);

  if (workspacePath && looksAbsolute && (
    normalizedPath === workspacePath || normalizedPath.startsWith(workspacePath + '/')
  )) {
    const relativePath = normalizedPath.slice(workspacePath.length).replace(/^\//, '');
    return wa.openWorkspaceFile(relativePath);
  }

  if (!looksAbsolute) {
    return wa.openWorkspaceFile(normalizedPath.replace(/^\//, ''));
  }

  return wa.openBrowserFile(rawPath, supported);
};

(window as any).loadFileBrowser = loadFileBrowser;

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    _installBrowserFileActionDelegation();
    _installBrowserPointerDragFallback();
    _bindLocalFilePickers();
    _autoLoadStandaloneFileBrowser();
  }, { once: true });
} else {
  _installBrowserFileActionDelegation();
  _installBrowserPointerDragFallback();
  _bindLocalFilePickers();
  _autoLoadStandaloneFileBrowser();
}

// setLoading helper
function setLoading(show: boolean, msg?: string): void {
  const overlay = document.getElementById('wa-canvas-loading');
  const list = document.getElementById('wa-files-list');
  if (show) {
    if (overlay) {
      const text = overlay.querySelector('.wa-loading-text');
      if (text) text.textContent = msg || '加载中...';
      overlay.style.display = 'flex';
    }
    if (list) list.classList.add('loading');
  } else {
    if (overlay) overlay.style.display = 'none';
    if (list) list.classList.remove('loading');
  }
}
