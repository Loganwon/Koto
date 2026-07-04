/**
 * Panel Layout & Selection — selectionchange handler, Split.js init, panel auto-reset.
 * Workspace panel layout.
 */

declare function $(id: string): HTMLElement | null;
declare var state: any;
declare var WA: any;
declare var lastSelectionText: string;
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
const _savedSplitSizes: number[] | null = (() => {
  try { const s = localStorage.getItem('wa_split_sizes'); return s ? JSON.parse(s) : null; } catch { return null; }
})();

export function _initSplit(): void {
  if ((window as any)._waSplit) return;
  const left = $('wa-left'), canvas = $('wa-canvas'), ai = $('wa-ai');
  const embedded = !!document.getElementById('workspaceView');
  if (!canvas || !ai || (!embedded && !left)) return;
  const splitKey = embedded ? 'wa_split_sizes_embedded' : 'wa_split_sizes';
  let savedSizes: number[] | null = null;
  try {
    const raw = localStorage.getItem(splitKey);
    savedSizes = raw ? JSON.parse(raw) : null;
  } catch (_) {}

  const targets = embedded ? ['#wa-canvas', '#wa-ai'] : ['#wa-left', '#wa-canvas', '#wa-ai'];
  (window as any)._waSplit = (window as any).Split(targets, {
    sizes: savedSizes || (embedded ? [68, 32] : (_savedSplitSizes || [15, 55, 30])),
    minSize: embedded ? [420, 280] : [150, 400, 250],
    gutterSize: 6,
    snapOffset: 0,
    onDragEnd(sizes: number[]) {
      try { localStorage.setItem(splitKey, JSON.stringify(sizes)); } catch {}
    }
  });
}

// Standalone page: init immediately; embedded mode defers to openInMainView().
if (!document.getElementById('workspaceView')) {
  _initSplit();
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
  const panel = $('wa-ai');
  if (!panel) return;
  const gutter = panel.previousElementSibling;
  if (gutter && gutter.classList.contains('gutter') && panel.offsetWidth < 80) {
    try {
      if ((window as any)._waSplit && typeof (window as any)._waSplit.setSizes === 'function') {
        (window as any)._waSplit.setSizes(document.getElementById('workspaceView') ? [68, 32] : [15, 55, 30]);
      }
    } catch (_) {}
  }
}

// ── Backward compat ──
if (typeof window !== 'undefined') {
  (window as any).WA = (window as any).WA || {};
  (window as any).WA.setPanelAutoReset = setPanelAutoReset;
  (window as any).WA._initSplit = _initSplit;
  (window as any)._expandWAPanel = _expandWAPanel;
}
