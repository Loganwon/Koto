// @ts-nocheck
import {
  getActivePdfEditor as _pdfActiveEditor,
  getPdfDocument as _pdfDocumentForEditor,
  getPdfSessionSnapshot as _pdfState,
  releasePdfSession,
} from './pdf-session-runtime';
import { downloadPdfBlob as _downloadPdfBlob } from './pdf-download';
import { getFeatureRegistry } from '../shared/feature-registry';

const workspaceApi = getFeatureRegistry();
const $ = (id: string): any => document.getElementById(id);
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

import { KotoPdfViewerPart3 } from './pdf-viewer-part-3';

export class KotoPdfViewerPart4 extends KotoPdfViewerPart3 { // PDF not directly editable

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
      this._renderSurface?.dispose();
      this._renderSurface = null;
      this._beginRenderGeneration();
      this._releaseAllPageSurfaces();
      const pdfDocument = this._pdfDoc;
      this._pdfDoc = null;
      try { pdfDocument?.destroy?.(); } catch (_) {}
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
      releasePdfSession(this._session);
    }
}
