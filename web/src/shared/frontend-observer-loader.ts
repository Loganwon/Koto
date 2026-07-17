import { getWorkspaceApi } from './workspace-api';

type IdleWindow = Window & typeof globalThis & {
  requestIdleCallback?: (callback: () => void, options?: { timeout?: number }) => number;
};

let observerLoadPromise: Promise<void> | null = null;

function _observerAssetUrl(): string {
  const assets = (window as any).__kotoWorkspaceEditorAssets || {};
  return String(assets['frontend-observer-bundle'] || '').trim();
}

export function loadFrontendObserver(): Promise<void> {
  if ((window as any).KotoFrontendObserver) return Promise.resolve();
  if (observerLoadPromise) return observerLoadPromise;

  const src = _observerAssetUrl();
  if (!src) return Promise.reject(new Error('Frontend observer asset is not configured'));

  observerLoadPromise = new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>('script[data-koto-frontend-observer]');
    if (existing) {
      existing.addEventListener('load', () => resolve(), { once: true });
      existing.addEventListener('error', () => reject(new Error('Frontend observer failed to load')), { once: true });
      return;
    }

    const script = document.createElement('script');
    script.src = src;
    script.async = true;
    script.dataset.kotoFrontendObserver = 'loading';
    script.onload = () => {
      script.dataset.kotoFrontendObserver = 'ready';
      document.documentElement.setAttribute('data-koto-frontend-observer', 'ready');
      resolve();
    };
    script.onerror = () => {
      observerLoadPromise = null;
      script.dataset.kotoFrontendObserver = 'error';
      document.documentElement.setAttribute('data-koto-frontend-observer', 'error');
      reject(new Error('Frontend observer failed to load'));
    };
    document.head.appendChild(script);
  });

  return observerLoadPromise;
}

export function scheduleFrontendObserverLoad(): void {
  const run = () => {
    void loadFrontendObserver().catch((error) => {
      console.warn('[Koto] Frontend observer unavailable:', error);
    });
  };
  const idleWindow = window as IdleWindow;
  if (typeof idleWindow.requestIdleCallback === 'function') {
    idleWindow.requestIdleCallback(run, { timeout: 1500 });
  } else {
    window.setTimeout(run, 350);
  }
}

getWorkspaceApi().loadFrontendObserver = loadFrontendObserver;
