// @ts-nocheck
/**
 * Global State + Tab Management + Workspace Tree + Recent Files + My/Temp Workspace.
 * Workspace state.
 */

import { _csrfFetch, _fileIcon, _escHtml, _FOLDER_SVG, _FOLDER_OPEN_SVG } from './infrastructure';
import { logger } from '../shared/logger';
import { CapabilityProfile, TabInfo, _normalizeCapabilityProfile, _switchToTab, _syncWorkspaceSurfaces, _updateStatusBar, state, toggleWorkspace } from './state';

// ── Tab Info ──

function _tabDisplayInfo(tab: TabInfo | null): { extAttr: string; title: string } {
  const profile = _normalizeCapabilityProfile(tab?.capabilityProfile, tab?.fileType || null, tab?.name || null);
  const extAttr = String(profile.format || tab?.ext || tab?.fileType || '').toLowerCase();
  return {
    extAttr,
    title: String((tab?.name || '')).trim(),
  };
}

export function _activeCapabilityProfile(tab?: TabInfo | null): CapabilityProfile {
  const source = tab || state.openTabs.find((item) => item.path === state.activeTabPath) || null;
  if (source) return _normalizeCapabilityProfile(source.capabilityProfile, source.fileType, source.name);
  return _normalizeCapabilityProfile(state.capabilityProfile, state.fileType, state.fileName);
}

// ── Clear Active File ──

export function _clearActiveFileState(): void {
  state.activeTabPath = null;
  state.fileId = null;
  state.fileType = null;
  state.fileName = null;
  state.filePath = null;
  state.wsSourcePath = null;
  state.capabilityProfile = null;
  const fileNameEl = document.getElementById('wa-file-name');
  if (fileNameEl) fileNameEl.textContent = '全格式 AI 工作区';
  _syncCurrentFileChrome();
  const saveBtn = document.getElementById('wa-save-btn') as HTMLButtonElement | null;
  if (saveBtn) saveBtn.disabled = true;
  const saveAsBtn = document.getElementById('wa-saveas-btn') as HTMLButtonElement | null;
  if (saveAsBtn) saveAsBtn.disabled = true;
}

export function _syncCurrentFileChrome(): void {
  const activeTab = state.openTabs.find((tab) => tab.path === state.activeTabPath) || null;
  const toolbar = document.querySelector('.wa-unified-toolbar') as HTMLElement | null;
  const fileNameEl = document.getElementById('wa-file-name');
  const filePathEl = document.getElementById('wa-file-path');
  const dirtyEl = document.getElementById('wa-file-dirty');
  if (toolbar) toolbar.hidden = !activeTab;
  if (fileNameEl) fileNameEl.textContent = activeTab ? (activeTab.name || '未命名文件') : '全格式 AI 工作区';
  if (filePathEl) {
    filePathEl.textContent = '';
    filePathEl.toggleAttribute('hidden', true);
    filePathEl.removeAttribute('title');
  }
  if (dirtyEl) dirtyEl.toggleAttribute('hidden', !activeTab?.modified);
}

// ── Destroy Editor ──

export function _destroyActiveEditorForClosedFile(): void {
  if (state.activeEditor) {
    try {
      state.activeEditor.destroy?.();
    } catch (error) {
      logger.error('state', 'Editor destroy failed', error);
    }
  }
  state.activeEditor = null;
  _deactivateWorkspaceEditors();
  // _docListeners cleanup is in infrastructure; skip duplication
}

function _deactivateWorkspaceEditors(): void {
  [
    'wa-docx-editor',
    'wa-xlsx-editor',
    'wa-pptx-editor',
    'wa-pdf-editor',
    'wa-pdf-viewer',
    'wa-image-viewer',
    'wa-text-editor',
  ].forEach((id) => document.getElementById(id)?.classList.remove('active'));
  _syncWorkspaceSurfaces();
}

// ── Remove Tab After Delete ──

export async function _removeOpenTabAfterFileDeleted(path: string): Promise<boolean> {
  const idx = state.openTabs.findIndex((tab) => tab.path === path);
  if (idx < 0) return false;
  const wasActive = state.openTabs[idx].path === state.activeTabPath;
  if (wasActive) {
    _destroyActiveEditorForClosedFile();
    _clearActiveFileState();
    _deactivateWorkspaceEditors();
  }
  state.openTabs.splice(idx, 1);
  if (wasActive) {
    if (state.openTabs.length > 0) {
      const neighborIdx = Math.min(idx, state.openTabs.length - 1);
      await _switchToTab(state.openTabs[neighborIdx].path);
    } else {
      toggleWorkspace(false);
      _renderTabs();
    }
  } else {
    _renderTabs();
  }
  return true;
}

// ── Render Tabs ──

export function _renderTabs(): void {
  const bar = document.getElementById('wa-tab-bar');
  if (!bar) return;
  bar.classList.toggle('single-tab', state.openTabs.length <= 1);
  bar.innerHTML = state.openTabs
    .map((tab) => {
      const active = tab.path === state.activeTabPath ? ' active' : '';
      const modified = tab.modified ? ' modified' : '';
      const info = _tabDisplayInfo(tab);
      const extAttr = _escHtml(info.extAttr || '');
      const nameEsc = _escHtml(tab.name || '');
      const titleEsc = _escHtml(info.title || tab.name || '');
      return (
        `<div class="wa-tab${active}${modified}" data-path="${tab.path.replace(/"/g, '&quot;')}" data-ext="${extAttr}"` +
        ` data-wa-tab-action="open" title="${titleEsc}">` +
        `<span class="tab-icon">${_fileIcon(tab.ext)}</span>` +
        `<span class="tab-main">` +
        `<span class="tab-label">${nameEsc}</span>` +
        `</span>` +
        `<span class="tab-dirty"></span>` +
        `<button class="tab-close" data-wa-tab-action="close" title="关闭">×</button>` +
        `</div>`
      );
    })
    .join('');
  _syncCurrentFileChrome();
  _updateStatusBar();
}

// ── Switch Tab ──

// These are declared here but full implementations reference editor mounters defined elsewhere.
// We export the signatures and assign full implementations after all modules are loaded.

export let _switchToTabImpl: ((path: string) => Promise<void>) | null = null;

export function _setSwitchToTabImpl(fn: (path: string) => Promise<void>): void {
  _switchToTabImpl = fn;
}
