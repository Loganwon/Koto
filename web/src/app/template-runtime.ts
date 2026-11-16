// Runtime behavior owned by server-rendered workspace markup.
import { getFeatureRegistry, registerFeatures } from '../shared/feature-registry';
import { reportWorkspaceReady } from '../shared/startup-monitor';
import { getWorkspaceAssetUrl } from '../shared/workspace-assets';

const bundleLoads = new Map<string, Promise<void>>();

function loadBundle(src: string): Promise<void> {
  const base = src.split('?')[0];
  const loaded = Array.from(document.scripts).some(script =>
    !!script.src && script.src.includes(base),
  );
  if (loaded) return Promise.resolve();
  const pending = bundleLoads.get(src);
  if (pending) return pending;

  const load = new Promise<void>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = src;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(script);
  }).catch(error => {
    bundleLoads.delete(src);
    throw error;
  });
  bundleLoads.set(src, load);
  return load;
}

function updateGreeting(): void {
  const hour = new Date().getHours();
  const greeting = hour < 6 ? '夜深了'
    : hour < 9 ? '早上好'
      : hour < 12 ? '上午好'
        : hour < 14 ? '中午好'
          : hour < 18 ? '下午好'
            : hour < 22 ? '晚上好'
              : '夜深了';
  const target = document.getElementById('welcomeGreeting');
  if (target) target.textContent = `${greeting}，我是 Koto`;
}

function installCapabilityPanelLoader(): void {
  let loaded = false;
  let loading: Promise<void> | null = null;
  const bundleUrl = getWorkspaceAssetUrl('capability-panel-bundle');
  const stubs: Record<string, (...args: any[]) => unknown> = {};

  function load(): Promise<void> {
    if (loaded) return Promise.resolve();
    if (loading) return loading;
    loading = loadBundle(bundleUrl).then(() => { loaded = true; });
    return loading;
  }

  function callAfterLoad(name: string, args: any[]): Promise<unknown> {
    return load().then(() => {
      const fn = getFeatureRegistry()[name];
      if (typeof fn === 'function' && fn !== stubs[name]) {
        return fn(...args);
      }
      return undefined;
    }).catch(error => {
      console.warn('[Koto] Addon panel bundle load failed', error);
      return undefined;
    });
  }

  [
    'openCapabilityPanel',
    'closeCapabilityPanel',
    'toggleCapabilityPanel',
  ].forEach(name => {
    if (typeof getFeatureRegistry()[name] !== 'function') {
      stubs[name] = (...args: any[]) => callAfterLoad(name, args);
      getFeatureRegistry()[name] = stubs[name];
    }
  });

  document.addEventListener('click', event => {
    const target = event.target as Element | null;
    if (target?.closest('#navCapabilityBtn,#capabilityPanel .ui-close-button,[data-action="open-addons"],[data-action="toggle-addons"],[data-action="close-addons"]')) {
      void load();
    }
  }, true);

  registerFeatures({ loadCapabilityPanelBundle: load });
}

function installDeferredWorkspaceLoader(): void {
  const bundleUrl = getWorkspaceAssetUrl('workspace-bundle');
  let loading: Promise<void> | null = null;

  function load(): Promise<void> {
    if (document.documentElement.dataset.kotoWorkspaceRuntime === 'ready') {
      return Promise.resolve();
    }
    if (loading) return loading;
    const loadStartedAt = performance.now();
    document.documentElement.dataset.kotoWorkspaceBundle = 'loading';
    loading = loadBundle(bundleUrl).then(() => {
      document.documentElement.dataset.kotoWorkspaceBundle = 'ready';
      window.dispatchEvent(new CustomEvent('koto:workspace-ready'));
      void reportWorkspaceReady(performance.now() - loadStartedAt);
    }).catch(error => {
      loading = null;
      document.documentElement.dataset.kotoWorkspaceBundle = 'failed';
      console.warn('[Koto] Workspace bundle load failed', error);
      throw error;
    });
    return loading;
  }

  function schedule(): void {
    requestAnimationFrame(() => requestAnimationFrame(() => {
      void load().catch(() => undefined);
    }));
  }

  registerFeatures({ loadWorkspaceBundle: load });
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', schedule, { once: true });
  } else {
    schedule();
  }
}

function revealApplication(): void {
  if (document.body.style.opacity === '0') {
    setTimeout(() => { document.body.style.opacity = '1'; }, 50);
  }
  const splash = document.getElementById('startupSplash');
  if (!splash) return;
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      splash.classList.add('hidden');
      document.body.classList.remove('loading');
      setTimeout(() => splash.remove(), 350);
    });
  });
}

updateGreeting();
installCapabilityPanelLoader();
installDeferredWorkspaceLoader();
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', revealApplication, { once: true });
} else {
  revealApplication();
}
