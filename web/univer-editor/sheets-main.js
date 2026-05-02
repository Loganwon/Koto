// ─── CSS imports (order locked: design → ui → sheets-ui → formula-ui → custom)
import '@univerjs/design/lib/index.css';
import '@univerjs/ui/lib/index.css';
import '@univerjs/sheets-ui/lib/index.css';
import '@univerjs/sheets-formula-ui/lib/index.css';

// ─── Core
import { Univer, UniverInstanceType, LocaleType, FUniver } from '@univerjs/core';
import { defaultTheme } from '@univerjs/design';
import { UniverRenderEnginePlugin } from '@univerjs/engine-render';
import { UniverFormulaEnginePlugin } from '@univerjs/engine-formula';
import { UniverUIPlugin } from '@univerjs/ui';
import { UniverSheetsPlugin } from '@univerjs/sheets';
import { UniverSheetsUIPlugin } from '@univerjs/sheets-ui';
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula';
import { UniverSheetsFormulaUIPlugin } from '@univerjs/sheets-formula-ui';
import '@univerjs/ui/facade';
import '@univerjs/sheets/facade';
import '@univerjs/sheets-ui/facade';
import '@univerjs/sheets-formula/facade';

// ─── Locales
import DesignZhCN from '@univerjs/design/locale/zh-CN';
import UIZhCN from '@univerjs/ui/locale/zh-CN';
import SheetsZhCN from '@univerjs/sheets/locale/zh-CN';
import SheetsUIZhCN from '@univerjs/sheets-ui/locale/zh-CN';
import SheetsFormulaZhCN from '@univerjs/sheets-formula/locale/zh-CN';
import SheetsFormulaUIZhCN from '@univerjs/sheets-formula-ui/locale/zh-CN';

// ─── KotoSheetsAPI ───────────────────────────────────────────────────────────
/**
 * Manages a single Univer Sheets instance inside a given DOM container.
 * Designed to be created fresh for each file open and disposed on close.
 */
class KotoSheetsAPIClass {
  constructor() {
    this._univer = null;
    this._api = null;
    this._disposed = true;
  }

  /**
   * Create and mount a Univer Sheets instance.
   * @param {string|HTMLElement} containerOrEl  DOM element id OR the element itself
   * @param {object} workbookData IWorkbookData snapshot (Univer format)
   */
  create(containerOrEl, workbookData) {
    this.dispose();

    // Resolve to HTMLElement immediately so Univer never falls back to a detached div.
    // Passing an HTMLElement (instead of a string ID) bypasses Univer's internal
    // document.getElementById() lookup that can fail during async module init.
    let container = containerOrEl;
    if (typeof containerOrEl === 'string') {
      const el = document.getElementById(containerOrEl);
      if (!el) {
        console.error('[KotoSheets] 容器元素未找到:', containerOrEl);
        throw new Error(`Univer 容器元素 #${containerOrEl} 不在 DOM 中`);
      }
      // Verify container has non-zero dimensions
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) {
        console.warn('[KotoSheets] 容器尺寸为零, rect=', rect, 'offsetWidth=', el.offsetWidth, 'offsetHeight=', el.offsetHeight);
      }
      container = el;
      console.log('[KotoSheets] 容器元素找到:', containerOrEl, 'rect=', rect.width.toFixed(0) + 'x' + rect.height.toFixed(0));
    }

    const univer = new Univer({
      theme: defaultTheme,
      locale: LocaleType.ZH_CN,
      locales: {
        [LocaleType.ZH_CN]: {
          ...DesignZhCN,
          ...UIZhCN,
          ...SheetsZhCN,
          ...SheetsUIZhCN,
          ...SheetsFormulaZhCN,
          ...SheetsFormulaUIZhCN,
        },
      },
    });

    univer.registerPlugin(UniverRenderEnginePlugin);
    univer.registerPlugin(UniverFormulaEnginePlugin);
    univer.registerPlugin(UniverUIPlugin, { container });
    univer.registerPlugin(UniverSheetsPlugin);
    univer.registerPlugin(UniverSheetsUIPlugin);
    univer.registerPlugin(UniverSheetsFormulaPlugin);
    univer.registerPlugin(UniverSheetsFormulaUIPlugin);

    // Use univer.createUnit directly — api.createUniverSheet is deprecated in v0.5.x
    univer.createUnit(UniverInstanceType.UNIVER_SHEET, workbookData);

    const api = FUniver.newAPI(univer);

    this._univer = univer;
    this._api = api;
    this._disposed = false;

    console.log('[KotoSheets] Univer Sheets 引擎初始化完成');
    return api;
  }

  dispose() {
    if (this._univer && !this._disposed) {
      try { this._univer.dispose(); } catch (e) {
        console.warn('[KotoSheets] dispose error', e);
      }
    }
    this._univer = null;
    this._api = null;
    this._disposed = true;
  }

  isReady() {
    return !this._disposed && this._api !== null;
  }

  // ── Read operations ────────────────────────────────────────────────────────

  /** Get current selection as tab-separated text. Returns null if no selection. */
  getSelectionText() {
    try {
      const wb = this._api.getActiveWorkbook();
      if (!wb) return null;
      const sheet = wb.getActiveSheet();
      if (!sheet) return null;
      const sel = sheet.getSelection();
      if (!sel) return null;
      const range = sel.getCurrentCell
        ? sel.getCurrentCell()
        : (sel.getActiveRange ? sel.getActiveRange() : null);
      if (!range) return null;
      const values = range.getValues();
      if (!values || values.length === 0) return null;
      return values
        .map(row => row.map(cell => (cell ? (cell.v ?? '') : '')).join('\t'))
        .join('\n');
    } catch (e) {
      console.warn('[KotoSheets] getSelectionText error', e);
      return null;
    }
  }

  /** Export all data from the active sheet as CSV. */
  getActiveSheetCSV() {
    try {
      const wb = this._api.getActiveWorkbook();
      if (!wb) return '';
      const sheet = wb.getActiveSheet();
      if (!sheet) return '';
      const maxRow = sheet.getMaxRows();
      const maxCol = sheet.getMaxColumns();
      if (!maxRow || !maxCol) return '';
      const values = sheet.getRange(0, 0, maxRow, maxCol).getValues();
      return values
        .filter(row => row.some(c => c && c.v !== null && c.v !== undefined && c.v !== ''))
        .map(row => row.map(cell => {
          const v = String(cell ? (cell.v ?? '') : '');
          return v.includes(',') ? `"${v}"` : v;
        }).join(','))
        .join('\n');
    } catch (e) {
      console.warn('[KotoSheets] getActiveSheetCSV error', e);
      return '';
    }
  }

  // ── Write operations ───────────────────────────────────────────────────────

  setCellValue(r, c, value) {
    try {
      const wb = this._api.getActiveWorkbook();
      if (!wb) return;
      const sheet = wb.getActiveSheet();
      if (!sheet) return;
      sheet.getRange(r, c, 1, 1).setValue(value);
    } catch (e) {
      console.warn('[KotoSheets] setCellValue error', e);
    }
  }

  // ── Snapshot ───────────────────────────────────────────────────────────────

  /** Returns current IWorkbookData snapshot for tab cache. */
  getSnapshot() {
    try {
      const wb = this._api.getActiveWorkbook();
      return wb ? wb.save() : null;
    } catch (e) {
      console.warn('[KotoSheets] getSnapshot error', e);
      return null;
    }
  }

  // ── Selection event ────────────────────────────────────────────────────────

  /** Register a callback fired when selection changes. */
  onSelectionChange(handler) {
    try {
      if (this._api && this._api.getActiveWorkbook) {
        const wb = this._api.getActiveWorkbook();
        if (wb && wb.onSelectionChange) {
          wb.onSelectionChange(handler);
        }
      }
    } catch (e) {
      // Selection event API may vary across Univer versions
    }
  }
}

window.KotoSheetsAPI = new KotoSheetsAPIClass();
console.log('[KotoSheets] Module ready. window.KotoSheetsAPI available.');
