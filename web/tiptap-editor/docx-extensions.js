/**
 * docx-extensions.js
 * Custom TipTap / ProseMirror extensions that preserve
 * DOCX-specific formatting attributes during round-trip HTML editing.
 */

import { Extension, Mark, Node, mergeAttributes } from '@tiptap/core';
import { NodeSelection, Plugin, PluginKey } from 'prosemirror-state';
import { Decoration, DecorationSet } from 'prosemirror-view';
import { TableMap } from '@tiptap/pm/tables';
import { Table, TableView } from '@tiptap/extension-table';
import { TableRow } from '@tiptap/extension-table-row';
import { TableCell } from '@tiptap/extension-table-cell';
import { TableHeader } from '@tiptap/extension-table-header';
import { TextStyle } from '@tiptap/extension-text-style';
import Image from '@tiptap/extension-image';
import Heading from '@tiptap/extension-heading';
import { resolveDocxBreakChrome } from './docx-pagination-runtime.js';
import {
  ResizeState,
  cellAround,
  columnResizingPluginKey,
  pointsAtCell,
  tableEditing,
  tableNodeTypes,
  updateColumnsOnResize,
} from 'prosemirror-tables';

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

  let bestCell = null;
  let bestScore = Number.POSITIVE_INFINITY;
  const cells = table.querySelectorAll('td,th');
  for (const cell of cells) {
    const rect = cell.getBoundingClientRect();
    const dx = clientX < rect.left ? rect.left - clientX : clientX > rect.right ? clientX - rect.right : 0;
    const dy = clientY < rect.top ? rect.top - clientY : clientY > rect.bottom ? clientY - rect.bottom : 0;
    if (dx > 8 || dy > 8) continue;
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
  const offset = side === 'right' ? -handleWidth : handleWidth;
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
  const offset = event.clientX - dragging.startX;
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
    if (event.clientX - left <= handleWidth) {
      cell = _docxEdgeCell(view, event, 'left', handleWidth);
    } else if (right - event.clientX <= handleWidth) {
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
  _docxSetResizeUiState(true);
  view.dispatch(view.state.tr.setMeta(columnResizingPluginKey, {
    setDragging: { startX: event.clientX, startWidth: width },
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
  const cellEl = _docxCellAroundEvent(view, event, [
    [0, 0],
    [0, -1],
    [0, 1],
    [0, -handleHeight],
    [0, handleHeight],
    [-1, 0],
    [1, 0],
  ]);
  if (!cellEl) return -1;

  const rect = cellEl.getBoundingClientRect();
  const topDistance = event.clientY - rect.top;
  const bottomDistance = rect.bottom - event.clientY;
  if (topDistance > handleHeight && bottomDistance > handleHeight) return -1;

  const cellPos = _docxCellPosFromDom(view, cellEl);
  const rowInfo = _docxResolveRowInfoFromCellPos(view.state.doc, cellPos);
  if (!rowInfo) return -1;

  let targetRowIndex = rowInfo.rowIndex;
  if (topDistance <= handleHeight && bottomDistance <= handleHeight) {
    targetRowIndex = topDistance <= bottomDistance ? rowInfo.rowIndex - 1 : rowInfo.rowIndex;
  } else if (topDistance <= handleHeight) {
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
  const offset = event.clientY - dragging.startY;
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
  const liveStartHeight = liveRowEl?.getBoundingClientRect?.().height || liveRowEl?.offsetHeight || 0;
  const height = liveStartHeight || _docxCurrentRowHeight(view, activeRowPos, rowNode);
  _docxSetResizeUiState(true);
  view.dispatch(view.state.tr.setMeta(_DOCX_ROW_RESIZE_KEY, {
    setRow: activeRowPos,
    setDragging: { startY: event.clientY, startHeight: height },
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

// ─────────────────────────────────────────────────────────────────────────────
// DocxImage
// ─────────────────────────────────────────────────────────────────────────────
function _docxNormalizeImageLayout(layoutValue) {
  const value = String(layoutValue || '').trim().toLowerCase();

  if (!value) return '';
  if (value === 'top-bottom') return 'top-bottom-center';
  if (
    value === 'inline'
    || value === 'square-left'
    || value === 'square-center'
    || value === 'square-right'
    || value === 'tight-left'
    || value === 'tight-center'
    || value === 'tight-right'
    || value === 'top-bottom-left'
    || value === 'top-bottom-center'
    || value === 'top-bottom-right'
  ) {
    return value;
  }

  return '';
}

function _docxImageLayoutContainer(el) {
  const parent = el?.parentElement || null;
  if (!parent) return null;

  if (
    parent.hasAttribute('data-koto-layout')
    || parent.hasAttribute('data-koto-wrap')
    || parent.hasAttribute('data-koto-side')
  ) {
    return parent;
  }

  if (parent.childElementCount !== 1 || parent.firstElementChild !== el) {
    return null;
  }

  if (
    parent.style.float
    || parent.style.display
    || parent.style.textAlign
    || parent.style.position
    || parent.style.left
    || parent.style.top
    || parent.style.margin
  ) {
    return parent;
  }

  return null;
}

function _docxImageStyleValue(el, prop) {
  return String(el?.style?.[prop] || '').trim().toLowerCase();
}

function _docxImageStyleRaw(el, prop) {
  return String(el?.style?.[prop] || '').trim();
}

function _docxImageStyleAttr(el, prop, { preferContainer = false } = {}) {
  const container = _docxImageLayoutContainer(el);
  const sources = preferContainer
    ? [container, el]
    : [el, container];

  for (const source of sources) {
    const value = _docxImageStyleRaw(source, prop);
    if (value) return value;
  }

  return null;
}

function _docxComposeImageLayout(wrapMode, align = '') {
  const wrap = String(wrapMode || '').trim().toLowerCase();
  const side = String(align || '').trim().toLowerCase();

  if (wrap === 'inline') return 'inline';
  if (wrap === 'square') {
    if (side === 'left' || side === 'center' || side === 'right') return `square-${side}`;
    return 'square-right';
  }
  if (wrap === 'tight') {
    if (side === 'left' || side === 'center' || side === 'right') return `tight-${side}`;
    return 'tight-right';
  }
  if (wrap === 'top-bottom') {
    if (side === 'left' || side === 'right') return `top-bottom-${side}`;
    return 'top-bottom-center';
  }

  return '';
}

function _docxImageLayoutStateFromLayout(layoutValue) {
  const layout = _docxNormalizeImageLayout(layoutValue);

  switch (layout) {
    case 'inline':
      return { wrapMode: 'inline', align: 'center' };
    case 'square-left':
      return { wrapMode: 'square', align: 'left' };
    case 'square-center':
      return { wrapMode: 'square', align: 'center' };
    case 'square-right':
      return { wrapMode: 'square', align: 'right' };
    case 'tight-left':
      return { wrapMode: 'tight', align: 'left' };
    case 'tight-center':
      return { wrapMode: 'tight', align: 'center' };
    case 'tight-right':
      return { wrapMode: 'tight', align: 'right' };
    case 'top-bottom-left':
      return { wrapMode: 'top-bottom', align: 'left' };
    case 'top-bottom-right':
      return { wrapMode: 'top-bottom', align: 'right' };
    case 'top-bottom-center':
      return { wrapMode: 'top-bottom', align: 'center' };
    default:
      return null;
  }
}

function _docxImageLayoutSupportsAlign(wrapMode, align) {
  if (wrapMode === 'inline') return false;
  if (wrapMode === 'square' || wrapMode === 'tight') {
    return align === 'left' || align === 'center' || align === 'right';
  }
  if (wrapMode === 'top-bottom') {
    return align === 'left' || align === 'center' || align === 'right';
  }
  return false;
}

function _docxDefaultImageMargin(wrapMode, align) {
  if (wrapMode === 'square') {
    if (align === 'center') return '4px auto 12px';
    return align === 'left' ? '0 16px 12px 0' : '0 0 12px 16px';
  }
  if (wrapMode === 'tight') {
    if (align === 'center') return '4px auto 8px';
    return align === 'left' ? '0 10px 8px 0' : '0 0 8px 10px';
  }
  if (wrapMode === 'top-bottom') {
    if (align === 'left') return '10px auto 10px 0';
    if (align === 'right') return '10px 0 10px auto';
    return '10px auto';
  }
  return '0 6px';
}

function _docxImageLayoutStateFromAttrs(attrs = {}) {
  const explicit = _docxImageLayoutStateFromLayout(attrs.layout);
  if (explicit) return explicit;

  const float = String(attrs.float || '').trim().toLowerCase();
  if (float === 'left') return { wrapMode: 'square', align: 'left' };
  if (float === 'right') return { wrapMode: 'square', align: 'right' };

  if (String(attrs.display || '').trim().toLowerCase() === 'block') {
    return { wrapMode: 'top-bottom', align: 'center' };
  }

  return { wrapMode: 'inline', align: 'center' };
}

function _docxImageLayoutFromElement(el) {
  const container = _docxImageLayoutContainer(el);
  const explicit = _docxNormalizeImageLayout(
    container?.getAttribute('data-koto-layout') || el.getAttribute('data-koto-layout')
  );
  if (explicit) return explicit;

  const wrapMode = String(
    container?.getAttribute('data-koto-wrap') || el.getAttribute('data-koto-wrap') || ''
  ).trim().toLowerCase();
  const align = String(
    container?.getAttribute('data-koto-side') || el.getAttribute('data-koto-side') || ''
  ).trim().toLowerCase();
  const composed = _docxComposeImageLayout(wrapMode, align);
  if (composed) return composed;

  const float = _docxImageStyleValue(container, 'float') || _docxImageStyleValue(el, 'float');
  if (float === 'left') return 'square-left';
  if (float === 'right') return 'square-right';

  const display = _docxImageStyleValue(container, 'display') || _docxImageStyleValue(el, 'display');
  const position = _docxImageStyleValue(container, 'position');
  const width = _docxImageStyleValue(container, 'width');
  const height = _docxImageStyleValue(container, 'height');
  const left = _docxImageStyleRaw(container, 'left');
  const top = _docxImageStyleRaw(container, 'top');

  // docx-preview encodes wrapNone/anchored drawings as a zero-sized relative
  // wrapper with left/top offsets. Treat those as unsupported floating imports
  // instead of misclassifying them as top/bottom-wrapped images.
  const looksAnchored = !!container
    && display === 'block'
    && position === 'relative'
    && (width === '0px' || width === '0')
    && (height === '0px' || height === '0')
    && (left || top);
  if (looksAnchored) return 'inline';

  if (display === 'block') {
    const textAlign = _docxImageStyleValue(container, 'textAlign');
    if (textAlign === 'left') return 'top-bottom-left';
    if (textAlign === 'right') return 'top-bottom-right';
    return 'top-bottom-center';
  }

  return 'inline';
}

function _docxBuildImageLayoutAttrs(attrs, nextState) {
  const wrapMode = String(nextState?.wrapMode || '').trim().toLowerCase() || 'inline';
  let align = String(nextState?.align || '').trim().toLowerCase() || 'center';
  const centeredWrappedImage = (wrapMode === 'square' || wrapMode === 'tight') && align === 'center';

  if (!_docxImageLayoutSupportsAlign(wrapMode, align)) {
    align = wrapMode === 'top-bottom' ? 'center' : 'right';
  }

  return {
    ...attrs,
    layout: _docxComposeImageLayout(wrapMode, align),
    float: wrapMode === 'square' || wrapMode === 'tight'
      ? (align === 'left' || align === 'right' ? align : null)
      : null,
    display: wrapMode === 'top-bottom' || centeredWrappedImage ? 'block' : null,
    margin: _docxDefaultImageMargin(wrapMode, align),
    verticalAlign: wrapMode === 'inline' ? 'baseline' : null,
  };
}

function _docxImageWrapperStyle(attrs) {
  const { wrapMode, align } = _docxImageLayoutStateFromAttrs(attrs);
  const margin = attrs.margin || _docxDefaultImageMargin(wrapMode, align);

  if (wrapMode === 'square' || wrapMode === 'tight') {
    if (align === 'center') {
      return [
        'display:block',
        'width:fit-content',
        'max-width:100%',
        'clear:both',
        `margin:${margin}`,
        'position:relative',
      ].join(';');
    }

    return [
      `float:${align === 'left' ? 'left' : 'right'}`,
      'display:inline-block',
      `margin:${margin}`,
      'position:relative',
    ].join(';');
  }

  if (wrapMode === 'top-bottom' || attrs.display === 'block') {
    return [
      'display:block',
      'width:fit-content',
      'max-width:100%',
      'clear:both',
      `margin:${margin}`,
      'position:relative',
    ].join(';');
  }

  return [
    'display:inline-block',
    'max-width:100%',
    `margin:${margin}`,
    `vertical-align:${attrs.verticalAlign || 'baseline'}`,
    'position:relative',
  ].join(';');
}

function _docxImageWrapLabel(wrapMode) {
  if (wrapMode === 'square') return '四周环绕';
  if (wrapMode === 'tight') return '紧密环绕';
  if (wrapMode === 'top-bottom') return '上下环绕';
  return '与文字同行';
}

function _docxImageAlignLabel(align) {
  if (align === 'left') return '靠左';
  if (align === 'right') return '靠右';
  return '居中';
}

function _docxImageLayoutStatusText(attrs) {
  const state = _docxImageLayoutStateFromAttrs(attrs);
  if (state.wrapMode === 'inline') return '当前: 与文字同行';
  return `当前: ${_docxImageWrapLabel(state.wrapMode)} · ${_docxImageAlignLabel(state.align)}`;
}

export const DocxImage = Image.extend({
  inline() {
    return true;
  },

  group() {
    return 'inline';
  },

  addAttributes() {
    return {
      ...this.parent?.(),
      layout:       {
        default: null,
        parseHTML: el => _docxImageLayoutFromElement(el),
      },
      width:        { default: null, parseHTML: el => el.style.width        || el.getAttribute('width') || null },
      height:       { default: null, parseHTML: el => el.style.height       || el.getAttribute('height') || null },
      float:        { default: null, parseHTML: el => _docxImageStyleAttr(el, 'float', { preferContainer: true }) },
      display:      { default: null, parseHTML: el => _docxImageStyleAttr(el, 'display', { preferContainer: true }) },
      verticalAlign:{ default: null, parseHTML: el => el.style.verticalAlign || null },
      objectFit:    { default: null, parseHTML: el => el.style.objectFit    || null },
      margin:       { default: null, parseHTML: el => _docxImageStyleAttr(el, 'margin', { preferContainer: true }) },
      maxWidth:     { default: null, parseHTML: el => el.style.maxWidth     || null },
      maxHeight:    { default: null, parseHTML: el => el.style.maxHeight    || null },
      borderRadius: { default: null, parseHTML: el => el.style.borderRadius || null },
    };
  },
  renderHTML({ HTMLAttributes, node }) {
    const styles = [];
    const a = node.attrs;
    const layoutState = _docxImageLayoutStateFromAttrs(a);
    const canonicalLayout = _docxComposeImageLayout(layoutState.wrapMode, layoutState.align);
    if (a.width)        styles.push(`width:${a.width}`);
    if (a.height)       styles.push(`height:${a.height}`);
    if (a.float)        styles.push(`float:${a.float}`);
    if (a.display)      styles.push(`display:${a.display}`);
    if (a.verticalAlign) styles.push(`vertical-align:${a.verticalAlign}`);
    if (a.objectFit)    styles.push(`object-fit:${a.objectFit}`);
    if (a.margin)       styles.push(`margin:${a.margin}`);
    if (a.maxWidth)     styles.push(`max-width:${a.maxWidth}`);
    if (a.maxHeight)    styles.push(`max-height:${a.maxHeight}`);
    if (a.borderRadius) styles.push(`border-radius:${a.borderRadius}`);

    const merged = mergeAttributes(this.options.HTMLAttributes, HTMLAttributes);
    if (canonicalLayout) merged['data-koto-layout'] = canonicalLayout;
    merged['data-koto-wrap'] = layoutState.wrapMode;
    if (layoutState.wrapMode !== 'inline') merged['data-koto-side'] = layoutState.align;
    if (styles.length) merged.style = styles.join(';');

    return ['img', merged];
  },

  // ── Interactive NodeView: resize handles + Word-like layout toolbar ──────
  addNodeView() {
    return ({ node, editor, getPos }) => {
      const UI_HIDE_DELAY_MS = 1200;
      const dom = document.createElement('span');
      dom.className = 'koto-img-wrapper';
      let uiHideTimer = null;
      let isHoverUiVisible = false;
      let isNodeSelected = false;
      let isToolbarOpen = false;
      let toolbarTrigger = null;

      const _clearUiHideTimer = () => {
        if (uiHideTimer != null) {
          window.clearTimeout(uiHideTimer);
          uiHideTimer = null;
        }
      };

      const _syncUiState = () => {
        const shouldShowUi = isHoverUiVisible || isNodeSelected || isToolbarOpen;
        dom.classList.toggle('is-ui-visible', shouldShowUi);
        dom.classList.toggle('selected', isNodeSelected);
        dom.classList.toggle('is-toolbar-open', isToolbarOpen);
        if (toolbarTrigger) {
          toolbarTrigger.setAttribute('aria-expanded', isToolbarOpen ? 'true' : 'false');
        }
      };

      const _setHoverUiVisible = (visible) => {
        isHoverUiVisible = !!visible;
        _syncUiState();
      };

      const _setNodeSelected = (selected) => {
        isNodeSelected = !!selected;
        if (!isNodeSelected && isToolbarOpen) _setToolbarOpen(false);
        _syncUiState();
      };

      const _setToolbarOpen = (open) => {
        isToolbarOpen = !!open;
        if (isToolbarOpen) {
          isHoverUiVisible = true;
          _clearUiHideTimer();
          // Portal: mount toolbar on body so it is completely outside the
          // transform:scale() zoom wrapper (fixed positioning only works
          // relative to the viewport when no transform ancestor is present).
          const bodyEl = (dom.ownerDocument || document).body;
          if (!toolbar.parentNode) bodyEl.appendChild(toolbar);
          toolbar.style.display = 'block';
          requestAnimationFrame(_updateFixedToolbarPos);
          window.addEventListener('scroll', _updateFixedToolbarPos, { passive: true, capture: true });
          window.addEventListener('resize', _updateFixedToolbarPos, { passive: true });
        } else {
          toolbar.style.display = 'none';
          window.removeEventListener('scroll', _updateFixedToolbarPos, { capture: true });
          window.removeEventListener('resize', _updateFixedToolbarPos);
          if (!isNodeSelected) {
            isHoverUiVisible = false;
          }
        }
        _syncUiState();
      };

      const _showUi = () => {
        _clearUiHideTimer();
        _setHoverUiVisible(true);
      };

      const _scheduleUiHide = () => {
        if (isNodeSelected || isToolbarOpen) return;
        _clearUiHideTimer();
        uiHideTimer = window.setTimeout(() => {
          _setHoverUiVisible(false);
          uiHideTimer = null;
        }, UI_HIDE_DELAY_MS);
      };

      // Positions the toolbar panel in fixed viewport coords.
      // Because the toolbar is mounted on document.body (outside any
      // transform ancestor), position:fixed here is truly viewport-relative.
      const _updateFixedToolbarPos = () => {
        if (!isToolbarOpen || !toolbarTrigger) return;
        const triggerRect = toolbarTrigger.getBoundingClientRect();
        const panelW = toolbar.offsetWidth || 284;
        const panelH = toolbar.offsetHeight || 340;
        // Prefer opening below the trigger; flip above when space is tight.
        const spaceBelow = window.innerHeight - triggerRect.bottom - 12;
        let topPx = spaceBelow >= Math.min(panelH, 240)
          ? triggerRect.bottom + 8
          : Math.max(8, triggerRect.top - panelH - 8);
        topPx = Math.max(8, Math.min(topPx, window.innerHeight - panelH - 8));
        // Align right edge with trigger right edge, clamped to viewport.
        let leftPx = triggerRect.right - panelW;
        leftPx = Math.max(8, Math.min(leftPx, window.innerWidth - panelW - 8));
        toolbar.style.position = 'fixed';
        toolbar.style.top = topPx + 'px';
        toolbar.style.left = leftPx + 'px';
        toolbar.style.right = 'auto';
        toolbar.style.bottom = 'auto';
      };

      const _isInsideTableCell = () => !!dom.closest('td,th');

      const _applyWrapperStyle = (attrs) => {
        const state = _docxImageLayoutStateFromAttrs(attrs);
        dom.dataset.layout = _docxComposeImageLayout(state.wrapMode, state.align);
        dom.dataset.scope = _isInsideTableCell() ? 'table' : 'body';
        dom.style.cssText = _docxImageWrapperStyle(attrs);
      };
      _applyWrapperStyle(node.attrs);

      const img = document.createElement('img');
      img.style.display = 'block';
      img.draggable = false;
      const _syncImg = (attrs) => {
        img.src = attrs.src || '';
        img.alt = attrs.alt || '';
        img.style.width = attrs.width || 'auto';
        img.style.height = 'auto';
        img.style.maxWidth = '100%';
      };
      _syncImg(node.attrs);
      dom.appendChild(img);

      const _focusImageNodeSelection = () => {
        const pos = typeof getPos === 'function' ? getPos() : null;
        if (pos == null) return;

        editor.view.focus();

        let tr = editor.view.state.tr;
        try {
          tr = tr.setSelection(NodeSelection.create(tr.doc, pos));
        } catch (_) {}

        editor.view.dispatch(tr);
        _setNodeSelected(true);
      };

      toolbarTrigger = document.createElement('button');
      toolbarTrigger.type = 'button';
      toolbarTrigger.className = 'koto-img-toolbar-trigger';
      toolbarTrigger.setAttribute('contenteditable', 'false');
      toolbarTrigger.setAttribute('aria-label', '打开图片布局选项');
      toolbarTrigger.setAttribute('title', '图片布局选项');
      toolbarTrigger.innerHTML = `
        <span class="koto-img-toolbar-trigger-icon" aria-hidden="true"></span>
        <span class="koto-img-toolbar-trigger-label">布局选项</span>
      `;
      toolbarTrigger.addEventListener('mouseenter', _showUi);
      toolbarTrigger.addEventListener('mouseleave', _scheduleUiHide);
      toolbarTrigger.addEventListener('mousedown', (e) => e.preventDefault());
      toolbarTrigger.addEventListener('pointerdown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        _focusImageNodeSelection();
        _setToolbarOpen(!isToolbarOpen);
      });
      dom.appendChild(toolbarTrigger);

      const toolbar = document.createElement('div');
      toolbar.className = 'koto-img-toolbar';
      toolbar.setAttribute('contenteditable', 'false');
      toolbar.innerHTML = `
        <div class="koto-img-toolbar-header">
          <div class="koto-img-toolbar-title">图片布局</div>
          <div class="koto-img-toolbar-status" data-role="status"></div>
        </div>
        <div class="koto-img-toolbar-section">
          <div class="koto-img-toolbar-label">文字环绕</div>
          <div class="koto-img-toolbar-grid" role="group" aria-label="文字环绕">
            <button type="button" class="koto-img-layout-card" data-wrap="inline" aria-label="与文字同行">
              <span class="koto-img-layout-preview" aria-hidden="true"></span>
              <span class="koto-img-layout-title">同行</span>
              <span class="koto-img-layout-copy">嵌入段落</span>
            </button>
            <button type="button" class="koto-img-layout-card" data-wrap="square" aria-label="四周环绕">
              <span class="koto-img-layout-preview" aria-hidden="true"></span>
              <span class="koto-img-layout-title">四周</span>
              <span class="koto-img-layout-copy">矩形绕排</span>
            </button>
            <button type="button" class="koto-img-layout-card" data-wrap="tight" aria-label="紧密环绕">
              <span class="koto-img-layout-preview" aria-hidden="true"></span>
              <span class="koto-img-layout-title">紧密</span>
              <span class="koto-img-layout-copy">更贴近文字</span>
            </button>
            <button type="button" class="koto-img-layout-card" data-wrap="top-bottom" aria-label="上下环绕">
              <span class="koto-img-layout-preview" aria-hidden="true"></span>
              <span class="koto-img-layout-title">上下</span>
              <span class="koto-img-layout-copy">段前段后绕排</span>
            </button>
          </div>
        </div>
        <div class="koto-img-toolbar-section">
          <div class="koto-img-toolbar-label">图片位置</div>
          <div class="koto-img-position-group" role="group" aria-label="图片位置">
            <button type="button" class="koto-img-pos-btn" data-align="left" aria-label="靠左">靠左</button>
            <button type="button" class="koto-img-pos-btn" data-align="center" aria-label="居中">居中</button>
            <button type="button" class="koto-img-pos-btn" data-align="right" aria-label="靠右">靠右</button>
          </div>
          <div class="koto-img-toolbar-note" data-role="scope"></div>
        </div>
      `;

      const statusEl = toolbar.querySelector('[data-role="status"]');
      const scopeEl = toolbar.querySelector('[data-role="scope"]');

      const _syncToolbarState = (attrs) => {
        const state = _docxImageLayoutStateFromAttrs(attrs);
        const insideTable = _isInsideTableCell();

        toolbar.dataset.scope = insideTable ? 'table' : 'body';
        toolbar.dataset.wrap = state.wrapMode;
        toolbar.dataset.align = state.align;

        toolbar.querySelectorAll('[data-wrap]').forEach((button) => {
          const isActive = button.dataset.wrap === state.wrapMode;
          button.classList.toggle('active', isActive);
          button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        });

        toolbar.querySelectorAll('[data-align]').forEach((button) => {
          const supported = _docxImageLayoutSupportsAlign(state.wrapMode, button.dataset.align);
          const isActive = supported && button.dataset.align === state.align;
          button.disabled = !supported;
          button.classList.toggle('is-disabled', !supported);
          button.classList.toggle('active', isActive);
          button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        });

        if (statusEl) statusEl.textContent = _docxImageLayoutStatusText(attrs);
        if (scopeEl) {
          let noteText = insideTable
            ? '表格内仅影响当前单元格中的文本环绕'
            : '正文图片会按所选环绕方式影响后续段落';
          if ((state.wrapMode === 'square' || state.wrapMode === 'tight') && state.align === 'center') {
            noteText += '；居中为网页近似效果';
          }
          scopeEl.textContent = noteText;
        }
      };

      const _applyLayoutUpdate = (nextState) => {
        const pos = typeof getPos === 'function' ? getPos() : null;
        if (pos == null) return;

        const nextAttrs = _docxBuildImageLayoutAttrs(node.attrs, nextState);
        editor.view.focus();

        let tr = editor.view.state.tr.setNodeMarkup(pos, null, nextAttrs);
        try {
          tr = tr.setSelection(NodeSelection.create(tr.doc, pos));
        } catch (_) {}

        editor.view.dispatch(tr.scrollIntoView());
        _applyWrapperStyle(nextAttrs);
        _syncToolbarState(nextAttrs);
        _showUi();
        requestAnimationFrame(_updateFixedToolbarPos);
      };

      toolbar.addEventListener('mousedown', (e) => e.preventDefault());
      toolbar.addEventListener('pointerdown', (e) => {
        const wrapBtn = e.target.closest('[data-wrap]');
        const alignBtn = e.target.closest('[data-align]');

        if (!wrapBtn && !alignBtn) return;

        e.preventDefault();
        e.stopPropagation();

        const currentState = _docxImageLayoutStateFromAttrs(node.attrs);

        if (wrapBtn) {
          const nextWrapMode = wrapBtn.dataset.wrap || 'inline';
          let nextAlign = currentState.align;
          if (!_docxImageLayoutSupportsAlign(nextWrapMode, nextAlign)) {
            nextAlign = nextWrapMode === 'top-bottom' ? 'center' : 'right';
          }
          // For float modes (square/tight), 'center' produces a display:block element (no float).
          // When inheriting 'center' from inline/top-bottom mode, default to 'left' so the image
          // actually floats and text wraps around it across multiple lines.
          if ((nextWrapMode === 'square' || nextWrapMode === 'tight') && nextAlign === 'center') {
            nextAlign = 'left';
          }
          _applyLayoutUpdate({ wrapMode: nextWrapMode, align: nextAlign });
          return;
        }

        const nextAlign = alignBtn?.dataset.align || '';
        if (!_docxImageLayoutSupportsAlign(currentState.wrapMode, nextAlign)) return;
        _applyLayoutUpdate({ wrapMode: currentState.wrapMode, align: nextAlign });
      });

      const ownerDoc = dom.ownerDocument || document;
      const _handleOutsidePointerDown = (event) => {
        if (!isToolbarOpen) return;
        // Toolbar is mounted on body (portal) so check it separately.
        if (event.target && (dom.contains(event.target) || toolbar.contains(event.target))) return;
        _setToolbarOpen(false);
      };

      const _handleEscapeKey = (event) => {
        if (event.key !== 'Escape' || !isToolbarOpen) return;
        event.preventDefault();
        _setToolbarOpen(false);
        editor.view.focus();
      };

      ownerDoc.addEventListener('pointerdown', _handleOutsidePointerDown, true);
      ownerDoc.addEventListener('keydown', _handleEscapeKey, true);

      // NOTE: toolbar is NOT appended to dom here — it is portal-mounted on
      // document.body when first opened, to escape the zoom transform context.
      _syncToolbarState(node.attrs);
      _syncUiState();

      const CORNERS = [
        { cls: 'nw', cursor: 'nw-resize' },
        { cls: 'ne', cursor: 'ne-resize' },
        { cls: 'sw', cursor: 'sw-resize' },
        { cls: 'se', cursor: 'se-resize' },
      ];
      for (const { cls } of CORNERS) {
        const handle = document.createElement('span');
        handle.className = `koto-img-handle koto-img-handle-${cls}`;
        handle.setAttribute('contenteditable', 'false');

        handle.addEventListener('mousedown', (e) => {
          e.preventDefault();
          e.stopPropagation();

          const isLeft = cls.includes('w');
          const isTop = cls.includes('n');
          const startX = e.clientX;
          const startY = e.clientY;
          const startW = img.offsetWidth || parseInt(node.attrs.width) || img.naturalWidth || 200;
          const startH = img.offsetHeight || parseInt(node.attrs.height) || img.naturalHeight || 150;

          const onMove = (me) => {
            const dx = me.clientX - startX;
            const dy = me.clientY - startY;
            const newW = Math.max(40, startW + (isLeft ? -dx : dx));
            const newH = Math.max(30, startH + (isTop ? -dy : dy));
            img.style.width = newW + 'px';
            img.style.height = newH + 'px';
          };

          const onUp = () => {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            const newW = img.offsetWidth || startW;
            const newH = img.offsetHeight || startH;
            const pos = typeof getPos === 'function' ? getPos() : null;
            if (pos == null) return;
            editor.view.dispatch(
              editor.view.state.tr.setNodeMarkup(pos, null, {
                ...node.attrs,
                width: newW + 'px',
                height: newH + 'px',
              })
            );
          };

          document.addEventListener('mousemove', onMove);
          document.addEventListener('mouseup', onUp);
        });
        dom.appendChild(handle);
      }

      dom.addEventListener('mouseenter', _showUi);
      dom.addEventListener('mouseleave', _scheduleUiHide);
      dom.addEventListener('mousedown', _showUi);

      return {
        dom,
        selectNode() {
          _clearUiHideTimer();
          _setNodeSelected(true);
        },
        deselectNode() {
          _clearUiHideTimer();
          _setHoverUiVisible(false);
          _setNodeSelected(false);
        },
        update(updatedNode) {
          if (updatedNode.type.name !== node.type.name) return false;
          node = updatedNode;
          _syncImg(node.attrs);
          _applyWrapperStyle(node.attrs);
          _syncToolbarState(node.attrs);
          _syncUiState();
          return true;
        },
        stopEvent(event) {
          // Toolbar is on document.body (not inside dom), so ProseMirror
          // never sees its events. Only guard handles and the trigger button.
          return !!(event.target && event.target.closest &&
            event.target.closest('.koto-img-handle, .koto-img-toolbar-trigger'));
        },
        destroy() {
          _clearUiHideTimer();
          window.removeEventListener('scroll', _updateFixedToolbarPos, { capture: true });
          window.removeEventListener('resize', _updateFixedToolbarPos);
          ownerDoc.removeEventListener('pointerdown', _handleOutsidePointerDown, true);
          ownerDoc.removeEventListener('keydown', _handleEscapeKey, true);
          // Remove body-portalled toolbar to avoid orphaned DOM nodes.
          if (toolbar.parentNode) toolbar.parentNode.removeChild(toolbar);
        },
      };
    };
  },
});


// ─────────────────────────────────────────────────────────────────────────────
// DocxParagraph
// Extends the built-in Paragraph to carry indent, line-height, and
// spacing-before/after attributes that python-docx emits.
// ─────────────────────────────────────────────────────────────────────────────
export const DocxParagraph = Node.create({
  name: 'paragraph',
  priority: 1000,
  group: 'block',
  content: 'inline*',
  addAttributes() {
    return {
      textAlign:      { default: null, parseHTML: el => el.style.textAlign      || null, renderHTML: attrs => attrs.textAlign      ? { style: `text-align:${attrs.textAlign}` }      : {} },
      marginLeft:     { default: null, parseHTML: el => el.style.marginLeft      || null, renderHTML: attrs => attrs.marginLeft      ? { style: `margin-left:${attrs.marginLeft}` }      : {} },
      marginRight:    { default: null, parseHTML: el => el.style.marginRight     || null, renderHTML: attrs => attrs.marginRight     ? { style: `margin-right:${attrs.marginRight}` }     : {} },
      marginTop:      { default: null, parseHTML: el => el.style.marginTop       || null, renderHTML: attrs => attrs.marginTop       ? { style: `margin-top:${attrs.marginTop}` }         : {} },
      marginBottom:   { default: null, parseHTML: el => el.style.marginBottom    || null, renderHTML: attrs => attrs.marginBottom    ? { style: `margin-bottom:${attrs.marginBottom}` }   : {} },
      lineHeight:     { default: null, parseHTML: el => el.style.lineHeight      || null, renderHTML: attrs => attrs.lineHeight      ? { style: `line-height:${attrs.lineHeight}` }       : {} },
      textIndent:     { default: null, parseHTML: el => el.style.textIndent      || null, renderHTML: attrs => attrs.textIndent      ? { style: `text-indent:${attrs.textIndent}` }       : {} },
      listStyleType:  { default: null, parseHTML: el => el.style.listStyleType   || el.getAttribute('data-list-style') || null, renderHTML: attrs => {} },
      paddingLeft:    { default: null, parseHTML: el => el.style.paddingLeft     || null, renderHTML: attrs => attrs.paddingLeft     ? { style: `padding-left:${attrs.paddingLeft}` }     : {} },
      fontSize:       { default: null, parseHTML: el => el.style.fontSize        || null, renderHTML: attrs => attrs.fontSize        ? { style: `font-size:${attrs.fontSize}` }           : {} },
      fontFamily:     { default: null, parseHTML: el => el.style.fontFamily      || null, renderHTML: attrs => attrs.fontFamily      ? { style: `font-family:${attrs.fontFamily}` }       : {} },
      fontWeight:     { default: null, parseHTML: el => el.style.fontWeight      || null, renderHTML: attrs => attrs.fontWeight      ? { style: `font-weight:${attrs.fontWeight}` }       : {} },
      fontStyle:      { default: null, parseHTML: el => el.style.fontStyle       || null, renderHTML: attrs => attrs.fontStyle       ? { style: `font-style:${attrs.fontStyle}` }         : {} },
      className:      { default: null, parseHTML: el => el.getAttribute('class') || null, renderHTML: attrs => attrs.className ? { class: attrs.className } : {} },
      id:             { default: null, parseHTML: el => el.getAttribute('id') || null, renderHTML: attrs => attrs.id ? { id: attrs.id } : {} },
      kotoRole:       { default: null, parseHTML: el => el.getAttribute('data-koto-role') || null, renderHTML: attrs => attrs.kotoRole ? { 'data-koto-role': attrs.kotoRole } : {} },
    };
  },
  parseHTML() {
    return [{ tag: 'p' }];
  },
  renderHTML({ HTMLAttributes, node }) {
    // Merge all style attributes into one style string
    const styles = [];
    const a = node.attrs;
    if (a.textAlign)     styles.push(`text-align:${a.textAlign}`);
    if (a.marginLeft)    styles.push(`margin-left:${a.marginLeft}`);
    if (a.marginRight)   styles.push(`margin-right:${a.marginRight}`);
    if (a.marginTop)     styles.push(`margin-top:${a.marginTop}`);
    if (a.marginBottom)  styles.push(`margin-bottom:${a.marginBottom}`);
    if (a.lineHeight)    styles.push(`line-height:${a.lineHeight}`);
    if (a.textIndent)    styles.push(`text-indent:${a.textIndent}`);
    if (a.paddingLeft)   styles.push(`padding-left:${a.paddingLeft}`);
    if (a.fontSize)      styles.push(`font-size:${a.fontSize}`);
    if (a.fontFamily)    styles.push(`font-family:${a.fontFamily}`);
    if (a.fontWeight)    styles.push(`font-weight:${a.fontWeight}`);
    if (a.fontStyle)     styles.push(`font-style:${a.fontStyle}`);
    const merged = { ...HTMLAttributes };
    if (styles.length) merged.style = styles.join(';');
    return ['p', merged, 0];
  },
});

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

function _normalizeHdrFtrHtml(html) {
  return String(html || '')
    .replace(/<p(?:\s[^>]*)?>\s*(?:<br\s*\/?>|&nbsp;|\s)*<\/p>/gi, '')
    .replace(/&nbsp;/gi, ' ')
    .trim();
}

function _hdrFtrSlotLabel(slotType) {
  return slotType === 'footer' ? '页脚' : '页眉';
}

function _markHdrFtrOverlayActive(overlay) {
  const root = document.getElementById('wa-docx-editor') || document;
  root.querySelectorAll('.koto-hdrftr-overlay.is-active').forEach((el) => {
    if (el !== overlay) el.classList.remove('is-active');
  });
  if (overlay) overlay.classList.add('is-active');
}

function _clearHdrFtrOverlayActive(overlay) {
  if (overlay) overlay.classList.remove('is-active');
}

function _isHdrFtrToolbarInteractionLocked() {
  return Number(window.__kotoHdrFtrToolbarUntil || 0) > Date.now();
}

function _notifyHdrFtrSelectionChanged() {
  if (typeof window._kotoDocxSelectionChanged === 'function') {
    window._kotoDocxSelectionChanged();
  }
}

function _initialHdrFtrOverlayHtml(html) {
  return _normalizeHdrFtrHtml(html) ? html : '<p><br></p>';
}

function _focusHdrFtrOverlay(overlay) {
  if (!overlay || !window.getSelection || !document.createRange) return;
  const target = overlay.querySelector('p,div,li,blockquote,h1,h2,h3,h4,h5,h6') || overlay;
  if (!target) return;
  if (!target.childNodes.length) target.appendChild(document.createElement('br'));
  const range = document.createRange();
  range.selectNodeContents(target);
  range.collapse(false);
  const sel = window.getSelection();
  try {
    sel.removeAllRanges();
    sel.addRange(range);
  } catch (_) {}
}

function _setHdrFtrSlotState(slotEl, html, slotType) {
  if (!slotEl) return;
  const hasContent = !!_normalizeHdrFtrHtml(html);
  const slotLabel = _hdrFtrSlotLabel(slotType);
  slotEl.dataset.slotType = slotType;
  slotEl.dataset.slotLabel = slotLabel;
  slotEl.title = `双击编辑${slotLabel}`;
  slotEl.classList.toggle('is-empty', !hasContent);
  slotEl.innerHTML = hasContent ? html : '';
}

// ─────────────────────────────────────────────────────────────────────────────
// DocxPageBreak
// An in-flow block node that creates REAL vertical space between pages.
// Instead of a z-index overlay, the NodeView renders a full structural
// gap: bottom-margin zone → gray gap → top-margin zone, each occupying
// actual height in the document so content is never hidden behind them.
//
// Header / footer HTML is supplied via extension storage after the editor
// is created:
//   editor.storage.docxPageBreak.headerHtml = '<p>…</p>';
//   editor.storage.docxPageBreak.footerHtml = '<p>…</p>';
// ─────────────────────────────────────────────────────────────────────────────
export const DocxPageBreak = Node.create({
  name: 'docxPageBreak',
  group: 'block',
  atom: true,
  selectable: false,

  addStorage() {
    return { headerHtml: '', footerHtml: '' };
  },

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
      // ── Root wrapper ─────────────────────────────────────────────────
      const dom = document.createElement('div');
      dom.setAttribute('data-page-break', '');
      dom.setAttribute('data-page-num', String(Math.max(1, Number.parseInt(node.attrs.page, 10) || 1)));
      dom.setAttribute('data-section-idx', String(Math.max(0, Number.parseInt(node.attrs.sectionIdx, 10) || 0)));
      dom.setAttribute('data-current-section-idx', String(Math.max(0, Number.parseInt(node.attrs.currentSectionIdx, 10) || 0)));
      dom.setAttribute('data-next-section-idx', String(Math.max(0, Number.parseInt(node.attrs.nextSectionIdx, 10) || Number.parseInt(node.attrs.sectionIdx, 10) || 0)));
      dom.setAttribute('data-content-fill-px', '0');
      dom.className = 'koto-page-break';
      dom.setAttribute('contenteditable', 'false');

      const fillEl = document.createElement('div');
      fillEl.className = 'koto-pb-fill';
      dom.appendChild(fillEl);

      // ── Bottom zone of the upper page (white, with footer) ───────────
      const endZone = document.createElement('div');
      endZone.className = 'koto-pb-end';

      // Footer content
      const footerEl = document.createElement('div');
      footerEl.className = 'koto-pb-footer';
      _setHdrFtrSlotState(footerEl, '', 'footer');
      endZone.appendChild(footerEl);

      dom.appendChild(endZone);

      // ── Gap between pages (canvas-colored separator) ─────────────────
      const gapZone = document.createElement('div');
      gapZone.className = 'koto-pb-gap';
      dom.appendChild(gapZone);

      // ── Top zone of the next page (white, with header) ───────────────
      const startZone = document.createElement('div');
      startZone.className = 'koto-pb-start';

      // Header content
      const headerEl = document.createElement('div');
      headerEl.className = 'koto-pb-header';
      _setHdrFtrSlotState(headerEl, '', 'header');
      startZone.appendChild(headerEl);

      dom.appendChild(startZone);

      // ── Click-to-edit overlay for header/footer ───────────────────────
      const _openOverlay = (targetEl, type) => {
        if (targetEl.querySelector('.koto-hdrftr-overlay')) return;
        targetEl.classList.add('is-editing');
        const overlay = document.createElement('div');
        overlay.className = 'koto-hdrftr-overlay';
        overlay.setAttribute('contenteditable', 'true');
        overlay.dataset.slotType = type;
        overlay.innerHTML = _normalizeHdrFtrHtml(targetEl.innerHTML) ? targetEl.innerHTML : '<p></p>';
        const overlayOutline = type === 'header'
          ? 'outline:none;outline-offset:0;'
          : 'outline:1px dashed rgba(79,126,255,.5);outline-offset:-1px;';
        overlay.style.cssText = `position:absolute;top:0;left:0;right:0;bottom:0;z-index:10;background:#fff;padding:inherit;box-sizing:border-box;${overlayOutline}`;

        const _finish = () => {
          const newHtml = _normalizeHdrFtrHtml(overlay.innerHTML) ? overlay.innerHTML : '';
          overlay.remove();
          targetEl.classList.remove('is-editing');
          _setHdrFtrSlotState(targetEl, newHtml, type);
          if (editor.storage?.docxPageBreak) editor.storage.docxPageBreak[type === 'header' ? 'headerHtml' : 'footerHtml'] = newHtml;
          if (editor.storage?.autoPageBreak) {
            const storageKey = type === 'header' ? 'headerHtml' : 'footerHtml';
            editor.storage.autoPageBreak[storageKey] = newHtml;
            if (Array.isArray(editor.storage.autoPageBreak.sections)) {
              editor.storage.autoPageBreak.sections.forEach((section) => {
                if (section && typeof section === 'object') {
                  section[type === 'header' ? 'header_html' : 'footer_html'] = newHtml;
                }
              });
            }
          }
          const root = dom.closest('#wa-docx-editor');
          if (!root) return;
          root.querySelectorAll(type === 'header' ? '.koto-pb-header' : '.koto-pb-footer').forEach((sib) => {
            if (sib !== targetEl) _setHdrFtrSlotState(sib, newHtml, type);
          });
          const flEl = root.querySelector(type === 'header' ? '.koto-page-header-first' : '.koto-page-footer-last');
          if (flEl && flEl.dataset.variant !== 'first') {
            _setHdrFtrSlotState(flEl, newHtml, type);
          }
        };

        overlay.addEventListener('blur', _finish);
        overlay.addEventListener('keydown', (e) => {
          if (e.key === 'Escape') { overlay.blur(); }
          if (e.key === 'Enter') { e.preventDefault(); document.execCommand('insertLineBreak'); }
        });
        targetEl.appendChild(overlay);
        overlay.focus();
      };

      headerEl.addEventListener('dblclick', (e) => { e.stopPropagation(); _openOverlay(headerEl, 'header'); });
      footerEl.addEventListener('dblclick', (e) => { e.stopPropagation(); _openOverlay(footerEl, 'footer'); });

      // ── Deferred header/footer injection ─────────────────────────────
      // storage.docxPageBreak is set by render() AFTER new Editor() returns,
      // so NodeViews created during parsing read empty defaults.  Retry on
      // rAF and again at 200ms to guarantee content is filled.
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

        dom.style.marginLeft = `-${mLeft}px`;
        dom.style.marginRight = `-${mRight}px`;
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

/** Build the DOM element rendered for each soft page break widget. */
function _buildSoftBreakWidget(pageNum, headerHtml, footerHtml, marginTopPx, marginBottomPx, marginLeftPx, marginRightPx, pageWidthPx, extStorage, contentFillPx = 0) {
  const dom = document.createElement('div');
  dom.setAttribute('data-soft-page-break', String(pageNum));
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

  return dom;
}

function _buildInlineSoftBreakWidget(pageNum, headerHtml, footerHtml, marginTopPx, marginBottomPx, marginLeftPx, marginRightPx, pageWidthPx, extStorage, contentFillPx = 0) {
  const anchor = document.createElement('span');
  anchor.className = 'koto-inline-page-break-anchor';
  anchor.setAttribute('contenteditable', 'false');
  anchor.style.display = 'block';
  anchor.style.width = '100%';
  anchor.style.lineHeight = '0';
  anchor.style.fontSize = '0';

  const widget = _buildSoftBreakWidget(
    pageNum,
    headerHtml,
    footerHtml,
    marginTopPx,
    marginBottomPx,
    marginLeftPx,
    marginRightPx,
    pageWidthPx,
    extStorage,
    contentFillPx,
  );
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

  const range = domEl.ownerDocument.createRange();
  range.selectNodeContents(domEl);
  const lines = _normalizeDocxLineHeights(
    _groupDocxLineRects(Array.from(range.getClientRects() || [])),
    domEl.offsetHeight || 0,
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
      nextPage += 1;
      nextUsed = 0;
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

function _suppressDocxSoftPageBreaksForMeasurement(root) {
  const records = [];
  try {
    root?.querySelectorAll?.(_DOCX_SOFT_PAGE_BREAK_SELECTOR).forEach((node) => {
      if (!node || !node.style) return;
      records.push([node, node.style.display]);
      node.style.display = 'none';
    });
  } catch (_) {}

  return () => {
    records.forEach(([node, display]) => {
      try {
        if (node && node.style) node.style.display = display || '';
      } catch (_) {}
    });
  };
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

  const widget = _buildSoftBreakWidget(
    pageNum,
    headerHtml,
    footerHtml,
    marginTopPx,
    marginBottomPx,
    marginLeftPx,
    marginRightPx,
    pageWidthPx,
    extStorage,
    contentFillPx,
  );
  widget.style.marginLeft = `${-Math.round(tableLeftOffsetPx || 0)}px`;
  widget.style.marginRight = '0';
  widget.style.position = 'relative';
  widget.style.left = '0';
  widget.style.transform = 'none';
  if (pageWidthPx) {
    widget.style.width = pageWidthPx + 'px';
    widget.style.maxWidth = pageWidthPx + 'px';
  }

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
        let _timer = null;
        let _measuring = false;  // guard against re-entrant measurement
        let _mediaResizeObserver = null;
        const _watchedMedia = new Map();

        const _schedule = (delayMs = _AUTO_PB_UPDATE_DELAY_MS) => {
          clearTimeout(_timer);
          _timer = setTimeout(() => {
            requestAnimationFrame(() => _measure(editorView));
          }, delayMs);
        };

        const _scheduleAfterMediaSettles = () => _schedule(40);

        const _watchMediaForPagination = (view) => {
          const pmDom = view?.dom;
          if (!pmDom || !pmDom.querySelectorAll) return;

          if (
            typeof ResizeObserver !== 'undefined'
            && !_mediaResizeObserver
          ) {
            _mediaResizeObserver = new ResizeObserver(() => {
              _scheduleAfterMediaSettles();
            });
          }

          const mediaNodes = Array.from(pmDom.querySelectorAll(
            'img,svg,canvas,video,.koto-img-wrapper'
          ));

          mediaNodes.forEach((node) => {
            if (!node || _watchedMedia.has(node)) return;
            const onSettled = () => _scheduleAfterMediaSettles();
            _watchedMedia.set(node, onSettled);

            try {
              _mediaResizeObserver?.observe(node);
            } catch (_) {}

            if (node.tagName === 'IMG' || node.tagName === 'VIDEO') {
              node.addEventListener('load', onSettled, { passive: true });
              node.addEventListener('error', onSettled, { passive: true });

              if (node.tagName === 'IMG' && node.complete) {
                _scheduleAfterMediaSettles();
              }
            }
          });
        };

        const _measure = (view) => {
          if (_measuring) return;
          _measuring = true;
          const restoreSoftBreaks = _suppressDocxSoftPageBreaksForMeasurement(view?.dom);
          try {
            _measureInner(view);
          } finally {
            restoreSoftBreaks();
            _measuring = false;
          }
        };

        const _measureInner = (view) => {
          const doc    = view.state.doc;
          const pmDom  = view.dom;  // the .ProseMirror editable div

          // ── Read config from extension storage ──────────────────────────
          const pageW      = extStorage.pageWidthPx    || 816;
          const pageH      = extStorage.pageHeightPx   || 1056;
          const mTop       = extStorage.marginTopPx    || 96;
          const mBot       = extStorage.marginBottomPx || 80;
          const mLeft      = extStorage.marginLeftPx   || 96;
          const mRight     = extStorage.marginRightPx  || 96;
          const hdrHtml    = extStorage.headerHtml     || '';
          const ftrHtml    = extStorage.footerHtml     || '';
          const sectionsAr = extStorage.sections       || [];

          // ── Content height per page ────────────────────────────────────
          // In Word, headers/footers are positioned within the margin areas
          // (between page edge and margin boundary).  They do NOT reduce the
          // usable content area unless they overflow the margin, which is
          // rare.  Content area = page_height - top_margin - bottom_margin.
          const contentH   = pageH - mTop - mBot;

          _measureClean(view);
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
                      const extra = Math.floor(overflow / contentH);
                      pageNum += 1 + extra;
                      usedH = overflow % contentH;
                    } else {
                      pageNum++;
                      usedH = 0;
                    }
                  }
                }
                continue;
              }
            }

            let blockH = _measureDocxBlockOuterHeightPx(domEl);

            if (blockH <= 0) continue;

            const remaining = contentH - usedH;
            if (usedH > 0 && blockH > remaining) {
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
                  breaks.push(...textPlan.breaks);
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
                const extra = Math.floor(blockH / contentH);
                pageNum += extra;
                usedH = blockH % contentH;
                if (usedH === 0) usedH = contentH;
              } else {
                usedH = blockH;
              }
            } else {
              usedH += blockH;
              if (usedH >= contentH) {
                const overflow = usedH - contentH;
                if (overflow > 0) {
                  const extra = Math.floor(overflow / contentH);
                  pageNum += 1 + extra;
                  usedH = overflow % contentH;
                } else {
                  pageNum++;
                  usedH = 0;
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
            const decos = breaks.map(({ pos, pageNum: pn, currentSectionIdx: csi, nextSectionIdx: nsi, contentFillPx, tableCols, tableLeftOffsetPx, inline }) => {
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
                      breakChrome.pageWidthPx,
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
                        breakChrome.pageWidthPx,
                        extStorage,
                        contentFillPx,
                      )
                      : _buildSoftBreakWidget(
                        pn,
                        breakChrome.nextPage.headerHtml,
                        breakChrome.currentPage.footerHtml,
                        breakChrome.marginTopPx,
                        breakChrome.marginBottomPx,
                        breakChrome.marginLeftPx,
                        breakChrome.marginRightPx,
                        breakChrome.pageWidthPx,
                        extStorage,
                        contentFillPx,
                      );
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

          view.dispatch(view.state.tr.setMeta(_AUTO_PB_KEY, decoSet));
        };

        _watchMediaForPagination(editorView);
        _schedule(_AUTO_PB_INITIAL_DELAY_MS);

        return {
          update(view, prevState) {
            // Only re-measure when doc content changed (not on meta dispatches)
            if (view.state.doc !== prevState.doc) {
              _watchMediaForPagination(view);
              _schedule();
            }
          },
          destroy() {
            clearTimeout(_timer);
            if (_mediaResizeObserver) {
              try { _mediaResizeObserver.disconnect(); } catch (_) {}
              _mediaResizeObserver = null;
            }
            _watchedMedia.forEach((onSettled, node) => {
              try {
                node.removeEventListener('load', onSettled);
                node.removeEventListener('error', onSettled);
              } catch (_) {}
            });
            _watchedMedia.clear();
          },
        };
      },
    })];
  },
});
