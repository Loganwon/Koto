// @ts-nocheck
/**
 * File System Browser — Tree rendering, search, browse, live polling, file loader.
 * Workspace file tree.
 */

import { _fileIcon, _escHtml, _FOLDER_OPEN_SVG, _FOLDER_PICK_SVG, _FOLDER_SVG } from './infrastructure';
import { state, _forgetRecentPath, _trackUserOpen, BrowserNode } from './state';
import {
  entrySearchCategory as _entrySearchCategory,
  flattenWorkspaceListFiles as _flattenWorkspaceListFiles,
  formatFileSize as _formatSize,
  isSupportedExtension as _isSupportedExt,
  joinWorkspacePath as _joinWorkspacePath,
  mergeSearchResults as _mergeSearchResults,
  type SearchResult,
} from './fs-tree-helpers';
import { _fileActionButtons, _fileDragAttrs, _fileOpenHitDragAttrs, _isAbsolutePath } from './fs-tree';

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

export function _browserPathKey(rawPath: string): string {
  return String(rawPath || '').trim().replace(/[\\/]+$/, '');
}

export async function _loadBrowserFolderEntries(absPath: string): Promise<any[]> {
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

export async function _doSearch(): Promise<void> {
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
