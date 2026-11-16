/**
 * Global State + Tab Management + Workspace Tree + Recent Files + My/Temp Workspace.
 * Workspace state.
 */

import { _csrfFetch, _fileIcon, _escHtml, showToast, _FOLDER_SVG, _FOLDER_OPEN_SVG } from './infrastructure';
import { getFeatureRegistry } from '../shared/feature-registry';

// ── Interfaces ──

export interface TabInfo {
  path: string;
  name: string;
  ext: string;
  fileType: string;
  fileId?: string | null;
  sourceSha256?: string;
  filePath?: string | null;
  serverData: ServerFileData;
  cache?: Record<string, unknown>;
  savedSnapshot?: string | null;
  modified?: boolean;
  capabilityProfile?: CapabilityProfile | null;
  reviewState?: Record<string, unknown>;
  fsHandle?: FileSystemHandle;
}

export interface CapabilityProfile {
  format: string;
  family: string;
  workspace: {
    open_mode: string;
    edit_mode: string;
    progressive_loading: boolean;
  };
  task: {
    analysis_mode: string;
    annotation_support: string;
    write_support: string;
  };
  ocr_mode: string;
  actions: string[];
  notes?: string[];
}

export interface FsClipboardEntry {
  path: string;
  name: string;
  mode: 'copy' | 'cut';
}


export interface BrowserNode {
  path: string;
  name: string;
  type: 'folder' | 'file' | 'drive' | 'quick';
  ext?: string;
  category?: string;
  mtime?: number;
  size_bytes?: number;
  supported?: boolean;
  children?: BrowserNode[];
}

export interface BrowserRoots {
  drives: BrowserNode[];
  quick_access: BrowserNode[];
}

export interface RecentFileEntry {
  path: string;
  name: string;
  ts: number;
  category?: string;
  size_bytes?: number;
}

export interface MyWorkspaceFile {
  path: string;
  name: string;
  ext: string;
  addedAt: number;
}

// ?? Domain type interfaces ??

export interface ServerFileData {
  file_id?: string;
  file_name?: string;
  file_type?: string;
  file_path?: string;
  content?: unknown;
  text?: string;
  html?: string;
  pages?: unknown[];
  preview?: string;
  error?: string;
  capability?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface ModelInfo {
  id: string;
  name: string;
  provider: string;
  [key: string]: unknown;
}

export interface AiFileContext {
  path: string;
  name: string;
  ext?: string;
  content?: string | null;
  loading?: boolean;
  error?: string;
  warning?: string;
  requestId?: string;
  originalChars?: number;
  type?: string;
  [key: string]: unknown;
}

export interface TaskPayload {
  prompt?: string;
  files?: string[];
  task_type?: string;
  model?: string;
  feedback?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface EditorInstance {
  destroy?: () => void;
  getContent?: () => unknown;
  setContent?: (data: unknown) => void;
  render: (...args: unknown[]) => unknown;
  applyToolCall?: (command: any) => unknown;
  appendToolCall?: (command: any) => unknown;
  replaceSelectionWith?: (mode: string, selection: any, rawText: string) => unknown;
  editor?: unknown;
  [key: string]: unknown;
}

export interface WorkspaceState {
  fileId: string | null;
  sourceSha256?: string;
  fileType: string | null;
  fileName: string | null;
  filePath: string | null;
  wsSourcePath: string | null;
  capabilityProfile: CapabilityProfile | null;
  activeEditor: EditorInstance | null;
  socket: WebSocket | null;
  isLoading: boolean;
  conversation: Array<{ role: string; content: string }>;
  sortBy: string;
  sectionOpen: Record<string, boolean>;
  searchQuery: string;
  _allFiles: Record<string, unknown>[];
  pinnedSelection: Record<string, unknown> | null;
  lastPinnedSel: Record<string, unknown> | null;
  selectMode: boolean;
  selectedFiles: Set<string>;
  openTabs: TabInfo[];
  activeTabPath: string | null;
  lockedModel: string;
  _reviewCenterOpen: boolean;
  _reviewMode: string;
  _editingReviewCommentId: string;
  _editingReviewProposalId: string;
  _reviewSelectionSnapshot: Record<string, unknown> | null;
  _reviewToolbarSelectionSnapshot: Record<string, unknown> | null;
  _reviewToolbarSelectionCapturedAt: number;
  _reviewNavQuery: string;
  _reviewLauncherVisible: boolean;
  _activeProposalBatch: Record<string, unknown>[];
  _streamAbortCtrl: AbortController | null;
  _cancelCurrentTask?: (() => void | Promise<void>) | null;
  _pendingTaskPayload: TaskPayload | null;
  _pendingTaskPayloadUsesFeedback: boolean;
  _pendingTaskFollowupContext: Record<string, unknown> | null;
  _pendingTaskFollowupPrompt: string | null;
  _recentOpen: boolean;
  _workspacePath: string;
  _workspaceName?: string;
  _browserRoots: BrowserRoots | null;
  _browserExpanded: Set<string>;
  _browserCache: Record<string, any>;
  _browserLoading: Record<string, Promise<any[]>>;
  _fsClipboard: FsClipboardEntry | null;
  _searchFilter: string;
  _searchActive: boolean;
  _browserSort: string;
  _livePollTimer: ReturnType<typeof setInterval> | null;
  _availableModels: ModelInfo[];
  _modelMap: Record<string, unknown>;
  _modelsReady: boolean;
  _cloudProvider: string;
  _modelCatalogPromise: Promise<any> | null;
  _activeRoute: Record<string, unknown> | null;
  _activeTaskReconnectors: Map<string, any>;
  _localRuntimeModel: string;
  _localModelSupportsTools: boolean | null;
  _modelChoicePendingMode?: string;
  _modelChoiceUpdatedAt?: number;
  _modelChoicePromise?: Promise<any> | null;
  useAgentMode: boolean;
  _aiFileContext: AiFileContext[];
  _aiTargetFileIdx: number;
  _tempWorkspace: Record<string, unknown>[];
  _reviewEntryLookup?: Map<string, any>;
  _activeProposals?: any[];
}

// ── Constants ──

const _WA_EMPTY_WORKSPACE_LAYOUT = {
  open_tabs: [] as TabInfo[],
  active_tab_path: null as string | null,
};

const _WA_MODEL_MODES = new Set(['cloud', 'deepseek', 'local']);

export function _normalizeWorkspaceModelMode(value: string, fallback: string = 'deepseek'): string {
  const normalized = String(value || '').trim().toLowerCase();
  return _WA_MODEL_MODES.has(normalized) ? normalized : fallback;
}

// ── Global State ──

export const state: WorkspaceState = {
  fileId: null,
  fileType: null,
  fileName: null,
  filePath: null,
  wsSourcePath: null,
  capabilityProfile: null,
  activeEditor: null,
  socket: null,
  isLoading: false,
  conversation: [],
  sortBy: localStorage.getItem('wa_sort_by') || 'name',
  sectionOpen: JSON.parse(localStorage.getItem('wa_sections') || '{"workspace":true}'),
  searchQuery: '',
  _allFiles: [],
  pinnedSelection: null,
  lastPinnedSel: null,
  selectMode: false,
  selectedFiles: new Set(),
  openTabs: [..._WA_EMPTY_WORKSPACE_LAYOUT.open_tabs],
  activeTabPath: _WA_EMPTY_WORKSPACE_LAYOUT.active_tab_path,
  // Runtime settings are server-authoritative.  The old localStorage value
  // could outlive a settings change and briefly route chat to the wrong mode.
  lockedModel: 'deepseek',
  _reviewCenterOpen: localStorage.getItem('wa_review_center_open') !== '0',
  _reviewMode: ['all', 'comments', 'proposals'].includes(localStorage.getItem('wa_review_mode') || '')
    ? localStorage.getItem('wa_review_mode') || 'all'
    : 'all',
  _editingReviewCommentId: '',
  _editingReviewProposalId: '',
  _reviewSelectionSnapshot: null,
  _reviewToolbarSelectionSnapshot: null,
  _reviewToolbarSelectionCapturedAt: 0,
  _reviewNavQuery: '',
  _reviewLauncherVisible: false,
  _activeProposalBatch: [],
  _streamAbortCtrl: null,
  _pendingTaskPayload: null,
  _pendingTaskPayloadUsesFeedback: false,
  _pendingTaskFollowupContext: null,
  _pendingTaskFollowupPrompt: null,
  _recentOpen: true,
  _workspacePath: '',
  _browserRoots: null,
  _browserExpanded: new Set(),
  _browserCache: {},
  _browserLoading: {},
  _fsClipboard: null,
  _searchFilter: 'all',
  _searchActive: false,
  _browserSort: localStorage.getItem('wa_browser_sort') || 'name',
  _livePollTimer: null,
  _availableModels: [],
  _modelMap: {},
  _modelsReady: false,
  _cloudProvider: 'deepseek',
  _modelCatalogPromise: null,
  _activeRoute: null,
  _activeTaskReconnectors: new Map(),
  _localRuntimeModel: '',
  _localModelSupportsTools: null,
  _modelChoicePromise: null,
  useAgentMode: localStorage.getItem('wa_use_agent') !== 'off',
  _aiFileContext: [],
  _aiTargetFileIdx: -1,
  _tempWorkspace: [],
};

export const _fsHandleMap = new Map<string, any>();

export const _WA_RUNTIME_SESSION_ID: string = (() => {
  try {
    const stored = sessionStorage.getItem('wa_runtime_session_id');
    if (stored && /^workspace_runtime_/i.test(stored)) return stored;
  } catch (_) {
    /* ignore */
  }

  let generated = '';
  try {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      generated = `workspace_runtime_${window.crypto.randomUUID().replace(/-/g, '')}`;
    }
  } catch (_) {
    /* ignore */
  }
  if (!generated) {
    generated = `workspace_runtime_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
  }
  try {
    sessionStorage.setItem('wa_runtime_session_id', generated);
  } catch (_) {
    /* ignore */
  }
  return generated;
})();

// ── Capability Profile ──

function _inferCapabilityFormat(fileType: string | null, fileName: string | null): string {
  const fromName = (String(fileName || '').split('.').pop() || '').toLowerCase();
  if (fromName) return fromName;
  if (fileType === 'text') return 'txt';
  if (fileType === 'code') return 'code';
  return String(fileType || 'unknown').toLowerCase();
}

export function _fallbackCapabilityProfile(fileType: string | null, fileName: string | null): CapabilityProfile {
  const type = String(fileType || '').toLowerCase();
  const format = _inferCapabilityFormat(type, fileName);
  if (type === 'pdf') {
    return {
      format,
      family: 'document',
      workspace: { open_mode: 'native', edit_mode: 'annotate_only', progressive_loading: false },
      task: { analysis_mode: 'native_with_ocr', annotation_support: 'best_effort', write_support: 'none' },
      ocr_mode: 'fallback',
      actions: ['preview', 'analyze', 'annotate'],
    };
  }
  if (type === 'image') {
    return {
      format,
      family: 'image',
      workspace: { open_mode: 'native', edit_mode: 'none', progressive_loading: false },
      task: { analysis_mode: 'sidecar_only', annotation_support: 'none', write_support: 'none' },
      ocr_mode: 'auxiliary',
      actions: ['preview'],
    };
  }
  if (type === 'docx' || type === 'xlsx' || type === 'pptx' || type === 'text' || type === 'code') {
    return {
      format,
      family: type === 'xlsx' ? 'spreadsheet' : type === 'pptx' ? 'presentation' : type === 'docx' ? 'document' : type,
      workspace: { open_mode: 'native', edit_mode: 'native', progressive_loading: type === 'docx' },
      task: { analysis_mode: 'native', annotation_support: 'none', write_support: 'native' },
      ocr_mode: 'none',
      actions: ['preview', 'edit', 'analyze'],
    };
  }
  return {
    format,
    family: type || 'unknown',
    workspace: { open_mode: 'unsupported', edit_mode: 'none', progressive_loading: false },
    task: { analysis_mode: 'none', annotation_support: 'none', write_support: 'none' },
    ocr_mode: 'none',
    actions: ['preview'],
  };
}

export function _normalizeCapabilityProfile(profile: any, fileType: string | null, fileName: string | null): CapabilityProfile {
  const fallback = _fallbackCapabilityProfile(fileType, fileName);
  if (!profile || typeof profile !== 'object') return fallback;
  const normalized = Object.assign({}, fallback, _cloneSerializable(profile, {}) || {});
  normalized.workspace = Object.assign({}, fallback.workspace, normalized.workspace || {});
  normalized.task = Object.assign({}, fallback.task, normalized.task || {});
  normalized.actions = Array.isArray(normalized.actions) ? normalized.actions.slice() : fallback.actions.slice();
  normalized.notes = Array.isArray(normalized.notes) ? normalized.notes.slice() : [];
  normalized.format = String(normalized.format || fallback.format || 'unknown').toLowerCase();
  normalized.family = String(normalized.family || fallback.family || 'unknown').toLowerCase();
  normalized.ocr_mode = String(normalized.ocr_mode || fallback.ocr_mode || 'none').toLowerCase();
  return normalized;
}

function _cloneSerializable(value: any, fallback: any = null): any {
  try {
    return JSON.parse(JSON.stringify(value));
  } catch (_) {
    return fallback;
  }
}

import { _clearActiveFileState, _destroyActiveEditorForClosedFile, _removeOpenTabAfterFileDeleted, _renderTabs, _setSwitchToTabImpl, _switchToTabImpl } from './state-tab-lifecycle';
export * from './state-tab-lifecycle';


export function _registerSwitchToTab(fn: (path: string) => Promise<void>): void {
  _setSwitchToTabImpl(fn);
}

export async function _switchToTab(path: string): Promise<void> {
  if (_switchToTabImpl) return _switchToTabImpl(path);
  // Fallback: basic tab-switching without editor mounting
  state.activeTabPath = path;
  const tab = state.openTabs.find((item) => item.path === path);
  if (tab) {
    state.fileId = tab.fileId || null;
    state.sourceSha256 = tab.sourceSha256 || '';
    state.fileType = tab.fileType;
    state.fileName = tab.name;
    state.filePath = tab.filePath || tab.path || null;
    state.wsSourcePath = tab.path;
    state.capabilityProfile = tab.capabilityProfile || null;
  }
  _renderTabs();
}import { _syncWorkspaceSurfaces } from './state-editor-layout';
export * from './state-editor-layout';


// ── Toggle Workspace / Loading ──

export function toggleWorkspace(show: boolean): void {
  const dropZone = document.getElementById('wa-drop-zone');
  if (dropZone) dropZone.classList.toggle('hidden', show);
  _syncWorkspaceSurfaces();
  document.dispatchEvent(new CustomEvent('koto:workspace-file-change'));
}

export function setLoading(show: boolean, msg?: string): void {
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

// ── Workspace Root & Tree ──

export function _renderWorkspaceRoot(): void {
  const rootLabel = document.getElementById('wa-ws-root-label');
  if (rootLabel) {
    rootLabel.textContent = (state._workspaceName || 'workspace').toUpperCase();
    rootLabel.title = state._workspacePath || '';
  }
  const panelTitle = document.getElementById('wa-panel-title-ws');
  if (panelTitle) panelTitle.textContent = state._workspaceName || 'workspace';
}

export function _renderWorkspaceTree(): void {
  // Replaced by _renderBrowserTree in full filesystem mode.
}

// ── Load Workspace Files ──

export async function loadWorkspaceFiles(): Promise<void> {
  try {
    const res = await fetch('/api/v1/workspace/current_dir');
    if (res.ok) {
      const data = await res.json();
      state._workspaceName = data.name || 'workspace';
      state._workspacePath = data.path || '';
      _renderWorkspaceRoot();
    } else {
      throw new Error(String(res.status));
    }
  } catch (error) {
    console.error('Fetch dir error', error);
    showToast('获取工作区目录网络异常...', 'error');
  }
  // _softRefreshBrowser() is in fs-tree module — call after modules load
  if (typeof getFeatureRegistry()?._softRefreshBrowser === 'function') {
    await getFeatureRegistry()._softRefreshBrowser();
  }
}import { loadRecentFiles } from './state-recent-files';
export * from './state-recent-files';


// ── My Workspace ──

const _MYWS_KEY = 'wa_my_workspace_v1';

export function _loadMyWorkspace(): MyWorkspaceFile[] {
  try {
    return JSON.parse(localStorage.getItem(_MYWS_KEY) || '[]');
  } catch (_) {
    return [];
  }
}

export function _saveMyWorkspace(list: MyWorkspaceFile[]): void {
  localStorage.setItem(_MYWS_KEY, JSON.stringify(list));
}

export function _toggleMyWorkspaceSection(): void {
  const open = state.sectionOpen.myworkspace !== false;
  const list = document.getElementById('wa-myws-list');
  const empty = document.getElementById('wa-myws-empty');
  const arrow = document.getElementById('wa-myws-arrow');
  if (arrow) arrow.classList.toggle('open', open);
  if (list) list.style.display = open ? '' : 'none';
  if (empty) empty.style.display = open && !_loadMyWorkspace().length ? '' : 'none';
}

export function _renderMyWorkspace(): void {
  const list = document.getElementById('wa-myws-list');
  const empty = document.getElementById('wa-myws-empty');
  const badge = document.getElementById('wa-myws-badge');
  if (!list) return;
  const files = _loadMyWorkspace();
  if (badge) badge.textContent = files.length ? String(files.length) : '';
  const isOpen = state.sectionOpen.myworkspace !== false;
  if (!isOpen) {
    list.style.display = 'none';
    if (empty) empty.style.display = 'none';
    return;
  }
  if (!files.length) {
    list.innerHTML = '';
    list.style.display = 'none';
    if (empty) empty.style.display = '';
    return;
  }
  if (empty) empty.style.display = 'none';
  list.style.display = '';
  list.innerHTML = files
    .map((file) => {
      const pathEsc = _escHtml(file.path);
      const nameEsc = _escHtml(file.name);
      const icon = _fileIcon(file.ext || file.name.split('.').pop() || '');
      const active = state.activeTabPath === file.path ? ' active' : '';
      return (
        `<div class="wa-myws-item${active}" data-path="${pathEsc}" title="${pathEsc}"` +
        ` data-wa-workspace-row-action="open" draggable="true">` +
        `${icon}<span class="wa-file-label">${nameEsc}</span>` +
        `<button type="button" class="wa-myws-remove" data-wa-workspace-row-action="remove-my" title="从工作区移除">×</button>` +
        `</div>`
      );
    })
    .join('');
  list.querySelectorAll('.wa-myws-item[draggable]').forEach((element) => {
    (element as HTMLElement).addEventListener('dragstart', (event: DragEvent) => {
      const el = element as HTMLElement;
      const path = el.dataset.path;
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = 'copyMove';
        event.dataTransfer.setData('application/wa-file-path', path || '');
        event.dataTransfer.setData('text/plain', path || '');
      }
      el.classList.add('dragging');
      document.body.classList.add('wa-file-dragging');
    });
    (element as HTMLElement).addEventListener('dragend', () => {
      element.classList.remove('dragging');
      document.body.classList.remove('wa-file-dragging');
    });
  });
}

// ── Temp Workspace ──

export function _toggleTempWorkspaceSection(): void {
  const open = state.sectionOpen.tmpworkspace !== false;
  const list = document.getElementById('wa-tmpws-list');
  const empty = document.getElementById('wa-tmpws-empty');
  const arrow = document.getElementById('wa-tmpws-arrow');
  if (arrow) arrow.classList.toggle('open', open);
  if (list) list.style.display = open ? '' : 'none';
  if (empty) empty.style.display = open && !state._tempWorkspace.length ? '' : 'none';
}

export function _renderTempWorkspace(): void {
  const list = document.getElementById('wa-tmpws-list');
  const empty = document.getElementById('wa-tmpws-empty');
  const badge = document.getElementById('wa-tmpws-badge');
  if (!list) return;
  const files = state._tempWorkspace;
  if (badge) badge.textContent = files.length ? String(files.length) : '';
  const isOpen = state.sectionOpen.tmpworkspace !== false;
  if (!isOpen) {
    list.style.display = 'none';
    if (empty) empty.style.display = 'none';
    return;
  }
  if (!files.length) {
    list.innerHTML = '';
    list.style.display = 'none';
    if (empty) empty.style.display = '';
    return;
  }
  if (empty) empty.style.display = 'none';
  list.style.display = '';
  list.innerHTML = files
    .map((file: any) => {
      const pathEsc = _escHtml(file.path);
      const nameEsc = _escHtml(file.name);
      const icon = _fileIcon(file.ext || file.name.split('.').pop() || '');
      const active = state.activeTabPath === file.path ? ' active' : '';
      return (
        `<div class="wa-myws-item${active}" data-path="${pathEsc}" title="${pathEsc}"` +
        ` data-wa-workspace-row-action="open" draggable="true">` +
        `${icon}<span class="wa-file-label">${nameEsc}</span>` +
        `<button type="button" class="wa-myws-remove" data-wa-workspace-row-action="remove-temp" title="从临时工作区移除">×</button>` +
        `</div>`
      );
    })
    .join('');
  list.querySelectorAll('.wa-myws-item[draggable]').forEach((element) => {
    (element as HTMLElement).addEventListener('dragstart', (event: DragEvent) => {
      const el = element as HTMLElement;
      const path = el.dataset.path;
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = 'copyMove';
        event.dataTransfer.setData('application/wa-file-path', path || '');
        event.dataTransfer.setData('text/plain', path || '');
      }
      el.classList.add('dragging');
      document.body.classList.add('wa-file-dragging');
    });
    (element as HTMLElement).addEventListener('dragend', () => {
      element.classList.remove('dragging');
      document.body.classList.remove('wa-file-dragging');
    });
  });
}

let _workspaceRowActionDelegationInstalled = false;

function _installWorkspaceRowActionDelegation(): void {
  if (_workspaceRowActionDelegationInstalled) return;
  _workspaceRowActionDelegationInstalled = true;
  document.addEventListener('click', (event) => {
    const target = event.target as HTMLElement | null;
    const tabControl = target?.closest<HTMLElement>('[data-wa-tab-action]');
    if (tabControl) {
      const tab = tabControl.closest<HTMLElement>('.wa-tab');
      const path = String(tab?.dataset.path || '').trim();
      const action = String(tabControl.dataset.waTabAction || '');
      if (path) {
        event.preventDefault();
        event.stopPropagation();
        const features = getFeatureRegistry();
        if (action === 'open') void features._tabClick?.(path);
        if (action === 'close') void features._closeTab?.(path);
      }
      return;
    }
    const control = target && target.closest ? target.closest<HTMLElement>('[data-wa-workspace-row-action]') : null;
    if (!control) return;
    const row = control.closest<HTMLElement>('.wa-myws-item');
    const path = String(row?.dataset.path || '').trim();
    const action = String(control.dataset.waWorkspaceRowAction || '');
    if (!path) return;
    event.preventDefault();
    event.stopPropagation();
    const workspaceApi = getFeatureRegistry();
    if (action === 'open' && typeof workspaceApi.openBrowserFile === 'function') {
      void workspaceApi.openBrowserFile(path, true);
    } else if (action === 'remove-my' && typeof workspaceApi.removeFromMyWorkspace === 'function') {
      workspaceApi.removeFromMyWorkspace(path);
    } else if (action === 'remove-temp' && typeof workspaceApi.removeFromTempWorkspace === 'function') {
      workspaceApi.removeFromTempWorkspace(path);
    }
  }, true);
}

_installWorkspaceRowActionDelegation();

// ── Cross-module status bridge ──

export function _updateStatusBar(): void {
  const update = getFeatureRegistry()._updateStatusBar;
  if (typeof update === 'function') update();
}

// ── Register with getFeatureRegistry() ──

const wa = getFeatureRegistry();

function _syncMobileFilesA11y(): void {
  const left = document.getElementById('wa-left') as HTMLElement | null;
  if (!left) return;
  const isOpen = document.body.classList.contains('wa-mobile-files-open');
  const hidden = !isOpen;
  left.setAttribute('aria-hidden', hidden ? 'true' : 'false');
  (left as any).inert = hidden;
  left.toggleAttribute('inert', hidden);
}

wa.toggleMobileFiles = (force?: boolean) => {
  const isOpen = typeof force === 'boolean'
    ? force
    : !document.body.classList.contains('wa-mobile-files-open');
  document.body.classList.toggle('wa-mobile-files-open', isOpen);
  document.querySelectorAll('[aria-controls="wa-left"]').forEach((btn) => {
    btn.setAttribute('aria-expanded', String(isOpen));
  });
  _syncMobileFilesA11y();
};

wa.closeMobileFiles = () => wa.toggleMobileFiles(false);

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    _syncWorkspaceSurfaces();
    _syncMobileFilesA11y();
  });
} else {
  _syncWorkspaceSurfaces();
  _syncMobileFilesA11y();
}
window.addEventListener('resize', _syncMobileFilesA11y);
window.addEventListener('koto-ui-zoom-change', _syncMobileFilesA11y);
getFeatureRegistry()._WA_RUNTIME_SESSION_ID = _WA_RUNTIME_SESSION_ID;
getFeatureRegistry()._fsHandleMap = _fsHandleMap;
getFeatureRegistry()._normalizeWorkspaceModelMode = _normalizeWorkspaceModelMode;
getFeatureRegistry()._cloneSerializable = _cloneSerializable;

wa._renderTabs = _renderTabs;
wa._removeOpenTabAfterFileDeleted = _removeOpenTabAfterFileDeleted;
wa._tabClick = async (path: string) => {
  await _switchToTab(path);
};
wa._closeTab = async (path: string) => {
  const idx = state.openTabs.findIndex((tab) => tab.path === path);
  if (idx < 0) return;
  const tab = state.openTabs[idx];

  const wa = getFeatureRegistry() || {};
  const isUnsaved = typeof wa.isTabActuallyUnsaved === 'function'
    ? wa.isTabActuallyUnsaved(tab)
    : !!tab.modified;
  if (isUnsaved) {
    if (!confirm(`"${tab.name}" 有未保存的修改，关闭后将丢失。\n是否继续关闭？`)) return;
  } else if (tab.modified) {
    tab.modified = false;
    if (typeof wa._notifyPyModified === 'function') {
      try { wa._notifyPyModified(tab, false); } catch (e) { console.warn("[Koto]", e) }
    }
  }

  const isActive = tab.path === state.activeTabPath;

  if (isActive) {
    _destroyActiveEditorForClosedFile();
    _clearActiveFileState();
  }

  state.openTabs.splice(idx, 1);

  if (isActive) {
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
};

wa.refreshFiles = async () => {
  const btn = document.querySelector('.wa-icon-btn');
  if (btn) {
    btn.classList.add('spinning');
    setTimeout(() => btn.classList.remove('spinning'), 700);
  }
  if (typeof wa.loadFileBrowser === 'function') await wa.loadFileBrowser();
  else await loadWorkspaceFiles();
  if (typeof wa.refreshRecent === 'function') await wa.refreshRecent();
};

wa.filterFiles = (query: string) => {
  state.searchQuery = query.trim();
  const clear = document.getElementById('wa-search-clear');
  if (clear) clear.style.display = state.searchQuery ? '' : 'none';
  if (!state.searchQuery) {
    state._searchActive = false;
    if (typeof wa._renderBrowserTree === 'function') wa._renderBrowserTree();
  } else {
    if (typeof wa._doSearch === 'function') wa._doSearch();
  }
};

wa.setSearchFilter = (category: string) => {
  state._searchFilter = category;
  document.querySelectorAll('.wa-filter-chip').forEach((element: any) => {
    element.classList.toggle('active', element.dataset.cat === category);
  });
  if (state.searchQuery && typeof wa._doSearch === 'function') wa._doSearch();
  else {
    state._searchActive = false;
    if (typeof wa._renderBrowserTree === 'function') wa._renderBrowserTree();
  }
};

wa.clearSearch = () => {
  const input = document.getElementById('wa-search') as HTMLInputElement | null;
  if (input) input.value = '';
  if (typeof getFeatureRegistry() !== 'undefined' && getFeatureRegistry().filterFiles) getFeatureRegistry().filterFiles('');
};

function _syncSectionToggleState(id: string, open: boolean): void {
  const control = document.querySelector(`[data-wa-section-toggle="${CSS.escape(id)}"]`);
  if (control) control.setAttribute('aria-expanded', String(open));
}

wa.toggleSection = (id: string) => {
  state.sectionOpen[id] = !state.sectionOpen[id];
  _syncSectionToggleState(id, state.sectionOpen[id] !== false);
  localStorage.setItem('wa_sections', JSON.stringify(state.sectionOpen));
  if (id === 'myworkspace') {
    _toggleMyWorkspaceSection();
  } else if (id === 'tmpworkspace') {
    _toggleTempWorkspaceSection();
  } else if (id === 'workspace') {
    const open = state.sectionOpen.workspace !== false;
    const list = document.getElementById('wa-files-list');
    const arrow = document.getElementById('wa-ws-arrow');
    if (arrow) arrow.classList.toggle('open', open);
    if (list) list.style.display = open ? '' : 'none';
    if (open && typeof wa._renderBrowserTree === 'function') wa._renderBrowserTree();
  } else {
    _renderWorkspaceTree();
  }
};

wa.refreshRecent = () => loadRecentFiles();

wa.toggleRecentSection = () => {
  state._recentOpen = !state._recentOpen;
  _syncSectionToggleState('recent', state._recentOpen);
  const list = document.getElementById('wa-recent-list');
  const arrow = document.getElementById('wa-recent-arrow');
  if (list) list.style.display = state._recentOpen ? '' : 'none';
  if (arrow) arrow.classList.toggle('open', state._recentOpen);
};

getFeatureRegistry().loadRecentFiles = loadRecentFiles;

wa.addToMyWorkspace = (path: string) => {
  let targetPath = path;
  if (!targetPath) targetPath = state.activeTabPath || state.wsSourcePath || '';
  if (!targetPath) {
    showToast('请先打开一个文件', 'info');
    return;
  }
  const name = targetPath.split(/[\\/]/).pop() || targetPath;
  const ext = name.includes('.') ? name.split('.').pop()!.toLowerCase() : '';
  const files = _loadMyWorkspace();
  if (files.some((file) => file.path === targetPath)) {
    showToast(`"${name}" 已在工作区中`, 'info');
    return;
  }
  files.push({ path: targetPath, name, ext, addedAt: Date.now() });
  _saveMyWorkspace(files);
  _renderMyWorkspace();
  showToast(`"${name}" 已加入工作区`, 'success');
};

wa.removeFromMyWorkspace = (path: string) => {
  const files = _loadMyWorkspace().filter((file) => file.path !== path);
  _saveMyWorkspace(files);
  _renderMyWorkspace();
};

wa.addToTempWorkspace = (path: string) => {
  let targetPath = path;
  if (!targetPath) targetPath = state.activeTabPath || state.wsSourcePath || '';
  if (!targetPath) {
    showToast('请先打开一个文件', 'info');
    return;
  }
  const name = targetPath.split(/[\\/]/).pop() || targetPath;
  const ext = name.includes('.') ? name.split('.').pop()!.toLowerCase() : '';
  if (state._tempWorkspace.some((file: any) => file.path === targetPath)) {
    showToast(`"${name}" 已在临时工作区中`, 'info');
    return;
  }
  state._tempWorkspace.push({ path: targetPath, name, ext, addedAt: Date.now() });
  _renderTempWorkspace();
  if (typeof wa.openBrowserFile === 'function') wa.openBrowserFile(targetPath, true);
  showToast(`"${name}" 已加入临时工作区`, 'success');
};

wa.removeFromTempWorkspace = (path: string) => {
  state._tempWorkspace = state._tempWorkspace.filter((file: any) => file.path !== path);
  _renderTempWorkspace();
};

wa.clearTempWorkspace = () => {
  if (!state._tempWorkspace.length) return;
  if (!confirm('确认清空临时工作区？已打开的标签页不受影响。')) return;
  state._tempWorkspace = [];
  _renderTempWorkspace();
  showToast('临时工作区已清空', 'info');
};
