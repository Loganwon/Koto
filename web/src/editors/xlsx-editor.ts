/**
 * KotoXlsxEditor - Univer spreadsheet editor wrapper
 */

import type { WorkspaceEditor } from './types';

declare global {
  var KotoSheetsAPI: any;
}

function $(id: string): HTMLElement | null { return document.getElementById(id); }

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
          const text = window.KotoSheetsAPI.getSelectionText();
          if (text) {
            (window as any).lastSelectionText = `[当前选中表格数据]:\n${text}\n`;
            if (typeof (window as any)._pinSelectionChip === 'function') {
              (window as any)._pinSelectionChip((window as any).lastSelectionText);
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
    if (!window.KotoSheetsAPI || !window.KotoSheetsAPI.isReady()) return '';
    const text = window.KotoSheetsAPI.getSelectionText();
    if (text && text.trim()) return `[当前选中表格数据]:\n${text}\n`;
    return '[当前表格未选中区域，请提示用户框选数据]';
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
