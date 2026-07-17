/**
 * Koto Theme Module — theme management, dark mode, UI zoom
 */

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
  const previousTheme = String((window as any).currentSettings?.appearance?.theme || localStorage.getItem('koto.theme') || 'light');
  updateThemeSelector(theme);
  applyTheme(theme);
  localStorage.setItem('koto.theme', theme);
  if (typeof (window as any).updateSetting === 'function') {
    void (window as any).updateSetting('appearance', 'theme', theme).then((saved: boolean) => {
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
function _syncZoomLayoutViewport(zoom: number): void {
  const root = document.documentElement;
  root.style.setProperty('--koto-layout-width', `${window.innerWidth / zoom}px`);
  root.style.setProperty('--koto-layout-height', `${window.innerHeight / zoom}px`);

  // The compensated layout width is the single responsive input.  This covers
  // both a physically narrow window and a large UI scale without maintaining
  // parallel media-query and zoom-only layout branches.
  document.body?.classList.toggle('koto-layout-compact', (window.innerWidth / zoom) < 1100);
  window.dispatchEvent(new CustomEvent('koto-ui-zoom-change'));
}

function _reflowWorkspaceAfterZoom(): void {
  const WA = (window as any).WA || {};
  if (typeof WA.refreshWorkspaceLayout === 'function') {
    WA.refreshWorkspaceLayout();
  }
}

export function setUIZoom(zoomStr: string, suppressSave: boolean = false): void {
  const rawZoom = parseFloat(zoomStr);
  if (isNaN(rawZoom) || rawZoom <= 0) return;
  const zoom = Math.max(0.7, Math.min(1.5, rawZoom));
  const normalizedZoom = zoom.toFixed(2).replace(/\.?0+$/, '');
  const pct = Math.round(zoom * 100);
  const root = document.documentElement;
  // Slider previews can already have changed the DOM.  The last acknowledged
  // backend value is the only safe rollback target when the final save fails.
  const previousZoom = String((window as any).currentSettings?.appearance?.ui_zoom || root.dataset.kotoUiZoom || '1');
  // Body zoom is the single owner for visual scaling.  Its post-layout nature
  // requires the logical viewport compensation below for fixed workspace UI.
  root.style.zoom = '';
  root.style.fontSize = '16px';
  root.dataset.kotoUiZoom = normalizedZoom;
  if (document.body) document.body.style.zoom = normalizedZoom;
  delete (window as any)._waZoomMinSize;
  _syncZoomViewportHeight(zoom);
  _syncZoomLayoutViewport(zoom);
  // Update number-only display beside "Koto" logo
  const display = document.getElementById('uiZoomDisplay');
  if (display) display.textContent = pct + '%';
  const slider = document.getElementById('uiZoomSlider') as HTMLInputElement | null;
  if (slider) slider.value = String(pct);
  document.querySelectorAll('.fs-preset-btn').forEach((btn: Element) => {
    (btn as HTMLElement).classList.toggle('active', parseInt((btn.textContent || '').trim()) === pct);
  });
  localStorage.setItem('koto.uiZoom', normalizedZoom);
  // Persist to server (unless loading)
  if (!suppressSave) {
    if (typeof (window as any).updateSetting === 'function') {
      void (window as any).updateSetting('appearance', 'ui_zoom', normalizedZoom).then((saved: boolean) => {
        if (saved === false && root.dataset.kotoUiZoom === normalizedZoom) {
          setUIZoom(previousZoom, true);
        }
      });
    }
  }
  requestAnimationFrame(_reflowWorkspaceAfterZoom);
}

/** Apply a slider value immediately without producing overlapping save requests. */
export function previewUIZoom(zoomStr: string): void {
  setUIZoom(zoomStr, true);
}

export function changeUIScale(delta: number): void {
  const currentZoom = parseFloat(localStorage.getItem('koto.uiZoom') || '1');
  const newZoom = Math.max(0.7, Math.min(1.5, currentZoom + delta));
  setUIZoom(newZoom.toFixed(2));
}

window.addEventListener('resize', () => {
  const zoom = parseFloat(document.documentElement.dataset.kotoUiZoom || '1');
  const normalizedZoom = Number.isFinite(zoom) && zoom > 0 ? zoom : 1;
  _syncZoomViewportHeight(normalizedZoom);
  _syncZoomLayoutViewport(normalizedZoom);
});

const _systemThemeQuery = window.matchMedia('(prefers-color-scheme: dark)');
_systemThemeQuery.addEventListener('change', () => {
  if (localStorage.getItem('koto.theme') === 'auto') applyTheme('auto');
});

// Backward compat
(window as any).applyTheme = applyTheme;
(window as any).updateThemeSelector = updateThemeSelector;
(window as any).selectTheme = selectTheme;
(window as any).setUIZoom = setUIZoom;
(window as any).previewUIZoom = previewUIZoom;
(window as any).changeUIScale = changeUIScale;
