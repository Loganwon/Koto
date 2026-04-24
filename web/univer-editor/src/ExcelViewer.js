// ══════════════════════════════════════════════════════════════
// ExcelViewer.js — Univer Sheets Excel 查看器 (文件助手集成版)
//
// 动态加载预编译的 sheets-main.js，在中心区容器内渲染 Excel 数据。
// 数据来源于 doc.sheetsData（IWorkbookData 格式）。
// ══════════════════════════════════════════════════════════════

export class ExcelViewer {
  /**
   * @param {string} centerId  中央区容器 DOM id (如 'center-doc')
   */
  constructor(centerId) {
    this._center = document.getElementById(centerId);
    this._host = null;
    this._sheetsContainer = null;
    this._warningBar = null;

    this._sheetsData = null;
    this._docId = null;
    this._active = false;
    this._sheetsLoaded = false;  // sheets-main.js 脚本是否已注入

    this._buildDOM();
  }

  // ─── DOM 构建 ──────────────────────────────────────────────

  _buildDOM() {
    this._host = document.createElement('div');
    this._host.id = 'excel-view-host';

    // 可选的警告条（含公式提示）
    this._warningBar = document.createElement('div');
    this._warningBar.id = 'excel-warning-bar';
    this._warningBar.style.display = 'none';

    // Univer Sheets 挂载容器
    this._sheetsContainer = document.createElement('div');
    this._sheetsContainer.id = 'koto-sheets-container';

    this._host.appendChild(this._warningBar);
    this._host.appendChild(this._sheetsContainer);
    this._center.appendChild(this._host);
  }

  // ─── 公共 API ──────────────────────────────────────────────

  /**
   * 渲染 Excel 数据。
   * @param {object} sheetsData  IWorkbookData (parse_xlsx 输出)
   * @param {string} docId       文档 ID
   */
  async render(sheetsData, docId) {
    this._sheetsData = sheetsData;
    this._docId = docId;
    this.show();
    await this._ensureSheets();

    const warnings = (sheetsData._warnings || []);
    if (warnings.length) {
      this._warningBar.textContent = '⚠ ' + warnings[0];
      this._warningBar.style.display = 'block';
    } else {
      this._warningBar.style.display = 'none';
    }

    if (window.KotoSheetsAPI) {
      try {
        window.KotoSheetsAPI.create(this._sheetsContainer, sheetsData);
      } catch (e) {
        console.error('[ExcelViewer] KotoSheetsAPI.create failed:', e);
        this._sheetsContainer.innerHTML =
          `<div style="padding:20px;color:#c00">⚠ 表格加载失败: ${e.message}</div>`;
      }
    } else {
      this._sheetsContainer.innerHTML =
        '<div style="padding:20px;color:#888">⚠ Univer Sheets 引擎未就绪</div>';
    }
  }

  show() {
    if (this._active) return;
    this._active = true;
    this._host.style.display = 'flex';
    // 隐藏 Univer Docs 画布
    const univerContainer = document.getElementById('univer-container');
    if (univerContainer) univerContainer.style.display = 'none';
    // 隐藏其他查看器
    const docxHost = document.getElementById('docx-view-host');
    if (docxHost) docxHost.style.display = 'none';
    const pptxHost = document.getElementById('pptx-view-host');
    if (pptxHost) pptxHost.style.display = 'none';
    // 隐藏浮动工具栏
    const ft = window.__koto && window.__koto.floatingToolbar;
    if (ft && ft._toolbar) ft._toolbar.classList.add('hidden');
  }

  hide() {
    if (!this._active) return;
    this._active = false;
    this._host.style.display = 'none';
    // 销毁 Univer Sheets 实例（释放内存 + 避免多实例冲突）
    if (window.KotoSheetsAPI && window.KotoSheetsAPI.isReady()) {
      window.KotoSheetsAPI.dispose();
    }
  }

  isActive() { return this._active; }

  /** Get selected cell range text from Univer Sheets (tab-separated). Returns null if no selection or Sheets not ready. */
  getSelectionText() {
    if (!window.KotoSheetsAPI || !window.KotoSheetsAPI.isReady()) return null;
    return window.KotoSheetsAPI.getSelectionText() || null;
  }

  /** Extract plain text from all sheets (used by AIPanel / FloatingToolbar for context injection). */
  getFullText() {
    if (!this._sheetsData || !this._sheetsData.sheets) return '';
    const order = this._sheetsData.sheetOrder || Object.keys(this._sheetsData.sheets);
    return order.map(id => {
      const sheet = this._sheetsData.sheets[id];
      if (!sheet) return '';
      const rows = sheet.cellData || {};
      const lines = Object.entries(rows)
        .sort(([a], [b]) => Number(a) - Number(b))
        .map(([, cols]) => Object.entries(cols)
          .sort(([a], [b]) => Number(a) - Number(b))
          .map(([, c]) => c && c.v !== undefined ? String(c.v) : '')
          .join('\t'))
        .filter(l => l.trim());
      return `[${sheet.name || id}]\n` + lines.join('\n');
    }).filter(t => t.trim()).join('\n\n');
  }

  setCellValue(r, c, value) {
    if (!window.KotoSheetsAPI || !window.KotoSheetsAPI.isReady()) return false;
    window.KotoSheetsAPI.setCellValue(Number(r) || 0, Number(c) || 0, value ?? '');
    return true;
  }

  setCells(cells = []) {
    let applied = false;
    cells.forEach((cell) => {
      if (!cell || typeof cell !== 'object') return;
      applied = this.setCellValue(cell.r, cell.c, cell.value) || applied;
    });
    return applied;
  }

  // ─── 动态加载 sheets-main.js ───────────────────────────────

  _ensureSheets() {
    // 若 KotoSheetsAPI 已存在（之前已加载），直接返回已完成的 Promise
    if (window.KotoSheetsAPI) {
      this._sheetsLoaded = true;
      return Promise.resolve();
    }
    if (this._sheetsLoaded) {
      // 脚本已注入但 API 尚未就绪，等待一下
      return new Promise(resolve => setTimeout(resolve, 300));
    }

    return new Promise((resolve, reject) => {
      // 注入 CSS（如果还没有）
      if (!document.querySelector('link[href*="sheets-main.css"]')) {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = '/editor/assets/sheets-main.css';
        document.head.appendChild(link);
      }

      const script = document.createElement('script');
      script.type = 'module';
      script.src = '/editor/assets/sheets-main.js';
      script.onload = () => {
        this._sheetsLoaded = true;
        // 等待模块内部赋值完成（模块顶层代码异步执行）
        let tries = 0;
        const poll = setInterval(() => {
          tries++;
          if (window.KotoSheetsAPI) {
            clearInterval(poll);
            resolve();
          } else if (tries > 40) {
            clearInterval(poll);
            reject(new Error('KotoSheetsAPI 加载超时'));
          }
        }, 100);
      };
      script.onerror = () => reject(new Error('sheets-main.js 加载失败'));
      document.head.appendChild(script);
    });
  }
}
