import { _loadScript } from '../editors/cdn-loaders';
import { getWorkspaceApi, publishWorkspaceApi } from '../shared/workspace-api';

export interface TaskWorkbenchOpenOptions {
  taskId?: any;
  runId?: any;
  scroll?: boolean;
}

let taskWorkbenchLoadPromise: Promise<void> | null = null;
let loaderInstalled = false;

function taskWorkbenchAssetUrl(): string {
  const assets = (window as any).__kotoWorkspaceEditorAssets || {};
  return String(
    assets['task-workbench-bundle']
    || '/static/js/build/task-workbench-bundle.js',
  );
}

function hasLoadedTaskWorkbench(): boolean {
  const api = getWorkspaceApi();
  return typeof api.initTaskWorkbench === 'function'
    && api.initTaskWorkbench !== initTaskWorkbenchBridge
    && typeof api.openTaskWorkbenchForCurrentRun === 'function'
    && api.openTaskWorkbenchForCurrentRun !== openTaskWorkbenchBridge;
}

export function loadTaskWorkbench(): Promise<void> {
  if (taskWorkbenchLoadPromise) return taskWorkbenchLoadPromise;
  if (hasLoadedTaskWorkbench()) {
    document.documentElement.setAttribute('data-koto-task-workbench', 'ready');
    return Promise.resolve();
  }

  document.documentElement.setAttribute('data-koto-task-workbench', 'loading');
  taskWorkbenchLoadPromise = _loadScript(taskWorkbenchAssetUrl(), 60000)
    .then(() => {
      if (!hasLoadedTaskWorkbench()) {
        throw new Error('任务详情运行时加载后未注册完整接口');
      }
      document.documentElement.setAttribute('data-koto-task-workbench', 'ready');
    })
    .catch((error) => {
      taskWorkbenchLoadPromise = null;
      document.documentElement.setAttribute('data-koto-task-workbench', 'error');
      throw error;
    });
  return taskWorkbenchLoadPromise;
}

function reportLoadFailure(error: unknown): void {
  console.warn('[Koto] Task workbench runtime unavailable:', error);
}

function initTaskWorkbenchBridge(): null {
  void loadTaskWorkbench().then(() => {
    const init = getWorkspaceApi().initTaskWorkbench;
    if (typeof init === 'function' && init !== initTaskWorkbenchBridge) init();
  }).catch(reportLoadFailure);
  return null;
}

function openTaskWorkbenchBridge(options?: TaskWorkbenchOpenOptions): null {
  const request = options ? { ...options } : {};
  void loadTaskWorkbench().then(() => {
    const open = getWorkspaceApi().openTaskWorkbenchForCurrentRun;
    if (typeof open === 'function' && open !== openTaskWorkbenchBridge) {
      open(request);
    }
  }).catch(reportLoadFailure);
  return null;
}

function refreshCurrentTaskFlowBridge(): Promise<any> {
  return loadTaskWorkbench().then(() => {
    const refresh = getWorkspaceApi().refreshCurrentTaskFlow;
    if (typeof refresh === 'function' && refresh !== refreshCurrentTaskFlowBridge) {
      return refresh();
    }
    return null;
  });
}

export function installTaskWorkbenchLoader(): void {
  if (loaderInstalled) return;
  loaderInstalled = true;
  publishWorkspaceApi({
    initTaskWorkbench: initTaskWorkbenchBridge,
    refreshCurrentTaskFlow: refreshCurrentTaskFlowBridge,
    openTaskWorkbenchForCurrentRun: openTaskWorkbenchBridge,
    loadTaskWorkbench,
  });
}
