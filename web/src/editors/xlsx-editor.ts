/**
 * KotoXlsxEditor - Univer spreadsheet editor wrapper
 */

import type { WorkspaceEditor } from './types';

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

export class KotoXlsxEditor implements WorkspaceEditor {
  containerId: string;
  _containerId: string;
  _api: any;
  _images: Array<{ src: string; x: number; y: number; w: number; h: number }>;

  constructor() {
    this.containerId = 'wa-xlsx-editor';
    this._containerId = 'wa-xlsx-sheet';
    this._api = null;
    this._images = [];
    const wrapper = $(this.containerId);
    if (wrapper) wrapper.classList.add('active');
  }

  render(workbookData: any) {
    if (this._api) {
      try { window.KotoSheetsAPI.dispose(); } catch (e) {}
      this._api = null;
    }

    const wrapper = $(this.containerId);
    if (!wrapper) return;
    wrapper.innerHTML = '';

    const sheetEl = document.createElement('div');
    sheetEl.id = this._containerId;
    sheetEl.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;';
    wrapper.appendChild(sheetEl);

    const mountSheets = () => {
      if (!window.KotoSheetsAPI) {
        sheetEl.innerHTML = '<div style="padding:24px;color:#e74c3c;font-size:13px;">Univer Sheets 模块未就绪，请刷新页面重试</div>';
        return;
      }

      try {
        this._api = window.KotoSheetsAPI.create(sheetEl, workbookData);
        console.log('[KotoXlsxEditor] Univer Sheets 挂载成功');

        setTimeout(() => {
          const cssW = sheetEl.clientWidth;
          const bcrW = sheetEl.getBoundingClientRect().width;
          if (!cssW || !bcrW) return;
          const browserZoom = bcrW / cssW;

          console.log(`[KotoXlsxEditor] container CSS=${cssW} BCR=${bcrW.toFixed(1)} zoom=${browserZoom.toFixed(3)} DPR=${devicePixelRatio}`);

          if (Math.abs(browserZoom - 1) > 0.05) {
            console.log(`[KotoXlsxEditor] DPI counter-zoom: 1/${browserZoom.toFixed(3)}`);
            sheetEl.style.zoom = String(1 / browserZoom);
            sheetEl.style.width = (browserZoom * 100) + '%';
            sheetEl.style.height = (browserZoom * 100) + '%';
            sheetEl.dataset.dpiZoom = String(browserZoom);
            window.dispatchEvent(new Event('resize'));
          }
        }, 600);

        window.KotoSheetsAPI.onSelectionChange(() => {
          const payload = _xlsxSelectionPayload();
          if (payload && payload.aiText) {
            (window as any).lastSelectionText = payload.aiText;
            if (typeof (window as any)._pinSelectionChip === 'function') {
              (window as any)._pinSelectionChip({
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
          }
        });
      } catch (err: any) {
        console.error('[KotoXlsxEditor] Univer Sheets 初始化失败', err);
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
      (window as any).showToast(`AI 已更新单元格 (${cmd.r}, ${cmd.c})`, 'success');
      (window as any).WA.scheduleAutoSave();
    } else if (cmd.type === 'set_cells' && Array.isArray(cmd.cells)) {
      cmd.cells.forEach((cell: any) => window.KotoSheetsAPI.setCellValue(cell.r, cell.c, cell.value));
      (window as any).showToast(`AI 已批量更新 ${cmd.cells.length} 个单元格`, 'success');
      (window as any).WA.scheduleAutoSave();
    }
  }

  destroy() {
    if (window.KotoSheetsAPI) {
      try { window.KotoSheetsAPI.dispose(); } catch (e) {}
    }
    this._api = null;
    const sheetEl = $(this._containerId);
    if (sheetEl) {
      sheetEl.style.zoom = '';
      sheetEl.style.width = '';
      sheetEl.style.height = '';
      delete (sheetEl as any).dataset.dpiZoom;
    }
    const wrapper = $(this.containerId);
    if (wrapper) {
      wrapper.classList.remove('active');
    }
  }
}

(window as any).KotoXlsxEditor = KotoXlsxEditor;
