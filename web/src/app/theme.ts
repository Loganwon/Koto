/**
 * Koto Theme Module — theme management, dark mode, UI zoom
 */

export function applyTheme(theme: string): void {
  const root = document.documentElement;
  const isDark = theme === 'dark' || (theme === 'auto' && window.matchMedia('(prefers-color-scheme: dark)').matches);
  root.setAttribute('data-theme', isDark ? 'dark' : 'light');
  document.body.classList.toggle('theme-dark', isDark);
  document.body.classList.toggle('theme-light', !isDark);
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
  updateThemeSelector(theme);
  applyTheme(theme);
  localStorage.setItem('koto.theme', theme);
  if (typeof (window as any).updateSetting === 'function') {
    (window as any).updateSetting('appearance', 'theme', theme);
  }
}

export function setUIZoom(zoomStr: string, suppressSave: boolean = false): void {
  const rawZoom = parseFloat(zoomStr);
  if (isNaN(rawZoom) || rawZoom <= 0) return;
  const zoom = Math.max(0.7, Math.min(1.5, rawZoom));
  const normalizedZoom = zoom.toFixed(2).replace(/\.?0+$/, '');
  const pct = Math.round(zoom * 100);
  const root = document.documentElement;
  root.style.fontSize = `${16 * zoom}px`;
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
      (window as any).updateSetting('appearance', 'ui_zoom', normalizedZoom);
    }
  }
}

export function changeUIScale(delta: number): void {
  const currentZoom = parseFloat(localStorage.getItem('koto.uiZoom') || '1');
  const newZoom = Math.max(0.7, Math.min(1.5, currentZoom + delta));
  setUIZoom(newZoom.toFixed(2));
}

// Backward compat
(window as any).applyTheme = applyTheme;
(window as any).updateThemeSelector = updateThemeSelector;
(window as any).selectTheme = selectTheme;
(window as any).setUIZoom = setUIZoom;
(window as any).changeUIScale = changeUIScale;
