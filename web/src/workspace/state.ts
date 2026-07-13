/**
 * Global State + Tab Management + Workspace Tree + Recent Files + My/Temp Workspace.
 * Workspace state.
 */

import { _fileIcon, _escHtml, showToast, _FOLDER_SVG, _FOLDER_OPEN_SVG } from './infrastructure';
import { logger } from '../shared/logger';

// ── Interfaces ──

export interface TabInfo {
  path: string;
  name: string;
  ext: string;
  fileType: string;
  fileId?: string | null;
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
  editor?: unknown;
  [key: string]: unknown;
}

export interface WorkspaceState {
  fileId: string | null;
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
  _modelChoicePendingMode?: string;
  _modelChoiceUpdatedAt?: number;
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

function _normalizeWorkspaceModelMode(value: string, fallback: string = 'deepseek'): string {
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
      const pathEsc = tab.path.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
      const info = _tabDisplayInfo(tab);
      const extAttr = _escHtml(info.extAttr || '');
      const nameEsc = _escHtml(tab.name || '');
      const titleEsc = _escHtml(info.title || tab.name || '');
      return (
        `<div class="wa-tab${active}${modified}" data-path="${tab.path.replace(/"/g, '&quot;')}" data-ext="${extAttr}"` +
        ` onclick="WA._tabClick('${pathEsc}')" title="${titleEsc}">` +
        `<span class="tab-icon">${_fileIcon(tab.ext)}</span>` +
        `<span class="tab-main">` +
        `<span class="tab-label">${nameEsc}</span>` +
        `</span>` +
        `<span class="tab-dirty"></span>` +
        `<button class="tab-close" onclick="event.stopPropagation();WA._closeTab('${pathEsc}')" title="关闭">×</button>` +
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

let _switchToTabImpl: ((path: string) => Promise<void>) | null = null;

export function _registerSwitchToTab(fn: (path: string) => Promise<void>): void {
  _switchToTabImpl = fn;
}

export async function _switchToTab(path: string): Promise<void> {
  if (_switchToTabImpl) return _switchToTabImpl(path);
  // Fallback: basic tab-switching without editor mounting
  state.activeTabPath = path;
  const tab = state.openTabs.find((item) => item.path === path);
  if (tab) {
    state.fileId = tab.fileId || null;
    state.fileType = tab.fileType;
    state.fileName = tab.name;
    state.filePath = tab.filePath || tab.path || null;
    state.wsSourcePath = tab.path;
    state.capabilityProfile = tab.capabilityProfile || null;
  }
  _renderTabs();
}

// ── Editor Layout Helpers ──

function _editorLayoutContainerId(fileType: string): string | null {
  return fileType === 'xlsx'
    ? 'wa-xlsx-editor'
    : fileType === 'pptx'
      ? 'wa-pptx-editor'
      : fileType === 'pdf'
        ? 'wa-pdf-editor'
        : null;
}

const _WORKSPACE_SURFACE_IDS = [
  'wa-drop-zone',
  'wa-docx-editor',
  'wa-xlsx-editor',
  'wa-pptx-editor',
  'wa-pdf-editor',
  'wa-pdf-viewer',
  'wa-image-viewer',
  'wa-text-editor',
];

function _setSurfaceA11y(el: HTMLElement, isActive: boolean): void {
  el.setAttribute('aria-hidden', isActive ? 'false' : 'true');
  (el as any).inert = !isActive;
  el.toggleAttribute('inert', !isActive);
}

export function _syncWorkspaceSurfaces(): void {
  _WORKSPACE_SURFACE_IDS.forEach((id) => {
    const el = document.getElementById(id) as HTMLElement | null;
    if (!el) return;
    const isDropZone = id === 'wa-drop-zone';
    const isActive = isDropZone ? !el.classList.contains('hidden') : el.classList.contains('active');
    _setSurfaceA11y(el, isActive);
  });
}

export function _primeEditorLayout(fileType: string): void {
  const containerId = _editorLayoutContainerId(fileType);
  if (!containerId) return;
  const el = document.getElementById(containerId);
  if (el) el.classList.add('active');
  if (fileType === 'pdf') {
    document.getElementById('wa-pdf-viewer')?.classList.add('active');
  }
  _syncWorkspaceSurfaces();
}

export function _waitForEditorLayout(fileType: string, timeoutMs: number = 800): Promise<void> {
  const containerId = _editorLayoutContainerId(fileType);
  if (!containerId) return Promise.resolve();
  const isReady = () => {
    const el = document.getElementById(containerId);
    return !!(el && el.offsetWidth > 0 && el.offsetHeight > 0);
  };
  if (isReady()) return Promise.resolve();
  return new Promise((resolve) => {
    const deadline = Date.now() + timeoutMs;
    function check() {
      const el = document.getElementById(containerId!);
      if (el && el.offsetWidth > 0 && el.offsetHeight > 0) {
        resolve();
        return;
      }
      if (Date.now() >= deadline) {
        console.warn(
          '[WA] _waitForEditorLayout timeout for',
          containerId,
          'offsetW:',
          el ? el.offsetWidth : 'null',
          'offsetH:',
          el ? el.offsetHeight : 'null'
        );
        resolve();
        return;
      }
      requestAnimationFrame(check);
    }
    requestAnimationFrame(check);
  });
}

// ── Toggle Workspace / Loading ──

export function toggleWorkspace(show: boolean): void {
  const dropZone = document.getElementById('wa-drop-zone');
  if (dropZone) dropZone.classList.toggle('hidden', show);
  _syncWorkspaceSurfaces();
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
  if (typeof (window as any).WA?._softRefreshBrowser === 'function') {
    await (window as any).WA._softRefreshBrowser();
  }
}

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
  return 'draggable="true" ondragstart="WA._browserFileDragStart(event,this)" ondragend="WA._browserFileDragEnd(event,this)"';
}

function _recentFileOpenHitDragAttrs(): string {
  return 'draggable="true" ondragstart="WA._browserFileDragStart(event,this.closest(\'.wa-file-item\'))" ondragend="WA._browserFileDragEnd(event,this.closest(\'.wa-file-item\'))"';
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

  const userRecent = _mergeRecentFiles(localRecent, apiRecent);
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
      + ` onmousedown="WA._browserFileRowMouseDown(event,this)"`
      + ` onclick="WA.openRecentFile(${JSON.stringify(file.path || '')})"`
      + ` oncontextmenu="event.preventDefault();event.stopPropagation();WA._showBrowserCtx(event,this)">`
      + `<button type="button" class="wa-file-open-hit" ${_recentFileOpenHitDragAttrs()} aria-label="打开 ${_escHtml(name)}" onclick="event.preventDefault();event.stopPropagation();WA.openRecentFile(this.closest('.wa-file-item').dataset.path)"></button>`
      + `<span class="wa-recent-indent"></span>${icon}`
      + `<span class="wa-file-label">${_escHtml(name)}</span>`
      + `<span class="wa-recent-date">${date}${size}</span>`
      + `</div>`;
  }).join('');
}

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
      const pathJs = file.path.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
      return (
        `<div class="wa-myws-item${active}" data-path="${pathEsc}" title="${pathEsc}"` +
        ` onclick="WA.openBrowserFile('${pathJs}', true)" draggable="true">` +
        `${icon}<span class="wa-file-label">${nameEsc}</span>` +
        `<button class="wa-myws-remove" onclick="event.stopPropagation();WA.removeFromMyWorkspace('${pathJs}')" title="从工作区移除">×</button>` +
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
      const pathJs = file.path.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
      return (
        `<div class="wa-myws-item${active}" data-path="${pathEsc}" title="${pathEsc}"` +
        ` onclick="WA.openBrowserFile('${pathJs}', true)" draggable="true">` +
        `${icon}<span class="wa-file-label">${nameEsc}</span>` +
        `<button class="wa-myws-remove" onclick="event.stopPropagation();WA.removeFromTempWorkspace('${pathJs}')" title="从临时工作区移除">×</button>` +
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

// ── Placeholder helpers (implemented in other modules) ──

function _updateStatusBar(): void {
  /* placeholder - actual impl in another section */
}
function _updateSubjectBar(_name?: string | null, _type?: string | null): void {
  /* placeholder */
}
function _syncReviewStateForActiveFile(): Promise<void> {
  return Promise.resolve();
}
function _updateContextBar(_ctx?: any): void {
  /* placeholder */
}

// ── Register with window.WA ──

const wa = (window as any).WA || {};
(window as any).WA = wa;

function _syncMobileFilesA11y(): void {
  const left = document.getElementById('wa-left') as HTMLElement | null;
  if (!left) return;
  const isNarrow = typeof window.matchMedia === 'function'
    && window.matchMedia('(max-width: 760px)').matches;
  const isOpen = document.body.classList.contains('wa-mobile-files-open');
  const hidden = isNarrow && !isOpen;
  left.setAttribute('aria-hidden', hidden ? 'true' : 'false');
  (left as any).inert = hidden;
  left.toggleAttribute('inert', hidden);
}

wa.toggleMobileFiles = (force?: boolean) => {
  const isOpen = typeof force === 'boolean'
    ? force
    : !document.body.classList.contains('wa-mobile-files-open');
  document.body.classList.toggle('wa-mobile-files-open', isOpen);
  const btn = document.getElementById('wa-mobile-files-toggle');
  if (btn) btn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
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
(window as any).state = state;
(window as any)._WA_RUNTIME_SESSION_ID = _WA_RUNTIME_SESSION_ID;
(window as any)._fsHandleMap = _fsHandleMap;
(window as any)._normalizeWorkspaceModelMode = _normalizeWorkspaceModelMode;
(window as any)._cloneSerializable = _cloneSerializable;

wa._renderTabs = _renderTabs;
wa._removeOpenTabAfterFileDeleted = _removeOpenTabAfterFileDeleted;
wa._tabClick = async (path: string) => {
  await _switchToTab(path);
};
wa._closeTab = async (path: string) => {
  const idx = state.openTabs.findIndex((tab) => tab.path === path);
  if (idx < 0) return;
  const tab = state.openTabs[idx];

  const wa = (window as any).WA || {};
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
  if (typeof (window as any).WA !== 'undefined' && (window as any).WA.filterFiles) (window as any).WA.filterFiles('');
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

(window as any).loadRecentFiles = loadRecentFiles;

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
