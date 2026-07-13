/**
 * Panel Layout & Selection — selectionchange handler, Split.js init, panel auto-reset.
 * Workspace panel layout.
 */

declare function $(id: string): HTMLElement | null;
declare let state: any;
declare let WA: any;
declare let lastSelectionText: string;
declare function _resetDocxSelection(): void;

export interface SplitConfig {
  sizes: number[];
  minSize: number[];
  gutterSize: number;
  snapOffset: number;
  onDragEnd: (sizes: number[]) => void;
}

export interface PanelLayout {
  left?: HTMLElement | null;
  canvas: HTMLElement | null;
  ai: HTMLElement | null;
  embedded: boolean;
  splitKey: string;
}

// ── selectionchange: collapse detection ONLY ─────────────────────────
let _selChangeTimer: any = null;

function _isDocxMouseDown(): boolean {
  return Boolean(
    (state && state._docxMouseIsDown)
    || (window as any)._docxMouseIsDown,
  );
}

document.addEventListener('selectionchange', () => {
  if (state.fileType !== 'docx') return;
  clearTimeout(_selChangeTimer);
  _selChangeTimer = setTimeout(() => {
    const _ae = document.activeElement;
    if (_ae && (_ae.closest('#wa-pdf-tooltip') || _ae.closest('#wa-docx-hoverbar') || _ae.closest('#wa-docx-cp') || _ae.closest('#wa-review-shell') || _ae.closest('#wa-review-selection-launcher'))) return;
    if (_isDocxMouseDown() && document.querySelector('#wa-pdf-tooltip:hover, #wa-docx-hoverbar:hover, #wa-review-shell:hover, #wa-review-selection-launcher:hover')) return;
    const _ws = window.getSelection();
    if (!_ws || _ws.isCollapsed || !_ws.rangeCount) {
      _resetDocxSelection();
    }
  }, 80);
});

// Hide selection toolbar on scroll
document.addEventListener('scroll', () => {
  const tt = $('wa-pdf-tooltip');
  if (tt) tt.style.display = 'none';
  if (state.fileType === 'docx') _resetDocxSelection();
  else lastSelectionText = '';
}, true);

const _waAiMsgs = $('wa-ai-messages');
if (_waAiMsgs) {
  _waAiMsgs.addEventListener('wheel', () => {
    const tt = $('wa-pdf-tooltip');
    if (tt && tt.style.display !== 'none') {
      tt.style.display = 'none';
      lastSelectionText = '';
    }
  }, { passive: true });
}

document.addEventListener('wheel', () => {
  const tt = $('wa-pdf-tooltip');
  if (tt && tt.style.display !== 'none') {
    tt.style.display = 'none';
    lastSelectionText = '';
  }
}, { passive: true, capture: true });

// ── Split.js Init ────────────────────────────────────────────────────────────
const _STANDALONE_SPLIT_DEFAULT = [15, 55, 30];
const _EMBEDDED_SPLIT_DEFAULT = [68, 32];
// The composer has model controls, attachment actions, and a task stream.  A
// narrow persisted Split.js size turns it into an unusable clipped rail.
const _EMBEDDED_AI_MIN_WIDTH = 420;
const _SPLIT_LAYOUT_STORAGE = {
  standalone: 'wa_split_sizes_v2',
  embedded: 'wa_split_sizes_embedded_v2',
} as const;
const _LEGACY_SPLIT_LAYOUT_STORAGE = ['wa_split_sizes', 'wa_split_sizes_embedded'];

function _retireLegacySplitLayouts(): void {
  try {
    _LEGACY_SPLIT_LAYOUT_STORAGE.forEach((key) => localStorage.removeItem(key));
  } catch { /* Storage can be unavailable in private or embedded webviews. */ }
}

function _splitLayoutStorageKey(embedded: boolean): string {
  return embedded ? _SPLIT_LAYOUT_STORAGE.embedded : _SPLIT_LAYOUT_STORAGE.standalone;
}

function _isUsableSplitSizes(value: unknown, expectedLength: number): value is number[] {
  return Array.isArray(value)
    && value.length === expectedLength
    && value.every((size) => Number.isFinite(size) && size > 0)
    && Math.abs(value.reduce((total, size) => total + size, 0) - 100) < 1;
}

function _enforceEmbeddedAiWidth(splitKey: string, canvas: HTMLElement, ai: HTMLElement): void {
  const split = (window as any)._waSplit;
  if (!split || ai.offsetWidth >= _EMBEDDED_AI_MIN_WIDTH) return;
  const splitWidth = canvas.offsetWidth + ai.offsetWidth;
  if (splitWidth <= 0) return;

  const aiPercent = Math.min(50, Math.max(
    _EMBEDDED_SPLIT_DEFAULT[1],
    (_EMBEDDED_AI_MIN_WIDTH / splitWidth) * 100,
  ));
  const sizes = [100 - aiPercent, aiPercent];
  try {
    split.setSizes(sizes);
    localStorage.setItem(splitKey, JSON.stringify(sizes));
  } catch (e) { console.warn('[Koto] unable to restore AI panel width', e); }
}

export function _initSplit(): void {
  if ((window as any)._waSplit) return;
  const left = $('wa-left'), canvas = $('wa-canvas'), ai = $('wa-ai');
  const embedded = !!document.getElementById('workspaceView');
  if (!canvas || !ai || (!embedded && !left)) return;
  _retireLegacySplitLayouts();
  const splitKey = _splitLayoutStorageKey(embedded);
  let savedSizes: number[] | null = null;
  try {
    const raw = localStorage.getItem(splitKey);
    const parsed = raw ? JSON.parse(raw) : null;
    savedSizes = _isUsableSplitSizes(parsed, embedded ? 2 : 3) ? parsed : null;
  } catch (e) { console.warn("[Koto]", e) }

  const targets = embedded ? ['#wa-canvas', '#wa-ai'] : ['#wa-left', '#wa-canvas', '#wa-ai'];
  (window as any)._waSplit = (window as any).Split(targets, {
    sizes: savedSizes || (embedded ? _EMBEDDED_SPLIT_DEFAULT : _STANDALONE_SPLIT_DEFAULT),
    minSize: embedded ? [420, _EMBEDDED_AI_MIN_WIDTH] : [150, 400, _EMBEDDED_AI_MIN_WIDTH],
    gutterSize: 6,
    snapOffset: 0,
    onDragEnd(sizes: number[]) {
      try { localStorage.setItem(splitKey, JSON.stringify(sizes)); } catch {}
    }
  });
  if (embedded) {
    requestAnimationFrame(() => _enforceEmbeddedAiWidth(splitKey, canvas, ai));
  }
}

export function refreshWorkspaceLayout(): void {
  const split = (window as any)._waSplit;
  if (!split || typeof split.getSizes !== 'function' || typeof split.setSizes !== 'function') return;
  requestAnimationFrame(() => {
    try {
      const sizes = split.getSizes();
      if (Array.isArray(sizes) && sizes.length) split.setSizes(sizes);
    } catch (error) { console.warn('[Koto] unable to reflow workspace layout', error); }

    const embedded = !!document.getElementById('workspaceView');
    const canvas = $('wa-canvas');
    const ai = $('wa-ai');
    if (embedded && canvas && ai) {
      _enforceEmbeddedAiWidth(_splitLayoutStorageKey(true), canvas, ai);
    }
  });
}

// Standalone page: init immediately; embedded mode defers to openInMainView().
if (!document.getElementById('workspaceView')) {
  _initSplit();
  // Apply saved AI panel state after a short delay for Split.js to initialize
  setTimeout(() => _applySavedAiPanelState(), 50);
}

// ── Panel auto-reset setting ─────────────────────────────────────────────────
let _panelAutoReset: boolean = localStorage.getItem('wa_panel_autoreset') !== 'off';

export function setPanelAutoReset(enabled: boolean): void {
  _panelAutoReset = enabled;
  localStorage.setItem('wa_panel_autoreset', enabled ? 'on' : 'off');
  const onEl = document.getElementById('wa-panel-autoreset-on');
  if (onEl) onEl.classList.toggle('active', enabled);
  const offEl = document.getElementById('wa-panel-autoreset-off');
  if (offEl) offEl.classList.toggle('active', !enabled);
}

// Sync toggle buttons on load
export function _syncPanelAutoResetButtons(): void {
  const onEl = document.getElementById('wa-panel-autoreset-on');
  if (onEl) onEl.classList.toggle('active', _panelAutoReset);
  const offEl = document.getElementById('wa-panel-autoreset-off');
  if (offEl) offEl.classList.toggle('active', !_panelAutoReset);
}
_syncPanelAutoResetButtons();

export function _expandWAPanel(): void {
  if (!_panelAutoReset) return;
  // If collapsed, properly restore via toggle
  if (_aiPanelCollapsed) {
    toggleAiPanel();
    return;
  }
  const panel = $('wa-ai');
  if (!panel) return;
  const gutter = panel.previousElementSibling;
  if (gutter && gutter.classList.contains('gutter') && panel.offsetWidth < 80) {
    try {
      if ((window as any)._waSplit && typeof (window as any)._waSplit.setSizes === 'function') {
        (window as any)._waSplit.setSizes(document.getElementById('workspaceView') ? _EMBEDDED_SPLIT_DEFAULT : _STANDALONE_SPLIT_DEFAULT);
      }
    } catch (e) { console.warn("[Koto]", e) }
  }
}


// ── AI Panel Toggle ─────────────────────────────────────────────────────────
let _aiPanelCollapsed = false;
// Restore collapsed state from localStorage on init
try {
  const saved = localStorage.getItem('wa_ai_panel_collapsed');
  if (saved === '1') _aiPanelCollapsed = true;
} catch {}
// Sync button active state with initial panel state
try {
  const btn = document.getElementById('navAiBtn');
  if (btn && !_aiPanelCollapsed) {
    btn.classList.add('active');
  }
} catch {}
let _aiPanelPrevSizes: number[] | null = null;

function _updateGhostGutter(): void {
  const ai = document.getElementById('wa-ai');
  if (!ai) return;
  const gutter = ai.previousElementSibling;
  if (!gutter || !gutter.classList.contains('gutter')) return;
  if (_aiPanelCollapsed) {
    gutter.classList.add('gutter-hidden');
  } else {
    gutter.classList.remove('gutter-hidden');
  }
}

export function toggleAiPanel(): void {
  const split = (window as any)._waSplit;
  if (!split) return;
  const ai = document.getElementById('wa-ai');
  if (!ai) return;
  const canvas = document.getElementById('wa-canvas');
  const btn = document.getElementById('navAiBtn');

  _aiPanelCollapsed = !_aiPanelCollapsed;

  if (_aiPanelCollapsed) {
    // Save current sizes
    try {
      _aiPanelPrevSizes = split.getSizes();
    } catch (e) {}

    // Hide AI panel and gutter
    ai.style.display = 'none';
    ai.classList.add('wa-ai-collapsed');
    _updateGhostGutter();

    // Expand canvas to fill
    if (canvas) canvas.style.width = '100%';

    if (btn) btn.classList.remove('active');
    if (btn) btn.setAttribute('aria-expanded', 'false');
  } else {
    // Show AI panel
    ai.style.display = '';
    ai.classList.remove('wa-ai-collapsed');
    _updateGhostGutter();

    // Restore canvas
    if (canvas) canvas.style.width = '';

    // Restore split sizes
    const embedded = !!document.getElementById('workspaceView');
    const defaultSizes = embedded ? _EMBEDDED_SPLIT_DEFAULT : _STANDALONE_SPLIT_DEFAULT;
    try {
      if (_aiPanelPrevSizes && _aiPanelPrevSizes.length === (embedded ? 2 : 3)) {
        split.setSizes(_aiPanelPrevSizes);
      } else {
        split.setSizes(defaultSizes);
      }
    } catch (e) {
      split.setSizes(defaultSizes);
    }

    // active class is handled below
    if (btn) btn.classList.add('active');
    if (btn) btn.setAttribute('aria-expanded', 'true');
    _aiPanelPrevSizes = null;
    const showAiChat = (window as any).WA?.showAiChat;
    if (typeof showAiChat === 'function') showAiChat();
  }

  // Update panel close button icon
  const closeBtn = document.getElementById('wa-ai-panel-close');
  if (closeBtn) {
    const svg = closeBtn.querySelector('svg');
    if (svg) {
      svg.innerHTML = _aiPanelCollapsed
        ? '<path d="m9 18 6-6-6-6"/>'
        : '<path d="m15 18-6-6 6-6"/>';
    }
    closeBtn.title = _aiPanelCollapsed ? '展开AI面板' : '折叠AI面板';
    closeBtn.setAttribute('aria-label', closeBtn.title);
  }

  try { localStorage.setItem('wa_ai_panel_collapsed', _aiPanelCollapsed ? '1' : '0'); } catch {}
}

// Apply saved collapsed state on load (call after Split.js is ready)
export function _applySavedAiPanelState(): void {
  if (!_aiPanelCollapsed) return;
  const split = (window as any)._waSplit;
  if (!split) return;
  const ai = document.getElementById('wa-ai');
  if (!ai) return;
  const canvas = document.getElementById('wa-canvas');
  const btn = document.getElementById('navAiBtn');

  try { _aiPanelPrevSizes = split.getSizes(); } catch {}
  ai.style.display = 'none';
  ai.classList.add('wa-ai-collapsed');
  _updateGhostGutter();
  if (canvas) canvas.style.width = '100%';
  if (btn) btn.classList.remove('active');
  if (btn) btn.setAttribute('aria-expanded', 'false');

  // Update close button icon to show expand chevron
  const closeBtn = document.getElementById('wa-ai-panel-close');
  if (closeBtn) {
    const svg = closeBtn.querySelector('svg');
    if (svg) {
      svg.innerHTML = '<path d=\"m9 18 6-6-6-6\"/>';
    }
    closeBtn.title = '展开AI面板';
    closeBtn.setAttribute('aria-label', closeBtn.title);
  }
}

export function isAiPanelCollapsed(): boolean {
  return _aiPanelCollapsed;
}

// ── Backward compat ──
if (typeof window !== 'undefined') {
  (window as any).WA = (window as any).WA || {};
  (window as any).WA.setPanelAutoReset = setPanelAutoReset;
  (window as any).WA._initSplit = _initSplit;
  (window as any).WA.refreshWorkspaceLayout = refreshWorkspaceLayout;
  (window as any).WA.toggleAiPanel = toggleAiPanel;
  (window as any).WA.isAiPanelCollapsed = isAiPanelCollapsed;
  (window as any)._expandWAPanel = _expandWAPanel;
  (window as any)._applySavedAiPanelState = _applySavedAiPanelState;
}
