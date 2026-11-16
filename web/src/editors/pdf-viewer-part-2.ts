// @ts-nocheck
import {
  getActivePdfEditor as _pdfActiveEditor,
  getPdfDocument as _pdfDocumentForEditor,
  getPdfSessionSnapshot as _pdfState,
} from './pdf-session-runtime';
import { downloadPdfBlob as _downloadPdfBlob } from './pdf-download';
import { getFeatureRegistry } from '../shared/feature-registry';
import {
  getElementLogicalSize,
  viewportPointToElement,
  viewportRectToElement,
} from '../shared/ui-scale';

const workspaceApi = getFeatureRegistry();
const $ = (id: string): any => document.getElementById(id);
const showToast = (...args: any[]): void => workspaceApi.showToast?.(...args);
const _csrfFetch = (url: string, opts?: RequestInit): Promise<Response> => workspaceApi._csrfFetch(url, opts);
const _updatePdfZoomUI = (pct: number): void => workspaceApi._updatePdfZoomUI?.(pct);
const _hideWelcome = (): void => workspaceApi._hideWelcome?.();
const _setStreamBtn = (loading: boolean): void => workspaceApi._setStreamBtn?.(loading);
const _initWorkspaceAiRuntimes = (): void => workspaceApi._initWorkspaceAiRuntimes?.();

function _pdfRuntime(): any {
  return (window as any).pdfjsLib;
}

function _positionSelectionToolbar(): void {
  if (typeof workspaceApi._positionSelectionToolbar === 'function') {
    workspaceApi._positionSelectionToolbar();
  }
}

function _expandWAPanel(): void {
  if (typeof workspaceApi._expandWAPanel === 'function') workspaceApi._expandWAPanel();
}

import { KotoPdfViewerPart1 } from './pdf-viewer-part-1';

export class KotoPdfViewerPart2 extends KotoPdfViewerPart1 {

    async searchInput(query) {
      this._searchQuery = query;
      this._searchPgs = [];
      this._searchIdx = -1;
      this._clearSearchHighlights();

      if (!query || query.length < 1) {
        const cnt = $('wa-pdf-search-count');
        if (cnt) cnt.textContent = '';
        return;
      }

      // Search all pages that have text content
      const pdf = this._pdfDoc;
      if (!pdf) return;

      const lq = query.toLowerCase();
      let totalMatches = 0;

      for (let pg = 1; pg <= pdf.numPages; pg++) {
        // Ensure we have text for this page
        if (!this._textContent[pg]) {
          try {
            const page = await pdf.getPage(pg);
            const tc = await page.getTextContent();
            this._textContent[pg] = tc.items.map(it => it.str).join(' ');
          } catch (_) { continue; }
        }

        const text = this._textContent[pg] || '';
        let idx = 0;
        while ((idx = text.toLowerCase().indexOf(lq, idx)) !== -1) {
          this._searchPgs.push({ page: pg, charIdx: idx, charLen: lq.length });
          idx++;
          totalMatches++;
        }
      }

      const cnt = $('wa-pdf-search-count');
      if (cnt) cnt.textContent = totalMatches > 0 ? `${totalMatches} 处` : '未找到';

      if (totalMatches > 0) {
        this._searchIdx = 0;
        this._renderAllSearchHighlights();
        this._scrollToMatch(this._searchIdx);
      }
    }

    searchKeydown(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        if (e.shiftKey) this.searchPrev();
        else this.searchNext();
      } else if (e.key === 'Escape') {
        this.searchClose();
      }
    }

    searchNext() {
      if (this._searchPgs.length === 0) return;
      this._searchIdx = (this._searchIdx + 1) % this._searchPgs.length;
      this._updateSearchCounter();
      this._scrollToMatch(this._searchIdx);
      this._renderAllSearchHighlights();
    }

    searchPrev() {
      if (this._searchPgs.length === 0) return;
      this._searchIdx = (this._searchIdx - 1 + this._searchPgs.length) % this._searchPgs.length;
      this._updateSearchCounter();
      this._scrollToMatch(this._searchIdx);
      this._renderAllSearchHighlights();
    }

    _updateSearchCounter() {
      const cnt = $('wa-pdf-search-count');
      if (cnt) cnt.textContent = `${this._searchIdx + 1} / ${this._searchPgs.length}`;
    }

    _scrollToMatch(idx) {
      if (idx < 0 || idx >= this._searchPgs.length) return;
      const match = this._searchPgs[idx];
      this._scrollToPage(match.page);
    }

    _renderAllSearchHighlights() {
      const c = $(this.containerId);
      if (!c) return;
      // Clear current highlights
      c.querySelectorAll('.wa-pdf-search-hl').forEach(el => el.remove());
      // Can only do text-position-based highlighting if text layer is active
      // We use a character-position based approach: find all <span> elements
      // in the text layer that contain the query string characters
      this._searchPgs.forEach((match, i) => {
        this._renderSearchOnPage(match.page, match.charIdx, match.charLen, i === this._searchIdx);
      });
    }

    _renderSearchOnPage(pageNum, charIdx, charLen, isCurrent) {
      const wrap = document.getElementById(`pdf-page-${pageNum}`);
      if (!wrap) return;
      const textLayer = wrap.querySelector('.wa-pdf-text-layer');
      if (!textLayer) return;

      // Use range-based highlight: walk text layer spans
      const spans = Array.from(textLayer.querySelectorAll('span'));
      if (!spans.length) return;

      // Build running char offset → span mapping
      let running = 0, startSpan = null, startOff = 0, endSpan = null, endOff = 0;
      for (let i = 0; i < spans.length; i++) {
        const len = spans[i].textContent.length;
        if (startSpan === null && running + len > charIdx) {
          startSpan = spans[i];
          startOff = charIdx - running;
        }
        if (endSpan === null && running + len >= charIdx + charLen) {
          endSpan = spans[i];
          endOff = (charIdx + charLen) - running;
          break;
        }
        running += len;
      }
      if (!startSpan || !endSpan) return;

      try {
        const range = document.createRange();
        range.setStart(startSpan.firstChild || startSpan, Math.min(startOff, (startSpan.firstChild || startSpan).length));
        range.setEnd(endSpan.firstChild || endSpan, Math.min(endOff, (endSpan.firstChild || endSpan).length));
        const rects = Array.from(range.getClientRects());
        const svg = wrap.querySelector('.wa-pdf-annot-layer');
        if (!svg) return;

        rects.forEach(r => {
          const localRect = viewportRectToElement(wrap, r);
          const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
          rect.setAttribute('x',      localRect.x);
          rect.setAttribute('y',      localRect.y);
          rect.setAttribute('width',  localRect.width);
          rect.setAttribute('height', localRect.height);
          rect.classList.add('wa-pdf-search-hl');
          if (isCurrent) rect.classList.add('current');
          svg.appendChild(rect);
        });
      } catch (e) { console.warn("[Koto]", e) }
    }

    _clearSearchHighlights() {
      const c = $(this.containerId);
      if (c) c.querySelectorAll('.wa-pdf-search-hl').forEach(el => el.remove());
    }

    // ─── Annotation toolbar open/close ───────────────────────────────────────
    annotOpen() {
      const bar = $('wa-pdf-annot-bar');
      if (bar) bar.style.display = 'flex';
      const aiPanel = document.getElementById('wa-ai');
      const toggleAiPanel = workspaceApi.toggleAiPanel;
      if (
        document.body.classList.contains('koto-layout-compact')
        && aiPanel
        && !aiPanel.classList.contains('wa-ai-collapsed')
        && window.getComputedStyle(aiPanel).display !== 'none'
        && typeof toggleAiPanel === 'function'
      ) {
        // In compact mode the AI panel overlays the right side of the PDF
        // toolbar. Give annotation tools the whole canvas while they are open,
        // then restore the user's panel state on close.
        toggleAiPanel();
        this._restoreAiPanelAfterAnnot = true;
      }
      // Show annotation buttons in floating toolbar when PDF is open
      const annotBtns = document.querySelectorAll('.wa-pdf-annot-btn, .wa-pdf-annot-sep');
      annotBtns.forEach((el: HTMLElement) => {
        el.classList.remove('wa-hidden');
        el.style.display = '';
      });
    }

    annotClose() {
      const bar = $('wa-pdf-annot-bar');
      if (bar) bar.style.display = 'none';
      this._annotMode = null;
      document.querySelectorAll('.wa-pdf-abt').forEach(b => b.classList.remove('active'));
      // Restore default cursor
      const c = $(this.containerId);
      if (c) c.style.cursor = '';
      const aiPanel = document.getElementById('wa-ai');
      if (
        this._restoreAiPanelAfterAnnot
        && aiPanel?.classList.contains('wa-ai-collapsed')
        && typeof workspaceApi.toggleAiPanel === 'function'
      ) workspaceApi.toggleAiPanel();
      this._restoreAiPanelAfterAnnot = false;
    }

    setAnnotMode(mode) {
      if (this._annotMode === mode) {
        // Toggle off
        this._annotMode = null;
        document.querySelectorAll('.wa-pdf-abt').forEach(b => b.classList.remove('active'));
        const c = $(this.containerId);
        if (c) c.style.cursor = '';
        return;
      }
      this._annotMode = mode;
      document.querySelectorAll('.wa-pdf-abt').forEach(b => b.classList.remove('active'));
      const activeBtn = document.getElementById(`wa-pdf-abt-${mode}`);
      if (activeBtn) activeBtn.classList.add('active');
      const c = $(this.containerId);
      if (c) {
        const shapeModes = ['draw', 'rect', 'ellipse', 'line', 'arrow'];
        c.style.cursor = shapeModes.includes(mode) ? 'crosshair' :
          mode === 'eraser' ? 'cell' :
          mode === 'textbox' ? 'text' :
          mode === 'note' ? 'cell' : 'text';
      }
    }

    setAnnotColor(hex) {
      this._annotColor = hex;
      const circle = document.getElementById('wa-pdf-annot-color-circle');
      if (circle) circle.setAttribute('fill', hex);
    }

    // ─── Text annotation (highlight / underline / strikethrough) ─────────────
    _onMouseUp(_e) {
      const mode = this._annotMode;
      if (mode === 'highlight' || mode === 'underline' || mode === 'strikethrough') {
        const sel = window.getSelection();
        if (sel && sel.toString().trim().length > 0) {
          this._createTextAnnotation(mode);
          return;
        }
      }

      // Default: selection toolbar (AI actions)
      const sel = window.getSelection();
      const txt = sel ? sel.toString().trim() : '';
      if (txt) {
        _positionSelectionToolbar();
      }
    }

    _onMouseDown(e) {
      const wrap = e.target.closest('.wa-pdf-page-wrap');
      if (this._annotMode === 'draw') {
        if (wrap) {
          const pageNum = parseInt(wrap.dataset.page, 10);
          const svg = wrap.querySelector('.wa-pdf-annot-layer');
          if (svg) this._startDraw(e, svg, pageNum);
        }
      } else if (['rect', 'ellipse', 'line', 'arrow'].includes(this._annotMode)) {
        if (wrap) {
          const pageNum = parseInt(wrap.dataset.page, 10);
          const svg = wrap.querySelector('.wa-pdf-annot-layer');
          if (svg) this._startShape(e, svg, pageNum);
        }
      } else if (this._annotMode === 'textbox') {
        if (wrap) {
          const pageNum = parseInt(wrap.dataset.page, 10);
          this._startTextbox(e, wrap, pageNum);
        }
      } else if (this._annotMode === 'eraser') {
        if (wrap) this._handleEraser(e, wrap);
      }
    }

    _onMouseMove(e) {
      if (this._shapePreview && this._shapeStart && ['rect', 'ellipse', 'line', 'arrow'].includes(this._annotMode)) {
        this._moveShape(e);
      } else if (this._drawPath && this._annotMode === 'draw') {
        const wrap = this._drawingWrap;
        if (!wrap) return;
        const { x, y } = viewportPointToElement(wrap, e.clientX, e.clientY);
        this._drawPoints.push({ x, y });
        const d = this._drawPoints.map((p, i) => (i === 0 ? `M${p.x},${p.y}` : `L${p.x},${p.y}`)).join(' ');
        this._drawPath.setAttribute('d', d);
      }
    }

    _createTextAnnotation(type) {
      const sel = window.getSelection();
      if (!sel || sel.rangeCount === 0) return;
      const range = sel.getRangeAt(0);
      if (range.collapsed) return;

      // Find which page this selection is in
      const startElement = range.startContainer.nodeType === Node.TEXT_NODE
        ? range.startContainer.parentElement
        : range.startContainer;
      const wrap = startElement?.closest?.('.wa-pdf-page-wrap');
      if (!wrap) return;
      const endElement = range.endContainer.nodeType === Node.TEXT_NODE
        ? range.endContainer.parentElement
        : range.endContainer;
      const endWrap = endElement?.closest?.('.wa-pdf-page-wrap');
      if (endWrap && endWrap !== wrap) {
        showToast('请在同一 PDF 页面内选择要批注的文本', 'warning');
        return;
      }
      const pageNum = parseInt(wrap.dataset.page, 10);
      if (!pageNum) return;

      const rects = Array.from(range.getClientRects());
      const pageSize = getElementLogicalSize(wrap);
      const pageRects = rects.map(r => {
        const local = viewportRectToElement(wrap, r);
        return { x: local.x, y: local.y, w: local.width, h: local.height };
      });

      const annot = {
        id:    Date.now() + '-' + Math.random().toString(36).slice(2),
        type,
        page:  pageNum,
        pageWidth: pageSize.width,
        pageHeight: pageSize.height,
        rects: pageRects,
        color: this._annotColor,
        text:  sel.toString().trim(),
        timestamp: Date.now(),
      };
      this._annotations.push(annot);
      this._renderAnnotationsOnPage(pageNum);
      sel.removeAllRanges();
    }

    // ─── Note / sticky annotation ─────────────────────────────────────────────
    _placeNote(e, wrap, pageNum) {
      e.preventDefault();
      const { x, y } = viewportPointToElement(wrap, e.clientX, e.clientY);
      const pageSize = getElementLogicalSize(wrap);

      const annot = {
        id:    Date.now() + '-' + Math.random().toString(36).slice(2),
        type:  'note',
        page:  pageNum,
        x, y,
        pageWidth: pageSize.width,
        pageHeight: pageSize.height,
        text:  '',
        color: this._annotColor,
        timestamp: Date.now(),
      };
      this._annotations.push(annot);
      this._renderAnnotationsOnPage(pageNum);
      // Open the note popup immediately
      const popup = wrap.querySelector(`.wa-pdf-note-popup[data-id="${annot.id}"]`);
      if (popup) popup.querySelector('textarea').focus();
    }

    // ─── Freehand drawing ─────────────────────────────────────────────────────
    _startDraw(e, svg, pageNum) {
      e.preventDefault();
      const { x, y } = viewportPointToElement(svg, e.clientX, e.clientY);
      const pageSize = getElementLogicalSize(svg.closest('.wa-pdf-page-wrap'));

      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.classList.add('wa-annot-draw');
      path.setAttribute('stroke', this._annotColor);
      path.setAttribute('stroke-width', String(this._annotLineWidth));
      path.setAttribute('stroke-linecap', 'round');
      path.setAttribute('stroke-linejoin', 'round');
      path.setAttribute('d', `M${x},${y}`);
      svg.appendChild(path);

      this._drawPath   = path;
      this._drawPoints = [{ x, y }];
      this._drawingWrap = svg.closest('.wa-pdf-page-wrap');
      this._drawPageNum = pageNum;
      this._drawPageWidth = pageSize.width;
      this._drawPageHeight = pageSize.height;

      const endDraw = () => {
        if (!this._drawPath) return;
        if (this._drawPoints.length > 1) {
          const annot = {
            id:        Date.now() + '-' + Math.random().toString(36).slice(2),
            type:      'draw',
            page:      this._drawPageNum,
            pageWidth: this._drawPageWidth,
            pageHeight: this._drawPageHeight,
            points:    this._drawPoints,
            color:     this._annotColor,
            lineWidth: this._annotLineWidth,
            timestamp: Date.now(),
          };
          this._annotations.push(annot);
        } else {
          // Single click — discard
          this._drawPath.remove();
        }
        this._drawPath   = null;
        this._drawPoints = [];
        this._drawingWrap = null;
        this._drawPageWidth = 0;
        this._drawPageHeight = 0;
        document.removeEventListener('mouseup', endDraw);
      };
      document.addEventListener('mouseup', endDraw, { once: true });
    }

    // ─── Shape drawing (rect / ellipse / line / arrow) ─────────────────────────────
    _startShape(e, svg, pageNum) {
      e.preventDefault();
      const { x, y } = viewportPointToElement(svg, e.clientX, e.clientY);
      const pageSize = getElementLogicalSize(svg.closest('.wa-pdf-page-wrap'));
      this._shapeStart   = { x, y };
      this._shapeSvg     = svg;
      this._shapePageNum = pageNum;
      this._shapePageWidth = pageSize.width;
      this._shapePageHeight = pageSize.height;
      const mode = this._annotMode;
      const ns = 'http://www.w3.org/2000/svg';
      let el;
      if (mode === 'rect') {
        el = document.createElementNS(ns, 'rect');
        el.setAttribute('fill', 'none');
        el.setAttribute('x', x); el.setAttribute('y', y);
        el.setAttribute('width', '1'); el.setAttribute('height', '1');
      } else if (mode === 'ellipse') {
        el = document.createElementNS(ns, 'ellipse');
        el.setAttribute('fill', 'none');
        el.setAttribute('cx', x); el.setAttribute('cy', y);
        el.setAttribute('rx', '1'); el.setAttribute('ry', '1');
      } else if (mode === 'line' || mode === 'arrow') {
        el = document.createElementNS(ns, 'line');
        el.setAttribute('x1', x); el.setAttribute('y1', y);
        el.setAttribute('x2', x); el.setAttribute('y2', y);
      }
      if (el) {
        el.setAttribute('stroke', this._annotColor);
        el.setAttribute('stroke-width', this._annotLineWidth);
        el.classList.add('wa-annot-preview');
        svg.appendChild(el);
        this._shapePreview = el;
      }
      document.addEventListener('mouseup', () => this._finishShape(), { once: true });
    }

    _moveShape(e) {
      if (!this._shapePreview || !this._shapeStart || !this._shapeSvg) return;
      const { x: x2, y: y2 } = viewportPointToElement(this._shapeSvg, e.clientX, e.clientY);
      const { x: x1, y: y1 } = this._shapeStart;
      const mode = this._annotMode;
      if (mode === 'rect') {
        this._shapePreview.setAttribute('x', Math.min(x1, x2));
        this._shapePreview.setAttribute('y', Math.min(y1, y2));
        this._shapePreview.setAttribute('width',  Math.abs(x2 - x1));
        this._shapePreview.setAttribute('height', Math.abs(y2 - y1));
      } else if (mode === 'ellipse') {
        this._shapePreview.setAttribute('cx', (x1 + x2) / 2);
        this._shapePreview.setAttribute('cy', (y1 + y2) / 2);
        this._shapePreview.setAttribute('rx', Math.abs(x2 - x1) / 2);
        this._shapePreview.setAttribute('ry', Math.abs(y2 - y1) / 2);
      } else if (mode === 'line' || mode === 'arrow') {
        this._shapePreview.setAttribute('x2', x2);
        this._shapePreview.setAttribute('y2', y2);
      }
    }

    _finishShape() {
      if (!this._shapePreview || !this._shapeStart) return;
      const mode = this._annotMode;
      let annot = null;
      if (mode === 'rect') {
        const x = parseFloat(this._shapePreview.getAttribute('x'));
        const y = parseFloat(this._shapePreview.getAttribute('y'));
        const w = parseFloat(this._shapePreview.getAttribute('width'));
        const h = parseFloat(this._shapePreview.getAttribute('height'));
        if (w >= 5 && h >= 5) annot = { type: 'rect', x, y, w, h };
      } else if (mode === 'ellipse') {
        const cx = parseFloat(this._shapePreview.getAttribute('cx'));
        const cy = parseFloat(this._shapePreview.getAttribute('cy'));
        const rx = parseFloat(this._shapePreview.getAttribute('rx'));
        const ry = parseFloat(this._shapePreview.getAttribute('ry'));
        if (rx >= 3 && ry >= 3) annot = { type: 'ellipse', cx, cy, rx, ry };
      } else if (mode === 'line' || mode === 'arrow') {
        const x1 = parseFloat(this._shapePreview.getAttribute('x1'));
        const y1 = parseFloat(this._shapePreview.getAttribute('y1'));
        const x2 = parseFloat(this._shapePreview.getAttribute('x2'));
        const y2 = parseFloat(this._shapePreview.getAttribute('y2'));
        const len = Math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2);
        if (len >= 5) annot = { type: mode, x1, y1, x2, y2 };
      }
      this._shapePreview.remove();
      this._shapePreview = null;
      this._shapeStart   = null;
      if (annot) {
        const full = {
          ...annot,
          id:        Date.now() + '-' + Math.random().toString(36).slice(2),
          page:      this._shapePageNum,
          pageWidth: this._shapePageWidth,
          pageHeight: this._shapePageHeight,
          color:     this._annotColor,
          lineWidth: this._annotLineWidth,
          timestamp: Date.now(),
        };
        this._annotations.push(full);
        this._renderAnnotationsOnPage(full.page);
      }
      this._shapePageWidth = 0;
      this._shapePageHeight = 0;
    }

    _annotationForViewport(annotation, viewportWidth, viewportHeight) {
      const sourceWidth = Number(annotation?.pageWidth || viewportWidth) || viewportWidth;
      const sourceHeight = Number(annotation?.pageHeight || viewportHeight) || viewportHeight;
      const sx = sourceWidth > 0 ? viewportWidth / sourceWidth : 1;
      const sy = sourceHeight > 0 ? viewportHeight / sourceHeight : 1;
      if (Math.abs(sx - 1) < 0.0001 && Math.abs(sy - 1) < 0.0001) return annotation;
      const scaled = { ...annotation, _source: annotation };
      const scaleRect = rect => ({
        ...rect,
        x: Number(rect.x || 0) * sx,
        y: Number(rect.y || 0) * sy,
        w: Number(rect.w ?? rect.width ?? 0) * sx,
        h: Number(rect.h ?? rect.height ?? 0) * sy,
      });
      if (Array.isArray(annotation.rects)) scaled.rects = annotation.rects.map(scaleRect);
      if (Array.isArray(annotation.points)) {
        scaled.points = annotation.points.map(point => ({ x: point.x * sx, y: point.y * sy }));
      }
      ['x', 'w', 'cx', 'rx', 'x1', 'x2'].forEach(key => {
        if (Number.isFinite(Number(annotation[key]))) scaled[key] = Number(annotation[key]) * sx;
      });
      ['y', 'h', 'cy', 'ry', 'y1', 'y2'].forEach(key => {
        if (Number.isFinite(Number(annotation[key]))) scaled[key] = Number(annotation[key]) * sy;
      });
      const strokeScale = (sx + sy) / 2;
      if (Number.isFinite(Number(annotation.lineWidth))) scaled.lineWidth = Number(annotation.lineWidth) * strokeScale;
      if (Number.isFinite(Number(annotation.fontSize))) scaled.fontSize = Number(annotation.fontSize) * sy;
      return scaled;
    }

    // ─── Eraser ──────────────────────────────────────────────────────────────
    _handleEraser(e, wrap) {
      const pageNum = parseInt(wrap.dataset.page, 10);
      const { x: ex, y: ey } = viewportPointToElement(wrap, e.clientX, e.clientY);
      const pageSize = getElementLogicalSize(wrap);
      const HIT = 14;
      const hit = this._annotations
        .map(annotation => this._annotationForViewport(annotation, pageSize.width, pageSize.height))
        .find(a => {
        if (a.page !== pageNum) return false;
        if (a.type === 'rect')    return ex >= a.x - HIT && ex <= a.x + a.w + HIT && ey >= a.y - HIT && ey <= a.y + a.h + HIT;
        if (a.type === 'ellipse') return Math.abs(ex - a.cx) <= a.rx + HIT && Math.abs(ey - a.cy) <= a.ry + HIT;
        if (a.type === 'line' || a.type === 'arrow') {
          const dx = a.x2 - a.x1, dy = a.y2 - a.y1, len2 = dx * dx + dy * dy;
          const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((ex - a.x1) * dx + (ey - a.y1) * dy) / len2));
          return Math.sqrt((ex - (a.x1 + t * dx)) ** 2 + (ey - (a.y1 + t * dy)) ** 2) <= HIT;
        }
        if (a.type === 'note')    return Math.sqrt((ex - a.x) ** 2 + (ey - a.y) ** 2) <= HIT + 10;
        if (a.type === 'textbox') return ex >= a.x - HIT && ex <= a.x + a.w + HIT && ey >= a.y - HIT && ey <= a.y + a.h + HIT;
        if (a.type === 'draw')    return a.points && a.points.some(p => Math.sqrt((ex - p.x) ** 2 + (ey - p.y) ** 2) <= HIT);
        if (a.rects)              return a.rects.some(r => ex >= r.x - 2 && ex <= r.x + r.w + 2 && ey >= r.y - 2 && ey <= r.y + r.h + 2);
        return false;
      });
      if (hit) {
        this._deleteAnnotation(hit.id);
        showToast('批注已删除', 'info');
      }
    }

    // ─── Text-box annotation ──────────────────────────────────────────────────
    _startTextbox(e, wrap, pageNum) {
      e.preventDefault();
      const { x, y } = viewportPointToElement(wrap, e.clientX, e.clientY);
      const pageSize = getElementLogicalSize(wrap);
      const box = document.createElement('div');
      box.contentEditable = 'true';
      box.className = 'wa-pdf-textbox-edit';
      box.style.cssText = `position:absolute;left:${x}px;top:${y}px;min-width:80px;min-height:22px;
        border:1.5px dashed ${this._annotColor};color:${this._annotColor};font-size:14px;
        background:rgba(255,255,255,.06);outline:none;padding:2px 4px;cursor:text;z-index:100;`;
      wrap.appendChild(box);
      box.focus();
      let committed = false;
      const commit = () => {
        if (committed) return;
        committed = true;
        const text = box.innerText.trim();
        const width = Math.max(80, box.offsetWidth);
        const height = Math.max(22, box.offsetHeight);
        box.remove();
        if (!text) return;
        const annot = {
          id:        Date.now() + '-' + Math.random().toString(36).slice(2),
          type:      'textbox',
          page:      pageNum,
          pageWidth: pageSize.width,
          pageHeight: pageSize.height,
          x, y,
          w:         width,
          h:         height,
          text,
          fontSize:  14,
          color:     this._annotColor,
          timestamp: Date.now(),
        };
        this._annotations.push(annot);
        this._renderAnnotationsOnPage(pageNum);
      };
      box.addEventListener('blur', commit);
      box.addEventListener('keydown', ke => {
        if (ke.key === 'Escape') { ke.preventDefault(); committed = true; box.remove(); }
        else if (ke.key === 'Enter' && !ke.shiftKey) { ke.preventDefault(); commit(); }
      });
    }
}
