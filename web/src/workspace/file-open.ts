/**
 * Workspace file mounting for the TS bundle.
 *
 * Exposes WA._applyFileJson so fs-tree can apply parsed file responses.
 */

import {
  state,
  _fsHandleMap,
  _normalizeCapabilityProfile,
  _renderTabs,
  _registerSwitchToTab,
  _primeEditorLayout,
  _syncWorkspaceSurfaces,
  _waitForEditorLayout,
  _destroyActiveEditorForClosedFile,
  toggleWorkspace,
  loadWorkspaceFiles,
  type TabInfo,
} from './state';
import { _escHtml } from './infrastructure';
import { _ensurePdfJS, _ensureTipTap, _ensureUniverSheets, _ensureWorkbookDefaults } from '../editors/cdn-loaders';
import { KotoTextEditor, _setupDocOutline, loadPptxEditor, loadPdfViewer, loadXlsxEditor, loadImageViewer } from '../editors/lazy-loaders';

function _fileExt(fileName: string): string {
  return (String(fileName || '').split('.').pop() || '').toLowerCase();
}

function _setHeaderFileName(name: string): void {
  const fileNameEl = document.getElementById('wa-file-name');
  if (fileNameEl) fileNameEl.textContent = name || '未打开文件';
}

function _showPdfOpenError(error: any): void {
  const outer = document.getElementById('wa-pdf-editor') as HTMLElement | null;
  const viewer = document.getElementById('wa-pdf-viewer') as HTMLElement | null;
  if (outer) outer.classList.add('active');
  if (viewer) {
    viewer.classList.add('active');
    const message = error && error.message ? error.message : String(error || '未知错误');
    viewer.innerHTML = `
      <div style="max-width:720px;margin:40px auto;padding:16px 18px;border:1px solid rgba(239,68,68,.45);border-radius:6px;background:#fff;color:#3f1f1f;line-height:1.6;font-size:13px;">
        <div style="font-weight:700;margin-bottom:6px;color:#b42318;">PDF 加载失败</div>
        <div>${_escHtml(message)}</div>
      </div>`;
  }
}

function _syncPrimarySaveButtons(tab: TabInfo | null): void {
  const readonly = !tab || tab.fileType === 'pdf' || tab.fileType === 'image';
  const saveBtn = document.getElementById('wa-save-btn') as HTMLButtonElement | null;
  const saveAsBtn = document.getElementById('wa-saveas-btn') as HTMLButtonElement | null;
  const toolbar = document.querySelector('.wa-unified-toolbar') as HTMLElement | null;
  if (toolbar) toolbar.hidden = !tab;
  if (saveBtn) {
    saveBtn.hidden = !tab;
    saveBtn.disabled = readonly;
  }
  if (saveAsBtn) {
    saveAsBtn.hidden = !tab;
    saveAsBtn.disabled = readonly;
  }
}

function _syncZoomControls(fileType: string | null): void {
  const pdfZoomCtrl = document.getElementById('wa-pdf-zoom-ctrl') as HTMLElement | null;
  if (pdfZoomCtrl) pdfZoomCtrl.style.display = fileType === 'pdf' ? 'flex' : 'none';
  const docxZoomCtrl = document.getElementById('wa-docx-zoom-ctrl') as HTMLElement | null;
  if (docxZoomCtrl) docxZoomCtrl.style.display = fileType === 'docx' ? 'flex' : 'none';
}

export function _serializeEditorForTab(_tab: TabInfo | null, editor: any): any {
  if (!editor || typeof editor.serialize !== 'function') return null;
  if (_tab && _tab.fileType === 'docx' && typeof editor.getDocxSavePayload === 'function') {
    return editor.getDocxSavePayload();
  }
  return editor.serialize();
}

export function _stableWorkspaceSnapshot(value: any): string {
  if (value === undefined) return 'undefined';
  if (value === null) return 'null';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value);
  } catch (_) {
    return String(value);
  }
}

export function _rememberSavedSnapshotForTab(tab: TabInfo | null, editor: any = state.activeEditor): void {
  if (!tab) return;
  const data = editor ? _serializeEditorForTab(tab, editor) : (tab.cache !== undefined && tab.cache !== null ? tab.cache : tab.serverData);
  tab.savedSnapshot = _stableWorkspaceSnapshot(data);
}

async function _mountDocx(tab: TabInfo, data: any): Promise<void> {
  await _ensureTipTap();
  const html = typeof tab.cache === 'string' && (tab.cache as string).trim()
    ? tab.cache
    : (data && data.html) || '';
  state.activeEditor = new (window as any).KotoDocxEditorLib.KotoTipTapEditor() as any;
  state.activeEditor!.render(html, data || {});
  setTimeout(() => _setupDocOutline((data && data.headings) || []), 0);
  setTimeout(() => {
    const syncReviewState = (window as any)._syncReviewStateForActiveFile;
    if (typeof syncReviewState === 'function') syncReviewState();
  }, 0);
}

async function _mountEditor(tab: TabInfo, data: any): Promise<void> {
  _primeEditorLayout(tab.fileType);
  await _waitForEditorLayout(tab.fileType);

  if (tab.fileType === 'docx') {
    await _mountDocx(tab, data);
  } else if (tab.fileType === 'xlsx') {
    await _ensureUniverSheets();
    state.activeEditor = new (window as any).KotoXlsxEditor() as any;
    const workbook = tab.cache && tab.cache.snapshot ? tab.cache.snapshot : data;
    state.activeEditor!.render(_ensureWorkbookDefaults(workbook));
  } else if (tab.fileType === 'pptx') {
    state.activeEditor = new (await loadPptxEditor()).KotoPptxEditor() as any;
    state.activeEditor!.render(tab.cache !== null && tab.cache !== undefined ? tab.cache : data);
  } else if (tab.fileType === 'pdf') {
    try {
      await _ensurePdfJS();
      state.activeEditor = new (await loadPdfViewer()).KotoPdfViewer() as any;
      await state.activeEditor!.render(data && data.raw_url, data);
    } catch (error) {
      console.error('[WA] PDF 打开失败:', error);
      _showPdfOpenError(error);
    }
  } else if (tab.fileType === 'image') {
    state.activeEditor = new (await loadImageViewer()).KotoImageViewer() as any;
    state.activeEditor!.render(data && data.raw_url);
  } else if (tab.fileType === 'text' || tab.fileType === 'code') {
    state.activeEditor = new KotoTextEditor(tab.fileType) as any;
    state.activeEditor!.render(data);
  } else {
    const textEditor = document.getElementById('wa-text-editor');
    const textArea = document.getElementById('wa-text-content') as HTMLTextAreaElement | null;
    if (textEditor && textArea) {
      textEditor.classList.add('active');
      textArea.value = JSON.stringify(data || {}, null, 2);
    }
  }
  _syncWorkspaceSurfaces();
}

function _applyTabState(tab: TabInfo): void {
  state.activeTabPath = tab.path;
  state.fileId = tab.fileId || null;
  state.fileType = tab.fileType;
  state.fileName = tab.name;
  state.filePath = tab.filePath || tab.path || null;
  state.wsSourcePath = tab.path;
  state.capabilityProfile = tab.capabilityProfile || null;
  _setHeaderFileName(tab.name);
  _syncPrimarySaveButtons(tab);
  _syncZoomControls(tab.fileType);
  toggleWorkspace(true);
  if (typeof (window as any).WA?.closeMobileFiles === 'function') {
    (window as any).WA.closeMobileFiles();
  }
}

async function _switchToTabImpl(path: string): Promise<void> {
  if (state.activeTabPath === path) return;
  if (state.activeEditor && state.activeTabPath) {
    const currentTab = state.openTabs.find((tab) => tab.path === state.activeTabPath);
    if (currentTab && state.fileType !== 'pdf' && state.fileType !== 'image') {
      currentTab.cache = _serializeEditorForTab(currentTab, state.activeEditor);
    }
  }
  _destroyActiveEditorForClosedFile();
  const tab = state.openTabs.find((item) => item.path === path);
  if (!tab) return;
  _applyTabState(tab);
  await _mountEditor(tab, tab.serverData);
  if (!tab.modified && !tab.savedSnapshot) _rememberSavedSnapshotForTab(tab, state.activeEditor);
  _renderTabs();
  _highlightActiveFile(path);
}

function _highlightActiveFile(path: string): void {
  document.querySelectorAll('.wa-file-item').forEach((element) => {
    const el = element as HTMLElement;
    el.classList.toggle('active', el.dataset.path === path);
  });
}

export async function _applyFileJson(json: any, wsPath: string | null, fsHandle: any = null): Promise<any> {
  const fileName = json.file_name || (wsPath ? String(wsPath).split(/[\\/]/).pop() : 'file');
  const fileType = json.file_type || 'text';
  const resolvedPath = wsPath || json.ws_source_path || json.source_path || json.temp_path || fileName;
  const existingTabIdx = state.openTabs.findIndex((tab) => tab.path === resolvedPath);
  const existingTab = existingTabIdx >= 0 ? state.openTabs[existingTabIdx] : null;

  if (state.activeEditor && state.activeTabPath && state.activeTabPath !== resolvedPath) {
    const currentTab = state.openTabs.find((tab) => tab.path === state.activeTabPath);
    if (currentTab && state.fileType !== 'pdf' && state.fileType !== 'image') {
      currentTab.cache = _serializeEditorForTab(currentTab, state.activeEditor);
    }
  }
  _destroyActiveEditorForClosedFile();

  const tabEntry: TabInfo = {
    path: resolvedPath,
    name: fileName,
    ext: _fileExt(fileName),
    filePath: json.temp_path || resolvedPath,
    fileType,
    fileId: json.file_id || null,
    serverData: json.data,
    cache: undefined,
    savedSnapshot: null,
    modified: false,
    capabilityProfile: _normalizeCapabilityProfile(json.capability_profile, fileType, fileName),
    reviewState: existingTab && existingTab.reviewState
      ? JSON.parse(JSON.stringify(existingTab.reviewState))
      : { comments: [], proposals: [], focusedId: '', expandedId: '' },
    fsHandle: fsHandle || null,
  };

  if (fsHandle) _fsHandleMap.set(resolvedPath, fsHandle);
  if (existingTabIdx >= 0) state.openTabs[existingTabIdx] = tabEntry;
  else state.openTabs.push(tabEntry);

  _applyTabState(tabEntry);
  await _mountEditor(tabEntry, json.data);
  _rememberSavedSnapshotForTab(tabEntry, state.activeEditor);
  if (typeof (window as any).WA?.clearExternalFileChange === 'function') {
    (window as any).WA.clearExternalFileChange(resolvedPath);
  }
  _renderTabs();
  _highlightActiveFile(resolvedPath);
  setTimeout(() => {
    if (typeof (window as any).WA?._softRefreshBrowser === 'function') {
      (window as any).WA._softRefreshBrowser().catch(() => {});
    } else {
      loadWorkspaceFiles().catch(() => {});
    }
  }, 600);
  return json;
}

_registerSwitchToTab(_switchToTabImpl);

const wa = (window as any).WA || {};
(window as any).WA = wa;
(window as any)._serializeEditorForTab = _serializeEditorForTab;
wa._applyFileJson = _applyFileJson;
wa._syncPrimarySaveButtons = _syncPrimarySaveButtons;
wa._stableWorkspaceSnapshot = _stableWorkspaceSnapshot;
wa._rememberSavedSnapshotForTab = _rememberSavedSnapshotForTab;

// Keeps old inline templates that call global helpers from breaking in the TS bundle.
(window as any)._serializeEditorForTab = _serializeEditorForTab;
(window as any)._stableWorkspaceSnapshot = _stableWorkspaceSnapshot;
(window as any)._rememberSavedSnapshotForTab = _rememberSavedSnapshotForTab;
(window as any)._escHtml = (window as any)._escHtml || _escHtml;
