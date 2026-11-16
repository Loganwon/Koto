import { deferAfterPaint } from './init-deferred';
import { reportFrontendReadyAfterPaint } from './startup-monitor';

type StartupHost = Window & {
  applyTheme?: (theme: string) => void;
  updateThemeSelector?: (theme: string) => void;
  setUIZoom?: (zoom: string, suppressSave?: boolean, persistLocal?: boolean) => void;
  renderWelcomeScreen?: () => void;
  loadSettings?: () => void | Promise<void>;
};

function readCachedSetting(key: string): string {
  try {
    return localStorage.getItem(key) || '';
  } catch {
    return '';
  }
}

/** Render everything required for a usable first frame without network I/O. */
export function renderStartupShell(host: StartupHost = window): void {
  const root = document.documentElement;
  const theme = readCachedSetting('koto.theme')
    || root.dataset.kotoTheme
    || root.getAttribute('data-theme')
    || 'light';
  const zoom = readCachedSetting('koto.uiZoom')
    || root.dataset.kotoUiZoom
    || '1';

  host.applyTheme?.(theme);
  host.updateThemeSelector?.(theme);
  host.setUIZoom?.(zoom, true, false);
  host.renderWelcomeScreen?.();
}

/** Reconcile server-backed state after first paint; it must never gate startup. */
export function startPostPaintHydration(host: StartupHost = window): void {
  void reportFrontendReadyAfterPaint();
  deferAfterPaint(() => host.loadSettings?.());
}
