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

export const DOCX_ROW_RESIZE_SKIP_AUTOSAVE_META = 'kotoDocxRowResizeSkipAutoSave';
export const DOCX_TABLE_RESIZE_TRANSACTION_META = 'kotoDocxTableResizeTransaction';

function _docxSetResizeUiState(active, settleMs = 160) {
  if (typeof window === 'undefined') return;
  window.__kotoDocxTableResizeUiState = {
    active: !!active,
    suppressUntil: active ? 0 : (Date.now() + Math.max(0, settleMs)),
  };
}

function _docxDomCellAround(target) {
  while (target && target.nodeName !== 'TD' && target.nodeName !== 'TH') {
    target = target.classList && target.classList.contains('ProseMirror')
      ? null
      : target.parentNode;
  }
  return target;
}

function _docxCellFromTableGeometry(target, clientX, clientY) {
  const baseTarget = target?.nodeType === 1 ? target : target?.parentElement;
  const table = baseTarget?.nodeName === 'TABLE' ? baseTarget : baseTarget?.closest?.('table');
  if (!table) return null;
  const paintScale = window.KotoUiScale.getElementPaintScale(table);
  const maxDx = 8 * paintScale.x;
  const maxDy = 8 * paintScale.y;

  let bestCell = null;
  let bestScore = Number.POSITIVE_INFINITY;
  const cells = table.querySelectorAll('td,th');
  for (const cell of cells) {
    const rect = cell.getBoundingClientRect();
    const dx = clientX < rect.left ? rect.left - clientX : clientX > rect.right ? clientX - rect.right : 0;
    const dy = clientY < rect.top ? rect.top - clientY : clientY > rect.bottom ? clientY - rect.bottom : 0;
    if (dx > maxDx || dy > maxDy) continue;
    const score = (dy * 1000) + dx;
    if (score < bestScore) {
      bestScore = score;
      bestCell = cell;
    }
  }

  return bestCell;
}

function _docxCellAroundEvent(view, event, sampleOffsets = [[0, 0]]) {
  const directTarget = _docxDomCellAround(event?.target);
  if (directTarget) return directTarget;

  const clientX = Number(event?.clientX);
  const clientY = Number(event?.clientY);
  if (!Number.isFinite(clientX) || !Number.isFinite(clientY)) return null;

  const geometricCell = _docxCellFromTableGeometry(event?.target, clientX, clientY);
  if (geometricCell) return geometricCell;

  const doc = view.dom.ownerDocument;
  for (const [offsetX, offsetY] of sampleOffsets) {
    const el = doc.elementFromPoint(clientX + offsetX, clientY + offsetY);
    const cell = _docxDomCellAround(el);
    if (cell) return cell;
  }

  for (const [offsetX, offsetY] of sampleOffsets) {
    const resolvedPos = view.posAtCoords({
      left: clientX + offsetX,
      top: clientY + offsetY,
    });
    if (!resolvedPos) continue;
    try {
      const $cell = cellAround(view.state.doc.resolve(resolvedPos.pos));
      if (!$cell) continue;
      const cellEl = view.nodeDOM($cell.pos);
      if (cellEl?.nodeName === 'TD' || cellEl?.nodeName === 'TH') {
        return cellEl;
      }
    } catch (_) {}
  }

  return null;
}

function _docxEdgeCell(view, event, side, handleWidth) {
  const paintScale = window.KotoUiScale.getElementPaintScale(view.dom);
  const visualHandleWidth = handleWidth * paintScale.x;
  const offset = side === 'right' ? -visualHandleWidth : visualHandleWidth;
  const found = view.posAtCoords({
    left: event.clientX + offset,
    top: event.clientY,
  });
  if (!found) return -1;
  const $cell = cellAround(view.state.doc.resolve(found.pos));
  if (!$cell) return -1;
  if (side === 'right') return $cell.pos;
  const map = TableMap.get($cell.node(-1));
  const start = $cell.start(-1);
  const index = map.map.indexOf($cell.pos - start);
  return index % map.width === 0 ? -1 : start + map.map[index - 1];
}

function _docxNormalizeHandleCellToColumnAnchor(doc, cellPos) {
  if (cellPos < 0) return -1;
  try {
    const $cell = doc.resolve(cellPos);
    if (!pointsAtCell($cell)) return -1;
    const table = $cell.node(-1);
    const map = TableMap.get(table);
    const tableStart = $cell.start(-1);
    const col = map.colCount($cell.pos - tableStart) + $cell.nodeAfter.attrs.colspan - 1;
    const anchor = map.map[col];
    return anchor == null ? cellPos : tableStart + anchor;
  } catch (_) {
    return cellPos;
  }
}

function _docxDraggedWidth(dragging, event, resizeMinWidth) {
  const offset = (event.clientX - dragging.startX) / (dragging.paintScaleX || 1);
  return Math.max(resizeMinWidth, dragging.startWidth + offset);
}

function _docxIsPrimaryPointerStillDown(mouseEvent) {
  if (!mouseEvent) return false;
  if (typeof mouseEvent.buttons === 'number') {
    return (mouseEvent.buttons & 1) === 1;
  }
  if (typeof mouseEvent.which === 'number') {
    return mouseEvent.which === 1;
  }
  return true;
}

function _docxUpdateResizeHandle(view, value) {
  view.dispatch(view.state.tr.setMeta(columnResizingPluginKey, { setHandle: value }));
}

function _docxCurrentColWidth(view, cellPos, { colspan, colwidth }) {
  const width = colwidth && colwidth[colwidth.length - 1];
  if (width) return width;
  const dom = view.domAtPos(cellPos);
  let domWidth = dom.node.childNodes[dom.offset].offsetWidth;
  let parts = colspan;
  if (colwidth) {
    for (let i = 0; i < colspan; i += 1) {
      if (colwidth[i]) {
        domWidth -= colwidth[i];
        parts -= 1;
      }
    }
  }
  return domWidth / parts;
}

function _docxDisplayColumnWidth(view, cell, width, defaultCellMinWidth) {
  const $cell = view.state.doc.resolve(cell);
  const table = $cell.node(-1);
  const start = $cell.start(-1);
  const col = TableMap.get(table).colCount($cell.pos - start) + $cell.nodeAfter.attrs.colspan - 1;
  let dom = view.domAtPos($cell.start(-1)).node;
  while (dom && dom.nodeName !== 'TABLE') dom = dom.parentNode;
  if (!dom) return;
  updateColumnsOnResize(table, dom.firstChild, dom, defaultCellMinWidth, col, width);
}

function _docxUpdateColumnWidth(view, cell, width) {
  const $cell = view.state.doc.resolve(cell);
  const table = $cell.node(-1);
  const map = TableMap.get(table);
  const start = $cell.start(-1);
  const col = map.colCount($cell.pos - start) + $cell.nodeAfter.attrs.colspan - 1;
  const tr = view.state.tr;

  for (let row = 0; row < map.height; row += 1) {
    const mapIndex = row * map.width + col;
    if (row && map.map[mapIndex] === map.map[mapIndex - map.width]) continue;
    const pos = map.map[mapIndex];
    const attrs = table.nodeAt(pos).attrs;
    const index = attrs.colspan === 1 ? 0 : col - map.colCount(pos);
    if (attrs.colwidth && attrs.colwidth[index] === width) continue;
    const colwidth = attrs.colwidth ? attrs.colwidth.slice() : Array(attrs.colspan).fill(0);
    colwidth[index] = width;
    tr.setNodeMarkup(start + pos, null, {
      ...attrs,
      colwidth,
    });
  }

  if (tr.docChanged) {
    tr.setMeta(DOCX_TABLE_RESIZE_TRANSACTION_META, true);
    view.dispatch(tr);
  }
}

function _docxHandleMouseMove(view, event, handleWidth, lastColumnResizable) {
  if (!view.editable) return;
  const pluginState = columnResizingPluginKey.getState(view.state);
  if (!pluginState || pluginState.dragging) return;

  const target = _docxDomCellAround(event.target);
  let cell = -1;
  if (target) {
    const { left, right } = target.getBoundingClientRect();
  const visualHandleWidth = handleWidth * window.KotoUiScale.getElementPaintScale(view.dom).x;
  if (event.clientX - left <= visualHandleWidth) {
    cell = _docxEdgeCell(view, event, 'left', handleWidth);
  } else if (right - event.clientX <= visualHandleWidth) {
      cell = _docxEdgeCell(view, event, 'right', handleWidth);
    }
  }

  if (!lastColumnResizable && cell !== -1) {
    const $cell = view.state.doc.resolve(cell);
    const table = $cell.node(-1);
    const map = TableMap.get(table);
    const tableStart = $cell.start(-1);
    const lastCol = map.colCount($cell.pos - tableStart) + $cell.nodeAfter.attrs.colspan - 1;
    if (lastCol === map.width - 1) return;
  }

  const normalizedCell = _docxNormalizeHandleCellToColumnAnchor(view.state.doc, cell);
  if (normalizedCell !== pluginState.activeHandle) {
    _docxUpdateResizeHandle(view, normalizedCell);
  }
}

function _docxHandleMouseLeave(view) {
  if (!view.editable) return;
  const pluginState = columnResizingPluginKey.getState(view.state);
  if (pluginState && pluginState.activeHandle > -1 && !pluginState.dragging) {
    _docxUpdateResizeHandle(view, -1);
  }
}

function _docxHandleMouseDown(view, event, cellMinWidth, defaultCellMinWidth) {
  if (!view.editable) return false;
  const win = view.dom.ownerDocument.defaultView ?? window;
  const pluginState = columnResizingPluginKey.getState(view.state);
  if (!pluginState || pluginState.activeHandle === -1 || pluginState.dragging) return false;

  const cell = view.state.doc.nodeAt(pluginState.activeHandle);
  const width = _docxCurrentColWidth(view, pluginState.activeHandle, cell.attrs);
  const paintScale = window.KotoUiScale.getElementPaintScale(view.dom);
  _docxSetResizeUiState(true);
  view.dispatch(view.state.tr.setMeta(columnResizingPluginKey, {
    setDragging: { startX: event.clientX, startWidth: width, paintScaleX: paintScale.x },
  }));

  function finish(mouseEvent) {
    win.removeEventListener('mouseup', finish, true);
    win.removeEventListener('mousemove', move, true);
    _docxSetResizeUiState(false);
    const currentState = columnResizingPluginKey.getState(view.state);
    if (currentState?.dragging) {
      _docxUpdateColumnWidth(
        view,
        currentState.activeHandle,
        _docxDraggedWidth(currentState.dragging, mouseEvent, cellMinWidth),
      );
      view.dispatch(view.state.tr.setMeta(columnResizingPluginKey, { setDragging: null }));
    }
  }

  function move(mouseEvent) {
    if (!_docxIsPrimaryPointerStillDown(mouseEvent)) return finish(mouseEvent);
    const currentState = columnResizingPluginKey.getState(view.state);
    if (!currentState?.dragging) return;
    const dragged = _docxDraggedWidth(currentState.dragging, mouseEvent, cellMinWidth);
    _docxDisplayColumnWidth(view, currentState.activeHandle, dragged, defaultCellMinWidth);
  }

  _docxDisplayColumnWidth(view, pluginState.activeHandle, width, defaultCellMinWidth);
  win.addEventListener('mouseup', finish, true);
  win.addEventListener('mousemove', move, true);
  event.preventDefault();
  return true;
}

export function createDocxSafeColumnResizing({
  handleWidth = 5,
  cellMinWidth = 25,
  defaultCellMinWidth = 100,
  View = TableView,
  lastColumnResizable = true,
} = {}) {
  const plugin = new Plugin({
    key: columnResizingPluginKey,
    state: {
      init(_, state) {
        const nodeViews = plugin.spec?.props?.nodeViews;
        const tableName = tableNodeTypes(state.schema).table.name;
        if (View && nodeViews) {
          nodeViews[tableName] = (node, view) => new View(node, defaultCellMinWidth, view);
        }
        return new ResizeState(-1, false);
      },
      apply(tr, prev) {
        return prev.apply(tr);
      },
    },
    props: {
      attributes: state => {
        const pluginState = columnResizingPluginKey.getState(state);
        return pluginState && pluginState.activeHandle > -1 ? { class: 'resize-cursor' } : {};
      },
      handleDOMEvents: {
        mousemove: (view, event) => _docxHandleMouseMove(view, event, handleWidth, lastColumnResizable),
        mouseleave: view => _docxHandleMouseLeave(view),
        mousedown: (view, event) => _docxHandleMouseDown(view, event, cellMinWidth, defaultCellMinWidth),
      },
      // Keep the DOM stable on hover: width dragging only needs activeHandle + cursor,
      // not the injected widget decorations from the stock plugin.
      decorations: () => undefined,
      nodeViews: {},
    },
  });

  return plugin;
}

export const DocxTable = Table.extend({
  addOptions() {
    return {
      ...this.parent?.(),
      resizable: true,
      handleWidth: 5,
      cellMinWidth: 25,
      View: TableView,
      lastColumnResizable: true,
      rowResizable: true,
      rowHandleHeight: 5,
      rowMinHeight: 18,
    };
  },

  addProseMirrorPlugins() {
    const isResizable = this.options.resizable && this.editor.isEditable;
    const isRowResizable = this.options.rowResizable && this.editor.isEditable;
    return [
      ...(isResizable
        ? [createDocxSafeColumnResizing({
            handleWidth: this.options.handleWidth,
            cellMinWidth: this.options.cellMinWidth,
            defaultCellMinWidth: this.options.cellMinWidth,
            View: this.options.View,
            lastColumnResizable: this.options.lastColumnResizable,
          })]
        : []),
      ...(isRowResizable
        ? [createDocxSafeRowResizing({
            handleHeight: this.options.rowHandleHeight,
            rowMinHeight: this.options.rowMinHeight,
          })]
        : []),
      tableEditing({
        allowTableNodeSelection: this.options.allowTableNodeSelection,
      }),
    ];
  },
});

const _DOCX_ROW_RESIZE_KEY = new PluginKey('docxTableRowResizing');

class _DocxRowResizeState {
  constructor(activeRowPos, dragging) {
    this.activeRowPos = activeRowPos;
    this.dragging = dragging;
  }

  apply(tr) {
    const action = tr.getMeta(_DOCX_ROW_RESIZE_KEY);
    if (action) {
      let activeRowPos = this.activeRowPos;
      let dragging = this.dragging;
      if (action.setRow !== undefined) {
        activeRowPos = action.setRow;
        dragging = false;
      }
      if (Object.prototype.hasOwnProperty.call(action, 'setDragging')) {
        dragging = action.setDragging;
      }
      return new _DocxRowResizeState(activeRowPos, dragging);
    }
    if (this.activeRowPos > -1 && tr.docChanged) {
      let rowPos = tr.mapping.map(this.activeRowPos, -1);
      const rowNode = tr.doc.nodeAt(rowPos);
      if (!rowNode || rowNode.type?.spec?.tableRole !== 'row') {
        rowPos = -1;
      }
      return new _DocxRowResizeState(rowPos, this.dragging);
    }
    return this;
  }
}

function _docxResolveRowInfoFromRowPos(doc, rowPos) {
  if (rowPos < 0) return null;
  let found = null;
  try {
    doc.descendants((node, pos) => {
      if (found) return false;
      if (node.type?.spec?.tableRole !== 'table') return true;
      node.forEach((rowNode, rowOffset, index) => {
        if (found) return;
        const currentRowPos = pos + 1 + rowOffset;
        if (currentRowPos === rowPos) {
          found = {
            tablePos: pos,
            rowPos: currentRowPos,
            rowIndex: index,
            rowNode,
          };
        }
      });
      return !found;
    });
  } catch (_) {
    return null;
  }
  return found;
}

function _docxTableDomFromPos(view, tablePos) {
  const dom = view.nodeDOM(tablePos);
  if (!dom || dom.nodeType !== 1) return null;
  if (dom.nodeName === 'TABLE') return dom;
  return dom.querySelector?.('table') || dom.closest?.('table') || null;
}

function _docxResolveResizeRowElementFromDocRow(view, rowPos) {
  const rowInfo = _docxResolveRowInfoFromRowPos(view.state.doc, rowPos);
  if (!rowInfo) return null;
  const tableEl = _docxTableDomFromPos(view, rowInfo.tablePos);
  const rowEl = tableEl?.querySelectorAll?.('tr')?.[rowInfo.rowIndex] || null;
  return rowEl?.nodeName === 'TR' ? rowEl : null;
}

function _docxCssLengthToPx(value) {
  const raw = String(value || '').trim();
  if (!raw) return null;
  const match = raw.match(/^(-?\d+(?:\.\d+)?)(px|pt)?$/i);
  if (!match) return null;
  const numeric = parseFloat(match[1]);
  if (!Number.isFinite(numeric) || numeric <= 0) return null;
  const unit = (match[2] || 'px').toLowerCase();
  return unit === 'pt' ? numeric * 96 / 72 : numeric;
}

function _docxPxToPtString(valuePx) {
  const pt = Math.max(1, valuePx * 72 / 96);
  const rounded = Number(pt.toFixed(2));
  return `${rounded}pt`;
}

function _docxCellPosFromDom(view, cellEl) {
  try {
    const pos = view.posAtDOM(cellEl, 0);
    const $cell = cellAround(view.state.doc.resolve(pos));
    return $cell ? $cell.pos : -1;
  } catch (_) {
    return -1;
  }
}

function _docxResolveRowInfoFromCellPos(doc, cellPos) {
  if (cellPos < 0) return null;
  try {
    const $cell = doc.resolve(cellPos);
    let rowDepth = -1;
    let tableDepth = -1;
    for (let depth = $cell.depth; depth > 0; depth -= 1) {
      const role = $cell.node(depth).type?.spec?.tableRole;
      if (rowDepth < 0 && role === 'row') rowDepth = depth;
      if (tableDepth < 0 && role === 'table') tableDepth = depth;
    }
    if (rowDepth < 0 || tableDepth < 0) return null;

    const rowPos = $cell.before(rowDepth);
    const tablePos = $cell.before(tableDepth);
    const tableNode = $cell.node(tableDepth);
    const rows = [];

    tableNode.forEach((rowNode, rowOffset, index) => {
      rows.push({
        index,
        pos: tablePos + 1 + rowOffset,
        node: rowNode,
      });
    });

    const currentRow = rows.find(row => row.pos === rowPos) || null;
    if (!currentRow) return null;

    return {
      rowPos: currentRow.pos,
      rowIndex: currentRow.index,
      rowNode: currentRow.node,
      rows,
    };
  } catch (_) {
    return null;
  }
}

function _docxGetResizeRowPos(view, event, handleHeight) {
  const visualHandleHeight = handleHeight * window.KotoUiScale.getElementPaintScale(view.dom).y;
  const cellEl = _docxCellAroundEvent(view, event, [
    [0, 0],
    [0, -1],
    [0, 1],
    [0, -visualHandleHeight],
    [0, visualHandleHeight],
    [-1, 0],
    [1, 0],
  ]);
  if (!cellEl) return -1;

  const rect = cellEl.getBoundingClientRect();
  const topDistance = event.clientY - rect.top;
  const bottomDistance = rect.bottom - event.clientY;
  if (topDistance > visualHandleHeight && bottomDistance > visualHandleHeight) return -1;

  const cellPos = _docxCellPosFromDom(view, cellEl);
  const rowInfo = _docxResolveRowInfoFromCellPos(view.state.doc, cellPos);
  if (!rowInfo) return -1;

  let targetRowIndex = rowInfo.rowIndex;
  if (topDistance <= visualHandleHeight && bottomDistance <= visualHandleHeight) {
    targetRowIndex = topDistance <= bottomDistance ? rowInfo.rowIndex - 1 : rowInfo.rowIndex;
  } else if (topDistance <= visualHandleHeight) {
    targetRowIndex = rowInfo.rowIndex - 1;
  }

  const target = rowInfo.rows.find(row => row.index === targetRowIndex);
  return target ? target.pos : -1;
}

function _docxCurrentRowHeight(view, rowPos, rowNode) {
  const fromAttrs = _docxCssLengthToPx(rowNode?.attrs?.rowHeight || rowNode?.attrs?.exactRowHeight);
  if (Number.isFinite(fromAttrs)) return fromAttrs;
  const rowEl = view.nodeDOM(rowPos);
  if (rowEl && rowEl.nodeType === 1) {
    return rowEl.getBoundingClientRect().height || rowEl.offsetHeight || 24;
  }
  return 24;
}

function _docxResolveResizeRowElementFromCell(view, cellEl, rowPos) {
  if (!cellEl) return null;
  const rowEl = cellEl.closest('tr');
  if (!rowEl) return null;

  const cellPos = _docxCellPosFromDom(view, cellEl);
  const rowInfo = _docxResolveRowInfoFromCellPos(view.state.doc, cellPos);
  if (!rowInfo) return rowEl.nodeName === 'TR' ? rowEl : null;
  if (rowInfo.rowPos === rowPos) return rowEl;

  const previousRow = rowInfo.rows.find(row => row.index === rowInfo.rowIndex - 1);
  if (previousRow?.pos === rowPos) {
    const prevDom = rowEl.previousElementSibling;
    if (prevDom?.nodeName === 'TR') return prevDom;
  }
  return null;
}

function _docxResolveLiveResizeRowElement(view, event, rowPos) {
  const directRow = _docxResolveResizeRowElementFromCell(view, _docxDomCellAround(event?.target), rowPos);
  if (directRow) return directRow;

  const docRow = _docxResolveResizeRowElementFromDocRow(view, rowPos);
  if (docRow) return docRow;

  const sampledCell = _docxCellAroundEvent(view, event, [
    [0, 0],
    [0, -1],
    [0, 1],
    [-1, 0],
    [1, 0],
    [0, -4],
    [0, 4],
  ]);
  const sampledRow = _docxResolveResizeRowElementFromCell(view, sampledCell, rowPos);
  if (sampledRow) return sampledRow;

  const domFromPos = view.nodeDOM(rowPos);
  if (domFromPos?.nodeType === 1) {
    const rowFromPos = domFromPos.nodeName === 'TR' ? domFromPos : domFromPos.closest?.('tr');
    if (rowFromPos?.nodeName === 'TR') return rowFromPos;
  }
  return null;
}

function _docxRefreshLiveResizeRowElement(view, event, rowPos, rowEl) {
  const docRow = _docxResolveResizeRowElementFromDocRow(view, rowPos);
  if (docRow) return docRow;
  if (rowEl?.isConnected && rowEl.nodeName === 'TR') {
    return rowEl;
  }
  return _docxResolveLiveResizeRowElement(view, event, rowPos);
}

function _docxApplyLiveRowHeightPreview(rowEl, heightPx, view = null) {
  if (!rowEl || rowEl.nodeName !== 'TR') return;
  const height = `${Math.max(8, heightPx)}px`;
  const observer = view?.domObserver;
  const canPauseObserver = observer && typeof observer.stop === 'function' && typeof observer.start === 'function';
  if (canPauseObserver) observer.stop();
  try {
    rowEl.style.height = height;
    rowEl.style.minHeight = height;
    Array.from(rowEl.children || []).forEach(cell => {
      if (!(cell instanceof HTMLElement)) return;
      cell.style.height = height;
      cell.style.minHeight = height;
    });
  } finally {
    if (canPauseObserver) observer.start();
  }
}

function _docxClearLiveRowHeightPreview(rowEl) {
  if (!rowEl || rowEl.nodeName !== 'TR') return;
  rowEl.style.removeProperty('height');
  rowEl.style.removeProperty('min-height');
  Array.from(rowEl.children || []).forEach(cell => {
    if (!(cell instanceof HTMLElement)) return;
    cell.style.removeProperty('height');
    cell.style.removeProperty('min-height');
  });
}

function _docxUpdateRowHeight(view, rowPos, heightPx) {
  const rowNode = view.state.doc.nodeAt(rowPos);
  if (!rowNode) return;
  const nextHeight = _docxPxToPtString(heightPx);
  if (rowNode.attrs.rowHeight === nextHeight && rowNode.attrs.exactRowHeight === nextHeight) {
    return;
  }
  view.dispatch(view.state.tr
    .setNodeMarkup(rowPos, null, {
      ...rowNode.attrs,
      rowHeight: nextHeight,
      exactRowHeight: nextHeight,
    })
    .setMeta(DOCX_TABLE_RESIZE_TRANSACTION_META, true)
    .setMeta(DOCX_ROW_RESIZE_SKIP_AUTOSAVE_META, true));
}

function _docxDraggedRowHeight(dragging, event, rowMinHeight) {
  const offset = (event.clientY - dragging.startY) / (dragging.paintScaleY || 1);
  return Math.max(rowMinHeight, dragging.startHeight + offset);
}

function _docxUpdateRowResizeHandle(view, value) {
  view.dispatch(view.state.tr.setMeta(_DOCX_ROW_RESIZE_KEY, { setRow: value }));
}

function _docxHandleRowMouseMove(view, event, handleHeight) {
  if (!view.editable) return;
  const pluginState = _DOCX_ROW_RESIZE_KEY.getState(view.state);
  if (!pluginState || pluginState.dragging) return;
  const rowPos = _docxGetResizeRowPos(view, event, handleHeight);
  if (rowPos !== pluginState.activeRowPos) {
    _docxUpdateRowResizeHandle(view, rowPos);
  }
}

function _docxHandleRowMouseLeave(view) {
  if (!view.editable) return;
  const pluginState = _DOCX_ROW_RESIZE_KEY.getState(view.state);
  if (pluginState && pluginState.activeRowPos > -1 && !pluginState.dragging) {
    _docxUpdateRowResizeHandle(view, -1);
  }
}

function _docxHandleRowMouseDown(view, event, rowMinHeight, handleHeight = 5) {
  if (!view.editable) return false;
  const win = view.dom.ownerDocument.defaultView ?? window;
  const pluginState = _DOCX_ROW_RESIZE_KEY.getState(view.state);
  if (!pluginState || pluginState.dragging) return false;

  const activeRowPos = pluginState.activeRowPos > -1
    ? pluginState.activeRowPos
    : _docxGetResizeRowPos(view, event, handleHeight);
  if (activeRowPos === -1) return false;

  const rowNode = view.state.doc.nodeAt(activeRowPos);
  let liveRowEl = _docxResolveLiveResizeRowElement(view, event, activeRowPos);
  const paintScale = window.KotoUiScale.getElementPaintScale(liveRowEl || view.dom);
  const liveStartHeight = liveRowEl?.offsetHeight
    || ((liveRowEl?.getBoundingClientRect?.().height || 0) / paintScale.y);
  const height = liveStartHeight || _docxCurrentRowHeight(view, activeRowPos, rowNode);
  _docxSetResizeUiState(true);
  view.dispatch(view.state.tr.setMeta(_DOCX_ROW_RESIZE_KEY, {
    setRow: activeRowPos,
    setDragging: { startY: event.clientY, startHeight: height, paintScaleY: paintScale.y },
  }));
  liveRowEl = _docxRefreshLiveResizeRowElement(view, event, activeRowPos, liveRowEl);

  function finish(mouseEvent) {
    win.removeEventListener('mouseup', finish, true);
    win.removeEventListener('mousemove', move, true);
    _docxSetResizeUiState(false);
    const currentState = _DOCX_ROW_RESIZE_KEY.getState(view.state);
    const previewRowEl = _docxRefreshLiveResizeRowElement(
      view,
      mouseEvent,
      currentState?.activeRowPos ?? activeRowPos,
      liveRowEl,
    );
    if (currentState?.dragging) {
      _docxUpdateRowHeight(
        view,
        currentState.activeRowPos,
        _docxDraggedRowHeight(currentState.dragging, mouseEvent, rowMinHeight),
      );
      view.dispatch(view.state.tr.setMeta(_DOCX_ROW_RESIZE_KEY, { setDragging: null }));
    }
    requestAnimationFrame(() => _docxClearLiveRowHeightPreview(previewRowEl));
  }

  function move(mouseEvent) {
    const primaryDown = _docxIsPrimaryPointerStillDown(mouseEvent);
    if (!primaryDown) return finish(mouseEvent);
    mouseEvent.preventDefault?.();
    const currentState = _DOCX_ROW_RESIZE_KEY.getState(view.state);
    if (!currentState?.dragging) return;
    liveRowEl = _docxRefreshLiveResizeRowElement(view, mouseEvent, currentState.activeRowPos, liveRowEl);
    const dragged = _docxDraggedRowHeight(currentState.dragging, mouseEvent, rowMinHeight);
    _docxApplyLiveRowHeightPreview(liveRowEl, dragged, view);
  }

  _docxApplyLiveRowHeightPreview(liveRowEl, height, view);
  win.addEventListener('mouseup', finish, true);
  win.addEventListener('mousemove', move, true);
  event.preventDefault();
  return true;
}

export function createDocxSafeRowResizing({
  handleHeight = 5,
  rowMinHeight = 18,
} = {}) {
  return new Plugin({
    key: _DOCX_ROW_RESIZE_KEY,
    state: {
      init() {
        return new _DocxRowResizeState(-1, false);
      },
      apply(tr, prev) {
        return prev.apply(tr);
      },
    },
    props: {
      attributes: state => {
        const pluginState = _DOCX_ROW_RESIZE_KEY.getState(state);
        return pluginState && pluginState.activeRowPos > -1 ? { class: 'koto-row-resize-cursor' } : {};
      },
      handleDOMEvents: {
        mousemove: (view, event) => _docxHandleRowMouseMove(view, event, handleHeight),
        mouseleave: view => _docxHandleRowMouseLeave(view),
        mousedown: (view, event) => _docxHandleRowMouseDown(view, event, rowMinHeight, handleHeight),
      },
      decorations: () => undefined,
    },
  });
}

export const DocxTableRow = TableRow.extend({
  addAttributes() {
    return {
      rowHeight: {
        default: null,
        parseHTML: el => el.style.height || null,
      },
      exactRowHeight: {
        default: null,
        parseHTML: el => el.getAttribute('data-koto-row-height') || null,
      },
    };
  },

  renderHTML({ HTMLAttributes, node }) {
    const merged = { ...HTMLAttributes };
    const styleParts = [];
    if (merged.style) styleParts.push(merged.style);
    if (node.attrs.rowHeight) styleParts.push(`height:${node.attrs.rowHeight}`);
    if (node.attrs.exactRowHeight) merged['data-koto-row-height'] = node.attrs.exactRowHeight;
    if (styleParts.length) merged.style = styleParts.join(';');
    return ['tr', mergeAttributes(this.options.HTMLAttributes, merged), 0];
  },
});
export { DocxImage, DocxParagraph } from './docx-image-extension.js';


// ─────────────────────────────────────────────────────────────────────────────
// DocxTableCell
// Extends TipTap's TableCell to preserve all DOCX cell styling:
// border colours, background fill, vertical alignment, padding, colspan/rowspan.
// ─────────────────────────────────────────────────────────────────────────────
function _cellStyle(attrs) {
  const styles = [];
  if (attrs.backgroundColor) styles.push(`background-color:${attrs.backgroundColor}`);
  if (attrs.verticalAlign)   styles.push(`vertical-align:${attrs.verticalAlign}`);
  if (attrs.paddingTop)      styles.push(`padding-top:${attrs.paddingTop}`);
  if (attrs.paddingBottom)   styles.push(`padding-bottom:${attrs.paddingBottom}`);
  if (attrs.paddingLeft)     styles.push(`padding-left:${attrs.paddingLeft}`);
  if (attrs.paddingRight)    styles.push(`padding-right:${attrs.paddingRight}`);
  if (attrs.borderTop)       styles.push(`border-top:${attrs.borderTop}`);
  if (attrs.borderBottom)    styles.push(`border-bottom:${attrs.borderBottom}`);
  if (attrs.borderLeft)      styles.push(`border-left:${attrs.borderLeft}`);
  if (attrs.borderRight)     styles.push(`border-right:${attrs.borderRight}`);
  if (attrs.width)           styles.push(`width:${attrs.width}`);
  return styles.join(';');
}

const _docxCellAttrs = {
  colspan:         { default: 1 },
  rowspan:         { default: 1 },
  colwidth: {
    default: null,
    parseHTML: el => {
      const raw = el.getAttribute('data-colwidth') || el.getAttribute('colwidth');
      if (!raw) return null;
      const arr = raw.split(',').map(v => parseInt(v, 10)).filter(v => v > 0);
      return arr.length ? arr : null;
    },
    renderHTML: attrs => {
      if (!attrs.colwidth) return {};
      return { 'data-colwidth': attrs.colwidth.join(',') };
    },
  },
  backgroundColor: {
    default: null,
    parseHTML: el => el.style.backgroundColor || el.getAttribute('data-bg-color') || null,
  },
  verticalAlign: {
    default: null,
    parseHTML: el => el.style.verticalAlign || el.getAttribute('data-valign') || null,
  },
  paddingTop:    { default: null, parseHTML: el => el.style.paddingTop     || null },
  paddingBottom: { default: null, parseHTML: el => el.style.paddingBottom  || null },
  paddingLeft:   { default: null, parseHTML: el => el.style.paddingLeft    || null },
  paddingRight:  { default: null, parseHTML: el => el.style.paddingRight   || null },
  borderTop:     { default: null, parseHTML: el => el.style.borderTop      || null },
  borderBottom:  { default: null, parseHTML: el => el.style.borderBottom   || null },
  borderLeft:    { default: null, parseHTML: el => el.style.borderLeft     || null },
  borderRight:   { default: null, parseHTML: el => el.style.borderRight    || null },
  kotoBorderlessCell: {
    default: false,
    parseHTML: el => el.getAttribute('data-koto-borderless-cell') === 'true',
    renderHTML: attrs => attrs.kotoBorderlessCell ? { 'data-koto-borderless-cell': 'true' } : {},
  },
  width:         { default: null, parseHTML: el => el.style.width          || null },
};

export const DocxTableCell = TableCell.extend({
  addAttributes() {
    return _docxCellAttrs;
  },
  renderHTML({ HTMLAttributes, node }) {
    const style = _cellStyle(node.attrs);
    const merged = { ...HTMLAttributes };
    if (node.attrs.colspan && node.attrs.colspan > 1) merged.colspan = node.attrs.colspan;
    if (node.attrs.rowspan && node.attrs.rowspan > 1) merged.rowspan = node.attrs.rowspan;
    if (node.attrs.colwidth) merged['data-colwidth'] = node.attrs.colwidth.join(',');
    if (style) merged.style = style;
    return ['td', merged, 0];
  },
});

export const DocxTableHeader = TableHeader.extend({
  addAttributes() {
    return _docxCellAttrs;
  },
  renderHTML({ HTMLAttributes, node }) {
    const style = _cellStyle(node.attrs);
    const merged = { ...HTMLAttributes };
    if (node.attrs.colspan && node.attrs.colspan > 1) merged.colspan = node.attrs.colspan;
    if (node.attrs.rowspan && node.attrs.rowspan > 1) merged.rowspan = node.attrs.rowspan;
    if (node.attrs.colwidth) merged['data-colwidth'] = node.attrs.colwidth.join(',');
    if (style) merged.style = style;
    return ['th', merged, 0];
  },
});

// ─────────────────────────────────────────────────────────────────────────────
// DocxPageBreak
// An in-flow block node that creates REAL vertical space between pages.
// Instead of a z-index overlay, the NodeView renders a full structural
// gap: bottom-margin zone → gray gap → top-margin zone, each occupying
// actual height in the document so content is never hidden behind them.
//
// Explicit and automatic page boundaries share the AutoPageBreak storage and
// the same page-break widget builder below.  Keeping one source of page chrome
// prevents header/footer or sheet geometry from drifting between break types.
// ─────────────────────────────────────────────────────────────────────────────
export const DocxPageBreak = Node.create({
  name: 'docxPageBreak',
  group: 'block',
  atom: true,
  selectable: false,

  addAttributes() {
    return {
      page: {
        default: 1,
        parseHTML: (element) => Number.parseInt(element.getAttribute('data-page-num') || '1', 10) || 1,
        renderHTML: (attributes) => ({ 'data-page-num': String(Math.max(1, Number.parseInt(attributes.page, 10) || 1)) }),
      },
      sectionIdx: {
        default: 0,
        parseHTML: (element) => Number.parseInt(element.getAttribute('data-section-idx') || element.getAttribute('data-next-section-idx') || '0', 10) || 0,
        renderHTML: (attributes) => ({ 'data-section-idx': String(Math.max(0, Number.parseInt(attributes.sectionIdx, 10) || 0)) }),
      },
      currentSectionIdx: {
        default: 0,
        parseHTML: (element) => Number.parseInt(element.getAttribute('data-current-section-idx') || element.getAttribute('data-section-idx') || '0', 10) || 0,
        renderHTML: (attributes) => ({ 'data-current-section-idx': String(Math.max(0, Number.parseInt(attributes.currentSectionIdx, 10) || 0)) }),
      },
      nextSectionIdx: {
        default: 0,
        parseHTML: (element) => Number.parseInt(element.getAttribute('data-next-section-idx') || element.getAttribute('data-section-idx') || '0', 10) || 0,
        renderHTML: (attributes) => ({ 'data-next-section-idx': String(Math.max(0, Number.parseInt(attributes.nextSectionIdx, 10) || 0)) }),
      },
    };
  },

  parseHTML() {
    return [{ tag: 'div[data-page-break]' }];
  },

  // renderHTML is used ONLY when serializing back to HTML for saving.
  // The NodeView below handles all visual rendering in the editor.
  renderHTML({ HTMLAttributes }) {
    return ['div', mergeAttributes(HTMLAttributes, {
      'data-page-break': '',
      class: 'koto-page-break',
      contenteditable: 'false',
    })];
  },

  addNodeView() {
    return ({ node, editor }) => {
      // Use the same page-break chrome as automatic, inline and table breaks.
      // Only the placement differs; the sheet surface must not.
      const { dom, fillEl, endZone, startZone, footerEl, headerEl } = _buildDocxPageBreakWidget({
        breakAttribute: 'data-page-break',
        pageNum: Math.max(1, Number.parseInt(node.attrs.page, 10) || 1),
        headerHtml: '',
        footerHtml: '',
        marginTopPx: 96,
        marginBottomPx: 80,
        marginLeftPx: 96,
        marginRightPx: 96,
        extStorage: editor.storage?.autoPageBreak,
        contentFillPx: 0,
      });
      dom.setAttribute('data-page-num', String(Math.max(1, Number.parseInt(node.attrs.page, 10) || 1)));
      dom.setAttribute('data-section-idx', String(Math.max(0, Number.parseInt(node.attrs.sectionIdx, 10) || 0)));
      dom.setAttribute('data-current-section-idx', String(Math.max(0, Number.parseInt(node.attrs.currentSectionIdx, 10) || 0)));
      dom.setAttribute('data-next-section-idx', String(Math.max(0, Number.parseInt(node.attrs.nextSectionIdx, 10) || Number.parseInt(node.attrs.sectionIdx, 10) || 0)));
      // ── Deferred header/footer injection ─────────────────────────────
      // AutoPageBreak storage is populated after new Editor() returns. Retry
      // on rAF and again at 200ms to guarantee content is filled.
      const _injectHdrFtr = () => {
        const breakChrome = resolveDocxBreakChrome(
          editor.storage?.autoPageBreak || {},
          Number.parseInt(node.attrs.page, 10) || 1,
          Number.parseInt(node.attrs.currentSectionIdx, 10) || Number.parseInt(node.attrs.sectionIdx, 10) || 0,
          Number.parseInt(node.attrs.nextSectionIdx, 10) || Number.parseInt(node.attrs.sectionIdx, 10) || 0,
        );
        const mTop = breakChrome.marginTopPx || 96;
        const mBot = breakChrome.marginBottomPx || 80;
        const mLeft = breakChrome.marginLeftPx || 96;
        const mRight = breakChrome.marginRightPx || 96;
        const contentFillPx = _normalizeDocxBreakFillPx(dom.getAttribute('data-content-fill-px'));

        // This node lives in the ProseMirror content box, while the visible
        // sheet is its border box.  Escaping both document margins made an
        // explicit DOCX page break wider than the sheet whenever its stored
        // section margins differed from the editor padding (for example 120px
        // margins on an 816px sheet produced an 864px break).  Use the actual
        // rendered editor surface just like auto-generated soft breaks do.
        const pageGeometry = _resolveRenderedDocxPageGeometry(
          editor.view?.dom,
          breakChrome.pageWidthPx || 816,
          mLeft,
        );
        _alignSoftBreakWidgetToRenderedPage(dom, pageGeometry.contentLeftPx, pageGeometry.pageWidthPx);
        fillEl.style.height = `${contentFillPx}px`;
        endZone.style.height = `${mBot}px`;
        startZone.style.height = `${mTop}px`;
        endZone.style.setProperty('--koto-docx-marker-left', `${Math.max(24, mLeft - 12)}px`);
        endZone.style.setProperty('--koto-docx-marker-right', `${Math.max(24, mRight - 12)}px`);
        startZone.style.setProperty('--koto-docx-marker-left', `${Math.max(24, mLeft - 12)}px`);
        startZone.style.setProperty('--koto-docx-marker-right', `${Math.max(24, mRight - 12)}px`);
        footerEl.style.padding = `0 ${mRight}px 0 ${mLeft}px`;
        headerEl.style.padding = `0 ${mRight}px 0 ${mLeft}px`;

        const hdr = breakChrome.nextPage.headerHtml || '';
        const ftr = breakChrome.currentPage.footerHtml || '';
        if (!footerEl.querySelector('.koto-hdrftr-overlay')) {
          footerEl.dataset.variant = breakChrome.currentPage.footerVariant || 'default';
          _setHdrFtrSlotState(footerEl, ftr, 'footer');
          footerEl.querySelectorAll('.koto-hdr-page-num').forEach((el) => {
            el.textContent = String(Math.max(1, Number.parseInt(node.attrs.page, 10) || 1));
            el.setAttribute('contenteditable', 'false');
          });
        }
        if (!headerEl.querySelector('.koto-hdrftr-overlay')) {
          headerEl.dataset.variant = breakChrome.nextPage.headerVariant || 'default';
          _setHdrFtrSlotState(headerEl, hdr, 'header');
          headerEl.querySelectorAll('.koto-hdr-page-num').forEach((el) => {
            el.textContent = String(Math.max(2, (Number.parseInt(node.attrs.page, 10) || 1) + 1));
            el.setAttribute('contenteditable', 'false');
          });
        }
      };
      _injectHdrFtr();
      requestAnimationFrame(_injectHdrFtr);
      setTimeout(_injectHdrFtr, 200);

      return {
        dom,
        update(updatedNode) {
          if (updatedNode.type.name !== 'docxPageBreak') return false;
          node = updatedNode;
          _injectHdrFtr();
          return true;
        },
        stopEvent() { return true; },
      };
    };
  },
});

// ─────────────────────────────────────────────────────────────────────────────
// DocxHeading
// Extends the built-in Heading to preserve `id` and `class` attributes
// from DOCX bookmarks, enabling TOC anchor navigation (#_Toc... links).
// ─────────────────────────────────────────────────────────────────────────────
export const DocxHeading = Heading.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      id:        { default: null, parseHTML: el => el.getAttribute('id') || null, renderHTML: attrs => attrs.id ? { id: attrs.id } : {} },
      className: { default: null, parseHTML: el => el.getAttribute('class') || null, renderHTML: attrs => attrs.className ? { class: attrs.className } : {} },
      style:     { default: null, parseHTML: el => el.getAttribute('style') || null, renderHTML: attrs => attrs.style ? { style: attrs.style } : {} },
      kotoRole:  { default: null, parseHTML: el => el.getAttribute('data-koto-role') || null, renderHTML: attrs => attrs.kotoRole ? { 'data-koto-role': attrs.kotoRole } : {} },
    };
  },
});

// ─────────────────────────────────────────────────────────────────────────────
// TocTab
// Inline atom node that preserves <span class="koto-toc-tab"></span> in TOC
// paragraphs.  The backend emits this empty span for tab characters inside TOC
// entries; CSS renders it as a flex-grow spacer with dot-leader ::after content.
// Without this extension ProseMirror would strip the unrecognised span entirely,
// causing dot leaders and right-aligned page numbers to vanish.
// ─────────────────────────────────────────────────────────────────────────────
export const TocTab = Node.create({
  name: 'tocTab',
  group: 'inline',
  inline: true,
  atom: true,          // non-editable, no text content
  selectable: false,
  parseHTML() {
    return [{ tag: 'span.koto-toc-tab' }];
  },
  renderHTML() {
    return ['span', { class: 'koto-toc-tab' }];
  },
});

// ─────────────────────────────────────────────────────────────────────────────
// FontSize extension
// Adds `fontSize` mark via TextStyle so any span with font-size CSS is preserved.
// ─────────────────────────────────────────────────────────────────────────────
function _normalizeFontSize(value) {
  const raw = String(value || '').trim();
  if (!raw) return null;
  const match = raw.match(/^(-?\d+(?:\.\d+)?)([a-z%]*)$/i);
  if (!match) return null;
  const numeric = parseFloat(match[1]);
  if (!Number.isFinite(numeric) || numeric <= 0) return null;
  const rounded = Math.round(numeric * 10) / 10;
  const formatted = Number.isInteger(rounded)
    ? String(rounded)
    : String(rounded).replace(/\.0$/, '');
  return `${formatted}pt`;
}

export const FontSize = Extension.create({
  name: 'fontSize',

  addCommands() {
    return {
      setFontSize: fontSize => ({ chain }) => {
        const normalized = _normalizeFontSize(fontSize);
        if (!normalized) return false;
        return chain().setMark('textStyle', { fontSize: normalized }).run();
      },

      unsetFontSize: () => ({ chain }) => {
        return chain().setMark('textStyle', { fontSize: null }).removeEmptyTextStyle().run();
      },
    };
  },

  addGlobalAttributes() {
    return [
      {
        types: ['textStyle'],
        attributes: {
          fontSize: {
            default: null,
            parseHTML: el => el.style.fontSize || null,
            renderHTML: attrs => {
              if (!attrs.fontSize) return {};
              return { style: `font-size:${attrs.fontSize}` };
            },
          },
        },
      },
    ];
  },
});

// ─────────────────────────────────────────────────────────────────────────────
// LineHeight extension
// Adds `lineHeight` mark via TextStyle
// ─────────────────────────────────────────────────────────────────────────────
export const LineHeight = Extension.create({
  name: 'lineHeight',
  addGlobalAttributes() {
    return [
      {
        types: ['textStyle'],
        attributes: {
          lineHeight: {
            default: null,
            parseHTML: el => el.style.lineHeight || null,
            renderHTML: attrs => {
              if (!attrs.lineHeight) return {};
              return { style: `line-height:${attrs.lineHeight}` };
            },
          },
        },
      },
    ];
  },
});

// ─────────────────────────────────────────────────────────────────────────────
// Native DOCX tracked-change marks
// Preserve parser-emitted revision wrappers in TipTap so imported Word/WPS
// revisions stay visible/actionable in the editor DOM.
// ─────────────────────────────────────────────────────────────────────────────
export const DocxTrackChange = Mark.create({
  name: 'docxTrackChange',
  inclusive: false,

  addAttributes() {
    return {
      className: {
        default: 'koto-docx-track-change',
        parseHTML: (element) => String(element.getAttribute('class') || '').trim() || 'koto-docx-track-change',
        renderHTML: (attrs) => {
          const raw = String(attrs.className || '').trim();
          return raw ? { class: raw } : { class: 'koto-docx-track-change' };
        },
      },
      reviewId: {
        default: null,
        parseHTML: (element) => element.getAttribute('data-koto-review-id') || null,
        renderHTML: (attrs) => attrs.reviewId ? { 'data-koto-review-id': attrs.reviewId } : {},
      },
      reviewSource: {
        default: null,
        parseHTML: (element) => element.getAttribute('data-koto-review-source') || null,
        renderHTML: (attrs) => attrs.reviewSource ? { 'data-koto-review-source': attrs.reviewSource } : {},
      },
      reviewAction: {
        default: null,
        parseHTML: (element) => element.getAttribute('data-koto-review-action') || null,
        renderHTML: (attrs) => attrs.reviewAction ? { 'data-koto-review-action': attrs.reviewAction } : {},
      },
      reviewAuthor: {
        default: null,
        parseHTML: (element) => element.getAttribute('data-koto-review-author') || null,
        renderHTML: (attrs) => attrs.reviewAuthor ? { 'data-koto-review-author': attrs.reviewAuthor } : {},
      },
      reviewDate: {
        default: null,
        parseHTML: (element) => element.getAttribute('data-koto-review-date') || null,
        renderHTML: (attrs) => attrs.reviewDate ? { 'data-koto-review-date': attrs.reviewDate } : {},
      },
    };
  },

  parseHTML() {
    return [{ tag: 'span.koto-docx-track-change' }];
  },

  renderHTML({ HTMLAttributes }) {
    return ['span', mergeAttributes({ class: 'koto-docx-track-change' }, HTMLAttributes), 0];
  },
});

export const DocxTrackChangePart = Mark.create({
  name: 'docxTrackChangePart',
  inclusive: false,

  addAttributes() {
    return {
      variant: {
        default: null,
        parseHTML: (element) => {
          if (element.classList.contains('koto-docx-track-change-delete')) return 'delete';
          if (element.classList.contains('koto-docx-track-change-insert')) return 'insert';
          return null;
        },
        renderHTML: (attrs) => {
          if (attrs.variant === 'delete') return { class: 'koto-docx-track-change-delete' };
          if (attrs.variant === 'insert') return { class: 'koto-docx-track-change-insert' };
          return {};
        },
      },
    };
  },

  parseHTML() {
    return [
      { tag: 'span.koto-docx-track-change-delete', getAttrs: () => ({ variant: 'delete' }) },
      { tag: 'span.koto-docx-track-change-insert', getAttrs: () => ({ variant: 'insert' }) },
    ];
  },

  renderHTML({ HTMLAttributes }) {
    const variant = HTMLAttributes.variant;
    const fallbackClass = variant === 'delete'
      ? 'koto-docx-track-change-delete'
      : 'koto-docx-track-change-insert';
    const merged = mergeAttributes({ class: fallbackClass }, HTMLAttributes);
    delete merged.variant;
    return ['span', merged, 0];
  },
});
export { AutoPageBreakPlugin } from './docx-pagination-extension.js';
