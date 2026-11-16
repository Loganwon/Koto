// @ts-nocheck
import type { WorkspaceEditor } from './types';
import type { EditorSession } from './editor-session';
import {
  bindPdfSession,
  getActivePdfEditor as _pdfActiveEditor,
  getPdfDocument as _pdfDocumentForEditor,
  getPdfSessionSnapshot as _pdfState,
} from './pdf-session-runtime';
import { downloadPdfBlob as _downloadPdfBlob } from './pdf-download';
import { getFeatureRegistry, registerFeatures } from '../shared/feature-registry';
import { viewportDeltaToElement } from '../shared/ui-scale';
import { syncCanvasBackingStore } from '../shared/render-surface';

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

import { KotoPdfViewerPart4 } from './pdf-viewer-part-4';

export class KotoPdfViewer extends KotoPdfViewerPart4 implements WorkspaceEditor {
    constructor(session: EditorSession) {
      super();
      this._session      = session;
      bindPdfSession(session);
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
      this._thumbObserver = null;
      this._renderedPgs  = new Set();   // set of 1-based page nums that have been rendered
      this._renderTasks = new Map();
      this._loadingTask = null;
      this._renderGeneration = 0;
      this._activePageRenders = 0;
      this._activeThumbRenders = 0;
      this._pageRenderQueue = [];
      this._thumbRenderQueue = [];
      this._pendingThumbs = new Set();
      this._pageAccess = new Map();
      this._renderedThumbs = new Set();
      this._thumbAccess = new Map();
      this._textContent  = {};          // page → pdfjsLib textContent (for search)
      this._thumbCanvas  = {};          // page → small canvas element (thumbnails)
      this._renderSurface = null;
      this._surfaceLogicalWidth = 0;
      this._surfaceDensityKey = '';

      // Sidebar state
      this._sidebarPanel = 'thumbs';    // 'thumbs' | 'bookmarks'
      this._restoreAiPanelAfterAnnot = false;

      // Keyboard handler (Ctrl+F)
      this._keyHandler = (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
          if (this._session.snapshot().fileType === 'pdf') {
            e.preventDefault();
            this.searchOpen();
          }
        }
        if (e.key === 'Escape' && this._session.snapshot().fileType === 'pdf') {
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
}
async function _pdfPageMgrRenderThumb(ed: any, pageNum: number, canvas: HTMLCanvasElement): Promise<void> {
  try {
    const pdf = _pdfDocumentForEditor(ed);
    if (!pdf || !canvas) return;
    const page = await pdf.getPage(pageNum);
    const logicalViewport = page.getViewport({ scale: 0.3 });
    const logicalWidth = Math.max(1, Math.round(logicalViewport.width));
    const logicalHeight = Math.max(1, Math.round(logicalViewport.height));
    const backingStore = syncCanvasBackingStore(
      canvas,
      logicalWidth,
      logicalHeight,
      canvas.parentElement || canvas,
    );
    const renderViewport = page.getViewport({ scale: 0.3 * backingStore.scaleX });
    await page.render({ canvasContext: canvas.getContext('2d'), viewport: renderViewport }).promise;
  } catch (e) { console.warn("[Koto]", e) }
}

function _setupPageMgrDrag(card: HTMLElement): void {
  card.addEventListener('dragstart', (event: DragEvent) => {
    if (!event.dataTransfer) return;
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', '');
    card.classList.add('dragging');
    getFeatureRegistry()._pmgrDragSrc = card;
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
    const src = getFeatureRegistry()._pmgrDragSrc as HTMLElement | null;
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
  const runtime = _pdfState();
  if (!runtime.fileId) return;
  const pages = _pdfPageMgrCards('.wa-pmgr-card:not(.deleted)').map((card) => ({
    orig_page: parseInt(card.dataset.origPage || '0', 10),
    rotation: parseInt(card.dataset.rotation || '0', 10),
  })).filter((page) => page.orig_page > 0);
  showToast('正在应用页面更改…', 'info', 2000);
  try {
    const response = await _csrfFetch('/api/v1/workspace/pdf/page_ops', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_id: runtime.fileId, pages }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || response.statusText);
    }
    _downloadPdfBlob(await response.blob(), runtime.fileName || 'modified.pdf');
    pdfPageMgrClose();
    showToast('页面更改已导出', 'success');
  } catch (error: any) {
    showToast('操作失败: ' + (error && error.message ? error.message : error), 'error');
  }
};
const pdfPageMgrExport = async () => {
  const runtime = _pdfState();
  if (!runtime.fileId) return;
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
      body: JSON.stringify({ file_id: runtime.fileId, pages }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || response.statusText);
    }
    const base = (runtime.fileName || 'export.pdf').replace(/\.pdf$/i, '');
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
  const runtime = _pdfState();
  if (!runtime.fileId) {
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
      body: JSON.stringify({ file_id: runtime.fileId, target_format: targetFormat, filename: runtime.fileName }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || response.statusText);
    }
    const warning = response.headers.get('X-Koto-Warning');
    const base = (runtime.fileName || 'converted').replace(/\.pdf$/i, '');
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
    const coordinateHost = popup.parentElement || popup;
    const delta = viewportDeltaToElement(coordinateHost, e.clientX - startX, e.clientY - startY);
    popup.style.left = (startLeft + delta.x) + 'px';
    popup.style.top = (startTop + delta.y) + 'px';
  };
  const onUp = () => {
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
  };
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
}

registerFeatures({
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
