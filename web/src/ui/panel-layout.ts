/**
 * Shared selection listeners. The document/AI layout belongs to workspace-layout.
 */

import { $ } from '../workspace/infrastructure';
import { state } from '../workspace/state';
import { isDocxMouseDown, setLastSelectionText } from '../shared/selection-runtime';
import {
  _resetDocxSelection,
  _showSelectionToolbarForCurrentSelection,
} from './selection-toolbar';

// ── selectionchange: collapse detection ONLY ─────────────────────────
let _selChangeTimer: any = null;

document.addEventListener('selectionchange', () => {
  if (state.fileType !== 'docx') return;
  clearTimeout(_selChangeTimer);
  _selChangeTimer = setTimeout(() => {
    const _ae = document.activeElement;
    if (_ae?.closest('#wa-ai')) {
      const toolbar = $('wa-selection-toolbar');
      if (toolbar) toolbar.style.display = 'none';
      return; // AI input keeps its pinned selection without reopening the document popup.
    }
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
