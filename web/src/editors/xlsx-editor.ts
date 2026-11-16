/**
 * XlsxEditor - Univer spreadsheet editor wrapper
 */

import type { WorkspaceEditor } from './types';
import type { EditorSession } from './editor-session';
import { setLastSelectionText } from '../shared/selection-runtime';
import { getFeatureRegistry } from '../shared/feature-registry';
import {
  createRenderSurfaceController,
  syncNativeRenderSurface,
  type RenderSurfaceController,
} from '../shared/render-surface';

declare global {
  var KotoSheetsAPI: any;
}

function $(id: string): HTMLElement | null { return document.getElementById(id); }

function _xlsxSelectionPayload(): any {
  if (!window.KotoSheetsAPI || !window.KotoSheetsAPI.isReady()) return null;
  if (typeof window.KotoSheetsAPI.getSelectionPayload === 'function') {
    return window.KotoSheetsAPI.getSelectionPayload();
  }
  const text = typeof window.KotoSheetsAPI.getSelectionText === 'function'
    ? window.KotoSheetsAPI.getSelectionText()
    : '';
  return text ? {
    kind: 'xlsx-range',
    tsv: text,
    aiText: `[当前选中表格数据]:\n${text}\n`,
    previewText: '选中表格区域',
  } : null;
}

function _syncXlsxSelectionContext(payload: any, session: EditorSession): void {
  const api = getFeatureRegistry() || {};
  if (payload && payload.aiText) {
    setLastSelectionText(payload.aiText);
    if (typeof api._pinSelectionChip === 'function') {
      api._pinSelectionChip({
        kind: payload.kind || 'xlsx-range',
        text: payload.aiText,
        previewText: payload.previewText || '选中表格区域',
        sourceType: 'xlsx',
        sheetName: payload.sheetName || '',
        rangeA1: payload.rangeA1 || '',
        rows: payload.rows || 0,
        cols: payload.cols || 0,
      });
    }
    return;
  }
  const pinned = session.getPinnedSelection();
  if ((!pinned || String(pinned.sourceType || '').toLowerCase() === 'xlsx') && typeof api.clearSelection === 'function') {
    api.clearSelection();
  }
}

export class XlsxEditor implements WorkspaceEditor {
  containerId: string;
  _containerId: string;
  _api: any;
  _images: Array<{ src: string; x: number; y: number; w: number; h: number }>;
  _viewportEl: HTMLElement | null;
  _sheetEl: HTMLElement | null;
  _renderSurface: RenderSurfaceController | null;
  _session: EditorSession;

  constructor(session: EditorSession) {
    this._session = session;
    this.containerId = 'wa-xlsx-editor';
    this._containerId = 'wa-xlsx-sheet';
    this._api = null;
    this._images = [];
    this._viewportEl = null;
    this._sheetEl = null;
    this._renderSurface = null;
    const wrapper = $(this.containerId);
    if (wrapper) wrapper.classList.add('active');
  }

  render(workbookData: any) {
    this._teardownLayoutSync();
    if (this._api) {
      try { window.KotoSheetsAPI.dispose(); } catch (e) {}
      this._api = null;
    }

    const wrapper = $(this.containerId);
    if (!wrapper) return;
    wrapper.innerHTML = '';

    const viewportEl = document.createElement('div');
    viewportEl.id = 'wa-xlsx-viewport';
    const sheetEl = document.createElement('div');
    sheetEl.id = this._containerId;
    sheetEl.style.cssText = 'position:absolute;left:0;top:0;transform-origin:top left;';
    viewportEl.appendChild(sheetEl);
    wrapper.appendChild(viewportEl);
    this._installLayoutSync(viewportEl, sheetEl);
    this._applyLayoutScale();

    const mountSheets = () => {
      if (!window.KotoSheetsAPI) {
        sheetEl.innerHTML = '<div style="padding:24px;color:#e74c3c;font-size:13px;">Univer Sheets 模块未就绪，请刷新页面重试</div>';
        return;
      }

      try {
        this._api = window.KotoSheetsAPI.create(sheetEl, workbookData);
        // '[XlsxEditor] Univer Sheets 挂载成功');
        // Univer renders Canvas at device-pixel density. Keep its runtime in an
        // unscaled inner coordinate space so body zoom never stretches those
        // pixels; the outer viewport owns clipping and workspace dimensions.
        this.refreshLayout();

        window.KotoSheetsAPI.onSelectionChange(() => {
          _syncXlsxSelectionContext(_xlsxSelectionPayload(), this._session);
        });
        if (typeof window.KotoSheetsAPI.onCellDataChange === 'function') {
          window.KotoSheetsAPI.onCellDataChange(() => {
            _syncXlsxSelectionContext(_xlsxSelectionPayload(), this._session);
            const api = getFeatureRegistry() || {};
            if (typeof api.scheduleAutoSave === 'function') api.scheduleAutoSave();
          });
        }
      } catch (err: any) {
        console.error('[XlsxEditor] Univer Sheets 初始化失败', err);
        sheetEl.innerHTML = `<div style="padding:24px;color:#e74c3c;font-size:13px;">表格引擎加载失败: ${err.message}</div>`;
      }
    };

    if (wrapper.offsetWidth > 0 && wrapper.offsetHeight > 0) {
      mountSheets();
    } else {
      requestAnimationFrame(() => {
        if (wrapper.offsetWidth > 0 && wrapper.offsetHeight > 0) mountSheets();
        else requestAnimationFrame(mountSheets);
      });
    }
  }

  _installLayoutSync(viewportEl: HTMLElement, sheetEl: HTMLElement): void {
    this._viewportEl = viewportEl;
    this._sheetEl = sheetEl;
    this._renderSurface = createRenderSurfaceController(viewportEl, () => {
      this._applyLayoutScale();
    });
  }

  _applyLayoutScale(): void {
    const sheetEl = this._sheetEl;
    if (!sheetEl || !sheetEl.isConnected) return;
    syncNativeRenderSurface(sheetEl);
    // Chromium resolves percentage sizes through the element's own CSS zoom.
    // 100% already expands the logical box enough to fill the painted parent;
    // multiplying by UI zoom again would produce a zoom² overflow.
    sheetEl.style.setProperty('width', '100%', 'important');
    sheetEl.style.setProperty('height', '100%', 'important');
  }

  refreshLayout(): void {
    if (this._renderSurface) this._renderSurface.request('manual');
    else this._applyLayoutScale();
  }

  _teardownLayoutSync(): void {
    this._renderSurface?.dispose();
    this._renderSurface = null;
    this._viewportEl = null;
    this._sheetEl = null;
  }

  getContent(): string {
    const payload = this.getSelectionPayload();
    if (payload && String(payload.aiText || '').trim()) return payload.aiText;
    return '[当前表格未选中区域，请提示用户框选数据]';
  }

  getSelectionPayload(): any {
    const payload = _xlsxSelectionPayload();
    if (!payload) return null;
    return Object.assign({ sourceType: 'xlsx' }, payload);
  }

  getCSV(): string {
    if (!window.KotoSheetsAPI || !window.KotoSheetsAPI.isReady()) return '';
    return window.KotoSheetsAPI.getActiveSheetCSV();
  }

  serialize(): { snapshot: any; _images: any[] } {
    const snapshot = (window.KotoSheetsAPI && window.KotoSheetsAPI.isReady())
      ? window.KotoSheetsAPI.getSnapshot()
      : null;
    return { snapshot, _images: this._images };
  }

  applyToolCall(cmd: any) {
    if (!window.KotoSheetsAPI || !window.KotoSheetsAPI.isReady()) return;
    if (cmd.type === 'set_cell') {
      window.KotoSheetsAPI.setCellValue(cmd.r, cmd.c, cmd.value);
      getFeatureRegistry().showToast(`AI 已更新单元格 (${cmd.r}, ${cmd.c})`, 'success');
      getFeatureRegistry().scheduleAutoSave();
    } else if (cmd.type === 'set_cells' && Array.isArray(cmd.cells)) {
      cmd.cells.forEach((cell: any) => window.KotoSheetsAPI.setCellValue(cell.r, cell.c, cell.value));
      getFeatureRegistry().showToast(`AI 已批量更新 ${cmd.cells.length} 个单元格`, 'success');
      getFeatureRegistry().scheduleAutoSave();
    }
  }

  destroy() {
    this._teardownLayoutSync();
    if (window.KotoSheetsAPI) {
      try { window.KotoSheetsAPI.dispose(); } catch (e) {}
    }
    this._api = null;
    const wrapper = $(this.containerId);
    if (wrapper) {
      wrapper.classList.remove('active');
    }
  }
}
