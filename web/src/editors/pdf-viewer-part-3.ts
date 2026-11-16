// @ts-nocheck
import { dragPdfNote as _pdfDragNote } from './pdf-note-drag';
import {
  getActivePdfEditor as _pdfActiveEditor,
  getPdfDocument as _pdfDocumentForEditor,
  getPdfSessionSnapshot as _pdfState,
} from './pdf-session-runtime';
import { downloadPdfBlob as _downloadPdfBlob } from './pdf-download';
import { getFeatureRegistry } from '../shared/feature-registry';
import {
  appendToUiPortal,
  getElementLogicalSize,
  placeFixedInViewport,
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
const getWorkspaceConversationRuntime = (): any => workspaceApi.getWorkspaceConversationRuntime?.();
const getWorkspaceTaskDispatcher = (): any => workspaceApi.getWorkspaceTaskDispatcher?.();

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

import { KotoPdfViewerPart2 } from './pdf-viewer-part-2';

export class KotoPdfViewerPart3 extends KotoPdfViewerPart2 {

    // ─── Render annotations on a page ────────────────────────────────────────
    _renderAnnotationsOnPage(pageNum) {
      const wrap = document.getElementById(`pdf-page-${pageNum}`);
      if (!wrap) return;
      const svg = wrap.querySelector('.wa-pdf-annot-layer');
      if (!svg) return;

      // Clear existing annotation elements (keep search highlights)
      svg.querySelectorAll('.wa-annot-hi, .wa-annot-ul, .wa-annot-st, .wa-annot-draw-saved, .wa-annot-shape, .wa-pdf-note-icon').forEach(el => el.remove());
      wrap.querySelectorAll('.wa-pdf-note-popup').forEach(el => el.remove());

      const viewportWidth = Number(svg.getAttribute('width') || svg.getBoundingClientRect().width || 0);
      const viewportHeight = Number(svg.getAttribute('height') || svg.getBoundingClientRect().height || 0);
      const pageAnnots = this._annotations
        .filter(a => a.page === pageNum)
        .map(annotation => this._annotationForViewport(annotation, viewportWidth, viewportHeight));
      pageAnnots.forEach(annot => {
        if (annot.type === 'highlight' || annot.type === 'underline' || annot.type === 'strikethrough') {
          annot.rects.forEach(r => {
            if (annot.type === 'highlight') {
              const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
              rect.setAttribute('x', r.x); rect.setAttribute('y', r.y);
              rect.setAttribute('width', r.w); rect.setAttribute('height', r.h);
              rect.setAttribute('fill', annot.color);
              rect.classList.add('wa-annot-hi');
              rect.dataset.annotId = annot.id;
              rect.addEventListener('contextmenu', (e) => { e.preventDefault(); this._showAnnotMenu(annot, e); });
              svg.appendChild(rect);
            } else if (annot.type === 'underline') {
              const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
              line.setAttribute('x1', r.x);      line.setAttribute('y1', r.y + r.h);
              line.setAttribute('x2', r.x + r.w); line.setAttribute('y2', r.y + r.h);
              line.setAttribute('stroke', annot.color); line.setAttribute('stroke-width', '1.5');
              line.classList.add('wa-annot-ul');
              line.dataset.annotId = annot.id;
              line.addEventListener('contextmenu', (e) => { e.preventDefault(); this._showAnnotMenu(annot, e); });
              svg.appendChild(line);
            } else if (annot.type === 'strikethrough') {
              const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
              const midY = r.y + r.h * 0.5;
              line.setAttribute('x1', r.x);      line.setAttribute('y1', midY);
              line.setAttribute('x2', r.x + r.w); line.setAttribute('y2', midY);
              line.setAttribute('stroke', annot.color); line.setAttribute('stroke-width', '1.5');
              line.classList.add('wa-annot-st');
              line.dataset.annotId = annot.id;
              line.addEventListener('contextmenu', (e) => { e.preventDefault(); this._showAnnotMenu(annot, e); });
              svg.appendChild(line);
            }
          });
        } else if (annot.type === 'draw') {
          const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
          const d = annot.points.map((p, i) => (i === 0 ? `M${p.x},${p.y}` : `L${p.x},${p.y}`)).join(' ');
          path.setAttribute('d', d);
          path.setAttribute('stroke', annot.color);
          path.setAttribute('stroke-width', String(annot.lineWidth || 2));
          path.setAttribute('stroke-linecap', 'round');
          path.setAttribute('stroke-linejoin', 'round');
          path.setAttribute('fill', 'none');
          path.classList.add('wa-annot-draw', 'wa-annot-draw-saved');
          path.dataset.annotId = annot.id;
          path.addEventListener('contextmenu', (e) => { e.preventDefault(); this._showAnnotMenu(annot, e); });
          svg.appendChild(path);
        } else if (annot.type === 'rect') {
          const el = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
          el.setAttribute('x', annot.x); el.setAttribute('y', annot.y);
          el.setAttribute('width', annot.w); el.setAttribute('height', annot.h);
          el.setAttribute('fill', 'none'); el.setAttribute('stroke', annot.color);
          el.setAttribute('stroke-width', annot.lineWidth || 2);
          el.classList.add('wa-annot-shape'); el.dataset.annotId = annot.id;
          el.addEventListener('contextmenu', (e) => { e.preventDefault(); this._showAnnotMenu(annot, e); });
          svg.appendChild(el);
        } else if (annot.type === 'ellipse') {
          const el = document.createElementNS('http://www.w3.org/2000/svg', 'ellipse');
          el.setAttribute('cx', annot.cx); el.setAttribute('cy', annot.cy);
          el.setAttribute('rx', annot.rx); el.setAttribute('ry', annot.ry);
          el.setAttribute('fill', 'none'); el.setAttribute('stroke', annot.color);
          el.setAttribute('stroke-width', annot.lineWidth || 2);
          el.classList.add('wa-annot-shape'); el.dataset.annotId = annot.id;
          el.addEventListener('contextmenu', (e) => { e.preventDefault(); this._showAnnotMenu(annot, e); });
          svg.appendChild(el);
        } else if (annot.type === 'line') {
          const el = document.createElementNS('http://www.w3.org/2000/svg', 'line');
          el.setAttribute('x1', annot.x1); el.setAttribute('y1', annot.y1);
          el.setAttribute('x2', annot.x2); el.setAttribute('y2', annot.y2);
          el.setAttribute('stroke', annot.color); el.setAttribute('stroke-width', annot.lineWidth || 2);
          el.classList.add('wa-annot-shape'); el.dataset.annotId = annot.id;
          el.addEventListener('contextmenu', (e) => { e.preventDefault(); this._showAnnotMenu(annot, e); });
          svg.appendChild(el);
        } else if (annot.type === 'arrow') {
          const ns = 'http://www.w3.org/2000/svg';
          const markerId = 'arrow-' + annot.id;
          let defs = svg.querySelector('defs');
          if (!defs) { defs = document.createElementNS(ns, 'defs'); svg.prepend(defs); }
          const marker = document.createElementNS(ns, 'marker');
          marker.setAttribute('id', markerId); marker.setAttribute('markerWidth', '10');
          marker.setAttribute('markerHeight', '7'); marker.setAttribute('refX', '9');
          marker.setAttribute('refY', '3.5'); marker.setAttribute('orient', 'auto');
          const poly = document.createElementNS(ns, 'polygon');
          poly.setAttribute('points', '0 0, 10 3.5, 0 7'); poly.setAttribute('fill', annot.color);
          marker.appendChild(poly); defs.appendChild(marker);
          const el = document.createElementNS(ns, 'line');
          el.setAttribute('x1', annot.x1); el.setAttribute('y1', annot.y1);
          el.setAttribute('x2', annot.x2); el.setAttribute('y2', annot.y2);
          el.setAttribute('stroke', annot.color); el.setAttribute('stroke-width', annot.lineWidth || 2);
          el.setAttribute('marker-end', `url(#${markerId})`);
          el.classList.add('wa-annot-shape'); el.dataset.annotId = annot.id;
          el.addEventListener('contextmenu', (e) => { e.preventDefault(); this._showAnnotMenu(annot, e); });
          svg.appendChild(el);
        } else if (annot.type === 'textbox') {
          // Non-Latin FreeText is flattened into the PDF page for portable
          // CJK rendering. Keep its metadata loaded, but do not draw a second
          // browser overlay on top of the already-visible page content.
          if (annot.flattened) return;
          const ns = 'http://www.w3.org/2000/svg';
          const fo = document.createElementNS(ns, 'foreignObject');
          fo.setAttribute('x', annot.x); fo.setAttribute('y', annot.y);
          fo.setAttribute('width',  annot.w || 120); fo.setAttribute('height', annot.h || 30);
          fo.classList.add('wa-annot-shape'); fo.dataset.annotId = annot.id;
          fo.addEventListener('contextmenu', (e) => { e.preventDefault(); this._showAnnotMenu(annot, e); });
          const div = document.createElement('div');
          div.style.cssText = `font-size:${annot.fontSize || 14}px;color:${annot.color};width:100%;height:100%;overflow:hidden;word-break:break-word;white-space:pre-wrap;`;
          div.textContent = annot.text; fo.appendChild(div); svg.appendChild(fo);
        } else if (annot.type === 'note') {
          // Note icon
          const icon = document.createElement('div');
          icon.className = 'wa-pdf-note-icon';
          icon.style.left = (annot.x - 11) + 'px';
          icon.style.top  = (annot.y - 22) + 'px';
          icon.title = annot.text || '便笺';
          icon.dataset.annotId = annot.id;
          icon.addEventListener('click', (e) => { e.stopPropagation(); this._toggleNotePopup(annot, wrap); });
          wrap.appendChild(icon);

          if (annot._open) this._showNotePopup(annot, wrap, icon);
        }
      });
    }

    _showAnnotMenu(annot, e) {
      // Simple context: delete annotation
      const existing = document.getElementById('wa-pdf-annot-ctx');
      if (existing) existing.remove();

      const menu = document.createElement('div');
      menu.id = 'wa-pdf-annot-ctx';
      menu.style.cssText = `position:fixed;
        background:var(--surface);border:1px solid var(--border);border-radius:6px;
        padding:4px 0;z-index:99999;box-shadow:0 4px 12px rgba(0,0,0,.25);min-width:130px;`;
      menu.innerHTML = `
        <div style="padding:6px 14px;cursor:pointer;font-size:12.5px;color:var(--text-muted)" id="wa-annt-explain">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:6px;vertical-align:middle"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>AI 解释
        </div>
        <div style="padding:6px 14px;cursor:pointer;font-size:12.5px;color:#ff7070" id="wa-annt-del">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:6px;vertical-align:middle"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/></svg>删除批注
        </div>`;

      appendToUiPortal(menu);
      placeFixedInViewport(menu, e.clientX, e.clientY, 8);

      menu.querySelector('#wa-annt-explain').addEventListener('click', () => {
        menu.remove();
        if (annot.text && typeof workspaceApi.sendCustomMessage === 'function') {
          workspaceApi.sendCustomMessage(`请解释以下内容：\n\n"${annot.text}"`);
        }
      });
      menu.querySelector('#wa-annt-del').addEventListener('click', () => {
        menu.remove();
        this._deleteAnnotation(annot.id);
      });

      const closeMenu = (ev) => { if (!menu.contains(ev.target)) { menu.remove(); document.removeEventListener('mousedown', closeMenu); } };
      document.addEventListener('mousedown', closeMenu);
    }

    _deleteAnnotation(id) {
      const annot = this._annotations.find(a => a.id === id);
      if (!annot) return;
      const page = annot.page;
      this._annotations = this._annotations.filter(a => a.id !== id);
      this._renderAnnotationsOnPage(page);
    }

    _toggleNotePopup(annot, wrap) {
      const existing = wrap.querySelector(`.wa-pdf-note-popup[data-id="${annot.id}"]`);
      if (existing) { existing.remove(); annot._open = false; }
      else { annot._open = true; const icon = wrap.querySelector(`.wa-pdf-note-icon[data-annotId="${annot.id}"]`); this._showNotePopup(annot, wrap, icon); }
    }

    _showNotePopup(annot, wrap, icon) {
      const popup = document.createElement('div');
      popup.className = 'wa-pdf-note-popup';
      popup.dataset.id = annot.id;
      const ix = icon ? (parseFloat(icon.style.left) + 11) : annot.x;
      const iy = icon ? (parseFloat(icon.style.top)  + 22) : annot.y;
      popup.style.left = (ix + 8) + 'px';
      popup.style.top  = (iy - 20) + 'px';

      popup.innerHTML = `
        <div class="wa-pdf-note-header" data-wa-pdf-note-drag>
          <span>便笺</span>
          <button class="wa-pdf-note-close" data-koto-stop-mousedown>✕</button>
        </div>
        <textarea class="wa-pdf-note-body" placeholder="在此输入备注…">${annot.text || ''}</textarea>
        <div class="wa-pdf-note-footer">
          <button class="wa-pdf-note-save">保存</button>
        </div>`;

      popup.querySelector('[data-wa-pdf-note-drag]')?.addEventListener('mousedown', (event) => {
        _pdfDragNote(event, popup);
      });
      popup.querySelector('.wa-pdf-note-close').addEventListener('mousedown', (event) => event.stopPropagation());
      popup.querySelector('.wa-pdf-note-close').addEventListener('click', () => {
        popup.remove(); annot._open = false;
      });
      popup.querySelector('.wa-pdf-note-save').addEventListener('click', () => {
        const nextText = popup.querySelector('textarea').value;
        annot.text = nextText;
        if (annot._source) annot._source.text = nextText;
        popup.remove(); annot._open = false;
        if (icon) icon.title = annot.text || '便笺';
      });

      wrap.appendChild(popup);
    }

    // ─── Annotate selection from floating toolbar ─────────────────────────────
    annotateSelection(type) {
      if (!this._annotMode) {
        // Temporarily set mode for this one action
        const prevMode = this._annotMode;
        this._annotMode = type;
        this._createTextAnnotation(type);
        this._annotMode = prevMode;
      } else {
        this._createTextAnnotation(type);
      }
      $('wa-selection-toolbar').style.display = 'none';
    }

    // ─── Save/load annotations via backend ───────────────────────────────────
    async saveAnnotations() {
      const runtime = this._session.snapshot();
      if (!runtime.fileId) return;
      try {
        showToast('正在保存批注到 PDF…', 'info');
        const res = await _csrfFetch('/api/v1/workspace/pdf/save_annotations', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            file_id: runtime.fileId,
            annotations: this._annotations,
            filename: runtime.fileName || 'annotated.pdf',
          }),
        });
        if (!res.ok) {
          const error = await res.json().catch(() => ({}));
          throw new Error(error.error || `HTTP ${res.status}`);
        }
        const blob = await res.blob();
        _downloadPdfBlob(blob, runtime.fileName || 'annotated.pdf');
        showToast('批注已嵌入 PDF 并下载', 'success');
      } catch (e) {
        showToast('保存批注失败: ' + e.message, 'error');
      }
    }

    async _annotationFromPdfSpace(annotation) {
      if (!annotation || annotation.coordinateSpace !== 'pdf' || !this._pdfDoc) {
        return annotation;
      }
      const pageNum = Number.parseInt(String(annotation.page || 0), 10);
      if (!pageNum || pageNum < 1 || pageNum > this._pageCount) return null;
      const page = await this._pdfDoc.getPage(pageNum);
      const baseViewport = page.getViewport({ scale: 1 });
      const fitScale = ((this._containerW || baseViewport.width) / baseViewport.width) * this._scale;
      const viewport = page.getViewport({ scale: fitScale });

      const rectToCss = (raw) => {
        if (!Array.isArray(raw) || raw.length < 4) return null;
        const converted = viewport.convertToViewportRectangle(raw.map(Number));
        const x1 = Math.min(converted[0], converted[2]);
        const y1 = Math.min(converted[1], converted[3]);
        const x2 = Math.max(converted[0], converted[2]);
        const y2 = Math.max(converted[1], converted[3]);
        return { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
      };
      const pointToCss = (x, y) => {
        const converted = viewport.convertToViewportPoint(Number(x), Number(y));
        return { x: converted[0], y: converted[1] };
      };

      const normalized = {
        ...annotation,
        pageWidth: viewport.width,
        pageHeight: viewport.height,
      };
      if (Number.isFinite(Number(annotation.pdfFontSize))) {
        normalized.fontSize = Number(annotation.pdfFontSize) * fitScale;
      }
      delete normalized.coordinateSpace;
      const cssRects = (Array.isArray(annotation.rects) ? annotation.rects : [])
        .map(rectToCss)
        .filter(Boolean);

      if (['highlight', 'underline', 'strikethrough'].includes(annotation.type)) {
        normalized.rects = cssRects;
      } else if (annotation.type === 'rect' || annotation.type === 'textbox' || annotation.type === 'note') {
        const rect = cssRects[0];
        if (!rect) return null;
        normalized.x = rect.x;
        normalized.y = rect.y;
        normalized.w = rect.w;
        normalized.h = rect.h;
      } else if (annotation.type === 'ellipse') {
        const rect = cssRects[0];
        if (!rect) return null;
        normalized.cx = rect.x + rect.w / 2;
        normalized.cy = rect.y + rect.h / 2;
        normalized.rx = rect.w / 2;
        normalized.ry = rect.h / 2;
      } else if (annotation.type === 'line' || annotation.type === 'arrow') {
        const line = Array.isArray(annotation.line) ? annotation.line : [];
        if (line.length < 4) return null;
        const start = pointToCss(line[0], line[1]);
        const end = pointToCss(line[2], line[3]);
        Object.assign(normalized, { x1: start.x, y1: start.y, x2: end.x, y2: end.y });
      } else if (annotation.type === 'draw') {
        const firstStroke = Array.isArray(annotation.inkList?.[0]) ? annotation.inkList[0] : [];
        normalized.points = firstStroke.map(point => pointToCss(point[0], point[1]));
      }
      return normalized;
    }

    async _loadAnnotationsFromServer() {
      const runtime = this._session.snapshot();
      if (!runtime.fileId) return;
      try {
        const res = await fetch('/api/v1/workspace/pdf/load_annotations/' + runtime.fileId);
        if (!res.ok) return;
        const json = await res.json();
        if (json.annotations && json.annotations.length > 0) {
          const loaded = await Promise.all(
            json.annotations.map(annotation => this._annotationFromPdfSpace(annotation))
          );
          this._annotations = loaded.filter(Boolean);
          // Re-render all loaded pages
          this._renderedPgs.forEach(pg => this._renderAnnotationsOnPage(pg));
        }
      } catch (e) { console.warn("[Koto]", e) }
    }

    _normalizeTextWithMap(text) {
      const chars = [];
      const map = [];
      const source = String(text || '');
      for (let idx = 0; idx < source.length;) {
        const codePoint = source.codePointAt(idx);
        const raw = String.fromCodePoint(codePoint);
        const normalized = raw.normalize('NFKC').toLowerCase();
        for (const ch of normalized) {
          // AI responses commonly change Chinese/English punctuation or
          // full-width forms. Ignore separators while retaining a map back to
          // the exact PDF.js UTF-16 offsets used by DOM Range.
          if (/[\s\p{P}\p{S}]/u.test(ch)) continue;
          chars.push(ch);
          map.push(idx);
        }
        idx += raw.length;
      }
      return { text: chars.join(''), map };
    }

    _extractAiAnnotationSuggestions(rawText) {
      const source = String(rawText || '').trim();
      if (!source) return [];
      const candidates = [source];
      const fenced = source.match(/```(?:json)?\s*([\s\S]*?)```/i);
      if (fenced && fenced[1]) candidates.push(fenced[1].trim());
      const arrStart = source.indexOf('[');
      const arrEnd = source.lastIndexOf(']');
      if (arrStart >= 0 && arrEnd > arrStart) candidates.push(source.slice(arrStart, arrEnd + 1));
      const objStart = source.indexOf('{');
      const objEnd = source.lastIndexOf('}');
      if (objStart >= 0 && objEnd > objStart) candidates.push(source.slice(objStart, objEnd + 1));

      for (const candidate of candidates) {
        try {
          const parsed = JSON.parse(candidate);
          const list = Array.isArray(parsed)
            ? parsed
            : (Array.isArray(parsed.annotations) ? parsed.annotations
              : Array.isArray(parsed.suggestions) ? parsed.suggestions
              : Array.isArray(parsed.items) ? parsed.items
              : []);
          const normalized = list.map((item) => this._normalizeAiAnnotationSuggestion(item)).filter(Boolean);
          if (normalized.length) return normalized;
        } catch (e) { console.warn("[Koto]", e) }
      }
      return [];
    }

    _normalizeAiAnnotationSuggestion(item) {
      if (!item || typeof item !== 'object') return null;
      const quote = String(
        item.quote || item.source_text || item.original || item.excerpt || item.text ||
        item['原文片段'] || item['原文'] || item['引用'] || ''
      ).trim();
      if (!quote) return null;
      const comment = String(
        item.comment || item.note || item.reason || item.suggestion || item.issue ||
        item['批注内容'] || item['批注'] || item['建议'] || item['原因'] || ''
      ).trim();
      const page = Number.parseInt(String(item.page || item.page_num || item.pageNumber || item['页码'] || ''), 10);
      const type = String(item.type || item.annotation_type || item['类型'] || 'highlight').trim().toLowerCase();
      return {
        page: Number.isFinite(page) && page > 0 ? page : null,
        quote,
        comment,
        type: ['underline', 'strikethrough'].includes(type) ? type : 'highlight',
      };
    }

    async _ensurePdfPageTextLayer(pageNum) {
      const page = Number.parseInt(String(pageNum), 10);
      if (!page || page < 1 || page > this._pageCount) return null;
      if (!this._renderedPgs.has(page)) await this._renderPage(page);
      const wrap = document.getElementById(`pdf-page-${page}`);
      if (!wrap) return null;
      for (let i = 0; i < 20; i += 1) {
        const textLayer = wrap.querySelector('.wa-pdf-text-layer');
        if (textLayer && textLayer.querySelector('span')) return { page, wrap, textLayer };
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      return null;
    }

    _rectsForTextRange(wrap, textLayer, charIdx, charLen) {
      const spans = Array.from(textLayer.querySelectorAll('span'));
      if (!spans.length || charIdx < 0 || charLen <= 0) return [];

      let running = 0, startSpan = null, startOff = 0, endSpan = null, endOff = 0;
      for (let i = 0; i < spans.length; i += 1) {
        const text = spans[i].textContent || '';
        const len = text.length;
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
      if (!startSpan || !endSpan) return [];

      try {
        const startNode = startSpan.firstChild || startSpan;
        const endNode = endSpan.firstChild || endSpan;
        const range = document.createRange();
        range.setStart(startNode, Math.max(0, Math.min(startOff, startNode.length || 0)));
        range.setEnd(endNode, Math.max(0, Math.min(endOff, endNode.length || 0)));
        return Array.from(range.getClientRects())
          .filter(r => r.width > 0 && r.height > 0)
          .map(r => {
            const local = viewportRectToElement(wrap, r);
            return { x: local.x, y: local.y, w: local.width, h: local.height };
          });
      } catch (_) {
        return [];
      }
    }

    async _locateAiAnnotationQuote(suggestion) {
      const pages = suggestion.page
        ? [suggestion.page]
        : Array.from({ length: Math.min(this._pageCount || 0, 8) }, (_, idx) => idx + 1);
      const needle = this._normalizeTextWithMap(suggestion.quote);
      if (!needle.text) return null;

      for (const page of pages) {
        const layerInfo = await this._ensurePdfPageTextLayer(page);
        if (!layerInfo) continue;
        const spans = Array.from(layerInfo.textLayer.querySelectorAll('span'));
        const pageText = spans.map(span => span.textContent || '').join('');
        const haystack = this._normalizeTextWithMap(pageText);
        const normalizedIdx = haystack.text.indexOf(needle.text);
        if (normalizedIdx < 0) continue;
        const rawStart = haystack.map[normalizedIdx];
        const rawEnd = haystack.map[normalizedIdx + needle.text.length - 1] + 1;
        const rects = this._rectsForTextRange(layerInfo.wrap, layerInfo.textLayer, rawStart, rawEnd - rawStart);
        if (rects.length) {
          const pageSize = getElementLogicalSize(layerInfo.wrap);
          return { page, rects, pageWidth: pageSize.width, pageHeight: pageSize.height };
        }
      }
      return null;
    }

    async _applyAiAnnotationSuggestions(rawText) {
      const suggestions = this._extractAiAnnotationSuggestions(rawText);
      if (!suggestions.length) {
        showToast('AI 已返回建议，但未识别到可定位的 JSON 批注。', 'warning', 5000);
        return 0;
      }

      let added = 0;
      for (const suggestion of suggestions.slice(0, 20)) {
        const located = await this._locateAiAnnotationQuote(suggestion);
        if (!located) continue;
        const content = suggestion.comment
          ? `AI建议：${suggestion.comment}\n\n原文：${suggestion.quote}`
          : `AI标注：${suggestion.quote}`;
        this._annotations.push({
          id: Date.now() + '-' + Math.random().toString(36).slice(2),
          type: suggestion.type,
          page: located.page,
          pageWidth: located.pageWidth,
          pageHeight: located.pageHeight,
          rects: located.rects,
          color: this._annotColor || '#FFFF00',
          text: suggestion.quote,
          content,
          timestamp: Date.now(),
          source: 'ai',
        });
        added += 1;
      }
      this._renderedPgs.forEach(pg => this._renderAnnotationsOnPage(pg));
      if (added) {
        this.annotOpen();
        showToast(`AI 已生成 ${added} 条可保存批注`, 'success', 5000);
      } else {
        showToast('AI 建议未能匹配到当前 PDF 文本位置。', 'warning', 5000);
      }
      return added;
    }

    // ─── AI auto-annotation ───────────────────────────────────────────────────
    async aiAnnotate() {
      const runtime = this._session.snapshot();
      if (!runtime.fileId || runtime.fileType !== 'pdf') {
        showToast('请先打开一个 PDF 文件', 'warning');
        return;
      }
      _expandWAPanel();
      _initWorkspaceAiRuntimes();
      const taskDispatcher = getWorkspaceTaskDispatcher();
      const conversationRuntime = getWorkspaceConversationRuntime();
      if (!taskDispatcher || typeof taskDispatcher.dispatchMessage !== 'function') {
        showToast('任务流程运行时未加载，请刷新后重试。', 'error');
        return;
      }

      const currentFile = {
        path: runtime.wsSourcePath || runtime.filePath || '',
        name: runtime.fileName || 'document.pdf',
        type: 'pdf',
      };
      const taskText = [
        '请读取当前 PDF，找出最需要标注的重点、风险、疑问或问题位置。',
        '只输出 JSON，不要 Markdown，不要额外解释。',
        'JSON 格式：{"annotations":[{"page":1,"quote":"PDF 中必须逐字存在的短原文片段","comment":"为什么需要标注/建议关注什么","type":"highlight"}]}',
        'quote 必须尽量短，必须来自原文，便于前端定位；最多 8 条。'
      ].join('\n');
      const msgs = $('wa-ai-messages');
      const turnUi = conversationRuntime && typeof conversationRuntime.appendUserMessageWithLoading === 'function'
        ? conversationRuntime.appendUserMessageWithLoading({
            content: 'AI 标注当前 PDF',
            files: [currentFile],
            task_kind: 'file_task',
          })
        : null;
      const loadingEl = turnUi && turnUi.loadingEl ? turnUi.loadingEl : document.createElement('div');
      if (!turnUi && msgs) {
        _hideWelcome();
        const uMsg = document.createElement('div');
        uMsg.className = 'wa-msg user';
        uMsg.textContent = 'AI 标注当前 PDF';
        msgs.appendChild(uMsg);
        loadingEl.className = 'wa-msg ai streaming';
        msgs.appendChild(loadingEl);
      }

      this._session.setLoading(true);
      _setStreamBtn(true);
      taskDispatcher.dispatchMessage({
        text: taskText,
        pinnedSelText: '',
        pinnedSelSource: '',
        msgs,
        loadingEl,
        taskPayload: {
          task: taskText,
          current_file: currentFile,
          files: [currentFile],
          file_name: currentFile.name,
          file_type: 'pdf',
          target_path: '',
          options: {
            output_mode: 'answer',
            pdf_ai_annotate: true,
          },
        },
        options: {
          output_mode: 'answer',
          pdf_ai_annotate: true,
        },
      }).then(async (result) => {
        const resultText = [
          result && result.assistantText,
          result && result.summary,
          result && result.result && result.result.summary,
          loadingEl && loadingEl.dataset && loadingEl.dataset.taskSummary,
          loadingEl && (loadingEl.innerText || loadingEl.textContent),
        ].filter(Boolean).join('\n');
        await this._applyAiAnnotationSuggestions(resultText);
      }).catch((error) => {
        loadingEl.classList.remove('streaming');
        loadingEl.textContent = `AI 标注失败：${error && error.message ? error.message : error}`;
      }).finally(() => {
        this._session.setLoading(false);
        _setStreamBtn(false);
      });
    }

    // ─── Local structural watermark removal ───────────────────────────────────
    async pdfRemoveWatermark() {
      const runtime = this._session.snapshot();
      if (!runtime.fileId) { showToast('请先打开一个 PDF 文件', 'warning'); return; }
      const overlay  = document.getElementById('wa-pdf-watermark-overlay');
      const statusEl = document.getElementById('wa-pwm-status');
      const barEl    = document.getElementById('wa-pwm-bar');
      const dlLink   = document.getElementById('wa-pwm-download');
      const resultEl = document.getElementById('wa-pwm-result');
      if (overlay)  { overlay.style.display = 'flex'; overlay.classList.add('open'); }
      if (statusEl) statusEl.textContent = '正在分析 PDF 水印…';
      if (barEl)    barEl.style.width = '20%';
      if (dlLink)   dlLink.style.display = 'none';
      if (resultEl) resultEl.textContent = '';
      try {
        const res = await _csrfFetch('/api/v1/workspace/pdf/remove_watermark', {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ file_id: runtime.fileId }),
        });
        if (barEl) barEl.style.width = '80%';
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.error || `HTTP ${res.status}`);
        }
        const blob = await res.blob();
        if (barEl) barEl.style.width = '100%';
        const url  = URL.createObjectURL(blob);
        const name = (runtime.fileName || 'watermark_removed.pdf').replace(/\.pdf$/i, '') + '_去水印.pdf';
        const removed = res.headers.get('X-Koto-Removed-Count') || '?';
        const method  = res.headers.get('X-Koto-Method') || '';
        const reason = res.headers.get('X-Koto-Reason') || '';
        if (removed !== '0' && removed !== '?') {
          _downloadPdfBlob(blob, name);
          if (dlLink) { dlLink.href = url; dlLink.download = name; dlLink.style.display = ''; }
        } else {
          URL.revokeObjectURL(url);
          if (dlLink) { dlLink.removeAttribute('href'); dlLink.style.display = 'none'; }
        }
        if (statusEl) statusEl.textContent = removed === '0'
          ? '未检测到可安全清理的受支持水印，原文件未改变。'
          : `去水印完成！共处理 ${removed} 处。`;
        if (resultEl) resultEl.textContent = [
          method ? `检测方法：${method}` : '',
          reason ? `结果原因：${reason}` : '',
        ].filter(Boolean).join(' · ');
        showToast(removed === '0' ? '未检测到可安全清理的水印' : '水印清理完成', removed === '0' ? 'info' : 'success');
      } catch (err) {
        if (statusEl) statusEl.textContent = '去水印失败：' + err.message;
        if (barEl)    barEl.style.width = '0%';
        showToast('去水印失败: ' + err.message, 'error');
      }
    }

    // ─── Existing interface ───────────────────────────────────────────────────
    handleMouseUp(e) {
      this._onMouseUp(e);
    }

    hideTooltip(e) {
      if (!e.target.closest('#wa-selection-toolbar')) {
        $('wa-selection-toolbar').style.display = 'none';
      }
    }

    getContent() {
      const sel = window.getSelection().toString().trim();
      if (sel) return `[选中的 PDF 文本]:\n${sel}\n`;
      // Collect text from rendered pages
      const texts = [];
      for (let pg = 1; pg <= Math.min(3, this._pageCount); pg++) {
        if (this._textContent[pg]) texts.push(`[第${pg}页]\n` + this._textContent[pg].slice(0, 2000));
      }
      return texts.length > 0 ? texts.join('\n\n') : '[PDF 正在加载，暂无文本]';
    }

    getSelectionPayload() {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
      const text = sel.toString().trim();
      if (!text) return null;
      const range = sel.getRangeAt(0);
      const startEl = range.startContainer.nodeType === Node.TEXT_NODE
        ? range.startContainer.parentElement
        : range.startContainer;
      const endEl = range.endContainer.nodeType === Node.TEXT_NODE
        ? range.endContainer.parentElement
        : range.endContainer;
      const startWrap = startEl && startEl.closest ? startEl.closest('.wa-pdf-page-wrap') : null;
      const endWrap = endEl && endEl.closest ? endEl.closest('.wa-pdf-page-wrap') : null;
      const container = $(this.containerId);
      if (!startWrap || !container || !container.contains(startWrap)) return null;
      const pageStart = Number(startWrap.dataset.page || 0) || 0;
      const pageEnd = Number((endWrap && endWrap.dataset.page) || pageStart) || pageStart;
      const pageLabel = pageStart === pageEnd ? `第 ${pageStart} 页` : `第 ${pageStart}-${pageEnd} 页`;
      return {
        kind: 'pdf-text',
        text,
        aiText: `[选中的 PDF 文本，${pageLabel}]:\n${text}\n`,
        previewText: `${pageLabel} · ${text.length} 字`,
        countLabel: `${text.replace(/\s/g, '').length}字`,
        pageStart,
        pageEnd,
      };
    }

    serialize() { return null; }
}
