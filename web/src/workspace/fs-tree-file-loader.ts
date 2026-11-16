// @ts-nocheck
/**
 * File System Browser — Tree rendering, search, browse, live polling, file loader.
 * Workspace file tree.
 */

import { _fileIcon, _escHtml, showToast, _FOLDER_OPEN_SVG, _FOLDER_PICK_SVG, _FOLDER_SVG } from './infrastructure';
import { state, _forgetRecentPath, _trackUserOpen, loadRecentFiles } from './state';
import { getFeatureRegistry } from '../shared/feature-registry';
import {
  entrySearchCategory as _entrySearchCategory,
  flattenWorkspaceListFiles as _flattenWorkspaceListFiles,
  formatFileSize as _formatSize,
  isSupportedExtension as _isSupportedExt,
  joinWorkspacePath as _joinWorkspacePath,
  mergeSearchResults as _mergeSearchResults,
} from './fs-tree-helpers';
import { _csrfFetch, _isAbsolutePath, _isInsideWorkspace, _safeJson, _workspaceRelativePath, workspaceApi } from './fs-tree';

// ── Workspace File Loader (fallback) ──

export function _createFallbackWorkspaceFileLoader(): any {
  type OpenRequest = {
    controller: AbortController;
    id: string;
    startedAt: number;
    source: 'workspace' | 'external' | 'upload';
    extension: string;
    sizeBytes?: number;
  };
  let activeOpenRequest: OpenRequest | null = null;

  const _switchToTab = async (path: string): Promise<void> => {
    if (typeof workspaceApi._tabClick === 'function') {
      await workspaceApi._tabClick(path);
    }
  };

  const setLoadingFn = (show: boolean, msg?: string, onCancel?: (() => void) | null): void => {
    const overlay = document.getElementById('wa-canvas-loading');
    if (show) {
      if (overlay) {
        const text = overlay.querySelector('.wa-loading-text');
        if (text) text.textContent = msg || '加载中...';
        let cancel = overlay.querySelector('.wa-loading-cancel') as HTMLButtonElement | null;
        if (!cancel) {
          cancel = document.createElement('button');
          cancel.type = 'button';
          cancel.className = 'wa-loading-cancel';
          cancel.textContent = '取消打开';
          overlay.appendChild(cancel);
        }
        cancel.hidden = typeof onCancel !== 'function';
        cancel.onclick = typeof onCancel === 'function' ? onCancel : null;
        overlay.style.display = 'flex';
      }
    } else {
      if (overlay) {
        overlay.style.display = 'none';
        const cancel = overlay.querySelector('.wa-loading-cancel') as HTMLButtonElement | null;
        if (cancel) {
          cancel.hidden = true;
          cancel.onclick = null;
        }
      }
    }
  };

  const _requestServerCancellation = (openRequest: OpenRequest): void => {
    void _csrfFetch('/api/v1/workspace/open_file/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ open_request_id: openRequest.id }),
      keepalive: true,
    }).catch(() => {});
  };

  const cancelOpenRequest = (openRequest: OpenRequest): void => {
    if (openRequest.controller.signal.aborted) return;
    _requestServerCancellation(openRequest);
    openRequest.controller.abort();
  };

  const beginOpenRequest = (
    message: string,
    source: OpenRequest['source'],
    path: string,
    sizeBytes?: number,
  ): OpenRequest => {
    if (activeOpenRequest) cancelOpenRequest(activeOpenRequest);
    const openRequest: OpenRequest = {
      controller: new AbortController(),
      id: typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`,
      startedAt: performance.now(),
      source,
      extension: String(path || '').split('.').pop()?.toLowerCase() || '',
      sizeBytes,
    };
    activeOpenRequest = openRequest;
    setLoadingFn(true, message, () => cancelOpenRequest(openRequest));
    return openRequest;
  };

  const recordOpenOutcome = (
    openRequest: OpenRequest,
    outcome: 'success' | 'cancelled' | 'error',
  ): void => {
    const metric = {
      requestId: openRequest.id,
      startedAt: openRequest.startedAt,
      finishedAt: performance.now(),
      source: openRequest.source,
      extension: openRequest.extension,
      sizeBytes: openRequest.sizeBytes,
      outcome,
    };
    const performanceMonitor = getFeatureRegistry().frontendPerformance;
    if (performanceMonitor && typeof performanceMonitor.recordFileOpen === 'function') {
      performanceMonitor.recordFileOpen(metric);
      return;
    }
    const loadObserver = getFeatureRegistry().loadFrontendObserver;
    if (typeof loadObserver !== 'function') return;
    void Promise.resolve(loadObserver()).then(() => {
      const loadedMonitor = getFeatureRegistry().frontendPerformance;
      if (loadedMonitor && typeof loadedMonitor.recordFileOpen === 'function') {
        loadedMonitor.recordFileOpen(metric);
      }
    }).catch(() => {});
  };

  const finishOpenRequest = (openRequest: OpenRequest): void => {
    if (activeOpenRequest !== openRequest) return;
    activeOpenRequest = null;
    setLoadingFn(false);
  };

  const handleOpenAbort = (error: any): boolean => {
    if (error?.name !== 'AbortError') return false;
    showToast('已取消打开文件', 'info', 1600);
    return true;
  };

  async function activateOpenTab(path: string): Promise<boolean> {
    const key = String(path || '').trim().replace(/\\/g, '/').toLowerCase();
    if (!key) return false;
    const openTab = state.openTabs.find((tab) =>
      String(tab.path || '').trim().replace(/\\/g, '/').toLowerCase() === key
    );
    if (!openTab) return false;
    await _switchToTab(openTab.path);
    return true;
  }

  async function openParsedFile(json: any, wsPath: string | null, _fsHandle: any = null): Promise<any> {
    const resolvedPath = wsPath || json.ws_source_path || json.source_path || json.temp_path || json.file_name;
    if (typeof workspaceApi._applyFileJson === 'function') {
      await workspaceApi._applyFileJson(json, resolvedPath, _fsHandle);
    }
    if (resolvedPath) _trackUserOpen(resolvedPath);
    return json;
  }

  async function openWorkspaceFile(path: string, supported: boolean = true, forceReload: boolean = false): Promise<any> {
    const requestPath = _workspaceRelativePath(path);
    if (!requestPath) return null;
    if (!supported) {
      showToast('此格式暂不支持在线编辑：' + _displayFileName(requestPath), 'info');
      return null;
    }
    if (!forceReload && await activateOpenTab(requestPath)) return null;
    const openRequest = beginOpenRequest('正在打开文件...', 'workspace', requestPath);
    let outcome: 'success' | 'cancelled' | 'error' = 'error';
    let missingWorkspaceFile = false;
    try {
      const res = await _csrfFetch('/api/v1/workspace/open_file_by_path', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: requestPath, open_request_id: openRequest.id }),
        signal: openRequest.controller.signal,
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
      const result = await openParsedFile(data, requestPath, null);
      outcome = 'success';
      return result;
    } catch (error: any) {
      if (handleOpenAbort(error)) {
        outcome = 'cancelled';
        return null;
      }
      if (!missingWorkspaceFile) console.error('[WA] openWorkspaceFile failed:', error);
      showToast(
        missingWorkspaceFile ? '文件已不存在，已从最近文件移除' : (error.message || '打开文件失败'),
        missingWorkspaceFile ? 'info' : 'error',
      );
      return null;
    } finally {
      recordOpenOutcome(openRequest, outcome);
      finishOpenRequest(openRequest);
    }
  }

  async function openBrowserFile(absPath: string, supported: boolean = true, forceReload: boolean = false): Promise<any> {
    if (!supported) {
      showToast('此格式暂不支持在线编辑：' + _displayFileName(absPath), 'info');
      return null;
    }
    if (!forceReload && await activateOpenTab(absPath)) return null;
    if (_isAbsolutePath(absPath) && !_isInsideWorkspace(absPath)) {
      const openRequest = beginOpenRequest('正在打开文件...', 'external', absPath);
      let outcome: 'success' | 'cancelled' | 'error' = 'error';
      let missingExternalFile = false;
      try {
        const res = await _csrfFetch('/api/v1/workspace/open_abs_file', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: absPath, open_request_id: openRequest.id }),
          signal: openRequest.controller.signal,
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
        const result = await openParsedFile(data, absPath, null);
        outcome = 'success';
        return result;
      } catch (error: any) {
        if (handleOpenAbort(error)) {
          outcome = 'cancelled';
          return null;
        }
        if (!missingExternalFile) console.error('[WA] openBrowserFile failed:', error);
        showToast(
          missingExternalFile ? '文件已不存在，已从最近文件移除' : (error.message || '打开文件失败'),
          missingExternalFile ? 'info' : 'error',
        );
        return null;
      } finally {
        recordOpenOutcome(openRequest, outcome);
        finishOpenRequest(openRequest);
      }
    }
    return openWorkspaceFile(absPath, supported, forceReload);
  }

  async function reloadFileByPath(filePath: string, supported: boolean = true): Promise<any> {
    if (_isAbsolutePath(filePath) && !_isInsideWorkspace(filePath)) {
      return openBrowserFile(filePath, supported, true);
    }
    return openWorkspaceFile(filePath, supported, true);
  }

  async function load(file: any): Promise<any> {
    if (!file) return null;
    if (file._waPath) return openWorkspaceFile(file._waPath, true);
    const openRequest = beginOpenRequest('正在解析文件...', 'upload', file.name, file.size);
    let outcome: 'success' | 'cancelled' | 'error' = 'error';
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('open_request_id', openRequest.id);
      const res = await _csrfFetch('/api/v1/workspace/open_file', {
        method: 'POST',
        body: formData,
        signal: openRequest.controller.signal,
      });
      const data = await _safeJson(res);
      if (!res.ok) throw new Error(data.error || '打开文件失败');
      const result = await openParsedFile(data, data.ws_source_path || file.name, file._fsHandle || null);
      outcome = 'success';
      return result;
    } catch (error: any) {
      if (handleOpenAbort(error)) {
        outcome = 'cancelled';
        return null;
      }
      console.error('[WA] load file failed:', error);
      showToast(error.message || '打开文件失败', 'error');
      return null;
    } finally {
      recordOpenOutcome(openRequest, outcome);
      finishOpenRequest(openRequest);
    }
  }

  return { openBrowserFile, openWorkspaceFile, reloadFileByPath, openParsedFile, fromParsed: openParsedFile, load };
}
