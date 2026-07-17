// @ts-nocheck
import type { WorkspaceEditor, PdfViewerOptions, PdfOutlineItem, PdfAnnotation, PdfSearchMatch } from './types';
import { getWorkspaceApi, publishWorkspaceApi } from '../shared/workspace-api';

const workspaceApi = getWorkspaceApi();
const state: any = (window as any).state || {};
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

export class KotoPdfViewer implements WorkspaceEditor {
    constructor() {
      this.containerId   = 'wa-pdf-viewer';
      this._scale        = 1.0;
      this._pdfDoc       = null;
      this._pdfUrl       = null;
      this._pageCount    = 0;
      this._outline      = [];          // [{title, page, children}]
      this._metadata     = {};

      // Annotation state
      this._annotations  = [];          // in-memory annotation list
      this._annotMode    = null;        // 'highlight' | 'underline' | 'strikethrough' | 'note' | 'draw' | 'rect' | 'ellipse' | 'line' | 'arrow' | 'textbox' | 'eraser'
      this._annotColor   = '#FFFF00';   // current annotation color
      this._annotLineWidth = 2;         // line width for shapes and freehand
      this._drawPath     = null;        // active SVG path element during drawing
      this._drawPoints   = [];          // points during freehand draw
      this._shapePreview = null;        // live preview SVG element during shape drag
      this._shapeStart   = null;        // {x, y} drag start point
      this._shapeSvg     = null;        // SVG layer being drawn on
      this._shapePageNum = 0;           // page number being drawn on

      // Search state
      this._searchQuery  = '';
      this._searchPgs    = [];          // [{page, rects:[{x,y,w,h}]}] in CSS px, per match
      this._searchIdx    = -1;

      // Lazy loading
      this._observer     = null;        // IntersectionObserver
      this._renderedPgs  = new Set();   // set of 1-based page nums that have been rendered
      this._textContent  = {};          // page → pdfjsLib textContent (for search)
      this._thumbCanvas  = {};          // page → small canvas element (thumbnails)

      // Sidebar state
      this._sidebarPanel = 'thumbs';    // 'thumbs' | 'bookmarks'

      // Keyboard handler (Ctrl+F)
      this._keyHandler = (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
          if (state.fileType === 'pdf') {
            e.preventDefault();
            this.searchOpen();
          }
        }
        if (e.key === 'Escape' && state.fileType === 'pdf') {
          this.searchClose();
        }
      };
      document.addEventListener('keydown', this._keyHandler);

      // Wheel zoom
      this._wheelHandler = (e) => {
        if (!e.ctrlKey && !e.metaKey) return;
        e.preventDefault();
        const delta = e.deltaY > 0 ? -10 : 10;
        const newPct = Math.max(50, Math.min(300, Math.round(this._scale * 100) + delta));
        this.setZoom(newPct);
      };

      const container = $(this.containerId);
      container.classList.add('active');
      container.addEventListener('wheel', this._wheelHandler, { passive: false });
      container.addEventListener('mouseup', this._onMouseUp.bind(this));
      container.addEventListener('mousedown', this._onMouseDown.bind(this));
      container.addEventListener('mousemove', this._onMouseMove.bind(this));
      container.addEventListener('scroll', this._onScroll.bind(this), { passive: true });

      document.addEventListener('mousedown', (e) => {
        if (!e.target.closest('#wa-selection-toolbar')) {
          $('wa-selection-toolbar').style.display = 'none';
        }
      });

      const outer = $('wa-pdf-editor');
      if (outer) outer.classList.add('active');
    }

    // ─── render ──────────────────────────────────────────────────────────────
    async render(pdfUrl, pagesData) {
      this._pdfUrl    = pdfUrl;
      this._scale     = 1.0;
      this._outline   = (pagesData && pagesData.outline)  || [];
      this._metadata  = (pagesData && pagesData.metadata) || {};
      this._annotations = [];
      this._renderedPgs.clear();
      this._textContent = {};

      _updatePdfZoomUI(100);

      await this._doRender();

      // Load existing annotations if any are embedded in the PDF
      this._loadAnnotationsFromServer();
    }

    // ─── _doRender ───────────────────────────────────────────────────────────
    async _doRender() {
      const pdfUrl = this._pdfUrl;
      const c = $(this.containerId);
      c.innerHTML = '';

      const pdfjsLib = _pdfRuntime();
      if (!pdfjsLib) {
        c.innerHTML = '<div style="color:var(--danger);padding:16px">PDF.js 加载失败</div>';
        return;
      }

      try {
        if (!this._pdfDoc || this._pdfDoc._url !== pdfUrl) {
        const loadingTask = pdfjsLib.getDocument(pdfUrl);
          this._pdfDoc = await loadingTask.promise;
          this._pdfDoc._url = pdfUrl;
        }
        const pdf = this._pdfDoc;
        this._pageCount = pdf.numPages;

        // Containers for deferred render
        this._renderedPgs.clear();
        this._textContent = {};

        // Estimate page size for placeholders (use page 1)
        const firstPage = await pdf.getPage(1);
        const baseVP = firstPage.getViewport({ scale: 1 });
        const containerW = Math.max(240, (c.clientWidth || c.getBoundingClientRect?.().width || 800) - 32);
        const dpr = window.devicePixelRatio || 1;
        this._quality = Math.max(2, dpr);
        this._containerW = containerW;
        this._baseAspect = baseVP.height / baseVP.width;

        // Build placeholder pages for ALL pages (lazy rendering via IntersectionObserver)
        for (let i = 1; i <= pdf.numPages; i++) {
          const wrap = document.createElement('div');
          wrap.className = 'wa-pdf-page-wrap';
          wrap.id = `pdf-page-${i}`;
          wrap.dataset.page = i;

          // Placeholder canvas with estimated size
          const canvas = document.createElement('canvas');
          const fitScale = (containerW / baseVP.width) * this._scale;
          canvas.style.width  = Math.floor(baseVP.width  * fitScale) + 'px';
          canvas.style.height = Math.floor(baseVP.height * fitScale) + 'px';
          canvas.style.background = '#e8e8e8';
          canvas.style.borderRadius = '2px';
          canvas.width  = 1;  // minimal actual pixels until rendered
          canvas.height = 1;
          wrap.appendChild(canvas);
          c.appendChild(wrap);
        }

        // Disconnect old observer and set up new one
        if (this._observer) this._observer.disconnect();
        if (typeof IntersectionObserver !== 'undefined') {
          this._observer = new IntersectionObserver(
            (entries) => entries.forEach(en => {
              if (en.isIntersecting) {
                const pg = parseInt(en.target.dataset.page, 10);
                if (pg && !this._renderedPgs.has(pg)) {
                  this._renderPage(pg);
                }
              }
            }),
            { root: c, rootMargin: '300px 0px 300px 0px', threshold: 0 }
          );
          c.querySelectorAll('.wa-pdf-page-wrap').forEach(el => this._observer.observe(el));
        }
        this._scheduleVisiblePageRenderPasses();

        // Build sidebar
        this._buildThumbs();
        this._buildBookmarks();

        // Update page counter
        this._updatePageCounter(1);

      } catch (e) {
        console.error('[KotoPdfViewer] render error:', e);
        c.innerHTML = `<div style="color:var(--danger);padding:16px">PDF 渲染报错: ${e.message}</div>`;
      }
    }

    _scheduleVisiblePageRenderPasses() {
      this._renderVisiblePagesNow();
      requestAnimationFrame(() => this._renderVisiblePagesNow());
      setTimeout(() => this._renderVisiblePagesNow(), 120);
      setTimeout(() => this._renderVisiblePagesNow(), 500);
    }

    _renderVisiblePagesNow() {
      const c = $(this.containerId);
      if (!c || !this._pdfDoc) return;
      const wraps = Array.from(c.querySelectorAll('.wa-pdf-page-wrap'));
      if (!wraps.length) return;

      const rootRect = c.getBoundingClientRect?.();
      const hasViewport = rootRect && rootRect.width > 0 && rootRect.height > 0;
      const margin = 300;
      let renderedAny = false;

      wraps.forEach((wrap) => {
        const pg = parseInt(wrap.dataset.page, 10);
        if (!pg || this._renderedPgs.has(pg)) return;
        if (!hasViewport) return;
        const rect = wrap.getBoundingClientRect();
        const visible = rect.bottom >= rootRect.top - margin && rect.top <= rootRect.bottom + margin;
        if (visible) {
          renderedAny = true;
          this._renderPage(pg);
        }
      });

      if (!renderedAny && !this._renderedPgs.has(1)) {
        this._renderPage(1);
      }
    }

    // ─── _renderPage ─────────────────────────────────────────────────────────
    async _renderPage(pageNum) {
      if (this._renderedPgs.has(pageNum) || !this._pdfDoc) return;
      this._renderedPgs.add(pageNum);

      const wrap = document.getElementById(`pdf-page-${pageNum}`);
      if (!wrap) return;

      try {
        const pdf = this._pdfDoc;
        const page = await pdf.getPage(pageNum);
        const baseViewport = page.getViewport({ scale: 1 });
        const containerW = this._containerW || 800;
        const quality = this._quality || 2;
        const fitScale = (containerW / baseViewport.width) * this._scale;
        const renderViewport = page.getViewport({ scale: fitScale * quality });
        // textViewport drives both canvas CSS size AND text layer — must be the same object.
        // Using Math.floor() would create a sub-pixel mismatch between span coordinates
        // (float) and the container, causing selection drift and highlight misalignment.
        const textViewport = page.getViewport({ scale: fitScale });
        // Math.ceil: ensures container is never smaller than the viewport coordinate space.
        // A sub-pixel deficit (floor) would cause overflow:hidden to clip rightmost/bottom
        // spans, making those characters unselectable. Ceiling adds at most 1px of safe margin.
        const cssW = Math.ceil(textViewport.width);
        const cssH = Math.ceil(textViewport.height);

        // Replace placeholder canvas with real one
        const canvas = wrap.querySelector('canvas') || document.createElement('canvas');
        const context = canvas.getContext('2d');
        canvas.width  = Math.round(renderViewport.width);
        canvas.height = Math.round(renderViewport.height);
        canvas.style.width  = cssW + 'px';
        canvas.style.height = cssH + 'px';
        canvas.style.background = '';

        if (!wrap.contains(canvas)) wrap.insertBefore(canvas, wrap.firstChild);

        await page.render({ canvasContext: context, viewport: renderViewport }).promise;

        // Add text layer for selection and search
        this._addTextLayer(wrap, page, textViewport, cssW, cssH);

        // Add annotation SVG overlay
        this._addAnnotLayer(wrap, pageNum, cssW, cssH);

        // Re-render annotations for this page
        this._renderAnnotationsOnPage(pageNum);

        // Re-render search highlights
        if (this._searchQuery) this._renderSearchOnPage(pageNum);

        // Extract text for search index (background)
        this._extractPageText(page, pageNum);

        // Update thumbnail if needed (draw on existing thumb canvas)
        this._drawThumbForPage(pageNum, page, baseViewport);

      } catch (e) {
        console.warn(`[KotoPdfViewer] page ${pageNum} render error:`, e);
      }
    }

    // ─── _addTextLayer ───────────────────────────────────────────────────────
    // textViewport must be the SAME viewport used to set canvas CSS width/height.
    // This guarantees span coordinates exactly match the container pixel grid,
    // which is required for correct selection hit-testing and highlight alignment.
    async _addTextLayer(wrap, page, textViewport, cssW, cssH) {
      // Remove old text layer if re-rendering
      const old = wrap.querySelector('.wa-pdf-text-layer');
      if (old) old.remove();

      const div = document.createElement('div');
      div.className = 'wa-pdf-text-layer';
      div.style.width  = cssW + 'px';
      div.style.height = cssH + 'px';
      div.style.setProperty('--scale-factor', textViewport.scale);
      wrap.appendChild(div);

      try {
        const textContent = await page.getTextContent();

        // Use the viewport passed in — do NOT create a new one here.
        // Creating a second getViewport() call may return a slightly different
        // float width/height due to internal rounding, breaking span alignment.
        // pdfjs-dist 3.x API uses "textContent" (resolved object from getTextContent()).
        // "textContentSource" is the 4.x stream API — passing it to 3.x causes an error,
        // which triggers the catch block and sets pointerEvents:none on the layer,
        // making all text unselectable.
        const renderTask = _pdfRuntime().renderTextLayer({
          textContent: textContent,
          container: div,
          viewport: textViewport,
        });
        await renderTask.promise;
      } catch (e) {
        // text layer is best-effort — don't block render
        div.style.pointerEvents = 'none';
      }
    }

    // ─── _addAnnotLayer ──────────────────────────────────────────────────────
    _addAnnotLayer(wrap, pageNum, cssW, cssH) {
      const old = wrap.querySelector('.wa-pdf-annot-layer');
      if (old) old.remove();

      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.classList.add('wa-pdf-annot-layer');
      svg.dataset.page = pageNum;
      svg.setAttribute('width', cssW);
      svg.setAttribute('height', cssH);
      svg.style.width  = cssW + 'px';
      svg.style.height = cssH + 'px';
      wrap.appendChild(svg);

      // Drawing mode pointer events
      svg.addEventListener('mousedown', (e) => {
        if (this._annotMode === 'draw') this._startDraw(e, svg, pageNum);
        else if (this._annotMode === 'note') this._placeNote(e, wrap, pageNum);
      });

      return svg;
    }

    // ─── _extractPageText (async, for search) ────────────────────────────────
    async _extractPageText(page, pageNum) {
      if (this._textContent[pageNum]) return;
      try {
        const tc = await page.getTextContent();
        this._textContent[pageNum] = tc.items.map(it => it.str).join(' ');
      } catch (e) { console.warn("[Koto]", e) }
    }

    // ─── _buildThumbs ────────────────────────────────────────────────────────
    async _buildThumbs() {
      const strip = $('wa-pdf-thumbstrip');
      if (!strip) return;
      strip.innerHTML = '';

      const pdf = this._pdfDoc;
      if (!pdf) return;

      for (let i = 1; i <= pdf.numPages; i++) {
        const wrap = document.createElement('div');
        wrap.className = 'wa-pdf-thumb-wrap';

        const thumbDiv = document.createElement('div');
        thumbDiv.className = 'wa-pdf-thumb' + (i === 1 ? ' active' : '');
        thumbDiv.id = `pdf-thumb-${i}`;

        const canvas = document.createElement('canvas');
        canvas.style.display = 'block';
        thumbDiv.appendChild(canvas);

        const idx = document.createElement('span');
        idx.className = 'wa-pdf-thumb-idx';
        idx.textContent = i;

        wrap.appendChild(thumbDiv);
        wrap.appendChild(idx);
        wrap.addEventListener('click', () => this._scrollToPage(i));
        strip.appendChild(wrap);

        // Render thumbnail asynchronously
        this._renderThumb(i, canvas);
      }
    }

    async _renderThumb(pageNum, canvas) {
      try {
        const page = await this._pdfDoc.getPage(pageNum);
        const baseVP = page.getViewport({ scale: 1 });
        const THUMB_W = 148;
        const scale = THUMB_W / baseVP.width;
        const vp = page.getViewport({ scale });
        canvas.width  = Math.floor(vp.width);
        canvas.height = Math.floor(vp.height);
        canvas.style.width  = Math.floor(vp.width) + 'px';
        canvas.style.height = Math.floor(vp.height) + 'px';
        await page.render({ canvasContext: canvas.getContext('2d'), viewport: vp }).promise;
      } catch (e) { console.warn("[Koto]", e) }
    }

    _drawThumbForPage(pageNum, page, baseViewport) {
      const thumbDiv = document.getElementById(`pdf-thumb-${pageNum}`);
      if (!thumbDiv) return;
      const canvas = thumbDiv.querySelector('canvas');
      if (!canvas || canvas.width > 1) return; // already rendered by _renderThumb
      this._renderThumb(pageNum, canvas);
    }

    // ─── _buildBookmarks ─────────────────────────────────────────────────────
    _buildBookmarks() {
      const panel = $('wa-pdf-bookmarks');
      if (!panel) return;
      panel.innerHTML = '';

      if (!this._outline || this._outline.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'wa-pdf-bm-empty';
        empty.textContent = '无书签';
        panel.appendChild(empty);
        return;
      }

      const render = (items, container) => {
        items.forEach(item => {
          const div = document.createElement('div');
          div.className = 'wa-pdf-bm-item wa-pdf-bm-children';

          const toggle = document.createElement('span');
          toggle.className = 'wa-pdf-bm-toggle';
          toggle.textContent = item.children && item.children.length ? '▶' : '';

          const label = document.createElement('span');
          label.style.flex = '1';
          label.style.overflow = 'hidden';
          label.style.textOverflow = 'ellipsis';
          label.style.whiteSpace = 'nowrap';
          label.textContent = item.title || '(无标题)';
          label.title = item.title || '';

          const pg = document.createElement('span');
          pg.className = 'wa-pdf-bm-pg';
          if (item.page) pg.textContent = item.page;

          div.appendChild(toggle);
          div.appendChild(label);
          div.appendChild(pg);

          div.addEventListener('click', () => {
            if (item.page) this._scrollToPage(item.page);
          });

          container.appendChild(div);

          if (item.children && item.children.length) {
            const child = document.createElement('div');
            child.className = 'wa-pdf-bm-children';
            child.style.display = 'none';
            render(item.children, child);
            container.appendChild(child);

            toggle.textContent = '▶';
            toggle.style.cursor = 'pointer';
            toggle.addEventListener('click', (e) => {
              e.stopPropagation();
              const isOpen = child.style.display !== 'none';
              child.style.display = isOpen ? 'none' : 'block';
              toggle.textContent = isOpen ? '▶' : '▼';
            });
          }
        });
      };

      render(this._outline, panel);
    }

    // ─── _scrollToPage ───────────────────────────────────────────────────────
    _scrollToPage(pageNum) {
      const wrap = document.getElementById(`pdf-page-${pageNum}`);
      if (wrap) wrap.scrollIntoView({ behavior: 'smooth', block: 'start' });
      this._highlightThumb(pageNum);
    }

    _highlightThumb(pageNum) {
      const strip = $('wa-pdf-thumbstrip');
      if (!strip) return;
      strip.querySelectorAll('.wa-pdf-thumb').forEach(el => el.classList.remove('active'));
      const thumb = document.getElementById(`pdf-thumb-${pageNum}`);
      if (thumb) {
        thumb.classList.add('active');
        thumb.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }

    _updatePageCounter(pageNum) {
      const counter = $('wa-pdf-page-counter');
      if (counter) counter.textContent = `第 ${pageNum} 页，共 ${this._pageCount} 页`;
    }

    _onScroll() {
      // Find the page whose center is closest to the scroll container center
      const c = $(this.containerId);
      if (!c) return;
      const scrollMid = c.scrollTop + c.clientHeight / 2;
      let bestPage = 1, bestDist = Infinity;
      c.querySelectorAll('.wa-pdf-page-wrap').forEach(el => {
        const pg = parseInt(el.dataset.page, 10);
        const mid = el.offsetTop + el.offsetHeight / 2;
        const dist = Math.abs(mid - scrollMid);
        if (dist < bestDist) { bestDist = dist; bestPage = pg; }
      });
      this._updatePageCounter(bestPage);
      this._highlightThumb(bestPage);
    }

    // ─── zoom ─────────────────────────────────────────────────────────────────
    setZoom(pct) {
      this._scale = Math.max(0.5, Math.min(3.0, pct / 100));
      _updatePdfZoomUI(Math.round(this._scale * 100));
      // Re-render all pages at new scale
      this._renderedPgs.clear();
      const c = $(this.containerId);
      if (c) {
        c.querySelectorAll('.wa-pdf-page-wrap').forEach(el => {
          const pg = parseInt(el.dataset.page, 10);
          // Reset canvas to placeholder
          const cv = el.querySelector('canvas');
          if (cv) {
            cv.style.background = '#f0f0f0';
            cv.width = 1; cv.height = 1;
          }
          const tl = el.querySelector('.wa-pdf-text-layer');
          if (tl) tl.remove();
        });
      }
      // Re-trigger intersection observer
      if (this._observer) {
        this._observer.disconnect();
        if (c) {
          c.querySelectorAll('.wa-pdf-page-wrap').forEach(el => this._observer.observe(el));
        }
      }
      this._scheduleVisiblePageRenderPasses();
    }

    // ─── Sidebar tab switch ───────────────────────────────────────────────────
    sidebarTab(btn) {
      const panel = btn.dataset.panel;
      document.querySelectorAll('.wa-pdf-stab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      $('wa-pdf-thumbstrip').style.display = panel === 'thumbs' ? 'flex' : 'none';
      $('wa-pdf-bookmarks').style.display  = panel === 'bookmarks' ? 'flex' : 'none';
      this._sidebarPanel = panel;
    }

    toggleSidebar() {
      const sb = $('wa-pdf-sidebar');
      if (!sb) return;
      sb.style.display = sb.style.display === 'none' ? 'flex' : 'none';
    }

    // ─── Search ───────────────────────────────────────────────────────────────
    searchOpen() {
      const bar = $('wa-pdf-search-bar');
      if (!bar) return;
      bar.style.display = 'flex';
      const inp = $('wa-pdf-search-input');
      if (inp) { inp.value = this._searchQuery; inp.focus(); inp.select(); }
    }

    searchClose() {
      const bar = $('wa-pdf-search-bar');
      if (bar) bar.style.display = 'none';
      this._clearSearchHighlights();
      this._searchQuery = '';
      this._searchPgs = [];
      this._searchIdx = -1;
      const cnt = $('wa-pdf-search-count');
      if (cnt) cnt.textContent = '';
    }

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
        let count = 0;
        while ((idx = text.toLowerCase().indexOf(lq, idx)) !== -1) {
          this._searchPgs.push({ page: pg, charIdx: idx, charLen: lq.length });
          idx++;
          count++;
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
        const wrapRect = wrap.getBoundingClientRect();

        const svg = wrap.querySelector('.wa-pdf-annot-layer');
        if (!svg) return;

        rects.forEach(r => {
          const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
          rect.setAttribute('x',      r.left - wrapRect.left);
          rect.setAttribute('y',      r.top  - wrapRect.top);
          rect.setAttribute('width',  r.width);
          rect.setAttribute('height', r.height);
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
    _onMouseUp(e) {
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
        const rect = wrap.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
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
      const wrap = range.startContainer.parentElement &&
                   range.startContainer.parentElement.closest('.wa-pdf-page-wrap');
      if (!wrap) return;
      const pageNum = parseInt(wrap.dataset.page, 10);
      if (!pageNum) return;

      const rects = Array.from(range.getClientRects());
      const wrapRect = wrap.getBoundingClientRect();
      const pageRects = rects.map(r => ({
        x: r.left - wrapRect.left,
        y: r.top  - wrapRect.top,
        w: r.width,
        h: r.height,
      }));

      const annot = {
        id:    Date.now() + '-' + Math.random().toString(36).slice(2),
        type,
        page:  pageNum,
        pageWidth: wrapRect.width,
        pageHeight: wrapRect.height,
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
      const rect = wrap.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      const annot = {
        id:    Date.now() + '-' + Math.random().toString(36).slice(2),
        type:  'note',
        page:  pageNum,
        x, y,
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
      const rect = svg.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

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

      const endDraw = () => {
        if (!this._drawPath) return;
        if (this._drawPoints.length > 1) {
          const annot = {
            id:        Date.now() + '-' + Math.random().toString(36).slice(2),
            type:      'draw',
            page:      this._drawPageNum,
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
        document.removeEventListener('mouseup', endDraw);
      };
      document.addEventListener('mouseup', endDraw, { once: true });
    }

    // ─── Shape drawing (rect / ellipse / line / arrow) ─────────────────────────────
    _startShape(e, svg, pageNum) {
      e.preventDefault();
      const svgRect = svg.getBoundingClientRect();
      const x = e.clientX - svgRect.left;
      const y = e.clientY - svgRect.top;
      this._shapeStart   = { x, y };
      this._shapeSvg     = svg;
      this._shapePageNum = pageNum;
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
      const svgRect = this._shapeSvg.getBoundingClientRect();
      const x2 = e.clientX - svgRect.left;
      const y2 = e.clientY - svgRect.top;
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
          color:     this._annotColor,
          lineWidth: this._annotLineWidth,
          timestamp: Date.now(),
        };
        this._annotations.push(full);
        this._renderAnnotationsOnPage(full.page);
      }
    }

    // ─── Eraser ──────────────────────────────────────────────────────────────
    _handleEraser(e, wrap) {
      const pageNum = parseInt(wrap.dataset.page, 10);
      const wrapRect = wrap.getBoundingClientRect();
      const ex = e.clientX - wrapRect.left;
      const ey = e.clientY - wrapRect.top;
      const HIT = 14;
      const hit = this._annotations.find(a => {
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
      const wrapRect = wrap.getBoundingClientRect();
      const x = e.clientX - wrapRect.left;
      const y = e.clientY - wrapRect.top;
      const box = document.createElement('div');
      box.contentEditable = 'true';
      box.className = 'wa-pdf-textbox-edit';
      box.style.cssText = `position:absolute;left:${x}px;top:${y}px;min-width:80px;min-height:22px;
        border:1.5px dashed ${this._annotColor};color:${this._annotColor};font-size:14px;
        background:rgba(255,255,255,.06);outline:none;padding:2px 4px;cursor:text;z-index:100;`;
      wrap.appendChild(box);
      box.focus();
      const commit = () => {
        const text = box.innerText.trim();
        box.remove();
        if (!text) return;
        const annot = {
          id:        Date.now() + '-' + Math.random().toString(36).slice(2),
          type:      'textbox',
          page:      pageNum,
          x, y,
          w:         Math.max(80, box.offsetWidth),
          h:         Math.max(22, box.offsetHeight),
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
        if (ke.key === 'Escape') { ke.preventDefault(); box.remove(); }
        else if (ke.key === 'Enter' && !ke.shiftKey) { ke.preventDefault(); commit(); }
      });
    }

    // ─── Render annotations on a page ────────────────────────────────────────
    _renderAnnotationsOnPage(pageNum) {
      const wrap = document.getElementById(`pdf-page-${pageNum}`);
      if (!wrap) return;
      const svg = wrap.querySelector('.wa-pdf-annot-layer');
      if (!svg) return;

      // Clear existing annotation elements (keep search highlights)
      svg.querySelectorAll('.wa-annot-hi, .wa-annot-ul, .wa-annot-st, .wa-annot-draw-saved, .wa-annot-shape, .wa-pdf-note-icon').forEach(el => el.remove());
      wrap.querySelectorAll('.wa-pdf-note-popup').forEach(el => el.remove());

      const pageAnnots = this._annotations.filter(a => a.page === pageNum);
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
      menu.style.cssText = `position:fixed;left:${e.clientX}px;top:${e.clientY}px;
        background:var(--surface);border:1px solid var(--border);border-radius:6px;
        padding:4px 0;z-index:99999;box-shadow:0 4px 12px rgba(0,0,0,.25);min-width:130px;`;
      menu.innerHTML = `
        <div style="padding:6px 14px;cursor:pointer;font-size:12.5px;color:var(--text-muted)" id="wa-annt-explain">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:6px;vertical-align:middle"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>AI 解释
        </div>
        <div style="padding:6px 14px;cursor:pointer;font-size:12.5px;color:#ff7070" id="wa-annt-del">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:6px;vertical-align:middle"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/></svg>删除批注
        </div>`;

      document.body.appendChild(menu);

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
          <button class="wa-pdf-note-close" onmousedown="event.stopPropagation()">✕</button>
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
        annot.text = popup.querySelector('textarea').value;
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
      if (!state.fileId) return;
      try {
        showToast('正在保存批注到 PDF…', 'info');
        const res = await _csrfFetch('/api/v1/workspace/pdf/save_annotations', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ file_id: state.fileId, annotations: this._annotations }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const blob = await res.blob();
        // Trigger download of the annotated PDF
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = state.fileName || 'annotated.pdf';
        a.click();
        URL.revokeObjectURL(url);
        showToast('批注已嵌入 PDF 并下载', 'success');
      } catch (e) {
        showToast('保存批注失败: ' + e.message, 'error');
      }
    }

    async _loadAnnotationsFromServer() {
      if (!state.fileId) return;
      try {
        const res = await fetch('/api/v1/workspace/pdf/load_annotations/' + state.fileId);
        if (!res.ok) return;
        const json = await res.json();
        if (json.annotations && json.annotations.length > 0) {
          this._annotations = json.annotations;
          // Re-render all loaded pages
          this._renderedPgs.forEach(pg => this._renderAnnotationsOnPage(pg));
        }
      } catch (e) { console.warn("[Koto]", e) }
    }

    _normalizeTextWithMap(text) {
      const chars = [];
      const map = [];
      String(text || '').split('').forEach((ch, idx) => {
        if (/\s/.test(ch)) return;
        chars.push(ch.toLowerCase());
        map.push(idx);
      });
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
        const wrapRect = wrap.getBoundingClientRect();
        return Array.from(range.getClientRects())
          .filter(r => r.width > 0 && r.height > 0)
          .map(r => ({
            x: r.left - wrapRect.left,
            y: r.top - wrapRect.top,
            w: r.width,
            h: r.height,
          }));
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
          const wrapRect = layerInfo.wrap.getBoundingClientRect();
          return { page, rects, pageWidth: wrapRect.width, pageHeight: wrapRect.height };
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
      if (!state.fileId || state.fileType !== 'pdf') {
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
        path: state.wsSourcePath || state.filePath || '',
        name: state.fileName || 'document.pdf',
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

      state.isLoading = true;
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
        state.isLoading = false;
        _setStreamBtn(false);
      });
    }

    // ─── Local structural watermark removal ───────────────────────────────────
    async pdfRemoveWatermark() {
      if (!state.fileId) { showToast('请先打开一个 PDF 文件', 'warning'); return; }
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
          body:    JSON.stringify({ file_id: state.fileId }),
        });
        if (barEl) barEl.style.width = '80%';
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.error || `HTTP ${res.status}`);
        }
        const blob = await res.blob();
        if (barEl) barEl.style.width = '100%';
        const url  = URL.createObjectURL(blob);
        const name = (state.fileName || 'watermark_removed.pdf').replace(/\.pdf$/i, '') + '_去水印.pdf';
        if (dlLink) { dlLink.href = url; dlLink.download = name; dlLink.style.display = ''; }
        const removed = res.headers.get('X-Koto-Removed-Count') || '?';
        const method  = res.headers.get('X-Koto-Method') || '';
        if (statusEl) statusEl.textContent = `去水印完成！共处理 ${removed} 处。`;
        if (resultEl) resultEl.textContent = method ? `检测方法：${method}` : '';
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

    serialize() { return null; } // PDF not directly editable

    applyToolCall(cmd) {
      // For AI annotation commands
      if (cmd && cmd.type === 'annotate' && Array.isArray(cmd.annotations)) {
        const needsTextLocation = cmd.annotations.some(a => a && !Array.isArray(a.rects));
        if (needsTextLocation) {
          this._applyAiAnnotationSuggestions(JSON.stringify({ annotations: cmd.annotations }));
          return;
        }
        cmd.annotations.forEach(a => this._annotations.push({
          ...a,
          id: Date.now() + '-' + Math.random().toString(36).slice(2),
          timestamp: Date.now(),
        }));
        this._renderedPgs.forEach(pg => this._renderAnnotationsOnPage(pg));
      }
    }

    destroy() {
      if (this._observer) { this._observer.disconnect(); this._observer = null; }
      document.removeEventListener('keydown', this._keyHandler);

      const c = $(this.containerId);
      if (c) {
        c.classList.remove('active');
        c.innerHTML = '';
        c.removeEventListener('mouseup', this._onMouseUp);
        c.removeEventListener('mousedown', this._onMouseDown);
        c.removeEventListener('mousemove', this._onMouseMove);
        c.removeEventListener('wheel', this._wheelHandler);
      }

      const outer = $('wa-pdf-editor');
      if (outer) outer.classList.remove('active');

      const strip = $('wa-pdf-thumbstrip');
      if (strip) strip.innerHTML = '';

      const searchBar = $('wa-pdf-search-bar');
      if (searchBar) searchBar.style.display = 'none';

      const annotBar = $('wa-pdf-annot-bar');
      if (annotBar) annotBar.style.display = 'none';

      // Hide annotation buttons in floating toolbar
      const annotBtns = document.querySelectorAll('.wa-pdf-annot-btn, .wa-pdf-annot-sep');
      annotBtns.forEach((el: HTMLElement) => {
        el.classList.add('wa-hidden');
        el.style.display = 'none';
      });
    }
  }
function _pdfActiveEditor(): any {
  return state && state.activeEditor ? state.activeEditor : null;
}

function _pdfDocumentForEditor(ed: any): any {
  return ed && (ed._pdfDoc || ed._pdf || null);
}

function _downloadPdfBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

async function _pdfPageMgrRenderThumb(ed: any, pageNum: number, canvas: HTMLCanvasElement): Promise<void> {
  try {
    const pdf = _pdfDocumentForEditor(ed);
    if (!pdf || !canvas) return;
    const page = await pdf.getPage(pageNum);
    const vp = page.getViewport({ scale: 0.3 });
    canvas.width = vp.width;
    canvas.height = vp.height;
    await page.render({ canvasContext: canvas.getContext('2d'), viewport: vp }).promise;
  } catch (e) { console.warn("[Koto]", e) }
}

function _setupPageMgrDrag(card: HTMLElement): void {
  card.addEventListener('dragstart', (event: DragEvent) => {
    if (!event.dataTransfer) return;
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', '');
    card.classList.add('dragging');
    (window as any)._pmgrDragSrc = card;
  });
  card.addEventListener('dragend', () => card.classList.remove('dragging'));
  card.addEventListener('dragover', (event: DragEvent) => {
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    card.classList.add('drag-over');
  });
  card.addEventListener('dragleave', () => card.classList.remove('drag-over'));
  card.addEventListener('drop', (event: DragEvent) => {
    event.preventDefault();
    card.classList.remove('drag-over');
    const src = (window as any)._pmgrDragSrc as HTMLElement | null;
    if (!src || src === card) return;
    const grid = card.parentNode;
    if (!grid) return;
    const cards = Array.from(grid.children);
    const srcIdx = cards.indexOf(src);
    const dstIdx = cards.indexOf(card);
    if (srcIdx < dstIdx) grid.insertBefore(src, card.nextSibling);
    else grid.insertBefore(src, card);
  });
}

function _pdfPageMgrBuild(ed: any): void {
  const grid = document.getElementById('wa-pdf-pagemgr-grid');
  const pdf = _pdfDocumentForEditor(ed);
  if (!grid || !pdf) return;
  grid.innerHTML = '';
  const totalPages = pdf.numPages || 0;
  for (let pageNum = 1; pageNum <= totalPages; pageNum += 1) {
    const card = document.createElement('div');
    card.className = 'wa-pmgr-card';
    card.draggable = true;
    card.dataset.origPage = String(pageNum);
    card.dataset.rotation = '0';
    card.innerHTML = `
      <input type="checkbox" class="wa-pmgr-check" title="选中此页">
      <div class="wa-pmgr-thumb"><canvas></canvas></div>
      <div class="wa-pmgr-rotation-badge"></div>
      <div class="wa-pmgr-label">第 ${pageNum} 页</div>
      <div class="wa-pmgr-controls">
        <div class="wa-pmgr-ctrl-btn" title="顺时针旋转 90°" data-wa-pdf-page-action="rotate" data-delta="90">↻</div>
        <div class="wa-pmgr-ctrl-btn" title="逆时针旋转 90°" data-wa-pdf-page-action="rotate" data-delta="-90">↺</div>
        <div class="wa-pmgr-ctrl-btn" title="删除此页" data-wa-pdf-page-action="delete">✕</div>
      </div>`;
    card.querySelectorAll<HTMLElement>('[data-wa-pdf-page-action]').forEach((control) => {
      control.addEventListener('click', () => {
        const action = control.dataset.waPdfPageAction;
        if (action === 'rotate') pdfPageMgrRotate(card, Number(control.dataset.delta) || 0);
        if (action === 'delete') pdfPageMgrDelete(card);
      });
    });
    const checkbox = card.querySelector('.wa-pmgr-check') as HTMLInputElement | null;
    if (checkbox) checkbox.addEventListener('change', () => card.classList.toggle('selected', checkbox.checked));
    _setupPageMgrDrag(card);
    grid.appendChild(card);
    _pdfPageMgrRenderThumb(ed, pageNum, card.querySelector('canvas') as HTMLCanvasElement);
  }
}

function _pdfPageMgrCards(selector: string): HTMLElement[] {
  const grid = document.getElementById('wa-pdf-pagemgr-grid');
  return grid ? Array.from(grid.querySelectorAll(selector)) as HTMLElement[] : [];
}

const pdfZoom = (value: string | number) => {
  const ed = _pdfActiveEditor();
  const pct = parseInt(String(value), 10);
  if (ed && typeof ed.setZoom === 'function' && Number.isFinite(pct)) ed.setZoom(pct);
};
const pdfSidebarTab = (btn: HTMLElement) => {
  const ed = _pdfActiveEditor();
  if (ed && typeof ed.sidebarTab === 'function') ed.sidebarTab(btn);
};
const pdfToggleSidebar = () => {
  const ed = _pdfActiveEditor();
  if (ed && typeof ed.toggleSidebar === 'function') ed.toggleSidebar();
};
const pdfAnnotMode = (mode: string) => {
  const ed = _pdfActiveEditor();
  if (ed && typeof ed.setAnnotMode === 'function') ed.setAnnotMode(mode);
};
const pdfAnnotColor = (hex: string) => {
  const ed = _pdfActiveEditor();
  if (ed && typeof ed.setAnnotColor === 'function') ed.setAnnotColor(hex);
};
const pdfAnnotOpen = () => {
  const ed = _pdfActiveEditor();
  if (ed && typeof ed.annotOpen === 'function') ed.annotOpen();
};
const pdfAnnotClose = () => {
  const ed = _pdfActiveEditor();
  if (ed && typeof ed.annotClose === 'function') ed.annotClose();
};
const pdfAnnotateSelection = (type: string) => {
  const ed = _pdfActiveEditor();
  if (ed && typeof ed.annotateSelection === 'function') ed.annotateSelection(type);
};
const pdfSaveAnnotations = () => {
  const ed = _pdfActiveEditor();
  if (ed && typeof ed.saveAnnotations === 'function') ed.saveAnnotations();
};
const pdfAIAnnotate = () => {
  const ed = _pdfActiveEditor();
  if (ed && typeof ed.aiAnnotate === 'function') ed.aiAnnotate();
};
const pdfLineWidth = (width: string | number) => {
  const ed = _pdfActiveEditor();
  if (ed) ed._annotLineWidth = parseFloat(String(width)) || 2;
};
const pdfRemoveWatermark = () => {
  const ed = _pdfActiveEditor();
  if (ed && typeof ed.pdfRemoveWatermark === 'function') ed.pdfRemoveWatermark();
};
const pdfWatermarkClose = () => {
  const overlay = document.getElementById('wa-pdf-watermark-overlay');
  if (overlay) {
    overlay.style.display = 'none';
    overlay.classList.remove('open');
  }
};
const pdfSearchOpen = () => {
  const ed = _pdfActiveEditor();
  if (ed && typeof ed.searchOpen === 'function') ed.searchOpen();
};
const pdfSearchClose = () => {
  const ed = _pdfActiveEditor();
  if (ed && typeof ed.searchClose === 'function') ed.searchClose();
};
const pdfSearchInput = (value: string) => {
  const ed = _pdfActiveEditor();
  if (ed && typeof ed.searchInput === 'function') ed.searchInput(value);
};
const pdfSearchKeydown = (event: KeyboardEvent) => {
  const ed = _pdfActiveEditor();
  if (ed && typeof ed.searchKeydown === 'function') ed.searchKeydown(event);
};
const pdfSearchNext = () => {
  const ed = _pdfActiveEditor();
  if (ed && typeof ed.searchNext === 'function') ed.searchNext();
};
const pdfSearchPrev = () => {
  const ed = _pdfActiveEditor();
  if (ed && typeof ed.searchPrev === 'function') ed.searchPrev();
};
const pdfPageMgrOpen = () => {
  const ed = _pdfActiveEditor();
  if (!ed || !_pdfDocumentForEditor(ed)) {
    showToast('请先打开一个 PDF 文件', 'warning');
    return;
  }
  const mgr = document.getElementById('wa-pdf-pagemgr');
  if (!mgr) return;
  mgr.style.display = 'flex';
  _pdfPageMgrBuild(ed);
};
const pdfPageMgrClose = () => {
  const mgr = document.getElementById('wa-pdf-pagemgr');
  if (mgr) mgr.style.display = 'none';
};
const pdfPageMgrApply = async () => {
  if (!state.fileId) return;
  const pages = _pdfPageMgrCards('.wa-pmgr-card:not(.deleted)').map((card) => ({
    orig_page: parseInt(card.dataset.origPage || '0', 10),
    rotation: parseInt(card.dataset.rotation || '0', 10),
  })).filter((page) => page.orig_page > 0);
  showToast('正在应用页面更改…', 'info', 2000);
  try {
    const response = await _csrfFetch('/api/v1/workspace/pdf/page_ops', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_id: state.fileId, pages }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || response.statusText);
    }
    _downloadPdfBlob(await response.blob(), state.fileName || 'modified.pdf');
    pdfPageMgrClose();
    showToast('页面更改已导出', 'success');
  } catch (error: any) {
    showToast('操作失败: ' + (error && error.message ? error.message : error), 'error');
  }
};
const pdfPageMgrExport = async () => {
  if (!state.fileId) return;
  const pages = _pdfPageMgrCards('.wa-pmgr-card.selected:not(.deleted)').map((card) => ({
    orig_page: parseInt(card.dataset.origPage || '0', 10),
    rotation: parseInt(card.dataset.rotation || '0', 10),
  })).filter((page) => page.orig_page > 0);
  if (!pages.length) {
    showToast('请先勾选要导出的页面', 'warning');
    return;
  }
  showToast('正在导出选中页面…', 'info', 2000);
  try {
    const response = await _csrfFetch('/api/v1/workspace/pdf/page_ops', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_id: state.fileId, pages }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || response.statusText);
    }
    const base = (state.fileName || 'export.pdf').replace(/\.pdf$/i, '');
    _downloadPdfBlob(await response.blob(), base + '_选中页.pdf');
    showToast('导出完成', 'success');
  } catch (error: any) {
    showToast('导出失败: ' + (error && error.message ? error.message : error), 'error');
  }
};
const pdfPageMgrRotate = (card: HTMLElement, delta: number) => {
  if (!card) return;
  const current = parseInt(card.dataset.rotation || '0', 10);
  const next = ((current + delta) % 360 + 360) % 360;
  card.dataset.rotation = String(next);
  const badge = card.querySelector('.wa-pmgr-rotation-badge') as HTMLElement | null;
  if (badge) {
    badge.style.display = next !== 0 ? 'block' : 'none';
    badge.textContent = next + '°';
  }
  const canvas = card.querySelector('canvas') as HTMLElement | null;
  if (canvas) canvas.style.transform = `rotate(${next}deg)`;
};
const pdfPageMgrDelete = (card: HTMLElement) => {
  if (!card) return;
  card.classList.toggle('deleted');
  const label = card.querySelector('.wa-pmgr-label') as HTMLElement | null;
  if (label) label.textContent = card.classList.contains('deleted') ? '已删除' : `第 ${card.dataset.origPage} 页`;
};
const pdfConvertMenu = (btn: HTMLElement) => {
  const menu = document.getElementById('wa-pdf-convert-menu');
  if (!menu) return;
  const visible = menu.style.display !== 'none';
  menu.style.display = visible ? 'none' : 'block';
  if (!visible) {
    const close = (event: MouseEvent) => {
      const target = event.target as Node | null;
      if (!target || (!menu.contains(target) && target !== btn)) {
        menu.style.display = 'none';
        document.removeEventListener('mousedown', close);
      }
    };
    document.addEventListener('mousedown', close);
  }
};
const pdfConvert = async (targetFormat: string) => {
  const menu = document.getElementById('wa-pdf-convert-menu');
  if (menu) menu.style.display = 'none';
  if (!state.fileId) {
    showToast('请先打开一个 PDF 文件', 'warning');
    return;
  }
  const labels: Record<string, string> = { docx: 'Word (.docx)', xlsx: 'Excel (.xlsx)', pptx: 'PowerPoint (.pptx)' };
  const label = labels[targetFormat] || targetFormat;
  showToast(`正在转换为 ${label}…`, 'info', 3000);
  try {
    const response = await _csrfFetch('/api/v1/workspace/pdf/convert', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_id: state.fileId, target_format: targetFormat, filename: state.fileName }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || response.statusText);
    }
    const warning = response.headers.get('X-Koto-Warning');
    const base = (state.fileName || 'converted').replace(/\.pdf$/i, '');
    _downloadPdfBlob(await response.blob(), `${base}.${targetFormat}`);
    showToast(warning ? `转换完成 - ${warning}` : `已转换为 ${label}`, warning ? 'warning' : 'success', 5000);
  } catch (error: any) {
    showToast('格式转换失败: ' + (error && error.message ? error.message : error), 'error');
  }
};

function _pdfDragNote(event: MouseEvent, popup: HTMLElement): void {
  const startX = event.clientX, startY = event.clientY;
  const startLeft = parseFloat(popup.style.left), startTop = parseFloat(popup.style.top);
  const onMove = (e) => {
    popup.style.left = (startLeft + e.clientX - startX) + 'px';
    popup.style.top = (startTop + e.clientY - startY) + 'px';
  };
  const onUp = () => {
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
  };
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
}

publishWorkspaceApi({
  pdfZoom,
  pdfSidebarTab,
  pdfToggleSidebar,
  pdfAnnotMode,
  pdfAnnotColor,
  pdfAnnotOpen,
  pdfAnnotClose,
  pdfAnnotateSelection,
  pdfSaveAnnotations,
  pdfAIAnnotate,
  pdfLineWidth,
  pdfRemoveWatermark,
  pdfWatermarkClose,
  pdfSearchOpen,
  pdfSearchClose,
  pdfSearchInput,
  pdfSearchKeydown,
  pdfSearchNext,
  pdfSearchPrev,
  pdfPageMgrOpen,
  pdfPageMgrClose,
  pdfPageMgrApply,
  pdfPageMgrExport,
  _pdfPageMgrRotate: pdfPageMgrRotate,
  _pdfPageMgrDelete: pdfPageMgrDelete,
  pdfConvertMenu,
  pdfConvert,
  _pdfDragNote,
});
