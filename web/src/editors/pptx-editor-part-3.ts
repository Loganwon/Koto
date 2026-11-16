// @ts-nocheck
import { getFeatureRegistry } from '../shared/feature-registry';
import {
  placeFixedInViewport,
  viewportDeltaToElement,
} from '../shared/ui-scale';

const WA = getFeatureRegistry();
const $ = (id: string): HTMLElement | null => document.getElementById(id);
const _hexLuma = (...args: any[]): any => WA._hexLuma?.(...args);
const _runTextDecoration = (...args: any[]): any => WA._runTextDecoration?.(...args);
const _safeTextColor = (...args: any[]): any => WA._safeTextColor?.(...args);
const _shouldIgnorePptxGlobalKeydown = (...args: any[]): boolean => Boolean(WA._shouldIgnorePptxGlobalKeydown?.(...args));
const _extractPptxTableText = (...args: any[]): string => String(WA._extractPptxTableText?.(...args) || '');
const _normalizePptxTableSelection = (...args: any[]): any => WA._normalizePptxTableSelection?.(...args) || null;
const _pinSelectionChip = (...args: any[]): void => WA._pinSelectionChip?.(...args);
const _positionSelectionToolbar = (...args: any[]): void => WA._positionSelectionToolbar?.(...args);
const _updateContextBar = (...args: any[]): void => WA._updateContextBar?.(...args);
const _PENCIL_SVG = String(WA._PENCIL_SVG || '');
const _TRASH_SVG = String(WA._TRASH_SVG || '');
const _CLIPBOARD_SVG = String(WA._CLIPBOARD_SVG || '');

import { KotoPptxEditorPart2 } from './pptx-editor-part-2';

export class KotoPptxEditorPart3 extends KotoPptxEditorPart2 {

    // ── Resize shape ─────────────────────────────────────────────────────────

    _startResize(e, el, shape, canvas, scale, handleType) {
      const startX = e.clientX, startY = e.clientY;
      const startLeft = el.offsetLeft, startTop = el.offsetTop;
      const startW = el.offsetWidth, startH = el.offsetHeight;
      const pxW = canvas.offsetWidth, pxH = canvas.offsetHeight;
      const MIN_W = 30, MIN_H = 20;

      const onMove = (ev) => {
        const { x: dx, y: dy } = viewportDeltaToElement(canvas, ev.clientX - startX, ev.clientY - startY);
        let newLeft = startLeft, newTop = startTop;
        let newW = startW, newH = startH;

        if (handleType.includes('e')) newW = Math.max(MIN_W, startW + dx);
        if (handleType.includes('s')) newH = Math.max(MIN_H, startH + dy);
        if (handleType.includes('w')) {
          newW = Math.max(MIN_W, startW - dx);
          newLeft = startLeft + startW - newW;
        }
        if (handleType.includes('n')) {
          newH = Math.max(MIN_H, startH - dy);
          newTop = startTop + startH - newH;
        }
        // Clamp to canvas bounds
        newLeft = Math.max(0, Math.min(pxW - MIN_W, newLeft));
        newTop  = Math.max(0, Math.min(pxH - MIN_H, newTop));

        el.style.left   = newLeft + 'px';
        el.style.top    = newTop  + 'px';
        el.style.width  = newW    + 'px';
        el.style.height = newH    + 'px';
      };

      const onUp = () => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        // Snapshot BEFORE writing back (data model still has pre-drag values)
        this._pushUndo();
        // Write back to data model in EMU
        shape.left   = Math.round(parseInt(el.style.left)   / scale);
        shape.top    = Math.round(parseInt(el.style.top)    / scale);
        shape.width  = Math.round(parseInt(el.style.width)  / scale);
        shape.height = Math.round(parseInt(el.style.height) / scale);
        this._redrawThumb(this._curIdx);
        WA.scheduleAutoSave();
      };

      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    }

    // ── Drag to move ─────────────────────────────────────────────────────────

    _startMove(e, el, shape, canvas, scale, enterEditOnClick = false, allowDrag = true) {
      // preventDefault/stopPropagation only happen once movement exceeds threshold.
      e.stopPropagation();

      const startX = e.clientX, startY = e.clientY;
      const origLeft = el.offsetLeft, origTop = el.offsetTop;
      const pxW = canvas.offsetWidth, pxH = canvas.offsetHeight;
      let moved = false;

      const onMove = (ev) => {
        const visualDx = ev.clientX - startX, visualDy = ev.clientY - startY;
        if (Math.abs(visualDx) < 4 && Math.abs(visualDy) < 4) return;
        const { x: dx, y: dy } = viewportDeltaToElement(canvas, visualDx, visualDy);
        if (!allowDrag) return;  // interior text click — don't drag shape
        ev.preventDefault();
        if (!moved) { window.getSelection && window.getSelection().removeAllRanges(); }
        moved = true;
        el.style.cursor = 'grabbing';
        const newL = Math.max(0, Math.min(pxW - el.offsetWidth,  origLeft + dx));
        const newT = Math.max(0, Math.min(pxH - el.offsetHeight, origTop  + dy));
        el.style.left = newL + 'px';
        el.style.top  = newT + 'px';
      };

      const onUp = (ev) => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        el.style.cursor = shape.has_text ? 'text' : '';
        if (moved) {
          // Snapshot BEFORE writing back (el.style already updated, data model still old)
          this._pushUndo();
          // Write back to data model in EMU
          shape.left = Math.round(parseInt(el.style.left)  / scale);
          shape.top  = Math.round(parseInt(el.style.top)   / scale);
          this._redrawThumb(this._curIdx);
          WA.scheduleAutoSave();
        } else if (enterEditOnClick && shape.has_text && !this._editMode) {
          // Click (no drag) on an already-selected text shape → enter edit mode.
          // Place cursor at click position using caretRangeFromPoint for precision.
          this._enterEditModeAtPoint(el, ev.clientX, ev.clientY);
        }
      };

      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    }

    // Enter edit mode and try to place the cursor at (x, y) screen coordinates.
    _enterEditModeAtPoint(el, x, y) {
      if (this._editMode && this._selShape === el) return;
      this._editMode = true;
      el.classList.add('wa-pptx-editing');
      const _inner = el.querySelector('.wa-pptx-inner');
      if (_inner) {
        _inner.contentEditable = 'true';
        _inner.querySelectorAll('.wa-pptx-run').forEach(s => s.removeAttribute('contenteditable'));
      } else {
        el.querySelectorAll('.wa-pptx-run').forEach(s => { s.contentEditable = 'true'; });
      }

      // Attempt precise caret placement at click point
      let placed = false;
      try {
        let range = null;
        if (document.caretRangeFromPoint) {
          range = document.caretRangeFromPoint(x, y);
        } else if (document.caretPositionFromPoint) {
          const pos = document.caretPositionFromPoint(x, y);
          if (pos) { range = document.createRange(); range.setStart(pos.offsetNode, pos.offset); range.collapse(true); }
        }
        if (range) {
          const node = range.startContainer;
          const span = node.nodeType === 3 ? node.parentElement : node;
          if (span && span.classList && span.classList.contains('wa-pptx-run')) {
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
            span.focus();
            this._activeSpan = span;
            placed = true;
          }
        }
      } catch (_) { /* ignore */ }

      if (!placed) {
        const first = el.querySelector('.wa-pptx-run');
        if (first) { first.focus(); this._activeSpan = first; }
      }
    }

    _setActiveTableSummary(shape, selection = null) {
      if (shape && shape._type === 'TABLE' && Array.isArray(shape.cells)) {
        const normalized = _normalizePptxTableSelection(selection, shape.table_rows || 0, shape.table_cols || 0);
        this._lastTableText = _extractPptxTableText(shape, normalized);
        this._lastTableRows = normalized ? normalized.rows : (shape.table_rows || 0);
        this._lastTableCols = normalized ? normalized.cols : (shape.table_cols || 0);
        return;
      }
      this._lastTableText = null;
      this._lastTableRows = 0;
      this._lastTableCols = 0;
    }

    _clearTableSelection({ restoreWholeTableSummary = true } = {}) {
      if (this._tableSelectionCleanup) {
        try { this._tableSelectionCleanup(); } catch (_) { /* allowed to fail */ }
        this._tableSelectionCleanup = null;
      }

      const previousSelection = this._tableSelection;
      if (previousSelection && previousSelection.tableEl) {
        previousSelection.tableEl.querySelectorAll('.wa-pptx-cell-selected').forEach((cell) => {
          cell.classList.remove('wa-pptx-cell-selected');
        });
      }
      this._tableSelection = null;

      if (restoreWholeTableSummary && previousSelection && this._selShape) {
        const activeShapeId = Number(this._selShape.dataset.shapeId);
        if (activeShapeId === previousSelection.shapeId) {
          this._setActiveTableSummary(previousSelection.shape);
        }
      }
    }

    _setTableSelection(shapeEl, shape, tableEl, anchorCell, headCell = anchorCell) {
      const normalized = _normalizePptxTableSelection({
        anchorRow: anchorCell && anchorCell.row,
        anchorCol: anchorCell && anchorCell.col,
        headRow: headCell && headCell.row,
        headCol: headCell && headCell.col,
      }, shape.table_rows || 0, shape.table_cols || 0);
      if (!normalized || !tableEl) return null;

      this._tableSelection = Object.assign({
        shapeId: shape.id,
        shape,
        shapeEl,
        tableEl,
      }, normalized);

      tableEl.querySelectorAll('.wa-pptx-cell').forEach((cell) => {
        const row = Number(cell.dataset.row);
        const col = Number(cell.dataset.col);
        const isSelected = Number.isFinite(row) && Number.isFinite(col)
          && row >= normalized.startRow && row <= normalized.endRow
          && col >= normalized.startCol && col <= normalized.endCol;
        cell.classList.toggle('wa-pptx-cell-selected', isSelected);
      });

      this._setActiveTableSummary(shape, this._tableSelection);
      return this._tableSelection;
    }

    _beginTableSelection(event, shapeEl, shape, tableEl, startCellEl) {
      if (!event || event.button !== 0 || !startCellEl) return;

      const startCell = {
        row: Number(startCellEl.dataset.row),
        col: Number(startCellEl.dataset.col),
      };
      if (!Number.isFinite(startCell.row) || !Number.isFinite(startCell.col)) return;

      const previousSelection = this._tableSelection;
      const anchorCell = event.shiftKey && previousSelection && previousSelection.shapeId === shape.id
        ? { row: previousSelection.anchorRow, col: previousSelection.anchorCol }
        : startCell;

      this._clearTableSelection({ restoreWholeTableSummary: false });
      this._setTableSelection(shapeEl, shape, tableEl, anchorCell, startCell);

      const resolveCellFromPoint = (clientX, clientY) => {
        const target = document.elementFromPoint(clientX, clientY);
        const cell = target && target.closest ? target.closest('.wa-pptx-cell') : null;
        if (!cell || !tableEl.contains(cell)) return null;

        const row = Number(cell.dataset.row);
        const col = Number(cell.dataset.col);
        return Number.isFinite(row) && Number.isFinite(col) ? { row, col } : null;
      };

      const cleanup = () => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        if (this._tableSelectionCleanup === cleanup) this._tableSelectionCleanup = null;
      };

      const onMove = (moveEvent) => {
        if ((moveEvent.buttons & 1) === 0) {
          cleanup();
          return;
        }

        const headCell = resolveCellFromPoint(moveEvent.clientX, moveEvent.clientY);
        if (!headCell) return;

        moveEvent.preventDefault();
        this._setTableSelection(shapeEl, shape, tableEl, anchorCell, headCell);
      };

      const onUp = (upEvent) => {
        const headCell = resolveCellFromPoint(upEvent.clientX, upEvent.clientY);
        if (headCell) this._setTableSelection(shapeEl, shape, tableEl, anchorCell, headCell);
        cleanup();
      };

      this._tableSelectionCleanup = cleanup;
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    }

    getCellSelectionInfo() {
      const selection = this._tableSelection;
      if (!selection || !selection.shape || !selection.tableEl) return null;

      const totalRows = selection.shape.table_rows || 0;
      const totalCols = selection.shape.table_cols || 0;
      if (selection.rows === totalRows && selection.cols === totalCols) return null;

      const text = _extractPptxTableText(selection.shape, selection).trim();
      if (!text) return null;

      return {
        text,
        rows: selection.rows,
        cols: selection.cols,
        selectedCells: selection.rows * selection.cols,
        tableElement: selection.tableEl,
      };
    }

    getWholeTableSelectionInfo() {
      const selection = this._tableSelection;
      if (selection && selection.shape && selection.tableEl) {
        const totalRows = selection.shape.table_rows || 0;
        const totalCols = selection.shape.table_cols || 0;
        if (selection.rows !== totalRows || selection.cols !== totalCols) return null;

        const text = _extractPptxTableText(selection.shape, selection).trim();
        if (!text) return null;
        return {
          text,
          rows: totalRows,
          cols: totalCols,
          tableElement: selection.tableEl,
        };
      }

      if (!this._selShape) return null;
      const slide = this.data && this.data.slides && this.data.slides[this._curIdx];
      const shapeId = Number(this._selShape.dataset.shapeId);
      const shape = slide && (slide.shapes || []).find((item) => item.id === shapeId);
      if (!shape || shape._type !== 'TABLE' || !shape.cells) return null;

      const text = _extractPptxTableText(shape).trim();
      if (!text) return null;

      return {
        text,
        rows: shape.table_rows || 0,
        cols: shape.table_cols || 0,
        tableElement: this._selShape.querySelector('table'),
      };
    }

    _selectShape(el, shape) {
      if (el === this._selShape) return;  // already selected — don't wipe edit mode
      this._clearSelection();
      this._selShape = el;
      el.classList.add('wa-pptx-selected');
      // Add 8 resize handles (CSS positions them at corners + edge midpoints)
      const _canvas = $('wa-pptx-slide-canvas');
      ['nw','n','ne','e','se','s','sw','w'].forEach(hType => {
        const hEl = document.createElement('div');
        hEl.className = 'wa-pptx-handle';
        hEl.dataset.h = hType;
        hEl.addEventListener('mousedown', e => {
          e.stopPropagation();
          e.preventDefault();
          this._startResize(e, el, shape, _canvas, this._scale || 1, hType);
        });
        el.appendChild(hEl);
      });
      // Store table data so the mouseup handler can expose it to AI quick-actions
      this._setActiveTableSummary(shape);
      // Show PPTX format hoverbar when a text shape is selected (even without entering edit mode)
      if (shape && shape.has_text) {
        setTimeout(() => {
          const hb = document.getElementById('wa-pptx-hoverbar');
          if (!hb) return;
          const shapeEl = el;
          const rect = shapeEl.getBoundingClientRect();
          hb.style.visibility = 'hidden';
          hb.style.display = 'flex';
          const hbRect = hb.getBoundingClientRect();
          const hbW = hbRect.width || 360;
          const hbH = hbRect.height || 30;
          let top = rect.top - hbH - 6;
          if (top < 60) top = rect.bottom + 6;
          const left = rect.left + rect.width / 2 - hbW / 2;
          placeFixedInViewport(hb, left, top, 8);
          hb.style.visibility = '';
        }, 20);
      } else {
        // Non-text shape selected — hide the format hoverbar if it was open
        this._hideHoverBar();
      }
      // Sync shape format toolbar
      if (shape) {
        const fillSw = $('wa-pptx-shapefill-swatch');
        if (fillSw) fillSw.style.background = shape.fill || '#fff';
        if ($('wa-pptx-shapefill')) $('wa-pptx-shapefill').value = shape.fill || '#ffffff';
        const borderSw = $('wa-pptx-shapeborder-swatch');
        if (borderSw) borderSw.style.background = (shape.border && shape.border.color) || '#000';
        if ($('wa-pptx-shapeborder')) $('wa-pptx-shapeborder').value = (shape.border && shape.border.color) || '#000000';
        if ($('wa-pptx-borderwidth')) $('wa-pptx-borderwidth').value = (shape.border && shape.border.width) || 0;
        // Populate Format tab (size / pos / rotation) from DOM geometry
        const canvasEl = $('wa-pptx-slide-canvas');
        if (canvasEl && el) {
          const scaleW = parseFloat(canvasEl.style.width)  / (this.data.slideWidthEmu  || 1);
          const scaleH = parseFloat(canvasEl.style.height) / (this.data.slideHeightEmu || 1);
          const pxW = Math.round((shape.width  || 0) * scaleW);
          const pxH = Math.round((shape.height || 0) * scaleH);
          const pxX = Math.round((shape.left   || 0) * scaleW);
          const pxY = Math.round((shape.top    || 0) * scaleH);
          if ($('wa-pptx-shapeW'))   $('wa-pptx-shapeW').value   = pxW;
          if ($('wa-pptx-shapeH'))   $('wa-pptx-shapeH').value   = pxH;
          if ($('wa-pptx-shapeX'))   $('wa-pptx-shapeX').value   = pxX;
          if ($('wa-pptx-shapeY'))   $('wa-pptx-shapeY').value   = pxY;
          if ($('wa-pptx-shapeRot')) $('wa-pptx-shapeRot').value = Math.round(shape.rotation || 0);
        }
        if ($('wa-pptx-opacity')) $('wa-pptx-opacity').value = Math.round((shape.opacity !== undefined ? shape.opacity : 1) * 100);
      }
    }

    _clearSelection() {
      this._clearTableSelection({ restoreWholeTableSummary: false });
      if (this._selShape) {
        this._selShape.classList.remove('wa-pptx-selected');
        // Remove resize handles
        this._selShape.querySelectorAll('.wa-pptx-handle').forEach(h => h.remove());
        this._selShape.style.overflow = 'hidden';
        const _inner = this._selShape.querySelector('.wa-pptx-inner');
        if (_inner) {
          _inner.contentEditable = 'false';
          _inner.querySelectorAll('.wa-pptx-run').forEach(s => { s.contentEditable = 'false'; });
        } else {
          this._selShape.querySelectorAll('.wa-pptx-run').forEach(s => { s.contentEditable = 'false'; });
        }
        this._selShape.querySelectorAll('.wa-pptx-cell').forEach(td => { td.contentEditable = 'false'; td.blur(); });
        this._selShape = null;
      }
      this._editMode = false;
      this._lastTableText = null;
      this._lastTableRows = 0;
      this._lastTableCols = 0;
      this._hideHoverBar();
    }

    _enterEditMode(el) {
      if (this._editMode && this._selShape === el) return;  // already editing this shape
      this._editMode = true;
      el.classList.add('wa-pptx-editing');
      // Make inner container the single contentEditable region so cross-run/line selection works
      const _inner = el.querySelector('.wa-pptx-inner');
      if (_inner) {
        _inner.contentEditable = 'true';
        _inner.querySelectorAll('.wa-pptx-run').forEach(s => s.removeAttribute('contenteditable'));
      } else {
        el.querySelectorAll('.wa-pptx-run').forEach(s => { s.contentEditable = 'true'; });
      }
      const first = el.querySelector('.wa-pptx-run');
      if (first) {
        first.focus();
        this._activeSpan = first;
        // Explicitly place cursor at end of span so empty spans are reliably typeable
        try {
          const r = document.createRange();
          r.selectNodeContents(first);
          r.collapse(false);   // collapse to end
          const sel = window.getSelection();
          if (sel) { sel.removeAllRanges(); sel.addRange(r); }
        } catch (e) { console.warn("[Koto]", e) }
      }
    }

    _exitEditMode() {
      if (this._selShape) {
        this._selShape.classList.remove('wa-pptx-editing');
        const _inner = this._selShape.querySelector('.wa-pptx-inner');
        if (_inner) {
          _inner.contentEditable = 'false';
          _inner.querySelectorAll('.wa-pptx-run').forEach(s => { s.contentEditable = 'false'; s.blur(); });
        } else {
          this._selShape.querySelectorAll('.wa-pptx-run').forEach(s => { s.contentEditable = 'false'; s.blur(); });
        }
        this._selShape.querySelectorAll('.wa-pptx-cell').forEach(td => {
          td.contentEditable = 'false';
          td.blur();
        });
      }
      this._editMode = false;
      this._hideHoverBar();
    }

    // ── Floating format hover bar (文字格式助手) ───────────────────────────────

    _showHoverBar(range) {
      const hb = document.getElementById('wa-pptx-hoverbar');
      if (!hb) return;
      hb.style.display = 'flex';
      let rect = range.getBoundingClientRect();
      // Fallback: getClientRects()[0] for cross-block or single-caret selections
      if (!rect || rect.height === 0) {
        const rects = range.getClientRects();
        for (let i = 0; i < rects.length; i++) {
          if (rects[i].height > 0) { rect = rects[i]; break; }
        }
      }
      // Last resort: anchor to the selected shape element
      if (!rect || rect.height === 0) {
        const shapeEl = this._selShape && document.querySelector(`.wa-pptx-shape[data-si="${this._selShape.shapeIdx ?? ''}"]`);
        if (shapeEl) rect = shapeEl.getBoundingClientRect();
      }
      if (!rect || rect.height === 0) { hb.style.display = 'none'; return; }
      const hbRect = hb.getBoundingClientRect();
      const hbW = hbRect.width || 360;
      const hbH = hbRect.height || 30;
      let top = rect.top - hbH - 6;
      if (top < 60) top = rect.bottom + 6;
      const left = rect.left + rect.width / 2 - hbW / 2;
      placeFixedInViewport(hb, left, top, 8);
    }

    _hideHoverBar() {
      const hb = document.getElementById('wa-pptx-hoverbar');
      if (hb) hb.style.display = 'none';
    }

    _syncHoverBar(run) {
      if (!run) return;
      const hbName = document.getElementById('wa-hb-fontname');
      const hbSize = document.getElementById('wa-hb-fontsize');
      const hbBold = document.getElementById('wa-hb-bold');
      const hbItal = document.getElementById('wa-hb-italic');
      const hbUnd  = document.getElementById('wa-hb-underline');
      const hbSw   = document.getElementById('wa-hb-color-swatch');
      if (hbName && run.fontName) hbName.value = run.fontName;
      if (hbSize && run.size)     hbSize.value  = Math.round(run.size);
      if (hbBold)  hbBold.classList.toggle('active',  !!run.bold);
      if (hbItal)  hbItal.classList.toggle('active',  !!run.italic);
      if (hbUnd)   hbUnd.classList.toggle('active',   !!run.underline);
      if (hbSw && run.color) hbSw.style.background = run.color;
    }

    _onRunFocus(shapeEl, shape, pi, ri, run) {
      this._activeSpan = document.activeElement;  // save before focus can move to toolbar
      this._selectShape(shapeEl, shape);
      if ($('wa-pptx-bold'))        $('wa-pptx-bold').classList.toggle('active',        !!run.bold);
      if ($('wa-pptx-italic'))      $('wa-pptx-italic').classList.toggle('active',      !!run.italic);
      if ($('wa-pptx-underline'))   $('wa-pptx-underline').classList.toggle('active',   !!run.underline);
      if ($('wa-pptx-strike'))      $('wa-pptx-strike').classList.toggle('active',      !!run.strikethrough);
      if ($('wa-pptx-super'))       $('wa-pptx-super').classList.toggle('active',       !!run.superscript);
      if ($('wa-pptx-sub'))         $('wa-pptx-sub').classList.toggle('active',         !!run.subscript);
      const _hsFocus = $('wa-pptx-highlight-swatch');
      if (_hsFocus) _hsFocus.style.background = run.highlight || 'transparent';
      if ($('wa-pptx-fontsize') && run.size) $('wa-pptx-fontsize').value = Math.round(run.size);
      if ($('wa-pptx-fontname') && run.fontName) $('wa-pptx-fontname').value = run.fontName;
      if ($('wa-pptx-fontcolor') && run.color) {
        $('wa-pptx-fontcolor').value = run.color.startsWith('#') ? run.color : '#000000';
        const sw = $('wa-pptx-fontcolor-swatch');
        if (sw) sw.style.background = run.color;
      }
    }

    // Apply a single property to a run data object (no DOM update)
    _applyRunProp(run, prop, value) {
      if (prop === 'bold')          run.bold          = value;
      else if (prop === 'italic')        run.italic        = value;
      else if (prop === 'underline')     run.underline     = value;
      else if (prop === 'strikethrough') run.strikethrough = value;
      else if (prop === 'superscript')   { run.superscript = value; if (value) run.subscript = false; }
      else if (prop === 'subscript')     { run.subscript   = value; if (value) run.superscript = false; }
      else if (prop === 'highlight')     run.highlight     = value;
      else if (prop === 'size')          run.size          = parseFloat(value);
      else if (prop === 'fontName')      run.fontName      = value;
      else if (prop === 'color')         run.color         = value;
    }

    applyFormat(prop, value) {
      this._pushUndo();
      const slide = this.data.slides[this._curIdx];
      // Prefer _savedRange (set by selectionchange handler) so toolbar clicks don't lose selection
      const browserSel = window.getSelection && window.getSelection();
      const activeRange = (this._savedRange && !this._savedRange.collapsed)
        ? this._savedRange
        : (browserSel && browserSel.rangeCount > 0 && !browserSel.isCollapsed ? browserSel.getRangeAt(0) : null);
      const sel = activeRange ? { isCollapsed: false, rangeCount: 1, getRangeAt: () => activeRange,
        containsNode: (n, p) => browserSel ? browserSel.containsNode(n, p) : activeRange.intersectsNode(n) } : null;

      // ── Case 1: partial selection within ONE span → split run ──────────────
      if (sel && !sel.isCollapsed && sel.rangeCount > 0) {
        const range = sel.getRangeAt(0);
        const startSpan = range.startContainer.nodeType === Node.TEXT_NODE
          ? range.startContainer.parentElement : range.startContainer;
        const endSpan   = range.endContainer.nodeType === Node.TEXT_NODE
          ? range.endContainer.parentElement   : range.endContainer;

        if (startSpan === endSpan && startSpan.classList.contains('wa-pptx-run')) {
          const shapeId = parseInt(startSpan.dataset.shapeId);
          const pi      = parseInt(startSpan.dataset.pi);
          const ri      = parseInt(startSpan.dataset.ri);
          const shape   = (slide.shapes || []).find(s => s.id === shapeId);
          const para    = shape && shape.paragraphs[pi];
          const run     = para && para.runs[ri];
          if (run) {
            const s = range.startOffset, e = range.endOffset;
            const text = run.text;
            // Determine toggle value from current run state
            if (prop === 'bold')            value = !run.bold;
            else if (prop === 'italic')         value = !run.italic;
            else if (prop === 'underline')      value = !run.underline;
            else if (prop === 'strikethrough')  value = !run.strikethrough;
            else if (prop === 'superscript')    value = !run.superscript;
            else if (prop === 'subscript')      value = !run.subscript;

            if (s === 0 && e === text.length) {
              // Whole span selected — just apply to the run in-place, no split needed
              this._applyRunProp(run, prop, value);
              startSpan.style.fontWeight      = run.bold      ? 'bold'      : '';
              startSpan.style.fontStyle       = run.italic    ? 'italic'    : '';
              startSpan.style.textDecoration  = _runTextDecoration(run);
              if (prop === 'size') {
                const scaleW = parseFloat($('wa-pptx-slide-canvas').style.width) / this.data.slideWidthEmu;
                startSpan.style.fontSize = Math.max(Math.round(run.size * scaleW * 12700), 6) + 'px';
              }
              if (prop === 'fontName') startSpan.style.fontFamily = value;
              if (prop === 'color')    startSpan.style.color = value;
              if (prop === 'superscript' || prop === 'subscript') {
                startSpan.style.verticalAlign = run.superscript ? 'super' : (run.subscript ? 'sub' : '');
                startSpan.style.fontSize = (run.superscript || run.subscript)
                  ? Math.max(Math.round((run.size || 18) * (parseFloat($('wa-pptx-slide-canvas').style.width) / this.data.slideWidthEmu) * 12700 * 0.75), 5) + 'px'
                  : Math.max(Math.round((run.size || 18) * (parseFloat($('wa-pptx-slide-canvas').style.width) / this.data.slideWidthEmu) * 12700), 6) + 'px';
              }
              if (prop === 'highlight') startSpan.style.backgroundColor = value || '';
              if (prop === 'align') {
                para.align = value.toUpperCase();
                if (startSpan.parentElement) startSpan.parentElement.style.textAlign = value;
              }
              if (prop === 'lineSpacing') {
                para.lineSpacing = value;
                if (startSpan.parentElement) startSpan.parentElement.style.lineHeight = value;
              }
            } else {
              // Partial selection — split into up to 3 sub-runs
              const newRuns = [];
              if (s > 0) newRuns.push({ ...run, text: text.slice(0, s) });
              const mid = { ...run, text: text.slice(s, e) };
              this._applyRunProp(mid, prop, value);
              newRuns.push(mid);
              if (e < text.length) newRuns.push({ ...run, text: text.slice(e) });
              para.runs.splice(ri, 1, ...newRuns);
              this._renderSlide(this._curIdx);
            }
            WA.scheduleAutoSave();
            return;
          }
        }
      }

      // ── Case 2: multi-span selection, focused span, or whole shape ──────────
      const selSpans = [];
      if (sel && !sel.isCollapsed && this._selShape) {
        this._selShape.querySelectorAll('.wa-pptx-run').forEach(s => {
          if (sel.containsNode(s, true)) selSpans.push(s);
        });
      }
      const spansToFormat = selSpans.length > 0
        ? selSpans
        : (this._activeSpan && this._activeSpan.classList.contains('wa-pptx-run'))
            ? [this._activeSpan]
            : (this._selShape ? Array.from(this._selShape.querySelectorAll('.wa-pptx-run')) : []);

      if (!spansToFormat.length) return;

      // For toggle props on multiple spans, determine direction from the first run
      let toggleVal = value;
      spansToFormat.forEach((active, idx) => {
        const shapeId = parseInt(active.dataset.shapeId);
        const pi      = parseInt(active.dataset.pi);
        const ri      = parseInt(active.dataset.ri);
        const shape   = (slide.shapes || []).find(s => s.id === shapeId);
        if (!shape) return;
        const run = shape.paragraphs[pi] && shape.paragraphs[pi].runs[ri];
        if (!run) return;

        // On the first run, fix the toggle direction and reuse for others
        if (idx === 0 && (prop === 'bold' || prop === 'italic' || prop === 'underline' || prop === 'strikethrough' || prop === 'superscript' || prop === 'subscript')) {
          toggleVal = !run[prop];
        }
        const fVal = (prop === 'bold' || prop === 'italic' || prop === 'underline' || prop === 'strikethrough' || prop === 'superscript' || prop === 'subscript') ? toggleVal : value;
        this._applyRunProp(run, prop, fVal);

        // Live DOM update (no full re-render needed)
        active.style.fontWeight     = run.bold      ? 'bold'      : '';
        active.style.fontStyle      = run.italic    ? 'italic'    : '';
        active.style.textDecoration = _runTextDecoration(run);
        if (prop === 'size') {
          const scaleW = parseFloat($('wa-pptx-slide-canvas').style.width) / this.data.slideWidthEmu;
          active.style.fontSize = Math.max(Math.round(run.size * scaleW * 12700), 6) + 'px';
        }
        if (prop === 'fontName') active.style.fontFamily = value;
        if (prop === 'color')    active.style.color = value;
        if (prop === 'superscript' || prop === 'subscript') {
          active.style.verticalAlign = run.superscript ? 'super' : (run.subscript ? 'sub' : '');
          const scaleW = parseFloat($('wa-pptx-slide-canvas').style.width) / this.data.slideWidthEmu;
          active.style.fontSize = (run.superscript || run.subscript)
            ? Math.max(Math.round((run.size || 18) * scaleW * 12700 * 0.75), 5) + 'px'
            : Math.max(Math.round((run.size || 18) * scaleW * 12700), 6) + 'px';
        }
        if (prop === 'highlight') active.style.backgroundColor = fVal || '';
        // Paragraph-level props
        if (prop === 'align') {
          shape.paragraphs[pi].align = fVal.toUpperCase();
          if (active.parentElement) active.parentElement.style.textAlign = fVal;
        }
        if (prop === 'lineSpacing') {
          shape.paragraphs[pi].lineSpacing = fVal;
          if (active.parentElement) active.parentElement.style.lineHeight = fVal;
        }
        if (prop === 'bullet') {
          const para = shape.paragraphs[pi];
          para.bullet = fVal;
          if (fVal) para.numbered = false;
          const pEl = active.parentElement;
          if (pEl) { pEl.style.paddingLeft = fVal ? '1.5em' : ''; pEl.dataset.bullet = fVal ? (typeof fVal === 'string' ? fVal : '•') : ''; }
        }
        if (prop === 'numbered') {
          const para = shape.paragraphs[pi];
          para.numbered = fVal;
          if (fVal) para.bullet = false;
          const pEl = active.parentElement;
          if (pEl) pEl.dataset.numbered = fVal ? '1' : '';
        }
        if (prop === 'indent') {
          const para = shape.paragraphs[pi];
          para.indent = Math.max(0, (para.indent || 0) + (fVal || 0));
          const pEl = active.parentElement;
          if (pEl) pEl.style.paddingLeft = (para.indent * 20) + 'px';
        }
        // Shape-level vertical-align (textAnchor)
        if (prop === 'verticalAlign') {
          const shapeEl = this._selShape;
          if (shapeEl) {
            shape.textAnchor = fVal;
            const inner = shapeEl.querySelector('.wa-pptx-inner');
            if (inner) {
              const jcMap = { t: 'flex-start', ctr: 'center', b: 'flex-end' };
              inner.style.justifyContent = jcMap[fVal] || 'flex-start';
            }
          }
        }
      });
      // Sync toolbar state for the first formatted span
      const firstRun = (() => {
        if (!spansToFormat[0]) return null;
        const sp = spansToFormat[0];
        const shape = (slide.shapes || []).find(s => s.id === parseInt(sp.dataset.shapeId));
        const pi = parseInt(sp.dataset.pi), ri = parseInt(sp.dataset.ri);
        return shape && shape.paragraphs[pi] && shape.paragraphs[pi].runs[ri];
      })();
      if (firstRun) {
        if ($('wa-pptx-bold'))      $('wa-pptx-bold').classList.toggle('active',      !!firstRun.bold);
        if ($('wa-pptx-italic'))    $('wa-pptx-italic').classList.toggle('active',    !!firstRun.italic);
        if ($('wa-pptx-underline')) $('wa-pptx-underline').classList.toggle('active', !!firstRun.underline);
        if ($('wa-pptx-strike'))    $('wa-pptx-strike').classList.toggle('active',    !!firstRun.strikethrough);
        if ($('wa-pptx-super'))     $('wa-pptx-super').classList.toggle('active',     !!firstRun.superscript);
        if ($('wa-pptx-sub'))       $('wa-pptx-sub').classList.toggle('active',       !!firstRun.subscript);
        const _hs = $('wa-pptx-highlight-swatch');
        if (_hs) _hs.style.background = firstRun.highlight || 'transparent';
      }
      WA.scheduleAutoSave();
    }
}
