/**
 * DOCX/PPTX toolbar bridges - hoverbar formatting, slide operations, shape operations.
 */

import {
  _evtEl,
  _getDocxSelectionPayload,
  _showTableTooltipNear,
  _updateContextBar,
} from './selection-toolbar';
import { $, _csrfFetch, _escHtml } from '../workspace/infrastructure';
import { state as workspaceState } from '../workspace/state';
import { _updateDocxZoomUI } from '../editors/cdn-loaders';
import { getFeatureRegistry, registerFeatures } from '../shared/feature-registry';
import {
  getDocxHoverForceHiddenText,
  getDocxMouseUpY,
  getDocxNativeSelectionBottom,
  getLastSelectionText,
  isDocxMouseDown,
  setDocxHoverForceHiddenText,
  setDocxNativeSelectionBottom,
  setLastSelectionText,
} from '../shared/selection-runtime';
import { isReviewCommentModeEnabled } from '../workspace/docx-review-runtime';
import {
  appendToUiPortal,
  ensureUiPortalRoot,
  getVisualViewportBounds,
  placeFixedInViewport,
  setFixedVisualPosition,
} from '../shared/ui-scale';

// The concrete editor implementations are loaded lazily and expose different
// runtime protocols. Keep that dynamic boundary explicit here while importing
// the shared state from its real module.
export const state: any = workspaceState;
export const workspaceApi: any = getFeatureRegistry();
// Existing toolbar helpers retain this short local name, but it is now the
// canonical workspace API object rather than an ambient browser global.
export const WA = workspaceApi;

let _docxCpEl: HTMLElement | null = null;
let _docxHbEl: HTMLElement | null = null;

export const _CP_COLORS = [
  '#000000','#1f1f1f','#595959','#808080','#a6a6a6','#d9d9d9','#f2f2f2','#ffffff',
  '#c00000','#ff0000','#ff4b4b','#ff6d00','#ff9900','#ffc000','#ffff00','#fff2cc',
  '#375623','#548235','#70ad47','#92d050','#00b050','#008080','#0070c0','#bdd7ee',
  '#1f3864','#2e75b6','#4472c4','#9dc3e6','#7030a0','#984ea3','#c9a0dc','#d9e1f2',
  '#c55a11','#843c0c','#7f1d1d','#002060','#00bcd4','#009688','#4caf50','#607d8b',
];

function _getDocxRibbonToolbar(): HTMLElement | null {
  return document.getElementById('koto-tt-toolbar')
    || document.getElementById('wa-editor-toolbar');
}

function _ensureDocxHoverBar(): HTMLElement | null {
  if (!_docxHbEl || !_docxHbEl.isConnected) {
    _docxHbEl = document.getElementById('wa-docx-hoverbar');
  }
  if (!_docxCpEl || !_docxCpEl.isConnected) {
    _docxCpEl = document.getElementById('wa-docx-cp');
  }
  getFeatureRegistry()._docxHbEl = _docxHbEl;
  getFeatureRegistry()._docxCpEl = _docxCpEl;
  return _docxHbEl;
}

function _hideDocxHoverBar(): void {
  _ensureDocxHoverBar();
  if (_docxHbEl) _docxHbEl.style.display = 'none';
  if (_docxCpEl) _docxCpEl.style.display = 'none';
}

function _syncDocxHoverBar(): void {
  _syncDocxHoverBarFromRibbon();
}

function _resetDocxSelection(): void {
  const reset = getFeatureRegistry()._resetDocxSelection;
  if (typeof reset === 'function') reset();
}

function _updateSubjectBar(fileName: string, fileType: string): void {
  const update = workspaceApi._updateSubjectBar
    || getFeatureRegistry()._updateSubjectBar;
  if (typeof update === 'function') update(fileName, fileType);
}

function _resolveDocxFontFamily(name: string): string {
  return String(name || '').trim();
}

function _getDocxFontFamilyOptionValue(fontName: string, options: any): string {
  const resolved = _resolveDocxFontFamily(fontName);
  const normalized = resolved.toLowerCase();
  const matches = Array.from(options || []) as HTMLOptionElement[];
  const exact = matches.find((option) => String(option.value || '').toLowerCase() === normalized);
  return exact ? exact.value : '';
}

function _getDocxFontDisplayName(fontName: string): string {
  return _resolveDocxFontFamily(fontName).split(',')[0].replace(/^['"]|['"]$/g, '');
}

function _safeGetDocxHdrFtrSelectionInfo(): any {
  const getter = getFeatureRegistry()._getDocxHdrFtrSelectionInfo;
  return typeof getter === 'function' ? getter() : null;
}

export interface RibbonAction {
  cmd: string;
  value?: string;
}

export interface FormatConfig {
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  strike?: boolean;
  fontFamily?: string;
  fontSize?: string;
  color?: string;
  textAlign?: string;
}

export interface ToolbarState {
  visible: boolean;
  left: number;
  top: number;
  width: number;
  height: number;
}

function _boundsFromRects(rects: ArrayLike<DOMRect | ClientRect>, editorLeft = 0): any {
  const items = Array.from(rects || []).filter((rect: any) => {
    return rect && Number.isFinite(rect.top) && Number.isFinite(rect.bottom)
      && (rect.width > 0 || rect.height > 0);
  });
  if (!items.length) return null;
  const top = Math.min(...items.map((rect: any) => rect.top));
  const bottom = Math.max(...items.map((rect: any) => rect.bottom));
  const left = Math.min(...items.map((rect: any) => rect.left));
  const right = Math.max(...items.map((rect: any) => rect.right));
  return {
    top,
    bottom,
    left,
    right,
    centerX: left + ((right - left) / 2),
    editorLeft,
  };
}

export function _getDocxNativeSelectionBounds(pm?: HTMLElement | null, editorLeft = 0): any {
  const selection = window.getSelection && window.getSelection();
  if (!selection || selection.rangeCount <= 0) return null;
  const range = selection.getRangeAt(0);
  if (!range || range.collapsed) return null;
  if (pm) {
    const start = range.startContainer && (range.startContainer.nodeType === Node.ELEMENT_NODE
      ? range.startContainer as Element
      : range.startContainer.parentElement);
    const end = range.endContainer && (range.endContainer.nodeType === Node.ELEMENT_NODE
      ? range.endContainer as Element
      : range.endContainer.parentElement);
    if ((start && !pm.contains(start)) || (end && !pm.contains(end))) return null;
  }
  const rects: DOMRectList | DOMRect[] = range.getClientRects ? range.getClientRects() : [];
  const bounds = _boundsFromRects(rects, editorLeft);
  if (bounds) {
    setDocxNativeSelectionBottom(bounds.bottom);
  }
  return bounds;
}

export function _getDocxSelBounds(ed: any): any {
  const view = ed && ed.view;
  const pm = view && view.dom ? view.dom as HTMLElement : document.querySelector('#wa-docx-editor .ProseMirror') as HTMLElement | null;
  const pmRect = pm && pm.getBoundingClientRect ? pm.getBoundingClientRect() : null;
  const nativeBounds = _getDocxNativeSelectionBounds(pm, pmRect ? pmRect.left : 0);
  if (nativeBounds) return nativeBounds;

  const selection = ed && ed.state && ed.state.selection;
  if (!view || !selection || selection.from >= selection.to || typeof view.coordsAtPos !== 'function') return null;
  try {
    const start = view.coordsAtPos(selection.from);
    const end = view.coordsAtPos(selection.to);
    const left = Math.min(start.left, end.left);
    const right = Math.max(start.right || start.left, end.right || end.left);
    const top = Math.min(start.top, end.top);
    const bottom = Math.max(start.bottom || start.top, end.bottom || end.top);
    return {
      top,
      bottom,
      left,
      right,
      centerX: left + ((right - left) / 2),
      editorLeft: pmRect ? pmRect.left : 0,
    };
  } catch (_) {
    return null;
  }
}

// ── Ribbon dispatch ──────────────────────────────────────────────
export function _dispatchDocxRibbonClick(cmd: string): boolean {
  const ribbon = _getDocxRibbonToolbar();
  const button = ribbon && ribbon.querySelector(`[data-cmd="${cmd}"]`);
  if (!button) return false;
  button.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
  return true;
}

export function _dispatchDocxRibbonSelect(cmd: string, value: string): boolean {
  const ribbon = _getDocxRibbonToolbar();
  const select = ribbon && ribbon.querySelector(`[data-cmd="${cmd}"]`) as HTMLSelectElement;
  if (!select) return false;
  const nextValue = cmd === 'setFontFamily' ? _resolveDocxFontFamily(value) : (value || '');
  if (cmd === 'setFontFamily' && nextValue && !Array.from(select.options).some(option => option.value === nextValue)) {
    return false;
  }
  select.value = nextValue || '';
  select.dispatchEvent(new Event('change', { bubbles: true }));
  return true;
}

export function _syncDocxHoverBarFromRibbon(): boolean {
  const ribbon = _getDocxRibbonToolbar();
  if (!ribbon) return false;

  const buttonMap: Record<string, string> = {
    'wa-dh-bold': 'toggleBold',
    'wa-dh-italic': 'toggleItalic',
    'wa-dh-underline': 'toggleUnderline',
    'wa-dh-strike': 'toggleStrike',
    'wa-dh-align-left': 'setTextAlignLeft',
    'wa-dh-align-center': 'setTextAlignCenter',
    'wa-dh-align-right': 'setTextAlignRight',
  };
  Object.entries(buttonMap).forEach(([hoverId, ribbonCmd]) => {
    const hoverBtn = $(hoverId);
    const ribbonBtn = ribbon.querySelector(`[data-cmd="${ribbonCmd}"]`);
    if (hoverBtn && ribbonBtn) {
      hoverBtn.classList.toggle('active', ribbonBtn.classList.contains('is-active'));
    }
  });

  const fontNameSrc = ribbon.querySelector('[data-cmd="setFontFamily"]') as HTMLSelectElement;
  const fontNameDst = $('wa-dh-fontname') as HTMLSelectElement | HTMLInputElement;
  if (fontNameSrc && fontNameDst) {
    const fontNameValue = fontNameSrc.value || '';
    if (fontNameDst.tagName === 'SELECT') {
      (fontNameDst as HTMLSelectElement).value = _getDocxFontFamilyOptionValue(fontNameValue, (fontNameDst as HTMLSelectElement).options);
    } else {
      (fontNameDst as HTMLInputElement).value = _getDocxFontDisplayName(fontNameValue);
    }
  }

  const fontSizeSrc = ribbon.querySelector('[data-cmd="setFontSize"]') as HTMLSelectElement;
  const fontSizeDst = $('wa-dh-fontsize') as HTMLSelectElement;
  if (fontSizeSrc && fontSizeDst) {
    const raw = fontSizeSrc.value || '';
    const numeric = raw ? String(parseFloat(raw)) : '';
    const match = Array.from(fontSizeDst.options).find(o => parseFloat(o.value) === parseFloat(numeric));
    fontSizeDst.value = match ? match.value : (numeric || '');
  }

  const colorSrc = ribbon.querySelector('#tt-color-swatch') as HTMLElement;
  const colorDst = $('wa-dh-color-swatch');
  if (colorSrc && colorDst) colorDst.style.background = colorSrc.style.background || '#000000';

  const bgSrc = ribbon.querySelector('#tt-bg-swatch') as HTMLElement;
  const bgDst = $('wa-dh-bg-swatch');
  if (bgSrc && bgDst) bgDst.style.background = bgSrc.style.background || 'transparent';

  return true;
}

// ── Show BOTH toolbars ───────────────────────────────────────────
export function _showDocxHoverBar(): void {
  if (state.fileType !== 'docx') return;
  const hb = _ensureDocxHoverBar();
  if (!hb) return;

  const ed = state.activeEditor && state.activeEditor.editor;
  if (!ed) return;
  // Review mode owns the native selection and uses it to position the comment
  // launcher. Exit before the formatting path attempts to normalize or clear
  // a selection that ProseMirror has not mirrored yet.
  if (isReviewCommentModeEnabled()) {
    _hideDocxHoverBar();
    const tt = $('wa-selection-toolbar');
    if (tt) tt.style.display = 'none';
    return;
  }
  const overlaySelection = _safeGetDocxHdrFtrSelectionInfo();
  const docxSelection = overlaySelection ? null : _getDocxSelectionPayload({ includeOverlay: false, allowStaleFallback: false });
  let bounds: any = null;
  let selText = '';
  if (overlaySelection) {
    bounds = overlaySelection.bounds;
    selText = overlaySelection.text;
  } else {
    const sel = ed.state.selection;
    if (docxSelection && docxSelection.kind === 'table' && docxSelection.tableElement) {
      _hideDocxHoverBar();
      _showTableTooltipNear(docxSelection.tableElement);
      setLastSelectionText(docxSelection.rawText);
      const countEl = $('wa-tooltip-count');
      if (countEl) countEl.textContent = docxSelection.countLabel || docxSelection.previewText;
      _updateContextBar({ table: docxSelection.previewText });
      return;
    }
    if (!docxSelection && sel.from >= sel.to) { _resetDocxSelection(); return; }
    bounds = _getDocxSelBounds(ed);
    if (!bounds && docxSelection && docxSelection.tableElement) {
      const rect = docxSelection.tableElement.getBoundingClientRect();
      if (rect && rect.width > 0 && rect.height > 0) {
        bounds = { top: rect.top, bottom: rect.bottom, left: rect.left, centerX: rect.left + (rect.width / 2) };
      }
    }
    if (!bounds) { _hideDocxHoverBar(); return; }
    selText = docxSelection ? docxSelection.rawText : ed.state.doc.textBetween(sel.from, sel.to, ' ').trim();
  }
  if (!selText) { _resetDocxSelection(); return; }

  if (getDocxHoverForceHiddenText() === selText) {
    _hideDocxHoverBar();
    return;
  }

  hb.style.visibility = 'hidden';
  hb.style.display = 'flex';
  const hbRect = hb.getBoundingClientRect();
  const hbW = hbRect.width || 420;
  const hbH = hbRect.height || 34;
  hb.style.visibility = '';

  const ribbonEl = document.getElementById('koto-tt-toolbar')
                || document.getElementById('wa-editor-toolbar');
  let ribbonBottom = 80;
  if (ribbonEl) {
    const rr = ribbonEl.getBoundingClientRect();
    if (rr.height > 0) ribbonBottom = rr.bottom;
  }

  const viewport = getVisualViewportBounds();

  const nativeSelectionBottom = getDocxNativeSelectionBottom();
  const mouseUpY = getDocxMouseUpY();
  const anchorY = bounds.bottom > 0
    ? bounds.bottom
    : (nativeSelectionBottom > 0 ? nativeSelectionBottom : mouseUpY);

  const STACK_GAP = 8;
  const SELECTION_GAP = 2;
  const STACK_RAISE = 85;
  const EDGE_GAP = 6;
  const minTop = Math.max(EDGE_GAP, ribbonBottom + EDGE_GAP);

  const tt = $('wa-selection-toolbar');
  let ttH = 0;
  let ttW = 0;
  if (tt) {
    if (tt.parentElement !== ensureUiPortalRoot()) appendToUiPortal(tt);
    tt.style.visibility = 'hidden';
    tt.style.display = 'flex';
    const ttRect = tt.getBoundingClientRect();
    ttW = ttRect.width || 220;
    ttH = ttRect.height || 36;
    tt.style.visibility = '';
  }

  const stackHeight = hbH + (tt ? ttH + STACK_GAP : 0);
  const maxStackTop = Math.max(minTop, viewport.bottom - stackHeight - EDGE_GAP);
  let stackTop = anchorY + SELECTION_GAP - STACK_RAISE;
  if (stackTop + stackHeight > viewport.bottom - EDGE_GAP) {
    stackTop = bounds.top - stackHeight - SELECTION_GAP;
  }
  stackTop = Math.max(minTop, Math.min(stackTop, maxStackTop));

  if (tt) {
    const aiTop = stackTop;
    const aiLeft = Math.max(viewport.left + 8, Math.min(bounds.left, viewport.right - ttW - 8));
    setFixedVisualPosition(tt, aiLeft, aiTop);
  }

  let fmtTop = stackTop + (tt ? ttH + STACK_GAP : 0);
  let fmtLeft = bounds.left;
  fmtTop = Math.max(minTop, Math.min(fmtTop, viewport.bottom - hbH - EDGE_GAP));
  fmtLeft = Math.max(viewport.left + 4, Math.min(fmtLeft, viewport.right - hbW - 4));

  setFixedVisualPosition(hb, fmtLeft, fmtTop);

  _syncDocxHoverBar();

  if (selText) {
    setLastSelectionText(selText);
    const countEl = $('wa-tooltip-count');
    if (countEl) {
      countEl.textContent = docxSelection && docxSelection.countLabel
        ? docxSelection.countLabel
        : `${selText.replace(/\s/g, '').length}\u5b57`;
    }
    if (docxSelection && docxSelection.kind !== 'text') {
      _updateContextBar({ table: docxSelection.previewText });
    } else {
      _updateContextBar({ selection: selText });
    }
  }
}

// ── TipTap callback ───────────────────────────────────────────────
export function _kotoDocxSelectionChanged(): void {
  if (state.fileType !== 'docx') return;
  const _docxSelTimer = (state as any)._docxSelTimer;
  clearTimeout(_docxSelTimer);
  (state as any)._docxSelTimer = setTimeout(() => {
    const ed = state.activeEditor && state.activeEditor.editor;
    if (!ed) return;
    const overlaySelection = _safeGetDocxHdrFtrSelectionInfo();
    const docxSelection = _getDocxSelectionPayload({ includeOverlay: false, allowStaleFallback: false });
    if (!overlaySelection && !docxSelection) {
      // Clear stale toolbar selection to prevent phantom reappearances
      if (state.activeEditor && state.activeEditor._toolbarSelection) {
        state.activeEditor._toolbarSelection = null;
      }
      _resetDocxSelection();
    } else if (!isDocxMouseDown(state)) {
      // _showDocxHoverBar handles both the formatting hoverbar and the
      // quick-assistant selection toolbar (快捷助手) as a stacked layout.
      _showDocxHoverBar();
    }
  }, 50);
}

// ── DOCX Hoverbar format ──────────────────────────────────────────
export function docxHoverFmt(prop: string): void {
  const ribbonCmdMap: Record<string, string> = {
    bold: 'toggleBold',
    italic: 'toggleItalic',
    underline: 'toggleUnderline',
    strike: 'toggleStrike',
    justifyLeft: 'setTextAlignLeft',
    justifyCenter: 'setTextAlignCenter',
    justifyRight: 'setTextAlignRight',
    justify: 'setTextAlignJustify',
    clearMarks: 'unsetAllMarks',
  };
  if (ribbonCmdMap[prop] && _dispatchDocxRibbonClick(ribbonCmdMap[prop])) {
    _syncDocxHoverBar();
    return;
  }

  const ed = state.activeEditor && state.activeEditor.editor;
  if (!ed) return;
  switch (prop) {
    case 'bold':          ed.chain().focus().toggleBold().run(); break;
    case 'italic':        ed.chain().focus().toggleItalic().run(); break;
    case 'underline':     ed.chain().focus().toggleUnderline().run(); break;
    case 'strike':        ed.chain().focus().toggleStrike().run(); break;
    case 'superscript':   ed.chain().focus().toggleSuperscript().run(); break;
    case 'subscript':     ed.chain().focus().toggleSubscript().run(); break;
    case 'justifyLeft':   ed.chain().focus().setTextAlign('left').run(); break;
    case 'justifyCenter': ed.chain().focus().setTextAlign('center').run(); break;
    case 'justifyRight':  ed.chain().focus().setTextAlign('right').run(); break;
    case 'justify':       ed.chain().focus().setTextAlign('justify').run(); break;
    case 'indent':
      if (ed.can().sinkListItem('listItem')) { ed.chain().focus().sinkListItem('listItem').run(); }
      else { ed.chain().focus().indent().run(); }
      break;
    case 'outdent':
      if (ed.can().liftListItem('listItem')) { ed.chain().focus().liftListItem('listItem').run(); }
      else { ed.chain().focus().outdent().run(); }
      break;
    case 'clearMarks':    ed.chain().focus().unsetAllMarks().run(); break;
  }
  _syncDocxHoverBar();
}

export function docxInsertLink(): void {
  const ed = state.activeEditor && state.activeEditor.editor;
  if (!ed) return;
  const existing = (ed.getAttributes('link') || {}).href || '';
  const url = window.prompt('\u8bf7\u8f93\u5165\u94fe\u63a5\u5730\u5740 (URL):', existing);
  if (url === null) return;
  if (url.trim() === '') {
    ed.chain().focus().unsetLink().run();
  } else {
    const href = /^https?:\/\//i.test(url.trim()) ? url.trim() : 'https://' + url.trim();
    ed.chain().focus().setLink({ href, target: '_blank' }).run();
  }
  _syncDocxHoverBar();
}

export function docxHoverFontFamily(name: string): void {
  const value = _resolveDocxFontFamily(name.trim());
  if (_dispatchDocxRibbonSelect('setFontFamily', value)) {
    _syncDocxHoverBar();
    return;
  }

  const ed = state.activeEditor && state.activeEditor.editor;
  if (!ed) return;
  if (!value) {
    ed.chain().focus().unsetFontFamily().run();
    return;
  }
  ed.chain().focus().setFontFamily(value).run();
}

export function docxHoverFontSize(size: string): void {
  if (_dispatchDocxRibbonSelect('setFontSize', size ? `${parseFloat(size)}pt` : '')) {
    _syncDocxHoverBar();
    return;
  }

  const ed = state.activeEditor && state.activeEditor.editor;
  if (!ed || !size) return;
  const sz = parseFloat(size);
  if (isNaN(sz) || sz <= 0) return;
  ed.chain().focus().setFontSize(sz + 'pt').run();
}

export function docxColorPicker(type: string, triggerEl?: HTMLElement): void {
  _ensureDocxHoverBar();
  const palette = _docxCpEl;
  const grid = palette ? palette.querySelector('#wa-docx-cp-grid') : null;
  if (!palette || !grid) return;
  if (palette.style.display !== 'none' && palette.dataset.cpType === type) {
    palette.style.display = 'none'; return;
  }
  palette.dataset.cpType = type;
  grid.innerHTML = _CP_COLORS.map((c: string) =>
    `<div title="${c}" style="width:18px;height:18px;border-radius:3px;background:${c};cursor:pointer;border:1px solid rgba(255,255,255,.12);box-sizing:border-box"` +
    ` data-wa-toolbar-color="docx" data-color="${c}"></div>`
  ).join('');
  if (triggerEl) {
    const r = triggerEl.getBoundingClientRect();
    palette.style.visibility = 'hidden';
    palette.style.display = 'block';
    placeFixedInViewport(palette, r.left, r.bottom + 4, 4);
    palette.style.visibility = '';
    return;
  }
  palette.style.display = 'block';
}

export function _docxPickColor(color: string, keepOpen?: boolean): void {
  const palette = _docxCpEl;
  const type = palette ? palette.dataset.cpType : '';
  if (typeof getFeatureRegistry()._ttPickColor === 'function') {
    getFeatureRegistry()._ttPickColor(color, keepOpen);
    _syncDocxHoverBar();
    const hexEl = $('wa-docx-cp-hex');
    if (hexEl) hexEl.textContent = color;
    const ci = $('wa-docx-cp-custom') as HTMLInputElement;
    if (ci && /^#[0-9a-f]{6}$/i.test(color)) ci.value = color;
    if (!keepOpen && palette) palette.style.display = 'none';
    return;
  }

  const ed = state.activeEditor && state.activeEditor.editor;
  if (ed) {
    if (type === 'font') {
      ed.chain().focus().setColor(color).run();
      const sw = $('wa-dh-color-swatch');
      if (sw) sw.style.background = color;
    } else if (type === 'bg') {
      ed.chain().focus().toggleHighlight({ color }).run();
      const sw = $('wa-dh-bg-swatch');
      if (sw) sw.style.background = color;
    }
  }
  const hexEl = $('wa-docx-cp-hex');
  if (hexEl) hexEl.textContent = color;
  const ci = $('wa-docx-cp-custom') as HTMLInputElement;
  if (ci && /^#[0-9a-f]{6}$/i.test(color)) ci.value = color;
  if (!keepOpen && palette) palette.style.display = 'none';
}

export function closeDocxHoverBar(): void {
  setDocxHoverForceHiddenText(getLastSelectionText() || (window.getSelection()?.toString().trim() || ''));
  _resetDocxSelection();
}


// ── Header / Footer overlay selection helper ──────────────────────
// Provides the selection text + viewport bounds for the currently active
// header/footer overlay so the hoverbar and selection toolbar can show
// quick actions (润色/翻译/解释 etc.) on header/footer content.
function _buildHdrFtrSelectionInfo(): { text: string; bounds: any } | null {
  const overlay = document.querySelector('#wa-docx-editor .koto-hdrftr-overlay.is-active');
  if (!overlay) return null;
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
  const range = sel.getRangeAt(0);
  if (!overlay.contains(range.commonAncestorContainer)) return null;
  const text = sel.toString().trim();
  if (!text) return null;
  const rects = range.getClientRects();
  let top = Infinity, bottom = -Infinity, left = Infinity, right = -Infinity;
  for (let i = 0; i < rects.length; i++) {
    const r = rects[i];
    if (r.height <= 0 || r.width <= 0) continue;
    if (r.top < top) top = r.top;
    if (r.bottom > bottom) bottom = r.bottom;
    if (r.left < left) left = r.left;
    if (r.right > right) right = r.right;
  }
  if (top === Infinity) {
    const br = range.getBoundingClientRect();
    if (!br || br.height <= 0) return null;
    return { text, bounds: { top: br.top, bottom: br.bottom, left: br.left, right: br.right, centerX: br.left + br.width / 2 } };
  }
  return { text, bounds: { top, bottom, left, right, centerX: (left + right) / 2 } };
}import { _pptxPickColor, _sendImageToAI, docxZoom, pptxAddSlide, pptxAlign, pptxApplyQuickLayout, pptxBgColor, pptxBorderWidth, pptxChangeBgImage, pptxClearFormat, pptxColorPicker, pptxDelShape, pptxDelSlide, pptxDownload, pptxDupSlide, pptxFmt, pptxFontColor, pptxFontName, pptxFontSize, pptxHighlightColor, pptxIndent, pptxInsertImageClick, pptxInsertImageFile, pptxInsertMode, pptxInsertShape, pptxLineSpacing, pptxNav, pptxOpacity, pptxRedo, pptxRemoveBg, pptxSave, pptxSetBgImage, pptxSetShapePos, pptxSetShapeRot, pptxSetShapeSize, pptxShapeBorder, pptxShapeFill, pptxStepFont, pptxSwitchTab, pptxToggleBullet, pptxToggleNumbered, pptxUndo, pptxVertAlign, pptxZOrder, pptxZoom } from './pptx-toolbar-actions';
export * from './pptx-toolbar-actions';


let toolbarColorDelegationInstalled = false;

function _installToolbarColorDelegation(): void {
  if (toolbarColorDelegationInstalled) return;
  toolbarColorDelegationInstalled = true;
  document.addEventListener('pointerdown', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest('[data-wa-toolbar-color]')) event.preventDefault();
  }, true);
  document.addEventListener('click', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const swatch = target?.closest<HTMLElement>('[data-wa-toolbar-color]');
    if (!swatch) return;
    const color = String(swatch.dataset.color || '').trim();
    if (!color) return;
    event.preventDefault();
    event.stopPropagation();
    if (swatch.dataset.waToolbarColor === 'docx') _docxPickColor(color);
    else if (swatch.dataset.waToolbarColor === 'pptx') _pptxPickColor(color);
  }, true);
}

_installToolbarColorDelegation();

registerFeatures({
  docxHoverFmt, docxInsertLink, docxHoverFontFamily, docxHoverFontSize,
  docxColorPicker, _docxPickColor, closeDocxHoverBar,
  pptxShapeFill, pptxShapeBorder, pptxBorderWidth, pptxDupSlide, pptxStepFont,
  pptxClearFormat, pptxAddSlide, pptxDelSlide, pptxInsertShape, pptxSetShapeSize,
  pptxSetShapePos, pptxSetShapeRot, pptxHighlightColor, pptxApplyQuickLayout,
  pptxChangeBgImage, pptxBgColor, pptxSetBgImage, pptxRemoveBg, pptxFmt,
  pptxAlign, pptxFontSize, pptxFontName, pptxFontColor, pptxColorPicker,
  _pptxPickColor, pptxIndent, pptxLineSpacing, pptxToggleBullet,
  pptxToggleNumbered, pptxVertAlign, pptxOpacity, pptxZOrder, pptxZoom, pptxNav,
  docxZoom, pptxInsertImageClick, pptxInsertImageFile, pptxDelShape, pptxSwitchTab,
  pptxInsertMode, pptxSave, pptxUndo, pptxRedo, pptxDownload, _sendImageToAI,
  _getDocxSelBounds, _getDocxNativeSelectionBounds,
});

if (typeof window !== 'undefined') {
  getFeatureRegistry()._getDocxSelBounds = _getDocxSelBounds;
  getFeatureRegistry()._getDocxNativeSelectionBounds = _getDocxNativeSelectionBounds;
getFeatureRegistry()._getDocxHdrFtrSelectionInfo = _buildHdrFtrSelectionInfo;
  getFeatureRegistry()._kotoDocxSelectionChanged = _kotoDocxSelectionChanged;
}
