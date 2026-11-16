// @ts-nocheck
import { getFeatureRegistry } from '../shared/feature-registry';

const WA = getFeatureRegistry();
const $ = (id: string): HTMLElement | null => document.getElementById(id);
const showToast = (...args: any[]): void => WA.showToast?.(...args);
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

import { KotoPptxEditorPart3 } from './pptx-editor-part-3';

export class KotoPptxEditorPart4 extends KotoPptxEditorPart3 {

    setZoom(pct) {
      this._zoom = pct / 100;
      this._renderSlide(this._curIdx);
    }

    // ── Font size stepping (Ctrl+Shift+> / <) ────────────────────────────────

    _stepFontSize(dir) {
      const SIZES = [8,9,10,11,12,14,16,18,20,22,24,28,32,36,40,44,48,54,60,66,72,80,88,96];
      // Get current size from active span / savedRange
      const span = this._activeSpan;
      if (!span) return;
      const shapeId = parseInt(span.dataset.shapeId);
      const pi = parseInt(span.dataset.pi), ri = parseInt(span.dataset.ri);
      const slide = this.data.slides[this._curIdx];
      const shape = slide && (slide.shapes || []).find(s => s.id === shapeId);
      const run = shape && shape.paragraphs[pi] && shape.paragraphs[pi].runs[ri];
      if (!run) return;
      const curSize = Math.round(run.size || 18);
      let idx = SIZES.findIndex(s => s >= curSize);
      if (idx === -1) idx = SIZES.length - 1;
      const newIdx = Math.max(0, Math.min(SIZES.length - 1, idx + dir));
      this.applyFormat('size', SIZES[newIdx]);
      // Update toolbar font size display
      if ($('wa-pptx-fontsize')) $('wa-pptx-fontsize').value = SIZES[newIdx];
    }

    // ── Duplicate current slide ──────────────────────────────────────────────

    _duplicateSlide() {
      if (!this.data || !this.data.slides.length) return;
      this._pushUndo();
      const src = this.data.slides[this._curIdx];
      const copy = JSON.parse(JSON.stringify(src));
      // Assign new unique IDs to all shapes
      copy.shapes.forEach(s => { s.id = -(Date.now() % 100000000) - Math.floor(Math.random() * 10000); });
      const insertIdx = this._curIdx + 1;
      this.data.slides.splice(insertIdx, 0, copy);
      this.data.slides.forEach((s, i) => { s.index = i; });
      this._buildThumbs();
      this._renderSlide(insertIdx);
      WA.scheduleAutoSave();
      showToast('已复制幻灯片', 'info');
    }

    // ── Z-order: bring to front / send to back ──────────────────────────────

    _bringToFront(shapeId) {
      this._pushUndo();
      const slide = this.data.slides[this._curIdx];
      const shape = (slide.shapes || []).find(s => s.id === shapeId);
      if (!shape) return;
      shape.z_order = (slide.shapes.reduce((m, s) => Math.max(m, s.z_order), 0)) + 1;
      this._renderSlide(this._curIdx);
      WA.scheduleAutoSave();
    }

    _sendToBack(shapeId) {
      this._pushUndo();
      const slide = this.data.slides[this._curIdx];
      const shape = (slide.shapes || []).find(s => s.id === shapeId);
      if (!shape) return;
      const minZ = slide.shapes.reduce((m, s) => Math.min(m, s.z_order), Infinity);
      shape.z_order = Math.max(0, minZ - 1);
      this._renderSlide(this._curIdx);
      WA.scheduleAutoSave();
    }

    // ── Undo / Redo ──────────────────────────────────────────────────────────

    /** Snapshot current data + slideIdx onto the undo stack before any mutations. */
    _pushUndo() {
      this._undoStack.push({ slideIdx: this._curIdx, data: JSON.parse(JSON.stringify(this.data)) });
      if (this._undoStack.length > 50) this._undoStack.shift();
      this._redoStack = [];
      this._updateUndoRedoUI();
    }

    _undo() {
      if (!this._undoStack.length) return;
      this._redoStack.push({ slideIdx: this._curIdx, data: JSON.parse(JSON.stringify(this.data)) });
      const snap = this._undoStack.pop();
      this.data = snap.data;
      this._selShape = null;
      this._activeSpan = null;
      this._editMode = false;
      this._buildThumbs();
      this._renderSlide(Math.min(snap.slideIdx, this.data.slides.length - 1));
      this._updateUndoRedoUI();
      WA.scheduleAutoSave();
    }

    _redo() {
      if (!this._redoStack.length) return;
      this._undoStack.push({ slideIdx: this._curIdx, data: JSON.parse(JSON.stringify(this.data)) });
      const snap = this._redoStack.pop();
      this.data = snap.data;
      this._selShape = null;
      this._activeSpan = null;
      this._editMode = false;
      this._buildThumbs();
      this._renderSlide(Math.min(snap.slideIdx, this.data.slides.length - 1));
      this._updateUndoRedoUI();
      WA.scheduleAutoSave();
    }

    _updateUndoRedoUI() {
      const u = $('wa-pptx-undo');
      const r = $('wa-pptx-redo');
      if (u) u.disabled = !this._undoStack.length;
      if (r) r.disabled = !this._redoStack.length;
    }
}
