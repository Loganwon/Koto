// @ts-nocheck
import {
  getActivePdfEditor as _pdfActiveEditor,
  getPdfDocument as _pdfDocumentForEditor,
  getPdfSessionSnapshot as _pdfState,
} from './pdf-session-runtime';
import { downloadPdfBlob as _downloadPdfBlob } from './pdf-download';
import { getFeatureRegistry } from '../shared/feature-registry';
import {
  createRenderSurfaceController,
  getRenderScaleSnapshot,
  syncCanvasBackingStore,
} from '../shared/render-surface';

const workspaceApi = getFeatureRegistry();
const $ = (id: string): any => document.getElementById(id);
const _csrfFetch = (url: string, opts?: RequestInit): Promise<Response> => workspaceApi._csrfFetch(url, opts);
const _updatePdfZoomUI = (pct: number): void => workspaceApi._updatePdfZoomUI?.(pct);
const _hideWelcome = (): void => workspaceApi._hideWelcome?.();
const _setStreamBtn = (loading: boolean): void => workspaceApi._setStreamBtn?.(loading);
const _initWorkspaceAiRuntimes = (): void => workspaceApi._initWorkspaceAiRuntimes?.();
const PDF_VISIBLE_PAGE_BUDGET = 8;
const PDF_CANVAS_PIXEL_BUDGET = 48_000_000;
const PDF_THUMB_CACHE_BUDGET = 64;
const PDF_PAGE_RENDER_CONCURRENCY = 2;
const PDF_THUMB_RENDER_CONCURRENCY = 3;

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


export class KotoPdfViewerPart1 {

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
      this._installRenderSurface();

      // Load existing annotations if any are embedded in the PDF
      this._loadAnnotationsFromServer();
    }

    _installRenderSurface() {
      const container = $(this.containerId);
      if (!container) return;
      const snapshot = getRenderScaleSnapshot(container);
      this._rememberRenderSurface(snapshot);
      if (this._renderSurface) return;
      this._renderSurface = createRenderSurfaceController(container, (nextSnapshot) => {
        const logicalWidth = Math.round(nextSnapshot.logicalSize.width * 100) / 100;
        const densityKey = `${nextSnapshot.backingScale.x.toFixed(3)}:${nextSnapshot.backingScale.y.toFixed(3)}`;
        if (logicalWidth === this._surfaceLogicalWidth && densityKey === this._surfaceDensityKey) return;
        this._rememberRenderSurface(nextSnapshot);
        if (this._pdfUrl) void this._doRender();
      });
    }

    _rememberRenderSurface(snapshot) {
      this._surfaceLogicalWidth = Math.round(snapshot.logicalSize.width * 100) / 100;
      this._surfaceDensityKey = `${snapshot.backingScale.x.toFixed(3)}:${snapshot.backingScale.y.toFixed(3)}`;
    }

    // ─── _doRender ───────────────────────────────────────────────────────────
    async _doRender() {
      const pdfUrl = this._pdfUrl;
      const c = $(this.containerId);
      this._beginRenderGeneration();
      const generation = this._renderGeneration;
      this._releaseAllPageSurfaces();
      c.innerHTML = '';

      const pdfjsLib = _pdfRuntime();
      if (!pdfjsLib) {
        c.innerHTML = '<div style="color:var(--danger);padding:16px">PDF.js 加载失败</div>';
        return;
      }

      try {
        if (!this._pdfDoc || this._pdfDoc._url !== pdfUrl) {
          const staleDocument = this._pdfDoc;
          this._pdfDoc = null;
          try { staleDocument?.destroy?.(); } catch (_) {}

          const loadingTask = pdfjsLib.getDocument(pdfUrl);
          this._loadingTask = loadingTask;
          try {
            const loadedDocument = await loadingTask.promise;
            if (generation !== this._renderGeneration) {
              try { loadedDocument?.destroy?.(); } catch (_) {}
              return;
            }
            this._pdfDoc = loadedDocument;
            this._pdfDoc._url = pdfUrl;
          } finally {
            if (this._loadingTask === loadingTask) this._loadingTask = null;
          }
        }
        const pdf = this._pdfDoc;
        this._pageCount = pdf.numPages;

        // Containers for deferred render
        this._renderedPgs.clear();
        this._textContent = {};

        // Estimate page size for placeholders (use page 1)
        const firstPage = await pdf.getPage(1);
        if (generation !== this._renderGeneration) return;
        const baseVP = firstPage.getViewport({ scale: 1 });
        const surfaceSnapshot = getRenderScaleSnapshot(c);
        this._rememberRenderSurface(surfaceSnapshot);
        const containerW = Math.max(240, (surfaceSnapshot.logicalSize.width || 800) - 32);
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
                this._touchPage(pg);
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
        if (generation !== this._renderGeneration
            || e?.name === 'RenderingCancelledException'
            || e?.name === 'AbortException') return;
        console.error('[KotoPdfViewer] render error:', e);
        c.innerHTML = `<div style="color:var(--danger);padding:16px">PDF 渲染报错: ${e.message}</div>`;
      }
    }

    _beginRenderGeneration() {
      this._renderGeneration += 1;
      const loadingTask = this._loadingTask;
      this._loadingTask = null;
      try { loadingTask?.destroy?.(); } catch (_) {}
      this._cancelRenderTasks();
      this._activePageRenders = 0;
      this._activeThumbRenders = 0;
      this._pageRenderQueue = [];
      this._thumbRenderQueue = [];
      this._pendingThumbs.clear();
      this._thumbObserver?.disconnect();
      this._thumbObserver = null;
      Object.values(this._thumbCanvas || {}).forEach(canvas => this._releaseCanvas(canvas));
      this._renderedThumbs.clear();
      this._thumbAccess.clear();
      this._thumbCanvas = {};
    }

    _cancelRenderTasks(prefix = '') {
      for (const [key, entry] of this._renderTasks.entries()) {
        if (prefix && !String(key).startsWith(prefix)) continue;
        try { entry.task?.cancel?.(); } catch (_) {}
        this._renderTasks.delete(key);
      }
    }

    _releaseCanvas(canvas) {
      if (!canvas) return;
      // Setting both dimensions releases the browser's GPU/bitmap allocation.
      canvas.width = 1;
      canvas.height = 1;
      canvas.style.background = '#f0f0f0';
    }

    _releasePageSurface(pageNum) {
      const key = `page:${pageNum}`;
      const active = this._renderTasks.get(key);
      try { active?.task?.cancel?.(); } catch (_) {}
      this._renderTasks.delete(key);
      const wrap = document.getElementById(`pdf-page-${pageNum}`);
      if (wrap) {
        this._releaseCanvas(wrap.querySelector('canvas'));
        wrap.querySelector('.wa-pdf-text-layer')?.remove();
        wrap.querySelector('.wa-pdf-annot-layer')?.remove();
      }
      this._renderedPgs.delete(pageNum);
      this._pageAccess.delete(pageNum);
      delete this._textContent[pageNum];
    }

    _releaseAllPageSurfaces() {
      [...this._renderedPgs].forEach(pageNum => this._releasePageSurface(pageNum));
      this._renderedPgs.clear();
      this._pageAccess.clear();
    }

    _touchPage(pageNum) {
      this._pageAccess.set(pageNum, performance.now());
    }

    _visiblePageNumbers() {
      const container = $(this.containerId);
      if (!container) return new Set();
      const rootRect = container.getBoundingClientRect();
      const visible = new Set();
      container.querySelectorAll('.wa-pdf-page-wrap').forEach((wrap) => {
        const rect = wrap.getBoundingClientRect();
        if (rect.bottom >= rootRect.top - 300 && rect.top <= rootRect.bottom + 300) {
          visible.add(parseInt(wrap.dataset.page, 10));
        }
      });
      return visible;
    }

    _renderedCanvasPixels() {
      let pixels = 0;
      this._renderedPgs.forEach((pageNum) => {
        const canvas = document.querySelector(`#pdf-page-${pageNum} canvas`);
        if (canvas) pixels += Number(canvas.width || 0) * Number(canvas.height || 0);
      });
      return pixels;
    }

    _enforcePageBudget(protectedPage = 0) {
      const visible = this._visiblePageNumbers();
      if (protectedPage) visible.add(protectedPage);
      const candidates = [...this._renderedPgs]
        .filter(pageNum => !visible.has(pageNum))
        .sort((a, b) => (this._pageAccess.get(a) || 0) - (this._pageAccess.get(b) || 0));
      while (
        candidates.length
        && (this._renderedPgs.size > PDF_VISIBLE_PAGE_BUDGET
          || this._renderedCanvasPixels() > PDF_CANVAS_PIXEL_BUDGET)
      ) {
        this._releasePageSurface(candidates.shift());
      }
    }

    _scheduleVisiblePageRenderPasses() {
      this._renderVisiblePagesNow();
      requestAnimationFrame(() => this._renderVisiblePagesNow());
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
      const taskKey = `page:${pageNum}`;
      if (this._renderedPgs.has(pageNum) || this._renderTasks.has(taskKey) || !this._pdfDoc) return;
      if (this._activePageRenders >= PDF_PAGE_RENDER_CONCURRENCY) {
        if (!this._pageRenderQueue.includes(pageNum)) this._pageRenderQueue.push(pageNum);
        return;
      }
      const generation = this._renderGeneration;
      const wrap = document.getElementById(`pdf-page-${pageNum}`);
      if (!wrap) return;
      this._activePageRenders += 1;
      this._renderedPgs.add(pageNum);
      this._touchPage(pageNum);

      try {
        const pdf = this._pdfDoc;
        const page = await pdf.getPage(pageNum);
        if (generation !== this._renderGeneration || !wrap.isConnected) {
          this._renderedPgs.delete(pageNum);
          return;
        }
        const baseViewport = page.getViewport({ scale: 1 });
        const containerW = this._containerW || 800;
        const fitScale = (containerW / baseViewport.width) * this._scale;
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
        const backingStore = syncCanvasBackingStore(canvas, cssW, cssH, wrap);
        const renderViewport = page.getViewport({ scale: fitScale * backingStore.scaleX });
        const context = canvas.getContext('2d');
        canvas.style.background = '';

        if (!wrap.contains(canvas)) wrap.insertBefore(canvas, wrap.firstChild);

        const renderTask = page.render({ canvasContext: context, viewport: renderViewport });
        this._renderTasks.set(taskKey, { task: renderTask, generation });
        await renderTask.promise;
        if (generation !== this._renderGeneration || !wrap.isConnected) {
          this._renderedPgs.delete(pageNum);
          return;
        }

        // Add text layer for selection and search
        this._addTextLayer(wrap, page, textViewport, cssW, cssH);

        // Add annotation SVG overlay
        this._addAnnotLayer(wrap, pageNum, cssW, cssH);

        // Re-render annotations for this page
        this._renderAnnotationsOnPage(pageNum);

        // Re-render search highlights
        if (this._searchQuery) this._renderSearchOnPage(pageNum);

        // Extract text for search index (background)
        this._extractPageText(page, pageNum, generation);

        // Update thumbnail if needed (draw on existing thumb canvas)
        this._drawThumbForPage(pageNum);
        this._enforcePageBudget(pageNum);

      } catch (e) {
        this._renderedPgs.delete(pageNum);
        if (e?.name !== 'RenderingCancelledException') {
          console.warn(`[KotoPdfViewer] page ${pageNum} render error:`, e);
        }
      } finally {
        const active = this._renderTasks.get(taskKey);
        if (active?.generation === generation) this._renderTasks.delete(taskKey);
        if (generation === this._renderGeneration) {
          this._activePageRenders = Math.max(0, this._activePageRenders - 1);
          const nextPage = this._pageRenderQueue.shift();
          if (nextPage) void this._renderPage(nextPage);
        }
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
    async _extractPageText(page, pageNum, generation = this._renderGeneration) {
      if (this._textContent[pageNum]) return;
      try {
        const tc = await page.getTextContent();
        if (generation !== this._renderGeneration || !this._renderedPgs.has(pageNum)) return;
        this._textContent[pageNum] = tc.items.map(it => it.str).join(' ');
      } catch (e) { console.warn("[Koto]", e) }
    }

    // ─── _buildThumbs ────────────────────────────────────────────────────────
    async _buildThumbs() {
      const strip = $('wa-pdf-thumbstrip');
      if (!strip) return;
      this._thumbObserver?.disconnect();
      this._thumbObserver = null;
      this._cancelRenderTasks('thumb:');
      this._renderedThumbs.clear();
      this._thumbAccess.clear();
      this._thumbCanvas = {};
      strip.innerHTML = '';

      const pdf = this._pdfDoc;
      if (!pdf) return;

      for (let i = 1; i <= pdf.numPages; i++) {
        const wrap = document.createElement('div');
        wrap.className = 'wa-pdf-thumb-wrap';
        wrap.dataset.page = i;

        const thumbDiv = document.createElement('div');
        thumbDiv.className = 'wa-pdf-thumb' + (i === 1 ? ' active' : '');
        thumbDiv.id = `pdf-thumb-${i}`;

        const canvas = document.createElement('canvas');
        canvas.style.display = 'block';
        canvas.style.width = '148px';
        canvas.style.height = `${Math.max(1, Math.round(148 * (this._baseAspect || 1.414)))}px`;
        canvas.width = 1;
        canvas.height = 1;
        thumbDiv.appendChild(canvas);
        this._thumbCanvas[i] = canvas;

        const idx = document.createElement('span');
        idx.className = 'wa-pdf-thumb-idx';
        idx.textContent = i;

        wrap.appendChild(thumbDiv);
        wrap.appendChild(idx);
        wrap.addEventListener('click', () => this._scrollToPage(i));
        strip.appendChild(wrap);
      }

      if (typeof IntersectionObserver !== 'undefined') {
        this._thumbObserver = new IntersectionObserver((entries) => {
          entries.forEach((entry) => {
            if (!entry.isIntersecting) return;
            const pageNum = parseInt(entry.target.dataset.page, 10);
            const canvas = this._thumbCanvas[pageNum];
            if (pageNum && canvas) void this._renderThumb(pageNum, canvas);
          });
        }, { root: strip, rootMargin: '300px 0px', threshold: 0 });
        strip.querySelectorAll('.wa-pdf-thumb-wrap').forEach(el => this._thumbObserver.observe(el));
      } else {
        for (let pageNum = 1; pageNum <= Math.min(pdf.numPages, 12); pageNum += 1) {
          void this._renderThumb(pageNum, this._thumbCanvas[pageNum]);
        }
      }
    }

    async _renderThumb(pageNum, canvas) {
      const taskKey = `thumb:${pageNum}`;
      if (!canvas || this._renderedThumbs.has(pageNum) || this._renderTasks.has(taskKey) || this._pendingThumbs.has(pageNum)) return;
      if (this._activeThumbRenders >= PDF_THUMB_RENDER_CONCURRENCY) {
        if (!this._thumbRenderQueue.some(item => item.pageNum === pageNum)) {
          this._thumbRenderQueue.push({ pageNum, canvas });
        }
        return;
      }
      const generation = this._renderGeneration;
      this._activeThumbRenders += 1;
      this._pendingThumbs.add(pageNum);
      this._thumbAccess.set(pageNum, performance.now());
      try {
        const page = await this._pdfDoc.getPage(pageNum);
        if (generation !== this._renderGeneration || !canvas.isConnected) return;
        const baseVP = page.getViewport({ scale: 1 });
        const THUMB_W = 148;
        const scale = THUMB_W / baseVP.width;
        const cssViewport = page.getViewport({ scale });
        const cssW = Math.max(1, Math.round(cssViewport.width));
        const cssH = Math.max(1, Math.round(cssViewport.height));
        const backingStore = syncCanvasBackingStore(canvas, cssW, cssH, canvas.parentElement || canvas);
        const renderViewport = page.getViewport({ scale: scale * backingStore.scaleX });
        const renderTask = page.render({ canvasContext: canvas.getContext('2d'), viewport: renderViewport });
        this._renderTasks.set(taskKey, { task: renderTask, generation });
        await renderTask.promise;
        if (generation !== this._renderGeneration || !canvas.isConnected) return;
        this._renderedThumbs.add(pageNum);
        this._enforceThumbBudget(pageNum);
      } catch (e) {
        if (e?.name !== 'RenderingCancelledException') console.warn('[Koto]', e);
      } finally {
        const active = this._renderTasks.get(taskKey);
        if (active?.generation === generation) this._renderTasks.delete(taskKey);
        if (generation === this._renderGeneration) {
          this._pendingThumbs.delete(pageNum);
          this._activeThumbRenders = Math.max(0, this._activeThumbRenders - 1);
          const nextThumb = this._thumbRenderQueue.shift();
          if (nextThumb) void this._renderThumb(nextThumb.pageNum, nextThumb.canvas);
        }
      }
    }

    _enforceThumbBudget(protectedPage = 0) {
      const strip = $('wa-pdf-thumbstrip');
      const visible = new Set([protectedPage]);
      const stripRect = strip?.getBoundingClientRect();
      strip?.querySelectorAll('.wa-pdf-thumb-wrap').forEach((wrap) => {
        const rect = wrap.getBoundingClientRect();
        if (stripRect && rect.bottom >= stripRect.top - 300 && rect.top <= stripRect.bottom + 300) {
          visible.add(parseInt(wrap.dataset.page, 10));
        }
      });
      const candidates = [...this._renderedThumbs]
        .filter(pageNum => !visible.has(pageNum))
        .sort((a, b) => (this._thumbAccess.get(a) || 0) - (this._thumbAccess.get(b) || 0));
      while (this._renderedThumbs.size > PDF_THUMB_CACHE_BUDGET && candidates.length) {
        const pageNum = candidates.shift();
        this._releaseCanvas(this._thumbCanvas[pageNum]);
        this._renderedThumbs.delete(pageNum);
        this._thumbAccess.delete(pageNum);
      }
    }

    _drawThumbForPage(pageNum) {
      const thumbDiv = document.getElementById(`pdf-thumb-${pageNum}`);
      if (!thumbDiv) return;
      const canvas = thumbDiv.querySelector('canvas');
      if (!canvas) return;
      void this._renderThumb(pageNum, canvas);
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
        const canvas = thumb.querySelector('canvas');
        if (canvas) void this._renderThumb(pageNum, canvas);
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
      // A generation swap cancels stale PDF.js work and rebuilds placeholder
      // geometry before visible pages are scheduled again.
      if (this._pdfUrl) void this._doRender();
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
}
