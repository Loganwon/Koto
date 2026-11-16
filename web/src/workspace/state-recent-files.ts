// @ts-nocheck
/**
 * Global State + Tab Management + Workspace Tree + Recent Files + My/Temp Workspace.
 * Workspace state.
 */

import { _csrfFetch, _fileIcon, _escHtml, _FOLDER_SVG, _FOLDER_OPEN_SVG } from './infrastructure';
import { logger } from '../shared/logger';
import { _clearActiveFileState, _destroyActiveEditorForClosedFile, _removeOpenTabAfterFileDeleted, _renderTabs, _switchToTabImpl } from './state-tab-lifecycle';
import { _syncWorkspaceSurfaces } from './state-editor-layout';
import { RecentFileEntry } from './state';

// ── Recent Files ──

export const _WA_RECENT_KEY = 'wa_user_recent_v1';

function _recentFileSupportedExt(ext: string): boolean {
  return new Set([
    'docx', 'xlsx', 'pptx', 'pdf',
    'txt', 'md', 'markdown', 'csv', 'json',
    'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'svg',
  ]).has(String(ext || '').toLowerCase().replace(/^\./, ''));
}

function _formatRecentSize(bytes: number): string {
  if (!bytes || bytes < 0) return '';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}

export function _trackUserOpen(path: string): void {
  if (!path) return;
  const name = path.split(/[\\/]/).pop() || path;
  try {
    const list: RecentFileEntry[] = JSON.parse(localStorage.getItem(_WA_RECENT_KEY) || '[]');
    const normalizedPath = _normalizeRecentPath(path);
    const filtered = list.filter((file) => _normalizeRecentPath(file.path) !== normalizedPath);
    filtered.unshift({ path, name, ts: Date.now() });
    localStorage.setItem(_WA_RECENT_KEY, JSON.stringify(filtered.slice(0, 30)));
  } catch (_) {
    /* ignore */
  }
}

export function _forgetRecentPath(path: string): void {
  if (!path) return;
  try {
    const normalizedPath = _normalizeRecentPath(path);
    const list: RecentFileEntry[] = JSON.parse(localStorage.getItem(_WA_RECENT_KEY) || '[]');
    const filtered = list.filter((file) => _normalizeRecentPath(file.path) !== normalizedPath);
    if (filtered.length !== list.length) {
      localStorage.setItem(_WA_RECENT_KEY, JSON.stringify(filtered));
    }
  } catch (_) {
    /* ignore */
  }
}

function _normalizeRecentPath(path: string): string {
  return String(path || '').trim().replace(/\\/g, '/').toLowerCase();
}

function _recentFileDragAttrs(): string {
  return 'draggable="true" data-wa-file-draggable="true"';
}

function _recentFileOpenHitDragAttrs(): string {
  return 'draggable="false" data-wa-file-action="open"';
}

function _loadLocalRecentFiles(): RecentFileEntry[] {
  try {
    return JSON.parse(localStorage.getItem(_WA_RECENT_KEY) || '[]');
  } catch (_) {
    return [];
  }
}

function _normalizeRecentEntry(file: any, source: 'local' | 'api'): RecentFileEntry | null {
  const path = String(file && file.path || '').trim();
  if (!path) return null;
  const name = String(file.name || path.split(/[\\/]/).pop() || path).trim();
  const rawTs = Number(file.ts || 0);
  const mtimeTs = Number(file.mtime || 0) ? Number(file.mtime) * 1000 : 0;
  return {
    path,
    name,
    ts: source === 'local' ? (rawTs || Date.now()) : (mtimeTs || rawTs || 0),
    category: String(file.category || '').trim(),
    size_bytes: Number(file.size_bytes || 0) || 0,
  };
}

function _mergeRecentFiles(localRecent: RecentFileEntry[], apiRecent: RecentFileEntry[]): RecentFileEntry[] {
  if (localRecent.length) {
    const apiByPath = new Map(apiRecent.map((file) => [_normalizeRecentPath(file.path), file]));
    return localRecent
      .map((file) => {
        const apiFile = apiByPath.get(_normalizeRecentPath(file.path));
        return Object.assign({}, apiFile || {}, file, {
          category: file.category || apiFile?.category,
          size_bytes: file.size_bytes || apiFile?.size_bytes,
        });
      })
      .sort((a, b) => Number(b.ts || 0) - Number(a.ts || 0))
      .slice(0, 20);
  }
  const seen = new Set<string>();
  const out: RecentFileEntry[] = [];
  apiRecent.forEach((file) => {
    const normalized = _normalizeRecentPath(file.path);
    if (!normalized || seen.has(normalized)) return;
    seen.add(normalized);
    out.push(file);
  });
  return out
    .sort((a, b) => Number(b.ts || 0) - Number(a.ts || 0))
    .slice(0, 20);
}

async function _filterAvailableRecentFiles(files: RecentFileEntry[]): Promise<RecentFileEntry[]> {
  if (!files.length) return files;
  try {
    const response = await _csrfFetch('/api/v1/workspace/recent_files/status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths: files.map((file) => file.path).slice(0, 50) }),
    });
    if (!response.ok) return files;
    const data = await response.json();
    const statuses = Array.isArray(data.files) ? data.files : [];
    const missing = new Set(
      statuses
        .filter((entry: any) => entry && entry.exists === false)
        .map((entry: any) => _normalizeRecentPath(entry.path)),
    );
    if (!missing.size) return files;
    statuses.forEach((entry: any) => {
      if (entry && entry.exists === false) _forgetRecentPath(String(entry.path || ''));
    });
    return files.filter((file) => !missing.has(_normalizeRecentPath(file.path)));
  } catch (error) {
    logger.debug('state', 'Recent-file availability check skipped', error);
    return files;
  }
}

export async function loadRecentFiles(): Promise<void> {
  const list = document.getElementById('wa-recent-list');
  if (!list) return;
  const localRecent = _loadLocalRecentFiles()
    .map((file) => _normalizeRecentEntry(file, 'local'))
    .filter(Boolean) as RecentFileEntry[];
  let apiRecent: RecentFileEntry[] = [];
  try {
    const res = await fetch('/api/files/recent?days=30&limit=20');
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data.files)) {
        apiRecent = data.files
          .map((file: any) => _normalizeRecentEntry(file, 'api'))
          .filter(Boolean) as RecentFileEntry[];
      }
    }
  } catch (_) {
    apiRecent = [];
  }

  const userRecent = await _filterAvailableRecentFiles(
    _mergeRecentFiles(localRecent, apiRecent),
  );
  if (!userRecent.length) {
    list.innerHTML = '<div class="wa-empty-row">暂无最近文件</div>';
    return;
  }

  list.innerHTML = userRecent.slice(0, 20).map((file) => {
    const name = file.name || (file.path || '').split(/[\\/]/).pop() || '';
    const ext = (name.includes('.') ? (name.split('.').pop() || '') : '').toLowerCase();
    const icon = _fileIcon(ext, file.category || '');
    const date = file.ts ? new Date(file.ts).toLocaleDateString('zh-CN') : '';
    const size = file.size_bytes ? ' · ' + _formatRecentSize(file.size_bytes) : '';
    const supported = _recentFileSupportedExt(ext);
    return `<div class="wa-file-item file wa-recent-file" title="${_escHtml(file.path || '')}"`
      + ` data-path="${_escHtml(file.path || '')}" data-supported="${supported}"`
      + ` ${_recentFileDragAttrs()}`
      + `>`
      + `<button type="button" class="wa-file-open-hit" ${_recentFileOpenHitDragAttrs()} aria-label="打开 ${_escHtml(name)}"></button>`
      + `<span class="wa-recent-indent"></span>${icon}`
      + `<span class="wa-file-label">${_escHtml(name)}</span>`
      + `<span class="wa-recent-date">${date}${size}</span>`
      + `</div>`;
  }).join('');
}
