/**
 * docx-extensions.js
 * Custom TipTap / ProseMirror extensions that preserve
 * DOCX-specific formatting attributes during round-trip HTML editing.
 */

import { Extension, Mark, Node, mergeAttributes } from '@tiptap/core';
import { NodeSelection, Plugin, PluginKey } from '@tiptap/pm/state';
import { Decoration, DecorationSet } from '@tiptap/pm/view';
import {
  ResizeState,
  TableMap,
  cellAround,
  columnResizingPluginKey,
  pointsAtCell,
  tableEditing,
  tableNodeTypes,
  updateColumnsOnResize,
} from '@tiptap/pm/tables';
import { Table, TableView } from '@tiptap/extension-table';
import { TableRow } from '@tiptap/extension-table-row';
import { TableCell } from '@tiptap/extension-table-cell';
import { TableHeader } from '@tiptap/extension-table-header';
import { TextStyle } from '@tiptap/extension-text-style';
import Image from '@tiptap/extension-image';
import Heading from '@tiptap/extension-heading';
import { resolveDocxBreakChrome } from './docx-pagination-runtime.js';
import { createDocxPaginationScheduler } from './docx-pagination-scheduler.js';
import {
  clearHdrFtrOverlayActive as _clearHdrFtrOverlayActive,
  focusHdrFtrOverlay as _focusHdrFtrOverlay,
  initialHdrFtrOverlayHtml as _initialHdrFtrOverlayHtml,
  isHdrFtrToolbarInteractionLocked as _isHdrFtrToolbarInteractionLocked,
  markHdrFtrOverlayActive as _markHdrFtrOverlayActive,
  normalizeHdrFtrHtml as _normalizeHdrFtrHtml,
  notifyHdrFtrSelectionChanged as _notifyHdrFtrSelectionChanged,
  setHdrFtrSlotState as _setHdrFtrSlotState,
} from './docx-header-footer-runtime.js';

// ─────────────────────────────────────────────────────────────────────────────
// AutoPageBreakPlugin
//
// A ProseMirror-based TipTap Extension that measures each top-level block's
// rendered height and inserts WORD-LIKE soft page breaks as widget decorations
// (not real nodes) whenever cumulative content height exceeds one page's
// content area.
//
// Key design decisions:
//   - Widget decorations (not real nodes): soft breaks never appear in the
//     serialized HTML or DOCX export. Only explicit <w:br type="page"/> breaks
//     become real DocxPageBreak nodes.
//   - Block-level only: breaks at block (paragraph / table / image) boundaries,
//     not mid-line. This avoids font-metric calculations while still producing
//     a layout close to Word's Print Layout view.
//   - No overlay: all break visuals are in-flow (display:block inside
//     .ProseMirror), so content is never hidden behind a z-index overlay.
//   - Explicit DocxPageBreak nodes coexist: when encountered, they reset the
//     height accumulator (page counter advances via the NodeView itself).
//
// Configuration (set on editor.storage.autoPageBreak after render()):
//   pageHeightPx     — full page height in CSS pixels (default: 1056 US-Letter)
//   marginTopPx      — top margin in px (default: 96)
//   marginBottomPx   — bottom margin in px (default: 80)
//   headerHtml       — HTML string for page header (shown in each break zone)
//   footerHtml       — HTML string for page footer (shown in each break zone)
//   onPageCountChange — optional callback(totalPages) called after each recalc
// ─────────────────────────────────────────────────────────────────────────────

const _AUTO_PB_KEY = new PluginKey('autoPageBreak');

const _AUTO_PB_INITIAL_DELAY_MS = 80;

const _AUTO_PB_UPDATE_DELAY_MS = 120;

const _AUTO_PB_MIN_LINES_PER_FRAGMENT = 2;

const _DOCX_SOFT_PAGE_BREAK_SELECTOR = '[data-soft-page-break]';

const _DOCX_PAGE_BOUNDARY_SELECTOR = '[data-soft-page-break],[data-page-break]';

function _normalizeDocxBreakFillPx(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : 0;
}

function _resolveRenderedDocxPageGeometry(pmDom, fallbackPageWidthPx, fallbackContentLeftPx) {
  const fallbackWidth = Math.max(0, Number(fallbackPageWidthPx) || 0);
  const fallbackLeft = Math.max(0, Number(fallbackContentLeftPx) || 0);
  let contentLeftPx = fallbackLeft;
  try {
    const pmStyle = pmDom && typeof window !== 'undefined'
      ? window.getComputedStyle(pmDom)
      : null;
    contentLeftPx = Number.parseFloat(pmStyle?.paddingLeft || '') || fallbackLeft;
  } catch (_) {}
  return {
    pageWidthPx: pmDom?.offsetWidth || fallbackWidth,
    contentLeftPx,
  };
}

function _alignSoftBreakWidgetToRenderedPage(widget, pageLeftOffsetPx, pageWidthPx) {
  if (!widget?.style) return;
  const pageOffset = Math.max(0, Number(pageLeftOffsetPx) || 0);
  const renderedWidth = Math.max(0, Number(pageWidthPx) || 0);
  widget.style.marginLeft = `${-pageOffset}px`;
  widget.style.marginRight = '0';
  if (renderedWidth > 0) {
    widget.style.width = renderedWidth + 'px';
    widget.style.maxWidth = renderedWidth + 'px';
  }
}

function _applyMeasuredExplicitBreakState(dom, pageNum, currentSectionIdx, nextSectionIdx, contentFillPx) {
  if (!dom) return;
  dom.setAttribute('data-page-num', String(Math.max(1, Number.parseInt(pageNum, 10) || 1)));
  dom.setAttribute('data-section-idx', String(Math.max(0, Number.parseInt(nextSectionIdx, 10) || 0)));
  dom.setAttribute('data-current-section-idx', String(Math.max(0, Number.parseInt(currentSectionIdx, 10) || 0)));
  dom.setAttribute('data-next-section-idx', String(Math.max(0, Number.parseInt(nextSectionIdx, 10) || 0)));
  dom.setAttribute('data-content-fill-px', String(Math.round(_normalizeDocxBreakFillPx(contentFillPx))));
  const fillEl = dom.querySelector('.koto-pb-fill');
  if (fillEl) fillEl.style.height = `${_normalizeDocxBreakFillPx(contentFillPx)}px`;
}

/**
 * Build the one shared page-break surface used by explicit, automatic, inline
 * and table pagination.  Callers only decide where the surface is anchored.
 */
function _buildDocxPageBreakWidget({
  breakAttribute = 'data-soft-page-break',
  pageNum,
  headerHtml,
  footerHtml,
  marginTopPx,
  marginBottomPx,
  marginLeftPx,
  marginRightPx,
  extStorage,
  contentFillPx = 0,
}) {
  const dom = document.createElement('div');
  dom.setAttribute(breakAttribute, String(pageNum));
  dom.setAttribute('data-content-fill-px', String(Math.round(_normalizeDocxBreakFillPx(contentFillPx))));
  dom.className = 'koto-page-break';
  dom.setAttribute('contenteditable', 'false');
  // Cancel ProseMirror's horizontal padding so the page break spans the full page width
  const mL = marginLeftPx || 96;
  const mR = marginRightPx || 96;
  dom.style.marginLeft = `-${mL}px`;
  dom.style.marginRight = `-${mR}px`;

  const fillEl = document.createElement('div');
  fillEl.className = 'koto-pb-fill';
  fillEl.style.height = `${_normalizeDocxBreakFillPx(contentFillPx)}px`;
  dom.appendChild(fillEl);

  // ── Bottom zone of ending page (white footer area) ──────────────────────
  const endZone = document.createElement('div');
  endZone.className = 'koto-pb-end';
  if (marginBottomPx) endZone.style.height = marginBottomPx + 'px';
  endZone.style.setProperty('--koto-docx-marker-left', `${Math.max(24, mL - 12)}px`);
  endZone.style.setProperty('--koto-docx-marker-right', `${Math.max(24, mR - 12)}px`);

  const footerEl = document.createElement('div');
  footerEl.className = 'koto-pb-footer';
  footerEl.style.padding = `0 ${mR}px 0 ${mL}px`;
  _setHdrFtrSlotState(footerEl, footerHtml, 'footer');
  endZone.appendChild(footerEl);

  dom.appendChild(endZone);

  // ── Gray gap between pages ───────────────────────────────────────────────
  const gapZone = document.createElement('div');
  gapZone.className = 'koto-pb-gap';
  dom.appendChild(gapZone);

  // ── Top zone of starting page (white header area) ────────────────────────
  const startZone = document.createElement('div');
  startZone.className = 'koto-pb-start';
  if (marginTopPx) startZone.style.height = marginTopPx + 'px';
  startZone.style.setProperty('--koto-docx-marker-left', `${Math.max(24, mL - 12)}px`);
  startZone.style.setProperty('--koto-docx-marker-right', `${Math.max(24, mR - 12)}px`);

  const headerEl = document.createElement('div');
  headerEl.className = 'koto-pb-header';
  headerEl.style.padding = `0 ${mR}px 0 ${mL}px`;
  _setHdrFtrSlotState(headerEl, headerHtml, 'header');
  startZone.appendChild(headerEl);

  dom.appendChild(startZone);

  // ── Click-to-edit: double-click opens an overlay editor ──────────────────
  const _openOverlay = (targetEl, type) => {
    // Prevent duplicate overlays
    if (targetEl.querySelector('.koto-hdrftr-overlay')) return;
    targetEl.classList.add('is-editing');
    const overlay = document.createElement('div');
    overlay.className = 'koto-hdrftr-overlay';
    overlay.setAttribute('contenteditable', 'true');
    overlay.dataset.slotType = type;
    overlay.innerHTML = _initialHdrFtrOverlayHtml(targetEl.innerHTML);
    const overlayOutline = type === 'header'
      ? 'outline:none;outline-offset:0;'
      : 'outline:1px dashed rgba(79,126,255,.5);outline-offset:-1px;';
    overlay.style.cssText = `position:absolute;top:0;left:0;right:0;bottom:0;z-index:10;background:#fff;padding:inherit;box-sizing:border-box;${overlayOutline}`;

    const _finish = () => {
      const newHtml = _normalizeHdrFtrHtml(overlay.innerHTML) ? overlay.innerHTML : '';
      _clearHdrFtrOverlayActive(overlay);
      overlay.remove();
      targetEl.classList.remove('is-editing');
      _setHdrFtrSlotState(targetEl, newHtml, type);
      const storageKey = type === 'header' ? 'headerHtml' : 'footerHtml';
      if (extStorage) extStorage[storageKey] = newHtml;
      if (extStorage && Array.isArray(extStorage.sections)) {
        extStorage.sections.forEach((section) => {
          if (section && typeof section === 'object') {
            section[type === 'header' ? 'header_html' : 'footer_html'] = newHtml;
          }
        });
      }
      // Sync to all header/footer instances
      const root = dom.closest('#wa-docx-editor');
      if (!root) return;
      const cls = type === 'header' ? '.koto-pb-header' : '.koto-pb-footer';
      root.querySelectorAll(cls).forEach((sib) => {
        if (sib !== targetEl) _setHdrFtrSlotState(sib, newHtml, type);
      });
      const flCls = type === 'header' ? '.koto-page-header-first' : '.koto-page-footer-last';
      const flEl = root.querySelector(flCls);
      if (flEl && flEl.dataset.variant !== 'first') {
        _setHdrFtrSlotState(flEl, newHtml, type);
      }
      _notifyHdrFtrSelectionChanged();
    };

    const _syncSelection = () => {
      _markHdrFtrOverlayActive(overlay);
      _notifyHdrFtrSelectionChanged();
    };

    overlay.addEventListener('focus', _syncSelection);
    overlay.addEventListener('mouseup', () => requestAnimationFrame(_syncSelection));
    overlay.addEventListener('keyup', _syncSelection);
    overlay.addEventListener('input', _syncSelection);
    overlay.addEventListener('blur', () => {
      requestAnimationFrame(() => {
        if (!overlay.isConnected || _isHdrFtrToolbarInteractionLocked()) return;
        _finish();
      });
    });
    overlay.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { overlay.blur(); }
      if (e.key === 'Enter') { e.preventDefault(); document.execCommand('insertLineBreak'); }
    });
    targetEl.appendChild(overlay);
    _markHdrFtrOverlayActive(overlay);
    overlay.focus();
    requestAnimationFrame(() => _focusHdrFtrOverlay(overlay));
  };

  headerEl.addEventListener('dblclick', (e) => { e.stopPropagation(); _openOverlay(headerEl, 'header'); });
  footerEl.addEventListener('dblclick', (e) => { e.stopPropagation(); _openOverlay(footerEl, 'footer'); });

  return { dom, fillEl, endZone, startZone, footerEl, headerEl };
}

function _buildInlineSoftBreakWidget(pageNum, headerHtml, footerHtml, marginTopPx, marginBottomPx, marginLeftPx, marginRightPx, pageWidthPx, extStorage, pageLeftOffsetPx, contentFillPx = 0) {
  const anchor = document.createElement('span');
  anchor.className = 'koto-inline-page-break-anchor';
  anchor.setAttribute('contenteditable', 'false');
  anchor.style.display = 'block';
  anchor.style.width = '100%';
  anchor.style.lineHeight = '0';
  anchor.style.fontSize = '0';

  const { dom: widget } = _buildDocxPageBreakWidget({
    pageNum,
    headerHtml,
    footerHtml,
    marginTopPx,
    marginBottomPx,
    marginLeftPx,
    marginRightPx,
    extStorage,
    contentFillPx,
  });
  // Inline decorations live inside the paragraph that is being split.  Its
  // own left/right or hanging indent changes the widget's containing block,
  // so escaping by the document margins alone does not reach the page edges.
  // Anchor the chrome to the measured page origin and give it the exact page
  // width instead; this keeps every sheet aligned regardless of paragraph
  // indentation.
  _alignSoftBreakWidgetToRenderedPage(widget, pageLeftOffsetPx, pageWidthPx);
  anchor.appendChild(widget);
  return anchor;
}

function _measureRelativeLeftPx(element, ancestor) {
  if (!element || !ancestor || !element.getBoundingClientRect || !ancestor.getBoundingClientRect) {
    return 0;
  }
  const ancestorRect = ancestor.getBoundingClientRect();
  const elementRect = element.getBoundingClientRect();
  const scaleX = ancestor.offsetWidth ? ancestorRect.width / ancestor.offsetWidth : 1;
  if (!Number.isFinite(scaleX) || scaleX <= 0) {
    return 0;
  }
  return Math.max(0, (elementRect.left - ancestorRect.left) / scaleX);
}

function _measureVerticalMarginsPx(element) {
  if (!element || typeof window === 'undefined' || typeof window.getComputedStyle !== 'function') {
    return { top: 0, bottom: 0 };
  }
  try {
    const style = window.getComputedStyle(element);
    return {
      top: parseFloat(style.marginTop || '0') || 0,
      bottom: parseFloat(style.marginBottom || '0') || 0,
    };
  } catch (_) {
    return { top: 0, bottom: 0 };
  }
}

function _measureDocxBlockContentHeightPx(element) {
  if (!element || typeof element.getBoundingClientRect !== 'function') {
    return element?.offsetHeight || 0;
  }

  const baseHeight = element.offsetHeight || 0;
  let contentHeight = baseHeight;

  try {
    const rootRect = element.getBoundingClientRect();
    const scaleY = baseHeight > 0 && rootRect.height > 0
      ? Math.max(0.01, rootRect.height / baseHeight)
      : 1;
    const visualChildren = element.querySelectorAll?.(
      'img,svg,canvas,video,.koto-img-wrapper'
    ) || [];

    visualChildren.forEach((child) => {
      if (!child || typeof child.getBoundingClientRect !== 'function') return;
      const rect = child.getBoundingClientRect();
      if (!rect || rect.width <= 0.5 || rect.height <= 0.5) return;
      const childBottom = (rect.bottom - rootRect.top) / scaleY;
      if (Number.isFinite(childBottom)) {
        contentHeight = Math.max(contentHeight, childBottom);
      }
    });
  } catch (_) {}

  // Subtract inline page-break anchor heights from the measured content
  // height.  When soft breaks are kept visible during measurement the
  // anchors occupy vertical space inside the block that does not represent
  // text content.  Excluding them yields the true text-only content height.
  try {
    const anchors = element.querySelectorAll?.('.koto-inline-page-break-anchor') || [];
    for (let ai = 0; ai < anchors.length; ai++) {
      const anchor = anchors[ai];
      if (anchor && anchor.offsetHeight) {
        contentHeight = Math.max(0, contentHeight - anchor.offsetHeight);
      }
    }
  } catch (_) {}

  return Math.max(0, contentHeight);
}

function _measureDocxBlockOuterHeightPx(element) {
  const margins = _measureVerticalMarginsPx(element);
  return _measureDocxBlockContentHeightPx(element) + margins.top + margins.bottom;
}

function _docxBlockAvoidsAutoSplit(node, element) {
  if (node?.type?.name === 'image') return true;
  if (!element) return false;
  try {
    return !!(
      element.matches?.('img,.koto-img-wrapper')
      || element.querySelector?.('img,.koto-img-wrapper')
    );
  } catch (_) {
    return false;
  }
}

function _groupDocxLineRects(rects) {
  const sorted = rects
    .filter((rect) => rect && rect.width > 0.5 && rect.height > 0.5)
    .sort((left, right) => (left.top - right.top) || (left.left - right.left));
  const lines = [];

  for (const rect of sorted) {
    const prev = lines[lines.length - 1];
    if (!prev || Math.abs(rect.top - prev.top) > 1.5 || Math.abs(rect.bottom - prev.bottom) > 1.5) {
      lines.push({
        top: rect.top,
        bottom: rect.bottom,
        left: rect.left,
        right: rect.right,
      });
      continue;
    }
    prev.top = Math.min(prev.top, rect.top);
    prev.bottom = Math.max(prev.bottom, rect.bottom);
    prev.left = Math.min(prev.left, rect.left);
    prev.right = Math.max(prev.right, rect.right);
  }

  return lines.filter((line) => (line.bottom - line.top) > 0.5 && (line.right - line.left) > 0.5);
}

function _normalizeDocxLineHeights(lines, targetHeight) {
  if (!Array.isArray(lines) || !lines.length) return [];

  const advances = lines.map((line, index) => {
    const rawHeight = Math.max(0, line.bottom - line.top);
    if (index < lines.length - 1) {
      return Math.max(rawHeight, lines[index + 1].top - line.top);
    }
    if (index > 0) {
      return Math.max(rawHeight, line.top - lines[index - 1].top);
    }
    return rawHeight;
  });

  const totalAdvance = advances.reduce((sum, value) => sum + (value || 0), 0);
  const scale = totalAdvance > 0 && targetHeight > 0
    ? targetHeight / totalAdvance
    : 1;

  return lines
    .map((line, index) => ({
      ...line,
      height: Math.max(0, (advances[index] || 0) * scale),
    }))
    .filter((line) => line.height > 0.5 && (line.right - line.left) > 0.5);
}

function _resolveDocxLineStartPos(view, line, nodeStart, nodeEnd) {
  const probeY = line.top + Math.max(1, Math.min(line.height / 2, line.height - 1));
  const probeXs = [
    Math.min(line.left + 1, line.right - 1),
    Math.min(line.left + 6, line.right - 1),
    (line.left + line.right) / 2,
  ];
  const ownerDoc = view?.dom?.ownerDocument || document;

  for (const probeX of probeXs) {
    try {
      if (typeof ownerDoc.caretPositionFromPoint === 'function') {
        const caret = ownerDoc.caretPositionFromPoint(probeX, probeY);
        const node = caret?.offsetNode;
        const offset = caret?.offset;
        if (node && Number.isFinite(offset)) {
          const domPos = view.posAtDOM(node, offset);
          if (domPos > nodeStart && domPos < nodeEnd) return domPos;
          if (domPos === nodeStart) return domPos;
        }
      } else if (typeof ownerDoc.caretRangeFromPoint === 'function') {
        const caretRange = ownerDoc.caretRangeFromPoint(probeX, probeY);
        const node = caretRange?.startContainer;
        const offset = caretRange?.startOffset;
        if (node && Number.isFinite(offset)) {
          const domPos = view.posAtDOM(node, offset);
          if (domPos > nodeStart && domPos < nodeEnd) return domPos;
          if (domPos === nodeStart) return domPos;
        }
      }
    } catch (_) {}

    const found = view.posAtCoords({ left: probeX, top: probeY });
    if (!found || !Number.isFinite(found.pos)) continue;
    if (found.pos > nodeStart && found.pos < nodeEnd) return found.pos;
    if (found.pos === nodeStart) return found.pos;
  }

  return null;
}

function _collectDocxTextBlockLines(view, domEl, nodeStart, nodeEnd) {
  if (!domEl || !domEl.ownerDocument?.createRange || nodeEnd <= nodeStart) return [];

  // Collect client rects from text nodes only, skipping break anchor
  // elements.  When soft breaks are kept visible the anchors produce
  // full-width block rects that would be misidentified as text lines.
  const allRects = [];
  const walker = domEl.ownerDocument.createTreeWalker(
    domEl,
    NodeFilter.SHOW_TEXT,
    null,
    false
  );
  const range = domEl.ownerDocument.createRange();
  let textNode;
  while ((textNode = walker.nextNode())) {
    // Skip text nodes inside break chrome (page numbers, headers, etc.)
    if (textNode.parentElement?.closest?.(
      '.koto-inline-page-break-anchor, [data-soft-page-break], .koto-pb-header, .koto-pb-footer'
    )) {
      continue;
    }
    range.selectNodeContents(textNode);
    const rects = range.getClientRects();
    for (let ri = 0; ri < rects.length; ri++) {
      allRects.push(rects[ri]);
    }
  }

  // Compute text-only content height for line-height normalization.
  // The full element height includes break anchors which are not text.
  let textContentHeight = domEl.offsetHeight || 0;
  try {
    const anchors = domEl.querySelectorAll?.('.koto-inline-page-break-anchor') || [];
    for (let ai = 0; ai < anchors.length; ai++) {
      textContentHeight -= anchors[ai]?.offsetHeight || 0;
    }
    textContentHeight = Math.max(1, textContentHeight);
  } catch (_) {}

  const lines = _normalizeDocxLineHeights(
    _groupDocxLineRects(allRects),
    textContentHeight,
  );
  if (lines.length < 2) return [];

  const resolved = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const startPos = index === 0
      ? nodeStart
      : _resolveDocxLineStartPos(view, line, nodeStart, nodeEnd);
    if (index > 0 && (!Number.isFinite(startPos) || startPos <= nodeStart || startPos >= nodeEnd)) {
      return [];
    }
    resolved.push({ ...line, startPos });
  }

  return resolved;
}

function _sumDocxLineHeights(lines, startIndex, count) {
  let total = 0;
  for (let idx = 0; idx < count; idx += 1) {
    total += lines[startIndex + idx]?.height || 0;
  }
  return total;
}

function _advanceDocxPageUsage(usedH, addedH, contentH, pageNum) {
  let nextUsed = usedH + addedH;
  let nextPage = pageNum;
  if (nextUsed >= contentH) {
    const overflow = nextUsed - contentH;
    if (overflow > 0) {
      const extra = Math.floor(overflow / contentH);
      nextPage += 1 + extra;
      nextUsed = overflow % contentH;
    } else {
      // Keep an exactly-full page pending. The following block will see zero
      // remaining space and insert the real boundary before it. Advancing the
      // counter here created a phantom page with no DOM separator.
      nextUsed = contentH;
    }
  }
  return { usedH: nextUsed, pageNum: nextPage };
}

function _planDocxTextBlockBreaks(view, node, start, domEl, usedH, contentH, pageNum, sectionIdx) {
  if (!node?.isTextblock || node.type?.name !== 'paragraph') return null;
  if (!node.textContent || !String(node.textContent).trim()) return null;

  const nodeStart = start + 1;
  const nodeEnd = start + node.nodeSize - 1;
  const lines = _collectDocxTextBlockLines(view, domEl, nodeStart, nodeEnd);
  if (lines.length < (_AUTO_PB_MIN_LINES_PER_FRAGMENT * 2)) return null;

  const margins = _measureVerticalMarginsPx(domEl);
  const plannedBreaks = [];
  let lineIndex = 0;
  let currentUsed = usedH;
  let currentPage = pageNum;
  let firstFragment = true;

  while (lineIndex < lines.length) {
    const remainingSpace = contentH - currentUsed;
    const marginTop = firstFragment ? margins.top : 0;
    let fitCount = 0;

    while ((lineIndex + fitCount) < lines.length) {
      const nextCount = fitCount + 1;
      const isFinalFragment = (lineIndex + nextCount) >= lines.length;
      const candidateHeight = marginTop
        + _sumDocxLineHeights(lines, lineIndex, nextCount)
        + (isFinalFragment ? margins.bottom : 0);
      if (candidateHeight > remainingSpace + 0.5) break;
      fitCount = nextCount;
    }

    if (fitCount <= 0) return null;

    const remainingLines = lines.length - lineIndex;
    const remainingAfterFit = remainingLines - fitCount;
    const maxFitWithoutWidow = remainingLines - _AUTO_PB_MIN_LINES_PER_FRAGMENT;
    if (remainingAfterFit > 0 && fitCount > maxFitWithoutWidow) {
      fitCount = maxFitWithoutWidow;
    }
    if (remainingAfterFit > 0 && fitCount < _AUTO_PB_MIN_LINES_PER_FRAGMENT) {
      return null;
    }

    const isFinalFragment = (lineIndex + fitCount) >= lines.length;
    const fragmentHeight = marginTop
      + _sumDocxLineHeights(lines, lineIndex, fitCount)
      + (isFinalFragment ? margins.bottom : 0);

    if (isFinalFragment) {
      const advanced = _advanceDocxPageUsage(currentUsed, fragmentHeight, contentH, currentPage);
      return {
        breaks: plannedBreaks,
        usedH: advanced.usedH,
        pageNum: advanced.pageNum,
      };
    }

    const breakPos = lines[lineIndex + fitCount]?.startPos;
    if (!Number.isFinite(breakPos) || breakPos <= nodeStart || breakPos >= nodeEnd) {
      return null;
    }

    plannedBreaks.push({
      pos: breakPos,
      pageNum: currentPage,
      currentSectionIdx: sectionIdx,
      nextSectionIdx: sectionIdx,
      contentFillPx: Math.max(0, remainingSpace - fragmentHeight),
      inline: true,
    });
    currentPage += 1;
    currentUsed = 0;
    lineIndex += fitCount;
    firstFragment = false;
  }

  return {
    breaks: plannedBreaks,
    usedH: currentUsed,
    pageNum: currentPage,
  };
}

function _isTopLevelDocxPaginationBoundaryEl(element) {
  return !!(
    element
    && element.nodeType === 1
    && (
      element.matches?.(_DOCX_PAGE_BOUNDARY_SELECTOR)
      || element.hasAttribute('data-page-break')
      || element.classList?.contains('koto-table-page-break-row')
    )
  );
}

function _buildSoftBreakTableRow(pageNum, columnCount, headerHtml, footerHtml, marginTopPx, marginBottomPx, marginLeftPx, marginRightPx, pageWidthPx, extStorage, tableLeftOffsetPx, contentFillPx = 0) {
  const row = document.createElement('tr');
  row.className = 'koto-table-page-break-row';
  row.setAttribute('data-soft-page-break', String(pageNum));
  row.setAttribute('contenteditable', 'false');

  const cell = document.createElement('td');
  cell.className = 'koto-table-page-break-cell';
  cell.colSpan = Math.max(1, columnCount || 1);
  cell.setAttribute('contenteditable', 'false');

  const { dom: widget } = _buildDocxPageBreakWidget({
    pageNum,
    headerHtml,
    footerHtml,
    marginTopPx,
    marginBottomPx,
    marginLeftPx,
    marginRightPx,
    extStorage,
    contentFillPx,
  });
  _alignSoftBreakWidgetToRenderedPage(widget, tableLeftOffsetPx, pageWidthPx);
  widget.style.position = 'relative';
  widget.style.left = '0';
  widget.style.transform = 'none';
  cell.appendChild(widget);
  row.appendChild(cell);
  return row;
}

function _consumeTableRowspanState(activeRowspans, rowEl, columnCount) {
  const width = Math.max(1, Number(columnCount) || 1);
  const currentActive = Array.from({ length: width }, (_, idx) => Math.max(0, Number(activeRowspans?.[idx] || 0)));
  const nextActive = currentActive.map((span) => Math.max(0, span - 1));
  let colIdx = 0;

  for (const cellEl of Array.from(rowEl?.cells || [])) {
    while (colIdx < width && currentActive[colIdx] > 0) {
      colIdx += 1;
    }

    const colspan = Math.max(1, Number(cellEl?.colSpan) || 1);
    const rowspan = Math.max(1, Number(cellEl?.rowSpan) || 1);
    if (rowspan > 1) {
      for (let offset = 0; offset < colspan && colIdx + offset < width; offset += 1) {
        nextActive[colIdx + offset] = Math.max(nextActive[colIdx + offset], rowspan - 1);
      }
    }
    colIdx += colspan;
  }

  return nextActive;
}

function _collectTableRowPaginationGroups(domRows, pmRows, tableCols, tableEl, pmDom) {
  const groups = [];
  let activeRowspans = Array(Math.max(1, Number(tableCols) || 1)).fill(0);
  let currentGroup = null;

  for (let rowIdx = 0; rowIdx < domRows.length; rowIdx += 1) {
    const rowEl = domRows[rowIdx];
    const rowPos = pmRows[rowIdx]?.pos;
    const incomingRowspan = activeRowspans.some((span) => span > 0);

    if (rowPos != null) {
      if (!currentGroup || !incomingRowspan) {
        const rowAnchorEl = rowEl?.cells && rowEl.cells.length
          ? rowEl.cells[0]
          : tableEl;
        currentGroup = {
          pos: rowPos,
          height: 0,
          tableLeftOffsetPx: _measureRelativeLeftPx(rowAnchorEl, pmDom),
        };
        groups.push(currentGroup);
      }

      currentGroup.height += rowEl?.offsetHeight || 0;
    }

    activeRowspans = _consumeTableRowspanState(activeRowspans, rowEl, tableCols);
  }

  return groups;
}

export const AutoPageBreakPlugin = Extension.create({
  name: 'autoPageBreak',

  addStorage() {
    return {
      pageWidthPx:       null,
      pageHeightPx:      null,
      marginTopPx:       null,
      marginBottomPx:    null,
      marginLeftPx:      null,
      marginRightPx:     null,
      headerHtml:        '',
      footerHtml:        '',
      sections:          [],      // per-section header/footer data from backend
      totalPages:        1,
      onPageCountChange: null,
    };
  },

  addProseMirrorPlugins() {
    const extStorage = this.storage;  // mutable reference, updated by KotoTipTapEditor

    return [new Plugin({
      key: _AUTO_PB_KEY,

      // ── Plugin state: holds the current DecorationSet ──────────────────
      state: {
        init() {
          return DecorationSet.empty;
        },
        apply(tr, decoSet) {
          // When measurement result arrives (via setMeta), replace the set
          const newSet = tr.getMeta(_AUTO_PB_KEY);
          if (newSet !== undefined) return newSet;
          // Otherwise map existing decorations through any content changes
          if (!tr.docChanged) return decoSet;
          return decoSet.map(tr.mapping, tr.doc);
        },
      },

      // ── Provide decorations to ProseMirror ─────────────────────────────
      props: {
        decorations(state) {
          return _AUTO_PB_KEY.getState(state);
        },
      },

      // ── View plugin: triggers measurement after DOM settles ────────────
      view(editorView) {
        let _measuring = false;  // guard against re-entrant measurement
        // A document's node tree is not a layout cache key. Fonts, images,
        // style commands and the available editor width can all change the
        // rendered heights without changing node text or nodeSize. Reusing
        // old break positions here was the reason a stale blank page could
        // remain visible after the document had reflowed.
        let _lastLayoutSignature = null;

        const _measure = (view) => {
          if (_measuring) return;
          _measuring = true;
          try {
            _measureClean(view);
          } finally {
            _measuring = false;
          }
        };

        const _measureClean = (view) => {
          const doc    = view.state.doc;
          const pmDom  = view.dom;

          const pageW      = extStorage.pageWidthPx    || 816;
          const pageH      = extStorage.pageHeightPx   || 1056;
          const mTop       = extStorage.marginTopPx    || 96;
          const mBot       = extStorage.marginBottomPx || 80;
          const mLeft      = extStorage.marginLeftPx   || 96;
          const mRight     = extStorage.marginRightPx  || 96;
          const hdrHtml    = extStorage.headerHtml     || '';
          const ftrHtml    = extStorage.footerHtml     || '';
          const sectionsAr = extStorage.sections       || [];
          const contentH   = pageH - mTop - mBot;
          // The editor surface has one concrete page box. Section-specific
          // margins may change header/footer placement, but must not resize
          // the page-break chrome beyond that rendered sheet.
          const pageGeometry = _resolveRenderedDocxPageGeometry(pmDom, pageW, mLeft);
          const renderedPageWidthPx = pageGeometry.pageWidthPx;
          const renderedContentLeftPx = pageGeometry.contentLeftPx;

          pmDom.style.paddingBottom = `${mBot}px`;

          const docNodes = [];
          doc.content.forEach((node, start) => {
            docNodes.push({ node, start });
          });

          const pmChildren = Array.from(pmDom.children);
          let pmIdx = 0;

          const breaks = [];   // { pos, pageNum, currentSectionIdx, nextSectionIdx, tableCols?, tableLeftOffsetPx? }
          let pageNum = 1;
          let usedH = 0;
          let curSection = 0;

          for (const { node, start } of docNodes) {
            let domEl;
            if (node.type.name === 'docxPageBreak') {
              while (pmIdx < pmChildren.length) {
                const candidate = pmChildren[pmIdx];
                pmIdx++;
                if (candidate?.hasAttribute?.('data-page-break')) {
                  domEl = candidate;
                  break;
                }
              }
            } else {
              while (
                pmIdx < pmChildren.length &&
                _isTopLevelDocxPaginationBoundaryEl(pmChildren[pmIdx])
              ) {
                pmIdx++;
              }
              domEl = pmChildren[pmIdx];
              pmIdx++;
            }

            if (!domEl) break;

            if (node.type.name === 'docxPageBreak') {
            const nextSection = Math.max(0, Number.parseInt(node.attrs.nextSectionIdx ?? node.attrs.sectionIdx, 10) || curSection);
            _applyMeasuredExplicitBreakState(
              domEl,
              pageNum,
              curSection,
              nextSection,
              Math.max(0, usedH > 0 ? (contentH - usedH) : contentH),
            );
            curSection = nextSection;
              pageNum++;
              usedH = 0;
              continue;
            }

            if (node.type.name === 'table') {
              const tableEl = domEl?.tagName === 'TABLE'
                ? domEl
                : domEl?.querySelector?.('table');
              const domRows = tableEl
                ? Array.from(tableEl.rows || []).filter((rowEl) => !_isTopLevelDocxPaginationBoundaryEl(rowEl))
                : [];
              const pmRows = [];

              node.forEach((rowNode, rowOffset) => {
                if (rowNode.type?.name === 'tableRow') {
                  pmRows.push({ pos: start + 1 + rowOffset });
                }
              });

              if (domRows.length && domRows.length === pmRows.length) {
                const tableCols = Math.max(1, TableMap.get(node).width || 1);

                const tableGroups = _collectTableRowPaginationGroups(
                  domRows,
                  pmRows,
                  tableCols,
                  tableEl,
                  pmDom,
                );

                for (const group of tableGroups) {
                  const groupH = group?.height || 0;
                  if (groupH <= 0 || group?.pos == null) continue;

                  const remaining = contentH - usedH;
                  if (usedH > 0 && groupH > remaining) {
                    breaks.push({
                      pos: group.pos,
                      pageNum,
                      currentSectionIdx: curSection,
                      nextSectionIdx: curSection,
                      contentFillPx: Math.max(0, remaining),
                      tableCols,
                      tableLeftOffsetPx: group.tableLeftOffsetPx,
                    });
                    pageNum++;
                    usedH = groupH;
                  } else {
                    usedH += groupH;
                  }

                  if (usedH >= contentH) {
                    const overflow = usedH - contentH;
                    if (overflow > 0) {
                      // An unsplittable row/rowspan group may be taller than
                      // the content box. Do not invent invisible pages; keep
                      // this page full so the next row group creates a real
                      // row-level boundary.
                      usedH = contentH;
                    } else {
                      usedH = contentH;
                    }
                  }
                }
                continue;
              }
            }

            let blockH = _measureDocxBlockOuterHeightPx(domEl);

            if (blockH <= 0) continue;

            const remaining = contentH - usedH;
            // A paragraph taller than a full content page must be fragmented
            // even when it starts at the top of a fresh page (usedH === 0).
            // The old guard only entered this branch when prior content had
            // consumed space, producing a multi-page count with no visible
            // boundaries for page-starting long paragraphs.
            if (blockH > remaining && (usedH > 0 || blockH > contentH)) {
              if (!_docxBlockAvoidsAutoSplit(node, domEl)) {
                const textPlan = _planDocxTextBlockBreaks(
                  view,
                  node,
                  start,
                  domEl,
                  usedH,
                  contentH,
                  pageNum,
                  curSection,
                );
                if (textPlan && Array.isArray(textPlan.breaks) && textPlan.breaks.length) {
                  const pageLeftOffsetPx = _measureRelativeLeftPx(domEl, pmDom);
                  breaks.push(...textPlan.breaks.map((plannedBreak) => ({
                    ...plannedBreak,
                    pageLeftOffsetPx,
                  })));
                  pageNum = textPlan.pageNum;
                  usedH = textPlan.usedH;
                  continue;
                }
              }

              breaks.push({
                pos: start,
                pageNum,
                currentSectionIdx: curSection,
                nextSectionIdx: curSection,
                contentFillPx: Math.max(0, remaining),
              });
              pageNum++;

              if (blockH > contentH) {
                // This block has no safe internal split position. It occupies
                // one visual page even if it overflows the ideal content box;
                // never advance through pages that have no rendered boundary.
                usedH = contentH;
              } else {
                usedH = blockH;
              }
            } else {
              usedH += blockH;
              if (usedH >= contentH) {
                const overflow = usedH - contentH;
                if (overflow > 0) {
                  // Non-text blocks that cannot be fragmented stay on one
                  // visual page. Leave it full; the next block will create a
                  // concrete boundary instead of skipping page numbers.
                  usedH = contentH;
                } else {
                  usedH = contentH;
                }
              }
            }
          }

          const total = pageNum;
          const finalContentFillPx = usedH > 0 ? Math.max(0, contentH - usedH) : 0;
          pmDom.style.paddingBottom = `${mBot + finalContentFillPx}px`;
          extStorage.totalPages = total;
          if (typeof extStorage.onPageCountChange === 'function') {
            extStorage.onPageCountChange(total);
          }

          let decoSet;
          if (breaks.length === 0) {
            decoSet = DecorationSet.empty;
          } else {
            const decos = breaks.map(({ pos, pageNum: pn, currentSectionIdx: csi, nextSectionIdx: nsi, contentFillPx, tableCols, tableLeftOffsetPx, pageLeftOffsetPx, inline }) => {
              const breakChrome = resolveDocxBreakChrome(extStorage, pn, csi, nsi);
              return Decoration.widget(
                pos,
                () => {
                  const breakDom = tableCols
                    ? _buildSoftBreakTableRow(
                      pn,
                      tableCols,
                      breakChrome.nextPage.headerHtml,
                      breakChrome.currentPage.footerHtml,
                      breakChrome.marginTopPx,
                      breakChrome.marginBottomPx,
                      breakChrome.marginLeftPx,
                      breakChrome.marginRightPx,
                      renderedPageWidthPx,
                      extStorage,
                      tableLeftOffsetPx,
                      contentFillPx,
                    )
                    : inline
                      ? _buildInlineSoftBreakWidget(
                        pn,
                        breakChrome.nextPage.headerHtml,
                        breakChrome.currentPage.footerHtml,
                        breakChrome.marginTopPx,
                        breakChrome.marginBottomPx,
                        breakChrome.marginLeftPx,
                        breakChrome.marginRightPx,
                        renderedPageWidthPx,
                        extStorage,
                        pageLeftOffsetPx,
                        contentFillPx,
                      )
                      : _buildDocxPageBreakWidget({
                        pageNum: pn,
                        headerHtml: breakChrome.nextPage.headerHtml,
                        footerHtml: breakChrome.currentPage.footerHtml,
                        marginTopPx: breakChrome.marginTopPx,
                        marginBottomPx: breakChrome.marginBottomPx,
                        marginLeftPx: breakChrome.marginLeftPx,
                        marginRightPx: breakChrome.marginRightPx,
                        extStorage,
                        contentFillPx,
                      }).dom;
                  if (!tableCols && !inline) {
                    _alignSoftBreakWidgetToRenderedPage(
                      breakDom,
                      renderedContentLeftPx,
                      renderedPageWidthPx,
                    );
                  }
                  const breakRoot = breakDom.matches?.(_DOCX_SOFT_PAGE_BREAK_SELECTOR)
                    ? breakDom
                    : breakDom.querySelector?.(_DOCX_SOFT_PAGE_BREAK_SELECTOR);
                  if (breakRoot) {
                    breakRoot.setAttribute('data-section-idx', String(Math.max(0, Number.parseInt(nsi, 10) || 0)));
                    breakRoot.setAttribute('data-current-section-idx', String(Math.max(0, Number.parseInt(csi, 10) || 0)));
                    breakRoot.setAttribute('data-next-section-idx', String(Math.max(0, Number.parseInt(nsi, 10) || 0)));
                    breakRoot.setAttribute('data-content-fill-px', String(Math.round(_normalizeDocxBreakFillPx(contentFillPx))));
                  }
                  breakDom.querySelectorAll('.koto-pb-footer').forEach((el) => {
                    el.dataset.variant = breakChrome.currentPage.footerVariant || 'default';
                    el.querySelectorAll('.koto-hdr-page-num').forEach((pageEl) => {
                      pageEl.textContent = String(pn);
                      pageEl.setAttribute('contenteditable', 'false');
                    });
                  });
                  breakDom.querySelectorAll('.koto-pb-header').forEach((el) => {
                    el.dataset.variant = breakChrome.nextPage.headerVariant || 'default';
                    el.querySelectorAll('.koto-hdr-page-num').forEach((pageEl) => {
                      pageEl.textContent = String(pn + 1);
                      pageEl.setAttribute('contenteditable', 'false');
                    });
                  });
                  return breakDom;
                },
                {
                  side:             -1,
                  key:              `spb-${pos}-${pn}`,
                  stopEvent:        () => true,
                  ignoreSelection:  true,
                  destroy:          (dom) => { dom.remove(); },
                },
              );
            });
            decoSet = DecorationSet.create(doc, decos);
          }

          // Dispatch only when the *rendered* pagination changes.  The
          // signature deliberately includes fill height and page chrome, not
          // only positions: a different remaining height with the same break
          // position otherwise leaves a large stale white region in place.
          const layoutSignature = JSON.stringify({
            pageW: Math.round(renderedPageWidthPx * 100) / 100,
            contentLeft: Math.round(renderedContentLeftPx * 100) / 100,
            pageH,
            mTop,
            mBot,
            mLeft,
            mRight,
            hdrHtml,
            ftrHtml,
            sectionsAr,
            finalContentFillPx: Math.round(finalContentFillPx * 100) / 100,
            breaks: breaks.map((entry) => [
              entry.pos,
              entry.pageNum,
              entry.currentSectionIdx,
              entry.nextSectionIdx,
              Math.round(_normalizeDocxBreakFillPx(entry.contentFillPx) * 100) / 100,
              entry.tableCols || 0,
              Math.round((entry.tableLeftOffsetPx || 0) * 100) / 100,
              Math.round((entry.pageLeftOffsetPx || 0) * 100) / 100,
              entry.inline ? 1 : 0,
            ]),
          });
          if (layoutSignature !== _lastLayoutSignature) {
            _lastLayoutSignature = layoutSignature;
            view.dispatch(view.state.tr.setMeta(_AUTO_PB_KEY, decoSet));
          }
        };

        const _scheduler = createDocxPaginationScheduler({
          view: editorView,
          measure: () => _measure(editorView),
          initialDelayMs: _AUTO_PB_INITIAL_DELAY_MS,
          updateDelayMs: _AUTO_PB_UPDATE_DELAY_MS,
        });
        _scheduler.start();

        return {
          update(view, prevState) {
            // Only re-measure when doc content changed (not on meta dispatches)
            if (view.state.doc !== prevState.doc) {
              _scheduler.onDocumentChanged(view);
            }
          },
          destroy() {
            _scheduler.destroy();
            _lastLayoutSignature = null;
          },
        };
      },
    })];
  },
});
