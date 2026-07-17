/**
 * Panel Layout & Selection — selectionchange handler, Split.js init, panel auto-reset.
 * Workspace panel layout.
 */

import { $ } from '../workspace/infrastructure';
import { state } from '../workspace/state';
import { getWorkspaceApi, publishWorkspaceApi } from '../shared/workspace-api';
import { isDocxMouseDown, setLastSelectionText } from '../shared/selection-runtime';
import {
  _resetDocxSelection,
  _showSelectionToolbarForCurrentSelection,
} from './selection-toolbar';

const WA = getWorkspaceApi();

// ── selectionchange: collapse detection ONLY ─────────────────────────
let _selChangeTimer: any = null;

document.addEventListener('selectionchange', () => {
  if (state.fileType !== 'docx') return;
  clearTimeout(_selChangeTimer);
  _selChangeTimer = setTimeout(() => {
    const _ae = document.activeElement;
    if (_ae && (_ae.closest('#wa-selection-toolbar') || _ae.closest('#wa-docx-hoverbar') || _ae.closest('#wa-docx-cp') || _ae.closest('#wa-review-shell') || _ae.closest('#wa-review-selection-launcher'))) return;
    if (isDocxMouseDown(state) && document.querySelector('#wa-selection-toolbar:hover, #wa-docx-hoverbar:hover, #wa-review-shell:hover, #wa-review-selection-launcher:hover')) return;
    const _ws = window.getSelection();
    if (_ws && !_ws.isCollapsed && _ws.rangeCount) {
      _showSelectionToolbarForCurrentSelection();
      return;
    }
    if (!_ws || _ws.isCollapsed || !_ws.rangeCount) {
      _resetDocxSelection();
    }
  }, 80);
});

// Hide selection toolbar on scroll
document.addEventListener('scroll', () => {
  const tt = $('wa-selection-toolbar');
  if (tt) tt.style.display = 'none';
  if (state.fileType === 'docx') _resetDocxSelection();
  else setLastSelectionText('');
}, true);

const _waAiMsgs = $('wa-ai-messages');
if (_waAiMsgs) {
  _waAiMsgs.addEventListener('wheel', () => {
    const tt = $('wa-selection-toolbar');
    if (tt && tt.style.display !== 'none') {
      tt.style.display = 'none';
      setLastSelectionText('');
    }
  }, { passive: true });
}

document.addEventListener('wheel', () => {
  const tt = $('wa-selection-toolbar');
  if (tt && tt.style.display !== 'none') {
    tt.style.display = 'none';
    setLastSelectionText('');
  }
}, { passive: true, capture: true });

// ── Split.js Init ────────────────────────────────────────────────────────────
const _SPLIT_DEFAULT = [15, 53, 32];
// The composer has model controls, attachment actions, and a task stream.  A
// narrow persisted Split.js size turns it into an unusable clipped rail.
const _EMBEDDED_AI_MIN_WIDTH = 420;
const _SPLIT_MIN_WIDTHS = [150, 400, _EMBEDDED_AI_MIN_WIDTH] as const;
const _SPLIT_LAYOUT_STORAGE = 'wa_split_sizes_embedded_v3';
const _LEGACY_SPLIT_LAYOUT_STORAGE = [
  'wa_split_sizes',
  'wa_split_sizes_v2',
  'wa_split_sizes_embedded',
  'wa_split_sizes_embedded_v2',
];

function _readStorage(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}

function _writeStorage(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* Storage is optional. */ }
}

function _removeStorage(key: string): void {
  try { localStorage.removeItem(key); } catch { /* Storage is optional. */ }
}

function _retireLegacySplitLayouts(): void {
  _LEGACY_SPLIT_LAYOUT_STORAGE.forEach(_removeStorage);
}

function _isUsableSplitSizes(value: unknown, expectedLength: number): value is number[] {
  return Array.isArray(value)
    && value.length === expectedLength
    && value.every((size) => Number.isFinite(size) && size > 0)
    && Math.abs(value.reduce((total, size) => total + size, 0) - 100) < 1;
}

function _persistSplitSizes(sizes: unknown): void {
  if (!_isUsableSplitSizes(sizes, 3)) return;
  _writeStorage(_SPLIT_LAYOUT_STORAGE, JSON.stringify(sizes));
}

function _setSplitDragging(dragging: boolean): void {
  document.body?.classList.toggle('wa-workspace-split-dragging', dragging);
}

function _clearSplitDragging(): void {
  _setSplitDragging(false);
}

function _cancelActiveSplitDrag(): void {
  const split = (window as any)._waSplit;
  if (Array.isArray(split?.pairs)) {
    split.pairs.forEach((pair: any) => {
      if (pair?.dragging && typeof pair.stop === 'function') {
        try { pair.stop(); } catch { /* Always clear the visual state below. */ }
      }
    });
  }
  _clearSplitDragging();
}

window.addEventListener('blur', _cancelActiveSplitDrag);
window.addEventListener('mouseup', _clearSplitDragging, true);
window.addEventListener('touchend', _clearSplitDragging, true);
window.addEventListener('touchcancel', _cancelActiveSplitDrag, true);
document.addEventListener('visibilitychange', () => {
  if (document.hidden) _cancelActiveSplitDrag();
});

function _workspaceGutterCount(workspace: HTMLElement): number {
  return Array.from(workspace.children).filter((child) => child.classList.contains('gutter')).length;
}

function _hasLiveSplitInstance(workspace: HTMLElement): boolean {
  const split = (window as any)._waSplit;
  return !!split
    && typeof split.getSizes === 'function'
    && typeof split.setSizes === 'function'
    && split.parent === workspace
    && _workspaceGutterCount(workspace) === 2;
}

function _discardStaleSplitInstance(workspace: HTMLElement): void {
  const split = (window as any)._waSplit;
  try { split?.destroy?.(); } catch { /* Remove orphan gutters below. */ }
  Array.from(workspace.children).forEach((child) => {
    if (child.classList.contains('gutter')) child.remove();
  });
  (window as any)._waSplit = null;
  _clearSplitDragging();
}

function _enforceEmbeddedAiWidth(
  left: HTMLElement,
  canvas: HTMLElement,
  ai: HTMLElement,
): void {
  const split = (window as any)._waSplit;
  if (!split || ai.offsetWidth >= _EMBEDDED_AI_MIN_WIDTH) return;
  const splitWidth = left.offsetWidth + canvas.offsetWidth + ai.offsetWidth;
  const minimumWidth = _SPLIT_MIN_WIDTHS.reduce((total, width) => total + width, 0);
  if (splitWidth < minimumWidth) return;

  const aiPercent = Math.min(50, Math.max(
    _SPLIT_DEFAULT[2],
    (_EMBEDDED_AI_MIN_WIDTH / splitWidth) * 100,
  ));
  const currentSizes = typeof split.getSizes === 'function' ? split.getSizes() : null;
  const requestedLeftPercent = _isUsableSplitSizes(currentSizes, 3)
    ? currentSizes[0]
    : _SPLIT_DEFAULT[0];
  const leftMinPercent = (_SPLIT_MIN_WIDTHS[0] / splitWidth) * 100;
  const canvasMinPercent = (_SPLIT_MIN_WIDTHS[1] / splitWidth) * 100;
  const leftPercent = Math.min(
    100 - aiPercent - canvasMinPercent,
    Math.max(leftMinPercent, requestedLeftPercent),
  );
  const sizes = [leftPercent, 100 - leftPercent - aiPercent, aiPercent];
  try {
    split.setSizes(sizes);
    _persistSplitSizes(sizes);
  } catch (e) { console.warn('[Koto] unable to restore AI panel width', e); }
}

export function _initSplit(): void {
  const workspace = $('wa-workspace');
  const left = $('wa-left'), canvas = $('wa-canvas'), ai = $('wa-ai');
  if (!document.getElementById('workspaceView') || !workspace || !left || !canvas || !ai) return;
  if (_hasLiveSplitInstance(workspace)) return;
  if ((window as any)._waSplit || _workspaceGutterCount(workspace) > 0) {
    _discardStaleSplitInstance(workspace);
  }
  const splitFactory = (window as any).Split;
  if (typeof splitFactory !== 'function') {
    console.error('[Koto] workspace split runtime is unavailable');
    return;
  }
  _retireLegacySplitLayouts();
  let savedSizes: number[] | null = null;
  try {
    const raw = _readStorage(_SPLIT_LAYOUT_STORAGE);
    const parsed = raw ? JSON.parse(raw) : null;
    savedSizes = _isUsableSplitSizes(parsed, 3) ? parsed : null;
  } catch (e) { console.warn("[Koto]", e) }

  const targets = ['#wa-left', '#wa-canvas', '#wa-ai'];
  (window as any)._waSplit = splitFactory(targets, {
    sizes: savedSizes || _SPLIT_DEFAULT,
    // The canvas may shrink below the preferred 420px at high UI scales.
    // The AI composer remains protected at 420px; keeping both floors at
    // 420px made their combined minimum wider than a zoom-adjusted viewport.
    minSize: [..._SPLIT_MIN_WIDTHS],
    gutterSize: 6,
    snapOffset: 0,
    onDragStart() {
      _setSplitDragging(true);
    },
    onDragEnd(sizes: number[]) {
      _clearSplitDragging();
      _persistSplitSizes(sizes);
    }
  });
  requestAnimationFrame(() => {
    _enforceEmbeddedAiWidth(left, canvas, ai);
    _applySavedAiPanelState();
  });
}

export function refreshWorkspaceLayout(): void {
  const split = (window as any)._waSplit;
  if (!split || typeof split.getSizes !== 'function' || typeof split.setSizes !== 'function') return;
  requestAnimationFrame(() => {
    try {
      const sizes = split.getSizes();
      if (Array.isArray(sizes) && sizes.length) split.setSizes(sizes);
    } catch (error) { console.warn('[Koto] unable to reflow workspace layout', error); }

    const left = $('wa-left');
    const canvas = $('wa-canvas');
    const ai = $('wa-ai');
    if (left && canvas && ai) {
      _enforceEmbeddedAiWidth(left, canvas, ai);
    }
  });
}

// ── Panel auto-reset setting ─────────────────────────────────────────────────
let _panelAutoReset: boolean = _readStorage('wa_panel_autoreset') !== 'off';

export function setPanelAutoReset(enabled: boolean): void {
  _panelAutoReset = enabled;
  _writeStorage('wa_panel_autoreset', enabled ? 'on' : 'off');
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
        (window as any)._waSplit.setSizes(_SPLIT_DEFAULT);
      }
    } catch (e) { console.warn("[Koto]", e) }
  }
}


// ── AI Panel Toggle ─────────────────────────────────────────────────────────
let _aiPanelCollapsed = false;
// Restore collapsed state from localStorage on init
try {
  const saved = _readStorage('wa_ai_panel_collapsed');
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
    try {
      if (_aiPanelPrevSizes && _aiPanelPrevSizes.length === 3) {
        split.setSizes(_aiPanelPrevSizes);
      } else {
        split.setSizes(_SPLIT_DEFAULT);
      }
    } catch (e) {
      split.setSizes(_SPLIT_DEFAULT);
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

  _writeStorage('wa_ai_panel_collapsed', _aiPanelCollapsed ? '1' : '0');
}

// Apply saved collapsed state on load (call after Split.js is ready)
function _applySavedAiPanelState(): void {
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

// Publish only the cross-bundle UI actions that still have live callers.
if (typeof window !== 'undefined') {
  publishWorkspaceApi({
    setPanelAutoReset,
    refreshWorkspaceLayout,
    toggleAiPanel,
    _expandWAPanel,
  });
}
