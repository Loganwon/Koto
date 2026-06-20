/**
 * File System Context Menu — browser right-click menus, rename, delete, copy, paste, AI summary.
 * Extracted from workspace-assistant.js lines 2112-5426 (context menu + workspace file ops).
 */

import { _escHtml, showToast, _FOLDER_SVG, _DEFAULT_FILE_SVG } from './infrastructure';
import { state } from './state';

// ── Interfaces ──

export interface ContextMenuConfig {
  path: string;
  name: string;
  isFolder: boolean;
  supported: boolean;
}

export interface MenuAction {
  label: string;
  icon: string;
  action: string;
  danger?: boolean;
}

export interface BrowserEntry {
  path: string;
  name: string;
  isFolder: boolean;
  supported: boolean;
}

// ── Context Menu State ──

let _fsBrowserCtxTarget: ContextMenuConfig = { path: '', name: '', isFolder: false, supported: true };
let _ctxTarget: { path: string | null; name: string | null } = { path: null, name: null };

// ── Clone Serializable ──

function _cloneSerializable(value: any, fallback: any = null): any {
  try {
    return JSON.parse(JSON.stringify(value));
  } catch (_) {
    return fallback;
  }
}

// ── CSRF Fetch ──

function _csrfFetch(url: string, options: any = {}): Promise<Response> {
  if (typeof (window as any).WA?._csrfFetch === 'function') {
    return (window as any).WA._csrfFetch(url, options);
  }
  return fetch(url, options);
}

// ── Context Menu Zoom & Position ──

function _ctxMenuZoom(): number {
  const inlineZoom = parseFloat(((document.documentElement as any)?.style?.zoom as string) || '');
  if (Number.isFinite(inlineZoom) && inlineZoom > 0) return inlineZoom;
  const computedZoom = parseFloat(window.getComputedStyle(document.documentElement).zoom || '');
  return Number.isFinite(computedZoom) && computedZoom > 0 ? computedZoom : 1;
}

function _logicalCtxValue(value: number, zoom: number): number {
  const number = Number(value);
  return Number.isFinite(number) ? number / zoom : 0;
}

function _logicalCtxRect(rect: DOMRect | null | undefined, zoom: number): { left: number; top: number; right: number; bottom: number; width: number; height: number } {
  return {
    left: _logicalCtxValue(rect?.left ?? 0, zoom),
    top: _logicalCtxValue(rect?.top ?? 0, zoom),
    right: _logicalCtxValue(rect?.right ?? 0, zoom),
    bottom: _logicalCtxValue(rect?.bottom ?? 0, zoom),
    width: _logicalCtxValue(rect?.width ?? 0, zoom),
    height: _logicalCtxValue(rect?.height ?? 0, zoom),
  };
}

function _measureCtxMenu(menu: HTMLElement): {
  zoom: number;
  viewportWidth: number;
  viewportHeight: number;
  width: number;
  height: number;
} {
  const zoom = _ctxMenuZoom();
  const rect = _logicalCtxRect(menu.getBoundingClientRect(), zoom);
  const itemCount = menu.querySelectorAll('.wa-ctx-item').length;
  const separatorCount = menu.querySelectorAll('.wa-ctx-separator').length;
  return {
    zoom,
    viewportWidth: window.innerWidth / zoom,
    viewportHeight: window.innerHeight / zoom,
    width: rect.width || menu.offsetWidth || 180,
    height:
      rect.height ||
      menu.scrollHeight ||
      menu.offsetHeight ||
      itemCount * 28 + separatorCount * 7 + 8,
  };
}

function _logicalCtxPoint(event: MouseEvent, zoom: number): { x: number; y: number } {
  return {
    x: _logicalCtxValue(event?.clientX ?? 0, zoom),
    y: _logicalCtxValue(event?.clientY ?? 0, zoom),
  };
}

function _clampCtxMenuPosition(
  x: number,
  y: number,
  menuW: number,
  menuH: number,
  zoom: number,
  { clampToLeftPanel = false } = {}
): { x: number; y: number } {
  const viewportWidth = window.innerWidth / zoom;
  const viewportHeight = window.innerHeight / zoom;
  if (clampToLeftPanel) {
    const leftPanel = document.getElementById('wa-left');
    if (leftPanel) {
      const panelRect = _logicalCtxRect(leftPanel.getBoundingClientRect(), zoom);
      if (x + menuW > panelRect.right) x = panelRect.right - menuW - 4;
      if (x < panelRect.left) x = panelRect.left + 4;
    }
  }
  if (x + menuW > viewportWidth) x = viewportWidth - menuW - 4;
  if (x < 4) x = 4;
  if (y + menuH > viewportHeight - 2) y = Math.max(4, viewportHeight - menuH - 4);
  if (y < 4) y = 4;
  return { x, y };
}

function _clampMenuPos(menu: HTMLElement): void {
  const zoom = _ctxMenuZoom();
  const r = _logicalCtxRect(menu.getBoundingClientRect(), zoom);
  const vw2 = window.innerWidth / zoom;
  const vh2 = window.innerHeight / zoom;
  let t = parseFloat(menu.style.top),
    l = parseFloat(menu.style.left);
  if (r.bottom > vh2 - 2) t = Math.max(4, t - (r.bottom - vh2 + 4));
  if (r.right > vw2 - 2) l = Math.max(4, vw2 - r.width - 4);
  if (t < 4) t = 4;
  if (l < 4) l = 4;
  menu.style.top = t + 'px';
  menu.style.left = l + 'px';
}

function _positionCtxMenu(
  menu: HTMLElement,
  event: MouseEvent,
  { alignToButton = false, clampToLeftPanel = false } = {}
): void {
  menu.classList.add('open');
  menu.style.visibility = 'hidden';
  menu.style.top = '0px';
  menu.style.left = '0px';
  void menu.getBoundingClientRect();
  const metrics = _measureCtxMenu(menu);
  menu.style.visibility = '';

  let { x, y } = _logicalCtxPoint(event, metrics.zoom);
  const btn = alignToButton
    ? ((event.currentTarget as HTMLElement)?.closest?.('button') || (event.target as HTMLElement)?.closest?.('button'))
    : null;
  if (btn) {
    const btnRect = _logicalCtxRect(btn.getBoundingClientRect(), metrics.zoom);
    x = btnRect.right - metrics.width;
    y =
      btnRect.bottom + metrics.height + 4 <= metrics.viewportHeight
        ? btnRect.bottom + 2
        : Math.max(4, btnRect.top - metrics.height - 2);
  } else {
    y =
      y + metrics.height + 4 <= metrics.viewportHeight
        ? y
        : Math.max(4, y - metrics.height);
  }

  ({ x, y } = _clampCtxMenuPosition(x, y, metrics.width, metrics.height, metrics.zoom, { clampToLeftPanel }));
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';
  _clampMenuPos(menu);
}

// ── Close Context Menu ──

function _closeCtxMenu(): void {
  const menu = document.getElementById('wa-ctx-menu');
  if (menu) menu.classList.remove('open');
}
(window as any)._closeCtxMenu = _closeCtxMenu;

// ── SVG Icons for Context Menu ──

const CTX_SVG: Record<string, string> = {
  open: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>`,
  copy: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`,
  cut: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.12 15.88"/><path d="M14.47 14.48 20 20"/><path d="M8.12 8.12 12 12"/></svg>`,
  paste: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/></svg>`,
  rename: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`,
  newf: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/></svg>`,
  newdir: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/></svg>`,
  ai: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`,
  del: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>`,
};

// ── Browser Context Menu ──

function _showBrowserCtx(event: MouseEvent, el: HTMLElement): void {
  if (!el) return;
  event.preventDefault();
  event.stopPropagation();
  const absPath = el.dataset.path;
  if (!absPath) return;
  const name =
    (el.querySelector('.wa-file-label') as HTMLElement)?.textContent ||
    absPath.split(/[\\/]/).pop() ||
    '';
  const isFolder = el.classList.contains('folder');
  const supported = el.dataset.supported !== 'false';
  _fsBrowserCtxTarget = { path: absPath, name, isFolder, supported };
  const menu = document.getElementById('wa-ctx-menu');
  if (!menu) return;

  const clip = state._fsClipboard;

  let html = '';
  if (isFolder) {
    html += `<div class="wa-ctx-item" onclick="WA._fsBrowserNewFile();_closeCtxMenu()">${CTX_SVG.newf} 新建文件</div>`;
    html += `<div class="wa-ctx-item" onclick="WA._fsBrowserNewFolder();_closeCtxMenu()">${CTX_SVG.newdir} 新建子文件夹</div>`;
    html += `<div class="wa-ctx-separator"></div>`;
    if (clip) {
      html += `<div class="wa-ctx-item" onclick="WA._fsBrowserPaste();_closeCtxMenu()">${CTX_SVG.paste} 粘贴 <span style="font-size:11px;color:var(--text-muted);margin-left:4px">${_escHtml(clip.name)}</span></div>`;
      html += `<div class="wa-ctx-separator"></div>`;
    }
    html += `<div class="wa-ctx-item" onclick="WA._fsBrowserRename();_closeCtxMenu()">${CTX_SVG.rename} 重命名</div>`;
    html += `<div class="wa-ctx-item" onclick="WA._fsBrowserCopyPath();_closeCtxMenu()">${CTX_SVG.copy} 复制路径</div>`;
    html += `<div class="wa-ctx-separator"></div>`;
    html += `<div class="wa-ctx-item danger" onclick="WA._fsBrowserDelete();_closeCtxMenu()">${CTX_SVG.del} 删除文件夹</div>`;
  } else {
    html += `<div class="wa-ctx-item" onclick="WA._fsBrowserOpen();_closeCtxMenu()">${CTX_SVG.open} 打开</div>`;
    html += `<div class="wa-ctx-separator"></div>`;
    html += `<div class="wa-ctx-item" onclick="WA._fsBrowserAddToTempWorkspace();_closeCtxMenu()">${CTX_SVG.newf} 加入临时工作区</div>`;
    html += `<div class="wa-ctx-item" onclick="WA._fsBrowserAddToWorkspace();_closeCtxMenu()">${CTX_SVG.newf} 加入我的工作区</div>`;
    html += `<div class="wa-ctx-item" onclick="WA._fsBrowserSendToAI();_closeCtxMenu()">${CTX_SVG.ai} 发送给AI分析</div>`;
    html += `<div class="wa-ctx-separator"></div>`;
    html += `<div class="wa-ctx-item" onclick="WA._fsBrowserCopy();_closeCtxMenu()">${CTX_SVG.copy} 复制</div>`;
    html += `<div class="wa-ctx-item" onclick="WA._fsBrowserCut();_closeCtxMenu()">${CTX_SVG.cut} 剪切</div>`;
    if (clip) {
      html += `<div class="wa-ctx-item" onclick="WA._fsBrowserPaste();_closeCtxMenu()">${CTX_SVG.paste} 粘贴到此处</div>`;
    }
    html += `<div class="wa-ctx-separator"></div>`;
    html += `<div class="wa-ctx-item" onclick="WA._fsBrowserRename();_closeCtxMenu()">${CTX_SVG.rename} 重命名</div>`;
    if (supported) {
      html += `<div class="wa-ctx-separator"></div>`;
      html += `<div class="wa-ctx-item" onclick="WA._fsBrowserAISummary();_closeCtxMenu()">${CTX_SVG.ai} AI 概括</div>`;
    }
    html += `<div class="wa-ctx-separator"></div>`;
    html += `<div class="wa-ctx-item" onclick="WA._fsBrowserCopyPath();_closeCtxMenu()">${CTX_SVG.copy} 复制路径</div>`;
    html += `<div class="wa-ctx-separator"></div>`;
    html += `<div class="wa-ctx-item danger" onclick="WA._fsBrowserDelete();_closeCtxMenu()">${CTX_SVG.del} 删除</div>`;
  }
  menu.innerHTML = html;
  _positionCtxMenu(menu, event, {
    alignToButton: event.type === 'click',
    clampToLeftPanel: true,
  });
}

// ── Browser Context Menu Actions ──

function _fsBrowserOpen(): void {
  const { path, supported } = _fsBrowserCtxTarget;
  if (!path) return;
  (window as any).WA.openBrowserFile(path, supported);
}

function _fsBrowserAddToWorkspace(): void {
  const { path } = _fsBrowserCtxTarget;
  if (path) (window as any).WA.addToMyWorkspace(path);
}

function _fsBrowserAddToTempWorkspace(): void {
  const { path } = _fsBrowserCtxTarget;
  if (path) (window as any).WA.addToTempWorkspace(path);
}

async function _fsBrowserSendToAI(): Promise<void> {
  const { path } = _fsBrowserCtxTarget;
  if (!path) return;
  if (typeof (window as any).WA.attachFilesToTask === 'function') {
    await (window as any).WA.attachFilesToTask([path], { source: 'browser_context_menu' });
  }
}

function _fsBrowserCopy(): void {
  const { path, name } = _fsBrowserCtxTarget;
  if (!path) return;
  state._fsClipboard = { path, name, mode: 'copy' };
  showToast('"' + name + '" 已复制', 'success');
}

function _fsBrowserCut(): void {
  const { path, name } = _fsBrowserCtxTarget;
  if (!path) return;
  state._fsClipboard = { path, name, mode: 'cut' };
  const el = document.querySelector(`.wa-file-item[data-path="${CSS.escape(path)}"]`) as HTMLElement | null;
  if (el) el.style.opacity = '0.45';
  showToast('"' + name + '" 准备移动', 'info');
}

async function _fsBrowserPaste(): Promise<void> {
  const clip = state._fsClipboard;
  if (!clip) return;
  const { path: target, isFolder } = _fsBrowserCtxTarget;
  const dstDir = isFolder ? target : target.replace(/[\\/][^\\/]+$/, '');
  try {
    const res = await _csrfFetch('/api/v1/workspace/fs_copy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ src: clip.path, dst_dir: dstDir, move: clip.mode === 'cut' }),
    });
    const json = await res.json();
    if (!res.ok) throw new Error(json.error || '操作失败');
    if (clip.mode === 'cut') state._fsClipboard = null;
    showToast('已粘贴 "' + clip.name + '"', 'success');
    delete state._browserCache[dstDir];
    state._browserExpanded.add(dstDir);
    if (typeof (window as any).WA._softRefreshBrowser === 'function') {
      await (window as any).WA._softRefreshBrowser();
    }
  } catch (e: any) {
    showToast(e.message, 'error');
  }
}

function _fsBrowserCopyPath(): void {
  const { path } = _fsBrowserCtxTarget;
  if (!path) return;
  navigator.clipboard
    .writeText(path)
    .then(() => showToast('路径已复制', 'success'))
    .catch(() => showToast(path, 'info'));
}

async function _fsBrowserRename(): Promise<void> {
  const { path, name, isFolder } = _fsBrowserCtxTarget;
  if (!path) return;
  const item = document.querySelector(`.wa-file-item[data-path="${CSS.escape(path)}"]`) as HTMLElement | null;
  if (!item) return;
  const labelSpan = item.querySelector('.wa-file-label') as HTMLElement | null;
  if (!labelSpan) return;
  const stem = !isFolder && name.includes('.') ? name.slice(0, name.lastIndexOf('.')) : name;
  const input = document.createElement('input');
  input.className = 'wa-rename-input';
  input.value = stem;
  labelSpan.replaceWith(input);
  input.focus();
  input.select();
  const commit = async () => {
    const newName = input.value.trim();
    if (!newName || newName === stem) {
      const softRefresh = (window as any).WA._softRefreshBrowser;
      if (typeof softRefresh === 'function') await softRefresh();
      return;
    }
    try {
      const res = await _csrfFetch('/api/v1/workspace/fs_rename', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, name: newName }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || '重命名失败');
      showToast('已重命名为 ' + json.name, 'success');
    } catch (e: any) {
      showToast(e.message, 'error');
    }
    const parent = path.replace(/[\\/][^\\/]+$/, '');
    delete state._browserCache[parent];
    const softRefresh = (window as any).WA._softRefreshBrowser;
    if (typeof softRefresh === 'function') await softRefresh();
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      commit();
    }
    if (e.key === 'Escape') {
      const softRefresh = (window as any).WA._softRefreshBrowser;
      if (typeof softRefresh === 'function') softRefresh();
    }
  });
  input.addEventListener('blur', commit);
}

async function _fsBrowserDelete(): Promise<void> {
  const { path, name, isFolder } = _fsBrowserCtxTarget;
  if (!path) return;
  const msg = isFolder
    ? `确定要删除文件夹 "${name}" 及其所有内容吗？此操作不可撤销。`
    : `确定要删除 "${name}" 吗？`;
  if (!confirm(msg)) return;
  try {
    const res = await _csrfFetch('/api/v1/workspace/fs_delete?path=' + encodeURIComponent(path), { method: 'DELETE' });
    const json = await res.json();
    if (!res.ok) throw new Error(json.error || '删除失败');
    showToast('已删除 "' + name + '"', 'success');
    const removeTabFn = (window as any).WA?._removeOpenTabAfterFileDeleted;
    if (typeof removeTabFn === 'function') {
      await removeTabFn(path);
    }
    const parent = path.replace(/[\\/][^\\/]+$/, '');
    delete state._browserCache[parent];
    if (state._browserExpanded.has(path)) state._browserExpanded.delete(path);
    const softRefresh = (window as any).WA._softRefreshBrowser;
    if (typeof softRefresh === 'function') await softRefresh();
  } catch (e: any) {
    showToast(e.message, 'error');
  }
}

function _fsBrowserNewFile(): void {
  const { path } = _fsBrowserCtxTarget;
  if (path && typeof (window as any).WA.startNewFile === 'function') {
    (window as any).WA.startNewFile(path);
  }
}

function _fsBrowserNewFolder(): void {
  const { path } = _fsBrowserCtxTarget;
  if (path && typeof (window as any).WA.startNewFolder === 'function') {
    (window as any).WA.startNewFolder(path);
  }
}

async function _fsBrowserAISummary(): Promise<void> {
  const { path, supported } = _fsBrowserCtxTarget;
  if (!path || !supported) return;
  const openFile = (window as any).WA.openBrowserFile;
  if (typeof openFile === 'function') {
    await openFile(path, true);
  }
  setTimeout(() => {
    const input = document.getElementById('wa-user-input') as HTMLInputElement | null;
    if (input) {
      input.value = '请帮我概括这份文件的主要内容，列出核心要点。';
      const sendMsg = (window as any).WA.sendMessage;
      if (typeof sendMsg === 'function') sendMsg();
    }
  }, 600);
}

// ── Workspace File Operations (legacy) ──

async function renameWorkspaceFile(path: string, currentName: string): Promise<void> {
  const item = document.querySelector(`.wa-file-item[data-path="${CSS.escape(path)}"]`) as HTMLElement | null;
  if (!item) return;
  const labelSpan = item.querySelector('.wa-file-label') as HTMLElement | null;
  if (!labelSpan) return;

  const stem = currentName.includes('.') ? currentName.slice(0, currentName.lastIndexOf('.')) : currentName;
  const input = document.createElement('input');
  input.className = 'wa-rename-input';
  input.value = stem;
  labelSpan.replaceWith(input);
  input.focus();
  input.select();

  const commit = async () => {
    const newName = input.value.trim();
    if (!newName || newName === stem) {
      const loadWs = (window as any).WA?.refreshFiles;
      if (typeof loadWs === 'function') await loadWs();
      return;
    }
    try {
      const res = await _csrfFetch('/api/v1/workspace/rename', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, name: newName }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || '重命名失败');
      showToast('已重命名为 ' + json.name, 'success');
    } catch (e: any) {
      showToast(e.message, 'error');
    }
    const loadWs = (window as any).WA?.refreshFiles;
    if (typeof loadWs === 'function') await loadWs();
  };

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      commit();
    }
    if (e.key === 'Escape') {
      const loadWs = (window as any).WA?.refreshFiles;
      if (typeof loadWs === 'function') loadWs();
    }
  });
  input.addEventListener('blur', commit);
}

async function deleteWorkspaceFile(filepath: string): Promise<void> {
  if (!confirm(`确定要将 "${filepath.split('/').pop()}" 移入回收站吗？`)) return;
  try {
    const res = await _csrfFetch('/api/v1/workspace/file?path=' + encodeURIComponent(filepath), { method: 'DELETE' });
    const json = await res.json();
    if (!res.ok) {
      if (res.status === 404) {
        const loadWs = (window as any).WA?.refreshFiles;
        if (typeof loadWs === 'function') loadWs();
        showToast('文件已不存在，已从列表移除', 'info');
      } else {
        throw new Error(json.error || '删除失败');
      }
      return;
    }
    const removeFn = (window as any).WA?._removeOpenTabAfterFileDeleted;
    if (typeof removeFn === 'function') {
      await removeFn(filepath);
    }
    showToast('已移入回收站：' + filepath.split('/').pop(), 'success');
    const loadWs = (window as any).WA?.refreshFiles;
    if (typeof loadWs === 'function') loadWs();
  } catch (e: any) {
    showToast(e.message, 'error');
  }
}

async function deleteFolderWorkspace(folderPath: string, folderName?: string): Promise<void> {
  const name = folderName || folderPath.split('/').pop() || '';
  if (!confirm(`确定要将文件夹 "${name}" 及其所有内容移入回收站吗？`)) return;
  try {
    const res = await _csrfFetch('/api/v1/workspace/folder?path=' + encodeURIComponent(folderPath), { method: 'DELETE' });
    const json = await res.json();
    if (!res.ok) throw new Error(json.error || '删除失败');
    showToast(`已将文件夹 "${name}" 移入回收站`, 'success');
    const loadWs = (window as any).WA?.refreshFiles;
    if (typeof loadWs === 'function') await loadWs();
  } catch (e: any) {
    showToast(e.message, 'error');
  }
}

async function renameFolderWorkspace(path: string, currentName: string): Promise<void> {
  const item = document.querySelector(`.wa-file-item.folder[data-path="${CSS.escape(path)}"]`) as HTMLElement | null;
  if (!item) return;
  const labelSpan = item.querySelector('.wa-file-label') as HTMLElement | null;
  if (!labelSpan) return;

  const input = document.createElement('input');
  input.className = 'wa-rename-input';
  input.value = currentName;
  labelSpan.replaceWith(input);
  input.focus();
  input.select();

  const commit = async () => {
    const newName = input.value.trim();
    if (!newName || newName === currentName) {
      const loadWs = (window as any).WA?.refreshFiles;
      if (typeof loadWs === 'function') await loadWs();
      return;
    }
    try {
      const res = await _csrfFetch('/api/v1/workspace/rename', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, name: newName }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || '重命名失败');
      showToast('已重命名为 ' + json.name, 'success');
    } catch (e: any) {
      showToast(e.message, 'error');
    }
    const loadWs = (window as any).WA?.refreshFiles;
    if (typeof loadWs === 'function') await loadWs();
  };

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      commit();
    }
    if (e.key === 'Escape') {
      const loadWs = (window as any).WA?.refreshFiles;
      if (typeof loadWs === 'function') loadWs();
    }
  });
  input.addEventListener('blur', commit);
}

// ── Legacy Context Menu (workspace tree) ──

function _showCtxMenu(event: MouseEvent, path: string, name: string): void {
  event.preventDefault();
  event.stopPropagation();
  _ctxTarget = { path, name };
  const menu = document.getElementById('wa-ctx-menu');
  if (!menu) return;
  menu.innerHTML = `
    <div class="wa-ctx-item" onclick="WA._ctxOpen()">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
      打开
    </div>
    <div class="wa-ctx-separator"></div>
    <div class="wa-ctx-item" onclick="WA._ctxRename()">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
      重命名
    </div>
    <div class="wa-ctx-item" onclick="WA._ctxCopyPath()">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
      复制路径
    </div>
    <div class="wa-ctx-separator"></div>
    <div class="wa-ctx-item danger" onclick="WA._ctxDelete()">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>
      删除
    </div>`;
  _positionCtxMenu(menu, event, { clampToLeftPanel: true });
}

function _showFolderCtxMenu(event: MouseEvent, path: string, name: string): void {
  event.preventDefault();
  event.stopPropagation();
  _ctxTarget = { path, name };
  const menu = document.getElementById('wa-ctx-menu');
  if (!menu) return;
  menu.innerHTML = `
    <div class="wa-ctx-item" onclick="WA.startNewFile('${path.replace(/'/g, "\\'")}');_closeCtxMenu()">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/></svg>
      新建文件
    </div>
    <div class="wa-ctx-item" onclick="WA.startNewFolder('${path.replace(/'/g, "\\'")}');_closeCtxMenu()">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/></svg>
      新建子文件夹
    </div>
    <div class="wa-ctx-separator"></div>
    <div class="wa-ctx-item" onclick="WA._ctxFolderRename()">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
      重命名
    </div>
    <div class="wa-ctx-separator"></div>
    <div class="wa-ctx-item danger" onclick="WA._ctxFolderDelete()">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>
      删除文件夹
    </div>`;
  _positionCtxMenu(menu, event, { clampToLeftPanel: true });
}

function _ctxOpen(): void {
  _closeCtxMenu();
  if (_ctxTarget.path && typeof (window as any).WA.openWorkspaceFile === 'function') {
    (window as any).WA.openWorkspaceFile(_ctxTarget.path);
  }
}

function _ctxRename(): void {
  _closeCtxMenu();
  if (_ctxTarget.path && typeof renameWorkspaceFile === 'function') {
    renameWorkspaceFile(_ctxTarget.path, _ctxTarget.name || '');
  }
}

function _ctxCopyPath(): void {
  _closeCtxMenu();
  if (_ctxTarget.path) {
    navigator.clipboard
      .writeText(_ctxTarget.path)
      .then(() => showToast('路径已复制', 'success'))
      .catch(() => showToast(_ctxTarget.path || '', 'info'));
  }
}

function _ctxDelete(): void {
  _closeCtxMenu();
  if (_ctxTarget.path && typeof deleteWorkspaceFile === 'function') {
    deleteWorkspaceFile(_ctxTarget.path);
  }
}

function _ctxFolderRename(): void {
  _closeCtxMenu();
  if (!_ctxTarget.path) return;
  renameFolderWorkspace(_ctxTarget.path, _ctxTarget.name || '');
}

function _ctxFolderDelete(): void {
  _closeCtxMenu();
  if (!_ctxTarget.path) return;
  deleteFolderWorkspace(_ctxTarget.path, _ctxTarget.name || '');
}

// ── Register document event listeners for closing context menu ──

document.addEventListener(
  'click',
  (e) => {
    if (!(e.target as HTMLElement)?.closest('#wa-ctx-menu')) _closeCtxMenu();
  },
  true
);
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') _closeCtxMenu();
});

// ── Backward compatibility ──

const wa = (window as any).WA || {};
(window as any).WA = wa;

wa._showBrowserCtx = _showBrowserCtx;
wa._showCtxMenu = _showCtxMenu;
wa._showFolderCtxMenu = _showFolderCtxMenu;
wa._closeCtxMenu = _closeCtxMenu;
wa._fsBrowserOpen = _fsBrowserOpen;
wa._fsBrowserAddToWorkspace = _fsBrowserAddToWorkspace;
wa._fsBrowserAddToTempWorkspace = _fsBrowserAddToTempWorkspace;
wa._fsBrowserSendToAI = _fsBrowserSendToAI;
wa._fsBrowserCopy = _fsBrowserCopy;
wa._fsBrowserCut = _fsBrowserCut;
wa._fsBrowserPaste = _fsBrowserPaste;
wa._fsBrowserCopyPath = _fsBrowserCopyPath;
wa._fsBrowserRename = _fsBrowserRename;
wa._fsBrowserDelete = _fsBrowserDelete;
wa._fsBrowserNewFile = _fsBrowserNewFile;
wa._fsBrowserNewFolder = _fsBrowserNewFolder;
wa._fsBrowserAISummary = _fsBrowserAISummary;
wa.renameWorkspaceFile = renameWorkspaceFile;
wa.deleteWorkspaceFile = deleteWorkspaceFile;
wa.deleteFolderWorkspace = deleteFolderWorkspace;
wa.renameFolderWorkspace = renameFolderWorkspace;
wa._ctxOpen = _ctxOpen;
wa._ctxRename = _ctxRename;
wa._ctxCopyPath = _ctxCopyPath;
wa._ctxDelete = _ctxDelete;
wa._ctxFolderRename = _ctxFolderRename;
wa._ctxFolderDelete = _ctxFolderDelete;
