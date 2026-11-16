// @ts-nocheck
/**
 * File System Browser — Tree rendering, search, browse, live polling, file loader.
 * Workspace file tree.
 */

import { _fileIcon, _escHtml, _FOLDER_OPEN_SVG, _FOLDER_PICK_SVG, _FOLDER_SVG } from './infrastructure';
import { state, _forgetRecentPath, _trackUserOpen } from './state';
import { getFeatureRegistry } from '../shared/feature-registry';
import {
  entrySearchCategory as _entrySearchCategory,
  flattenWorkspaceListFiles as _flattenWorkspaceListFiles,
  formatFileSize as _formatSize,
  isSupportedExtension as _isSupportedExt,
  joinWorkspacePath as _joinWorkspacePath,
  mergeSearchResults as _mergeSearchResults,
} from './fs-tree-helpers';
import { _attachBrowserFileToAI } from './fs-tree';

let _browserPointerDrag: {
  path: string;
  supported: boolean;
  el: HTMLElement;
  startX: number;
  startY: number;
  active: boolean;
} | null = null;
export let _suppressBrowserRowClickUntil = 0;

export function _suppressBrowserRowClickFor(milliseconds: number): void {
  _suppressBrowserRowClickUntil = Date.now() + Math.max(0, milliseconds);
}

export function _isAiSessionListVisible(): boolean {
  const listView = document.getElementById('wa-ai-session-list-view');
  return !!listView && !listView.hidden;
}

export function _focusVisibleAIComposer(): void {
  const input = document.getElementById('wa-user-input') as HTMLInputElement | null;
  if (input) setTimeout(() => input.focus(), 120);
}

export function _isPointInsideAIPanel(x: number, y: number): boolean {
  const target = document.elementFromPoint(x, y) as HTMLElement | null;
  if (target && target.closest('#wa-ai, #wa-ai-session-list-composer, #wa-ai-input-area, #wa-ai-file-drop')) return true;
  const aiPanel = document.getElementById('wa-ai');
  if (!aiPanel) return false;
  const rect = aiPanel.getBoundingClientRect();
  return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
}

function _endBrowserPointerDrag(): void {
  if (_browserPointerDrag && _browserPointerDrag.el) _browserPointerDrag.el.classList.remove('dragging');
  _browserPointerDrag = null;
  document.body.classList.remove('wa-file-dragging');
}

function _isBrowserFileActionTarget(target: EventTarget | null): boolean {
  const el = target instanceof Element ? target : null;
  return !!(el && el.closest('.wa-file-actions, .wa-file-check, input, select, textarea, a'));
}

export function _startBrowserPointerDrag(event: MouseEvent | PointerEvent, el: HTMLElement): void {
  if (!el || event.button !== 0 || state.selectMode) return;
  if (_isBrowserFileActionTarget(event.target)) return;
  const path = String(el.dataset.path || '').trim();
  if (!path) return;
  _browserPointerDrag = {
    path,
    supported: el.dataset.supported !== 'false',
    el,
    startX: event.clientX,
    startY: event.clientY,
    active: false,
  };
}

function _onBrowserPointerMove(event: MouseEvent | PointerEvent): void {
  const drag = _browserPointerDrag;
  if (!drag) return;
  if (!drag.active) {
    const dx = event.clientX - drag.startX;
    const dy = event.clientY - drag.startY;
    if (Math.sqrt(dx * dx + dy * dy) < 8) return;
    drag.active = true;
    drag.el.classList.add('dragging');
    document.body.classList.add('wa-file-dragging');
  }
}

async function _onBrowserPointerUp(event: MouseEvent | PointerEvent): Promise<void> {
  const drag = _browserPointerDrag;
  if (!drag) return;
  const shouldAttach = drag.active && drag.supported && _isPointInsideAIPanel(event.clientX, event.clientY);
  _endBrowserPointerDrag();
  if (!shouldAttach) return;
  event.preventDefault();
  event.stopPropagation();
  _suppressBrowserRowClickUntil = Date.now() + 450;
  await _attachBrowserFileToAI(drag.path, 'file_tree_pointer_drop');
}

export function _installBrowserPointerDragFallback(): void {
  if (getFeatureRegistry()._waBrowserPointerDragFallbackInstalled) return;
  getFeatureRegistry()._waBrowserPointerDragFallbackInstalled = true;
  document.addEventListener('mousemove', (event) => _onBrowserPointerMove(event));
  document.addEventListener('pointermove', (event) => _onBrowserPointerMove(event));
  document.addEventListener('mouseup', (event) => {
    _onBrowserPointerUp(event).catch((error) => {
      console.warn('[WA] file pointer drop failed:', error);
      _endBrowserPointerDrag();
    });
  }, true);
  document.addEventListener('pointerup', (event) => {
    _onBrowserPointerUp(event).catch((error) => {
      console.warn('[WA] file pointer drop failed:', error);
      _endBrowserPointerDrag();
    });
  }, true);
}
