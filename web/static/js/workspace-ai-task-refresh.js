(function () {
  'use strict';

  window.WA = window.WA || {};

  window.WA.createFileTaskRefreshController = function createFileTaskRefreshController(options = {}) {
    const ensureTaskUiState = typeof options.ensureTaskUiState === 'function'
      ? options.ensureTaskUiState
      : (card) => {
          card._taskUiState = card._taskUiState || { fileRefreshEntries: new Map() };
          return card._taskUiState;
        };
    const basename = typeof options.basename === 'function'
      ? options.basename
      : (path) => String(path || '').replace(/\\/g, '/').split('/').filter(Boolean).pop() || String(path || '');
    const normalizePath = typeof options.normalizePath === 'function'
      ? options.normalizePath
      : (path) => path;

    function refreshEntryKey(path) {
      return String(normalizePath(path) || path || '').trim().replace(/\\/g, '/').toLowerCase();
    }

    function ensureRefreshState(card) {
      const state = ensureTaskUiState(card);
      if (!state.fileRefreshEntries || typeof state.fileRefreshEntries.set !== 'function') {
        state.fileRefreshEntries = new Map();
      }
      if (!card._pendingFileRefreshes) card._pendingFileRefreshes = new Set();
      return state;
    }

    function upsertEntry(card, item) {
      const state = ensureRefreshState(card);
      const key = refreshEntryKey(item && item.path);
      if (!key) return null;
      const previous = state.fileRefreshEntries.get(key) || {};
      const previousStatus = String(previous.status || '');
      const nextStatus = String(item.status || previous.status || 'pending');
      const status = (
        nextStatus === 'pending'
        && ['pending', 'refreshing', 'reloaded'].includes(previousStatus)
      ) ? previousStatus : nextStatus;
      const entry = Object.assign({}, previous, item, { key, status });
      state.fileRefreshEntries.set(key, entry);
      return entry;
    }

    function queue(card, payload, queueOptions = {}) {
      if (!card || !payload) return null;
      const path = payload.path || payload.file_path || payload.output_path || payload.target_path;
      if (!path) return null;
      const supported = payload.supported !== false && payload.refresh_supported !== false;
      const entry = upsertEntry(card, {
        path,
        name: payload.name || payload.file_name || basename(path),
        status: supported ? 'pending' : 'unsupported',
        stepId: queueOptions.stepId || '',
        stepTitle: queueOptions.stepTitle || '',
        supported,
      });
      if (entry && supported) card._pendingFileRefreshes.add(entry.key);
      return entry;
    }

    async function flush(card) {
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
          const current = state.fileRefreshEntries.get(key);
          if (!current || current.supported === false) continue;
          upsertEntry(card, Object.assign({}, current, { status: 'refreshing' }));
          try {
            if (!window.WA || typeof window.WA.reloadFileByPath !== 'function') {
              throw new Error('文件刷新器未加载');
            }
            const refreshed = await window.WA.reloadFileByPath(current.path, true);
            upsertEntry(card, Object.assign({}, current, { status: 'reloaded' }));
            refreshedCount += 1;
            if (typeof flushOptions.onRefreshed === 'function') flushOptions.onRefreshed(refreshed, current);
          } catch (err) {
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

    function trigger(card, triggerOptions = {}) {
      const errorLog = triggerOptions.errorLog || `${options.logPrefix || '[FileTask]'} refresh failed:`;
      if (card) card._fileRefreshOptions = triggerOptions;
      void flush(card).catch((err) => {
        console.warn(errorLog, err);
      });
    }

    async function finalize(card, payload, finalizeOptions = {}) {
      if (card) card._fileRefreshOptions = finalizeOptions;
      const refreshResult = await flush(card);
      const refreshOk = refreshResult && typeof refreshResult === 'object'
        ? refreshResult.ok !== false
        : refreshResult !== false;
      const didRefresh = refreshResult && typeof refreshResult === 'object'
        ? refreshResult.refreshed === true
        : refreshResult !== false;
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
  };
})();
