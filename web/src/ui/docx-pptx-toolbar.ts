/**
 * DOCX/PPTX toolbar bridges - hoverbar formatting, slide operations, shape operations.
 */

import {
  _evtEl,
  _getDocxSelectionPayload,
  _showTableTooltipNear,
  _updateContextBar,
} from './selection-toolbar';
import { $, _csrfFetch, _escHtml, showToast } from '../workspace/infrastructure';
import { state as workspaceState } from '../workspace/state';
import { _updateDocxZoomUI } from '../editors/cdn-loaders';
import { getWorkspaceApi, publishWorkspaceApi } from '../shared/workspace-api';
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

// The concrete editor implementations are loaded lazily and expose different
// runtime protocols. Keep that dynamic boundary explicit here while importing
// the shared state from its real module.
const state: any = workspaceState;
const workspaceApi: any = getWorkspaceApi();
// Existing toolbar helpers retain this short local name, but it is now the
// canonical workspace API object rather than an ambient browser global.
const WA = workspaceApi;

let _docxCpEl: HTMLElement | null = null;
let _docxHbEl: HTMLElement | null = null;

const _CP_COLORS = [
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
  (window as any)._docxHbEl = _docxHbEl;
  (window as any)._docxCpEl = _docxCpEl;
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
  const reset = (window as any)._resetDocxSelection;
  if (typeof reset === 'function') reset();
}

function _updateSubjectBar(fileName: string, fileType: string): void {
  const update = workspaceApi._updateSubjectBar
    || (window as any)._updateSubjectBar;
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
  const getter = (window as any)._getDocxHdrFtrSelectionInfo;
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
  const hbW = hb.offsetWidth || 420;
  const hbH = hb.offsetHeight || 34;
  hb.style.visibility = '';

  const ribbonEl = document.getElementById('koto-tt-toolbar')
                || document.getElementById('wa-editor-toolbar');
  let ribbonBottom = 80;
  if (ribbonEl) {
    const rr = ribbonEl.getBoundingClientRect();
    if (rr.height > 0) ribbonBottom = rr.bottom;
  }

  const vh = window.innerHeight;
  const vw = window.innerWidth;

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
    if (tt.parentElement !== document.body) document.body.appendChild(tt);
    tt.style.visibility = 'hidden';
    tt.style.display = 'flex';
    ttW = tt.offsetWidth || 220;
    ttH = tt.offsetHeight || 36;
    tt.style.visibility = '';
  }

  const stackHeight = hbH + (tt ? ttH + STACK_GAP : 0);
  const maxStackTop = Math.max(minTop, vh - stackHeight - EDGE_GAP);
  let stackTop = anchorY + SELECTION_GAP - STACK_RAISE;
  if (stackTop + stackHeight > vh - EDGE_GAP) {
    stackTop = bounds.top - stackHeight - SELECTION_GAP;
  }
  stackTop = Math.max(minTop, Math.min(stackTop, maxStackTop));

  if (tt) {
    const aiTop = stackTop;
    const aiLeft = Math.max(8, Math.min(bounds.left, vw - ttW - 8));
    tt.style.left = aiLeft + 'px';
    tt.style.top = aiTop + 'px';
  }

  let fmtTop = stackTop + (tt ? ttH + STACK_GAP : 0);
  let fmtLeft = bounds.left;
  fmtTop = Math.max(minTop, Math.min(fmtTop, vh - hbH - EDGE_GAP));
  fmtLeft = Math.max(4, Math.min(fmtLeft, vw - hbW - 4));

  hb.style.left = fmtLeft + 'px';
  hb.style.top = fmtTop + 'px';

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
    const pw = 8 * 18 + 7 * 3 + 16;
    const left = Math.min(r.left, window.innerWidth - pw - 8);
    palette.style.left = Math.max(4, left) + 'px';
    palette.style.top = (r.bottom + 4) + 'px';
  }
  palette.style.display = 'block';
}

export function _docxPickColor(color: string, keepOpen?: boolean): void {
  const palette = _docxCpEl;
  const type = palette ? palette.dataset.cpType : '';
  if (typeof (window as any)._ttPickColor === 'function') {
    (window as any)._ttPickColor(color, keepOpen);
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
}

// ── PPTX shape/slide operations ───────────────────────────────────

export function pptxShapeFill(val: string): void {
  const ed = state.activeEditor;
  if (!ed || !ed._selShape) { showToast('\u8bf7\u5148\u9009\u4e2d\u4e00\u4e2a\u5f62\u72b6', 'info'); return; }
  const swatch = $('wa-pptx-shapefill-swatch');
  if (swatch) swatch.style.background = val;
  ed._pushUndo();
  const shapeId = parseInt(ed._selShape.dataset.shapeId);
  const slide = ed.data.slides[ed._curIdx];
  const shape = (slide.shapes || []).find((s: any) => s.id === shapeId);
  if (shape) {
    shape.fill = val;
    ed._selShape.style.backgroundColor = val;
    WA.scheduleAutoSave();
  }
}

export function pptxShapeBorder(val: string): void {
  const ed = state.activeEditor;
  if (!ed || !ed._selShape) { showToast('\u8bf7\u5148\u9009\u4e2d\u4e00\u4e2a\u5f62\u72b6', 'info'); return; }
  const swatch = $('wa-pptx-shapeborder-swatch');
  if (swatch) swatch.style.background = val;
  ed._pushUndo();
  const shapeId = parseInt(ed._selShape.dataset.shapeId);
  const slide = ed.data.slides[ed._curIdx];
  const shape = (slide.shapes || []).find((s: any) => s.id === shapeId);
  if (shape) {
    if (!shape.border) shape.border = {};
    shape.border.color = val;
    const w = shape.border.width || 1;
    ed._selShape.style.border = w + 'pt solid ' + val;
    WA.scheduleAutoSave();
  }
}

export function pptxBorderWidth(val: string): void {
  const ed = state.activeEditor;
  if (!ed || !ed._selShape) return;
  ed._pushUndo();
  const shapeId = parseInt(ed._selShape.dataset.shapeId);
  const slide = ed.data.slides[ed._curIdx];
  const shape = (slide.shapes || []).find((s: any) => s.id === shapeId);
  if (shape) {
    if (!shape.border) shape.border = {};
    shape.border.width = parseFloat(val);
    if (parseFloat(val) === 0) {
      ed._selShape.style.border = 'none';
    } else {
      const c = shape.border.color || '#000000';
      ed._selShape.style.border = val + 'pt solid ' + c;
    }
    WA.scheduleAutoSave();
  }
}

export function pptxDupSlide(): void {
  const ed = state.activeEditor;
  if (ed && ed._duplicateSlide) ed._duplicateSlide();
}

export function pptxStepFont(dir: number): void {
  const ed = state.activeEditor;
  if (ed && ed._stepFontSize) ed._stepFontSize(dir);
}

export function pptxClearFormat(): void {
  const ed = state.activeEditor;
  if (!ed) return;
  const slide = ed.data.slides[ed._curIdx];
  const getSpans = (): HTMLElement[] => {
    const sel = window.getSelection && window.getSelection();
    const actRange = (ed._savedRange && !ed._savedRange.collapsed)
      ? ed._savedRange
      : (sel && sel.rangeCount > 0 && !sel.isCollapsed ? sel.getRangeAt(0) : null);
    if (actRange) {
      const arr: HTMLElement[] = [];
      ed._selShape && ed._selShape.querySelectorAll('.wa-pptx-run').forEach((s: HTMLElement) => {
        if (sel ? sel.containsNode(s, true) : actRange.intersectsNode(s)) arr.push(s);
      });
      if (arr.length) return arr;
    }
    return ed._activeSpan ? [ed._activeSpan]
      : (ed._selShape ? Array.from(ed._selShape.querySelectorAll('.wa-pptx-run')) : []);
  };
  const spans = getSpans();
  if (!spans.length) return;
  ed._pushUndo();
  spans.forEach((sp: HTMLElement) => {
    const shape = (slide.shapes || []).find((s: any) => s.id === parseInt(sp.dataset.shapeId || '0'));
    const run = shape && shape.paragraphs[parseInt(sp.dataset.pi || '0')] && shape.paragraphs[parseInt(sp.dataset.pi || '0')].runs[parseInt(sp.dataset.ri || '0')];
    if (!run) return;
    ['bold','italic','underline','strikethrough','superscript','subscript','highlight','color'].forEach(p => { delete run[p]; });
    sp.style.fontWeight = '';
    sp.style.fontStyle = '';
    sp.style.textDecoration = '';
    sp.style.verticalAlign = '';
    sp.style.backgroundColor = '';
    sp.style.color = '';
    const canvasEl = $('wa-pptx-slide-canvas');
    if (canvasEl) {
      const scaleW = parseFloat(canvasEl.style.width) / ed.data.slideWidthEmu;
      sp.style.fontSize = Math.max(Math.round((run.size || 18) * scaleW * 12700), 6) + 'px';
    }
  });
  WA.scheduleAutoSave();
}

export function pptxAddSlide(): void {
  const ed = state.activeEditor;
  if (!ed || !ed.data) return;
  ed._pushUndo();
  const newIdx = ed.data.slides.length;
  const sW = ed.data.slideWidthEmu || 9144000;
  const sH = ed.data.slideHeightEmu || 6858000;
  ed.data.slides.push({
    index: newIdx, background: '#ffffff',
    shapes: [
      {
        id: -(Date.now() % 100000000),
        name: 'Title', type: 'TEXT_BOX',
        left: Math.round(sW * 0.05), top: Math.round(sH * 0.06),
        width: Math.round(sW * 0.9), height: Math.round(sH * 0.18),
        z_order: 1, has_text: true, fill: null,
        paragraphs: [{ align: 'CENTER', runs: [{ text: '\u70b9\u51fb\u8f93\u5165\u6807\u9898', size: 36, bold: true }] }],
      },
      {
        id: -(Date.now() % 100000000) - 1,
        name: 'Content', type: 'TEXT_BOX',
        left: Math.round(sW * 0.05), top: Math.round(sH * 0.30),
        width: Math.round(sW * 0.9), height: Math.round(sH * 0.60),
        z_order: 2, has_text: true, fill: null,
        paragraphs: [{ align: 'LEFT', runs: [{ text: '\u70b9\u51fb\u8f93\u5165\u5185\u5bb9', size: 24 }] }],
      },
    ],
  });
  ed._buildThumbs();
  ed._renderSlide(newIdx);
  WA.scheduleAutoSave();
}

export function pptxDelSlide(): void {
  const ed = state.activeEditor;
  if (!ed || !ed.data || ed.data.slides.length <= 1) { showToast('\u81f3\u5c11\u4fdd\u7559\u4e00\u5f20\u5e7b\u706f\u7247', 'error'); return; }
  ed._pushUndo();
  const deletedIdx = ed._curIdx;
  ed.data.slides.splice(deletedIdx, 1);
  ed.data.slides.forEach((s: any, i: number) => { s.index = i; });
  const newIdx = Math.min(deletedIdx, ed.data.slides.length - 1);
  ed._buildThumbs();
  ed._renderSlide(newIdx);
  WA.scheduleAutoSave();
  showToast(`\u5df2\u5220\u9664\u7b2c ${deletedIdx + 1} \u5f20\u5e7b\u706f\u7247`, 'info');
}

export function pptxInsertShape(type: string): void {
  const ed = state.activeEditor;
  if (!ed) return;
  const slide = ed.data.slides[ed._curIdx];
  if (!slide) return;
  ed._pushUndo();
  const newId = Math.max(0, ...(slide.shapes || []).map((s: any) => s.id || 0)) + 1;
  const W = ed.data.slideWidthEmu, H = ed.data.slideHeightEmu;
  const shape: any = {
    id: newId, type: 'shape', shapeType: type,
    left: W * 0.3, top: H * 0.3,
    width: W * 0.2, height: H * 0.15,
    fill: '#4472C4',
    border: { color: '#2F4E8A', width: 1 },
    paragraphs: [{ runs: [], align: 'CENTER' }]
  };
  if (type === 'line') {
    shape.height = 0;
    shape.top = H * 0.5;
    shape.fill = 'none';
    shape.border = { color: '#4472C4', width: 2 };
  }
  slide.shapes.push(shape);
  ed._renderSlide(ed._curIdx);
  WA.scheduleAutoSave();
}

export function pptxSetShapeSize(dim: string, val: string): void {
  const ed = state.activeEditor;
  if (!ed || !ed._selShape) return;
  const px = parseFloat(val);
  if (isNaN(px) || px <= 0) return;
  const shapeId = parseInt(ed._selShape.dataset.shapeId);
  const slide = ed.data.slides[ed._curIdx];
  const shape = (slide.shapes || []).find((s: any) => s.id === shapeId);
  if (!shape) return;
  ed._pushUndo();
  const canvasEl = $('wa-pptx-slide-canvas');
  const scaleW = parseFloat(canvasEl!.style.width) / ed.data.slideWidthEmu;
  const scaleH = parseFloat(canvasEl!.style.height) / ed.data.slideHeightEmu;
  if (dim === 'w') { shape.width = px / scaleW; ed._selShape.style.width = px + 'px'; }
  else             { shape.height = px / scaleH; ed._selShape.style.height = px + 'px'; }
  WA.scheduleAutoSave();
}

export function pptxSetShapePos(dim: string, val: string): void {
  const ed = state.activeEditor;
  if (!ed || !ed._selShape) return;
  const px = parseFloat(val);
  if (isNaN(px)) return;
  const shapeId = parseInt(ed._selShape.dataset.shapeId);
  const slide = ed.data.slides[ed._curIdx];
  const shape = (slide.shapes || []).find((s: any) => s.id === shapeId);
  if (!shape) return;
  ed._pushUndo();
  const canvasEl = $('wa-pptx-slide-canvas');
  const scaleW = parseFloat(canvasEl!.style.width) / ed.data.slideWidthEmu;
  const scaleH = parseFloat(canvasEl!.style.height) / ed.data.slideHeightEmu;
  if (dim === 'x') { shape.left = px / scaleW;  ed._selShape.style.left = px + 'px'; }
  else             { shape.top  = px / scaleH;  ed._selShape.style.top  = px + 'px'; }
  WA.scheduleAutoSave();
}

export function pptxSetShapeRot(deg: string): void {
  const ed = state.activeEditor;
  if (!ed || !ed._selShape) return;
  const d = parseFloat(deg);
  if (isNaN(d)) return;
  const shapeId = parseInt(ed._selShape.dataset.shapeId);
  const slide = ed.data.slides[ed._curIdx];
  const shape = (slide.shapes || []).find((s: any) => s.id === shapeId);
  if (!shape) return;
  ed._pushUndo();
  shape.rotation = d;
  ed._selShape.style.transform = 'rotate(' + d + 'deg)';
  WA.scheduleAutoSave();
}

export function pptxHighlightColor(val: string): void {
  const swatch = $('wa-pptx-highlight-swatch');
  if (swatch) swatch.style.background = val;
  const ed = state.activeEditor;
  if (ed && ed.applyFormat) ed.applyFormat('highlight', val);
}

// ── PPTX slide background operations ──────────────────────────────

export function pptxBgColor(color: string): void {
  const ed = state.activeEditor;
  if (!ed) return;
  ed._pushUndo();
  const slide = ed.data.slides[ed._curIdx];
  slide.background = color;
  slide.backgroundGradient = null;
  slide.backgroundImage = null;
  const canvas = $('wa-pptx-slide-canvas');
  if (canvas) canvas.style.background = color;
  const swatch = $('wa-pptx-bg-swatch');
  if (swatch) swatch.style.background = color;
  ed._redrawThumb(ed._curIdx);
  WA.scheduleAutoSave();
}

export function pptxSetBgImage(fileInput: HTMLInputElement): void {
  const ed = state.activeEditor;
  if (!ed || !fileInput.files || !fileInput.files[0]) return;
  const file = fileInput.files[0];
  fileInput.value = '';
  const reader = new FileReader();
  reader.onload = (ev) => {
    const raw = ev.target!.result as string;
    const img = new Image();
    img.onload = () => {
      const MAX = 1920;
      let w = img.naturalWidth, h = img.naturalHeight;
      if (w > MAX || h > MAX) {
        const ratio = Math.min(MAX / w, MAX / h);
        w = Math.round(w * ratio);
        h = Math.round(h * ratio);
      }
      const _cv = document.createElement('canvas');
      _cv.width = w; _cv.height = h;
      const _ctx = _cv.getContext('2d')!;
      _ctx.drawImage(img, 0, 0, w, h);
      const dataUri = _cv.toDataURL('image/jpeg', 0.82);
      ed._pushUndo();
      const slide = ed.data.slides[ed._curIdx];
      slide.backgroundImage = dataUri;
      slide.backgroundGradient = null;
      const canvas = $('wa-pptx-slide-canvas');
      if (canvas) canvas.style.background = `url('${dataUri}') center/cover no-repeat`;
      const swatch = $('wa-pptx-bg-swatch');
      if (swatch) { swatch.style.background = `url('${dataUri}') center/cover`; swatch.style.backgroundSize = 'cover'; }
      ed._redrawThumb(ed._curIdx);
      WA.scheduleAutoSave();
    };
    img.src = raw;
  };
  reader.readAsDataURL(file);
}

export function pptxRemoveBg(): void {
  const ed = state.activeEditor;
  if (!ed) return;
  ed._pushUndo();
  const slide = ed.data.slides[ed._curIdx];
  slide.background = '#ffffff';
  slide.backgroundGradient = null;
  slide.backgroundImage = null;
  const canvas = $('wa-pptx-slide-canvas');
  if (canvas) canvas.style.background = '#ffffff';
  const swatch = $('wa-pptx-bg-swatch');
  if (swatch) { swatch.style.background = '#ffffff'; swatch.style.backgroundImage = ''; }
  ed._redrawThumb(ed._curIdx);
  WA.scheduleAutoSave();
}

export function pptxApplyQuickLayout(layout: string): void {
  const ed = state.activeEditor;
  if (ed && ed._applyQuickLayout) ed._applyQuickLayout(layout);
}

export function pptxChangeBgImage(fileInput: HTMLInputElement): void {
  pptxSetBgImage(fileInput);
}

export function pptxFmt(cmd: string): void {
  const ed = state.activeEditor;
  if (ed && typeof ed.applyFormat === 'function') ed.applyFormat(cmd);
}

export function pptxAlign(align: string): void {
  const ed = state.activeEditor;
  if (ed && typeof ed.applyFormat === 'function') ed.applyFormat('align', align);
}

export function pptxFontSize(size: string): void {
  const ed = state.activeEditor;
  if (ed && typeof ed.applyFormat === 'function') ed.applyFormat('size', size);
}

export function pptxFontName(value: string): void {
  const ed = state.activeEditor;
  if (ed && typeof ed.applyFormat === 'function') ed.applyFormat('fontName', value);
}

export function pptxFontColor(value: string): void {
  const swatch = $('wa-pptx-fontcolor-swatch');
  if (swatch) swatch.style.background = value;
  const hoverSwatch = $('wa-hb-color-swatch');
  if (hoverSwatch) hoverSwatch.style.background = value;
  const ed = state.activeEditor;
  if (ed && typeof ed.applyFormat === 'function') ed.applyFormat('color', value);
}

export function pptxColorPicker(type: string, triggerEl?: HTMLElement): void {
  const palette = $('wa-pptx-cp');
  const grid = $('wa-pptx-cp-grid');
  if (!palette || !grid) return;
  if (palette.style.display !== 'none' && palette.dataset.cpType === type) {
    palette.style.display = 'none';
    return;
  }
  palette.dataset.cpType = type;
  grid.innerHTML = _CP_COLORS.map((c: string) =>
    `<div title="${c}" style="width:18px;height:18px;border-radius:3px;background:${c};cursor:pointer;border:1px solid rgba(255,255,255,.12);box-sizing:border-box"` +
    ` data-wa-toolbar-color="pptx" data-color="${c}"></div>`
  ).join('');
  if (triggerEl) {
    const r = triggerEl.getBoundingClientRect();
    const pw = 8 * 18 + 7 * 3 + 16;
    const left = Math.min(r.left, window.innerWidth - pw - 8);
    palette.style.left = Math.max(4, left) + 'px';
    palette.style.top = (r.bottom + 4) + 'px';
  }
  palette.style.display = 'block';
}

export function _pptxPickColor(color: string, keepOpen?: boolean): void {
  const palette = $('wa-pptx-cp');
  const type = palette ? palette.dataset.cpType : '';
  if (type === 'font') pptxFontColor(color);
  else if (type === 'fill') pptxShapeFill(color);
  else if (type === 'border') pptxShapeBorder(color);
  else if (type === 'highlight') pptxHighlightColor(color);
  else if (type === 'bg') pptxBgColor(color);
  const hexEl = $('wa-pptx-cp-hex');
  if (hexEl) hexEl.textContent = color;
  const customInput = $('wa-pptx-cp-custom') as HTMLInputElement;
  if (customInput && /^#[0-9a-f]{6}$/i.test(color)) customInput.value = color;
  if (!keepOpen && palette) palette.style.display = 'none';
}

export function pptxIndent(delta: number): void {
  const ed = state.activeEditor;
  if (ed && typeof ed.applyFormat === 'function') ed.applyFormat('indent', Number(delta) || 0);
}

export function pptxLineSpacing(value: string): void {
  const ed = state.activeEditor;
  if (ed && typeof ed.applyFormat === 'function') ed.applyFormat('lineSpacing', value);
}

export function pptxToggleBullet(): void {
  const ed = state.activeEditor;
  if (ed && typeof ed.applyFormat === 'function') ed.applyFormat('bullet', true);
}

export function pptxToggleNumbered(): void {
  const ed = state.activeEditor;
  if (ed && typeof ed.applyFormat === 'function') ed.applyFormat('numbered', true);
}

export function pptxVertAlign(value: string): void {
  const ed = state.activeEditor;
  if (ed && typeof ed.applyFormat === 'function') ed.applyFormat('verticalAlign', value);
}

export function pptxOpacity(value: string): void {
  const ed = state.activeEditor;
  if (!ed || !ed._selShape) return;
  const pct = Math.max(0, Math.min(100, parseFloat(value)));
  if (!Number.isFinite(pct)) return;
  const shapeId = parseInt(ed._selShape.dataset.shapeId || '0');
  const slide = ed.data && ed.data.slides && ed.data.slides[ed._curIdx];
  const shape = slide && (slide.shapes || []).find((s: any) => s.id === shapeId);
  if (!shape) return;
  if (typeof ed._pushUndo === 'function') ed._pushUndo();
  shape.opacity = pct / 100;
  ed._selShape.style.opacity = String(shape.opacity);
  WA.scheduleAutoSave();
}

export function pptxZOrder(action: string): void {
  const ed = state.activeEditor;
  if (!ed || !ed._selShape) return;
  const shapeId = parseInt(ed._selShape.dataset.shapeId || '0');
  if (action === 'front' && typeof ed._bringToFront === 'function') ed._bringToFront(shapeId);
  else if (action === 'back' && typeof ed._sendToBack === 'function') ed._sendToBack(shapeId);
  else if ((action === 'up' || action === 'forward') && typeof ed._reorder === 'function') ed._reorder(shapeId, 1);
  else if ((action === 'down' || action === 'backward') && typeof ed._reorder === 'function') ed._reorder(shapeId, -1);
}

export function pptxZoom(value: string | number): void {
  const pct = parseInt(String(value), 10);
  const label = $('wa-pptx-zoom-label');
  if (label && Number.isFinite(pct)) label.textContent = pct + '%';
  const ed = state.activeEditor;
  if (ed && typeof ed.setZoom === 'function' && Number.isFinite(pct)) ed.setZoom(pct);
}

export function pptxNav(delta: number): void {
  const ed = state.activeEditor;
  if (!ed || !ed.data || !Array.isArray(ed.data.slides) || typeof ed._renderSlide !== 'function') return;
  const next = (ed._curIdx || 0) + Number(delta || 0);
  if (next >= 0 && next < ed.data.slides.length) ed._renderSlide(next);
}

export function docxZoom(value: string | number): void {
  const pct = parseInt(String(value), 10);
  const ed = state.activeEditor;
  if (ed && typeof ed.setZoom === 'function' && Number.isFinite(pct)) ed.setZoom(pct);
  if (Number.isFinite(pct)) _updateDocxZoomUI(pct);
}

export function pptxInsertImageClick(): void {
  const input = document.getElementById('wa-pptx-img-input') as HTMLInputElement | null
    || document.getElementById('wa-pptx-insert-image-file') as HTMLInputElement | null
    || document.getElementById('wa-pptx-image-input') as HTMLInputElement | null;
  if (input) {
    input.click();
    return;
  }
  showToast('未找到 PPT 图片文件选择器，请刷新后重试', 'warning');
}

export function pptxInsertImageFile(input: HTMLInputElement): void {
  const ed = state.activeEditor;
  const file = input && input.files && input.files[0];
  if (!file) return;
  input.value = '';
  if (!ed) {
    showToast('请先打开一个 PPT 文件', 'warning');
    return;
  }
  if (typeof ed.insertImageFile === 'function') {
    ed.insertImageFile(file);
    return;
  }
  if (typeof ed._insertImageFile === 'function') {
    ed._insertImageFile(file);
    return;
  }
  showToast('当前 PPT 编辑器不支持插入图片，请刷新后重试', 'error');
}

// ── Image send-to-AI ───────────────────────────────────────────────
export function _sendImageToAI(action: string, imgSrc: string): void {
  const aiInput = document.getElementById('wa-user-input') as HTMLTextAreaElement;
  if (!aiInput) return;
  const label = action === 'describe' ? '\u8bf7\u63cf\u8ff0\u8fd9\u5f20\u56fe\u7247\u7684\u5185\u5bb9' : '\u8bf7\u4e3a\u8fd9\u5f20\u56fe\u7247\u751f\u6210\u66ff\u6362\u65b9\u6848';
  aiInput.value = label;
  aiInput.focus();
  workspaceApi._pendingImageSrc = imgSrc;
  WA.sendMessage();
}

export function pptxDelShape(): void {
  const ed = state.activeEditor;
  if (ed && ed.deleteSelected) ed.deleteSelected();
}

export function pptxSwitchTab(btn: HTMLElement, tabName: string): void {
  document.querySelectorAll('.wa-pptx-rtab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  const toolbar = document.getElementById('wa-pptx-toolbar');
  if (!toolbar) return;
  toolbar.querySelectorAll('[data-tab]').forEach(el => {
    (el as HTMLElement).style.display = ((el as HTMLElement).dataset.tab === tabName) ? '' : 'none';
  });
}

export function pptxInsertMode(): void {
  const ed = state.activeEditor;
  if (!ed || !ed.data) return;
  ed._insertMode = !ed._insertMode;
  const btn = $('wa-pptx-insert-tb');
  if (btn) btn.classList.toggle('active', ed._insertMode);
  const canvas = $('wa-pptx-slide-canvas');
  if (canvas) canvas.style.cursor = ed._insertMode ? 'crosshair' : '';
  const mainEl = $('wa-pptx-main');
  if (mainEl) { mainEl.scrollLeft = 0; mainEl.scrollTop = 0; }
  if (ed._insertMode) showToast('\u5728\u5e7b\u706f\u7247\u4e0a\u62d6\u62fd\u7ed8\u5236\u6587\u672c\u6846', 'info');
}

export function pptxSave(): void {
  if (state.activeEditor && state.activeEditor.serialize) {
    WA.saveFile();
  }
}

export function pptxUndo(): void {
  if (state.activeEditor && state.activeEditor._undo) state.activeEditor._undo();
}

export function pptxRedo(): void {
  if (state.activeEditor && state.activeEditor._redo) state.activeEditor._redo();
}

export function pptxDownload(): void {
  if (state.fileId) {
    WA.saveFile().then(() => {
      const a = document.createElement('a');
      a.href = `/api/v1/workspace/raw/${state.fileId}`;
      a.download = state.fileName || 'presentation.pptx';
      a.click();
    }).catch(() => {});
  }
}

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

publishWorkspaceApi({
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
  (window as any)._getDocxSelBounds = _getDocxSelBounds;
  (window as any)._getDocxNativeSelectionBounds = _getDocxNativeSelectionBounds;
(window as any)._getDocxHdrFtrSelectionInfo = _buildHdrFtrSelectionInfo;
  (window as any)._kotoDocxSelectionChanged = _kotoDocxSelectionChanged;
}
