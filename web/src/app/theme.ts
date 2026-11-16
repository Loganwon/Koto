/**
 * Koto Theme Module — theme management, dark mode, UI zoom
 */

import {
  createUiZoomChangeEvent,
  getLogicalViewportSize,
  normalizeUiZoom,
  syncUiScaleBoundaries,
  syncLogicalViewportClasses,
  type UiZoomChangeDetail,
} from '../shared/ui-scale';
import { getFeatureRegistry } from '../shared/feature-registry';

export function applyTheme(theme: string): void {
  const root = document.documentElement;
  const requestedTheme = String(theme || 'light');
  // `auto` is a preference rather than a CSS palette.  Resolve it only for
  // the DOM attribute so the stylesheet still receives a concrete palette.
  // All named palettes must be preserved: reducing them to light/dark made
  // the Settings selection disagree with the workspace's actual colours.
  const resolvedTheme = requestedTheme === 'auto'
    ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : requestedTheme;
  const isDark = ['dark', 'ocean', 'forest', 'sunset', 'midnight'].includes(resolvedTheme);
  root.setAttribute('data-theme', resolvedTheme);
  root.dataset.kotoTheme = requestedTheme;
  document.body.classList.toggle('theme-dark', isDark);
  document.body.classList.toggle('theme-light', !isDark);
  document.body.dataset.kotoTheme = requestedTheme;
}

export function updateThemeSelector(theme: string): void {
  document.querySelectorAll('.theme-option').forEach((opt: Element) => {
    const el = opt as HTMLElement;
    el.classList.remove('active');
    if (el.dataset.theme === theme) {
      el.classList.add('active');
    }
  });
}

export function selectTheme(theme: string): void {
  const previousTheme = String(getFeatureRegistry().currentSettings?.appearance?.theme || localStorage.getItem('koto.theme') || 'light');
  updateThemeSelector(theme);
  applyTheme(theme);
  localStorage.setItem('koto.theme', theme);
  if (typeof getFeatureRegistry().updateSetting === 'function') {
    void getFeatureRegistry().updateSetting('appearance', 'theme', theme).then((saved: boolean) => {
      if (saved === false) {
        updateThemeSelector(previousTheme);
        applyTheme(previousTheme);
        localStorage.setItem('koto.theme', previousTheme);
      }
    });
  }
}

function _syncZoomViewportHeight(zoom: number): void {
  document.documentElement.style.setProperty('--viewport-h', `${window.innerHeight / zoom}px`);
}

/**
 * CSS zoom scales pixels after layout.  The unified workspace is fixed to the
 * viewport, so without compensating its logical dimensions a 130% zoom still
 * lays out at 100vw and is then painted 30% wider than the window.
 */
function _syncZoomLayoutViewport(zoom: number): UiZoomChangeDetail {
  const root = document.documentElement;
  const { width: layoutWidth, height: layoutHeight } = getLogicalViewportSize(zoom);
  root.style.setProperty('--koto-layout-width', `${layoutWidth}px`);
  root.style.setProperty('--koto-layout-height', `${layoutHeight}px`);

  // Compensated logical width is the only responsive input for workspace UI.
  if (document.body) syncLogicalViewportClasses(document.body, layoutWidth);
  return { zoom, layoutWidth, layoutHeight, devicePixelRatio: window.devicePixelRatio || 1 };
}

let _zoomNotificationFrame = 0;
let _pendingZoomDetail: UiZoomChangeDetail | null = null;

function _flushZoomChange(): void {
  _zoomNotificationFrame = 0;
  const detail = _pendingZoomDetail;
  _pendingZoomDetail = null;
  if (!detail) return;
  window.dispatchEvent(createUiZoomChangeEvent(detail));
  const WA = getFeatureRegistry() || {};
  if (typeof WA.refreshWorkspaceLayout === 'function') {
    WA.refreshWorkspaceLayout();
  }
}

function _scheduleZoomChange(detail: UiZoomChangeDetail): void {
  _pendingZoomDetail = detail;
  if (_zoomNotificationFrame) return;
  _zoomNotificationFrame = requestAnimationFrame(_flushZoomChange);
}

export function setUIZoom(
  zoomStr: string,
  suppressSave: boolean = false,
  persistLocal: boolean = true,
): void {
  const rawZoom = parseFloat(zoomStr);
  if (isNaN(rawZoom) || rawZoom <= 0) return;
  const zoom = normalizeUiZoom(rawZoom);
  const normalizedZoom = zoom.toFixed(2).replace(/\.?0+$/, '');
  const pct = Math.round(zoom * 100);
  const root = document.documentElement;
  // Slider previews can already have changed the DOM.  The last acknowledged
  // backend value is the only safe rollback target when the final save fails.
  const previousZoom = String(getFeatureRegistry().currentSettings?.appearance?.ui_zoom || root.dataset.kotoUiZoom || '1');
  // Only explicit UI boundaries are scaled. The body remains in native
  // viewport coordinates so startup chrome, downloads and third-party DOM do
  // not inherit application zoom accidentally.
  root.style.zoom = '';
  root.style.fontSize = '16px';
  const changed = root.dataset.kotoUiZoom !== normalizedZoom;
  root.dataset.kotoUiZoom = normalizedZoom;
  if (document.body) document.body.style.zoom = '';
  delete (window as any)._waZoomMinSize;
  _syncZoomViewportHeight(zoom);
  const detail = _syncZoomLayoutViewport(zoom);
  syncUiScaleBoundaries(zoom);
  // Update number-only display beside "Koto" logo
  const display = document.getElementById('uiZoomDisplay');
  if (display) display.textContent = pct + '%';
  const slider = document.getElementById('uiZoomSlider') as HTMLInputElement | null;
  if (slider) slider.value = String(pct);
  document.querySelectorAll('.fs-preset-btn').forEach((btn: Element) => {
    (btn as HTMLElement).classList.toggle('active', parseInt((btn.textContent || '').trim()) === pct);
  });
  if (persistLocal) localStorage.setItem('koto.uiZoom', normalizedZoom);
  // Persist to server (unless loading)
  if (!suppressSave) {
    if (typeof getFeatureRegistry().updateSetting === 'function') {
      void getFeatureRegistry().updateSetting('appearance', 'ui_zoom', normalizedZoom).then((saved: boolean) => {
        if (saved === false && root.dataset.kotoUiZoom === normalizedZoom) {
          setUIZoom(previousZoom, true);
        }
      });
    }
  }
  if (changed) _scheduleZoomChange(detail);
}

/** Apply a slider value immediately without producing overlapping save requests. */
export function previewUIZoom(zoomStr: string): void {
  setUIZoom(zoomStr, true, false);
}

export function changeUIScale(delta: number): void {
  const currentZoom = parseFloat(localStorage.getItem('koto.uiZoom') || '1');
  const newZoom = Math.max(0.7, Math.min(1.5, currentZoom + delta));
  setUIZoom(newZoom.toFixed(2));
}

window.addEventListener('resize', () => {
  const normalizedZoom = normalizeUiZoom(document.documentElement.dataset.kotoUiZoom || '1');
  _syncZoomViewportHeight(normalizedZoom);
  _scheduleZoomChange(_syncZoomLayoutViewport(normalizedZoom));
});

let _resolutionQuery: MediaQueryList | null = null;
function _watchDevicePixelRatio(): void {
  _resolutionQuery?.removeEventListener('change', _handleDevicePixelRatioChange);
  _resolutionQuery = window.matchMedia(`(resolution: ${window.devicePixelRatio || 1}dppx)`);
  _resolutionQuery.addEventListener('change', _handleDevicePixelRatioChange, { once: true });
}

function _handleDevicePixelRatioChange(): void {
  const normalizedZoom = normalizeUiZoom(document.documentElement.dataset.kotoUiZoom || '1');
  _syncZoomViewportHeight(normalizedZoom);
  _scheduleZoomChange(_syncZoomLayoutViewport(normalizedZoom));
  _watchDevicePixelRatio();
}

_watchDevicePixelRatio();

const _systemThemeQuery = window.matchMedia('(prefers-color-scheme: dark)');
_systemThemeQuery.addEventListener('change', () => {
  if (localStorage.getItem('koto.theme') === 'auto') applyTheme('auto');
});

// Backward compat
getFeatureRegistry().applyTheme = applyTheme;
getFeatureRegistry().updateThemeSelector = updateThemeSelector;
getFeatureRegistry().selectTheme = selectTheme;
getFeatureRegistry().setUIZoom = setUIZoom;
getFeatureRegistry().previewUIZoom = previewUIZoom;
getFeatureRegistry().changeUIScale = changeUIScale;

// Global exposure for inline HTML onclick handlers.
const w2 = window as any;
w2.selectTheme = selectTheme;
w2.setUIZoom = setUIZoom;
