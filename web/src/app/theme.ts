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
  const zoom = parseFloat(zoomStr);
  if (isNaN(zoom) || zoom <= 0) return;
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
  // Persist to server (unless loading)
  if (!suppressSave) {
    localStorage.setItem('koto.uiZoom', zoomStr);
    if (typeof (window as any).updateSetting === 'function') {
      (window as any).updateSetting('appearance', 'ui_zoom', zoomStr);
    }
  }
}

export function changeUIScale(delta: number): void {
  const currentZoom = parseFloat(localStorage.getItem('koto.uiZoom') || '1');
  const newZoom = Math.max(0.5, Math.min(2.0, currentZoom + delta));
  setUIZoom(newZoom.toFixed(2));
}

// Backward compat
(window as any).applyTheme = applyTheme;
(window as any).updateThemeSelector = updateThemeSelector;
(window as any).selectTheme = selectTheme;
(window as any).setUIZoom = setUIZoom;
(window as any).changeUIScale = changeUIScale;
