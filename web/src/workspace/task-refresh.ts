/**
 * File task refresh controller — manages file refresh entries
 * and triggers reloads after AI tasks complete.
 */

import { publishWorkspaceApi } from '../shared/workspace-api';

interface TaskCard {
  _taskUiState?: TaskUiState;
  _pendingFileRefreshes?: Set<string>;
  _fileRefreshPromise?: Promise<{ ok: boolean; refreshed: boolean; refreshedCount?: number }> | null;
  _fileRefreshOptions?: RefreshOptions;
  [key: string]: any;
}

interface TaskUiState {
  fileRefreshEntries?: Map<string, RefreshEntry>;
}

interface RefreshEntry {
  key: string;
  path: string;
  name?: string;
  status: string;
  stepId?: string;
  stepTitle?: string;
  supported?: boolean;
  error?: string;
}

interface RefreshPayload {
  path?: string;
  file_path?: string;
  output_path?: string;
  target_path?: string;
  name?: string;
  file_name?: string;
  supported?: boolean;
  refresh_supported?: boolean;
}

interface QueueOptions {
  stepId?: string;
  stepTitle?: string;
}

interface RefreshOptions {
  onRefreshed?: (result: any, entry: RefreshEntry) => void;
  showRefreshingStatus?: boolean;
  restoreFinalStatus?: boolean;
  errorLog?: string;
}

interface RefreshControllerDeps {
  ensureTaskUiState?: (card: TaskCard) => TaskUiState;
  basename?: (path: string) => string;
  normalizePath?: (path: string) => string;
  setStatus?: (card: TaskCard, status: string) => void;
  renderRunSummary?: (card: TaskCard, payload: any) => void;
  logPrefix?: string;
}

interface RefreshResult {
  ok: boolean;
  refreshed: boolean;
  refreshedCount?: number;
}

export function createFileTaskRefreshController(options: RefreshControllerDeps = {}) {
  const ensureTaskUiState = typeof options.ensureTaskUiState === 'function'
    ? options.ensureTaskUiState
    : (card: TaskCard): TaskUiState => {
        card._taskUiState = card._taskUiState || { fileRefreshEntries: new Map() };
        return card._taskUiState;
      };
  const basename = typeof options.basename === 'function'
    ? options.basename
    : (path: string) => String(path || '').replace(/\\/g, '/').split('/').filter(Boolean).pop() || String(path || '');
  const normalizePath = typeof options.normalizePath === 'function'
    ? options.normalizePath
    : (path: string) => path;

  function refreshEntryKey(path: string): string {
    return String(normalizePath(path) || path || '').trim().replace(/\\/g, '/').toLowerCase();
  }

  function ensureRefreshState(card: TaskCard): TaskUiState {
    const state = ensureTaskUiState(card);
    if (!state.fileRefreshEntries || typeof state.fileRefreshEntries.set !== 'function') {
      state.fileRefreshEntries = new Map();
    }
    if (!card._pendingFileRefreshes) card._pendingFileRefreshes = new Set();
    return state;
  }

  function upsertEntry(card: TaskCard, item: RefreshEntry & Partial<RefreshPayload>): RefreshEntry | null {
    const state = ensureRefreshState(card);
    const key = refreshEntryKey(item && (item.path as string));
    if (!key) return null;
    const previous = state.fileRefreshEntries?.get(key) || {} as RefreshEntry;
    const previousStatus = String(previous.status || '');
    const nextStatus = String(item.status || previousStatus || 'pending');
    const status = (
      nextStatus === 'pending'
      && ['pending', 'refreshing', 'reloaded'].includes(previousStatus)
    ) ? previousStatus : nextStatus;
    const entry: RefreshEntry = Object.assign({}, previous, item, { key, status });
    state.fileRefreshEntries?.set(key, entry);
    return entry;
  }

  function queue(card: TaskCard, payload: RefreshPayload, queueOptions: QueueOptions = {}): RefreshEntry | null {
    if (!card || !payload) return null;
    const rawPath = payload.path || payload.file_path || payload.output_path || payload.target_path;
    const path = normalizePath(rawPath || '') || rawPath;
    if (!path) return null;
    const supported = payload.supported !== false && payload.refresh_supported !== false;
    const entry = upsertEntry(card, {
      path,
      name: payload.name || payload.file_name || basename(path),
      status: supported ? 'pending' : 'unsupported',
      key: '',
      stepId: queueOptions.stepId || '',
      stepTitle: queueOptions.stepTitle || '',
      supported,
    });
    if (entry && supported) card._pendingFileRefreshes?.add(entry.key);
    return entry;
  }

  async function flush(card: TaskCard): Promise<RefreshResult> {
    if (!card) return { ok: true, refreshed: false };
    if (!((card._pendingFileRefreshes && card._pendingFileRefreshes.size) || card._fileRefreshPromise)) {
      return { ok: true, refreshed: false };
    }
    if (card._fileRefreshPromise) return card._fileRefreshPromise;
    const flushOptions = card._fileRefreshOptions || {};
    card._fileRefreshPromise = (async () => {
      const state = ensureRefreshState(card);
      const keys = Array.from(card._pendingFileRefreshes || []);
      if (card._pendingFileRefreshes) card._pendingFileRefreshes.clear();
      let allOk = true;
      let refreshedCount = 0;
      for (const key of keys) {
        const current = state.fileRefreshEntries?.get(key);
        if (!current || current.supported === false) continue;
        upsertEntry(card, Object.assign({}, current, { status: 'refreshing' }));
        try {
          if (!(window as any).WA || typeof (window as any).WA.reloadFileByPath !== 'function') {
            throw new Error('文件刷新器未加载');
          }
          const refreshed = await (window as any).WA.reloadFileByPath(current.path, true);
          upsertEntry(card, Object.assign({}, current, { status: 'reloaded' }));
          refreshedCount += 1;
          if (typeof flushOptions.onRefreshed === 'function') flushOptions.onRefreshed(refreshed, current);
        } catch (err: any) {
          allOk = false;
          upsertEntry(card, Object.assign({}, current, {
            status: 'failed',
            error: err && err.message ? err.message : String(err || '刷新失败'),
          }));
        }
      }
      return { ok: allOk, refreshed: refreshedCount > 0, refreshedCount };
    })();
    try {
      return await card._fileRefreshPromise;
    } finally {
      card._fileRefreshPromise = null;
    }
  }

  function trigger(card: TaskCard, triggerOptions: RefreshOptions = {}): void {
    const errorLog = triggerOptions.errorLog || `${options.logPrefix || '[FileTask]'} refresh failed:`;
    if (card) card._fileRefreshOptions = triggerOptions;
    void flush(card).catch((err) => {
      console.warn(errorLog, err);
    });
  }

  async function finalize(card: TaskCard, payload: any, finalizeOptions: RefreshOptions = {}): Promise<boolean> {
    if (card) card._fileRefreshOptions = finalizeOptions;
    const refreshResult = await flush(card);
    const refreshOk = refreshResult ? refreshResult.ok : false;
    const didRefresh = refreshResult ? refreshResult.refreshed : false;
    if (finalizeOptions.showRefreshingStatus && didRefresh && typeof options.setStatus === 'function') {
      options.setStatus(card, refreshOk ? '已刷新文件' : '文件刷新失败');
    }
    if (finalizeOptions.restoreFinalStatus && typeof options.renderRunSummary === 'function' && payload) {
      options.renderRunSummary(card, payload);
    }
    return refreshOk;
  }

  return {
    finalize,
    flush,
    queue,
    refreshEntryKey,
    trigger,
  };
}

publishWorkspaceApi({ createFileTaskRefreshController });
