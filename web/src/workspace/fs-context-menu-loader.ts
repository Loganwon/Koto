import { _loadScript } from '../editors/cdn-loaders';
import { getWorkspaceApi, publishWorkspaceApi } from '../shared/workspace-api';

const CONTEXT_ACTION_NAMES = [
  '_fsBrowserOpen',
  '_fsBrowserAddToWorkspace',
  '_fsBrowserAddToTempWorkspace',
  '_fsBrowserSendToAI',
  '_fsBrowserCopy',
  '_fsBrowserCut',
  '_fsBrowserPaste',
  '_fsBrowserCopyPath',
  '_fsBrowserRename',
  '_fsBrowserDelete',
  '_fsBrowserNewFile',
  '_fsBrowserNewFolder',
  '_fsBrowserAISummary',
] as const;

let fsContextMenuLoadPromise: Promise<void> | null = null;
let loaderInstalled = false;

function fsContextMenuAssetUrl(): string {
  const assets = (window as any).__kotoWorkspaceEditorAssets || {};
  return String(
    assets['fs-context-menu-bundle']
    || '/static/js/build/fs-context-menu-bundle.js',
  );
}

function hasLoadedFsContextMenu(): boolean {
  const api = getWorkspaceApi();
  return typeof api._showBrowserCtx === 'function'
    && api._showBrowserCtx !== showBrowserContextMenuBridge
    && typeof api._closeCtxMenu === 'function'
    && api._closeCtxMenu !== closeContextMenuBridge;
}

export function loadFsContextMenu(): Promise<void> {
  if (fsContextMenuLoadPromise) return fsContextMenuLoadPromise;
  if (hasLoadedFsContextMenu()) {
    document.documentElement.setAttribute('data-koto-fs-context-menu', 'ready');
    return Promise.resolve();
  }

  document.documentElement.setAttribute('data-koto-fs-context-menu', 'loading');
  fsContextMenuLoadPromise = _loadScript(fsContextMenuAssetUrl(), 60000)
    .then(() => {
      if (!hasLoadedFsContextMenu()) {
        throw new Error('文件右键菜单运行时加载后未注册完整接口');
      }
      document.documentElement.setAttribute('data-koto-fs-context-menu', 'ready');
    })
    .catch((error) => {
      fsContextMenuLoadPromise = null;
      document.documentElement.setAttribute('data-koto-fs-context-menu', 'error');
      throw error;
    });
  return fsContextMenuLoadPromise;
}

function reportLoadFailure(error: unknown): void {
  console.warn('[Koto] File context menu runtime unavailable:', error);
}

function showBrowserContextMenuBridge(event: MouseEvent, element: HTMLElement): null {
  event.preventDefault();
  event.stopPropagation();
  void loadFsContextMenu().then(() => {
    const show = getWorkspaceApi()._showBrowserCtx;
    if (typeof show === 'function' && show !== showBrowserContextMenuBridge) {
      show(event, element);
    }
  }).catch(reportLoadFailure);
  return null;
}

function closeContextMenuBridge(): void {
  // Closing a menu that has never opened must remain a no-op and must not pull
  // the optional runtime into normal file-tree clicks or Escape handling.
  document.getElementById('wa-ctx-menu')?.classList.remove('open');
}

const contextActionBridges: Record<string, (..._args: any[]) => Promise<any>> = {};
for (const name of CONTEXT_ACTION_NAMES) {
  contextActionBridges[name] = (...args: any[]) => loadFsContextMenu().then(() => {
    const method = getWorkspaceApi()[name];
    if (typeof method === 'function' && method !== contextActionBridges[name]) {
      return method(...args);
    }
    return null;
  });
}

export function installFsContextMenuLoader(): void {
  if (loaderInstalled) return;
  loaderInstalled = true;
  publishWorkspaceApi({
    _showBrowserCtx: showBrowserContextMenuBridge,
    _closeCtxMenu: closeContextMenuBridge,
    ...contextActionBridges,
    loadFsContextMenu,
  });
}
