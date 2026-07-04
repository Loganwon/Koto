// ─── CSS imports (order locked: design → ui → docs-ui → sheets-ui → formula-ui → custom)
import '@univerjs/design/lib/index.css';
import '@univerjs/ui/lib/index.css';
import '@univerjs/docs-ui/lib/index.css';
import '@univerjs/sheets-ui/lib/index.css';
import '@univerjs/sheets-formula-ui/lib/index.css';

// ─── Core
import { Univer, UniverInstanceType, LocaleType, FUniver } from '@univerjs/core';
import { defaultTheme } from '@univerjs/design';
import { UniverRenderEnginePlugin } from '@univerjs/engine-render';
import { UniverFormulaEnginePlugin } from '@univerjs/engine-formula';
import { UniverUIPlugin } from '@univerjs/ui';
import { UniverDocsPlugin } from '@univerjs/docs';
import { UniverDocsUIPlugin } from '@univerjs/docs-ui';
import { UniverSheetsPlugin } from '@univerjs/sheets';
import { UniverSheetsUIPlugin } from '@univerjs/sheets-ui';
import { UniverSheetsFormulaPlugin } from '@univerjs/sheets-formula';
import { UniverSheetsFormulaUIPlugin } from '@univerjs/sheets-formula-ui';
import '@univerjs/ui/facade';
import '@univerjs/docs-ui/facade';
import '@univerjs/sheets/facade';
import '@univerjs/sheets-ui/facade';
import '@univerjs/sheets-formula/facade';

// ─── Locales
import DesignZhCN from '@univerjs/design/locale/zh-CN';
import UIZhCN from '@univerjs/ui/locale/zh-CN';
import DocsUIZhCN from '@univerjs/docs-ui/locale/zh-CN';
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
   * @param {string|HTMLElement} containerOrId  DOM element id string OR the element itself
   * @param {object} workbookData IWorkbookData snapshot (Univer format)
   */
  create(containerOrId, workbookData) {
    this.dispose();

    // Resolve to an actual HTMLElement — we MUST pass the element (not a string)
    // to UniverUIPlugin because its internal getElementById lookup can silently
    // fail in pywebview/WebView2, causing it to create a *detached* div and
    // render into that (invisible to the user).
    let el;
    if (typeof containerOrId === 'string') {
      el = document.getElementById(containerOrId);
      if (!el) {
        console.error('[KotoSheets] 容器元素未找到:', containerOrId);
        throw new Error(`Univer 容器元素 #${containerOrId} 不在 DOM 中`);
      }
    } else if (containerOrId instanceof HTMLElement) {
      el = containerOrId;
    } else {
      throw new Error('create() 需要 string 或 HTMLElement 参数');
    }

    const rect = el.getBoundingClientRect();
    console.log('[KotoSheets] 容器:', el.id || '(no id)', 'rect=', rect.width.toFixed(0) + 'x' + rect.height.toFixed(0));

    const univer = new Univer({
      theme: defaultTheme,
      locale: LocaleType.ZH_CN,
      locales: {
        [LocaleType.ZH_CN]: {
          ...DesignZhCN,
          ...UIZhCN,
          ...DocsUIZhCN,
          ...SheetsZhCN,
          ...SheetsUIZhCN,
          ...SheetsFormulaZhCN,
          ...SheetsFormulaUIZhCN,
        },
      },
    });

    univer.registerPlugin(UniverRenderEnginePlugin);
    univer.registerPlugin(UniverFormulaEnginePlugin);
    // Pass the *actual element* — not a string — to avoid Univer's fallback to
    // a detached div when its internal getElementById fails.
    univer.registerPlugin(UniverUIPlugin, { container: el });
    univer.registerPlugin(UniverDocsPlugin);
    univer.registerPlugin(UniverDocsUIPlugin);
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

    // Coordinate debug: log offsetX/Y and resulting cell on click
    setTimeout(() => {
      const canvases = el.querySelectorAll('canvas');
      console.log('[KotoSheets] canvas count:', canvases.length);
      canvases.forEach((c, idx) => {
        const r = c.getBoundingClientRect();
        console.log(`[KotoSheets] canvas[${idx}] rect: ${r.left.toFixed(1)},${r.top.toFixed(1)} size: ${r.width.toFixed(0)}x${r.height.toFixed(0)} cssSize: ${c.style.width}x${c.style.height} bufferSize: ${c.width}x${c.height}`);
      });
      const mainCanvas = canvases[canvases.length - 1];
      if (mainCanvas) {
        mainCanvas.addEventListener('pointerdown', (e) => {
          const rect = mainCanvas.getBoundingClientRect();
          console.log(`[KotoSheets] click: clientX=${e.clientX.toFixed(1)},clientY=${e.clientY.toFixed(1)} offsetX=${e.offsetX.toFixed(1)},offsetY=${e.offsetY.toFixed(1)} canvasRect=${rect.left.toFixed(1)},${rect.top.toFixed(1)} computed=(${(e.clientX-rect.left).toFixed(1)},${(e.clientY-rect.top).toFixed(1)}) dpr=${window.devicePixelRatio}`);
        }, true);
      }
    }, 1000);

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

  /**
   * Convert a raw value from FRange.getValues() to a display string.
   * FRange.getValues() returns o.v directly (primitive: string|number|boolean|null),
   * NOT an ICellData object. Accessing .v on a primitive returns undefined.
   */
  _cellToStr(cell) {
    if (cell === null || cell === undefined) return '';
    if (typeof cell === 'object') return String(cell.v ?? '');  // safety for ICellData
    return String(cell);  // primitive: number, string, boolean
  }

  _valuesToTsv(values) {
    return (Array.isArray(values) ? values : [])
      .map(row => (Array.isArray(row) ? row : []).map(c => this._cellToStr(c)).join('\t'))
      .join('\n');
  }

  _activeRange() {
    try {
      const wb = this._api.getActiveWorkbook();
      if (!wb) return null;
      const sheet = wb.getActiveSheet();
      if (!sheet) return null;

      // Strategy 1: sheet.getActiveRange() — uses primary-flagged selection (standard drag-select)
      let range = null;
      if (typeof sheet.getActiveRange === 'function') {
        try { range = sheet.getActiveRange(); } catch (_) {}
      }

      // Strategy 2: FSelection.getActiveRangeList() — all selections even without primary flag
      if (!range && typeof sheet.getSelection === 'function') {
        try {
          const sel = sheet.getSelection();
          if (sel) {
            if (typeof sel.getActiveRangeList === 'function') {
              const list = sel.getActiveRangeList();
              if (list && list.length > 0) range = list[0];
            } else if (typeof sel.getActiveRange === 'function') {
              range = sel.getActiveRange();
            }
          }
        } catch (_) {}
      }

      return range;
    } catch (e) {
      console.warn('[KotoSheets] active range error', e);
      return null;
    }
  }

  /** Get current selection with address metadata and TSV text. */
  getSelectionPayload() {
    try {
      const range = this._activeRange();
      if (!range) return null;
      const values = range.getValues();
      if (!values || values.length === 0) return null;

      const tsv = this._valuesToTsv(values);
      if (!tsv.replace(/\t/g, '').trim()) return null;

      let sheetName = '';
      let rangeA1 = '';
      try { sheetName = typeof range.getSheetName === 'function' ? range.getSheetName() : ''; } catch (_) {}
      try { rangeA1 = typeof range.getA1Notation === 'function' ? range.getA1Notation() : ''; } catch (_) {}

      const rows = Array.isArray(values) ? values.length : 0;
      const cols = values.reduce((max, row) => Math.max(max, Array.isArray(row) ? row.length : 0), 0);
      const location = [sheetName, rangeA1].filter(Boolean).join('!');
      const sizeLabel = rows > 0 && cols > 0 ? `${rows}行×${cols}列` : '';
      const previewText = [location, sizeLabel].filter(Boolean).join(' · ') || '选中表格区域';
      const aiText =
        `[当前选中表格区域${location ? `: ${location}` : ''}${sizeLabel ? `, ${sizeLabel}` : ''}]\n` +
        `数据格式: TSV（制表符分隔，换行分隔行）\n` +
        `${tsv}\n`;

      console.log(`[KotoSheets] getSelectionPayload: ${rows} rows x ${cols} cols, notation=${rangeA1 || '?'}`);
      return {
        kind: 'xlsx-range',
        sheetName,
        rangeA1,
        rows,
        cols,
        values,
        tsv,
        aiText,
        previewText,
      };
    } catch (e) {
      console.warn('[KotoSheets] getSelectionPayload error', e);
      return null;
    }
  }

  /** Get current selection as tab-separated text. Returns null if nothing is selected or data is empty. */
  getSelectionText() {
    try {
      const payload = this.getSelectionPayload();
      return payload ? payload.tsv : null;
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
      // getValues() returns raw CellValue primitives (NOT ICellData with .v)
      return values
        .filter(row => row.some(c => c !== null && c !== undefined && c !== ''))
        .map(row => row.map(cell => {
          const v = this._cellToStr(cell);
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
