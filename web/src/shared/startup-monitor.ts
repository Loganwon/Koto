export interface StartupErrorRecord {
  type: string;
  message: string;
  source?: string;
  line?: number;
  column?: number;
}

const STARTUP_ERRORS_SLOT = '__kotoStartupErrors__';

function startupErrors(): StartupErrorRecord[] {
  const host = document as Document & Record<string, any>;
  if (!Array.isArray(host[STARTUP_ERRORS_SLOT])) {
    Object.defineProperty(host, STARTUP_ERRORS_SLOT, { value: [], enumerable: false });
  }
  return host[STARTUP_ERRORS_SLOT];
}

function recordStartupError(payload: StartupErrorRecord): void {
  const errors = startupErrors();
  errors.push(payload);
  document.documentElement.setAttribute('data-koto-startup-error', JSON.stringify(errors.slice(-5)));
}

export function installStartupMonitor(): void {
  if (document.documentElement.dataset.kotoStartupMonitor === 'ready') return;
  document.documentElement.dataset.kotoStartupMonitor = 'ready';
  window.addEventListener('error', (event) => recordStartupError({
    type: 'error',
    message: String(event.message || 'Unknown startup error'),
    source: String(event.filename || ''),
    line: Number(event.lineno || 0),
    column: Number(event.colno || 0),
  }));
  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason;
    recordStartupError({
      type: 'unhandledrejection',
      message: reason?.message ? String(reason.message) : String(reason || 'Unknown rejection'),
    });
  });
}

export function drainStartupErrors(): StartupErrorRecord[] {
  return startupErrors().splice(0);
}

type DesktopStartupApi = {
  report_frontend_ready?: (metrics: Record<string, unknown>) => Promise<unknown>;
  report_workspace_ready?: (metrics: Record<string, unknown>) => Promise<unknown>;
};

function desktopStartupApi(): DesktopStartupApi | null {
  const api = (window as any).pywebview?.api as DesktopStartupApi | undefined;
  return api?.report_frontend_ready ? api : null;
}

function waitForDesktopStartupApi(timeoutMs = 10000): Promise<DesktopStartupApi | null> {
  const current = desktopStartupApi();
  if (current) return Promise.resolve(current);
  return new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      window.removeEventListener('pywebviewready', onReady);
      resolve(desktopStartupApi());
    };
    const onReady = () => finish();
    const timer = window.setTimeout(finish, timeoutMs);
    window.addEventListener('pywebviewready', onReady, { once: true });
  });
}

function afterTwoPaints(): Promise<void> {
  return new Promise((resolve) => {
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => resolve()));
  });
}

export async function reportFrontendReadyAfterPaint(): Promise<boolean> {
  await afterTwoPaints();
  const api = await waitForDesktopStartupApi();
  if (!api?.report_frontend_ready) return false;
  const navigation = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined;
  try {
    await api.report_frontend_ready({
      document_ready_state: document.readyState,
      navigation_type: navigation?.type || '',
      dom_content_loaded_ms: Math.round(navigation?.domContentLoadedEventEnd || 0),
      load_event_ms: Math.round(navigation?.loadEventEnd || 0),
    });
    document.documentElement.dataset.kotoFrontendReady = 'true';
    return true;
  } catch {
    return false;
  }
}

export async function reportWorkspaceReady(bundleLoadMs: number): Promise<boolean> {
  const api = await waitForDesktopStartupApi();
  if (!api?.report_workspace_ready) return false;
  try {
    await api.report_workspace_ready({ bundle_load_ms: Math.round(bundleLoadMs) });
    return true;
  } catch {
    return false;
  }
}
