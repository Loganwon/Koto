import { _loadScript } from '../editors/cdn-loaders';
import { getFeatureRegistry } from '../shared/feature-registry';
import { getWorkspaceAssetUrl } from '../shared/workspace-assets';

export interface WorkspaceFindReplaceDeps {
  getActiveEditor: () => any;
  showToast?: (
    _message: string,
    _type?: 'info' | 'success' | 'warning' | 'error',
  ) => void;
  pptxNav?: (_delta: number) => void;
  scheduleAutoSave?: () => void;
}

type IdleWindow = Window & typeof globalThis & {
  requestIdleCallback?: (
    _callback: () => void,
    _options?: { timeout?: number },
  ) => number;
};

let findReplaceLoadPromise: Promise<void> | null = null;
let focusWarmupInstalled = false;

function findReplaceAssetUrl(): string {
  return getWorkspaceAssetUrl('find-replace-bundle');
}

function syncFocusedFindInput(): void {
  const input = document.activeElement as HTMLInputElement | null;
  const scope = String(input?.dataset?.waFindInput || '').trim();
  if (!scope || !input) return;
  const method = getFeatureRegistry()[`${scope}FindInput`];
  if (typeof method === 'function') method(input.value);
}

function installLoadedFindReplace(deps: WorkspaceFindReplaceDeps): void {
  const install = getFeatureRegistry().installWorkspaceFindReplace;
  if (typeof install !== 'function') {
    throw new Error('查找替换运行时加载后未注册安装接口');
  }
  install(deps);
  syncFocusedFindInput();
  document.documentElement.setAttribute('data-koto-find-replace', 'ready');
}

export function loadWorkspaceFindReplace(
  deps: WorkspaceFindReplaceDeps,
): Promise<void> {
  if (typeof getFeatureRegistry().installWorkspaceFindReplace === 'function') {
    installLoadedFindReplace(deps);
    return Promise.resolve();
  }
  if (findReplaceLoadPromise) return findReplaceLoadPromise;

  document.documentElement.setAttribute('data-koto-find-replace', 'loading');
  findReplaceLoadPromise = _loadScript(findReplaceAssetUrl(), 60000)
    .then(() => installLoadedFindReplace(deps))
    .catch((error) => {
      findReplaceLoadPromise = null;
      document.documentElement.setAttribute('data-koto-find-replace', 'error');
      throw error;
    });
  return findReplaceLoadPromise;
}

export function scheduleWorkspaceFindReplaceLoad(
  deps: WorkspaceFindReplaceDeps,
): void {
  const warmup = () => {
    void loadWorkspaceFindReplace(deps).catch((error) => {
      console.warn('[Koto] Find/replace runtime unavailable:', error);
    });
  };

  if (!focusWarmupInstalled) {
    focusWarmupInstalled = true;
    document.addEventListener('focusin', (event) => {
      const target = event.target as HTMLElement | null;
      if (target?.matches?.('[data-wa-find-input], [data-wa-find-replace-input]')) {
        warmup();
      }
    }, true);
  }

  const idleWindow = window as IdleWindow;
  if (typeof idleWindow.requestIdleCallback === 'function') {
    idleWindow.requestIdleCallback(warmup, { timeout: 1200 });
  } else {
    window.setTimeout(warmup, 300);
  }
}
